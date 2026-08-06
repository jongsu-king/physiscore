import os, json
import numpy as np
import pandas as pd
from spectra.core.config import PipelineConfig
from spectra.core.baseline import smooth_signal, baseline_asls
from spectra.core.peak_detect import find_candidates, detect_overlap_regions
from spectra.core.fit_common import add_qc_columns, fit_voigts
from spectra.core.fit_xps import fit_xps_doublet_voigts  # <- XPS fitting split out below

def run_xps_pipeline(x, y, outdir, cfg: PipelineConfig, log_cb=None):
    os.makedirs(outdir, exist_ok=True)
    def log(s): 
        if log_cb: log_cb(s)

    # meta
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
    log(f"Auto params: noise_sigma={noise_sigma:.4g}, prominence_abs={prom_abs:.4g}, distance_pts={dist_used}")

    roi = (float(cfg.xps_roi_min), float(cfg.xps_roi_max))
    if roi[0] >= roi[1]:
        roi = None

    fitted_tables = []
    for _, r in cand.iterrows():
        cx = float(r["x"])
        if roi is not None and not (roi[0] <= cx <= roi[1]):
            continue
        region = (cx - cfg.fit_pad, cx + cfg.fit_pad)
        if roi is not None:
            region = (max(region[0], roi[0]), min(region[1], roi[1]))

        if float(cfg.xps_split_ev) > 0:
            # spin-orbit doublet (2p, 3d, 4f ... lines)
            res = fit_xps_doublet_voigts(
                x, y_corr, region,
                init_center=cx,
                init_height=float(r["height"]),
                init_fwhm=float(max(r["fwhm_x"], 1e-6)),
                split_ev=cfg.xps_split_ev,
                area_ratio=cfg.xps_area_ratio,
                lock_widths=cfg.xps_lock_widths,
            )
        else:
            # singlet (s-orbital lines like O1s / C1s / N1s): a doublet with
            # split=0 would just stack two identical peaks - fit one Voigt
            res = fit_voigts(
                x, y_corr, region,
                [(cx, float(r["height"]), float(max(r["fwhm_x"], 1e-6)))],
            )
        if res is None:
            continue
        ft = res[0]
        if ft is not None and not ft.empty:
            fitted_tables.append(ft)

    fitted = pd.concat(fitted_tables, ignore_index=True) if fitted_tables else pd.DataFrame()
    fitted = add_qc_columns(fitted, noise_sigma)
    fitted.to_csv(os.path.join(outdir, "peaks_fitted.csv"), index=False)

    proc = pd.DataFrame({"x": x, "y_raw": y, "y_smooth": y_s, "baseline": bl, "y_corr": y_corr})
    proc.to_csv(os.path.join(outdir, "processed.csv"), index=False)

    log("Done.")
    return proc, cand, fitted
