"""Illuminated J-V: curve-derived device parameters.

Ground truth comes from the same single-diode model the data is generated from,
evaluated independently on a 200k-point grid (see conftest.single_diode_reference),
so each tolerance below characterises the extraction algorithm rather than the
resolution of the simulated sweep.
"""
import numpy as np
import pytest

from conftest import single_diode_jv, single_diode_reference
from scripts.JV.jv_core import compute_jv_parameters

PARAMS = dict(jph=22.0, j0=1e-9, n=1.5, rs=2.0, rsh=2000.0)


@pytest.fixture(scope="module")
def measured(jv_sweep):
    return jv_sweep, single_diode_jv(jv_sweep, **PARAMS)


@pytest.fixture(scope="module")
def truth():
    return single_diode_reference(**PARAMS)


def test_open_circuit_voltage(measured, truth):
    v, j = measured
    got = compute_jv_parameters(v, j)["Voc"]
    assert got == pytest.approx(truth["Voc"], abs=1e-3), \
        f"Voc {got:.4f} V vs truth {truth['Voc']:.4f} V"


def test_short_circuit_current(measured, truth):
    v, j = measured
    got = compute_jv_parameters(v, j)["Jsc"]
    assert got == pytest.approx(truth["Jsc"], rel=1e-4)


def test_fill_factor(measured, truth):
    v, j = measured
    got = compute_jv_parameters(v, j)["FF"]
    assert got == pytest.approx(truth["FF"], abs=0.5), \
        f"FF {got:.2f}% vs truth {truth['FF']:.2f}%"


def test_efficiency_is_consistent_with_pmax(measured):
    v, j = measured
    p = compute_jv_parameters(v, j, pin_mw_cm2=100.0)
    assert p["PCE"] == pytest.approx(p["Pmax"], rel=1e-9)
    assert p["FF"] == pytest.approx(100.0 * p["Pmax"] / (p["Jsc"] * p["Voc"]),
                                    rel=1e-9)


def test_non_standard_irradiance_scales_efficiency(measured):
    v, j = measured
    at_100 = compute_jv_parameters(v, j, pin_mw_cm2=100.0)["PCE"]
    at_50 = compute_jv_parameters(v, j, pin_mw_cm2=50.0)["PCE"]
    assert at_50 == pytest.approx(2.0 * at_100, rel=1e-9)


def test_shunt_resistance_recovered_from_slope(measured):
    """Rsh from the dV/dJ slope at short circuit, against the 2000 Ohm cm^2 input."""
    v, j = measured
    got = compute_jv_parameters(v, j)["Rsh"]
    assert got == pytest.approx(PARAMS["rsh"], rel=0.05), \
        f"Rsh {got:.1f} vs input {PARAMS['rsh']} Ohm cm^2"


def test_sign_convention_invariance(measured):
    """Source-meters export either sign; both must give identical parameters."""
    v, j = measured
    a = compute_jv_parameters(v, j)
    b = compute_jv_parameters(v, -j)
    for key in ("Voc", "Jsc", "FF", "PCE", "Pmax", "Rsh"):
        assert a[key] == pytest.approx(b[key], rel=1e-12), f"{key} differs"


def test_duplicate_voltages_are_averaged(measured, truth):
    """Merged forward/reverse sweeps repeat each voltage; they must collapse."""
    v, j = measured
    v2 = np.concatenate([v, v])
    j2 = np.concatenate([j, j])
    got = compute_jv_parameters(v2, j2)
    assert got["Voc"] == pytest.approx(truth["Voc"], abs=1e-3)
    assert got["Jsc"] == pytest.approx(truth["Jsc"], rel=1e-4)


def test_nan_points_are_ignored(measured, truth):
    v, j = measured
    j = j.copy()
    j[5] = np.nan
    j[-3] = np.nan
    assert compute_jv_parameters(v, j)["Voc"] == pytest.approx(truth["Voc"],
                                                               abs=1e-3)


@pytest.mark.parametrize("v,j", [
    ([], []),
    ([0.0, 0.1], [1.0, 0.5]),                      # fewer than 5 points
    ([0.5, 0.6, 0.7, 0.8, 0.9], [1, 1, 1, 1, 1]),  # V = 0 not bracketed
])
def test_degenerate_input_returns_nan_without_raising(v, j):
    out = compute_jv_parameters(v, j)
    assert all(np.isnan(x) for x in out.values())


def test_dark_curve_yields_no_parameters(jv_sweep):
    """A curve with no photocurrent must not report a fabricated Voc/PCE."""
    from conftest import dark_diode_jv
    j = dark_diode_jv(jv_sweep)
    out = compute_jv_parameters(jv_sweep, j)
    assert np.isnan(out["PCE"])
