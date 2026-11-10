"""Rule-based interpretation engine (3.4, replaces the Gemini text).

Each test feeds numbers whose interpretation is known and checks the level and
topic of the finding the rule must produce, plus the arithmetic the rules use."""
import math
import pathlib
import re

import numpy as np
import pandas as pd
import pytest

from scripts.common import interpret as I


def levels(rep):
    return {f.topic: f.level for f in rep.findings}


# --------------------------------------------------------------- J-V and fill factor
def test_green_ff0_matches_the_closed_form():
    # FF0 = (v - ln(v + 0.72)) / (v + 1), Green, Solid-State Electron. 24, 788 (1981)
    v = 40.0
    assert I.ff_from_voc(v) == pytest.approx((v - math.log(v + 0.72)) / (v + 1))


def test_ff_loss_breakdown_adds_up_to_the_measured_ff():
    b = I.ff_loss_breakdown(1.10, 23.0, 75.0, n=1.5, rs=3.0, rsh=800)
    assert b["FF0"] > b["FFs"] > b["FFsh"]
    total = b["loss_recombination"] + b["loss_series"] + b["loss_shunt"] + b["loss_unexplained"]
    assert b["FF_ideal"] - total == pytest.approx(b["FF_measured"], abs=1e-9)


def test_ff_loss_without_resistances_is_only_recombination():
    b = I.ff_loss_breakdown(1.10, 23.0, 80.0, n=1.0, rs=0.0, rsh=float("inf"))
    assert b["loss_series"] == pytest.approx(0.0, abs=1e-9)
    assert b["loss_shunt"] == pytest.approx(0.0, abs=1e-6)


def test_poor_cell_raises_resistance_ideality_and_hysteresis_problems():
    rep = I.interpret_jv({"Voc": 1.10, "Jsc": -23.0, "FF": 62.0, "PCE": 15.7, "Rs": 8.0, "Rsh": 300},
                         fit={"n": 2.3, "J0": 1e-9, "Rs": 7.5, "Rsh": 310, "R2": 0.999}, hysteresis_index=18)
    lv = levels(rep)
    for topic in ("Series resistance", "Shunt resistance", "Ideality factor", "Hysteresis"):
        assert lv[topic] == "problem"
    assert rep.sorted()[0].level == "problem"
    assert "Main point" in rep.summary()


def test_good_cell_is_all_in_range():
    rep = I.interpret_jv({"Voc": 1.15, "Jsc": 24.5, "FF": 82.0, "PCE": 23.1, "Rs": 1.0, "Rsh": 5000},
                         fit={"n": 1.3, "R2": 0.9995}, hysteresis_index=2)
    assert set(levels(rep).values()) == {"good"}
    assert "within the expected ranges" in rep.summary()


# --------------------------------------------------------------- statistics
def test_modified_z_score_flags_the_outlier():
    assert I.robust_outliers([1.0, 1.1, 0.9, 1.05, 0.95, 5.0]) == [5]
    assert I.robust_outliers([1.0, 1.0, 1.0]) == []


def test_hedges_g_and_holm():
    # pooled sd of [1..4] and [3..6] is 1.29; d = -1.549, small-sample factor 1 - 3/(4*6-1)
    assert I.hedges_g([1, 2, 3, 4], [3, 4, 5, 6]) == pytest.approx(-1.549 * (1 - 3 / 23), rel=1e-3)
    adj = I.holm([0.01, 0.04, 0.03])
    assert adj == pytest.approx([0.03, 0.06, 0.06])
    assert all(0 <= p <= 1 for p in adj)


def test_statistics_finds_the_significant_improvement():
    rep = I.interpret_statistics({"Ref": {"PCE": [18, 18.5, 17.9, 18.2, 18.1]},
                                  "Pass": {"PCE": [20, 20.4, 19.8, 20.1, 20.3]}}, reference="Ref")
    f = next(f for f in rep.findings if f.topic == "Pass vs Ref: PCE")
    assert f.level == "good" and "p" in f.evidence


# --------------------------------------------------------------- dark J-V
def test_dark_ideality_above_two_is_a_warning():
    rep = I.interpret_dark({"Ideality n": 2.4, "J0": 1e-6})
    assert levels(rep)["Ideality factor (dark)"] == "warning"
    rep = I.interpret_dark({"Ideality n": 1.3})
    assert levels(rep)["Ideality factor (dark)"] == "good"


# --------------------------------------------------------------- EQE
def test_spectral_losses_vanish_for_unit_eqe_and_grow_with_gaps():
    wl = np.arange(300, 851, 5.0)
    full = I.spectral_losses(wl, np.where(wl < 800, 1.0, 0.0), 1.55)
    assert all(v == pytest.approx(0.0, abs=1e-9) for v in full.values())
    part = I.spectral_losses(wl, np.where(wl < 800, 0.85, 0.0), 1.55)
    assert max(part, key=part.get) == "the middle of the spectrum"     # most photons sit there
    assert all(v > 0 for v in part.values())


def test_broad_urbach_tail_is_a_warning():
    rep = I.interpret_eqe({"Eu_meV": 35.0})
    assert levels(rep)["Urbach energy"] == "warning"
    assert levels(I.interpret_eqe({"Eu_meV": 15.0}))["Urbach energy"] == "good"


# --------------------------------------------------------------- absorbance
def test_tauc_prefers_the_other_transition_when_it_fits_better():
    rep = I.interpret_absorbance({"Eg": 1.6, "R2": 0.97, "mode": "direct"}, other_mode_r2=0.995)
    assert levels(rep)["Transition type"] == "warning"


# --------------------------------------------------------------- PL
def test_pl_quenching_shift_stokes_and_width():
    rows = [{"Sample": "ref", "Peak (eV)": 1.60, "FWHM (meV)": 95},
            {"Sample": "HTL", "Peak (eV)": 1.585, "FWHM (meV)": 140, "Quench eta (integral)": 93}]
    lv = levels(I.interpret_pl(rows, reference="ref", eg_ev=1.70))
    assert lv["Quenching - HTL"] == "good"
    assert lv["Line width - HTL"] == "warning" and lv["Line width - ref"] == "good"
    assert lv["Peak shift - HTL"] == "note"          # -15 meV
    assert lv["Stokes shift - ref"] == "warning"     # 100 meV below Eg


# --------------------------------------------------------------- XRD
def test_xrd_negative_strain_low_coverage_and_pbi2():
    rep = I.interpret_xrd([{"2Theta": 14.0, "FWHM": 0.1, "Crystallite_nm": 80}],
                          wh={"D_nm": 60, "strain": -1e-4, "R2": 0.8},
                          match={"coverage": 0.4, "unassigned": [{"2Theta": 12.7}], "n_matched": 2,
                                 "n_reference_lines": 5})
    lv = levels(rep)
    assert lv["Williamson-Hall"] == "warning" and lv["Phase identification"] == "warning"
    un = next(f for f in rep.findings if f.topic == "Unassigned reflection")
    assert un.level == "warning" and "PbI2" in un.text


def test_williamson_hall_recovers_size_and_strain():
    k, lam, d_nm, eps = 0.9, I.CU_KA1_NM, 50.0, 2e-3
    tt = np.array([14.0, 20.0, 28.4, 31.9, 40.6, 43.2])
    th = np.radians(tt / 2)
    beta = np.degrees((k * lam / d_nm + 4 * eps * np.sin(th)) / np.cos(th))
    wh = I._wh_fit(tt, beta, lam, k)
    assert wh["D_nm"] == pytest.approx(d_nm, rel=1e-6)
    assert wh["strain"] == pytest.approx(eps, rel=1e-6)
    assert wh["R2"] == pytest.approx(1.0)


# --------------------------------------------------------------- SEM
def test_sem_bimodal_distribution_is_detected():
    rng = np.random.default_rng(1)
    d = np.r_[rng.normal(200, 20, 150), rng.normal(600, 40, 150)]
    assert levels(I.interpret_sem(d))["Bimodality"] == "warning"
    uni = rng.lognormal(np.log(300), 0.15, 300)
    assert "Bimodality" not in levels(I.interpret_sem(uni))


# --------------------------------------------------------------- FTIR / Raman
def test_ftir_functional_groups():
    topics = levels(I.interpret_vibrational("FTIR", [3400, 1650]))
    assert "O-H stretch" in topics


# --------------------------------------------------------------- XPS
def test_xps_metallic_lead_doublet_and_stoichiometry():
    comps = [{"center": 136.9, "area": 60, "fwhm": 1.1}, {"center": 138.6, "area": 1000, "fwhm": 1.2},
             {"center": 143.47, "area": 750, "fwhm": 1.2}]
    lv = levels(I.interpret_xps(comps, atomic={"I": 40, "Pb": 16, "C": 45}))
    assert lv["Metallic lead"] == "warning"
    assert lv["Spin-orbit doublet"] == "good"        # 0.75 ratio
    assert lv["Stoichiometry"] == "warning"          # I/Pb = 2.5
    assert lv["Surface carbon"] == "note"


# --------------------------------------------------------------- device summary
def test_device_jsc_mismatch_levels():
    assert levels(I.interpret_device({"Jsc_mismatch_percent": 12.0}))["Jsc cross-check"] == "problem"
    assert levels(I.interpret_device({"Jsc_mismatch_percent": 3.0}))["Jsc cross-check"] == "good"


# --------------------------------------------------------------- auto-fit peak tables
def test_peak_fit_detection_limits_and_resolution():
    df = pd.DataFrame({"center": [10.0, 10.3, 20.0], "height": [5, 300, 50], "fwhm": [0.5, 0.5, 0.5],
                       "snr": [2.0, 120.0, 6.0]})
    lv = levels(I.interpret_peak_fit("GEN", df))
    assert lv["Detection limit"] == "warning" and lv["Quantification limit"] == "note"
    assert lv["Unresolved peaks"] == "note"          # 0.3 apart, mean FWHM 0.5


def test_peak_fit_residual_against_noise():
    df = pd.DataFrame({"center": [5.0], "height": [100.0], "fwhm": [1.0], "snr": [50.0], "noise_sigma": [2.0],
                       "redchi": [40.0], "region_xmin": [3.0]})
    assert levels(I.interpret_peak_fit("GEN", df))["Fit residual"] == "warning"   # 40 / 4 = 10 > 4
    df["redchi"] = 4.4
    assert "Fit residual" not in levels(I.interpret_peak_fit("GEN", df))


def test_peak_fit_xps_charge_reference_and_pl_units():
    c1s = pd.DataFrame({"center": [285.6, 287.0, 289.2], "height": [900, 200, 80], "fwhm": [1.3, 1.4, 1.5],
                        "area_amplitude": [1000, 250, 90]})
    f = next(f for f in I.interpret_peak_fit("XPS", c1s).findings if f.topic == "Charge reference")
    assert "-0.80 eV" in f.text
    pl = pd.DataFrame({"center": [780.0], "height": [1.0], "fwhm_x": [45.0]})
    w = next(f for f in I.interpret_peak_fit("PL", pl).findings if f.topic.startswith("Line width"))
    # 45 nm at 780 nm = 1239.84 * 45 / 780^2 eV = 91.7 meV
    assert "92 meV" in w.text


def test_empty_fit_is_a_warning_not_an_error():
    assert levels(I.interpret_peak_fit("XRD", pd.DataFrame()))["No peaks"] == "warning"


# --------------------------------------------------------------- report object
def test_report_is_deterministic_and_carries_the_evidence():
    args = ({"Voc": 1.10, "Jsc": -23.0, "FF": 62.0, "PCE": 15.7, "Rs": 8.0, "Rsh": 300},)
    a, b = I.interpret_jv(*args).to_markdown(), I.interpret_jv(*args).to_markdown()
    assert a == b
    assert "Series resistance" in a and "Ω cm²" in a and "Evidence" in a


def test_no_source_module_imports_an_llm_sdk():
    root = pathlib.Path(__file__).resolve().parents[1]
    pat = re.compile(r"^\s*(import|from)\s+google\.(generativeai|genai)", re.M)
    hits = [str(p.relative_to(root)) for d in ("scripts", "spectra") for p in (root / d).rglob("*.py")
            if pat.search(p.read_text(encoding="utf-8", errors="ignore"))]
    hits += [n for n in ("Physiscore_Launcher.py", "physiscore_cli.py")
             if pat.search((root / n).read_text(encoding="utf-8"))]
    assert hits == []
    req = (root / "requirements.txt").read_text(encoding="utf-8")
    assert "generativeai" not in req
