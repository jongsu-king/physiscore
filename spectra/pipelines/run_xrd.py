import os, json
import pandas as pd
from spectra.core.config import PipelineConfig
from spectra.core.baseline import smooth_signal, baseline_asls
from spectra.core.peak_detect import find_candidates
from spectra.core.fit_common import fit_voigts, add_qc_columns

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

    fitted_tables = []
    for _, r in cand.iterrows():
        cx = float(r["x"])
        region = (cx - cfg.fit_pad, cx + cfg.fit_pad)
        res = fit_voigts(x, y_corr, region, [(cx, float(r["height"]), float(max(r["fwhm_x"], 1e-6)))])
        ft = res[0] if res is not None else None
        if ft is not None and not ft.empty:
            fitted_tables.append(ft)

    fitted = pd.concat(fitted_tables, ignore_index=True) if fitted_tables else pd.DataFrame()
    fitted = add_qc_columns(fitted, noise_sigma)
    fitted.to_csv(os.path.join(outdir, "peaks_fitted.csv"), index=False)

    proc = pd.DataFrame({"x": x, "y_raw": y, "y_smooth": y_s, "baseline": bl, "y_corr": y_corr})
    proc.to_csv(os.path.join(outdir, "processed.csv"), index=False)

    log("Done.")
    return proc, cand, fitted
