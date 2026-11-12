"""Time-resolved photoluminescence: multi-exponential and stretched-
exponential tail fits, model selection, average and differential lifetimes.

    I(t) = sum_i A_i exp(-t / tau_i)                 1 - 3 components
    I(t) = A exp(-(t / tau)^beta)                    stretched (Kohlrausch)

    <tau>_amp = sum A_i tau_i / sum A_i              amplitude weighted
    <tau>_int = sum A_i tau_i^2 / sum A_i tau_i      intensity weighted
    <tau>_KWW = (tau / beta) Gamma(1 / beta)
    tau_diff(t) = -(d ln I / dt)^-1                  differential lifetime

Without an instrument response the fit is a tail fit: it starts at (or a
chosen delay after) the peak, so a component shorter than the response or
than about three time bins is not resolved. With a response (iterative
reconvolution) the model is the response convolved with the decay and is
fitted from the rising edge on:

    I(t) = IRF(t) (x) sum_i A_i exp(-(t - t0) / tau_i) H(t - t0)

    Gaussian IRF     closed form, width fixed or fitted:
                     g(x) = 1/2 exp(s^2 / 2 tau^2 - x / tau) erfc((s / tau - x / s) / sqrt 2)
    measured IRF     background-subtracted, normalised to unit area, moved by
                     a fitted shift (colour shift between the response and
                     the emission); the response is taken as constant within
                     a time bin, so the exponential kernel is integrated
                     exactly over each bin. Counting data
are weighted with Poisson errors sigma = sqrt(N), which makes the reduced
chi-square an absolute test; for other data the same weight shape is used
and the parameter errors are scaled with the residual variance.

The number of exponentials is chosen with the small-sample Akaike criterion
(AICc); a model is rejected when two lifetimes are closer than a factor
1.5, a component carries less than 1 % of the amplitude, or a lifetime is
not determined (relative error above 100 %).

References
    Lakowicz, Principles of Fluorescence Spectroscopy, 3rd ed. (2006), ch. 4
    Burnham, Anderson, Model Selection and Multimodel Inference (2002)   AICc
    Kirchartz, Marquez, Stolterfoht, Unold, Adv. Energy Mater. 10, 1904134 (2020)
    Krueckemeier, Krogmeier, Liu, Rau, Kirchartz, Adv. Energy Mater. 11, 2003489 (2021)
    Peán et al., ACS Energy Lett. 5, 3244 (2020)     non-exponential decays in perovskites
    O'Connor, Phillips, Time-Correlated Single Photon Counting (1984), ch. 7    reconvolution
    Grinvald, Steinberg, Anal. Biochem. 59, 583 (1974)                        reconvolution fits
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import savgol_filter
from scipy.signal import fftconvolve
from scipy.special import erfc, erfcx, gamma as _gamma

KB_EV = 8.617333262e-5
TIME_UNITS = {"ps": 1e-12, "ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1.0}
MODELS = ("exp1", "exp2", "exp3", "stretched")
IRF_KINDS = ("none", "gaussian", "measured")
RECONV_MODELS = ("exp1", "exp2", "exp3")
FWHM_PER_SIGMA = 2.0 * np.sqrt(2.0 * np.log(2.0))
# shortest lifetime reported without remark by a reconvolution fit, as a fraction
# of the response FWHM: 0.1 when the response width is known (entered or
# measured), 0.2 when it is fitted (validation: single exponential, 10^4 peak
# counts, error at most 3 % and 19 % at 0.1 FWHM, 1 % and 2 % at 0.2 FWHM)
RECONV_LIMIT_KNOWN, RECONV_LIMIT_FITTED = 0.1, 0.2
MIN_FRACTION, MIN_RATIO, MAX_REL_ERR = 0.01, 1.5, 1.0

COLUMN_SPEC = [
    ("t", [r"time", r"delay", r"^t\b", r"\b[pnum]?s\b"], 0),
    ("y", [r"count", r"intens", r"\bpl\b", r"signal", r"decay", r"^y\b"], 1),
]


def looks_like_counts(y) -> bool:
    y = np.asarray(y, float)
    y = y[np.isfinite(y)]
    return bool(len(y) and y.max() >= 50 and y.min() >= 0 and np.allclose(y, np.round(y), atol=1e-6))


def _pre_pulse_points(t, rise: int, kp: int) -> int:
    """Points before the pulse that are free of its rising edge: those more
    than twice the 10 %-to-peak rise time (plus two bins) before the 10 %
    point, and at most 80 % of the points before it."""
    if rise <= 0:
        return 0
    dt = float(np.median(np.diff(t))) if len(t) > 1 else 0.0
    cut = t[rise] - 2.0 * (t[kp] - t[rise]) - 2.0 * dt
    return int(min(np.searchsorted(t, cut, side="left"), int(0.8 * rise)))


def prepare(t, y, background: Any = "auto", skip: float = 0.0, t_end: Optional[float] = None) -> Dict[str, Any]:
    """Sort, locate the peak, estimate and subtract the background, and cut
    the fit window [peak + skip, t_end]. Times are returned relative to the
    peak."""
    t, y = np.asarray(t, float), np.asarray(y, float)
    ok = np.isfinite(t) & np.isfinite(y)
    t, y = t[ok], y[ok]
    order = np.argsort(t, kind="stable")
    t, y = t[order], y[order]
    if len(t) < 12:
        raise ValueError("TRPL needs at least 12 points")
    kp = int(np.argmax(y))
    peak = float(y[kp])
    if peak <= 0:
        raise ValueError("the decay has no positive signal")
    counts = looks_like_counts(y)
    rise = int(np.argmax(y >= 0.1 * peak))
    bg, bg_from = 0.0, "none"
    if isinstance(background, (int, float)) and not isinstance(background, bool):
        bg, bg_from = float(background), "entered"
    elif str(background).lower() == "auto":
        n_pre = _pre_pulse_points(t, rise, kp)
        tail = y[-max(8, len(y) // 20):]
        half = len(tail) // 2
        noise = np.sqrt(max(np.median(tail), 1.0)) if counts else 0.02 * peak
        if n_pre >= 5:
            # counts: the mean (the median of a few counts per bin is an integer
            # and biased by up to half a count); other data: the median
            pre = y[:n_pre]
            bg, bg_from = float(np.mean(pre) if counts else np.median(pre)), "before the pulse"
        elif np.median(tail) < 0.05 * peak and abs(np.median(tail[:half]) - np.median(tail[half:])) < 2.0 * noise:
            bg, bg_from = float(np.median(tail)), "flat tail"
    ys = y - bg
    tr = t - t[kp]
    sel = tr >= float(skip)
    if t_end is not None:
        sel &= tr <= float(t_end)
    if sel.sum() < 10:
        raise ValueError("fewer than 10 points in the fit window")
    dt = float(np.median(np.diff(t))) if len(t) > 1 else np.nan
    if counts:
        sigma = np.sqrt(np.maximum(y, 1.0))
        floor = float(np.sqrt(max(bg, 1.0)))
    else:
        sigma = np.sqrt(np.maximum(ys, 1e-3 * peak) * peak) / np.sqrt(peak)   # Poisson shape, arbitrary scale
        floor = float(np.std(ys[-max(8, len(ys) // 20):])) or 1e-4 * peak
    sig_peak = float(ys[kp])
    return {"t": tr, "y": ys, "y_raw": y, "sigma": sigma, "mask": sel, "background": bg, "background_from": bg_from,
            "counts": counts, "peak": sig_peak, "t_peak": float(t[kp]), "dt": dt, "noise_floor": floor,
            "dynamic_range_dec": float(np.log10(max(sig_peak, 1e-300) / max(floor, 1e-300)))}


def deviance_residuals(m, y) -> np.ndarray:
    """Signed Poisson deviance residuals: their sum of squares is the
    Poisson deviance 2 sum(m - y + y ln(y / m)), so a least-squares solver
    that minimises it returns the maximum-likelihood estimate (Laurence and
    Chromy, Nat. Methods 7, 338 (2010)). Weighting by the data (sigma =
    sqrt(N)) instead biases a fitted level low by about one count."""
    m = np.maximum(np.asarray(m, float), 1e-12)
    y = np.asarray(y, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        term = np.where(y > 0, y * np.log(np.where(y > 0, y, 1.0) / m), 0.0)
    return np.sign(m - y) * np.sqrt(np.maximum(2.0 * (m - y + term), 0.0))


POISSON_MLE = True          # counting data: maximum likelihood (deviance); False: sigma = sqrt(N) least squares


def model_curve(kind: str, p, t) -> np.ndarray:
    t = np.asarray(t, float)
    if kind == "stretched":
        return np.exp(p[0]) * np.exp(-np.power(np.maximum(t, 0.0) / np.exp(p[1]), p[2]))
    out = np.zeros_like(t)
    for i in range(len(p) // 2):
        out = out + np.exp(p[2 * i]) * np.exp(-t / np.exp(p[2 * i + 1]))
    return out


def _starts(kind: str, t, y) -> List[np.ndarray]:
    span = float(t.max() - t.min()) or 1.0
    a0 = np.log(max(float(y.max()), 1e-12))
    if kind == "stretched":
        return [np.array([a0, np.log(span / d), b]) for d in (4.0, 15.0) for b in (0.6, 0.9)]
    n = int(kind[-1])
    out = []
    for lo, hi in ((60.0, 3.0), (200.0, 6.0), (20.0, 1.5)):
        taus = np.geomspace(span / lo, span / hi, n) if n > 1 else np.array([span / np.sqrt(lo * hi)])
        p = []
        for i, tau in enumerate(taus):
            p += [a0 - np.log(n) - 0.7 * i, np.log(tau)]
        out.append(np.array(p))
    return out


def _propagate(func: Callable[[np.ndarray], float], p: np.ndarray, cov: np.ndarray) -> float:
    g = np.zeros(len(p))
    for i in range(len(p)):
        h = 1e-5 * max(1.0, abs(p[i]))
        up, dn = p.copy(), p.copy()
        up[i] += h
        dn[i] -= h
        g[i] = (func(up) - func(dn)) / (2 * h)
    var = float(g @ cov @ g)
    return float(np.sqrt(var)) if var >= 0 and np.isfinite(var) else np.nan


def _averages(p) -> Tuple[float, float]:
    a, tau = np.exp(p[0::2]), np.exp(p[1::2])
    return float((a * tau).sum() / a.sum()), float((a * tau ** 2).sum() / (a * tau).sum())


def _objective(curve: Callable[[np.ndarray], np.ndarray], y, sigma, mle: bool, bg: float):
    """Residual function of the fit: Poisson deviance residuals on the raw
    counts (model + background) for counting data, else weighted residuals."""
    def safe(p):
        with np.errstate(over="ignore", invalid="ignore"):
            return np.nan_to_num(curve(p), nan=1e300, posinf=1e300, neginf=-1e300)
    if mle:
        raw = y + bg
        return lambda p: deviance_residuals(safe(p) + bg, raw)
    return lambda p: (safe(p) - y) / sigma


def _goodness(m, y, sigma, mle: bool, bg: float, k: int):
    """Residuals for the plot and the tests, chi-square and AICc. Counting
    data: Pearson residuals with the model's own variance and the deviance
    in the AICc; other data: weighted residuals and n ln(chi2 / n)."""
    n_pts = len(y)
    corr = 2 * k * (k + 1) / (n_pts - k - 1) if n_pts > k + 1 else np.inf
    if mle:
        mm = np.maximum(m + bg, 1e-12)
        res = (m - y) / np.sqrt(np.maximum(mm, 1.0))
        dev = float((deviance_residuals(m + bg, y + bg) ** 2).sum())
        return res, float((res ** 2).sum()), dev + 2 * k + corr
    res = (m - y) / sigma
    chi2 = float((res ** 2).sum())
    return res, chi2, n_pts * np.log(max(chi2, 1e-300) / n_pts) + 2 * k + corr


def fit_model(kind: str, t, y, sigma, absolute_sigma: bool, bg: float = 0.0) -> Dict[str, Any]:
    """Fit of one model to the background-subtracted signal y: Poisson
    maximum likelihood for counting data (absolute_sigma, on y + bg), else
    weighted least squares; returns parameters, errors and goodness of fit."""
    t, y, sigma = (np.asarray(a, float) for a in (t, y, sigma))
    mle = bool(absolute_sigma and POISSON_MLE)
    span = float(t.max() - t.min()) or 1.0
    if kind == "stretched":
        lo, hi = [-np.inf, np.log(span * 1e-5), 0.2], [np.inf, np.log(span * 1e3), 1.0]
    else:
        n = int(kind[-1])
        lo, hi = [-np.inf, np.log(span * 1e-5)] * n, [np.inf, np.log(span * 1e3)] * n
    best = None
    resid = _objective(lambda p: model_curve(kind, p, t), y, sigma, mle, bg)
    for p0 in _starts(kind, t, y):
        try:
            with np.errstate(over="ignore", invalid="ignore"):
                sol = least_squares(resid, np.clip(p0, lo, hi), bounds=(lo, hi), method="trf", x_scale="jac",
                                    max_nfev=600)
        except Exception:
            continue
        if best is None or sol.cost < best.cost:
            best = sol
    if best is None:
        raise ValueError(f"the {kind} fit did not converge")
    p = best.x.copy()
    k, n_pts = len(p), len(t)
    res, chi2, aicc = _goodness(model_curve(kind, p, t), y, sigma, mle, bg, k)
    dof = max(n_pts - k, 1)
    chi2_red = chi2 / dof
    try:
        cov = np.linalg.pinv(best.jac.T @ best.jac) * (max(chi2_red, 1.0) if absolute_sigma else chi2_red)
    except Exception:
        cov = np.full((k, k), np.nan)
    err = np.sqrt(np.clip(np.diag(cov), 0, None))
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(((model_curve(kind, p, t) - y) ** 2).sum()) / ss_tot if ss_tot > 0 else np.nan
    dw = float((np.diff(res) ** 2).sum() / chi2) if chi2 > 0 else np.nan
    out: Dict[str, Any] = {"model": kind, "p": p, "cov": cov, "k": k, "n": n_pts, "chi2": chi2, "chi2_red": chi2_red,
                           "aicc": float(aicc), "r2": r2, "dw": dw, "valid": True, "reason": "", "beta": np.nan}
    if kind == "stretched":
        tau, beta = float(np.exp(p[1])), float(p[2])
        mean = lambda q: float(np.exp(q[1]) / q[2] * _gamma(1.0 / q[2]))
        out.update({"taus": np.array([tau]), "tau_errs": np.array([tau * err[1]]), "amps": np.array([np.exp(p[0])]),
                    "amp_fracs": np.array([1.0]), "int_fracs": np.array([1.0]), "beta": beta, "beta_err": float(err[2]),
                    "tau_amp": mean(p), "tau_amp_err": _propagate(mean, p, cov), "tau_int": np.nan, "tau_int_err": np.nan})
        if beta > 0.98:
            out.update({"valid": False, "reason": "beta is 1 within the fit: a single exponential"})
        return out
    return _describe_exp(out, p, cov)


def _describe_exp(out: Dict[str, Any], p: np.ndarray, cov: np.ndarray) -> Dict[str, Any]:
    """Lifetimes sorted from short to long, amplitude and intensity fractions,
    mean lifetimes with propagated errors, and the validity tests, for an
    exponential parameter vector [ln A1, ln tau1, ...] and its covariance."""
    err = np.sqrt(np.clip(np.diag(cov), 0, None))
    order = np.argsort(p[1::2])
    p = np.column_stack([p[0::2][order], p[1::2][order]]).ravel()
    idx = np.column_stack([2 * order, 2 * order + 1]).ravel()
    cov = cov[np.ix_(idx, idx)]
    err = err[idx]
    a, tau = np.exp(p[0::2]), np.exp(p[1::2])
    out.update({"p": p, "cov": cov, "taus": tau, "tau_errs": tau * err[1::2], "amps": a, "amp_fracs": a / a.sum(),
                "int_fracs": a * tau / (a * tau).sum()})
    t_amp, t_int = _averages(p)
    out.update({"tau_amp": t_amp, "tau_amp_err": _propagate(lambda q: _averages(q)[0], p, cov),
                "tau_int": t_int, "tau_int_err": _propagate(lambda q: _averages(q)[1], p, cov)})
    if len(tau) > 1:
        if out["amp_fracs"].min() < MIN_FRACTION:
            out.update({"valid": False, "reason": "a component carries less than 1 % of the amplitude"})
        elif (tau[1:] / tau[:-1]).min() < MIN_RATIO:
            out.update({"valid": False, "reason": "two lifetimes are closer than a factor 1.5"})
        elif (err[1::2] > MAX_REL_ERR).any() or not np.isfinite(err).all():
            out.update({"valid": False, "reason": "a lifetime is not determined (relative error above 100 %)"})
    return out


def choose_model(fits: Dict[str, Dict[str, Any]], pool=("exp1", "exp2", "exp3")) -> str:
    """Lowest AICc among the valid models; a simpler model within 2 AICc
    units of the best one is preferred."""
    cand = [fits[m] for m in pool if m in fits and fits[m]["valid"]]
    if not cand:
        return "exp1" if "exp1" in fits else next(iter(fits))
    best = min(c["aicc"] for c in cand)
    for c in sorted(cand, key=lambda c: c["k"]):
        if c["aicc"] - best <= 2.0:
            return c["model"]
    return cand[0]["model"]


# ---------------------------------------------------------------------------
# reconvolution with the instrument response
# ---------------------------------------------------------------------------
def gauss_exp(x, tau: float, s: float) -> np.ndarray:
    """exp(-x / tau) H(x) convolved with a unit-area Gaussian of standard
    deviation s (exponentially modified Gaussian), written with erfcx where
    exp(...) erfc(...) would overflow."""
    x = np.asarray(x, float)
    z = (s / tau - x / s) / np.sqrt(2.0)
    out = np.empty_like(x)
    pos = z > 0
    out[pos] = 0.5 * erfcx(z[pos]) * np.exp(-0.5 * (x[pos] / s) ** 2)
    neg = ~pos
    out[neg] = 0.5 * np.exp(0.5 * (s / tau) ** 2 - x[neg] / tau) * erfc(z[neg])
    return out


def fwhm_of(t, y) -> float:
    """Full width at half maximum of a single peak, interpolated between samples."""
    t, y = np.asarray(t, float), np.asarray(y, float)
    k = int(np.argmax(y))
    half = 0.5 * y[k]
    left = np.where(y[:k] < half)[0]
    right = np.where(y[k:] < half)[0]
    if not len(left) or not len(right):
        return np.nan
    i, j = int(left[-1]), k + int(right[0])
    tl = t[i] + (half - y[i]) / (y[i + 1] - y[i]) * (t[i + 1] - t[i])
    tr = t[j - 1] + (y[j - 1] - half) / (y[j - 1] - y[j]) * (t[j] - t[j - 1])
    return float(tr - tl)


def prepare_irf(t, y) -> Dict[str, Any]:
    """Measured instrument response: background (median before the rise, or
    the lower of the two ends) subtracted, everything outside the main lobe
    (the run of points around the peak above twice the noise) set to zero,
    negative values clipped. The area is normalised later, on the decay's
    time grid."""
    t, y = np.asarray(t, float), np.asarray(y, float)
    ok = np.isfinite(t) & np.isfinite(y)
    t, y = t[ok], y[ok]
    order = np.argsort(t, kind="stable")
    t, y = t[order], y[order]
    if len(t) < 8:
        raise ValueError("the instrument response needs at least 8 points")
    kp = int(np.argmax(y))
    peak = float(y[kp])
    if peak <= 0:
        raise ValueError("the instrument response has no positive signal")
    counts = looks_like_counts(y)
    rise = int(np.argmax(y >= 0.1 * peak))
    n_pre = _pre_pulse_points(t, rise, kp)
    if n_pre >= 5:
        bg = float(np.mean(y[:n_pre]) if counts else np.median(y[:n_pre]))
        noise = np.sqrt(max(bg, 1.0)) if counts else float(np.std(y[:n_pre])) or 1e-3 * peak
    else:
        ends = [float(np.median(y[:5])), float(np.median(y[-max(5, len(y) // 20):]))]
        bg = min(ends) if min(ends) < 0.05 * peak else 0.0
        noise = np.sqrt(max(bg, 1.0)) if counts else 2e-3 * peak
    ys = y - bg
    above = ys > 2.0 * noise
    lo = hi = kp
    while lo > 0 and above[lo - 1]:
        lo -= 1
    while hi < len(y) - 1 and above[hi + 1]:
        hi += 1
    keep = np.zeros(len(y), bool)
    keep[max(lo - 2, 0):hi + 3] = True
    ys = np.where(keep, np.clip(ys, 0.0, None), 0.0)
    return {"t": t, "y": ys, "background": bg, "counts": counts, "t_peak": float(t[kp]), "fwhm": fwhm_of(t, ys),
            "dt": float(np.median(np.diff(t))), "lobe": (float(t[lo]), float(t[hi])), "peak_counts": peak - bg}


_RESPONSES: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}


def read_response(irf_file: str) -> Tuple[np.ndarray, np.ndarray]:
    """Measured instrument response file (time and counts columns, read like
    a decay file), kept in memory per path and modification time so that a
    batch reads it once."""
    import os
    from scripts.common import curve_io
    path = str(irf_file or "").strip().strip('"')
    if not path:
        raise ValueError("Response 'measured' needs the response file (IRF file)")
    if not os.path.isfile(path):
        raise ValueError(f"response file not found: {path}")
    key = f"{os.path.abspath(path)}|{os.path.getmtime(path)}"
    if key not in _RESPONSES:
        data, _names = curve_io.pick_columns(curve_io.read_numeric_table(path), COLUMN_SPEC)
        _RESPONSES.clear()
        _RESPONSES[key] = (np.asarray(data["t"], float), np.asarray(data["y"], float))
    return _RESPONSES[key]


def _exp_kernel(p_exp, dt: float, n: int) -> np.ndarray:
    """sum_i A_i exp(-(t_k - t') / tau_i) integrated over a time bin of a
    response that is constant within the bin, for lags k = 0 .. n-1."""
    m = np.arange(n, dtype=float)
    out = np.zeros(n)
    with np.errstate(over="ignore", invalid="ignore"):
        out = _kernel_sum(p_exp, dt, m, out)
    return np.nan_to_num(out, nan=1e300, posinf=1e300, neginf=-1e300)


def _kernel_sum(p_exp, dt, m, out):
    n = len(m)
    for i in range(len(p_exp) // 2):
        a, tau = np.exp(p_exp[2 * i]), np.exp(p_exp[2 * i + 1])
        r = dt / tau
        k = np.empty(n)
        k[0] = -tau * np.expm1(-0.5 * r)
        k[1:] = tau * (np.exp(-(m[1:] - 0.5) * r) - np.exp(-(m[1:] + 0.5) * r))
        out += a * k
    return out


class _GaussianIRF:
    """I(t) = sum_i A_i g(t - t0; tau_i, s); parameters [t0, ln s] or [t0]."""
    kind = "gaussian"

    def __init__(self, t, y, dt: float, fwhm_fixed: float):
        self.dt = dt
        self.fixed = fwhm_fixed / FWHM_PER_SIGMA if fwhm_fixed > 0 else None
        peak = float(y.max())
        kp = int(np.argmax(y))
        rising = np.where(y[:kp + 1] < 0.1 * peak)[0]
        i10 = int(rising[-1]) + 1 if len(rising) else 0
        i50 = int(np.argmax(y[:kp + 1] >= 0.5 * peak))
        i90 = int(np.argmax(y[:kp + 1] >= 0.9 * peak))
        s0 = self.fixed or max(dt, (t[i90] - t[i10]) / 2.56)
        self.s0, self.t10, self.t50, self.tpk = s0, float(t[i10]), float(t[i50]), float(t[kp])
        self.n_extra = 1 if self.fixed else 2
        self.names = ["t0"] if self.fixed else ["t0", "ln s"]

    def window_start(self) -> float:
        return self.t10 - 4.0 * self.s0 - 3.0 * self.dt

    def starts(self) -> List[np.ndarray]:
        t0s = (self.t50, self.t50 - 0.5 * self.s0)
        if self.fixed:
            return [np.array([t0]) for t0 in t0s]
        return [np.array([t0, np.log(s)]) for t0 in t0s for s in (self.s0, 0.6 * self.s0)]

    def bounds(self) -> Tuple[List[float], List[float]]:
        lo_t, hi_t = self.t10 - 4.0 * self.s0 - 3.0 * self.dt, self.tpk + self.dt
        if self.fixed:
            return [lo_t], [hi_t]
        return [lo_t, np.log(0.2 * self.dt)], [hi_t, np.log(5.0 * self.s0 + self.dt)]

    def sigma(self, q) -> float:
        return self.fixed if self.fixed else float(np.exp(q[1]))

    def curve(self, q, p_exp, t) -> np.ndarray:
        s = self.sigma(q)
        out = np.zeros(len(t))
        with np.errstate(over="ignore", invalid="ignore"):
            for i in range(len(p_exp) // 2):
                out += np.exp(p_exp[2 * i]) * gauss_exp(t - q[0], float(np.exp(p_exp[2 * i + 1])), s)
        return np.nan_to_num(out, nan=1e300, posinf=1e300, neginf=-1e300)

    def response(self, q, t) -> np.ndarray:
        s = self.sigma(q)
        return np.exp(-0.5 * ((t - q[0]) / s) ** 2) / (s * np.sqrt(2.0 * np.pi))

    def fwhm(self, q) -> float:
        return self.sigma(q) * FWHM_PER_SIGMA


class _MeasuredIRF:
    """I = IRF(t - shift) (x) decay on the decay's own equally spaced grid;
    parameter [shift]."""
    kind = "measured"

    def __init__(self, irf: Dict[str, Any], t_grid, y, dt: float):
        self.irf, self.dt, self.grid = irf, dt, np.asarray(t_grid, float)
        self.n_extra, self.names = 1, ["shift"]
        peak = float(np.max(y))
        kp = int(np.argmax(y))
        i50 = int(np.argmax(y[:kp + 1] >= 0.5 * peak))
        w = irf["fwhm"] if np.isfinite(irf["fwhm"]) else 3.0 * dt
        # the response file keeps the instrument's own time axis: first guess
        # is no shift; the second puts the response peak on the rising edge
        self.align = float(t_grid[i50] - irf["t_peak"])
        self.span = 3.0 * w + 5.0 * dt
        self.w = w

    def window_start(self) -> float:
        return self.irf["lobe"][0] + self.align - 3.0 * self.dt

    def starts(self) -> List[np.ndarray]:
        out = [np.array([self.align + d]) for d in (0.0, -0.3 * self.w, 0.3 * self.w)]
        if abs(self.align) < self.span:
            out.append(np.array([0.0]))
        return out

    def bounds(self) -> Tuple[List[float], List[float]]:
        return [self.align - self.span], [self.align + self.span]

    def on_grid(self, shift: float) -> np.ndarray:
        r = np.interp(self.grid - shift, self.irf["t"], self.irf["y"], left=0.0, right=0.0)
        area = r.sum() * self.dt
        return r / area if area > 0 else r

    def curve_full(self, q, p_exp) -> np.ndarray:
        n = len(self.grid)
        return fftconvolve(self.on_grid(float(q[0])), _exp_kernel(p_exp, self.dt, n))[:n]

    def response(self, q, t=None) -> np.ndarray:
        return self.on_grid(float(q[0]))

    def fwhm(self, q) -> float:
        return float(self.irf["fwhm"])


def fit_reconvolution(kind: str, t, y, sigma, absolute_sigma: bool, irf_model, sel,
                      starts_exp: List[np.ndarray], bg: float = 0.0) -> Dict[str, Any]:
    """Fit of response (x) decay + offset over the points `sel` of the full
    background-subtracted trace (t, y, sigma): Poisson maximum likelihood for
    counting data (on y + bg), else weighted least squares. Returns the same
    fields as `fit_model` plus the response parameters and the offset."""
    t, y, sigma = (np.asarray(a, float) for a in (t, y, sigma))
    mle = bool(absolute_sigma and POISSON_MLE)
    sel = np.asarray(sel, bool)
    tw, yw, sw = t[sel], y[sel], sigma[sel]
    n = int(kind[-1])
    span = float(tw.max() - tw.min()) or 1.0
    dt = irf_model.dt
    nq = irf_model.n_extra
    ne = nq + 1                                   # response parameters and the background offset
    lo_e, hi_e = irf_model.bounds()
    b_lim = max(10.0 * float(np.median(sw)), 0.05 * float(yw.max()))
    lo = lo_e + [-b_lim] + [-np.inf, np.log(0.02 * dt)] * n
    hi = hi_e + [b_lim] + [np.inf, np.log(span * 1e3)] * n
    last = int(np.where(sel)[0][-1]) + 1

    if irf_model.kind == "measured":
        def curve(p):
            return irf_model.curve_full(p[:nq], p[ne:])[:last][sel[:last]] + p[nq]
    else:
        def curve(p):
            return irf_model.curve(p[:nq], p[ne:], tw) + p[nq]

    resid = _objective(curve, yw, sw, mle, bg)

    # every start is run briefly; the two best are refined
    trials = []
    for e0 in irf_model.starts():
        for x0 in starts_exp:
            p0 = np.clip(np.concatenate([e0, [0.0], x0]), np.array(lo) + 1e-9, np.array(hi) - 1e-9)
            try:
                with np.errstate(over="ignore", invalid="ignore"):
                    trials.append(least_squares(resid, p0, bounds=(lo, hi), method="trf", x_scale="jac", max_nfev=40))
            except Exception:
                continue
    best = None
    for sol in sorted(trials, key=lambda s_: s_.cost)[:2]:
        try:
            with np.errstate(over="ignore", invalid="ignore"):
                sol = least_squares(resid, sol.x, bounds=(lo, hi), method="trf", x_scale="jac", max_nfev=600)
        except Exception:
            continue
        if best is None or sol.cost < best.cost:
            best = sol
    if best is None:
        raise ValueError(f"the {kind} reconvolution fit did not converge")
    p = best.x.copy()
    k, n_pts = len(p), len(tw)
    fit = curve(p)
    res, chi2, aicc = _goodness(fit, yw, sw, mle, bg, k)
    chi2_red = chi2 / max(n_pts - k, 1)
    try:
        cov = np.linalg.pinv(best.jac.T @ best.jac) * (max(chi2_red, 1.0) if absolute_sigma else chi2_red)
    except Exception:
        cov = np.full((k, k), np.nan)
    err = np.sqrt(np.clip(np.diag(cov), 0, None))
    ss_tot = float(((yw - yw.mean()) ** 2).sum())
    r2 = 1.0 - float(((fit - yw) ** 2).sum()) / ss_tot if ss_tot > 0 else np.nan
    dw = float((np.diff(res) ** 2).sum() / chi2) if chi2 > 0 else np.nan
    out: Dict[str, Any] = {"model": kind, "k": k, "n": n_pts, "chi2": chi2, "chi2_red": chi2_red, "aicc": float(aicc),
                           "r2": r2, "dw": dw, "valid": True, "reason": "", "beta": np.nan, "q_irf": p[:nq].copy(),
                           "q_irf_err": err[:nq].copy(), "offset": float(p[nq]), "offset_err": float(err[nq]),
                           "fit_curve": fit, "residual_curve": res}
    out = _describe_exp(out, p[ne:], cov[ne:, ne:])
    if irf_model.kind == "gaussian":
        out["t0"], out["t0_err"] = float(p[0]), float(err[0])
        out["irf_fwhm_fit"] = irf_model.fwhm(p[:nq])
        out["irf_fwhm_err"] = float(out["irf_fwhm_fit"] * err[1]) if nq == 2 else 0.0
        out["irf_at_bound"] = bool(nq == 2 and (abs(p[1] - lo[1]) < 1e-3 or abs(p[1] - hi[1]) < 1e-3))
    else:
        out["irf_shift"], out["irf_shift_err"] = float(p[0]), float(err[0])
        out["irf_fwhm_fit"], out["irf_fwhm_err"] = irf_model.fwhm(p[:nq]), np.nan
        out["irf_at_bound"] = bool(abs(p[0] - lo[0]) < 1e-3 * irf_model.span or abs(p[0] - hi[0]) < 1e-3 * irf_model.span)
    if n == 1 and (err[ne + 1] > MAX_REL_ERR or not np.isfinite(err[ne + 1])):
        out.update({"valid": False, "reason": "the lifetime is not determined (relative error above 100 %)"})
    return out


def _reconv_starts(kind: str, tail: Optional[Dict[str, Any]], t, y) -> List[np.ndarray]:
    """Starting points: the tail fit of the same model, the same with the
    shortest lifetime halved (the tail fit overestimates it), and the
    generic starts."""
    out: List[np.ndarray] = []
    if tail is not None and "p" in tail and len(tail["p"]) == 2 * int(kind[-1]):
        p = np.asarray(tail["p"], float).copy()
        out.append(p.copy())
        p[1] -= np.log(2.0)
        p[0] += np.log(2.0)
        out.append(p)
    return out + _starts(kind, t, y)[:2]


def tau_1e(t, y) -> float:
    """Model-free time for the signal to fall to 1/e of its peak."""
    t, y = np.asarray(t, float), np.asarray(y, float)
    k = int(np.argmax(y))
    level = y[k] / np.e
    below = np.where(y[k:] <= level)[0]
    if not len(below) or below[0] == 0:
        return np.nan
    i = k + int(below[0])
    y0, y1 = y[i - 1], y[i]
    f = (y0 - level) / (y0 - y1) if y0 != y1 else 0.0
    return float(t[i - 1] + f * (t[i] - t[i - 1]) - t[k])


def differential_lifetime(t, y, floor: float) -> Tuple[np.ndarray, np.ndarray]:
    """tau_diff(t) = -1 / (d ln I / dt) from a Savitzky-Golay derivative of
    ln I; points within a factor 3 of the noise floor are left out."""
    t, y = np.asarray(t, float), np.asarray(y, float)
    good = y > 3.0 * max(floor, 0.0)
    good &= y > 0
    if good.sum() < 15:
        return np.array([]), np.array([])
    last = int(np.where(~good)[0][0]) if (~good).any() else len(t)
    if last < 15:
        return np.array([]), np.array([])
    tt, ly = t[:last], np.log(y[:last])
    win = max(7, (last // 12) | 1)
    win = min(win, last - (1 - last % 2))
    win = win if win % 2 else win - 1
    step = np.diff(tt)
    if np.allclose(step, step[0], rtol=1e-3):
        d = savgol_filter(ly, win, 2, deriv=1, delta=float(step[0]))
    else:
        d = np.gradient(savgol_filter(ly, win, 2), tt)
    keep = d < 0
    half = win // 2
    keep[:half] = False
    keep[-half:] = False
    return tt[keep], -1.0 / d[keep]


def diffusion_length_um(tau: float, mobility_cm2_Vs: float, time_unit: str = "ns", temperature_k: float = 300.0) -> float:
    """L_D = sqrt(D tau) with D = mu kT / q."""
    if not (np.isfinite(tau) and tau > 0 and np.isfinite(mobility_cm2_Vs) and mobility_cm2_Vs > 0):
        return np.nan
    d = mobility_cm2_Vs * KB_EV * temperature_k            # cm2/s
    return float(np.sqrt(d * tau * TIME_UNITS.get(time_unit, 1e-9)) * 1e4)


def analyse(t, y, model: str = "auto", background: Any = "auto", skip: float = 0.0, t_end: Optional[float] = None,
            irf_fwhm: float = 0.0, mobility_cm2_Vs: float = 0.0, time_unit: str = "ns",
            temperature_k: float = 300.0, irf: str = "none", irf_t=None, irf_y=None) -> Dict[str, Any]:
    """Fit of a TRPL decay. `model` is auto, exp1, exp2, exp3 or stretched.

    `irf` none: tail fit from the peak (plus `skip`); `irf_fwhm` is then only
    used for the resolution check. gaussian: reconvolution with a Gaussian
    response of FWHM `irf_fwhm` (fitted when 0). measured: reconvolution with
    the response (irf_t, irf_y), recorded on the same time axis."""
    irf = str(irf or "none").strip().lower()
    if irf not in IRF_KINDS:
        raise ValueError(f"unknown instrument response: {irf} (none, gaussian or measured)")
    if irf != "none" and model == "stretched":
        raise ValueError("the stretched exponential is fitted as a tail fit only: set the response to none")
    d = prepare(t, y, background, skip if irf == "none" else 0.0, t_end)
    m = d["mask"]
    tf, yf, sf = d["t"][m], d["y"][m], d["sigma"][m]
    kinds = MODELS if model == "auto" else tuple(dict.fromkeys((model, "exp1")))
    fits: Dict[str, Dict[str, Any]] = {}
    for kind in kinds:
        if kind not in MODELS:
            raise ValueError(f"unknown model: {kind}")
        try:
            fits[kind] = fit_model(kind, tf, yf, sf, d["counts"], d["background"])
        except Exception as exc:
            if kind == model:
                raise
            fits[kind] = {"model": kind, "valid": False, "reason": str(exc), "aicc": np.inf, "chi2_red": np.nan, "k": 99}
    usable = {k: v for k, v in fits.items() if "p" in v}
    tail_model = choose_model(usable) if model == "auto" else model
    td, tau_d = differential_lifetime(tf, yf, d["noise_floor"])
    late = float(np.median(tau_d[-max(3, len(tau_d) // 3):])) if len(tau_d) >= 6 else np.nan
    res: Dict[str, Any] = {**{k: d[k] for k in ("t", "y", "y_raw", "sigma", "background", "background_from",
                                                  "counts", "peak", "dt", "noise_floor", "dynamic_range_dec")},
                           "requested": model, "tau_1e": tau_1e(d["t"], d["y"]), "tau_diff": (td, tau_d),
                           "tau_diff_late": late, "time_unit": time_unit, "mobility_cm2_Vs": float(mobility_cm2_Vs),
                           "irf": irf, "irf_entered": float(irf_fwhm), "skip_ignored": irf != "none" and float(skip) > 0,
                           "irf_curve": None, "irf_fwhm_err": np.nan, "irf_shift": np.nan, "irf_shift_err": np.nan,
                           "t0": np.nan, "irf_at_bound": False, "irf_dt": np.nan}
    if irf == "none":
        f = usable[tail_model]
        fit = model_curve(tail_model, f["p"], tf)
        if tail_model == "stretched":
            comps = [fit]
        else:
            comps = [np.exp(f["p"][2 * i]) * np.exp(-tf / np.exp(f["p"][2 * i + 1])) for i in range(len(f["p"]) // 2)]
        res.update({"mask": m, "t_fit": tf, "y_fit": yf, "fit": fit, "residuals": (fit - yf) / sf, "model": tail_model,
                    "candidates": fits, "components": comps, "method": "tail fit", "irf_fwhm": float(irf_fwhm)})
        chosen = tail_model
    else:
        tt, yy, ss, dt = d["t"], d["y"], d["sigma"], d["dt"]
        if irf == "gaussian":
            irf_model = _GaussianIRF(tt, yy, dt, float(irf_fwhm))
        else:
            if irf_t is None or irf_y is None:
                raise ValueError("reconvolution with a measured response needs the response file")
            if not np.allclose(np.diff(tt), dt, rtol=1e-3, atol=0.0):
                raise ValueError("reconvolution with a measured response needs equally spaced times")
            ir = prepare_irf(irf_t, irf_y)
            off = d["t_peak"]
            ir.update({"t": ir["t"] - off, "t_peak": ir["t_peak"] - off, "lobe": (ir["lobe"][0] - off, ir["lobe"][1] - off)})
            irf_model = _MeasuredIRF(ir, tt, yy, dt)
            res["irf_dt"] = ir["dt"]
        sel = tt >= max(irf_model.window_start(), float(tt[0]))
        if t_end is not None:
            sel &= tt <= float(t_end)
        if sel.sum() < 12:
            raise ValueError("fewer than 12 points in the reconvolution window")
        rkinds = RECONV_MODELS if model == "auto" else (model,)
        rfits: Dict[str, Dict[str, Any]] = {}
        for kind in rkinds:
            try:
                rfits[kind] = fit_reconvolution(kind, tt, yy, ss, d["counts"], irf_model, sel,
                                                _reconv_starts(kind, fits.get(kind), tf, yf), d["background"])
            except Exception as exc:
                if kind == model:
                    raise
                rfits[kind] = {"model": kind, "valid": False, "reason": str(exc), "aicc": np.inf, "chi2_red": np.nan,
                               "k": 99}
        rusable = {k: v for k, v in rfits.items() if "p" in v}
        if not rusable:
            raise ValueError("no reconvolution fit converged")
        chosen = choose_model(rusable) if model == "auto" else model
        f = rusable[chosen]
        tw = tt[sel]
        q = f["q_irf"]
        res["background"] = float(d["background"] + f["offset"])
        res["background_from"] = d["background_from"] + ", refined in the fit"
        if irf == "gaussian":
            comps = [irf_model.curve(q, f["p"][2 * i:2 * i + 2], tw) for i in range(len(f["p"]) // 2)]
            resp = irf_model.response(q, tw)
        else:
            last = int(np.where(sel)[0][-1]) + 1
            comps = [irf_model.curve_full(q, f["p"][2 * i:2 * i + 2])[:last][sel[:last]] for i in range(len(f["p"]) // 2)]
            resp = irf_model.response(q)[sel]
        off = f["offset"]
        yw = yy[sel] - off
        resp = resp * (float(yw.max()) / float(resp.max())) if resp.max() > 0 else resp
        res["y"] = yy - off
        res.update({"mask": sel, "t_fit": tw, "y_fit": yw, "fit": f["fit_curve"] - off, "residuals": f["residual_curve"],
                    "model": chosen, "candidates": rfits, "components": comps, "irf_curve": resp,
                    "method": "reconvolution",
                    "irf_fwhm": float(f["irf_fwhm_fit"]), "irf_fwhm_err": float(f["irf_fwhm_err"]),
                    "irf_at_bound": bool(f["irf_at_bound"]), "t0": float(f.get("t0", np.nan)),
                    "irf_shift": float(f.get("irf_shift", np.nan)), "irf_shift_err": float(f.get("irf_shift_err", np.nan)),
                    "irf_fixed": irf == "gaussian" and float(irf_fwhm) > 0})
        tail = usable.get(tail_model, {})
        res["tail"] = {"model": tail_model, "taus": tail.get("taus", np.array([np.nan])),
                       "tau_amp": tail.get("tau_amp", np.nan)}
    res["window"] = float(res["t_fit"].max() - res["t_fit"].min())
    for k in ("taus", "tau_errs", "amps", "amp_fracs", "int_fracs", "tau_amp", "tau_amp_err", "tau_int",
              "tau_int_err", "beta", "chi2_red", "r2", "dw", "aicc", "valid", "reason"):
        res[k] = f.get(k, np.nan)
    res["L_D_um"] = diffusion_length_um(res["tau_amp"], mobility_cm2_Vs, time_unit, temperature_k)
    res["warnings"] = checks(res)
    return res


def checks(r: Dict[str, Any]) -> List[str]:
    w: List[str] = []
    u = r["time_unit"]
    taus = np.atleast_1d(r["taus"])
    if not r["valid"] and r["reason"]:
        w.append(f"The {r['model']} model was requested but is not supported by the data: {r['reason']}.")
    if r["counts"]:
        if r["chi2_red"] > 1.3:
            w.append(f"Reduced chi-square {r['chi2_red']:.2f} is above 1.3: the model does not describe the decay "
                     "within the counting noise.")
        elif r["chi2_red"] < 0.7:
            w.append(f"Reduced chi-square {r['chi2_red']:.2f} is below 0.7: the data are smoother than Poisson noise "
                     "(binned, smoothed or scaled counts), so chi-square is not an absolute test here.")
    if np.isfinite(r["dw"]) and r["dw"] < 1.5:
        w.append(f"Durbin-Watson {r['dw']:.2f}: the residuals are correlated, a systematic misfit that the "
                 "chi-square alone can hide.")
    reconv = r.get("irf", "none") != "none"
    if not reconv:
        if np.isfinite(r["dt"]) and taus.min() < 3.0 * r["dt"]:
            w.append(f"The shortest lifetime ({taus.min():.3g} {u}) is below three time bins ({r['dt']:.3g} {u} each): "
                     "it is not resolved.")
        if r["irf_fwhm"] > 0 and taus.min() < r["irf_fwhm"]:
            w.append(f"The shortest lifetime ({taus.min():.3g} {u}) is below the instrument response "
                     f"({r['irf_fwhm']:.3g} {u} FWHM): a tail fit overestimates it (by about 5 % at one response "
                     "width, 20 % at half and 80 % at a fifth of it). Fit with the response (reconvolution) instead.")
    else:
        fw = r["irf_fwhm"]
        known = r["irf"] == "measured" or r.get("irf_fixed")
        lim = RECONV_LIMIT_KNOWN if known else RECONV_LIMIT_FITTED
        if np.isfinite(fw) and fw > 0 and taus.min() < lim * fw:
            w.append(f"The shortest lifetime ({taus.min():.3g} {u}) is below {lim:g} of the response width "
                     f"({fw:.3g} {u} FWHM" + ("" if known else ", fitted") + "): even with reconvolution its value "
                     "depends on the exact shape of the response; report it as an upper limit" +
                     ("." if known else ", or enter the measured response width."))
        if r["irf_at_bound"]:
            w.append("The fitted response " + ("width" if r["irf"] == "gaussian" else "shift") + " is at the limit "
                     "of its range: the rising edge does not determine it. Enter the measured response width or "
                     "load the measured response.")
        if r["irf"] == "measured":
            if np.isfinite(r["irf_shift"]) and np.isfinite(fw) and abs(r["irf_shift"]) > 2.0 * fw:
                w.append(f"The response had to be moved by {r['irf_shift']:.3g} {u}, more than twice its width: it "
                         "was probably recorded with another delay; check that it belongs to this measurement.")
            if np.isfinite(r["irf_dt"]) and abs(r["irf_dt"] - r["dt"]) > 1e-3 * r["dt"]:
                w.append(f"The response was recorded with {r['irf_dt']:.3g} {u} bins and the decay with "
                         f"{r['dt']:.3g} {u} bins; the response was interpolated onto the decay's time grid.")
        if r.get("skip_ignored"):
            w.append("'Skip after peak' is not used with reconvolution: the fit includes the rising edge.")
    if taus.max() > 0.5 * r["window"]:
        w.append(f"The longest lifetime ({taus.max():.3g} {u}) exceeds half the fit window ({r['window']:.3g} {u}): "
                 "the decay is not followed far enough and that lifetime is poorly constrained.")
    if r["dynamic_range_dec"] < 1.5:
        w.append(f"The decay spans only {r['dynamic_range_dec']:.1f} decades above the noise floor; more than one "
                 "exponential cannot be separated reliably.")
    st = r["candidates"].get("stretched")
    if not reconv and r["model"] in ("exp2", "exp3") and st and st.get("valid") and np.isfinite(st.get("aicc", np.inf)) \
            and st["aicc"] < r["aicc"] - 10.0:
        w.append(f"A stretched exponential (beta = {st['beta']:.2f}) describes the decay better with fewer parameters "
                 f"(AICc {st['aicc']:.0f} against {r['aicc']:.0f}): the decay is a continuous distribution of rates, "
                 "and the separate lifetimes are a parametrisation rather than distinct processes.")
    if r["background_from"] == "flat tail":
        w.append("The background was taken from the end of the trace because there are no points before the pulse; "
                 "a slow component would be partly subtracted with it.")
    return w


def summary_rows(r: Dict[str, Any]) -> List[Tuple[str, Any, str]]:
    u = r["time_unit"]
    rows: List[Tuple[str, Any, str]] = [("Model", r["model"], ""), ("Method", r.get("method", "tail fit"), ""),
                                        ("Points fitted", len(r["t_fit"]), "")]
    if r.get("irf", "none") != "none":
        rows.append(("Response", "Gaussian" if r["irf"] == "gaussian" else "measured file", ""))
        if r["irf"] == "gaussian":
            how = "entered" if r.get("irf_fixed") else "fitted"
            rows += [(f"Response FWHM ({how})", r["irf_fwhm"], u)]
            if not r.get("irf_fixed"):
                rows += [("Response FWHM std. error", r["irf_fwhm_err"], u)]
            rows += [("Time zero t0 (from the peak)", r["t0"], u)]
        else:
            rows += [("Response FWHM (measured file)", r["irf_fwhm"], u), ("Response shift", r["irf_shift"], u),
                     ("Response shift std. error", r["irf_shift_err"], u)]
    taus, errs = np.atleast_1d(r["taus"]), np.atleast_1d(r["tau_errs"])
    af, itf = np.atleast_1d(r["amp_fracs"]), np.atleast_1d(r["int_fracs"])
    for i in range(len(taus)):
        rows += [(f"tau{i + 1}", taus[i], u), (f"tau{i + 1} std. error", errs[i], u)]
        if len(taus) > 1:
            rows += [(f"A{i + 1} (amplitude fraction)", 100.0 * af[i], "%"), (f"f{i + 1} (intensity fraction)", 100.0 * itf[i], "%")]
    if r["model"] == "stretched":
        rows += [("beta", r["beta"], ""), ("<tau> (Kohlrausch mean)", r["tau_amp"], u)]
    else:
        rows += [("<tau> amplitude weighted", r["tau_amp"], u), ("<tau> amplitude weighted, std. error", r["tau_amp_err"], u),
                 ("<tau> intensity weighted", r["tau_int"], u)]
    rows += [("tau 1/e (model free)", r["tau_1e"], u), ("Differential lifetime, late", r["tau_diff_late"], u),
             ("Reduced chi-square" + ("" if r["counts"] else " (relative weights)"), r["chi2_red"], ""),
             ("R2", r["r2"], ""), ("Durbin-Watson", r["dw"], ""), ("Background", r["background"], "counts" if r["counts"] else ""),
             ("Dynamic range", r["dynamic_range_dec"], "decades")]
    if r.get("irf", "none") != "none" and "tail" in r:
        tl = r["tail"]
        rows += [("Tail fit for comparison: model", tl["model"], ""),
                 ("Tail fit for comparison: shortest tau", float(np.nanmin(np.atleast_1d(tl["taus"]))), u),
                 ("Tail fit for comparison: <tau>", tl["tau_amp"], u)]
    if np.isfinite(r["L_D_um"]):
        rows.append(("Diffusion length (from <tau>, entered mobility)", r["L_D_um"], "um"))
    return rows


def irf_shape(x, fwhm: float, tail_tau: float = 0.0, tail_frac: float = 0.0) -> np.ndarray:
    """Unit-area response: a Gaussian of the given FWHM, optionally with a
    fraction `tail_frac` in an exponential diffusion tail (as in a SPAD)."""
    s = fwhm / FWHM_PER_SIGMA
    x = np.asarray(x, float)
    g = np.exp(-0.5 * (x / s) ** 2) / (s * np.sqrt(2.0 * np.pi))
    if tail_tau > 0 and tail_frac > 0:
        g = (1.0 - tail_frac) * g + tail_frac * gauss_exp(x, tail_tau, s) / tail_tau
    return g


def _binned(t, func, oversample: int = 10) -> np.ndarray:
    """Mean of func over each time bin centred on t (equally spaced)."""
    dt = float(t[1] - t[0])
    q = (np.arange(oversample) + 0.5) / oversample - 0.5
    fine = (t[:, None] + q[None, :] * dt).ravel()
    return func(fine).reshape(len(t), oversample).mean(axis=1)


def simulate(taus=(5.0, 80.0), amps=(0.7, 0.3), peak_counts: float = 10000.0, background: float = 5.0,
             n: int = 1000, t_max: float = 500.0, t0: float = 20.0, poisson: bool = True, seed: int = 0,
             beta: Optional[float] = None, irf_fwhm: float = 0.0, irf_tail_tau: float = 0.0,
             irf_tail_frac: float = 0.0, irf_delay: float = 0.0) -> Tuple[np.ndarray, np.ndarray]:
    """Counting trace with a step rise at t0 (for tests and validation). With
    irf_fwhm > 0 the decay is convolved with `irf_shape` (centred irf_delay
    after t0) on a grid ten times finer than the bins and averaged over each
    bin, so the reconvolution fit is tested against binned data rather than
    against its own model."""
    t = np.linspace(0.0, t_max, n)
    a = np.asarray(amps, float) / np.sum(amps)
    if irf_fwhm > 0:
        if beta is not None:
            raise ValueError("simulate: a response is supported for exponential decays only")
        s = irf_fwhm / FWHM_PER_SIGMA
        def conv(tt):
            x = tt - t0 - irf_delay
            out = np.zeros_like(tt)
            for ai, ti in zip(a, taus):
                g = gauss_exp(x, ti, s)
                if irf_tail_tau > 0 and irf_tail_frac > 0:
                    # Gaussian (x) tail (x) decay: the tail and the decay combine as two exponentials
                    if abs(ti - irf_tail_tau) < 1e-9 * ti:
                        ti = ti * (1 + 1e-6)
                    tail = ti / (ti - irf_tail_tau) * (gauss_exp(x, ti, s) - gauss_exp(x, irf_tail_tau, s))
                    g = (1.0 - irf_tail_frac) * g + irf_tail_frac * tail
                out += ai * g
            return out
        sig = _binned(t, conv)
        sig = sig / sig.max()
        y = peak_counts * sig + background
    else:
        x = np.clip(t - t0, 0.0, None)
        if beta is not None:
            sig = np.exp(-np.power(x / taus[0], beta))
        else:
            sig = sum(ai * np.exp(-x / ti) for ai, ti in zip(a, taus))
        y = np.where(t >= t0, peak_counts * sig, 0.0) + background
    if poisson:
        y = np.random.default_rng(seed).poisson(y).astype(float)
    return t, y


def simulate_irf(fwhm: float, tail_tau: float = 0.0, tail_frac: float = 0.0, peak_counts: float = 10000.0,
                 background: float = 2.0, n: int = 1000, t_max: float = 500.0, t0: float = 20.0,
                 poisson: bool = True, seed: int = 1) -> Tuple[np.ndarray, np.ndarray]:
    """Recorded response (a scatterer) on the same time axis as `simulate`."""
    t = np.linspace(0.0, t_max, n)
    r = _binned(t, lambda tt: irf_shape(tt - t0, fwhm, tail_tau, tail_frac))
    y = peak_counts * r / r.max() + background
    if poisson:
        y = np.random.default_rng(seed).poisson(y).astype(float)
    return t, y
