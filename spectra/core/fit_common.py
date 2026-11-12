from __future__ import annotations

import math
from typing import List, Tuple, Optional

import numpy as np
import pandas as pd
from lmfit.models import VoigtModel, ConstantModel

from spectra.core.utils import quality_from_snr


def lorentzian(x: np.ndarray, height: float, center: float, fwhm: float) -> np.ndarray:
    """
    Lorentzian peak function for area integration.
    L(x) = height / (1 + 4*(x-center)^2 / fwhm^2)
    """
    gamma = fwhm / 2.0
    return height * (gamma**2) / ((x - center)**2 + gamma**2)


def voigt_fwhm(sigma: float, gamma: float) -> float:
    return 0.5346 * (2 * gamma) + math.sqrt(0.2166 * (2 * gamma) ** 2 + (2.3548 * sigma) ** 2)


# Olivero-Longbothum with f_G = f_L = f: f_V = (0.5346 + sqrt(0.2166 + 1)) f
_EQUAL_SPLIT = 0.5346 + math.sqrt(1.2166)


def voigt_seed(fwhm: float) -> Tuple[float, float]:
    """Starting sigma and gamma for a Voigt whose FWHM equals ``fwhm``, with
    equal Gaussian and Lorentzian widths.  Seeding sigma = fwhm/2.3548 and
    gamma = fwhm/2 together (as up to 3.5.1) starts the profile 1.64x too wide;
    once gamma is free that start can end in a local minimum with sigma at its
    lower bound (pure Lorentzian, area +28 % on a synthetic Pb 4f cluster, chi2
    8.6x the minimum reached from any other start)."""
    f = max(float(fwhm), 1e-6) / _EQUAL_SPLIT
    return max(f / 2.3548, 1e-6), max(f / 2.0, 1e-6)


def sigma_floor(fwhm: float, step: float) -> float:
    """Lower bound of a Voigt's sigma: its Gaussian FWHM is at least
    min(2 grid steps, half the seed FWHM).  A line sampled by fewer points is
    not resolved; without the floor a component fitted to unsmoothed data can
    collapse onto a single noisy point."""
    return max(1e-6, min(2.0 * float(step), 0.5 * float(fwhm)) / 2.3548)


def build_composite(n: int):
    model = ConstantModel(prefix="b_")
    params = model.make_params(c_c=0.0)
    for i in range(n):
        vm = VoigtModel(prefix=f"p{i}_")
        model = model + vm
        params.update(vm.make_params())
    return model, params


def fit_voigts(
    x: np.ndarray,
    y_corr: np.ndarray,
    region: Tuple[float, float],
    init_peaks: List[Tuple[float, float, float]],
) -> Optional[Tuple[pd.DataFrame, float, float]]:
    x0, x1 = region
    m = (x >= x0) & (x <= x1)
    # need comfortably more points than free parameters (4 per Voigt + 1 const);
    # the old fixed threshold of 60 rejected real XPS region scans (0.2 eV step,
    # ~25 points per fit window) outright
    min_pts = max(15, 5 * len(init_peaks) + 5)
    if m.sum() < min_pts:
        return None
    xr = x[m]
    yr = y_corr[m]

    model, params = build_composite(len(init_peaks))
    params["b_c"].set(value=float(np.median(yr)))

    span = x1 - x0
    step = float(np.median(np.abs(np.diff(xr)))) if len(xr) > 1 else 0.0
    for i, (c, h, fwhm) in enumerate(init_peaks):
        fwhm = max(float(fwhm), 1e-6)
        sigma, gamma = voigt_seed(fwhm)
        amp = float(max(h, 1e-6) * fwhm)

        # Each component stays near the peak it was seeded from (+-1 FWHM, at
        # least 3 grid steps), and its Gaussian and Lorentzian FWHM each stay
        # below 3x the seed FWHM.  (Up to 3.5.1 the bound was sigma, gamma <
        # 3 FWHM, i.e. a Gaussian FWHM up to 7x; with gamma free, a noise
        # candidate then grew into a 4 eV wide component under the main line.)
        # With the centre free over the whole window, the component of a small
        # peak next to a large one migrated onto the large peak (seen on Pb 4f
        # with a metallic shoulder: two components on 4f5/2, none on the shoulder).
        reach = max(fwhm, 3.0 * step)
        params[f"p{i}_center"].set(value=float(c), min=max(x0, float(c) - reach), max=min(x1, float(c) + reach))
        # Gaussian FWHM at least min(2 grid steps, half the seed FWHM) (3.5.3):
        # fitted to unsmoothed data, a noise candidate's component otherwise
        # shrinks onto one high point (FWHM 0.007 deg, height 20x the noise)
        params[f"p{i}_sigma"].set(value=max(float(sigma), sigma_floor(fwhm, step)), min=sigma_floor(fwhm, step),
                                  max=min(span, 3.0 * fwhm) / 2.3548)
        # lmfit's VoigtModel ties gamma to sigma (expr, vary=False); set(value=...)
        # clears the expr but leaves vary=False, so gamma must be freed explicitly.
        # Up to 3.5.1 it was not: gamma stayed at FWHM/2, sigma went to ~0 and the
        # Lorentzian tails inflated the areas (+3 to +36 % on synthetic Pb 4f).
        params[f"p{i}_gamma"].set(value=float(gamma), min=1e-6, max=min(span, 3.0 * fwhm) / 2.0, vary=True)
        params[f"p{i}_amplitude"].set(value=float(amp), min=0.0)

    try:
        res = model.fit(yr, params, x=xr)
    except Exception:
        return None

    rows = []
    for i in range(len(init_peaks)):
        center = res.params[f"p{i}_center"].value
        sigma = res.params[f"p{i}_sigma"].value
        gamma = res.params[f"p{i}_gamma"].value
        amp = res.params[f"p{i}_amplitude"].value
        fwhm_out = voigt_fwhm(sigma, gamma)

        comp = res.eval_components(x=np.array([center]))
        height = float(comp.get(f"p{i}_", np.array([np.nan]))[0])

        rows.append({
            "region_xmin": x0,
            "region_xmax": x1,
            "peak_index": i,
            "center": center,
            "height": height,
            "fwhm": fwhm_out,
            "area_amplitude": amp,
            "sigma": sigma,
            "gamma": gamma,
            "redchi": res.redchi,
            "aic": res.aic,
            "bic": res.bic,
            "npeaks": len(init_peaks),
        })

    return pd.DataFrame(rows), float(res.aic), float(res.bic)


def fit_windows_to_midpoints(
    x: np.ndarray,
    y_corr: np.ndarray,
    cand: pd.DataFrame,
    fit_pad: float,
    neighbour_frac: float = 0.1,
) -> List[pd.DataFrame]:
    """One Voigt per candidate, in a window of centre +- fit_pad that stops at
    the midpoint to any neighbouring candidate at least ``neighbour_frac`` of
    this candidate's height (but never closer than 3 seed FWHM to the centre).

    Up to 3.5.1 the XRD auto-fit used the full +- fit_pad window (3.5 deg).  A
    neighbouring line inside it had no component and lifted the constant
    term: on a synthetic pattern with lines 3.5 deg apart, the areas of the
    two lines came out 18 and 35 % low on noise-free data once gamma was free
    (3.5.2); with midpoint windows the fit returns them to 0.2 %.  Giving the
    neighbours their own components instead was ten times slower (noise
    candidates are often most of a diffractogram's candidate list) and still
    missed a neighbour just outside the window."""
    tables: List[pd.DataFrame] = []
    if cand is None or cand.empty:
        return tables
    sel = cand.sort_values("x").reset_index(drop=True)
    xs = sel["x"].to_numpy(float)
    hs = sel["height"].to_numpy(float)
    ws = np.maximum(sel["fwhm_x"].to_numpy(float), 1e-6)
    for i in range(len(sel)):
        lo, hi = xs[i] - fit_pad, xs[i] + fit_pad
        for j in range(len(sel)):
            if j == i or hs[j] < neighbour_frac * hs[i]:
                continue
            mid = 0.5 * (xs[i] + xs[j])
            # never closer than 3 seed FWHM to the centre -- except towards a taller
            # neighbour (3.5.3): a weak candidate's seed FWHM from the smoothed curve
            # can be degrees wide, and its window then held the taller line with no
            # component for it (residual up to 190x the noise)
            keep = 0.0 if hs[j] > hs[i] else 3.0 * ws[i]
            if xs[j] < xs[i]:
                lo = max(lo, min(mid, xs[i] - keep))
            else:
                hi = min(hi, max(mid, xs[i] + keep))
        res = fit_voigts(x, y_corr, (float(lo), float(hi)), [(float(xs[i]), float(hs[i]), float(ws[i]))])
        if res is None or res[0] is None or res[0].empty:
            continue
        # A component that ends nearer another candidate than its own seed has
        # moved onto that candidate's line, which has its own fit (3.5.3).  Weak
        # candidates on the flank of a strong line (seed FWHM of several degrees
        # from the smoothed curve) otherwise repeated the strong line's row.
        c_fit = float(res[0]["center"].iloc[0])
        d = np.abs(xs - c_fit)
        d[i] = np.inf
        if d.min() < abs(c_fit - xs[i]):
            continue
        tables.append(res[0])
    return tables


def fit_pl_aic_select(
    x: np.ndarray,
    y_corr: np.ndarray,
    region: Tuple[float, float],
    seed_peaks: List[Tuple[float, float, float]],
    max_peaks: int = 3,
) -> Optional[pd.DataFrame]:
    best_df = None
    best_aic = float("inf")

    for k in range(1, max_peaks + 1):
        init = seed_peaks[:k]
        if len(init) < k:
            break
        res = fit_voigts(x, y_corr, region, init)
        if res is None:
            continue
        df, aic, _bic = res
        if df is None or df.empty:
            continue
        if aic < best_aic:
            best_aic = aic
            best_df = df

    return best_df


def label_pl_peaks(fitted: pd.DataFrame, fwhm_threshold: float) -> pd.DataFrame:
    if fitted is None or fitted.empty:
        return fitted
    out = fitted.copy()
    out["pl_component"] = np.where(
        out["fwhm"].astype(float) >= float(fwhm_threshold),
        "defect(broad)",
        "band-edge(narrow)"
    )
    return out


def add_qc_columns(fitted: pd.DataFrame, noise_sigma: float) -> pd.DataFrame:
    if fitted is None or fitted.empty:
        return fitted
    out = fitted.copy()
    ns = float(noise_sigma) if float(noise_sigma) > 0 else 1.0
    out["noise_sigma"] = ns
    out["snr"] = out["height"].astype(float) / ns
    out["quality"] = out["snr"].apply(lambda v: quality_from_snr(float(v)))
    return out
