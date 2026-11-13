"""PLQY from integrating-sphere spectra (de Mello) and the quasi-Fermi-level
splitting it implies (3.7). The spectra are made by `simulate_sphere`, whose
B and C measurements follow the light paths de Mello et al. describe, so the
true PLQY and absorptance are known."""
import math

import numpy as np
import pandas as pd
import pytest

from scripts.EQE import eqe_core
from scripts.PLQY import plqy_core as c
from scripts.common import curve_batch as cb
from scripts.common import curve_io, interpret_transport

KT = c.KB_EV * 300.0


def sphere(**kw):
    d = c.simulate_sphere(**kw)
    return c.analyse_sphere(d["wl"], d["a"], d["c"], d["b"])


# ------------------------------------------------------------------ de Mello
@pytest.mark.parametrize("plqy,absorb,indirect", [(0.05, 0.8, 0.15), (0.6, 0.3, 0.05), (0.002, 0.95, 0.3),
                                                   (0.2, 0.15, 0.0)])
def test_three_measurements_recover_plqy_and_absorptance(plqy, absorb, indirect):
    r = sphere(plqy=plqy, absorptance=absorb, indirect=indirect, noise=False)
    s = r["sphere"]
    assert s["method"] == "three"
    assert s["absorptance"] == pytest.approx(absorb, abs=1e-6)
    assert r["PLQY_ref"] == pytest.approx(plqy, rel=2e-3)


def test_two_measurements_lump_indirect_absorption_into_the_absorptance():
    """Without B the scattered light the sample absorbs counts as direct absorption:
    the absorptance is A + mu (1 - A); the PLQY of a sample with one emission
    spectrum is still right (the extra emission and absorption cancel)."""
    d = c.simulate_sphere(plqy=0.05, absorptance=0.8, indirect=0.15, noise=False)
    r = c.analyse_sphere(d["wl"], d["a"], d["c"], None)
    assert r["sphere"]["method"] == "two"
    assert r["sphere"]["absorptance"] == pytest.approx(0.8 + 0.15 * 0.2, abs=1e-6)
    assert r["PLQY_ref"] == pytest.approx(0.05, rel=2e-3)


def test_energy_spectra_are_converted_to_photons():
    d = c.simulate_sphere(plqy=0.05, noise=False, units="energy")
    as_energy = c.analyse_sphere(d["wl"], d["a"], d["c"], d["b"], units="energy")
    as_photons = c.analyse_sphere(d["wl"], d["a"], d["c"], d["b"], units="photons")
    assert as_energy["PLQY_ref"] == pytest.approx(0.05, rel=2e-3)
    assert abs(as_photons["PLQY_ref"] / 0.05 - 1) > 0.2            # power spectra read as counts are wrong


def test_counting_noise_scatters_around_the_true_value():
    vals = [sphere(seed=k)["PLQY_ref"] for k in range(12)]
    assert np.median(vals) == pytest.approx(0.05, rel=0.01)
    assert np.std(vals) / 0.05 < 0.02


def test_windows_hold_the_line_and_the_band():
    d = c.simulate_sphere(noise=False)
    lo, hi = c.laser_window(d["wl"], d["a"])
    assert lo < 532.0 - 2.0 and hi > 532.0 + 2.0 and hi - lo < 12.0
    em = c.emission_window(d["wl"], d["a"], d["c"], (lo, hi))
    band = d["c"] - d["a"]
    m = (d["wl"] >= em["lo"]) & (d["wl"] <= em["hi"])
    outside = (d["wl"] > hi)
    assert np.trapezoid(band[m], d["wl"][m]) / np.trapezoid(band[outside], d["wl"][outside]) > 0.995
    assert em["truncated"] == "" and abs(em["peak_nm"] - eqe_core.HC_EV_NM / 1.60) < 15.0
    # windows entered by hand are used as given
    r = c.analyse_sphere(d["wl"], d["a"], d["c"], d["b"], laser_lo=525, laser_hi=540, em_lo=650, em_hi=900)
    assert r["sphere"]["laser"] == (525.0, 540.0) and r["sphere"]["emission"] == (650.0, 900.0)
    assert r["PLQY_ref"] == pytest.approx(0.05, rel=2e-3)


def test_a_band_cut_by_the_recorded_range_is_reported():
    d = c.simulate_sphere(noise=False)
    cut = d["wl"] < 790.0                               # the band peaks at 775 nm
    r = c.analyse_sphere(d["wl"][cut], d["a"][cut], d["c"][cut], d["b"][cut])
    assert r["sphere"]["truncated"] == "long"
    assert r["PLQY_ref"] < 0.05 * 0.8
    assert any("cut at the long-wavelength end" in w for w in r["warnings"])


def test_checks_name_low_absorptance_swapped_columns_and_a_floor():
    assert any("absorbs 4.0 %" in w for w in sphere(absorptance=0.04, noise=False)["warnings"])
    d = c.simulate_sphere(noise=False)
    swapped = c.analyse_sphere(d["wl"], d["a"], d["b"], d["c"])        # B and C exchanged
    assert any("swapped" in w or "not below" in w for w in swapped["warnings"])
    floor = c.analyse_sphere(d["wl"], d["a"] + 0.05 * d["a"].max(), d["c"] + 0.05 * d["a"].max(),
                             d["b"] + 0.05 * d["a"].max())
    assert any("dark-corrected" in w for w in floor["warnings"])


# ------------------------------------------------------------------ QFLS
def test_qfls_is_the_radiative_limit_less_the_nonradiative_loss():
    ref = c.radiative_reference("j0", j0_rad=1e-21, jsc_1sun=24.0)
    assert ref["Voc_rad_1sun"] == pytest.approx(KT * math.log(24.0 / 1e-21 + 1.0))
    d = c.simulate_sphere(plqy=0.03, noise=False)
    r = c.analyse_sphere(d["wl"], d["a"], d["c"], d["b"], reference=ref)
    assert r["QFLS_ref"] == pytest.approx(ref["Voc_rad_1sun"] + KT * math.log(r["PLQY_ref"]), abs=1e-6)
    assert r["dV_nr_ref"] == pytest.approx(-KT * math.log(r["PLQY_ref"]))
    assert r["QFLS_1sun"] == pytest.approx(r["QFLS_ref"])
    # ten times the excitation: 60 mV more splitting at the same PLQY
    hi = c.analyse_sphere(d["wl"], d["a"], d["c"], d["b"], reference=ref, excitation_suns=10.0)
    assert hi["QFLS_ref"] - r["QFLS_ref"] == pytest.approx(KT * math.log(10.0), abs=1e-9)
    assert not np.isfinite(hi["QFLS_1sun"])


def test_laser_power_gives_the_generation_current():
    # 100 mW/cm2 at 532 nm, all absorbed: q P lambda / (h c)
    expect = 1e3 * eqe_core.Q_E * 0.1 * 532e-9 / (eqe_core.H_PLANCK * eqe_core.C_LIGHT)
    assert c.generation_current(100.0, 532.0, 1.0) == pytest.approx(expect)
    assert expect == pytest.approx(42.9, abs=0.05)
    ref = c.radiative_reference("j0", j0_rad=1e-21, jsc_1sun=24.0)
    d = c.simulate_sphere(plqy=0.05, absorptance=0.8, noise=False)
    r = c.analyse_sphere(d["wl"], d["a"], d["c"], d["b"], reference=ref, power_mw_cm2=56.0)
    assert r["suns_ref"] == pytest.approx(c.generation_current(56.0, 532.0, 0.8) / 24.0, rel=1e-3)


def test_radiative_reference_from_an_eqe_file_and_from_the_band_gap(tmp_path):
    wl = np.arange(300.0, 900.0, 2.0)
    e = eqe_core.HC_EV_NM / wl
    eqe = 0.85 / (1 + np.exp(-(e - 1.60) / 0.012))
    path = tmp_path / "stack_EQE.csv"
    pd.DataFrame({"Wavelength (nm)": wl, "EQE (%)": 100 * eqe}).to_csv(path, index=False)
    ref = c.radiative_reference("eqe", eqe_file=str(path))
    rad = eqe_core.radiative_limit(e[::-1], eqe[::-1])
    assert ref["J0_rad"] == pytest.approx(rad["J0_rad_mA_cm2"], rel=1e-6)
    assert ref["J_G_1sun"] == pytest.approx(eqe_core.calculate_jsc(wl, eqe), rel=1e-6)
    assert ref["Eg_eV"] == pytest.approx(1.60, abs=0.01)
    sq = c.radiative_reference("bandgap", eg_ev=1.60)
    assert sq["J0_rad"] == pytest.approx(eqe_core.shockley_queisser(1.60)["J0_SQ"])
    # a step absorptance emits less below the gap than a real edge: lower J0, higher QFLS
    assert sq["J0_rad"] < ref["J0_rad"]
    with pytest.raises(ValueError, match="band gap"):
        c.radiative_reference("bandgap")
    with pytest.raises(ValueError, match="J0,rad"):
        c.radiative_reference("j0")


# ------------------------------------------------------------------ series
def series(**kw):
    d = c.simulate_series(**kw)
    ref = c.radiative_reference("j0", j0_rad=1e-21, jsc_1sun=24.0)
    return d, c.analyse_series(d["intensity"], d["plqy"], d["voc"], d["jsc"], d["ff"], reference=ref)


@pytest.mark.parametrize("n_id", [1.0, 1.3, 1.8])
def test_series_gives_implied_ideality_qfls_and_contact_loss(n_id):
    d, r = series(n_id=n_id, dv_int=0.04)
    assert r["qfls_fit"]["n_id"] == pytest.approx(n_id, abs=1e-6)
    assert r["plqy_exponent"] == pytest.approx(n_id - 1.0, abs=1e-6)
    assert r["voc_fit"]["n_id"] == pytest.approx(n_id, abs=1e-6)
    assert r["QFLS_1sun"] == pytest.approx(float(d["qfls"][-1]))
    assert r["dV_int_1sun"] == pytest.approx(0.04)
    assert r["warnings"] == []


@pytest.mark.parametrize("n_id", [1.0, 1.5, 2.0])
def test_implied_fill_factor_is_that_of_the_ideal_diode(n_id):
    d, r = series(n_id=n_id, transport_ff_loss=5.0)
    exact = 100.0 * c.ideal_ff(float(d["qfls"][-1]), n_id)
    assert r["iFF"] == pytest.approx(exact, abs=0.1)
    assert r["transport_loss_FF"] == pytest.approx(5.0, abs=0.1)
    assert r["iPCE"] == pytest.approx(24.0 * r["iVoc"] * r["iFF"] / 100.0)


def test_series_columns_in_per_cent_and_intensity_units(tmp_path):
    d = c.simulate_series()
    path = tmp_path / "film_PLQY.csv"
    pd.DataFrame({"Excitation (mW/cm2)": 100 * d["intensity"], "PLQY (%)": 100 * d["plqy"]}).to_csv(path, index=False)
    p = cb.parameters("plqy", {"intensity_unit": "mW/cm2", "radiative": "j0", "j0_rad": 1e-21, "jsc_1sun": 24.0})
    item = cb.run_file("plqy", str(path), p)
    assert item["error"] == ""
    r = item["result"]
    assert r["kind"] == "series" and r["plqy_percent_input"]
    assert r["PLQY_1sun"] == pytest.approx(0.02)
    assert r["QFLS_1sun"] == pytest.approx(float(d["qfls"][-1]))


def test_one_sun_is_extrapolated_only_close_to_the_series():
    ref = c.radiative_reference("j0", j0_rad=1e-21, jsc_1sun=24.0)
    d = c.simulate_series(suns=np.logspace(-3, np.log10(0.5), 12))
    r = c.analyse_series(d["intensity"], d["plqy"], reference=ref)
    assert r["extrapolated_1sun"]
    full = c.simulate_series()
    assert r["QFLS_1sun"] == pytest.approx(float(full["qfls"][-1]), abs=1e-6)
    assert any("extrapolated" in w for w in r["warnings"])
    far = c.simulate_series(suns=np.logspace(-4, -2, 8))
    r = c.analyse_series(far["intensity"], far["plqy"], reference=ref)
    assert not np.isfinite(r["QFLS_1sun"]) and not r["extrapolated_1sun"]


def test_fit_range_and_a_voc_above_the_qfls():
    ref = c.radiative_reference("j0", j0_rad=1e-21, jsc_1sun=24.0)
    d = c.simulate_series(dv_int=-0.03)
    r = c.analyse_series(d["intensity"], d["plqy"], d["voc"], reference=ref, i_min=0.01)
    assert r["fit_mask"].sum() == int((d["intensity"] >= 0.01).sum())
    assert any("above the QFLS" in w for w in r["warnings"])
    rep = interpret_transport.interpret_plqy(r, "x")
    assert any(f.topic == "QFLS and Voc" and f.level == "problem" for f in rep.findings)


# ------------------------------------------------------------------ reading
def test_sphere_columns_by_name_in_any_order_or_by_position():
    d = c.simulate_sphere(noise=False)
    named = pd.DataFrame({"In beam (C)": d["c"], "lambda (nm)": d["wl"], "Empty sphere": d["a"],
                          "Out of beam": d["b"]})
    r = c.read_table(named)
    assert r["_kind"] == "sphere"
    np.testing.assert_array_equal(r["c"], d["c"])
    np.testing.assert_array_equal(r["b"], d["b"])
    plain = pd.DataFrame({"col0": d["wl"], "col1": d["a"], "col2": d["b"], "col3": d["c"]})
    r = c.read_table(plain)
    np.testing.assert_array_equal(r["b"], d["b"])
    np.testing.assert_array_equal(r["c"], d["c"])
    three = pd.DataFrame({"col0": d["wl"], "col1": d["a"], "col2": d["c"]})
    r = c.read_table(three)
    assert "b" not in r
    np.testing.assert_array_equal(r["c"], d["c"])
    with pytest.raises(ValueError):
        c.read_table(pd.DataFrame({"col0": d["wl"], "col1": d["a"]}))


def test_a_utf16_sphere_export_is_read(tmp_path):
    d = c.simulate_sphere()
    text = "Wavelength (nm)\tEmpty sphere\tOut of beam\tIn beam\n" + "\n".join(
        f"{w:.1f}\t{a:.0f}\t{b:.0f}\t{x:.0f}" for w, a, b, x in zip(d["wl"], d["a"], d["b"], d["c"]))
    path = tmp_path / "sphere_PLQY.txt"
    path.write_bytes(text.encode("utf-16"))
    data = c.read_curve(str(path))
    assert data["_kind"] == "sphere" and len(data["wl"]) == len(d["wl"])
    df = curve_io.read_numeric_table(str(path))
    assert df.shape[1] == 4


# ------------------------------------------------------------------ interpretation
@pytest.mark.parametrize("plqy,level", [(0.05, "good"), (0.003, "note"), (0.0004, "warning")])
def test_plqy_grading(plqy, level):
    r = sphere(plqy=plqy, noise=False)
    rep = interpret_transport.interpret_plqy(r, "film")
    assert next(f for f in rep.findings if f.topic == "PLQY").level == level


@pytest.mark.parametrize("dv,level", [(0.01, "good"), (0.035, "note"), (0.08, "warning")])
def test_contact_loss_grading(dv, level):
    _d, r = series(dv_int=dv)
    rep = interpret_transport.interpret_plqy(r, "cell")
    assert next(f for f in rep.findings if f.topic == "QFLS and Voc").level == level
