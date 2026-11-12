"""Auto-fit workspace (spectra/), 3.5.3: lines are fitted to the unsmoothed
data minus the background, S/N uses the noise of those data, and the XPS
doublet mode fits each doublet once.

Up to 3.5.2 the XRD and XPS lines were fitted to the Savitzky-Golay output
(XRD: 31 points, 0.62 deg on a 0.02 deg grid), the S/N column divided by the
noise of that smoothed curve (18x below the counting noise), and the doublet
mode fitted every candidate as the first line of its own doublet."""
import copy

import numpy as np
import pandas as pd
import pytest
from scipy.special import voigt_profile

from spectra.app import build_default_configs
from spectra.core.fit_common import sigma_floor, voigt_fwhm
from spectra.core.fit_xps import doublet_mains
from spectra.pipelines.run_xps import run_xps_pipeline
from spectra.pipelines.run_xrd import run_xrd_pipeline

# (centre deg, sigma, gamma, area): the last line is 0.11 deg wide
XRD_LINES = [(14.1, 0.18, 0.06, 800.0), (28.4, 0.12, 0.10, 500.0), (31.9, 0.05, 0.14, 300.0),
             (43.2, 0.20, 0.02, 400.0), (50.5, 0.03, 0.03, 120.0)]
TT = np.arange(10.0, 60.0, 0.02)
BG = 200.0 + 150.0 * np.exp(-((TT - 25.0) / 8.0) ** 2)


def _xrd(seed):
    y = sum(a * voigt_profile(TT - c, s, g) for c, s, g, a in XRD_LINES)
    return np.random.default_rng(seed).poisson(y + BG).astype(float)


def _row(f, c):
    return f.iloc[(f["center"] - c).abs().argmin()]


@pytest.fixture(scope="module")
def xrd_runs(tmp_path_factory):
    cfg, _, _ = build_default_configs()
    out = []
    for seed in range(4):
        _, cand, f = run_xrd_pipeline(TT, _xrd(seed), str(tmp_path_factory.mktemp(f"xrd{seed}")), cfg)
        out.append((cand, f))
    return out


def test_xrd_widths_are_not_widened_by_the_smoothing(xrd_runs):
    """3.5.2: FWHM +2 to +29 %, the 0.11 deg line +174 %."""
    for c, s, g, a in XRD_LINES:
        w = np.median([_row(f, c)["fwhm"] for _, f in xrd_runs])
        # medians of 4: -1.6 to +2.5 % (the Lorentzian-dominated 31.9 deg line)
        assert w == pytest.approx(voigt_fwhm(s, g), rel=0.04), c


def test_xrd_areas_within_the_baseline_limit(xrd_runs):
    """What is left is the AsLS baseline taking part of the Lorentzian tails
    (METHODS section 5): -5 to -10 % here, under 1 % with the true background."""
    for c, s, g, a in XRD_LINES:
        ar = np.median([_row(f, c)["area_amplitude"] for _, f in xrd_runs]) / a
        assert 0.85 < ar < 1.03, c


def test_xrd_snr_uses_the_counting_noise(xrd_runs):
    """Poisson noise on a 200-350 count background is 14-19 counts; 3.5.2
    divided by 0.93 (first differences of the smoothed curve)."""
    for _, f in xrd_runs:
        assert 12.0 < float(f["noise_sigma"].iloc[0]) < 21.0
        assert float(np.median(f["redchi"] / f["noise_sigma"] ** 2)) == pytest.approx(1.0, abs=0.3)
        for c, *_ in XRD_LINES:
            assert _row(f, c)["snr"] > 10
        # rows that are not one of the five lines are noise: S/N below the Currie limit of quantification
        real = np.zeros(len(f), bool)
        for c, *_ in XRD_LINES:
            real |= (f["center"] - c).abs().to_numpy() < 0.05
        assert (f.loc[~real, "snr"] < 10).all()


def test_xrd_one_row_per_line_and_no_single_point_components(xrd_runs):
    """3.5.2 repeated the 50.5 deg line three times (weak flank candidates
    whose components moved onto it).  Without the width floor a noise
    candidate fitted to unsmoothed data shrank onto one point (FWHM 0.007 deg)."""
    for _, f in xrd_runs:
        for c, *_ in XRD_LINES:
            assert int(((f["center"] - c).abs() < 0.05).sum()) == 1, c
        assert (2.3548 * f["sigma"] >= 2 * 0.02 * 0.999).all()


def test_sigma_floor():
    assert 2.3548 * sigma_floor(1.0, 0.02) == pytest.approx(0.04)
    assert 2.3548 * sigma_floor(0.05, 0.02) == pytest.approx(0.025)
    assert sigma_floor(0.0, 0.0) == pytest.approx(1e-6)


def _pb4f(seed, step):
    be = np.arange(132.0, 150.0, step)

    def gl(c, fwhm, area, m=0.3):
        s = fwhm / 2.355
        g = np.exp(-((be - c) ** 2) / (2 * s * s)) / (s * np.sqrt(2 * np.pi))
        lo = (fwhm / 2) / np.pi / ((be - c) ** 2 + (fwhm / 2) ** 2)
        return area * ((1 - m) * g + m * lo)
    pk = gl(138.60, 0.95, 4000) + gl(143.47, 0.95, 3000) + gl(136.85, 0.8, 380) + gl(141.72, 0.8, 285)
    y = np.random.default_rng(seed).poisson(np.clip(pk + 900 + 0.12 * np.cumsum(pk[::-1])[::-1] * step, 1, None))
    return be, y.astype(float)


def test_xps_width_on_a_coarse_scan(tmp_path):
    """0.2 eV steps: the 7-point filter widened 4f7/2 by 7.5 % in 3.5.2."""
    _, _, cfg = build_default_configs()
    w = []
    for seed in range(8):
        be, y = _pb4f(seed, 0.2)
        _, _, f = run_xps_pipeline(be, y, str(tmp_path / str(seed)), cfg, log_cb=lambda m: None)
        w.append(_row(f, 138.6)["fwhm"])
    assert np.median(w) == pytest.approx(0.95, rel=0.02)


def test_doublet_mode_fits_each_doublet_once(tmp_path):
    """Doublet split 4.87 eV, ratio 0.75: two doublets (oxide and metal), each
    partner at +4.87 eV.  3.5.2 returned four doublets for the four candidates."""
    _, _, cfg = build_default_configs()
    cfg = copy.deepcopy(cfg)
    cfg.xps_split_ev, cfg.xps_area_ratio = 4.87, 0.75
    main, metal = [], []
    for seed in range(24):
        be, y = _pb4f(seed, 0.05)
        _, cand, f = run_xps_pipeline(be, y, str(tmp_path / str(seed)), cfg, log_cb=lambda m: None)
        for d, g in f.groupby("doublet_id"):
            g = g.sort_values("xps_index")
            assert g["center"].iloc[1] - g["center"].iloc[0] == pytest.approx(4.87)
            assert g["area_amplitude"].iloc[1] / g["area_amplitude"].iloc[0] == pytest.approx(0.75)
        firsts = f[f["xps_index"] == 0]
        for c in (136.85, 138.60):           # each first line is fitted once
            assert int(((firsts["center"] - c).abs() < 0.3).sum()) == 1
        for c in (141.72, 143.47):           # no doublet starts on a partner line
            assert int(((firsts["center"] - c).abs() < 0.3).sum()) == 0
        main.append(_row(firsts, 138.60)["area_amplitude"])
        metal.append(_row(firsts, 136.85)["area_amplitude"] / main[-1])
    # medians of 24 realisations: -1.1 % and -2.2 %; one spectrum scatters from
    # 0.06 to 0.16, and the median of only 12 sat at -14 % between two values
    assert np.median(main) == pytest.approx(4000.0, rel=0.03)
    assert np.median(metal) == pytest.approx(0.095, rel=0.15)


def test_doublet_partner_taller_than_its_first_line_is_still_a_partner():
    """Noise seed 10 of the Pb 4f example: the metallic 4f5/2 candidate (317
    counts) came out taller than its 4f7/2 candidate (307), sitting between the
    two main lines."""
    cand = pd.DataFrame({"x": [136.70, 138.60, 141.70, 143.45], "height": [307.2, 3587.5, 316.7, 2630.7],
                         "fwhm_x": [0.498, 0.907, 0.481, 0.951]})
    m = doublet_mains(cand, 4.87, 0.05, 0.75)
    assert list(m["x"]) == [136.70, 138.60]
    # a strong line 4.87 eV above a weak noise candidate is not its partner
    noise = pd.concat([cand, pd.DataFrame({"x": [133.75], "height": [67.7], "fwhm_x": [0.21]})], ignore_index=True)
    assert list(doublet_mains(noise, 4.87, 0.05, 0.75)["x"]) == [133.75, 136.70, 138.60]


def test_xrd_interpretation_flags_no_residual_and_only_the_lines_as_signal(xrd_runs):
    """3.5.2 flagged 32-37 fit regions with a residual above twice the noise
    and passed 13-16 rows (most of them noise) as S/N >= 10.  Fitted to the
    unsmoothed data with the counting noise, and with windows that stop at a
    taller neighbour, no region is flagged and only the five lines pass."""
    from scripts.common.interpret import interpret_peak_fit
    for _, f in xrd_runs:
        rep = interpret_peak_fit("XRD", f)
        topics = {x.topic: x for x in rep.findings}
        assert "Fit residual" not in topics
        assert topics["Signal"].text.startswith("5 of ")
