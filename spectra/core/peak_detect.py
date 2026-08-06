import numpy as np
import pandas as pd
from typing import List, Tuple
from scipy.signal import find_peaks, peak_widths
from spectra.core.utils import robust_noise_sigma, auto_distance_pts
from spectra.core.config import PipelineConfig

def find_candidates(x: np.ndarray, y_corr: np.ndarray, cfg: PipelineConfig):
    y = y_corr.copy()
    y = y - np.nanmin(y)

    dist = auto_distance_pts(x, cfg.min_peak_separation_x) if cfg.min_peak_separation_x > 0 else 6
    noise_sigma = robust_noise_sigma(y_corr)
    prom_abs = float(cfg.noise_k * noise_sigma) if cfg.use_noise_based_prominence else float(0.02 * np.nanmax(y))

    idx, props = find_peaks(y, prominence=prom_abs, distance=dist)
    if len(idx) == 0:
        return pd.DataFrame(columns=["idx","x","height","prominence","fwhm_x"]), noise_sigma, prom_abs, dist

    widths = peak_widths(y, idx, rel_height=0.5)[0]
    dx = float(np.median(np.diff(x))) if len(x) > 1 else 1.0
    fwhm_x = widths * dx

    df = pd.DataFrame({
        "idx": idx,
        "x": x[idx],
        "height": y_corr[idx],
        "prominence": props.get("prominences", np.full(len(idx), np.nan)),
        "fwhm_x": fwhm_x,
    }).sort_values("prominence", ascending=False).head(cfg.max_candidates).reset_index(drop=True)

    return df, noise_sigma, prom_abs, dist

def detect_overlap_regions(cand: pd.DataFrame, cfg: PipelineConfig) -> List[Tuple[float,float]]:
    if cand.empty: return []
    xs = np.sort(cand["x"].to_numpy())
    regions: List[Tuple[float,float]] = []
    for i in range(len(xs)-1):
        if abs(xs[i+1]-xs[i]) <= cfg.overlap_merge_dx:
            mid = 0.5*(xs[i+1]+xs[i])
            regions.append((mid-cfg.region_half_width, mid+cfg.region_half_width))

    if not regions: return []
    regions.sort()
    merged = [regions[0]]
    for a,b in regions[1:]:
        la, lb = merged[-1]
        if a <= lb:
            merged[-1] = (la, max(lb,b))
        else:
            merged.append((a,b))
    return merged
