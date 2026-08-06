"""XRD: global background, simultaneous fitting of overlapping reflections,
Bragg d-spacing and Scherrer crystallite size.

The central claim under test is that overlapping reflections are fitted as one
system. Fitting them independently and subtracting a local minimum under each
double-counts the shared tail and biases both the position and the width, which
propagates straight into the Scherrer size.
"""
import os

import numpy as np
import pytest

from conftest import pseudo_voigt
from scripts.XRD import xrd_core
from scripts.XRD.xrd_core import LAMBDA_CU, detect_peaks_and_fit

TWO_THETA = np.round(np.arange(10.0, 40.0 + 1e-9, 0.02), 4)


def background(x):
    """Smooth, monotonically decaying amorphous/air-scatter background."""
    return 300.0 * np.exp(-(x - 10.0) / 25.0) + 40.0


@pytest.fixture(scope="module")
def overlapping_doublet():
    """Two reflections separated by 0.4 deg -- close enough that their tails
    overlap inside a shared fit window."""
    truth = [
        dict(height=1000.0, center=28.20, fwhm=0.150, eta=0.5),
        dict(height=700.0, center=28.60, fwhm=0.180, eta=0.5),
    ]
    y = background(TWO_THETA)
    for peak in truth:
        y = y + pseudo_voigt(TWO_THETA, **peak)
    return TWO_THETA, y, truth


def matched(peaks_df, center, tol=0.2):
    hit = peaks_df[(peaks_df["2Theta"] - center).abs() < tol]
    assert len(hit) == 1, (
        f"expected exactly one peak near {center} deg, got "
        f"{hit['2Theta'].tolist()}"
    )
    return hit.iloc[0]


def test_both_overlapping_peaks_are_resolved(overlapping_doublet):
    x, y, truth = overlapping_doublet
    peaks_df, _ = detect_peaks_and_fit(x, y)
    assert len(peaks_df) == 2, f"resolved {len(peaks_df)} of 2 reflections"


def test_overlapping_peak_positions(overlapping_doublet):
    x, y, truth = overlapping_doublet
    peaks_df, _ = detect_peaks_and_fit(x, y)
    for peak in truth:
        got = matched(peaks_df, peak["center"])["2Theta"]
        assert got == pytest.approx(peak["center"], abs=0.01), \
            f"center {got:.4f} vs truth {peak['center']}"


def test_overlapping_peak_widths(overlapping_doublet):
    """FWHM is the quantity Scherrer sizes are computed from, so it carries the
    tightest requirement of anything the fit produces."""
    x, y, truth = overlapping_doublet
    peaks_df, _ = detect_peaks_and_fit(x, y)
    for peak in truth:
        got = matched(peaks_df, peak["center"])["FWHM"]
        assert got == pytest.approx(peak["fwhm"], rel=0.05), \
            f"FWHM {got:.4f} vs truth {peak['fwhm']}"


def test_fit_quality_is_reported(overlapping_doublet):
    x, y, truth = overlapping_doublet
    peaks_df, y_fit = detect_peaks_and_fit(x, y)
    assert (peaks_df["Fit_R2"] > 0.99).all()
    residual = y - y_fit
    assert np.max(np.abs(residual)) < 0.05 * np.max(y - background(x))


def test_d_spacing_follows_bragg(overlapping_doublet):
    x, y, _ = overlapping_doublet
    peaks_df, _ = detect_peaks_and_fit(x, y)
    for _, row in peaks_df.iterrows():
        expected = LAMBDA_CU / (2.0 * np.sin(np.radians(row["2Theta"] / 2.0)))
        assert row["d_spacing"] == pytest.approx(expected, rel=1e-9)


def test_scherrer_matches_closed_form(overlapping_doublet):
    x, y, _ = overlapping_doublet
    peaks_df, _ = detect_peaks_and_fit(x, y, scherrer_k=0.9)
    for _, row in peaks_df.iterrows():
        theta = np.radians(row["2Theta"] / 2.0)
        beta = np.radians(row["FWHM"])
        expected_nm = (0.9 * LAMBDA_CU / 10.0) / (beta * np.cos(theta))
        assert row["Crystallite_nm"] == pytest.approx(expected_nm, rel=1e-9)


def test_instrumental_broadening_is_deconvolved(overlapping_doublet):
    """beta = sqrt(FWHM^2 - FWHM_inst^2): correcting for the instrument must
    narrow beta and therefore report a LARGER crystallite size."""
    x, y, _ = overlapping_doublet
    uncorrected, _ = detect_peaks_and_fit(x, y, instrumental_fwhm_deg=0.0)
    corrected, _ = detect_peaks_and_fit(x, y, instrumental_fwhm_deg=0.05)
    for center in (28.20, 28.60):
        a = matched(uncorrected, center)
        b = matched(corrected, center)
        assert b["Crystallite_nm"] > a["Crystallite_nm"]

        beta = np.sqrt(np.radians(a["FWHM"]) ** 2 - np.radians(0.05) ** 2)
        theta = np.radians(b["2Theta"] / 2.0)
        assert b["Crystallite_nm"] == pytest.approx(
            (0.9 * LAMBDA_CU / 10.0) / (beta * np.cos(theta)), rel=1e-6)


def test_scherrer_k_is_applied_linearly(overlapping_doublet):
    x, y, _ = overlapping_doublet
    a, _ = detect_peaks_and_fit(x, y, scherrer_k=0.9)
    b, _ = detect_peaks_and_fit(x, y, scherrer_k=1.0)
    ratio = (matched(b, 28.20)["Crystallite_nm"]
             / matched(a, 28.20)["Crystallite_nm"])
    assert ratio == pytest.approx(1.0 / 0.9, rel=1e-6)


def test_global_background_is_removed_not_the_signal(overlapping_doublet):
    """The reported intensity is peak height above the fitted background, so a
    constant offset added to the whole pattern must not change it."""
    x, y, _ = overlapping_doublet
    base, _ = detect_peaks_and_fit(x, y)
    shifted, _ = detect_peaks_and_fit(x, y + 500.0)
    assert (matched(shifted, 28.20)["2Theta"]
            == pytest.approx(matched(base, 28.20)["2Theta"], abs=0.005))
    assert (matched(shifted, 28.20)["FWHM"]
            == pytest.approx(matched(base, 28.20)["FWHM"], rel=0.05))


@pytest.mark.parametrize("x,y", [
    ([], []),
    ([1.0, 2.0], [10.0, 12.0]),          # too few points
    (list(TWO_THETA), [5.0] * len(TWO_THETA)),   # flat, no peaks
])
def test_degenerate_input_returns_empty_without_raising(x, y):
    """Regression: a file whose rows all failed to parse used to surface a raw
    numpy 'zero-size array' exception in a user-facing dialog."""
    peaks_df, y_fit = detect_peaks_and_fit(np.asarray(x, dtype=float),
                                           np.asarray(y, dtype=float))
    assert len(peaks_df) == 0
    assert len(y_fit) == len(y)


# ---------------------------------------------------------------------------
# Measured data
# ---------------------------------------------------------------------------
def test_measured_perovskite_pattern(rawdata_dir):
    """Instrument export with a metadata preamble; the (110) and (220) cubic
    perovskite reflections must come out at their literature positions."""
    path = os.path.join(rawdata_dir, "peroV_2-Theta.TXT")
    if not os.path.exists(path):
        pytest.skip("peroV_2-Theta.TXT not present")

    x, y = xrd_core.load_data(path)
    assert len(x) > 1000, "metadata preamble was not skipped"

    peaks_df, _ = detect_peaks_and_fit(x, y)
    assert not peaks_df.empty

    for expected in (14.10, 28.42):
        near = peaks_df[(peaks_df["2Theta"] - expected).abs() < 0.15]
        assert len(near) >= 1, (
            f"no reflection within 0.15 deg of {expected}; found "
            f"{sorted(peaks_df['2Theta'].round(3).tolist())[:12]}"
        )

    strongest = peaks_df.iloc[0]
    assert strongest["Fit_R2"] > 0.95
    assert 5.0 < strongest["Crystallite_nm"] < 500.0
