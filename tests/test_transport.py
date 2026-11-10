"""Ground truth for the transport and recombination analyses added in 3.5.0.

Every curve is built by the forward model of its own module with known parameters,
so each analysis has to give those parameters back; the constants are written out
here again so that a wrong prefactor in a core cannot hide behind its own helper.
"""
import math

import numpy as np
import pytest

from scripts.CV import cv_core as cv
from scripts.EIS import eis_core as eis
from scripts.Intensity import intensity_core as inten
from scripts.SCLC import sclc_core as sclc
from scripts.Stability import stability_core as stab
from scripts.TRPL import trpl_core as trpl
from scripts.common import interpret_transport as rules

Q = 1.602176634e-19
KB = 1.380649e-23
EPS0 = 8.8541878128e-12
VT300 = KB * 300.0 / Q


def levels(report):
    """topic -> level of a report ('Check' appears several times and is left out)."""
    return {f.topic: f.level for f in report.findings if f.topic != "Check"}


def checks(report):
    return [f for f in report.findings if f.topic == "Check"]


# --------------------------------------------------------------------------- SCLC
def test_sclc_formulas_match_the_textbook_expressions():
    thickness, eps_r = 500.0, 25.0
    length = thickness * 1e-9
    n_t = 2.0 * EPS0 * eps_r * 4.5 / (Q * length ** 2) * 1e-6
    assert sclc.trap_density_cm3(4.5, thickness, eps_r) == pytest.approx(n_t, rel=1e-9)
    n_min = 4.0 * math.pi ** 2 * KB * 300.0 * EPS0 * eps_r / (Q ** 2 * length ** 2) * 1e-6
    assert sclc.resolution_limit_cm3(thickness, eps_r) == pytest.approx(n_min, rel=1e-9)
    # the limit scales with temperature and with 1/L^2
    assert sclc.resolution_limit_cm3(thickness, eps_r, 150.0) == pytest.approx(n_min / 2.0, rel=1e-9)
    assert sclc.resolution_limit_cm3(2 * thickness, eps_r) == pytest.approx(n_min / 4.0, rel=1e-9)


def test_sclc_recovers_trap_density_mobility_and_background_carriers():
    v, j = sclc.simulate(thickness_nm=500.0, eps_r=25.0, mobility_cm2_Vs=1.0, n_t_cm3=5e16, n0_cm3=1e13)
    r = sclc.analyse(v, j, 500.0, 25.0)
    assert r["n_t_cm3"] == pytest.approx(5e16, rel=0.02)
    assert r["mobility_cm2_Vs"] == pytest.approx(1.0, rel=0.02)
    assert r["child_slope"] == pytest.approx(2.0, abs=0.05)
    assert r["V_TFL"] == pytest.approx(Q * 5e22 * (500e-9) ** 2 / (2 * EPS0 * 25.0), rel=0.02)
    assert r["n0_cm3"] == pytest.approx(1e13, rel=0.05)
    assert r["n_t_min_cm3"] == pytest.approx(sclc.resolution_limit_cm3(500.0, 25.0), rel=1e-9)
    assert r["decades_V"] > 2.0
    found = levels(rules.interpret_sclc(r))
    assert found["Mott-Gurney region"] == "good"
    assert found["Trap density"] == "good"
    assert found["Sweep hysteresis"] == "note"          # a single sweep cannot show hysteresis


def test_sclc_trap_density_below_the_resolution_limit_is_a_problem():
    v, j = sclc.simulate(n_t_cm3=5e15, n0_cm3=1e9)      # 5e15 < 5.6e15 = limit of a 500 nm film
    r = sclc.analyse(v, j, 500.0, 25.0)
    assert r["n_t_cm3"] < r["n_t_min_cm3"]
    assert levels(rules.interpret_sclc(r))["Trap density"] == "problem"


def test_sclc_curve_without_trap_filling_reports_no_density():
    v, j = sclc.simulate(n_t_cm3=0.0, n0_cm3=1e13)
    r = sclc.analyse(v, j, 500.0, 25.0)
    assert r["tfl"] is None
    assert not np.isfinite(r["n_t_cm3"])
    assert r["mobility_cm2_Vs"] == pytest.approx(1.0, rel=0.02)
    assert any("trap-filling" in w for w in r["warnings"])
    assert levels(rules.interpret_sclc(r))["Trap density"] == "note"


def test_sclc_ohmic_curve_has_no_mott_gurney_region():
    v = np.logspace(-2, 0, 40)
    r = sclc.analyse(v, 1e-3 * v, 500.0, 25.0)
    assert r["child"] is None
    assert not np.isfinite(r["mobility_cm2_Vs"])
    assert levels(rules.interpret_sclc(r))["Mott-Gurney region"] == "problem"


def test_sclc_hysteresis_between_the_two_sweep_directions():
    v, j = sclc.simulate(n_t_cm3=5e16, n0_cm3=1e13)
    both_v = np.concatenate([v, v[::-1]])
    both_j = np.concatenate([j, 2.0 * j[::-1]])          # the return sweep lies a factor 2 higher
    r = sclc.analyse(both_v, both_j, 500.0, 25.0)
    assert r["hysteresis_dec"] == pytest.approx(math.log10(2.0), abs=0.03)
    assert levels(rules.interpret_sclc(r))["Sweep hysteresis"] == "warning"
    assert len(sclc.split_sweeps(both_v, both_j)) == 2


def test_sclc_murgatroyd_fit_returns_the_field_dependence():
    length, eps = 500e-9, EPS0 * 25.0
    v = np.logspace(-1, 1.5, 60)
    mu0, gamma = 1e-4, 3e-4                               # m2/Vs and (m/V)^0.5
    j_si = 9.0 / 8.0 * eps * mu0 * v ** 2 / length ** 3 * np.exp(0.891 * gamma * np.sqrt(v / length))
    fit = sclc.murgatroyd(v, j_si / 10.0, 500.0, 25.0)   # A/m2 -> mA/cm2
    assert fit["mu0_cm2_Vs"] == pytest.approx(mu0 * 1e4, rel=1e-3)
    assert fit["gamma_cm_V_05"] == pytest.approx(gamma * 10.0, rel=1e-3)
    assert fit["r2"] > 0.999


# ---------------------------------------------------------- light-intensity series
def test_intensity_recovers_ideality_factor_and_jsc_exponent():
    d = inten.simulate(n_id=1.5, alpha=0.97, rs_ohm_cm2=3.0)
    r = inten.analyse(**d)
    # Voc against ln(Jsc) gives the diode ideality; against ln(I) it is n_id * alpha
    assert r["jscvoc_fit"]["n_id"] == pytest.approx(1.5, rel=1e-3)
    assert r["voc_fit"]["n_id"] == pytest.approx(1.5 * 0.97, rel=1e-3)
    assert r["voc_fit"]["slope_mV_per_decade"] == pytest.approx(1.5 * 0.97 * VT300 * math.log(10) * 1e3, rel=1e-3)
    assert r["jsc_fit"]["alpha"] == pytest.approx(0.97, rel=1e-3)
    assert r["decades"] == pytest.approx(2.0, abs=1e-6)
    assert not r["warnings"]


def test_intensity_pseudo_fill_factor_separates_the_transport_loss():
    r = inten.analyse(**inten.simulate(rs_ohm_cm2=3.0))
    pff = 100.0 * r["pseudo"]["pFF"]
    assert pff > r["FF_at_max"]                          # the series resistance is taken out
    assert r["transport_loss_FF"] == pytest.approx(pff - r["FF_at_max"], abs=1e-6)
    low_rs = inten.analyse(**inten.simulate(rs_ohm_cm2=0.5))
    assert low_rs["transport_loss_FF"] < r["transport_loss_FF"]
    assert levels(rules.interpret_intensity(low_rs))["Transport loss in FF"] == "good"
    assert levels(rules.interpret_intensity(r))["Transport loss in FF"] == "warning"


def test_intensity_green_fill_factor():
    voc, n = 1.1, 1.0
    v = voc / (n * VT300)
    assert inten.ff0_green(voc, n) == pytest.approx((v - math.log(v + 0.72)) / (v + 1.0), rel=1e-6)
    assert inten.ff0_green(voc, 2.0) < inten.ff0_green(voc, 1.0)


@pytest.mark.parametrize("n_id, alpha, ideality, exponent", [
    (2.0, 1.0, "warning", "good"),        # trap-assisted (SRH) recombination in the bulk
    (1.5, 1.0, "note", "good"),
    (1.0, 0.8, "problem", "warning"),     # slope below kT/q, strongly sub-linear Jsc
])
def test_intensity_interpretation_levels(n_id, alpha, ideality, exponent):
    r = inten.analyse(**inten.simulate(n_id=n_id, alpha=alpha, rs_ohm_cm2=0.5))
    found = levels(rules.interpret_intensity(r))
    assert found["Ideality factor"] == ideality
    assert found["Jsc exponent"] == exponent


def test_intensity_fit_window_limits_the_points_used():
    d = inten.simulate()
    r = inten.analyse(d["intensity"], d["voc"], d["jsc"], d["ff"], i_min=5.0)
    assert int(np.sum(r["fit_mask"])) == 5
    assert r["voc_fit"]["n"] == 5


@pytest.mark.parametrize("name, expected", [
    ("cell_0.1sun.txt", 10.0), ("a_53mW.csv", 53.0), ("x_OD1.0.txt", 10.0), ("y_10pct.dat", 10.0),
    ("z 0p5 suns.txt", 50.0), ("ND2_cell.txt", 1.0),
])
def test_intensity_is_read_from_the_file_name(name, expected):
    assert inten.intensity_from_name(name) == pytest.approx(expected)


def test_intensity_from_a_plain_file_name_is_unknown():
    assert math.isnan(inten.intensity_from_name("plain.txt"))


# --------------------------------------------------------------------------- TRPL
def test_trpl_recovers_a_two_exponential_decay():
    t, y = trpl.simulate(taus=(5.0, 80.0), amps=(0.7, 0.3), peak_counts=10000.0, background=5.0, seed=0)
    r = trpl.analyse(t, y)
    assert r["model"] == "exp2"
    assert r["taus"] == pytest.approx([5.0, 80.0], rel=0.05)
    assert r["amp_fracs"] == pytest.approx([0.7, 0.3], abs=0.02)
    assert r["tau_amp"] == pytest.approx(0.7 * 5.0 + 0.3 * 80.0, rel=0.04)
    assert r["tau_int"] == pytest.approx((0.7 * 25.0 + 0.3 * 6400.0) / 27.5, rel=0.04)
    assert r["background"] == pytest.approx(5.0, abs=1.0)
    assert r["counts"] is True
    assert 0.8 < r["chi2_red"] < 1.25                    # Poisson weights: chi2 near 1 for the right model
    assert r["dw"] > 1.5
    found = levels(rules.interpret_trpl(r))
    assert found["Fit quality"] == "good"
    assert "Decay law" in found and "Average lifetime" in found


def test_trpl_keeps_the_simplest_model_that_describes_the_decay():
    t, y = trpl.simulate(taus=(50.0,), amps=(1.0,), seed=0)
    r = trpl.analyse(t, y)
    assert r["model"] == "exp1"
    assert r["taus"] == pytest.approx([50.0], rel=0.03)


def test_trpl_stretched_exponential_and_its_mean_lifetime():
    t, y = trpl.simulate(taus=(40.0,), amps=(1.0,), beta=0.6, seed=0)
    r = trpl.analyse(t, y, model="stretched")
    assert r["model"] == "stretched"
    assert r["beta"] == pytest.approx(0.6, abs=0.03)
    assert r["taus"][0] == pytest.approx(40.0, rel=0.05)
    mean = r["taus"][0] / r["beta"] * math.gamma(1.0 / r["beta"])
    assert r["tau_amp"] == pytest.approx(mean, rel=1e-6)


def test_trpl_noise_free_normalised_decay():
    t, y = trpl.simulate(poisson=False, background=0.0)
    r = trpl.analyse(t, y / y.max())
    assert r["counts"] is False                          # not photon counts: no Poisson chi2 claim
    assert r["taus"] == pytest.approx([5.0, 80.0], rel=1e-3)
    assert "Fit quality" not in {k for k, v in levels(rules.interpret_trpl(r)).items() if v == "good"}


def test_trpl_one_over_e_time_and_diffusion_length():
    t = np.linspace(0.0, 300.0, 600)
    assert trpl.tau_1e(t, 1000.0 * np.exp(-t / 30.0)) == pytest.approx(30.0, rel=1e-3)
    # L_D = sqrt(D tau), D = mu kT/q
    expected_um = math.sqrt(1.0 * VT300 * 100e-9) * 1e4
    assert trpl.diffusion_length_um(100.0, 1.0, "ns", 300.0) == pytest.approx(expected_um, rel=1e-6)
    assert trpl.diffusion_length_um(100.0, 1.0, "us", 300.0) == pytest.approx(expected_um * math.sqrt(1000.0), rel=1e-6)
    assert math.isnan(trpl.diffusion_length_um(100.0, 0.0))
    tt, yy = trpl.simulate()
    r = trpl.analyse(tt, yy, mobility_cm2_Vs=2.0)
    assert r["L_D_um"] == pytest.approx(trpl.diffusion_length_um(r["tau_amp"], 2.0, "ns", 300.0), rel=1e-6)
    assert "Diffusion length" in levels(rules.interpret_trpl(r))


# ---------------------------------------------------------------------- impedance
def test_eis_circuit_limits():
    z = eis.z_model("R(RC)", (20.0, 500.0, 1e-7), [1e-6, 1e12])
    assert z[0].real == pytest.approx(520.0, rel=1e-6)   # DC: Rs + R
    assert z[1].real == pytest.approx(20.0, rel=1e-6)    # high frequency: Rs
    assert eis.param_names("R(RQ)(RQ)") == ["Rs", "R1", "Q1", "alpha1", "R2", "Q2", "alpha2"]


def test_eis_recovers_two_arcs_and_passes_kramers_kronig():
    f, zre, zim = eis.simulate()                         # Rs 10, (200, 0.95), (1500, 0.85)
    r = eis.analyse(f, zre, zim)
    assert r["model"] == "R(RQ)(RQ)"
    assert r["Rs"] == pytest.approx(10.0, rel=0.03)
    assert [a["R"] for a in r["arcs"]] == pytest.approx([200.0, 1500.0], rel=0.03)
    assert [a["alpha"] for a in r["arcs"]] == pytest.approx([0.95, 0.85], abs=0.02)
    assert r["R_total"] == pytest.approx(1700.0, rel=0.02)
    assert r["arcs"][0]["f_peak_Hz"] > r["arcs"][1]["f_peak_Hz"]
    assert r["rms_pct"] < 1.0
    assert r["kk"]["rms_pct"] < 1.0 and r["kk"]["max_pct"] < 2.0
    assert r["flipped"] is False
    found = levels(rules.interpret_eis(r))
    assert found["Kramers-Kronig test"] == "good"
    assert found["Circuit fit"] == "good"
    assert found["Assignment of the arcs"] == "note"


def test_eis_sign_convention_is_detected():
    f, zre, zim = eis.simulate()
    r = eis.analyse(f, zre, -zim)                        # a file that stores -Z''
    assert r["flipped"] is True
    assert r["Rs"] == pytest.approx(10.0, rel=0.03)


def test_eis_drift_fails_the_kramers_kronig_test():
    f, zre, zim = eis.simulate(drift=0.5)
    r = eis.analyse(f, zre, zim)
    assert r["kk"]["max_pct"] > 2.0
    assert levels(rules.interpret_eis(r))["Kramers-Kronig test"] == "problem"


def test_eis_single_ideal_arc_takes_the_simple_circuit():
    f, zre, zim = eis.simulate(model="R(RC)", params=(20.0, 500.0, 1e-7), noise=0.002)
    r = eis.analyse(f, zre, zim)
    assert r["model"] == "R(RC)"
    assert list(r["names"]) == ["Rs", "R1", "C1"]
    assert r["p"] == pytest.approx([20.0, 500.0, 1e-7], rel=0.02)


def test_eis_frequency_window_and_permittivity():
    f, zre, zim = eis.simulate()
    cropped = eis.analyse(f, zre, zim, f_min=10.0)
    assert cropped["f"].min() >= 10.0 and len(cropped["f"]) < len(f)
    r = eis.analyse(f, zre, zim, area_cm2=0.1, thickness_nm=500.0)
    c_geo = min(a["C_eff_F"] for a in r["arcs"])         # the high-frequency arc is the geometric one
    assert r["eps_r"] == pytest.approx(c_geo * 500e-9 / (EPS0 * 0.1e-4), rel=1e-6)
    assert "Permittivity" in levels(rules.interpret_eis(r))


# ---------------------------------------------------------------------------- C-V
def test_cv_recovers_doping_density_and_built_in_potential():
    v, c = cv.simulate(n_cm3=1e17, v_bi=0.9, eps_r=25.0, area_cm2=0.1)
    r = cv.analyse(v, c, 0.1, 25.0)
    assert r["N_cm3"] == pytest.approx(1e17, rel=0.01)
    assert r["V_bi"] == pytest.approx(0.9, abs=0.01)
    assert r["polarity"] == 1
    assert r["window"]["r2"] > 0.999
    assert 100.0 < r["W0_nm"] < 200.0
    # without a thickness the density cannot be compared with the limit of the layer
    assert not np.isfinite(r["N_min_cm3"])
    assert any("thickness" in f.text for f in checks(rules.interpret_cv(r)))


def test_cv_bias_polarity_and_capacitance_unit_do_not_change_the_result():
    v, c = cv.simulate()
    reversed_bias = cv.analyse(-v, c, 0.1, 25.0)
    assert reversed_bias["polarity"] == -1
    assert reversed_bias["N_cm3"] == pytest.approx(1e17, rel=0.01)
    assert reversed_bias["V_bi"] == pytest.approx(0.9, abs=0.01)
    in_nf = cv.analyse(v, c * 1e9, 0.1, 25.0, c_unit="nF")
    assert in_nf["N_cm3"] == pytest.approx(1e17, rel=0.01)
    manual = cv.analyse(v, c, 0.1, 25.0, v_min=-0.5, v_max=0.3)
    assert manual["manual_window"] is True
    assert manual["N_cm3"] == pytest.approx(1e17, rel=0.01)


def test_cv_resolution_limit_of_a_thin_layer():
    d, eps_r = 500.0, 25.0
    expected = 27.0 * 2.0 * KB * 300.0 * EPS0 * eps_r / (4.0 * Q ** 2 * (d * 1e-9) ** 2) * 1e-6
    assert cv.resolution_limit_cm3(d, eps_r) == pytest.approx(expected, rel=1e-9)
    v, c = cv.simulate(n_cm3=1e17)
    r = cv.analyse(v, c, 0.1, eps_r, thickness_nm=d)
    assert r["N_min_cm3"] == pytest.approx(expected, rel=1e-9)
    assert r["C_geo_F"] == pytest.approx(EPS0 * eps_r * 0.1e-4 / (d * 1e-9), rel=1e-9)
    found = levels(rules.interpret_cv(r))
    assert found["Doping density against the resolution limit"] == "good"
    assert found["Depletion width"] == "good"


def test_cv_fully_depleted_layer_is_not_reported_as_doping():
    v, c = cv.simulate(n_cm3=1e15, thickness_nm=500.0, c_inj0=2e-12)
    r = cv.analyse(v, c, 0.1, 25.0, thickness_nm=500.0)
    assert r["N_cm3"] < 3.0 * r["N_min_cm3"]             # the apparent density sits at the limit
    assert r["C_min_over_C_geo"] == pytest.approx(1.0, abs=0.05)
    assert levels(rules.interpret_cv(r))["Doping density against the resolution limit"] in ("warning", "problem")
    assert r["warnings"]


def test_cv_flat_capacitance_has_no_mott_schottky_region():
    v = np.linspace(-0.5, 0.5, 30)
    r = cv.analyse(v, 1e-9 * (1.0 + 0.001 * np.sin(40.0 * v)), 0.1, 25.0)
    assert r["window"] is None
    assert not np.isfinite(r["N_cm3"])
    assert levels(rules.interpret_cv(r))["Mott-Schottky region"] == "problem"


def test_cv_refuses_too_few_points_and_missing_geometry():
    v, c = cv.simulate()
    with pytest.raises(ValueError):
        cv.analyse(v[:5], c[:5], 0.1, 25.0)
    with pytest.raises(ValueError):
        cv.analyse(v, c, 0.0, 25.0)


# ---------------------------------------------------------------------- stability
def test_stability_burn_in_trace():
    # E(t) = a1 exp(-t/tau1) + (1 - a1) - k t, so T80 = (0.2 - a1) / k = 800 h
    t, y = stab.simulate(a1=0.12, tau1=40.0, rate_per_h=1e-4, t_end=1000.0, seed=0)
    r = stab.analyse(t, y)
    assert r["model"] == "burn-in"
    assert r["T_reached"] is True
    assert r["T_measured"] == pytest.approx(800.0, rel=0.03)
    assert r["T_model"] == pytest.approx(800.0, rel=0.03)
    assert r["burn_in"] is True
    assert r["burn_in_loss_pct"] == pytest.approx(12.0, abs=1.5)
    assert r["rate_pct_per_1000h"] == pytest.approx(10.0, rel=0.15)
    assert r["duration_h"] == pytest.approx(1000.0)
    found = levels(rules.interpret_stability(r))
    assert found["T80"] == "good"
    assert found["Burn-in"] == "note"
    # a lifetime without its ageing protocol is flagged
    assert any("protocol" in f.text for f in checks(rules.interpret_stability(r)))
    stated = stab.analyse(t, y, protocol=stab.PROTOCOLS[1])
    assert not any("protocol" in w for w in stated["warnings"])


def test_stability_extrapolated_lifetime_is_marked_as_such():
    t, y = stab.simulate(a1=0.0, rate_per_h=1.5e-4, t_end=1000.0)
    r = stab.analyse(t, y)
    assert r["model"] == "linear"
    assert r["T_reached"] is False
    assert r["T_extrapolated"] == pytest.approx(0.2 / 1.5e-4, rel=0.05)
    assert levels(rules.interpret_stability(r))["T80"] == "warning"
    flat_t, flat_y = stab.simulate(a1=0.0, rate_per_h=0.0, t_end=1000.0)
    flat = stab.analyse(flat_t, flat_y)
    # an extrapolation far beyond the measured time is not a result
    assert levels(rules.interpret_stability(flat))["T80"] == "problem"


def test_stability_time_unit_normalisation_and_threshold():
    t, y = stab.simulate()
    hours = stab.analyse(t, y)
    minutes = stab.analyse(t * 60.0, y, time_unit="min")
    assert minutes["T_measured"] == pytest.approx(hours["T_measured"], rel=1e-9)
    assert minutes["duration_h"] == pytest.approx(1000.0)
    as_given = stab.analyse(t, y / y[0] * 100.0, norm="none")
    assert as_given["reference"] == pytest.approx(100.0)
    assert as_given["T_measured"] == pytest.approx(hours["T_measured"], rel=1e-6)
    assert stab.analyse(t, y, norm="maximum")["reference"] == pytest.approx(float(np.max(y)))
    t90 = stab.analyse(t, y, threshold=0.9)
    assert t90["T_measured"] < hours["T_measured"]


def test_stability_crossing_ignores_a_transient_dip():
    t = np.arange(10.0)
    y = np.array([1, 1, 0.7, 1, 1, 0.7, 0.7, 0.7, 0.7, 0.7])
    # the single low point at t = 2 does not persist; the crossing is interpolated between 4 and 5
    assert stab.crossing_time(t, y, 0.8) == pytest.approx(4.0 + 0.2 / 0.3, rel=1e-9)
    assert math.isnan(stab.crossing_time(t, np.ones(10), 0.8))


def test_stability_refuses_too_few_points():
    t, y = stab.simulate()
    with pytest.raises(ValueError):
        stab.analyse(t[:4], y[:4])


# ---------------------------------------------------------------- report contract
@pytest.mark.parametrize("build", [
    lambda: rules.interpret_sclc(sclc.analyse(*sclc.simulate(n_t_cm3=5e16, n0_cm3=1e13), 500.0, 25.0), "film A"),
    lambda: rules.interpret_intensity(inten.analyse(**inten.simulate()), "cell A"),
    lambda: rules.interpret_trpl(trpl.analyse(*trpl.simulate()), "film A"),
    lambda: rules.interpret_eis(eis.analyse(*eis.simulate()), "cell A"),
    lambda: rules.interpret_cv(cv.analyse(*cv.simulate(), 0.1, 25.0, thickness_nm=500.0), "cell A"),
    lambda: rules.interpret_stability(stab.analyse(*stab.simulate()), "cell A"),
])
def test_every_finding_names_its_rule_and_evidence(build):
    from scripts.common import interpret
    report = build()
    assert report.findings
    for f in report.findings:
        assert f.level in interpret.LEVELS
        assert f.topic and f.text
        if f.topic != "Check":
            assert f.rule, f"{f.topic}: the rule that produced a finding has to be stated"
    text = report.to_markdown()
    assert report.technique in text
    assert report.subject in text
