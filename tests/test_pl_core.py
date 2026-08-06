"""Photoluminescence: ALS baseline correction and windowed peak fitting."""
import numpy as np
import pytest

from conftest import gaussian
from scripts.PL.pl_core import (calculate_quenching_efficiency,
                                fit_peak_gaussian, process_spectrum)

WAVELENGTH = np.round(np.arange(600.0, 900.0 + 1e-9, 0.5), 4)
CENTER, FWHM, AMP = 750.0, 40.0, 1000.0


def sloping_background(x):
    return 80.0 + 0.35 * (x - x[0])


@pytest.fixture(scope="module")
def spectrum():
    return WAVELENGTH, gaussian(WAVELENGTH, AMP, CENTER, FWHM) + sloping_background(WAVELENGTH)


# ---------------------------------------------------------------------------
# ALS baseline
# ---------------------------------------------------------------------------
def test_baseline_correction_recovers_the_peak(spectrum):
    x, y = spectrum
    _, baseline, y_corr = process_spectrum(x, y, filter_width=5, rigidity=8,
                                           protection=0.01)
    assert np.max(y_corr) == pytest.approx(AMP, rel=0.02)
    off_peak = np.abs(x - CENTER) > 3 * FWHM
    assert np.max(np.abs(baseline[off_peak] - sloping_background(x)[off_peak])) < 0.05 * AMP


def test_rigidity_controls_how_much_of_the_peak_the_baseline_eats(spectrum):
    """A baseline that is too flexible follows the peak instead of the

    background and removes part of the signal. The recovered amplitude must
    therefore increase monotonically with rigidity and converge on the true
    one -- the user-facing consequence is that the rigidity has to be scaled to
    the peak width and the sampling interval, which the paper needs to state.
    """
    x, y = spectrum
    recovered = [float(np.max(process_spectrum(x, y, 5, rigidity, 0.01)[2]))
                 for rigidity in (4, 5, 6, 7, 8, 9, 10)]
    assert all(b > a for a, b in zip(recovered, recovered[1:])), recovered
    assert recovered[0] < 0.5 * AMP        # lam=1e4 destroys half the peak
    assert recovered[-1] == pytest.approx(AMP, rel=0.01)


def test_zero_protection_does_not_collapse_the_spectrum(spectrum):
    """Regression: the GUI slider defaults to 0, and ALS with p = 0 turns the

    baseline into the UPPER envelope of the spectrum -- the corrected signal
    then went identically to zero and the peak simply vanished. The asymmetry
    parameter is clamped into (0, 0.5] to prevent that.
    """
    x, y = spectrum
    _, _, y_corr = process_spectrum(x, y, filter_width=5, rigidity=6,
                                    protection=0.0)
    assert np.max(y_corr) > 0.5 * AMP, "peak collapsed at protection = 0"


def test_protection_is_clamped_at_both_ends(spectrum):
    x, y = spectrum
    peak_at = {}
    for protection in (-1.0, 0.0, 1e-3, 0.5, 5.0):
        _, _, y_corr = process_spectrum(x, y, filter_width=5, rigidity=6,
                                        protection=protection)
        peak_at[protection] = float(np.max(y_corr))
    assert peak_at[-1.0] == pytest.approx(peak_at[1e-3], rel=1e-9)
    assert peak_at[0.0] == pytest.approx(peak_at[1e-3], rel=1e-9)
    assert peak_at[5.0] == pytest.approx(peak_at[0.5], rel=1e-9)


def test_zero_rigidity_disables_the_baseline(spectrum):
    x, y = spectrum
    _, baseline, _ = process_spectrum(x, y, filter_width=5, rigidity=0,
                                      protection=0.01)
    assert np.allclose(baseline, 0.0)


def test_even_filter_width_is_made_odd(spectrum):
    """Savitzky-Golay requires an odd window; an even one must not raise."""
    x, y = spectrum
    a = process_spectrum(x, y, filter_width=6, rigidity=6, protection=0.01)[2]
    b = process_spectrum(x, y, filter_width=7, rigidity=6, protection=0.01)[2]
    assert np.allclose(a, b)


# ---------------------------------------------------------------------------
# Peak fitting
# ---------------------------------------------------------------------------
def test_single_peak_center_and_width(spectrum):
    x, y = spectrum
    _, _, y_corr = process_spectrum(x, y, filter_width=5, rigidity=8,
                                    protection=0.01)
    fit = fit_peak_gaussian(x, y_corr)
    assert fit["success"]
    assert fit["center"] == pytest.approx(CENTER, abs=0.5)
    assert fit["fwhm"] == pytest.approx(FWHM, rel=0.02)


def naive_full_range_fit(x, y):
    """What fitting the whole spectrum, unwindowed, would give."""
    from scipy.optimize import curve_fit
    popt, _ = curve_fit(lambda xx, a, c, s: a * np.exp(-(xx - c) ** 2 / (2 * s ** 2)),
                        x, y, p0=[float(np.max(y)), float(x[np.argmax(y)]),
                                  FWHM / 2.35482], maxfev=10000)
    return {"center": popt[1], "fwhm": 2.35482 * abs(popt[2])}


@pytest.mark.parametrize("label,amp,center,fwhm", [
    ("defect band, red side", 0.35 * AMP, 830.0, 70.0),
    ("shoulder, blue side", 0.30 * AMP, 680.0, 60.0),
])
def test_neighbouring_band_bias_is_halved_by_windowing(label, amp, center, fwhm):
    """A neighbouring band must not drag the main peak.

    The window is cut at the valley between the two bands. The earlier rule --
    walk outward until the signal drops below 10% of the maximum -- never
    triggered here, because such a band holds the signal above that line all
    the way to the end of the spectrum; the "windowed" fit then silently
    degenerated into the very full-range fit it was meant to replace (identical
    to three decimal places).

    A residual bias survives and is asserted rather than wished away: the
    valley-bounded window still contains part of the neighbour's tail, and a
    single Gaussian cannot represent that. Removing it entirely needs
    simultaneous multi-component fitting, which the PL core does not do (the
    `spectra` package does, via AIC-selected Voigt components).
    """
    x = WAVELENGTH
    y = gaussian(x, AMP, CENTER, FWHM) + gaussian(x, amp, center, fwhm)

    fit = fit_peak_gaussian(x, y)
    assert fit["success"]
    assert fit["center"] == pytest.approx(CENTER, abs=1.5), \
        f"{label}: centre pulled to {fit['center']:.2f} nm"
    assert fit["fwhm"] == pytest.approx(FWHM, rel=0.10), \
        f"{label}: FWHM {fit['fwhm']:.2f} nm"

    naive = naive_full_range_fit(x, y)
    assert abs(fit["fwhm"] - FWHM) < 0.55 * abs(naive["fwhm"] - FWHM), (
        f"{label}: windowing gained nothing -- windowed FWHM "
        f"{fit['fwhm']:.2f} vs full-range {naive['fwhm']:.2f} (truth {FWHM})"
    )
    assert abs(fit["center"] - CENTER) < abs(naive["center"] - CENTER)


def test_isolated_peak_is_unaffected_by_the_valley_rule(spectrum):
    """The valley cut must not clip a peak that has no neighbour."""
    x, y = spectrum
    fit = fit_peak_gaussian(x, y - sloping_background(x))
    assert fit["center"] == pytest.approx(CENTER, abs=0.1)
    assert fit["fwhm"] == pytest.approx(FWHM, rel=0.02)


def test_fit_curve_is_returned_over_the_full_range(spectrum):
    x, y = spectrum
    fit = fit_peak_gaussian(x, y - sloping_background(x))
    assert fit["y_fit"].shape == x.shape


def test_failed_fit_reports_failure_instead_of_raising():
    x = WAVELENGTH
    out = fit_peak_gaussian(x, np.full_like(x, -1.0))
    assert out["success"] is False
    assert out["fwhm"] == 0


# ---------------------------------------------------------------------------
# Quenching
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("factor,expected", [(1.0, 0.0), (0.4, 0.6), (0.0, 1.0)])
def test_quenching_efficiency(factor, expected):
    ref = gaussian(WAVELENGTH, AMP, CENTER, FWHM)
    eta, _, _ = calculate_quenching_efficiency(factor * ref, ref)
    assert eta == pytest.approx(expected, abs=1e-9)


def test_quenching_against_zero_reference_is_safe():
    ref = np.zeros_like(WAVELENGTH)
    eta, _, _ = calculate_quenching_efficiency(ref, ref)
    assert eta == 0.0
