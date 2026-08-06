from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd
from lmfit.models import VoigtModel, ConstantModel

from spectra.core.fit_common import voigt_fwhm


def fit_xps_doublet_voigts(
    x: np.ndarray,
    y_corr: np.ndarray,
    region: Tuple[float, float],
    init_center: float,
    init_height: float,
    init_fwhm: float,
    split_ev: float,
    area_ratio: float,
    lock_widths: bool = True,
) -> Optional[Tuple[pd.DataFrame, float, float]]:
    x0, x1 = region
    m = (x >= x0) & (x <= x1)
    # 2 Voigts + constant = 9 free params; old fixed threshold of 80 rejected
    # real XPS region scans (0.2 eV step) outright
    if m.sum() < 20:
        return None

    xr = x[m]
    yr = y_corr[m]

    model = ConstantModel(prefix="b_") + VoigtModel(prefix="p0_") + VoigtModel(prefix="p1_")
    params = model.make_params()
    params["b_c"].set(value=float(np.median(yr)))

    fwhm = max(float(init_fwhm), 1e-6)
    sigma0 = max(fwhm / 2.3548, 1e-6)
    gamma0 = max(fwhm / 2.0, 1e-6)
    amp0 = float(max(init_height, 1e-6) * fwhm)

    params["p0_center"].set(value=float(init_center), min=x0, max=x1)
    params["p0_sigma"].set(value=float(sigma0), min=1e-6, max=(x1 - x0))
    params["p0_gamma"].set(value=float(gamma0), min=1e-6, max=(x1 - x0))
    params["p0_amplitude"].set(value=float(amp0), min=0.0)

    params["p1_center"].expr = "p0_center + " + str(float(split_ev))
    params["p1_amplitude"].expr = str(float(area_ratio)) + " * p0_amplitude"

    if lock_widths:
        params["p1_sigma"].expr = "p0_sigma"
        params["p1_gamma"].expr = "p0_gamma"
    else:
        params["p1_sigma"].set(value=float(sigma0), min=1e-6, max=(x1 - x0))
        params["p1_gamma"].set(value=float(gamma0), min=1e-6, max=(x1 - x0))

    try:
        res = model.fit(yr, params, x=xr)
    except Exception:
        return None

    rows = []
    for i in [0, 1]:
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
            "npeaks": 2,
            "xps_doublet": True,
            "xps_split_ev": float(split_ev),
            "xps_area_ratio": float(area_ratio),
            "xps_index": i,
        })

    return pd.DataFrame(rows), float(res.aic), float(res.bic)
