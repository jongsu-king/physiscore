from __future__ import annotations

import time
import os
from typing import Optional, Callable

import numpy as np
import pandas as pd

from scripts.common.interpret import interpret_peak_fit
from spectra.core.config import PipelineConfig


def _log(log_cb: Optional[Callable[[str], None]], s: str):
    if log_cb:
        log_cb(s)


def _top_peaks(fitted: pd.DataFrame, topn: int = 10) -> pd.DataFrame:
    if fitted is None or fitted.empty:
        return pd.DataFrame()
    key = "area_amplitude" if "area_amplitude" in fitted.columns else None
    if key:
        return fitted.sort_values(key, ascending=False).head(topn).copy()
    return fitted.head(topn).copy()


def _format_table(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "(no fitted peaks)\n"
    cols = [c for c in ["center", "height", "fwhm", "area_amplitude", "snr", "quality", "pl_component"] if c in df.columns]
    d = df[cols].copy()
    # numeric formatting
    for c in ["center", "height", "fwhm", "area_amplitude", "snr"]:
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    return d.to_string(index=False)


def _rule_based_explanation(cfg: PipelineConfig, top: pd.DataFrame) -> str:
    if top is None or top.empty:
        return "No reliable fitted peaks were found. Check baseline, smoothing, or peak-detection thresholds.\n"

    lines = []
    tech = cfg.technique.upper()

    if tech == "XRD":
        lines.append("Interpretation notes (XRD, rule-based):")
        lines.append("- Peak centers are typically reported as 2θ (deg) if your x-axis is 2θ.")
        lines.append("- Higher area/height can indicate stronger diffraction intensity (preferred orientation, crystallinity, thickness effects).")
        lines.append("- FWHM relates to crystallite size/strain (Scherrer analysis requires instrument broadening correction).")

    elif tech == "PL":
        lines.append("Interpretation notes (PL, rule-based):")
        if cfg.pl_enable_aic:
            lines.append(f"- Model order selection used AIC up to max_peaks={cfg.pl_max_peaks}.")
        lines.append(f"- Broad vs narrow label threshold: FWHM >= {cfg.pl_defect_fwhm_threshold} → defect(broad).")
        lines.append("- Narrow peaks often relate to band-edge emission; broad peaks often relate to defect/CT-state emission (context dependent).")

    else:
        lines.append("Interpretation notes (rule-based):")
        lines.append("- Validate the baseline subtraction and smoothing first.")
        lines.append("- Check whether the detected peaks match visible spectral features.")

    # Per-peak bullets
    lines.append("\nTop peak comments:")
    for i, r in top.reset_index(drop=True).iterrows():
        center = float(r["center"]) if "center" in r else np.nan
        fwhm = float(r["fwhm"]) if "fwhm" in r else np.nan
        qual = str(r["quality"]) if "quality" in r else "N/A"
        snr = float(r["snr"]) if "snr" in r else np.nan

        msg = f"- Peak #{i+1}: center={center:.4g}, FWHM={fwhm:.4g}, SNR={snr:.3g}, quality={qual}"
        if tech == "PL" and "pl_component" in r:
            msg += f", label={r['pl_component']}"
        lines.append(msg)

    lines.append("\nRecommendations:")
    lines.append("- If you see false positives: increase noise_k or min_peak_separation_x.")
    lines.append("- If you miss shoulders: reduce noise_k or min_peak_separation_x and refit.")
    lines.append("- Always cross-check with the raw spectrum and instrument settings.")

    return "\n".join(lines) + "\n"


def generate_peak_report(
    proc: pd.DataFrame,
    cand: pd.DataFrame,
    fitted: pd.DataFrame,
    cfg: PipelineConfig,
    outdir: str,
    file_label: str = "",
    log_cb=None,
    topn: int = 10,
) -> str:
    """
    Writes:
      - peak_report.md
      - peak_report.txt
      - peak_report_top_peaks.csv
    Returns path to peak_report.md
    """
    os.makedirs(outdir, exist_ok=True)

    top = _top_peaks(fitted, topn=topn)

    _log(log_cb, "Preparing peak report contents...")
    table_txt = _format_table(top)

    rule_txt = _rule_based_explanation(cfg, top)
    rules = interpret_peak_fit(cfg.technique, fitted, subject=file_label)

    md_lines = []
    md_lines.append("# Peak report")
    if file_label:
        md_lines.append(f"**File:** {file_label}")
    md_lines.append(f"**Technique:** {cfg.technique}")
    md_lines.append(f"**Generated at:** {time.strftime('%Y-%m-%d %H:%M:%S')}")
    md_lines.append("")

    md_lines.append("## Summary Table (Top Peaks)")
    md_lines.append("```text")
    md_lines.append(table_txt)
    md_lines.append("```")
    md_lines.append("")

    md_lines.append("## Technique notes")
    md_lines.append(rule_txt)
    md_lines.append("")

    md_lines.append("## Rule-based findings")
    md_lines.append(rules.summary())
    md_lines.append("")
    for f in rules.sorted():
        md_lines.append(f"- **{f.level.capitalize()} - {f.topic}.** {f.text}"
                        + (f" Evidence: {f.evidence}." if f.evidence else "")
                        + (f" Rule: {f.rule}." if f.rule else "")
                        + (f" Next: {f.action}" if f.action else "")
                        + (f" ({f.ref})" if f.ref else ""))
    md_lines.append("")

    # Save outputs
    md_path = os.path.join(outdir, "peak_report.md")
    txt_path = os.path.join(outdir, "peak_report.txt")
    csv_path = os.path.join(outdir, "peak_report_top_peaks.csv")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines).replace("```text", "").replace("```", ""))

    if top is not None:
        top.to_csv(csv_path, index=False)

    _log(log_cb, f"Report files written: {md_path}, {txt_path}, {csv_path}")
    return md_path
