"""SEM grain-size statistics and log-normal description."""
import math

import numpy as np
import pytest

from scripts.SEM import sem_core


def test_size_statistics_recover_lognormal_parameters():
    rng = np.random.default_rng(0)
    mu, sigma = math.log(300.0), 0.35
    d = rng.lognormal(mu, sigma, 5000)
    s = sem_core.size_statistics(d)
    assert s["n"] == 5000
    assert s["lognorm_mu"] == pytest.approx(mu, abs=0.02)
    assert s["lognorm_sigma"] == pytest.approx(sigma, abs=0.02)
    assert s["geo_mean"] == pytest.approx(300.0, rel=0.03)
    assert s["D50"] == pytest.approx(300.0, rel=0.05)
    assert s["D10"] < s["D50"] < s["D90"]
    assert s["lognorm_mode"] < s["geo_mean"] < s["mean"]
    assert s["std"] == pytest.approx(np.std(d, ddof=1), rel=1e-9)


def test_statistics_use_the_sample_standard_deviation():
    d = [100.0, 120.0, 140.0]
    s = sem_core.size_statistics(d)
    assert s["std"] == pytest.approx(20.0)        # ddof = 1
    assert s["cv"] == pytest.approx(20.0 / 120.0)


def test_empty_and_invalid_inputs():
    s = sem_core.size_statistics([])
    assert s["n"] == 0 and np.isnan(s["mean"])
    s2 = sem_core.size_statistics([-5.0, 0.0, float("nan"), 50.0])
    assert s2["n"] == 1 and s2["mean"] == 50.0 and s2["std"] == 0.0


def test_lognormal_pdf_integrates_to_one_and_histogram_overlay_matches_counts():
    x = np.linspace(1e-3, 5000.0, 200001)
    pdf = sem_core.lognormal_pdf(x, math.log(300.0), 0.35)
    trap = getattr(np, "trapezoid", None) or np.trapz
    assert trap(pdf, x) == pytest.approx(1.0, abs=1e-3)
    rng = np.random.default_rng(1)
    d = rng.lognormal(math.log(300.0), 0.35, 2000)
    stats, counts, edges, xs, curve = sem_core.histogram_with_fit(d)
    assert counts.sum() == 2000
    assert len(edges) == len(counts) + 1
    assert curve.max() == pytest.approx(counts.max(), rel=0.3)
