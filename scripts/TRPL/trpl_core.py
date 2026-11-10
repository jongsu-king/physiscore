"""Time-resolved photoluminescence: multi-exponential and stretched-
exponential tail fits, model selection, average and differential lifetimes.

    I(t) = sum_i A_i exp(-t / tau_i)                 1 - 3 components
    I(t) = A exp(-(t / tau)^beta)                    stretched (Kohlrausch)

    <tau>_amp = sum A_i tau_i / sum A_i              amplitude weighted
    <tau>_int = sum A_i tau_i^2 / sum A_i tau_i      intensity weighted
    <tau>_KWW = (tau / beta) Gamma(1 / beta)
    tau_diff(t) = -(d ln I / dt)^-1                  differential lifetime

The fit is a tail fit: it starts at (or a chosen delay after) the peak and
does not deconvolve the instrument response, so a component shorter than
the response or than about three time bins is not resolved. Counting data
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
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import savgol_filter
from scipy.special import gamma as _gamma

KB_EV = 8.617333262e-5
TIME_UNITS = {"ps": 1e-12, "ns": 1e-9, "us": 1e-6, "ms": 1e-3, "s": 1.0}
MODELS = ("exp1", "exp2", "exp3", "stretched")
MIN_FRACTION, MIN_RATIO, MAX_REL_ERR = 0.01, 1.5, 1.0

COLUMN_SPEC = [
    ("t", [r"time", r"delay", r"^t\b", r"\b[pnum]?s\b"], 0),
    ("y", [r"count", r"intens", r"\bpl\b", r"signal", r"decay", r"^y\b"], 1),
]


def looks_like_counts(y) -> bool:
    y = np.asarray(y, float)
    y = y[np.isfinite(y)]
    return bool(len(y) and y.max() >= 50 and y.min() >= 0 and np.allclose(y, np.round(y), atol=1e-6))


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
        n_pre = int(0.8 * rise)
        tail = y[-max(8, len(y) // 20):]
        half = len(tail) // 2
        noise = np.sqrt(max(np.median(tail), 1.0)) if counts else 0.02 * peak
        if n_pre >= 5:
            bg, bg_from = float(np.median(y[:n_pre])), "before the pulse"
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


def fit_model(kind: str, t, y, sigma, absolute_sigma: bool) -> Dict[str, Any]:
    """Weighted least-squares fit of one model; returns parameters, errors
    and goodness of fit."""
    t, y, sigma = (np.asarray(a, float) for a in (t, y, sigma))
    span = float(t.max() - t.min()) or 1.0
    if kind == "stretched":
        lo, hi = [-np.inf, np.log(span * 1e-5), 0.2], [np.inf, np.log(span * 1e3), 1.0]
    else:
        n = int(kind[-1])
        lo, hi = [-np.inf, np.log(span * 1e-5)] * n, [np.inf, np.log(span * 1e3)] * n
    best = None
    for p0 in _starts(kind, t, y):
        try:
            sol = least_squares(lambda p: (model_curve(kind, p, t) - y) / sigma, np.clip(p0, lo, hi),
                                bounds=(lo, hi), method="trf", x_scale="jac", max_nfev=600)
        except Exception:
            continue
        if best is None or sol.cost < best.cost:
            best = sol
    if best is None:
        raise ValueError(f"the {kind} fit did not converge")
    p = best.x.copy()
    k, n_pts = len(p), len(t)
    res = (model_curve(kind, p, t) - y) / sigma
    chi2 = float((res ** 2).sum())
    dof = max(n_pts - k, 1)
    chi2_red = chi2 / dof
    try:
        cov = np.linalg.pinv(best.jac.T @ best.jac) * (max(chi2_red, 1.0) if absolute_sigma else chi2_red)
    except Exception:
        cov = np.full((k, k), np.nan)
    err = np.sqrt(np.clip(np.diag(cov), 0, None))
    aicc = n_pts * np.log(max(chi2, 1e-300) / n_pts) + 2 * k + (2 * k * (k + 1) / (n_pts - k - 1) if n_pts > k + 1 else np.inf)
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
            temperature_k: float = 300.0) -> Dict[str, Any]:
    """Tail fit of a TRPL decay. `model` is auto, exp1, exp2, exp3 or stretched."""
    d = prepare(t, y, background, skip, t_end)
    m = d["mask"]
    tf, yf, sf = d["t"][m], d["y"][m], d["sigma"][m]
    kinds = MODELS if model == "auto" else tuple(dict.fromkeys((model, "exp1")))
    fits: Dict[str, Dict[str, Any]] = {}
    for kind in kinds:
        if kind not in MODELS:
            raise ValueError(f"unknown model: {kind}")
        try:
            fits[kind] = fit_model(kind, tf, yf, sf, d["counts"])
        except Exception as exc:
            if kind == model:
                raise
            fits[kind] = {"model": kind, "valid": False, "reason": str(exc), "aicc": np.inf, "chi2_red": np.nan, "k": 99}
    usable = {k: v for k, v in fits.items() if "p" in v}
    chosen = choose_model(usable) if model == "auto" else model
    f = usable[chosen]
    td, tau_d = differential_lifetime(tf, yf, d["noise_floor"])
    late = float(np.median(tau_d[-max(3, len(tau_d) // 3):])) if len(tau_d) >= 6 else np.nan
    res: Dict[str, Any] = {**{k: d[k] for k in ("t", "y", "y_raw", "sigma", "mask", "background", "background_from",
                                                  "counts", "peak", "dt", "noise_floor", "dynamic_range_dec")},
                           "t_fit": tf, "y_fit": yf, "fit": model_curve(chosen, f["p"], tf),
                           "residuals": (model_curve(chosen, f["p"], tf) - yf) / sf,
                           "model": chosen, "requested": model, "candidates": fits, "window": float(tf.max() - tf.min()),
                           "tau_1e": tau_1e(d["t"], d["y"]), "tau_diff": (td, tau_d), "tau_diff_late": late,
                           "irf_fwhm": float(irf_fwhm), "time_unit": time_unit, "mobility_cm2_Vs": float(mobility_cm2_Vs)}
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
    if np.isfinite(r["dt"]) and taus.min() < 3.0 * r["dt"]:
        w.append(f"The shortest lifetime ({taus.min():.3g} {u}) is below three time bins ({r['dt']:.3g} {u} each): "
                 "it is not resolved.")
    if r["irf_fwhm"] > 0 and taus.min() < r["irf_fwhm"]:
        w.append(f"The shortest lifetime ({taus.min():.3g} {u}) is below the instrument response "
                 f"({r['irf_fwhm']:.3g} {u} FWHM); a tail fit cannot resolve it without deconvolution.")
    if taus.max() > 0.5 * r["window"]:
        w.append(f"The longest lifetime ({taus.max():.3g} {u}) exceeds half the fit window ({r['window']:.3g} {u}): "
                 "the decay is not followed far enough and that lifetime is poorly constrained.")
    if r["dynamic_range_dec"] < 1.5:
        w.append(f"The decay spans only {r['dynamic_range_dec']:.1f} decades above the noise floor; more than one "
                 "exponential cannot be separated reliably.")
    st = r["candidates"].get("stretched")
    if r["model"] in ("exp2", "exp3") and st and st.get("valid") and np.isfinite(st.get("aicc", np.inf)) \
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
    rows: List[Tuple[str, Any, str]] = [("Model", r["model"], ""), ("Points fitted", len(r["t_fit"]), "")]
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
    if np.isfinite(r["L_D_um"]):
        rows.append(("Diffusion length (from <tau>, entered mobility)", r["L_D_um"], "um"))
    return rows


def simulate(taus=(5.0, 80.0), amps=(0.7, 0.3), peak_counts: float = 10000.0, background: float = 5.0,
             n: int = 1000, t_max: float = 500.0, t0: float = 20.0, poisson: bool = True, seed: int = 0,
             beta: Optional[float] = None) -> Tuple[np.ndarray, np.ndarray]:
    """Counting trace with a step rise at t0 (for tests and validation)."""
    t = np.linspace(0.0, t_max, n)
    x = np.clip(t - t0, 0.0, None)
    a = np.asarray(amps, float) / np.sum(amps)
    if beta is not None:
        sig = np.exp(-np.power(x / taus[0], beta))
    else:
        sig = sum(ai * np.exp(-x / ti) for ai, ti in zip(a, taus))
    y = np.where(t >= t0, peak_counts * sig, 0.0) + background
    if poisson:
        y = np.random.default_rng(seed).poisson(y).astype(float)
    return t, y
