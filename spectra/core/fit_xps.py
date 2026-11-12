from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from lmfit.models import VoigtModel, ConstantModel

from spectra.core.fit_common import sigma_floor, voigt_fwhm, voigt_seed


def doublet_mains(cand: pd.DataFrame, split_ev: float, step: float, area_ratio: float = 0.75) -> pd.DataFrame:
    """Candidates that start a spin-orbit doublet.  A candidate ``split_ev``
    above a kept candidate (within half its FWHM, at least 3 grid steps) and no
    taller than twice the height the area ratio predicts (never less than the
    first line's height) is that line's partner and is dropped: the doublet fit
    puts a component there already.  Up to 3.5.2 every candidate was fitted as
    the first line of its own doublet, so a Pb 4f spectrum with a metallic
    shoulder (four candidates) came back as four doublets, two of them on the
    partner lines with an empty partner beyond.  The height allowance matters:
    the metallic 4f5/2 line sits between the two main lines, and on noisy data
    it can come out taller than its own 4f7/2 line."""
    if cand is None or cand.empty:
        return cand
    sel = cand.sort_values("x").reset_index(drop=True)
    xs = sel["x"].to_numpy(float)
    hs = sel["height"].to_numpy(float)
    ws = np.maximum(sel["fwhm_x"].to_numpy(float), 1e-6)
    keep = np.ones(len(sel), bool)
    h_lim = max(1.0, 2.0 * float(area_ratio))
    for j in range(len(sel)):
        for i in range(j):
            if keep[i] and hs[j] <= h_lim * hs[i] and abs(xs[j] - xs[i] - split_ev) <= max(0.5 * ws[i], 3.0 * step):
                keep[j] = False
                break
    return sel[keep].reset_index(drop=True)


def fit_xps_doublet_cluster(
    x: np.ndarray,
    y_corr: np.ndarray,
    region: Tuple[float, float],
    mains: List[Tuple[float, float, float]],
    split_ev: float,
    area_ratio: float,
    lock_widths: bool = True,
) -> Optional[Tuple[pd.DataFrame, float, float]]:
    """Spin-orbit doublets fitted together in one window: for each (centre,
    height, FWHM) in ``mains`` a Voigt and its partner at centre + split_ev
    with area_ratio times its area (widths shared when ``lock_widths``), plus
    one constant.  Components are bounded as in fit_common.fit_voigts: centre
    within +-max(FWHM, 3 steps) of the seed, Gaussian and Lorentzian FWHM each
    below 3x the seed FWHM."""
    x0, x1 = region
    m = (x >= x0) & (x <= x1)
    # per doublet 4 free parameters (6 with free partner widths) + constant; the
    # old fixed threshold of 80 rejected real XPS region scans (0.2 eV step)
    if not mains or m.sum() < max(20, 6 * len(mains) + 5):
        return None
    xr = x[m]
    yr = y_corr[m]
    span = x1 - x0
    step = float(np.median(np.abs(np.diff(xr)))) if len(xr) > 1 else 0.0

    model = ConstantModel(prefix="b_")
    for k in range(2 * len(mains)):
        model = model + VoigtModel(prefix=f"p{k}_")
    params = model.make_params()
    params["b_c"].set(value=float(np.median(yr)))

    for d, (c, h, fwhm) in enumerate(mains):
        a, b = f"p{2 * d}_", f"p{2 * d + 1}_"
        fwhm = max(float(fwhm), 1e-6)
        sigma0, gamma0 = voigt_seed(fwhm)        # start at the seed FWHM (3.5.2)
        reach = max(fwhm, 3.0 * step)
        s_max, g_max = min(span, 3.0 * fwhm) / 2.3548, min(span, 3.0 * fwhm) / 2.0
        params[a + "center"].set(value=float(c), min=max(x0, float(c) - reach), max=min(x1, float(c) + reach))
        s_min = sigma_floor(fwhm, step)          # Gaussian FWHM >= min(2 steps, seed/2) (3.5.3)
        params[a + "sigma"].set(value=max(float(sigma0), s_min), min=s_min, max=s_max)
        # vary=True: VoigtModel starts with gamma tied to sigma (vary=False) and
        # set(value=...) does not free it (see fit_common.fit_voigts; fixed in 3.5.2)
        params[a + "gamma"].set(value=float(gamma0), min=1e-6, max=g_max, vary=True)
        params[a + "amplitude"].set(value=float(max(h, 1e-6) * fwhm), min=0.0)
        params[b + "center"].expr = f"{a}center + {float(split_ev)!r}"
        params[b + "amplitude"].expr = f"{float(area_ratio)!r} * {a}amplitude"
        if lock_widths:
            params[b + "sigma"].expr = f"{a}sigma"
            params[b + "gamma"].expr = f"{a}gamma"
        else:
            params[b + "sigma"].set(value=max(float(sigma0), s_min), min=s_min, max=s_max)
            params[b + "gamma"].set(value=float(gamma0), min=1e-6, max=g_max, vary=True)

    try:
        res = model.fit(yr, params, x=xr)
    except Exception:
        return None

    rows = []
    for k in range(2 * len(mains)):
        p = f"p{k}_"
        center = res.params[p + "center"].value
        sigma = res.params[p + "sigma"].value
        gamma = res.params[p + "gamma"].value
        comp = res.eval_components(x=np.array([center]))
        rows.append({
            "region_xmin": x0,
            "region_xmax": x1,
            "peak_index": k,
            "center": center,
            "height": float(comp.get(p, np.array([np.nan]))[0]),
            "fwhm": voigt_fwhm(sigma, gamma),
            "area_amplitude": res.params[p + "amplitude"].value,
            "sigma": sigma,
            "gamma": gamma,
            "redchi": res.redchi,
            "aic": res.aic,
            "bic": res.bic,
            "npeaks": 2 * len(mains),
            "xps_doublet": True,
            "xps_split_ev": float(split_ev),
            "xps_area_ratio": float(area_ratio),
            "xps_index": k % 2,
            "doublet_id": k // 2,
        })
    return pd.DataFrame(rows), float(res.aic), float(res.bic)


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
    """One spin-orbit doublet (see fit_xps_doublet_cluster)."""
    return fit_xps_doublet_cluster(x, y_corr, region, [(float(init_center), float(init_height), float(init_fwhm))],
                                   split_ev, area_ratio, lock_widths)
