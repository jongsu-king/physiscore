import os, json
import numpy as np
import pandas as pd
from spectra.core.config import PipelineConfig
from spectra.core.baseline import smooth_signal, baseline_asls
from spectra.core.peak_detect import find_candidates
from spectra.core.fit_common import fit_windows_to_midpoints, add_qc_columns
from spectra.core.utils import robust_noise_sigma

def run_xrd_pipeline(x, y, outdir, cfg: PipelineConfig, log_cb=None):
    os.makedirs(outdir, exist_ok=True)
    def log(s): 
        if log_cb: log_cb(s)

    try:
        with open(os.path.join(outdir, "run_meta.json"), "w", encoding="utf-8") as f:
            json.dump(cfg.__dict__, f, indent=2)
    except Exception:
        pass

    log("Smoothing...")
    y_s = smooth_signal(y, cfg.sg_window, cfg.sg_poly)

    log("Baseline (AsLS)...")
    bl = baseline_asls(x, y_s, cfg.als_lam, cfg.als_p, cfg.als_max_iter)
    y_corr = y_s - bl

    log("Finding peak candidates...")
    cand, noise_sigma, prom_abs, dist_used = find_candidates(x, y_corr, cfg)
    cand.to_csv(os.path.join(outdir, "peaks_candidates.csv"), index=False)

    # One Voigt per line; windows stop at the midpoint to a neighbouring line
    # (3.5.2).  The smoothed curve finds the candidates and the baseline; the
    # lines are fitted to the unsmoothed counts minus the baseline (3.5.3).  Up
    # to 3.5.2 they were fitted to the smoothed curve: the default 31-point
    # filter (0.62 deg on a 0.02 deg grid) widened lines by +2 to +29 % and a
    # 0.11 deg line by +174 % (synthetic pattern, METHODS section 5).
    y_fit = np.asarray(y, dtype=float) - bl
    fitted_tables = fit_windows_to_midpoints(x, y_fit, cand, cfg.fit_pad)

    fitted = pd.concat(fitted_tables, ignore_index=True) if fitted_tables else pd.DataFrame()
    # S/N and the residual check use the noise of the data that were fitted
    # (3.5.3).  The smoothed curve's noise (first differences of a 31-point
    # filter output, 18x below the counting noise on a synthetic pattern) sets
    # only the detection threshold; up to 3.5.2 it also divided the S/N column.
    fit_sigma = robust_noise_sigma(y_fit)
    log(f"Noise of the fitted data: {fit_sigma:.4g}")
    fitted = add_qc_columns(fitted, fit_sigma)
    fitted.to_csv(os.path.join(outdir, "peaks_fitted.csv"), index=False)

    proc = pd.DataFrame({"x": x, "y_raw": y, "y_smooth": y_s, "baseline": bl, "y_corr": y_corr, "y_fit": y_fit})
    proc.to_csv(os.path.join(outdir, "processed.csv"), index=False)

    log("Done.")
    return proc, cand, fitted
