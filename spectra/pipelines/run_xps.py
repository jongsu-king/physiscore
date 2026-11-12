import os, json
import numpy as np
import pandas as pd
from spectra.core.config import PipelineConfig
from spectra.core.baseline import smooth_signal, baseline_asls
from spectra.core.peak_detect import find_candidates
from spectra.core.fit_common import add_qc_columns, fit_voigts
from spectra.core.fit_xps import doublet_mains, fit_xps_doublet_cluster
from spectra.core.utils import robust_noise_sigma


def _clusters(xs, gap):
    """Indices of sorted positions ``xs`` grouped where neighbours are <= gap apart."""
    groups, current = [], []
    for i, v in enumerate(xs):
        if current and v - xs[current[-1]] > gap:
            groups.append(current)
            current = []
        current.append(i)
    if current:
        groups.append(current)
    return groups


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

    x = np.asarray(x, dtype=float) + float(getattr(cfg, "xps_charge_shift_ev", 0.0) or 0.0)
    y = np.asarray(y, dtype=float)

    log("Smoothing...")
    y_s = smooth_signal(y, cfg.sg_window, cfg.sg_poly)

    if str(getattr(cfg, "xps_background", "shirley")).lower() == "shirley":
        log("Background (Shirley)...")
        from spectra.core.xps import shirley_background
        bl = shirley_background(x, y_s)
    else:
        log("Baseline (AsLS)...")
        bl = baseline_asls(x, y_s, cfg.als_lam, cfg.als_p, cfg.als_max_iter)
    y_corr = y_s - bl
    # The smoothed curve finds the candidates; the lines are fitted to the
    # unsmoothed counts minus the background (3.5.3).  Up to 3.5.2 they were
    # fitted to the smoothed curve: on a 0.2 eV scan the 7-point filter widened
    # Pb 4f7/2 by 7 % and took 5 % of its area.
    y_fit = y - bl

    log("Finding peak candidates...")
    cand, noise_sigma, prom_abs, dist_used = find_candidates(x, y_corr, cfg)
    cand.to_csv(os.path.join(outdir, "peaks_candidates.csv"), index=False)
    log(f"Auto params: noise_sigma={noise_sigma:.4g}, prominence_abs={prom_abs:.4g}, distance_pts={dist_used}")

    roi = (float(cfg.xps_roi_min), float(cfg.xps_roi_max))
    if roi[0] >= roi[1]:
        roi = None

    sel = cand.sort_values("x") if not cand.empty else cand
    if roi is not None and not sel.empty:
        sel = sel[(sel["x"] >= roi[0]) & (sel["x"] <= roi[1])]

    def clip(region):
        return (max(region[0], roi[0]), min(region[1], roi[1])) if roi is not None else region

    pad = float(cfg.fit_pad)
    split = float(cfg.xps_split_ev)
    fitted_tables = []
    if sel.empty:
        pass
    elif split <= 0:
        # Singlet lines: candidates whose windows overlap are fitted together as
        # one cluster (all components at once, window = cluster +- fit_pad).
        # Fitting one Voigt per candidate window failed next to large peaks: a
        # window edge cut through a neighbour that had no component, and the
        # small peak's amplitude went to 0 (Pb 4f with a metallic shoulder).
        rows = [r for _, r in sel.iterrows()]
        for g in _clusters([float(r["x"]) for r in rows], 2.0 * pad):
            members = [rows[i] for i in g]
            region = clip((float(members[0]["x"]) - pad, float(members[-1]["x"]) + pad))
            init = [(float(m["x"]), float(m["height"]), float(max(m["fwhm_x"], 1e-6))) for m in members]
            res = fit_voigts(x, y_fit, region, init)
            if res is not None and res[0] is not None and not res[0].empty:
                fitted_tables.append(res[0])
    else:
        # Spin-orbit doublets (2p, 3d, 4f ...): candidates that are the partner
        # line of a stronger candidate are dropped, and doublets whose windows
        # (first line - fit_pad to partner + fit_pad) overlap are fitted together
        # (3.5.3; up to 3.5.2 every candidate got its own doublet in its own window).
        step = float(np.median(np.abs(np.diff(x)))) if len(x) > 1 else 0.0
        mains = doublet_mains(sel, split, step, cfg.xps_area_ratio)
        log(f"Doublets: {len(mains)} first lines from {len(sel)} candidates (split {split:g} eV)")
        rows = [r for _, r in mains.iterrows()]
        for g in _clusters([float(r["x"]) for r in rows], split + 2.0 * pad):
            members = [rows[i] for i in g]
            region = clip((float(members[0]["x"]) - pad, float(members[-1]["x"]) + split + pad))
            init = [(float(m["x"]), float(m["height"]), float(max(m["fwhm_x"], 1e-6))) for m in members]
            res = fit_xps_doublet_cluster(x, y_fit, region, init, split, cfg.xps_area_ratio,
                                          lock_widths=cfg.xps_lock_widths)
            if res is not None and res[0] is not None and not res[0].empty:
                fitted_tables.append(res[0])

    fitted = pd.concat(fitted_tables, ignore_index=True) if fitted_tables else pd.DataFrame()
    # S/N and the residual check use the noise of the data that were fitted
    # (3.5.3); the smoothed curve's noise sets only the detection threshold.
    fit_sigma = robust_noise_sigma(y_fit)
    log(f"Noise of the fitted data: {fit_sigma:.4g}")
    fitted = add_qc_columns(fitted, fit_sigma)
    fitted.to_csv(os.path.join(outdir, "peaks_fitted.csv"), index=False)

    proc = pd.DataFrame({"x": x, "y_raw": y, "y_smooth": y_s, "baseline": bl, "y_corr": y_corr, "y_fit": y_fit})
    proc.to_csv(os.path.join(outdir, "processed.csv"), index=False)

    log("Done.")
    return proc, cand, fitted
