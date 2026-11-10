"""Operational stability: T80, burn-in, stabilised lifetime Ts80 and
degradation rate from a power (or efficiency) against time trace.

Models fitted to the normalised trace E(t)
    linear        E = a - b t
    exponential   E = a exp(-t / tau)
    burn-in       E = a1 exp(-t / tau1) + a0 - b t       fast loss, then linear
    bi-exponential E = a1 exp(-t / tau1) + a2 exp(-t / tau2)

The model is chosen with AICc. T80 is the first time the measured trace
falls below 80 % of its reference and stays there (a transient dip does not
count). When the trace never reaches the level, the chosen model is
extrapolated and the value is marked as extrapolated - an extrapolation
beyond the measured time rests entirely on the model and must not be
reported as a measured lifetime.

With a burn-in, the stabilised point t_s is where the fast term has decayed
to 5 % (three time constants) and E_s the value there; Ts80 is the time
from t_s until the trace reaches 80 % of E_s. T80 and Ts80 are only
comparable between reports that state the protocol (ISOS-D, -L, -T, -O, ...),
the load condition and the normalisation.

References
    Reese et al., Sol. Energy Mater. Sol. Cells 95, 1253 (2011)       ISOS protocols
    Roesch et al., Adv. Energy Mater. 5, 1501407 (2015)               burn-in, Ts80
    Khenkin et al., Nat. Energy 5, 35 (2020)                          ISOS for perovskites
    Burnham, Anderson, Model Selection and Multimodel Inference (2002)
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import brentq, least_squares

TIME_TO_HOURS = {"s": 1.0 / 3600.0, "min": 1.0 / 60.0, "h": 1.0, "day": 24.0}
MODELS = ("linear", "exponential", "burn-in", "bi-exponential")
PROTOCOLS = ("not stated", "ISOS-D-1", "ISOS-D-2", "ISOS-D-3", "ISOS-L-1", "ISOS-L-2", "ISOS-L-3", "ISOS-T-1",
             "ISOS-O-1", "ISOS-V-1", "ISOS-LC-1", "MPP tracking")

_trapz = getattr(np, "trapezoid", None) or np.trapz     # numpy 2 renamed trapz

COLUMN_SPEC = [
    ("t", [r"time", r"^t\b", r"hour", r"elapsed", r"duration"], 0),
    ("y", [r"pce", r"eff", r"power", r"pmax", r"pmpp", r"norm", r"eta"], 1),
]


def model_curve(kind: str, p, t) -> np.ndarray:
    t = np.asarray(t, float)
    if kind == "linear":
        return p[0] - p[1] * t
    if kind == "exponential":
        return p[0] * np.exp(-t / p[1])
    if kind == "burn-in":
        return p[0] * np.exp(-t / p[1]) + p[2] - p[3] * t
    return p[0] * np.exp(-t / p[1]) + p[2] * np.exp(-t / p[3])


def _setup(kind: str, t, y):
    span = float(t.max() - t.min()) or 1.0
    y0, y1 = float(y[0]), float(y[-1])
    big = 1e6 * span
    if kind == "linear":
        return [[y0, (y0 - y1) / span]], ([-np.inf, -np.inf], [np.inf, np.inf])
    if kind == "exponential":
        return [[y0, span * f] for f in (0.5, 3.0, 30.0)], ([0.0, span * 1e-4], [np.inf, big])
    if kind == "burn-in":
        starts = [[max(y0 - y1, 0.02) * a, span * f, y0 - max(y0 - y1, 0.02) * a, 0.0]
                  for f in (0.02, 0.1, 0.3) for a in (0.3, 0.8)]
        return starts, ([0.0, span * 1e-4, 0.0, -np.inf], [np.inf, span, np.inf, np.inf])
    starts = [[y0 * a, span * f, y0 * (1 - a), span * g] for f, g in ((0.03, 3.0), (0.1, 10.0), (0.3, 30.0)) for a in (0.2, 0.5)]
    return starts, ([0.0, span * 1e-4, 0.0, span * 1e-4], [np.inf, big, np.inf, big])


def fit_model(kind: str, t, y) -> Dict[str, Any]:
    t, y = np.asarray(t, float), np.asarray(y, float)
    starts, (lo, hi) = _setup(kind, t, y)
    best = None
    for p0 in starts:
        try:
            sol = least_squares(lambda p: model_curve(kind, p, t) - y, np.clip(p0, lo, hi), bounds=(lo, hi),
                                x_scale="jac", max_nfev=600)
        except Exception:
            continue
        if best is None or sol.cost < best.cost:
            best = sol
    if best is None:
        raise ValueError(f"the {kind} fit did not converge")
    p = best.x.copy()
    if kind == "bi-exponential" and p[1] > p[3]:
        p = p[[2, 3, 0, 1]]
        jac = best.jac[:, [2, 3, 0, 1]]
    else:
        jac = best.jac
    n, k = len(t), len(p)
    rss = float(((model_curve(kind, p, t) - y) ** 2).sum())
    s2 = rss / max(n - k, 1)
    try:
        err = np.sqrt(np.clip(np.diag(np.linalg.pinv(jac.T @ jac) * s2), 0, None))
    except Exception:
        err = np.full(k, np.nan)
    aicc = n * np.log(max(rss, 1e-300) / n) + 2 * k + (2 * k * (k + 1) / (n - k - 1) if n > k + 1 else np.inf)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    out = {"model": kind, "p": p, "perr": err, "k": k, "rss": rss, "rmse": float(np.sqrt(rss / n)), "aicc": float(aicc),
           "r2": 1.0 - rss / ss_tot if ss_tot > 0 else np.nan, "valid": True, "reason": ""}
    span = float(t.max() - t.min())
    if kind == "burn-in":
        if p[0] < 0.01:
            out.update({"valid": False, "reason": "the fast term is below 1 % of the initial value"})
        elif 3.0 * p[1] > span:
            out.update({"valid": False, "reason": "the fast term has not finished within the measurement"})
        elif not np.isfinite(err[1]) or err[1] > p[1]:
            out.update({"valid": False, "reason": "the burn-in time constant is not determined"})
    elif kind == "bi-exponential":
        if min(p[0], p[2]) < 0.01:
            out.update({"valid": False, "reason": "one term is below 1 % of the initial value"})
        elif p[3] / p[1] < 3.0:
            out.update({"valid": False, "reason": "the two time constants are closer than a factor 3"})
        elif not np.isfinite(err).all() or err[1] > p[1] or err[3] > p[3]:
            out.update({"valid": False, "reason": "a time constant is not determined"})
    elif kind == "exponential" and (not np.isfinite(err[1]) or err[1] > p[1]):
        out.update({"valid": False, "reason": "the time constant is not determined"})
    return out


def choose_model(fits: Dict[str, Dict[str, Any]]) -> str:
    cand = [v for v in fits.values() if v.get("valid") and "p" in v] or [v for v in fits.values() if "p" in v]
    best = min(c["aicc"] for c in cand)
    for c in sorted(cand, key=lambda c: (c["k"], MODELS.index(c["model"]))):
        if c["aicc"] - best <= 2.0:
            return c["model"]
    return cand[0]["model"]


def crossing_time(t, y, level: float, persist: int = 3, start: int = 0) -> float:
    """First time the trace falls below `level` and stays below it for the
    next `persist` points (or to the end); linear interpolation."""
    t, y = np.asarray(t, float), np.asarray(y, float)
    if len(y) >= 15:                       # 5-point running median: single noisy points do not set the lifetime
        pad = np.r_[y[:2][::-1], y, y[-2:][::-1]]
        y = np.median(np.lib.stride_tricks.sliding_window_view(pad, 5), axis=1)
    below = y < level
    for i in range(max(start, 1), len(t)):
        if below[i] and not below[i - 1]:
            j = min(len(t), i + persist)
            if below[i:j].all():
                f = (y[i - 1] - level) / (y[i - 1] - y[i]) if y[i - 1] != y[i] else 0.0
                return float(t[i - 1] + f * (t[i] - t[i - 1]))
    return np.nan


def extrapolate_crossing(func: Callable[[float], float], level: float, t_from: float, t_limit: float) -> float:
    """Time at which the model reaches `level` after t_from; inf when it
    does not within t_limit."""
    g = lambda x: func(x) - level
    if g(t_from) <= 0:
        return float(t_from)
    grid = np.geomspace(max(t_from, 1e-9), t_limit, 400)
    vals = np.array([g(x) for x in grid])
    k = np.where(vals <= 0)[0]
    if not len(k):
        return np.inf
    return float(brentq(g, grid[k[0] - 1] if k[0] else t_from, grid[k[0]]))


def analyse(t, y, time_unit: str = "h", norm: str = "initial", threshold: float = 0.8, model: str = "auto",
            protocol: str = "not stated", n_initial: int = 1) -> Dict[str, Any]:
    """Stability trace -> T80, burn-in, Ts80, rate. Times are converted to
    hours. `norm` is initial, maximum or none (data already normalised;
    percent values are divided by 100)."""
    t, y = np.asarray(t, float), np.asarray(y, float)
    ok = np.isfinite(t) & np.isfinite(y)
    t, y = t[ok] * TIME_TO_HOURS.get(time_unit, 1.0), y[ok]
    order = np.argsort(t, kind="stable")
    t, y = t[order], y[order]
    if len(t) < 6:
        raise ValueError("stability analysis needs at least 6 points")
    t = t - t[0]
    if norm == "maximum":
        ref = float(np.max(y))
    elif norm == "none":
        ref = 100.0 if np.nanmax(y) > 2.0 else 1.0
    else:
        ref = float(np.mean(y[:max(1, int(n_initial))]))
    if ref <= 0:
        raise ValueError("the reference value for normalisation is not positive")
    e = y / ref
    duration = float(t[-1])
    kinds = MODELS if model == "auto" else (model,)
    fits: Dict[str, Dict[str, Any]] = {}
    for kind in kinds:
        if kind not in MODELS:
            raise ValueError(f"unknown model: {kind}")
        try:
            fits[kind] = fit_model(kind, t, e)
        except Exception as exc:
            if model != "auto":
                raise
            fits[kind] = {"model": kind, "valid": False, "reason": str(exc), "aicc": np.inf, "k": 99}
    chosen = choose_model(fits) if model == "auto" else model
    f = fits[chosen]
    func = lambda x: float(model_curve(chosen, f["p"], np.array([x]))[0])
    level = float(threshold)
    k_max = int(np.argmax(e))
    t_cross = crossing_time(t, e, level, start=k_max if norm == "maximum" else 0)
    res: Dict[str, Any] = {"t": t, "e": e, "raw": y, "reference": ref, "norm": norm, "threshold": float(threshold),
                           "duration_h": duration, "model": chosen, "requested": model, "candidates": fits,
                           "p": f["p"], "perr": f["perr"], "rmse": f["rmse"], "r2": f["r2"], "valid": f["valid"],
                           "reason": f["reason"], "protocol": protocol,
                           "t_dense": np.linspace(0.0, duration, 400), "T_measured": t_cross,
                           "T_reached": bool(np.isfinite(t_cross)), "T_extrapolated": np.nan, "T_model": np.nan,
                           "final": float(np.mean(e[-max(1, len(e) // 20):])), "e_max": float(e[k_max]),
                           "t_max": float(t[k_max]),
                           "mean_output": float(_trapz(e, t) / duration) if duration > 0 else np.nan,
                           "burn_in": False, "t_s": np.nan, "E_s": np.nan, "burn_in_loss_pct": np.nan,
                           "Ts_measured": np.nan, "Ts_extrapolated": np.nan, "Ts_reached": False,
                           "rate_pct_per_1000h": np.nan, "rate_err": np.nan}
    res["fit_dense"] = model_curve(chosen, f["p"], res["t_dense"])
    limit = max(duration, 1e-6) * 1000.0
    if not res["T_reached"]:
        res["T_extrapolated"] = extrapolate_crossing(func, level, duration, limit)
    else:                                   # the same level read from the fitted curve, inside the measured range
        x = extrapolate_crossing(func, level, 1e-9 * max(duration, 1.0), duration)
        res["T_model"] = x if np.isfinite(x) else np.nan
    p = f["p"]
    burn = chosen == "burn-in" or (chosen == "bi-exponential" and f["valid"] and 3.0 * p[1] < duration)
    if burn and f["valid"]:
        t_s = 3.0 * p[1]
        e_s = func(t_s)
        k_s = int(np.searchsorted(t, t_s))
        res.update({"burn_in": True, "t_s": float(t_s), "E_s": float(e_s), "burn_in_loss_pct": 100.0 * (float(e[0]) - e_s)})
        ts_cross = crossing_time(t, e, threshold * e_s, start=max(k_s, 1))
        if np.isfinite(ts_cross):
            res.update({"Ts_measured": ts_cross - t_s, "Ts_reached": True})
        else:
            x = extrapolate_crossing(func, threshold * e_s, duration, limit)
            res["Ts_extrapolated"] = x - t_s if np.isfinite(x) else np.inf
    # linear rate over the stabilised part (after t_s) or the whole trace
    from scripts.common.curve_io import linfit
    sel = t >= (res["t_s"] if res["burn_in"] else 0.0)
    if sel.sum() >= 4:
        lf = linfit(t[sel], e[sel])
        res["rate_pct_per_1000h"] = float(-lf["slope"] * 100.0 * 1000.0)
        res["rate_err"] = float(lf["slope_err"] * 100.0 * 1000.0) if np.isfinite(lf["slope_err"]) else np.nan
    res["warnings"] = checks(res)
    return res


def checks(r: Dict[str, Any]) -> List[str]:
    w: List[str] = []
    pct = 100.0 * r["threshold"]
    if not r["T_reached"]:
        x = r["T_extrapolated"]
        if not np.isfinite(x):
            w.append(f"The trace does not reach {pct:.0f} % and the fitted model never does within 1000 times the "
                     "measured time: no lifetime can be stated, only that it exceeds the measurement.")
        else:
            ratio = x / r["duration_h"]
            w.append(f"T{pct:.0f} = {x:.3g} h is extrapolated ({ratio:.1f} times the measured {r['duration_h']:.3g} h) "
                     "with the fitted model. " + ("Beyond about twice the measured time the value depends on the "
                     "model more than on the data: quote it as an estimate, or as T > measured time."
                                                   if ratio > 2.0 else "Report it as extrapolated."))
    if r["e_max"] > 1.03 and r["norm"] == "initial":
        w.append(f"The output rises to {100 * r['e_max']:.1f} % of its first value at {r['t_max']:.3g} h before "
                 "falling (light soaking). Normalising to the first point overstates the lifetime compared with "
                 "normalising to the maximum; state which was used.")
    if r["protocol"] == "not stated":
        w.append("No ageing protocol is recorded. A lifetime is comparable only with its ISOS protocol, load "
                 "condition (MPP, open circuit, short circuit), temperature and atmosphere.")
    if len(r["t"]) < 15:
        w.append(f"Only {len(r['t'])} points: the burn-in and the linear loss cannot be separated reliably.")
    if not r["valid"] and r["reason"]:
        w.append(f"The {r['model']} model is not supported by the data: {r['reason']}.")
    if r["rmse"] > 0.02:
        w.append(f"The scatter around the fit is {100 * r['rmse']:.1f} % of the reference; periodic day-night or "
                 "temperature swings should be averaged before reading a lifetime.")
    return w


def summary_rows(r: Dict[str, Any]) -> List[Tuple[str, Any, str]]:
    pct = f"{100 * r['threshold']:.0f}"
    rows: List[Tuple[str, Any, str]] = [
        ("Duration", r["duration_h"], "h"), ("Points", len(r["t"]), ""), ("Reference value", r["reference"], ""),
        ("Normalised to", r["norm"], ""), ("Protocol", r["protocol"], ""), ("Model", r["model"], ""),
        (f"T{pct} (measured)", r["T_measured"], "h"), (f"T{pct} (on the fitted curve)", r["T_model"], "h"),
        (f"T{pct} (extrapolated)", r["T_extrapolated"], "h"),
        ("Final output", 100.0 * r["final"], "%"), ("Maximum output", 100.0 * r["e_max"], "%"),
        ("Time of maximum", r["t_max"], "h"), ("Mean output over the test", 100.0 * r["mean_output"], "%"),
        ("Linear loss rate" + (" after burn-in" if r["burn_in"] else ""), r["rate_pct_per_1000h"], "%/1000 h"),
        ("Loss rate std. error", r["rate_err"], "%/1000 h"),
    ]
    if r["burn_in"]:
        rows += [("Burn-in time constant", r["p"][1], "h"), ("Stabilised after t_s", r["t_s"], "h"),
                 ("Stabilised output E_s", 100.0 * r["E_s"], "%"), ("Burn-in loss", r["burn_in_loss_pct"], "% abs"),
                 (f"Ts{pct} (measured)", r["Ts_measured"], "h"), (f"Ts{pct} (extrapolated)", r["Ts_extrapolated"], "h")]
    rows += [("Fit RMSE", 100.0 * r["rmse"], "%"), ("Fit R2", r["r2"], "")]
    return rows


def simulate(a1: float = 0.12, tau1: float = 40.0, rate_per_h: float = 1.0e-4, t_end: float = 1000.0, n: int = 200,
             pce0: float = 20.0, noise: float = 0.004, seed: int = 0) -> Tuple[np.ndarray, np.ndarray]:
    """Burn-in plus linear loss (for tests and validation); returns hours, PCE %."""
    t = np.linspace(0.0, t_end, n)
    e = a1 * np.exp(-t / tau1) + (1.0 - a1) - rate_per_h * t
    if noise:
        e = e + noise * np.random.default_rng(seed).standard_normal(n)
    return t, pce0 * e
