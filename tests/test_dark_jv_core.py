"""Dark J-V: diode ideality factor, saturation current and shunt resistance.

Two synthetic curves are used, because they exercise different things:

  `clean_diode`   -- shunt made negligible, so the recovered n and J0 can be
                     compared against the values that went in.
  `shunted_diode` -- a 5e4 Ohm cm^2 shunt, which is what the low-bias ohmic
                     slope is measured from, and which also demonstrates the
                     documented upward bias it imposes on n.
"""
import numpy as np
import pytest

from conftest import dark_diode_jv
from scripts.Dark_JV.dark_jv_core import analyze_dark_diode

N_TRUE = 1.85
J0_TRUE = 1e-9        # mA/cm^2
RSH_TRUE = 5.0e4      # Ohm cm^2


@pytest.fixture(scope="module")
def clean_diode(dark_sweep):
    return dark_sweep, dark_diode_jv(dark_sweep, j0=J0_TRUE, n=N_TRUE,
                                     rsh=1.0e12)


@pytest.fixture(scope="module")
def shunted_diode(dark_sweep):
    return dark_sweep, dark_diode_jv(dark_sweep, j0=J0_TRUE, n=N_TRUE,
                                     rsh=RSH_TRUE)


# ---------------------------------------------------------------------------
# Diode parameters
# ---------------------------------------------------------------------------
def test_ideality_factor(clean_diode):
    v, j = clean_diode
    got = analyze_dark_diode(v, j)["n"]
    assert got == pytest.approx(N_TRUE, rel=0.02), \
        f"n {got:.4f} vs input {N_TRUE}"


def test_saturation_current(clean_diode):
    """J0 spans decades, so it is compared in log space."""
    v, j = clean_diode
    got = analyze_dark_diode(v, j)["J0_mA_cm2"]
    assert np.log10(got) == pytest.approx(np.log10(J0_TRUE), abs=0.15), \
        f"J0 {got:.4e} vs input {J0_TRUE:.4e} mA/cm^2"


def test_selected_window_is_linear_and_in_the_diode_region(clean_diode):
    v, j = clean_diode
    out = analyze_dark_diode(v, j)
    assert out["fit_R2"] > 0.999
    assert out["fit_Vmin"] >= 0.15
    assert out["fit_Vmax"] > out["fit_Vmin"]


@pytest.mark.parametrize("n_true", [1.0, 1.5, 2.0, 2.5])
def test_ideality_across_the_physical_range(dark_sweep, n_true):
    j = dark_diode_jv(dark_sweep, j0=J0_TRUE, n=n_true, rsh=1.0e12)
    got = analyze_dark_diode(dark_sweep, j)["n"]
    assert got == pytest.approx(n_true, rel=0.03)


def test_temperature_enters_only_through_the_thermal_voltage(dark_sweep):
    """n = 1 / ((kT/q) * d(lnJ)/dV): the fitted slope does not depend on the

    assumed temperature, so mis-declaring T must scale n by exactly T_wrong /
    T_true and nothing else.
    """
    j = dark_diode_jv(dark_sweep, j0=J0_TRUE, n=N_TRUE, rsh=1.0e12,
                      temperature_k=350.0)
    at_350 = analyze_dark_diode(dark_sweep, j, temperature_k=350.0)
    at_298 = analyze_dark_diode(dark_sweep, j, temperature_k=298.15)

    assert at_350["n"] == pytest.approx(N_TRUE, rel=0.02)
    assert at_298["n"] / at_350["n"] == pytest.approx(350.0 / 298.15, rel=1e-6)
    # only n is rescaled; the selected window is unchanged
    assert at_298["fit_Vmin"] == at_350["fit_Vmin"]
    assert at_298["fit_R2"] == pytest.approx(at_350["fit_R2"], rel=1e-12)


# ---------------------------------------------------------------------------
# Shunt
# ---------------------------------------------------------------------------
def test_dark_shunt_resistance(shunted_diode):
    v, j = shunted_diode
    got = analyze_dark_diode(v, j)["Rsh_dark_Ohm_cm2"]
    assert got == pytest.approx(RSH_TRUE, rel=0.05), \
        f"Rsh {got:.4g} vs input {RSH_TRUE:.4g} Ohm cm^2"


def test_window_selection_steps_over_the_shunt_region(clean_diode, shunted_diode):
    """A shunt flattens ln(J) vs V at low forward bias, and fitting a fixed

    voltage window there would bias n upward. Because the window is chosen by
    maximising R^2 rather than fixed in advance, it slides up the sweep until
    it clears the shunt -- so n stays accurate on a shunted device.
    """
    clean = analyze_dark_diode(*clean_diode)
    shunted = analyze_dark_diode(*shunted_diode)

    assert shunted["fit_Vmin"] > clean["fit_Vmin"], (
        "window did not move away from the shunt-dominated region "
        f"(clean {clean['fit_Vmin']:.3f} V, shunted {shunted['fit_Vmin']:.3f} V)"
    )
    assert shunted["n"] == pytest.approx(N_TRUE, rel=0.02), \
        f"n {shunted['n']:.4f} on a shunted device vs input {N_TRUE}"
    assert shunted["fit_R2"] > 0.999


# ---------------------------------------------------------------------------
# Numerical precision
# ---------------------------------------------------------------------------
def test_low_current_decades_survive(dark_sweep):
    """Regression: dark currents were once rounded to 2 decimal places before

    analysis. On a curve whose whole exponential region sits below 1e-2
    mA/cm^2 that erases every point, and the ideality factor becomes
    unrecoverable -- which is exactly what this asserts.
    """
    v = dark_sweep[dark_sweep <= 0.6]
    j = dark_diode_jv(v, j0=1e-12, n=N_TRUE, rsh=1.0e15)
    assert np.max(j) < 1e-2, "fixture no longer exercises the low-current case"

    assert analyze_dark_diode(v, j)["n"] == pytest.approx(N_TRUE, rel=0.02)
    assert np.isnan(analyze_dark_diode(v, np.round(j, 2))["n"])


@pytest.mark.parametrize("v,j", [([], []), ([0.1] * 4, [1e-6] * 4)])
def test_degenerate_input_returns_nan_without_raising(v, j):
    out = analyze_dark_diode(v, j)
    assert all(np.isnan(x) for x in out.values())


def test_unphysical_ideality_is_rejected(dark_sweep):
    """A curve whose slope implies n outside [0.5, 10] must report NaN rather

    than a number no one can interpret.
    """
    j = 1e-6 * np.exp(dark_sweep / 5.0)   # n ~ 195
    assert np.isnan(analyze_dark_diode(dark_sweep, j)["n"])
