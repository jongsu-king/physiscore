"""UV-Vis absorbance physics (GUI-free): Tauc transform, automatic selection
of the linear absorption-edge region, Urbach tail and derivative band gap.

The Tauc relation (alpha h nu)^(1/r) = B (h nu - Eg) holds just above the
edge: r = 1/2 for allowed direct and r = 2 for allowed indirect transitions.
A and alpha = 2.303 A / d differ by a constant, so Eg (the x-intercept) does
not depend on whether absorbance or absorption coefficient is used; only the
y-axis scale does.

References
----------
- Tauc, Grigorovici & Vancu, Phys. Status Solidi 15, 627 (1966).
- Makula, Pacia & Macyk, J. Phys. Chem. Lett. 9, 6814 (2018): guidance on
  choosing the linear region and on the Urbach tail.
- Urbach, Phys. Rev. 92, 1324 (1953).
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np

HC_EV_NM = 1239.84198
LN10 = 2.302585092994046

TAUC_EXPONENT = {"direct": 2.0, "indirect": 0.5,
                 "direct_forbidden": 2.0 / 3.0, "indirect_forbidden": 1.0 / 3.0}


def absorbance_to_alpha_cm(absorbance, thickness_nm: float) -> np.ndarray:
    """alpha [cm^-1] = ln(10) A / d."""
    d_cm = float(thickness_nm) * 1e-7
    if d_cm <= 0:
        raise ValueError("thickness must be positive")
    return LN10 * np.asarray(absorbance, dtype=float) / d_cm


def tauc_transform(wavelength_nm, absorbance, mode: str = "direct",
                   thickness_nm: Optional[float] = None) -> Tuple[np.ndarray, np.ndarray, str]:
    """(h nu [eV] ascending, (X h nu)^n, y-axis label) with X = A or alpha."""
    if mode not in TAUC_EXPONENT:
        raise ValueError(f"mode must be one of {tuple(TAUC_EXPONENT)}")
    wl = np.asarray(wavelength_nm, dtype=float)
    a = np.asarray(absorbance, dtype=float)
    ok = np.isfinite(wl) & np.isfinite(a) & (wl > 0)
    wl, a = wl[ok], a[ok]
    hv = HC_EV_NM / wl
    if thickness_nm:
        x = absorbance_to_alpha_cm(a, thickness_nm)
        sym = r"\alpha"
    else:
        x, sym = a, "A"
    n = TAUC_EXPONENT[mode]
    y = np.power(np.clip(x * hv, 0, None), n)
    exp_txt = {2.0: "2", 0.5: "1/2", 2.0 / 3.0: "2/3", 1.0 / 3.0: "1/3"}[n]
    label = r"$(%s\,h\nu)^{%s}$" % (sym, exp_txt)
    order = np.argsort(hv)
    return hv[order], y[order], label


def linear_fit(hv, y, lo: float, hi: float) -> Dict[str, float]:
    """Straight line through the Tauc curve in [lo, hi]: Eg = -b/m, with R^2
    and the standard error of Eg propagated from the fit covariance."""
    hv = np.asarray(hv, dtype=float)
    y = np.asarray(y, dtype=float)
    m = np.isfinite(hv) & np.isfinite(y) & (hv >= min(lo, hi)) & (hv <= max(lo, hi))
    out = {"Eg": float("nan"), "slope": float("nan"), "intercept": float("nan"),
           "R2": float("nan"), "Eg_err": float("nan"), "n_points": int(np.sum(m))}
    if out["n_points"] < 3:
        return out
    x, yy = hv[m], y[m]
    (slope, intercept), cov = np.polyfit(x, yy, 1, cov=True) if len(x) > 3 else (np.polyfit(x, yy, 1), None)
    if slope == 0:
        return out
    eg = -intercept / slope
    yhat = slope * x + intercept
    ss_tot = float(np.sum((yy - yy.mean()) ** 2))
    r2 = 1.0 - float(np.sum((yy - yhat) ** 2)) / ss_tot if ss_tot > 0 else float("nan")
    eg_err = float("nan")
    if cov is not None:
        # Eg = -b/m : var = (b/m^2)^2 var_m + (1/m)^2 var_b - 2 (b/m^3) cov_mb
        vm, vb, cmb = cov[0, 0], cov[1, 1], cov[0, 1]
        var = (intercept / slope ** 2) ** 2 * vm + (1.0 / slope) ** 2 * vb - 2.0 * intercept / slope ** 3 * cmb
        eg_err = float(np.sqrt(var)) if var > 0 else float("nan")
    out.update(Eg=float(eg), slope=float(slope), intercept=float(intercept), R2=r2, Eg_err=eg_err)
    return out


def auto_linear_region(hv, y, expected_eg: Optional[float] = None, window_points: int = 7,
                       slope_fraction: float = 0.6, min_r2: float = 0.98,
                       search_half_width: float = 0.6) -> Dict[str, float]:
    """Find the linear absorption-edge region of a Tauc curve automatically.

    1. the local slope and local R^2 are computed by moving-window
       regression (window = max(window_points, 4% of the points), so the
       estimate is stable on noisy data);
    2. the steepest positive, locally linear (R^2 >= 0.8) point above the
       onset is taken as the anchor (restricted to +-search_half_width eV
       around `expected_eg` when given);
    3. the region grows outward while the local slope stays above
       `slope_fraction` of the anchor slope;
    4. the ends are trimmed until the straight-line R^2 of the region
       reaches `min_r2` (never below the anchor window itself).

    Returns the region bounds and the linear_fit result for it. The
    procedure is the one most Tauc-plot papers describe in words ("the
    linear part of the edge was extrapolated"), made explicit and
    reproducible.
    """
    hv = np.asarray(hv, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(hv) & np.isfinite(y)
    hv, y = hv[ok], y[ok]
    order = np.argsort(hv)
    hv, y = hv[order], y[order]
    out = {"lo": float("nan"), "hi": float("nan"), "Eg": float("nan"), "R2": float("nan"),
           "slope": float("nan"), "intercept": float("nan"), "Eg_err": float("nan"), "n_points": 0}
    n = len(hv)
    k = max(int(window_points), 3, int(round(0.04 * n)))
    if k % 2 == 0:
        k += 1
    if n < k + 2:
        return out
    slopes = np.full(n, np.nan)
    local_r2 = np.full(n, np.nan)
    for i in range(n - k + 1):
        xs, ys = hv[i:i + k], y[i:i + k]
        if np.ptp(xs) <= 0:
            continue
        m, b = np.polyfit(xs, ys, 1)
        ss_tot = float(np.sum((ys - ys.mean()) ** 2))
        slopes[i + k // 2] = m
        local_r2[i + k // 2] = 1.0 - float(np.sum((ys - (m * xs + b)) ** 2)) / ss_tot if ss_tot > 0 else 0.0
    cand = np.isfinite(slopes) & (slopes > 0) & (local_r2 >= 0.8)
    if expected_eg is not None and np.isfinite(expected_eg):
        cand &= (hv >= expected_eg - search_half_width) & (hv <= expected_eg + search_half_width)
    else:
        # the edge sits above the onset: ignore the lowest-energy 10% where the
        # Tauc curve is just the sub-gap tail
        cand &= hv >= hv.min() + 0.1 * (hv.max() - hv.min())
    if not np.any(cand):
        return out
    i_max = int(np.argmax(np.where(cand, slopes, -np.inf)))
    s_max = slopes[i_max]
    thr = slope_fraction * s_max

    lo_i = hi_i = i_max
    while lo_i > 0 and np.isfinite(slopes[lo_i - 1]) and slopes[lo_i - 1] >= thr:
        lo_i -= 1
    while hi_i < n - 1 and np.isfinite(slopes[hi_i + 1]) and slopes[hi_i + 1] >= thr:
        hi_i += 1
    # include the half-window the slope estimate already spanned
    lo_i = max(lo_i - k // 2, 0)
    hi_i = min(hi_i + k // 2, n - 1)
    a_lo, a_hi = max(i_max - k // 2, 0), min(i_max + k // 2, n - 1)   # never trim inside the anchor window

    def fit_of(a, b):
        return linear_fit(hv, y, hv[a], hv[b])

    fit = fit_of(lo_i, hi_i)
    while (not np.isfinite(fit["R2"]) or fit["R2"] < min_r2) and (lo_i < a_lo or hi_i > a_hi):
        # drop the end whose removal helps the straight line more
        cand_fits = []
        if lo_i < a_lo:
            cand_fits.append((fit_of(lo_i + 1, hi_i)["R2"], lo_i + 1, hi_i))
        if hi_i > a_hi:
            cand_fits.append((fit_of(lo_i, hi_i - 1)["R2"], lo_i, hi_i - 1))
        _, lo_i, hi_i = max(cand_fits, key=lambda t: (t[0] if np.isfinite(t[0]) else -1.0))
        fit = fit_of(lo_i, hi_i)
    out.update(lo=float(hv[lo_i]), hi=float(hv[hi_i]),
               **{k2: fit[k2] for k2 in ("Eg", "R2", "slope", "intercept", "Eg_err", "n_points")})
    return out


def urbach_from_absorbance(wavelength_nm, absorbance, e_lo: float, e_hi: float) -> Dict[str, float]:
    """Urbach energy from ln(A) vs h nu (A is proportional to alpha, so the
    slope is unchanged): Eu [meV] = 1000 / slope."""
    wl = np.asarray(wavelength_nm, dtype=float)
    a = np.asarray(absorbance, dtype=float)
    hv = HC_EV_NM / wl
    m = np.isfinite(hv) & np.isfinite(a) & (a > 0) & (hv >= min(e_lo, e_hi)) & (hv <= max(e_lo, e_hi))
    out = {"Eu_meV": float("nan"), "slope": float("nan"), "intercept": float("nan"), "R2": float("nan"), "n_points": int(np.sum(m))}
    if out["n_points"] < 3:
        return out
    x, y = hv[m], np.log(a[m])
    slope, intercept = np.polyfit(x, y, 1)
    if slope <= 0:
        return out
    yhat = slope * x + intercept
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    out.update(Eu_meV=1000.0 / float(slope), slope=float(slope), intercept=float(intercept),
               R2=1.0 - float(np.sum((y - yhat) ** 2)) / ss_tot if ss_tot > 0 else float("nan"))
    return out


def derivative_bandgap(wavelength_nm, absorbance, smooth_window: int = 7) -> float:
    """Energy of the steepest rise of absorbance, dA/dE maximum (after a
    light Savitzky-Golay smoothing). A model-free cross-check of the Tauc
    intercept; for a sharp direct edge the two agree to within the edge
    broadening."""
    from scipy.signal import savgol_filter
    wl = np.asarray(wavelength_nm, dtype=float)
    a = np.asarray(absorbance, dtype=float)
    ok = np.isfinite(wl) & np.isfinite(a) & (wl > 0)
    hv = HC_EV_NM / wl[ok]
    a = a[ok]
    order = np.argsort(hv)
    hv, a = hv[order], a[order]
    if len(hv) < 7:
        return float("nan")
    w = int(smooth_window) | 1
    w = min(w, len(hv) - (1 - len(hv) % 2))
    if w >= 5:
        a = savgol_filter(a, w, 2)
    da = np.gradient(a, hv)
    # the absorption edge: steepest rise on the low-energy side of the maximum absorbance
    i_peak = int(np.argmax(a))
    cand = np.where(np.arange(len(hv)) <= i_peak, da, -np.inf)
    return float(hv[int(np.argmax(cand))])


def analyze_absorbance(wavelength_nm, absorbance, mode: str = "direct",
                       thickness_nm: Optional[float] = None,
                       expected_eg: Optional[float] = None) -> Dict[str, float]:
    """Tauc Eg with its automatically selected region, derivative Eg and the
    Urbach energy of the tail just below the Tauc region."""
    hv, y, label = tauc_transform(wavelength_nm, absorbance, mode, thickness_nm)
    reg = auto_linear_region(hv, y, expected_eg=expected_eg)
    out = {"mode": mode, "Eg_Tauc_eV": reg["Eg"], "Eg_err_eV": reg["Eg_err"], "Tauc_R2": reg["R2"],
           "Tauc_lo_eV": reg["lo"], "Tauc_hi_eV": reg["hi"], "Tauc_slope": reg["slope"],
           "Tauc_intercept": reg["intercept"], "Eg_derivative_eV": derivative_bandgap(wavelength_nm, absorbance),
           "y_label": label}
    if np.isfinite(reg["Eg"]):
        urb = urbach_from_absorbance(wavelength_nm, absorbance, reg["Eg"] - 0.25, reg["Eg"] - 0.02)
        out.update({"Eu_meV": urb["Eu_meV"], "Eu_R2": urb["R2"]})
    else:
        out.update({"Eu_meV": float("nan"), "Eu_R2": float("nan")})
    return out
