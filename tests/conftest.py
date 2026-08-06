"""Shared fixtures: closed-form synthetic measurements with known ground truth.

Every generator here produces data from an analytical model whose parameters are
known exactly, so a test can compare a recovered parameter against the value that
was put in. This is the evidence base for the validation section of the paper.
"""
import os
import sys

import numpy as np
import pytest
from scipy.optimize import brentq

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

Q = 1.602176634e-19
KB = 1.380649e-23


def thermal_voltage(temperature_k: float = 298.15) -> float:
    """kT/q [V]."""
    return KB * temperature_k / Q


# ----------------------------------------------------------------------------
# Illuminated J-V: single-diode model with series and shunt resistance
# ----------------------------------------------------------------------------
def single_diode_jv(v, jph=22.0, j0=1e-9, n=1.5, rs=2.0, rsh=2000.0,
                    temperature_k=298.15):
    """Solve J = Jph - J0*(exp(q(V+J*Rs)/nkT) - 1) - (V + J*Rs)/Rsh for J.

    Units: V [V], Jph/J0/J [mA/cm^2], Rs/Rsh [Ohm cm^2].
    Returned J uses the photocurrent-positive convention (J > 0 at V = 0).
    The equation is implicit in J because of the Rs drop, so each point is
    bracketed and solved numerically -- the model itself stays exact.
    """
    vt = n * thermal_voltage(temperature_k)

    def residual(j, v_point):
        v_junction = v_point + (j / 1000.0) * rs          # [V]
        return (jph
                - j0 * np.expm1(np.clip(v_junction / vt, -700, 700))
                - 1000.0 * v_junction / rsh
                - j)

    out = np.empty(len(np.atleast_1d(v)), dtype=float)
    for i, v_point in enumerate(np.atleast_1d(v)):
        out[i] = brentq(residual, -1.0e3, 1.0e3, args=(v_point,),
                        xtol=1e-12, rtol=1e-14)
    return out


def single_diode_reference(jph=22.0, j0=1e-9, n=1.5, rs=2.0, rsh=2000.0,
                           temperature_k=298.15, pin_mw_cm2=100.0):
    """Ground-truth Voc/Jsc/FF/PCE for the same model, on a very dense grid.

    Independent of the code under test: the tolerance a test asserts is then a
    statement about the extraction algorithm, not about grid resolution.
    """
    jsc = float(single_diode_jv([0.0], jph, j0, n, rs, rsh, temperature_k)[0])

    def j_at(v_point):
        return float(single_diode_jv([v_point], jph, j0, n, rs, rsh,
                                     temperature_k)[0])

    voc = brentq(j_at, 0.0, 2.0, xtol=1e-12, rtol=1e-14)

    grid = np.linspace(0.0, voc, 200_001)
    power = grid * single_diode_jv(grid, jph, j0, n, rs, rsh, temperature_k)
    i_max = int(np.argmax(power))
    pmax = float(power[i_max])

    return {
        "Voc": float(voc),
        "Jsc": jsc,
        "Pmax": pmax,
        "Vmpp": float(grid[i_max]),
        "FF": 100.0 * pmax / (jsc * voc),
        "PCE": 100.0 * pmax / pin_mw_cm2,
        "Rsh": rsh,
        "Rs": rs,
    }


# ----------------------------------------------------------------------------
# Dark J-V: diode in parallel with a shunt
# ----------------------------------------------------------------------------
def dark_diode_jv(v, j0=1e-9, n=1.85, rsh=5.0e4, temperature_k=298.15):
    """|J| [mA/cm^2] for a dark diode + shunt, no series resistance.

    Rs is omitted deliberately: analyze_dark_diode fits ln(J) vs V over a
    sliding window and the series-resistance roll-off at high bias would move
    the ground truth away from the nominal n, making the test ambiguous about
    what it is measuring.
    """
    v = np.asarray(v, dtype=float)
    vt = n * thermal_voltage(temperature_k)
    j_diode = j0 * np.expm1(np.clip(v / vt, -700, 700))
    j_shunt = 1000.0 * v / rsh
    return np.abs(j_diode + j_shunt)


# ----------------------------------------------------------------------------
# Spectral line shapes
# ----------------------------------------------------------------------------
def pseudo_voigt(x, height, center, fwhm, eta):
    """Normalized-to-`height` pseudo-Voigt, matching xrd_core's definition."""
    x = np.asarray(x, dtype=float)
    sigma = fwhm / 2.35482
    gauss = np.exp(-((x - center) ** 2) / (2.0 * sigma ** 2))
    lorentz = (fwhm / 2.0) ** 2 / ((x - center) ** 2 + (fwhm / 2.0) ** 2)
    return height * (eta * lorentz + (1.0 - eta) * gauss)


def gaussian(x, amp, center, fwhm):
    sigma = fwhm / 2.35482
    return amp * np.exp(-((np.asarray(x, dtype=float) - center) ** 2)
                        / (2.0 * sigma ** 2))


# ----------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------
@pytest.fixture(scope="session")
def jv_sweep():
    """Voltage grid typical of a real sweep: -0.2 to 1.1 V in 10 mV steps."""
    return np.round(np.arange(-0.20, 1.1001, 0.01), 4)


@pytest.fixture(scope="session")
def dark_sweep():
    return np.round(np.arange(0.0, 1.2001, 0.005), 4)


@pytest.fixture(scope="session")
def project_root():
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def rawdata_dir(project_root):
    path = os.path.join(project_root, "rawdata")
    if not os.path.isdir(path):
        pytest.skip("rawdata/ not present")
    return path
