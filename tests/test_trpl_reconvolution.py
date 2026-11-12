"""TRPL: iterative reconvolution with a Gaussian or measured instrument
response, and Poisson maximum likelihood for counting data (3.6.0).

Every case is synthetic with a known answer: the decay is convolved with the
response on a grid ten times finer than the time bins and averaged over each
bin, then given Poisson noise, so the fit is not tested against its own model.
"""
import math

import numpy as np
import pandas as pd
import pytest
from scipy.integrate import quad

from scripts.TRPL import trpl_core as trpl
from scripts.common import curve_batch as cb

GRID = dict(n=1000, t_max=25.0, t0=2.0)          # 25 ps bins


def _decay(seed=0, **kw):
    args = dict(taus=(0.3, 3.0), amps=(0.6, 0.4), peak_counts=1e4, background=3.0, irf_fwhm=0.5)
    args.update(kw)
    return trpl.simulate(seed=seed, **GRID, **args)


@pytest.mark.parametrize("tau,s", [(0.3, 0.2), (5.0, 0.2), (0.01, 0.3), (50.0, 0.05)])
def test_gauss_exp_is_the_convolution_of_a_gaussian_and_an_exponential(tau, s):
    for x in (-0.5, 0.0, 0.2, 1.0, 3.0):
        num = quad(lambda u: math.exp(-0.5 * ((x - u) / s) ** 2) / (s * math.sqrt(2 * math.pi)) * math.exp(-u / tau),
                   0, np.inf, limit=200)[0]
        assert trpl.gauss_exp(np.array([x]), tau, s)[0] == pytest.approx(num, rel=1e-6, abs=1e-9)


def test_gaussian_reconvolution_recovers_a_lifetime_below_the_response_width():
    t, y = _decay()
    r = trpl.analyse(t, y, model="exp2", irf="gaussian")
    tail = trpl.analyse(t, y, model="exp2")
    assert r["method"].startswith("reconvolution")
    assert r["taus"] == pytest.approx([0.3, 3.0], rel=0.03)
    assert r["irf_fwhm"] == pytest.approx(0.5, rel=0.02)
    assert 0.8 < r["chi2_red"] < 1.2
    # the tail fit of the same trace overestimates the 0.3 ns component
    assert tail["taus"][0] > 1.15 * 0.3
    assert r["tail"]["taus"][0] == pytest.approx(tail["taus"][0], rel=1e-6)


def test_entered_response_width_is_kept_fixed():
    t, y = _decay(seed=1)
    r = trpl.analyse(t, y, model="exp2", irf="gaussian", irf_fwhm=0.5)
    assert r["irf_fixed"] and r["irf_fwhm"] == pytest.approx(0.5, abs=1e-12)
    assert r["taus"] == pytest.approx([0.3, 3.0], rel=0.03)


def test_measured_response_with_a_tail_and_a_colour_shift():
    """A SPAD-like response (30 % in a 0.25 ns tail) recorded 0.12 ns earlier
    than it acts on the emission: the measured response recovers the lifetimes
    and the shift; a Gaussian response cannot describe the tail."""
    resp = dict(irf_fwhm=0.4, irf_tail_tau=0.25, irf_tail_frac=0.3)
    t, y = _decay(irf_delay=0.12, **resp)
    ti, yi = trpl.simulate_irf(0.4, 0.25, 0.3, peak_counts=2e4, background=2.0, seed=100, **GRID)
    r = trpl.analyse(t, y, model="exp2", irf="measured", irf_t=ti, irf_y=yi)
    assert r["taus"] == pytest.approx([0.3, 3.0], rel=0.04)
    assert r["irf_shift"] == pytest.approx(0.12, abs=0.01)
    assert 0.8 < r["chi2_red"] < 1.2
    g = trpl.analyse(t, y, model="exp2", irf="gaussian")
    assert g["taus"][0] > 1.2 * 0.3


def test_reconvolution_fits_the_background_without_bias():
    """The offset is fitted together with the decay; with sigma = sqrt(N)
    weights it came out about one count low (Neyman chi-square)."""
    bgs = [trpl.analyse(*_decay(seed=s), model="exp2", irf="gaussian")["background"] for s in range(5)]
    assert np.median(bgs) == pytest.approx(3.0, abs=0.35)


def test_poisson_likelihood_removes_the_low_count_bias_of_the_tail_fit(monkeypatch):
    """Peak 1000 counts, background 2: sigma = sqrt(N) least squares gave both
    lifetimes about 5 % short; maximum likelihood is within 1.5 %."""
    def median_errors():
        e = []
        for s in range(8):
            r = trpl.analyse(*trpl.simulate(peak_counts=1e3, background=2.0, seed=s), model="exp2")
            e.append(np.asarray(r["taus"]) / np.array([5.0, 80.0]) - 1.0)
        return np.median(np.array(e), axis=0)
    new = median_errors()
    assert np.all(np.abs(new) < 0.015)
    monkeypatch.setattr(trpl, "POISSON_MLE", False)
    old = median_errors()
    assert np.all(old < -0.03)


def test_deviance_residuals_square_to_the_poisson_deviance():
    m = np.array([0.5, 2.0, 10.0, 3.0])
    y = np.array([0.0, 3.0, 7.0, 3.0])
    dev = 2 * np.sum(m - y + np.where(y > 0, y * np.log(np.where(y > 0, y, 1) / m), 0))
    r = trpl.deviance_residuals(m, y)
    assert np.sum(r ** 2) == pytest.approx(dev)
    assert np.sign(r[1]) < 0 < np.sign(r[2]) and r[3] == 0.0


def test_reconvolution_checks():
    t, y = _decay(taus=(0.04, 2.0), amps=(0.5, 0.5), seed=2)
    r = trpl.analyse(t, y, model="exp2", irf="gaussian", skip=0.3)
    text = " ".join(r["warnings"])
    if r["taus"][0] < 0.2 * r["irf_fwhm"]:
        assert "upper limit" in text
    assert "'Skip after peak' is not used" in text
    tail = trpl.analyse(*_decay(), model="exp2", irf_fwhm=0.5)
    assert any("reconvolution" in w for w in tail["warnings"])


def test_reconvolution_input_errors():
    t, y = _decay()
    with pytest.raises(ValueError, match="tail fit only"):
        trpl.analyse(t, y, model="stretched", irf="gaussian")
    with pytest.raises(ValueError, match="response file"):
        trpl.analyse(t, y, irf="measured")
    with pytest.raises(ValueError, match="unknown instrument response"):
        trpl.analyse(t, y, irf="lorentzian")
    tt = t.copy()
    tt[500:] += 0.01
    ti, yi = trpl.simulate_irf(0.5, **GRID)
    with pytest.raises(ValueError, match="equally spaced"):
        trpl.analyse(tt, y, irf="measured", irf_t=ti, irf_y=yi)


def test_measured_response_through_the_batch_layer(tmp_path):
    t, y = _decay(irf_delay=0.12, irf_fwhm=0.4, irf_tail_tau=0.25, irf_tail_frac=0.3)
    ti, yi = trpl.simulate_irf(0.4, 0.25, 0.3, peak_counts=2e4, background=2.0, seed=100, **GRID)
    decay, resp = tmp_path / "film.csv", tmp_path / "irf.csv"
    pd.DataFrame({"Time (ns)": t, "Counts": y}).to_csv(decay, index=False)
    pd.DataFrame({"Time (ns)": ti, "Counts": yi}).to_csv(resp, index=False)
    p = cb.parameters("trpl", {"irf": "measured", "irf_file": str(resp), "model": "exp2"})
    r = cb.analyse("trpl", cb.load("trpl", str(decay), p), p)
    assert r["taus"] == pytest.approx([0.3, 3.0], rel=0.04)
    tables = cb.tables("trpl", {}, r)
    assert "Response (scaled to the peak)" in tables["Fit"] and "Component 2" in tables["Fit"]
    with pytest.raises(ValueError, match="needs the response file"):
        cb.analyse("trpl", cb.load("trpl", str(decay), p), {**p, "irf_file": ""})
    with pytest.raises(ValueError, match="not one of"):
        cb.parameters("trpl", {"irf": "voigt"})
