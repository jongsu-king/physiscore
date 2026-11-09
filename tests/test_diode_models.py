"""One-diode equivalent circuit: explicit Lambert-W solution, illuminated
fit, dark fit with series resistance, Cheung analysis and hysteresis.

Ground truth is the implicit single-diode solver in conftest (bracketed root
finding, independent of the Lambert-W code under test).
"""
import numpy as np
import pytest

from conftest import single_diode_jv, thermal_voltage
from scripts.JV import jv_core
from scripts.Dark_JV import dark_jv_core

PARAMS = dict(jph=22.0, j0=1e-9, n=1.5, rs=2.0, rsh=2000.0)


# ---------------------------------------------------------------------------
# Explicit model
# ---------------------------------------------------------------------------
def test_lambert_w_solution_matches_implicit_solver(jv_sweep):
    implicit = single_diode_jv(jv_sweep, **PARAMS)
    explicit = jv_core.single_diode_current(jv_sweep, **PARAMS)
    assert np.allclose(explicit, implicit, rtol=1e-8, atol=1e-8)


def test_lambert_w_is_stable_at_large_forward_bias():
    """Beyond ~0.7 V the argument of exp() overflows a double; the W(exp(z))
    helper must still return finite, monotonic currents."""
    v = np.linspace(0.0, 3.0, 301)
    j = jv_core.single_diode_current(v, 20.0, 1e-12, 1.0, 1.0, 1e4)
    assert np.all(np.isfinite(j))
    assert np.all(np.diff(j) < 0)


def test_zero_series_resistance_branch(jv_sweep):
    """With Rs = 0 the model is explicit without Lambert W; the Rs -> 0
    limit of the W form must join it continuously."""
    a = jv_core.single_diode_current(jv_sweep, 22.0, 1e-9, 1.5, 0.0, 2000.0)
    vt = 1.5 * thermal_voltage()
    b = 22.0 - 1e-9 * np.expm1(jv_sweep / vt) - 1000.0 * jv_sweep / 2000.0
    assert np.allclose(a, b, rtol=1e-9, atol=1e-9)
    c = jv_core.single_diode_current(jv_sweep, 22.0, 1e-9, 1.5, 1e-6, 2000.0)
    m = jv_sweep <= 1.0            # beyond Voc the current is amperes and J*Rs is no longer negligible
    assert np.allclose(a[m], c[m], rtol=1e-4, atol=1e-5)


def test_dark_current_is_the_illuminated_model_without_photocurrent(dark_sweep):
    j_dark = dark_jv_core.dark_diode_current(dark_sweep, 1e-9, 1.8, 3.0, 5e4)
    assert np.all(j_dark[1:] > 0)
    # with Rs -> 0 it reduces to the conftest dark diode
    from conftest import dark_diode_jv
    ref = dark_diode_jv(dark_sweep, j0=1e-9, n=1.8, rsh=5e4)
    got = dark_jv_core.dark_diode_current(dark_sweep, 1e-9, 1.8, 0.0, 5e4)
    assert np.allclose(got, ref, rtol=1e-9, atol=1e-12)


# ---------------------------------------------------------------------------
# Illuminated fit
# ---------------------------------------------------------------------------
def test_illuminated_fit_recovers_all_five_parameters(jv_sweep):
    j = single_diode_jv(jv_sweep, **PARAMS)
    fit = jv_core.fit_single_diode(jv_sweep, j)
    assert fit["success"]
    assert fit["Jph"] == pytest.approx(PARAMS["jph"], rel=1e-3)
    assert fit["n"] == pytest.approx(PARAMS["n"], rel=0.02)
    assert np.log10(fit["J0"]) == pytest.approx(np.log10(PARAMS["j0"]), abs=0.15)
    assert fit["Rs"] == pytest.approx(PARAMS["rs"], rel=0.05)
    assert fit["Rsh"] == pytest.approx(PARAMS["rsh"], rel=0.05)
    assert fit["R2"] > 0.9999


def test_illuminated_fit_survives_noise_and_sign_convention(jv_sweep):
    rng = np.random.default_rng(0)
    j = single_diode_jv(jv_sweep, **PARAMS) + rng.normal(0, 0.02, len(jv_sweep))
    a = jv_core.fit_single_diode(jv_sweep, j)
    b = jv_core.fit_single_diode(jv_sweep, -j)
    for key in ("n", "Rs", "Rsh", "Jph"):
        assert a[key] == pytest.approx(b[key], rel=1e-3), key
    assert a["n"] == pytest.approx(PARAMS["n"], rel=0.05)
    assert a["Rs"] == pytest.approx(PARAMS["rs"], rel=0.15)


def test_illuminated_fit_rejects_a_dark_curve(jv_sweep):
    from conftest import dark_diode_jv
    fit = jv_core.fit_single_diode(jv_sweep, dark_diode_jv(jv_sweep))
    assert fit["success"] is False
    assert np.isnan(fit["n"])


# ---------------------------------------------------------------------------
# Dark fit and Cheung
# ---------------------------------------------------------------------------
DARK = dict(j0=2e-9, n=1.8, rs=5.0, rsh=5e4)


def test_dark_fit_recovers_series_resistance(dark_sweep):
    j = dark_jv_core.dark_diode_current(dark_sweep, **DARK)
    fit = dark_jv_core.fit_dark_diode(dark_sweep, j)
    assert fit["success"]
    assert fit["n"] == pytest.approx(DARK["n"], rel=0.02)
    assert np.log10(fit["J0_mA_cm2"]) == pytest.approx(np.log10(DARK["j0"]), abs=0.1)
    assert fit["Rs_Ohm_cm2"] == pytest.approx(DARK["rs"], rel=0.05)
    assert fit["Rsh_Ohm_cm2"] == pytest.approx(DARK["rsh"], rel=0.10)
    assert fit["R2_log"] > 0.9999


def test_sliding_window_ideality_is_biased_by_rs_but_full_fit_is_not(dark_sweep):
    """With Rs the ln(J)-V curve bends over at high bias; the windowed slope
    still finds a linear-looking stretch but n drifts. The full fit models
    the roll-off and is the method of record when Rs matters."""
    j = dark_jv_core.dark_diode_current(dark_sweep, j0=2e-9, n=1.8, rs=20.0, rsh=1e6)
    win = dark_jv_core.analyze_dark_diode(dark_sweep, j)
    full = dark_jv_core.fit_dark_diode(dark_sweep, j)
    assert abs(full["n"] - 1.8) < abs(win["n"] - 1.8) or abs(full["n"] - 1.8) < 0.02
    assert full["Rs_Ohm_cm2"] == pytest.approx(20.0, rel=0.1)


def test_cheung_series_resistance_and_ideality(dark_sweep):
    j = dark_jv_core.dark_diode_current(dark_sweep, j0=2e-9, n=1.8, rs=5.0, rsh=1e9)
    ch = dark_jv_core.cheung_analysis(dark_sweep, j)
    assert ch["Rs_Ohm_cm2"] == pytest.approx(5.0, rel=0.1)
    assert ch["n"] == pytest.approx(1.8, rel=0.1)
    assert ch["R2"] > 0.99


def test_degenerate_dark_inputs_return_nan():
    out = dark_jv_core.fit_dark_diode([], [])
    assert out["success"] is False and np.isnan(out["n"])
    assert np.isnan(dark_jv_core.cheung_analysis([0.1] * 3, [1e-6] * 3)["Rs_Ohm_cm2"])


# ---------------------------------------------------------------------------
# Scan direction and hysteresis
# ---------------------------------------------------------------------------
def _fwd_rev_sweep(hyst_scale=1.0):
    v_f = np.round(np.arange(-0.2, 1.1001, 0.01), 4)
    j_f = single_diode_jv(v_f, **PARAMS)
    # reverse scan: a slightly better diode (classic perovskite hysteresis)
    j_r = single_diode_jv(v_f, jph=22.0, j0=1e-9 / (3.0 ** hyst_scale), n=1.5, rs=1.5, rsh=4000.0)
    v = np.concatenate([v_f, v_f[::-1]])
    j = np.concatenate([j_f, j_r[::-1]])
    return v, j, v_f, j_f, j_r


def test_scan_segments_are_split_and_labelled():
    v, j, *_ = _fwd_rev_sweep()
    segs = jv_core.split_scan_directions(v, j)
    assert [s["direction"] for s in segs] == ["forward", "reverse"]
    assert len(segs[0]["v"]) + len(segs[1]["v"]) >= len(v)


def test_single_direction_sweep_has_one_segment(jv_sweep):
    segs = jv_core.split_scan_directions(jv_sweep, single_diode_jv(jv_sweep, **PARAMS))
    assert len(segs) == 1 and segs[0]["direction"] == "forward"


def test_hysteresis_index_definition():
    assert jv_core.hysteresis_index(20.0, 18.0) == pytest.approx(10.0)
    assert jv_core.hysteresis_index(20.0, 20.0) == 0.0
    assert np.isnan(jv_core.hysteresis_index(0.0, 1.0))
    assert np.isnan(jv_core.hysteresis_index(float("nan"), 1.0))


def test_hysteresis_analysis_matches_per_direction_parameters():
    v, j, v_f, j_f, j_r = _fwd_rev_sweep()
    res = jv_core.analyze_scan_hysteresis(v, j)
    assert res["n_segments"] == 2
    pf = jv_core.compute_jv_parameters(v_f, j_f)
    pr = jv_core.compute_jv_parameters(v_f, j_r)
    assert res["forward"]["PCE"] == pytest.approx(pf["PCE"], rel=1e-6)
    assert res["reverse"]["PCE"] == pytest.approx(pr["PCE"], rel=1e-6)
    assert res["HI"] == pytest.approx(jv_core.hysteresis_index(pr["PCE"], pf["PCE"]), rel=1e-9)
    assert res["HI"] > 0
    assert res["dVoc"] > 0


def test_hysteresis_free_device_has_zero_index():
    v_f = np.round(np.arange(-0.2, 1.1001, 0.01), 4)
    j_f = single_diode_jv(v_f, **PARAMS)
    res = jv_core.analyze_scan_hysteresis(np.concatenate([v_f, v_f[::-1]]),
                                          np.concatenate([j_f, j_f[::-1]]))
    assert res["HI"] == pytest.approx(0.0, abs=1e-6)


def test_jsc_mismatch_sign_and_nan():
    assert jv_core.jsc_mismatch(21.0, 20.0) == pytest.approx(5.0)
    assert jv_core.jsc_mismatch(19.0, 20.0) == pytest.approx(-5.0)
    assert np.isnan(jv_core.jsc_mismatch(19.0, 0.0))


def test_read_jv_curve_keeps_measurement_order(tmp_path):
    p = tmp_path / "cell 1.txt"
    rows = "\n".join(f"{v:.3f}\t{-0.001 * (1 - v):.6f}" for v in [0.0, 0.5, 1.0, 0.5, 0.0])
    p.write_text("header\nVmeas\tImeas\n" + rows + "\n", encoding="utf-8")
    v, j = jv_core.read_jv_curve(str(p), area_cm2=0.04)
    assert v.tolist() == [0.0, 0.5, 1.0, 0.5, 0.0]
    assert j[0] == pytest.approx(25.0)
    assert len(jv_core.split_scan_directions(v, j, min_points=3)) == 2
