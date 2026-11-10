"""Capacitance-voltage (Mott-Schottky) analysis.

    1 / C^2 = 2 (V_bi - V - kT/q) / (q eps A^2 N)

    N     = 2 / (q eps A^2 |d(1/C^2)/dV|)        apparent doping density
    V_bi  = (voltage intercept) + kT/q
    W(V)  = eps A / C                            depletion width
    N(W)  = -2 / (q eps A^2 d(1/C^2)/dV)         doping profile

The straight part of 1/C^2 is found automatically: of all windows of
consecutive points with a negative slope and R2 above a threshold, the one
covering the widest voltage range is taken.

A thin, weakly doped absorber is fully depleted, and its capacitance is the
geometric capacitance plus the injected charge at forward bias. That
combination also produces a straight 1/C^2 section, with an apparent
density of the order

    N_min = 27 m kT eps / (4 q^2 d^2)           (Ravishankar 2021, 2022)

where d is the absorber thickness and m the slope factor of the capacitance
rise. Only a density clearly above N_min can be a real doping or trap
density; anything near it is a property of the geometry.

References
    Sze, Ng, Physics of Semiconductor Devices, 3rd ed. (2007), ch. 2
    Kirchartz, Gong, Hawks et al., J. Phys. Chem. C 116, 7672 (2012)
    Almora, Aranda, Mas-Marza, Garcia-Belmonte, Appl. Phys. Lett. 109, 173903 (2016)
    Ravishankar, Unold, Kirchartz, Science 371, eabd8014 (2021)
    Ravishankar, Bisquert, Kirchartz, Chem. Sci. 13, 4828 (2022), eq. 9
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

EPS0 = 8.8541878128e-12
Q = 1.602176634e-19
KB = 1.380649e-23
C_UNITS = {"F": 1.0, "mF": 1e-3, "uF": 1e-6, "nF": 1e-9, "pF": 1e-12}
R2_STEPS = (0.999, 0.995, 0.99, 0.98, 0.95)

COLUMN_SPEC = [
    ("v", [r"volt", r"bias", r"^v\b", r"v_?dc"], 0),
    ("c", [r"cap", r"^c\b", r"^cp\b", r"^cs\b", r"c\s*\("], 1),
]


def window_fits(x, y, min_pts: int) -> Dict[str, np.ndarray]:
    """Least-squares line of every window of at least min_pts consecutive
    points, from cumulative sums. x and y are centred and scaled first."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    x0, xs = x.mean(), np.ptp(x) or 1.0
    y0, ys = y.mean(), np.ptp(y) or 1.0
    u, v = (x - x0) / xs, (y - y0) / ys
    cs = lambda a: np.r_[0.0, np.cumsum(a)]
    su, sv, suu, suv, svv = cs(u), cs(v), cs(u * u), cs(u * v), cs(v * v)
    i, j = np.triu_indices(len(x) + 1, k=min_pts)
    m = (j - i).astype(float)
    a, b = su[j] - su[i], sv[j] - sv[i]
    cuu = suu[j] - suu[i] - a * a / m
    cuv = suv[j] - suv[i] - a * b / m
    cvv = svv[j] - svv[i] - b * b / m
    with np.errstate(divide="ignore", invalid="ignore"):
        slope_n = cuv / cuu
        r2 = np.where(cvv > 0, cuv * cuv / (cuu * cvv), 0.0)
        se_n = np.sqrt(np.clip((cvv - slope_n * cuv) / np.maximum(m - 2, 1), 0, None) / cuu)
    slope = slope_n * ys / xs
    icpt = y0 + ys * (b / m - slope_n * a / m) - slope * x0
    return {"i": i, "j": j, "slope": slope, "intercept": icpt, "r2": r2, "slope_err": se_n * ys / xs,
            "span": x[j - 1] - x[i]}


def find_linear_window(v, y, min_pts: int = 5, min_span_fraction: float = 0.15) -> Optional[Dict[str, float]]:
    """Widest window with negative slope whose R2 passes the strictest
    threshold that any sufficiently wide window reaches."""
    w = window_fits(v, y, min_pts)
    total = float(np.ptp(v))
    base = (w["slope"] < 0) & np.isfinite(w["r2"]) & (w["span"] >= min_span_fraction * total)
    for thr in R2_STEPS:
        ok = base & (w["r2"] >= thr)
        if ok.any():
            idx = np.where(ok)[0]
            k = idx[np.lexsort((-w["r2"][idx], -w["span"][idx]))[0]]
            return {"i0": int(w["i"][k]), "i1": int(w["j"][k]), "slope": float(w["slope"][k]),
                    "intercept": float(w["intercept"][k]), "r2": float(w["r2"][k]),
                    "slope_err": float(w["slope_err"][k]), "threshold": thr}
    return None


def resolution_limit_cm3(thickness_nm: float, eps_r: float, temperature_k: float = 300.0, m: float = 2.0) -> float:
    """Smallest density a C-V measurement on a layer of this thickness can
    distinguish from the response of an undoped layer."""
    d = thickness_nm * 1e-9
    return float(27.0 * m * KB * temperature_k * EPS0 * eps_r / (4.0 * Q * Q * d * d) * 1e-6)


def analyse(v, c, area_cm2: float, eps_r: float, c_unit: str = "F", thickness_nm: float = 0.0,
            temperature_k: float = 300.0, m: float = 2.0, v_min: Optional[float] = None,
            v_max: Optional[float] = None) -> Dict[str, Any]:
    """Mott-Schottky analysis. C in `c_unit`, area in cm2."""
    v, c = np.asarray(v, float), np.asarray(c, float) * C_UNITS.get(c_unit, 1.0)
    ok = np.isfinite(v) & np.isfinite(c) & (c > 0)
    v, c = v[ok], c[ok]
    order = np.argsort(v, kind="stable")
    v, c = v[order], c[order]
    if len(v) > 1:                                    # average repeated voltages (up and down sweeps)
        vu, inv = np.unique(v, return_inverse=True)
        c = np.bincount(inv, weights=c) / np.bincount(inv)
        v = vu
    if len(v) < 8:
        raise ValueError("C-V analysis needs at least 8 points with positive capacitance")
    if area_cm2 <= 0 or eps_r <= 0:
        raise ValueError("area and relative permittivity must be positive")
    a_m2, eps = area_cm2 * 1e-4, EPS0 * eps_r
    vt = KB * temperature_k / Q
    y = 1.0 / c ** 2
    polarity = 1
    if np.corrcoef(v, y)[0, 1] > 0:                   # forward bias is negative in this file
        polarity = -1
        v, c, y = -v[::-1], c[::-1], y[::-1]
    sel = np.ones(len(v), bool)
    if v_min is not None:
        sel &= v >= v_min
    if v_max is not None:
        sel &= v <= v_max
    idx = np.where(sel)[0]
    manual = v_min is not None or v_max is not None
    win = None
    if len(idx) >= 5:
        if manual:
            from scripts.common.curve_io import linfit
            f = linfit(v[idx], y[idx])
            win = {"i0": int(idx[0]), "i1": int(idx[-1]) + 1, "slope": f["slope"], "intercept": f["intercept"],
                   "r2": f["r2"], "slope_err": f["slope_err"], "threshold": np.nan}
        else:
            win = find_linear_window(v, y, min_pts=max(5, len(v) // 8))
    w_nm = eps * a_m2 / c * 1e9
    dy = np.gradient(y, v)
    with np.errstate(divide="ignore", invalid="ignore"):
        n_prof = np.where(dy < 0, -2.0 / (Q * eps * a_m2 ** 2 * dy) * 1e-6, np.nan)
    res: Dict[str, Any] = {"v": v, "c": c, "inv_c2": y, "w_nm": w_nm, "n_profile_cm3": n_prof, "polarity": polarity,
                           "window": win, "manual_window": manual, "area_cm2": float(area_cm2), "eps_r": float(eps_r),
                           "thickness_nm": float(thickness_nm), "temperature_K": float(temperature_k), "m": float(m),
                           "N_cm3": np.nan, "N_err_cm3": np.nan, "V_bi": np.nan, "V_intercept": np.nan,
                           "W0_nm": float(np.interp(0.0, v, w_nm)) if v.min() <= 0 <= v.max() else np.nan,
                           "C_geo_F": np.nan, "N_min_cm3": np.nan, "debye_nm": np.nan, "W_window_nm": (np.nan, np.nan),
                           "C_min_over_C_geo": np.nan}
    if thickness_nm > 0:
        res["C_geo_F"] = float(eps * a_m2 / (thickness_nm * 1e-9))
        res["N_min_cm3"] = resolution_limit_cm3(thickness_nm, eps_r, temperature_k, m)
        res["C_min_over_C_geo"] = float(c.min() / res["C_geo_F"])
    if win is not None and win["slope"] < 0:
        n_m3 = 2.0 / (Q * eps * a_m2 ** 2 * abs(win["slope"]))
        res["N_cm3"] = float(n_m3 * 1e-6)
        res["N_err_cm3"] = float(res["N_cm3"] * win["slope_err"] / abs(win["slope"])) if np.isfinite(win["slope_err"]) else np.nan
        res["V_intercept"] = float(-win["intercept"] / win["slope"])
        res["V_bi"] = res["V_intercept"] + vt
        res["debye_nm"] = float(np.sqrt(eps * KB * temperature_k / (Q * Q * n_m3)) * 1e9)
        ww = w_nm[win["i0"]:win["i1"]]
        res["W_window_nm"] = (float(ww.min()), float(ww.max()))
    res["warnings"] = checks(res)
    return res


def checks(r: Dict[str, Any]) -> List[str]:
    w: List[str] = []
    win = r["window"]
    if win is None or not np.isfinite(r["N_cm3"]):
        return ["No straight section with a negative slope was found in 1/C2: the capacitance does not follow "
                "Mott-Schottky behaviour in this voltage range."]
    d = r["thickness_nm"]
    if r["N_cm3"] > 1e20 or r["N_cm3"] < 1e10 or r["W_window_nm"][1] < 1.0:
        w.append(f"N = {r['N_cm3']:.1e} cm-3 with a depletion width of {r['W_window_nm'][1]:.2g} nm is not a physical "
                 "depletion layer. Check the capacitance unit and the area; a capacitance that grows exponentially "
                 "with forward bias is injected (chemical) charge, not a depletion capacitance.")
    if d > 0 and np.isfinite(r["N_min_cm3"]):
        if r["N_cm3"] < 3.0 * r["N_min_cm3"]:
            w.append(f"The apparent density {r['N_cm3']:.2e} cm-3 is not clearly above the resolution limit "
                     f"{r['N_min_cm3']:.2e} cm-3 of a {d:.0f} nm layer (Ravishankar 2021): geometric capacitance "
                     "plus injected charge gives the same straight line, so this is not evidence of doping.")
        if r["W_window_nm"][1] > 0.9 * d:
            w.append(f"The depletion width in the fitted window ({r['W_window_nm'][0]:.0f}-{r['W_window_nm'][1]:.0f} nm) "
                     f"reaches the layer thickness ({d:.0f} nm): the layer is fully depleted there and the "
                     "capacitance is geometric.")
    else:
        w.append("No absorber thickness was entered, so the density could not be compared with the resolution "
                 "limit of the layer. Enter the thickness before interpreting the value as doping.")
    if win["r2"] < 0.99:
        w.append(f"The straight section has R2 = {win['r2']:.3f}; the density changes with depth or the "
                 "capacitance has a second contribution.")
    span = r["v"][win["i1"] - 1] - r["v"][win["i0"]]
    if span < 0.2:
        w.append(f"The straight section covers only {span:.2f} V.")
    if np.isfinite(r["V_bi"]) and not 0.3 <= r["V_bi"] <= 1.6:
        w.append(f"V_bi = {r['V_bi']:.2f} V is outside the range a thin-film cell can have (0.3-1.6 V): the "
                 "intercept is set by something other than the built-in potential.")
    if r["polarity"] < 0:
        w.append("1/C2 rises with the voltage as stored, so the voltage axis was reversed (forward bias positive).")
    return w


def summary_rows(r: Dict[str, Any]) -> List[Tuple[str, Any, str]]:
    win = r["window"] or {}
    v0 = r["v"][win["i0"]] if win else np.nan
    v1 = r["v"][win["i1"] - 1] if win else np.nan
    return [
        ("Apparent doping density N", r["N_cm3"], "cm-3"), ("N std. error", r["N_err_cm3"], "cm-3"),
        ("Built-in potential V_bi", r["V_bi"], "V"), ("Voltage intercept", r["V_intercept"], "V"),
        ("Fit window", f"{v0:.3g} to {v1:.3g}" if win else "", "V"), ("Fit window R2", win.get("r2", np.nan), ""),
        ("Window chosen", "manually" if r["manual_window"] else "automatically", ""),
        ("Depletion width at 0 V", r["W0_nm"], "nm"),
        ("Depletion width in window (min)", r["W_window_nm"][0], "nm"),
        ("Depletion width in window (max)", r["W_window_nm"][1], "nm"),
        ("Debye length", r["debye_nm"], "nm"), ("Geometric capacitance", r["C_geo_F"], "F"),
        ("Lowest C / geometric C", r["C_min_over_C_geo"], ""),
        ("Resolution limit N_min", r["N_min_cm3"], "cm-3"),
        ("N / N_min", r["N_cm3"] / r["N_min_cm3"] if np.isfinite(r["N_min_cm3"]) else np.nan, ""),
    ]


def simulate(n_cm3: float = 1e17, v_bi: float = 0.9, eps_r: float = 25.0, area_cm2: float = 0.1,
             thickness_nm: float = 0.0, v=None, temperature_k: float = 300.0, c_inj0: float = 0.0, m: float = 2.0,
             noise: float = 0.0, seed: int = 0) -> Tuple[np.ndarray, np.ndarray]:
    """C(V) in farads of a one-sided junction, clamped at the geometric
    capacitance of a layer of the given thickness, plus an optional
    injection term c_inj0 exp(qV / m kT)."""
    v = np.asarray(v if v is not None else np.linspace(-0.6, 0.7, 53), float)
    a, eps, vt = area_cm2 * 1e-4, EPS0 * eps_r, KB * temperature_k / Q
    c = a * np.sqrt(Q * eps * n_cm3 * 1e6 / (2.0 * np.clip(v_bi - v - vt, 1e-3, None)))
    if thickness_nm > 0:
        c = np.maximum(c, eps * a / (thickness_nm * 1e-9))
    c = c + c_inj0 * np.exp(v / (m * vt))
    if noise:
        c = c * (1.0 + noise * np.random.default_rng(seed).standard_normal(len(v)))
    return v, c
