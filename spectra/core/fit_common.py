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
    for i, (c, h, fwhm) in enumerate(init_peaks):
        fwhm = max(float(fwhm), 1e-6)
        sigma = max(fwhm / 2.3548, 1e-6)
        gamma = max(fwhm / 2.0, 1e-6)
        amp = float(max(h, 1e-6) * fwhm)

        params[f"p{i}_center"].set(value=float(c), min=x0, max=x1)
        params[f"p{i}_sigma"].set(value=float(sigma), min=1e-6, max=span)
        params[f"p{i}_gamma"].set(value=float(gamma), min=1e-6, max=span)
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
