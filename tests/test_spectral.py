"""Shared spectral primitives: baselines, line shapes, multi-peak fitting,
model selection, energy-axis conversion and peak matching.

All inputs are closed-form, so every tolerance below is a statement about the
algorithm rather than about the data.
"""
import math

import numpy as np
import pytest

from scripts.common import spectral as sp

X = np.linspace(0.0, 100.0, 1001)


# ---------------------------------------------------------------------------
# Line shapes
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("shape", ["gaussian", "lorentzian"])
def test_height_and_fwhm_parametrisation(shape):
    f = getattr(sp, shape)
    y = f(X, 3.0, 50.0, 8.0)
    assert y.max() == pytest.approx(3.0, rel=1e-6)
    assert sp.numeric_fwhm(X, y) == pytest.approx(8.0, rel=0.02)


def test_pseudo_voigt_limits():
    g = sp.gaussian(X, 1.0, 50.0, 6.0)
    l = sp.lorentzian(X, 1.0, 50.0, 6.0)
    assert np.allclose(sp.pseudo_voigt(X, 1.0, 50.0, 6.0, 0.0), g)
    assert np.allclose(sp.pseudo_voigt(X, 1.0, 50.0, 6.0, 1.0), l)


def test_voigt_fwhm_matches_numeric():
    sigma, gamma = 2.0, 1.5
    y = sp.voigt(X, 1.0, 50.0, sigma, gamma)
    assert y.max() == pytest.approx(1.0, rel=1e-9)
    assert sp.voigt_fwhm(sigma, gamma) == pytest.approx(sp.numeric_fwhm(X, y), rel=0.01)


@pytest.mark.parametrize("shape,eta", [("gaussian", None), ("lorentzian", None), ("pvoigt", 0.3)])
def test_analytic_area_equals_integral(shape, eta):
    x = np.linspace(-500, 500, 200001)
    if shape == "pvoigt":
        y = sp.pseudo_voigt(x, 2.0, 0.0, 5.0, eta)
        area = sp.peak_area(shape, 2.0, 5.0, eta)
    else:
        y = getattr(sp, shape)(x, 2.0, 0.0, 5.0)
        area = sp.peak_area(shape, 2.0, 5.0)
    # Lorentzian tails are long: 1% of the area lies outside +-500 FWHM/5
    assert sp.integrate(x, y) == pytest.approx(area, rel=0.01)


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------
def _spectrum_with_background():
    bg = 20.0 + 0.3 * X + 0.002 * X ** 2
    y = bg + sp.gaussian(X, 100.0, 40.0, 5.0) + sp.lorentzian(X, 60.0, 70.0, 4.0)
    return y, bg


def test_als_recovers_smooth_background():
    y, bg = _spectrum_with_background()
    b = sp.baseline_als(y, lam=1e6, p=0.001)
    off = (np.abs(X - 40) > 15) & (np.abs(X - 70) > 15)
    # ALS cannot follow a curved background exactly (it penalises curvature):
    # a few percent bias in the background is the documented price, while the
    # peak heights are preserved to within 3%.
    assert np.max(np.abs(b[off] - bg[off])) < 3.0
    net = y - b
    assert net[np.argmin(np.abs(X - 40))] == pytest.approx(100.0, rel=0.03)
    assert net[np.argmin(np.abs(X - 70))] == pytest.approx(60.0, rel=0.05)   # Lorentzian wings lift the baseline slightly


def test_arpls_recovers_background_without_asymmetry_parameter():
    y, bg = _spectrum_with_background()
    rng = np.random.default_rng(0)
    yn = y + rng.normal(0, 0.5, len(y))
    b = sp.baseline_arpls(yn, lam=1e5)
    off = (np.abs(X - 40) > 15) & (np.abs(X - 70) > 15)
    assert np.max(np.abs(b[off] - bg[off])) < 2.5
    # the peaks must survive baseline subtraction
    assert np.max(yn - b) > 90


def test_als_p_zero_is_clamped():
    y, _ = _spectrum_with_background()
    b0 = sp.baseline_als(y, lam=1e5, p=0.0)
    b1 = sp.baseline_als(y, lam=1e5, p=1e-4)
    assert np.allclose(b0, b1)


def test_shirley_background_on_synthetic_xps_line():
    """A Shirley background is, by construction, proportional to the
    integrated peak area to one side. Build a spectrum from a Gaussian plus
    exactly that background and check it is recovered on both axis orders."""
    be = np.linspace(280.0, 295.0, 301)           # binding energy, ascending
    peak = sp.gaussian(be, 1000.0, 285.0, 1.4)
    dx = be[1] - be[0]
    cum = np.cumsum(peak) * dx
    step = 300.0 * cum / cum[-1]                 # rises towards high BE
    y = 100.0 + step + peak
    b = sp.baseline_shirley(be, y)
    assert np.max(np.abs(b - (100.0 + step))) < 0.02 * 300.0
    # descending axis (as instruments export it) gives the same answer
    b2 = sp.baseline_shirley(be[::-1], y[::-1])
    assert np.allclose(b2[::-1], b, atol=1e-6)


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------
def test_fit_two_overlapping_gaussians():
    y = sp.gaussian(X, 10.0, 48.0, 6.0) + sp.gaussian(X, 6.0, 55.0, 5.0)
    res = sp.fit_peaks(X, y, [47.0, 56.0], shape="gaussian")
    assert res.success
    c = sorted(p.center for p in res.peaks)
    assert c[0] == pytest.approx(48.0, abs=0.05)
    assert c[1] == pytest.approx(55.0, abs=0.05)
    w = {round(p.center): p.fwhm for p in res.peaks}
    assert w[48] == pytest.approx(6.0, rel=0.02)
    assert w[55] == pytest.approx(5.0, rel=0.02)
    assert res.r2 > 0.9999
    assert len(res.components) == 2
    assert np.allclose(res.y_fit, sum(res.components), atol=1e-9)


def test_fit_with_linear_baseline():
    y = 3.0 + 0.05 * X + sp.lorentzian(X, 8.0, 60.0, 4.0)
    res = sp.fit_peaks(X, y, [59.0], shape="lorentzian", baseline="linear")
    assert res.success
    assert res.peaks[0].height == pytest.approx(8.0, rel=0.02)
    assert res.peaks[0].fwhm == pytest.approx(4.0, rel=0.03)
    assert res.baseline[1] == pytest.approx(0.05, rel=0.05)


def test_fit_pseudo_voigt_recovers_mixing():
    y = sp.pseudo_voigt(X, 5.0, 50.0, 7.0, 0.7)
    res = sp.fit_peaks(X, y, [50.5], shape="pvoigt")
    assert res.peaks[0].eta == pytest.approx(0.7, abs=0.03)
    assert res.peaks[0].fwhm == pytest.approx(7.0, rel=0.02)


def test_fit_voigt_recovers_widths():
    y = sp.voigt(X, 5.0, 50.0, 2.0, 1.0)
    res = sp.fit_peaks(X, y, [50.3], shape="voigt")
    assert res.success
    assert res.peaks[0].sigma == pytest.approx(2.0, rel=0.05)
    assert res.peaks[0].gamma == pytest.approx(1.0, rel=0.05)


def test_shared_width_constraint():
    y = sp.gaussian(X, 10.0, 40.0, 5.0) + sp.gaussian(X, 4.0, 60.0, 5.0)
    res = sp.fit_peaks(X, y, [40.0, 60.0], shape="gaussian", share_fwhm=True)
    assert res.success
    assert res.peaks[0].fwhm == pytest.approx(res.peaks[1].fwhm, rel=1e-9)
    assert res.peaks[0].fwhm == pytest.approx(5.0, rel=0.02)


def test_fit_failure_is_reported_not_raised():
    res = sp.fit_peaks(X, np.full_like(X, np.nan), [50.0])
    assert res.success is False


def test_fit_reports_parameter_uncertainties():
    rng = np.random.default_rng(1)
    y = sp.gaussian(X, 10.0, 50.0, 6.0) + rng.normal(0, 0.1, len(X))
    res = sp.fit_peaks(X, y, [50.0])
    p = res.peaks[0]
    assert 0 < p.center_err < 0.05
    assert 0 < p.fwhm_err < 0.2


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------
def test_aic_selects_two_components_for_a_doublet_and_one_for_a_singlet():
    rng = np.random.default_rng(2)
    doublet = (sp.gaussian(X, 10.0, 45.0, 6.0) + sp.gaussian(X, 5.0, 58.0, 6.0)
               + rng.normal(0, 0.05, len(X)))
    singlet = sp.gaussian(X, 10.0, 50.0, 6.0) + rng.normal(0, 0.05, len(X))
    assert len(sp.select_n_peaks(X, doublet, max_peaks=4).peaks) == 2
    assert len(sp.select_n_peaks(X, singlet, max_peaks=4).peaks) == 1


def test_information_criteria_penalise_parameters():
    assert sp.aic(100, 1.0, 3) < sp.aic(100, 1.0, 6)
    assert sp.bic(100, 1.0, 3) < sp.bic(100, 1.0, 6)
    assert sp.aic(0, 1.0, 3) == float("inf")


# ---------------------------------------------------------------------------
# Axis conversion
# ---------------------------------------------------------------------------
def test_energy_conversion_preserves_integrated_intensity():
    wl = np.linspace(600.0, 900.0, 3001)
    y = sp.gaussian(wl, 1000.0, 750.0, 40.0)
    e, ye = sp.spectrum_to_energy(wl, y)
    assert np.all(np.diff(e) > 0)
    assert sp.integrate(e, ye) == pytest.approx(sp.integrate(wl, y), rel=1e-3)


def test_jacobian_shifts_the_peak_relative_to_a_naive_conversion():
    """The textbook check: a Gaussian centred at 750 nm does NOT peak at
    hc/750 nm = 1.653 eV once the Jacobian is applied; the naive conversion
    does. The two must differ, and the Jacobian peak must sit lower."""
    wl = np.linspace(600.0, 900.0, 3001)
    y = sp.gaussian(wl, 1000.0, 750.0, 60.0)
    e_j, y_j = sp.spectrum_to_energy(wl, y, jacobian=True)
    e_n, y_n = sp.spectrum_to_energy(wl, y, jacobian=False)
    assert e_n[np.argmax(y_n)] == pytest.approx(sp.HC_EV_NM / 750.0, abs=2e-3)
    assert e_j[np.argmax(y_j)] < e_n[np.argmax(y_n)] - 0.002


def test_nm_ev_round_trip():
    assert sp.ev_to_nm(sp.nm_to_ev(532.0)) == pytest.approx(532.0)


# ---------------------------------------------------------------------------
# Peak finding / matching / misc
# ---------------------------------------------------------------------------
def test_robust_peak_finding_ignores_noise():
    rng = np.random.default_rng(3)
    y = sp.gaussian(X, 10.0, 30.0, 3.0) + sp.gaussian(X, 4.0, 70.0, 3.0) + rng.normal(0, 0.1, len(X))
    pos, idx, prom = sp.find_peaks_robust(X, y, prominence_frac=0.05, noise_k=6)
    assert len(pos) == 2
    assert pos[0] == pytest.approx(30.0, abs=0.5)
    assert pos[1] == pytest.approx(70.0, abs=0.5)


def test_find_peaks_handles_dips():
    y = 1.0 - sp.gaussian(X, 0.5, 40.0, 4.0)
    pos, _, _ = sp.find_peaks_robust(X, y, invert=True)
    assert len(pos) == 1 and pos[0] == pytest.approx(40.0, abs=0.2)


def test_match_peaks_is_one_to_one_within_tolerance():
    m = sp.match_peaks([100.0, 200.0, 300.0], [102.0, 203.5, 450.0], tolerance=5.0)
    assert [round(p["shift"], 1) for p in m["matched"]] == [2.0, 3.5]
    assert m["unmatched_reference"] == [300.0]
    assert m["unmatched_sample"] == [450.0]


def test_normalisation_modes():
    y = np.array([1.0, 2.0, 4.0])
    assert sp.normalize(y, "max").max() == 1.0
    assert sp.normalize(y, "area").sum() == pytest.approx(1.0)
    assert sp.normalize(y, "minmax").tolist() == [0.0, 1.0 / 3.0, 1.0]
    assert np.linalg.norm(sp.normalize(y, "vector")) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        sp.normalize(y, "bogus")


def test_centroid_of_symmetric_peak():
    y = sp.gaussian(X, 1.0, 42.0, 5.0)
    assert sp.centroid(X, y) == pytest.approx(42.0, abs=1e-6)
