"""Voigt fits of the auto-fit workspace (spectra/): the Lorentzian width is
fitted, the seed starts at the measured FWHM, and XRD windows stop at a
neighbouring line.

Up to 3.5.1 gamma was never fitted: lmfit's VoigtModel ties gamma to sigma
(expr, vary=False) and Parameter.set(value=...) clears the expr but keeps
vary=False.  gamma stayed at FWHM/2, sigma went to ~0, and every line was
fitted as a Lorentzian of the seed width; on Pb 4f the 4f7/2 area came out
+3 to +36 % high (Lorentzian- to Gaussian-dominated lines)."""
import numpy as np
import pandas as pd
import pytest
from scipy.special import voigt_profile

from spectra.core.fit_common import fit_voigts, fit_windows_to_midpoints, voigt_fwhm, voigt_seed
from spectra.core.fit_xps import fit_xps_doublet_voigts

# (sigma, gamma): Gaussian-dominated, mixed, Lorentzian-dominated
REGIMES = [(0.36, 0.22), (0.25, 0.30), (0.10, 0.45)]


def test_voigt_seed_starts_at_the_measured_fwhm():
    for f in (0.05, 0.4, 1.3, 7.0):
        s, g = voigt_seed(f)
        assert voigt_fwhm(s, g) == pytest.approx(f, rel=1e-4)
        assert 2.3548 * s == pytest.approx(2.0 * g, rel=1e-6)      # equal Gaussian and Lorentzian FWHM


@pytest.mark.parametrize("sigma,gamma", REGIMES)
@pytest.mark.parametrize("seed_scale", [0.7, 1.0, 1.3])
def test_single_voigt_recovers_sigma_gamma_and_area(sigma, gamma, seed_scale):
    x = np.arange(130.0, 148.0, 0.05)
    y = 1000.0 * voigt_profile(x - 138.6, sigma, gamma)
    fw = voigt_fwhm(sigma, gamma)
    tab = fit_voigts(x, y, (134.6, 142.6), [(138.6, float(y.max()), fw * seed_scale)])[0]
    r = tab.iloc[0]
    assert r["gamma"] == pytest.approx(gamma, rel=0.01)
    assert r["sigma"] == pytest.approx(sigma, rel=0.01)
    assert r["area_amplitude"] == pytest.approx(1000.0, rel=0.005)
    assert r["fwhm"] == pytest.approx(fw, rel=0.005)


@pytest.mark.parametrize("sigma,gamma", REGIMES)
@pytest.mark.parametrize("lock_widths", [True, False])
def test_pb4f_doublet_area_in_three_line_shapes(sigma, gamma, lock_widths):
    """The case reported against 3.5.1: 4f7/2 area +35.5 / +20.5 / +3.3 %."""
    be = np.arange(132.0, 150.0001, 0.05)
    rng = np.random.default_rng(1)
    y = (1000.0 * voigt_profile(be - 138.6, sigma, gamma) + 750.0 * voigt_profile(be - 143.47, sigma, gamma)
         + rng.normal(0, 1.0, be.size))
    fw = voigt_fwhm(sigma, gamma)
    tab = fit_xps_doublet_voigts(be, y, (135.5, 147.0), 138.6, float(y.max()), fw, 4.87, 0.75,
                                 lock_widths=lock_widths)[0]
    assert tab["area_amplitude"].iloc[0] == pytest.approx(1000.0, rel=0.01)
    assert tab["fwhm"].iloc[0] == pytest.approx(fw, rel=0.01)
    assert tab["gamma"].iloc[0] == pytest.approx(gamma, rel=0.05)
    assert abs(tab["center"].iloc[0] - 138.6) < 0.005


def _pb4f_cluster(seed):
    """Pb 4f with a metallic shoulder, GL(30) lines on a Shirley-like step
    (the spectrum of tests/test_xps.py), Poisson noise."""
    be = np.arange(132.0, 150.0, 0.05)
    rng = np.random.default_rng(seed)

    def gl(c, fwhm, area, m=0.3):
        s = fwhm / 2.355
        gauss = np.exp(-((be - c) ** 2) / (2 * s * s)) / (s * np.sqrt(2 * np.pi))
        lor = (fwhm / 2) / np.pi / ((be - c) ** 2 + (fwhm / 2) ** 2)
        return area * ((1 - m) * gauss + m * lor)
    peaks = gl(138.60, 0.95, 4000) + gl(143.47, 0.95, 3000) + gl(136.85, 0.8, 380) + gl(141.72, 0.8, 285)
    step = 900 + 0.12 * np.cumsum(peaks[::-1])[::-1] * 0.05
    return be, rng.poisson(np.clip(peaks + step, 1, None)).astype(float)


def test_xps_cluster_areas_are_unbiased_over_noise_seeds(tmp_path):
    """Median over 12 noise realisations: 4f7/2 area within 3 % of the input
    and Pb0/Pb2+ within 10 % of 0.095.  3.5.1 gave +41 % and 0.074 (-22 %)."""
    from spectra.app import build_default_configs
    from spectra.pipelines.run_xps import run_xps_pipeline

    _, _, cfg = build_default_configs()
    main, metal = [], []
    for seed in range(12):
        be, y = _pb4f_cluster(seed)
        _, _, f = run_xps_pipeline(be, y, str(tmp_path / str(seed)), cfg, log_cb=lambda m: None)

        def area_at(c):
            return float(f.iloc[(f["center"] - c).abs().argmin()]["area_amplitude"])
        main.append(area_at(138.60))
        metal.append(area_at(136.85) / area_at(138.60))
    assert np.median(main) == pytest.approx(4000.0, rel=0.03)
    assert np.median(metal) == pytest.approx(0.095, rel=0.10)


XRD_LINES = [(14.1, 0.18, 0.06, 800.0), (28.4, 0.12, 0.10, 500.0), (31.9, 0.05, 0.14, 300.0), (43.2, 0.20, 0.02, 400.0)]


def test_xrd_windows_stop_at_a_neighbouring_line():
    """Lines 3.5 deg apart with the 3.5 deg default window: with a full window
    each line's fit holds the other line's flank and no component for it
    (areas -18 and -35 % on noise-free data once gamma is free)."""
    tt = np.arange(10.0, 60.0, 0.02)
    y = sum(a * voigt_profile(tt - c, s, g) for c, s, g, a in XRD_LINES)
    cand = pd.DataFrame({"x": [c for c, *_ in XRD_LINES],
                         "height": [float(y[np.abs(tt - c).argmin()]) for c, *_ in XRD_LINES],
                         "fwhm_x": [voigt_fwhm(s, g) for _, s, g, _ in XRD_LINES]})
    f = pd.concat(fit_windows_to_midpoints(tt, y, cand, 3.5), ignore_index=True)
    assert len(f) == 4
    for c, s, g, a in XRD_LINES:
        r = f.iloc[(f["center"] - c).abs().argmin()]
        assert r["area_amplitude"] == pytest.approx(a, rel=0.01)
        assert r["fwhm"] == pytest.approx(voigt_fwhm(s, g), rel=0.01)
    row = f.iloc[(f["center"] - 28.4).abs().argmin()]
    assert row["region_xmax"] == pytest.approx(30.15)            # midpoint to 31.9
    assert row["region_xmin"] == pytest.approx(28.4 - 3.5)       # no neighbour on that side
    # a small line does not cut a large line's window
    weak = pd.concat([cand, pd.DataFrame({"x": [26.0], "height": [5.0], "fwhm_x": [0.3]})], ignore_index=True)
    f2 = pd.concat(fit_windows_to_midpoints(tt, y, weak, 3.5), ignore_index=True)
    assert f2.iloc[(f2["center"] - 28.4).abs().argmin()]["region_xmin"] == pytest.approx(28.4 - 3.5)


def test_xrd_pipeline_uses_midpoint_windows(tmp_path):
    from spectra.app import build_default_configs
    from spectra.pipelines.run_xrd import run_xrd_pipeline

    tt = np.arange(10.0, 60.0, 0.02)
    y = 200.0 + sum(a * voigt_profile(tt - c, s, g) for c, s, g, a in XRD_LINES)
    cfg, _, _ = build_default_configs()
    _, cand, f = run_xrd_pipeline(tt, y, str(tmp_path), cfg, log_cb=lambda m: None)
    assert len(f) == len(cand)
    row = f.iloc[(f["center"] - 28.4).abs().argmin()]
    assert row["region_xmax"] < 31.0                              # stopped before the 31.9 deg line
    # the 43.2 deg line is nearly Gaussian (gamma 0.02): 3.5.1 held gamma at FWHM/2 (~0.25)
    assert f.iloc[(f["center"] - 43.2).abs().argmin()]["gamma"] < 0.1
