"""PL: energy-axis conversion with the Jacobian, AIC-selected multi-component
fitting and model-free peak metrics."""
import numpy as np
import pytest

from conftest import gaussian
from scripts.PL import pl_core

WL = np.round(np.arange(600.0, 900.0 + 1e-9, 0.5), 4)


def test_energy_axis_is_ascending_and_conserves_area():
    y = gaussian(WL, 1000.0, 750.0, 40.0)
    e, ye = pl_core.to_energy_axis(WL, y)
    assert np.all(np.diff(e) > 0)
    trap = getattr(np, "trapezoid", None) or np.trapz
    assert trap(ye, e) == pytest.approx(trap(y, WL), rel=1e-3)


def test_energy_domain_peak_is_red_shifted_relative_to_naive_conversion():
    y = gaussian(WL, 1000.0, 750.0, 60.0)
    e_j, y_j = pl_core.to_energy_axis(WL, y, jacobian=True)
    e_n, y_n = pl_core.to_energy_axis(WL, y, jacobian=False)
    assert e_j[np.argmax(y_j)] < e_n[np.argmax(y_n)]


def test_multi_peak_fit_separates_band_edge_and_defect_emission():
    rng = np.random.default_rng(0)
    y = gaussian(WL, 1000.0, 750.0, 40.0) + gaussian(WL, 300.0, 820.0, 80.0) + rng.normal(0, 3.0, len(WL))
    res = pl_core.fit_multi_peak(WL, y, max_peaks=3)
    assert len(res.peaks) == 2
    main = min(res.peaks, key=lambda p: abs(p.center - 750))
    defect = min(res.peaks, key=lambda p: abs(p.center - 820))
    assert main.center == pytest.approx(750.0, abs=1.0)
    assert main.fwhm == pytest.approx(40.0, rel=0.05)
    assert defect.center == pytest.approx(820.0, abs=5.0)
    # the single-Gaussian core fit is biased by the defect band; the
    # multi-component fit removes most of that bias
    single = pl_core.fit_peak_gaussian(WL, y)
    assert abs(main.fwhm - 40.0) <= abs(single["fwhm"] - 40.0) + 0.5


def test_single_peak_is_not_over_fitted():
    y = gaussian(WL, 1000.0, 750.0, 40.0) + np.random.default_rng(1).normal(0, 3.0, len(WL))
    res = pl_core.fit_multi_peak(WL, y, max_peaks=3)
    assert len(res.peaks) == 1


def test_peak_metrics_on_a_symmetric_and_an_asymmetric_band():
    y = gaussian(WL, 1000.0, 750.0, 40.0)
    m = pl_core.peak_metrics(WL, y)
    assert m["peak_x"] == pytest.approx(750.0, abs=0.5)
    assert m["centroid"] == pytest.approx(750.0, abs=0.1)
    assert m["fwhm"] == pytest.approx(40.0, rel=0.02)
    assert m["asymmetry"] == pytest.approx(1.0, abs=0.05)
    y2 = y + gaussian(WL, 400.0, 790.0, 40.0)
    m2 = pl_core.peak_metrics(WL, y2)
    assert m2["asymmetry"] > 1.1
    assert m2["centroid"] > 750.0


def test_fwhm_conversion_nm_to_mev():
    # dE = hc dl / l^2: 40 nm at 750 nm -> 88 meV
    assert pl_core.fwhm_nm_to_mev(750.0, 40.0) == pytest.approx(1000 * 1239.84198 * 40 / 750 ** 2, rel=1e-9)
    assert pl_core.fwhm_nm_to_mev(750.0, 40.0) == pytest.approx(88.2, abs=0.2)


def test_peak_metrics_degenerate_input():
    m = pl_core.peak_metrics([1, 2], [1, 2])
    assert np.isnan(m["fwhm"])
