"""XRD line-broadening analysis, Kalpha2 stripping, crystallinity, lattice
parameter and texture coefficient."""
import math

import numpy as np
import pytest

from conftest import pseudo_voigt
from scripts.XRD import xrd_core as xc


def test_scherrer_matches_the_closed_form_and_corrects_the_instrument():
    tau = xc.scherrer_size(28.4, 0.20)
    theta = math.radians(14.2)
    assert tau == pytest.approx(0.9 * xc.LAMBDA_CU / 10 / (math.radians(0.20) * math.cos(theta)), rel=1e-9)
    assert xc.scherrer_size(28.4, 0.20, instrumental_fwhm_deg=0.08) > tau
    assert np.isnan(xc.scherrer_size(28.4, 0.05, instrumental_fwhm_deg=0.08))
    assert xc.scherrer_size(28.4, 0.20, 0.05, breadth="linear") == pytest.approx(xc.scherrer_size(28.4, 0.15), rel=1e-9)


def test_williamson_hall_recovers_size_and_strain():
    """Build FWHMs from a known D and epsilon, then invert them."""
    d_nm, eps = 40.0, 2.0e-3
    two_theta = np.array([14.1, 20.0, 24.5, 28.4, 31.9, 35.0, 40.6, 43.2])
    theta = np.radians(two_theta / 2)
    beta = (0.9 * xc.LAMBDA_CU / 10 / d_nm) / np.cos(theta) + 4 * eps * np.tan(theta)   # radians
    fwhm = np.degrees(beta)
    wh = xc.williamson_hall(two_theta, fwhm)
    assert wh["n_peaks"] == 8
    assert wh["D_nm"] == pytest.approx(d_nm, rel=1e-6)
    assert wh["strain"] == pytest.approx(eps, rel=1e-6)
    assert wh["R2"] == pytest.approx(1.0, abs=1e-9)
    assert wh["D_err_nm"] < 1e-6


def test_williamson_hall_instrument_correction_and_minimum_peaks():
    two_theta = np.array([14.1, 28.4, 43.2])
    fwhm = np.array([0.20, 0.24, 0.30])
    raw = xc.williamson_hall(two_theta, fwhm)
    corr = xc.williamson_hall(two_theta, fwhm, instrumental_fwhm_deg=0.06)
    assert corr["D_nm"] > raw["D_nm"]
    assert np.isnan(xc.williamson_hall([28.4], [0.2])["D_nm"])
    two = xc.williamson_hall([14.1, 28.4], [0.20, 0.24])
    assert two["n_peaks"] == 2 and np.isfinite(two["D_nm"]) and np.isnan(two["D_err_nm"])


def test_kalpha2_stripping_removes_the_satellite():
    """A Kalpha1 line at 2theta_1 is accompanied by a Kalpha2 line of half the
    height at the angle where lambda2 diffracts from the same d. After
    stripping, the satellite must be gone and the main line untouched."""
    x = np.round(np.arange(60.0, 70.0 + 1e-9, 0.01), 4)
    c1 = 65.0
    d = xc.LAMBDA_CU_KA1 / (2 * math.sin(math.radians(c1 / 2)))
    c2 = 2 * math.degrees(math.asin(xc.LAMBDA_CU_KA2 / (2 * d)))
    y = pseudo_voigt(x, 1000.0, c1, 0.08, 0.5) + pseudo_voigt(x, 500.0, c2, 0.08, 0.5) + 20.0
    stripped = xc.strip_kalpha2(x, y)
    i2 = int(np.argmin(np.abs(x - c2)))
    i1 = int(np.argmin(np.abs(x - c1)))
    # a flat background B also contains a Kalpha2 share: it becomes B/(1+r)
    flat = (x > 61.0) & (x < 63.5)
    assert np.median(stripped[flat]) == pytest.approx(20.0 / 1.5, rel=0.02)
    bg = float(np.median(stripped[flat]))
    assert stripped[i1] - bg == pytest.approx(1000.0, rel=0.03)         # main line kept
    assert stripped[i2] - bg < 0.08 * 500.0                              # satellite removed to < 8%


def test_crystallinity_index_of_peaks_on_an_amorphous_hump():
    x = np.round(np.arange(10.0, 60.0 + 1e-9, 0.02), 4)
    hump = 300.0 * np.exp(-((x - 25.0) / 12.0) ** 2)
    peaks = pseudo_voigt(x, 2000.0, 28.4, 0.3, 0.5) + pseudo_voigt(x, 900.0, 40.6, 0.35, 0.5)
    ci = xc.crystallinity_index(x, hump + peaks, baseline=hump)
    trap = getattr(np, "trapezoid", None) or np.trapz
    expected = 100.0 * trap(peaks, x) / trap(hump + peaks, x)
    assert ci["CI_percent"] == pytest.approx(expected, rel=1e-9)
    auto = xc.crystallinity_index(x, hump + peaks)                      # ALS-estimated amorphous part
    assert auto["CI_percent"] == pytest.approx(expected, rel=0.15)


def test_cubic_lattice_parameter_and_nelson_riley():
    a0 = 6.28       # Angstrom, cubic perovskite-like
    hkl = [(1, 0, 0), (1, 1, 0), (1, 1, 1), (2, 0, 0), (2, 1, 0), (2, 1, 1), (2, 2, 0)]
    d = a0 / np.sqrt(np.sum(np.asarray(hkl, float) ** 2, axis=1))
    two_theta = 2 * np.degrees(np.arcsin(xc.LAMBDA_CU / (2 * d)))
    res = xc.lattice_parameter_cubic(two_theta, hkl)
    assert res["a_mean_A"] == pytest.approx(a0, rel=1e-9)
    assert res["a_NR_A"] == pytest.approx(a0, abs=1e-6)
    # a specimen-displacement error scales with cos^2(theta)/sin(theta): the
    # Nelson-Riley extrapolation removes most of it while the mean does not
    # specimen displacement shifts 2theta by an amount proportional to cos(theta)
    theta = np.radians(two_theta / 2)
    shifted = two_theta + 0.08 * np.cos(theta)
    res2 = xc.lattice_parameter_cubic(shifted, hkl)
    assert abs(res2["a_NR_A"] - a0) < abs(res2["a_mean_A"] - a0)
    with pytest.raises(ValueError):
        xc.lattice_parameter_cubic([14.1, 28.4], [(1, 0, 0)])


def test_strain_and_texture_coefficient():
    assert xc.lattice_strain(6.30, 6.28) == pytest.approx(0.02 / 6.28)
    tc = xc.texture_coefficient([100, 50, 30], [100, 50, 30])
    assert np.allclose(tc, 1.0)
    tc2 = xc.texture_coefficient([300, 50, 30], [100, 50, 30])
    assert tc2[0] > 1.0 and tc2[1] < 1.0
    assert np.mean(tc2) == pytest.approx(1.0)


def test_d_spacing_is_bragg():
    assert xc.d_spacing(28.4) == pytest.approx(xc.LAMBDA_CU / (2 * math.sin(math.radians(14.2))))
