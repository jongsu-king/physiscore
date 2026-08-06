from __future__ import annotations

import time
import os
import json
from typing import Optional, Callable

import numpy as np
import pandas as pd

from scripts.common import app_config
from spectra.core.config import PipelineConfig

# Optional Gemini - use google.generativeai, the same SDK as every other
# module in this project (the previous 'google.genai' SDK was not listed in
# requirements.txt, so the AI branch silently never activated)
try:
    import google.generativeai as genai
    _GEMINI_OK = True
except Exception:
    _GEMINI_OK = False



def _get_api_key() -> Optional[str]:
    """Resolve Gemini API key: env (GEMINI_API_KEY/GOOGLE_API_KEY) then config.

    Path resolution and the env export live in scripts.common.app_config, so
    every panel that offers AI commentary finds the same key.
    """
    return app_config.api_key()

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
    lines.append("- If you miss shoulders: reduce noise_k, or enable Gemini hint (overlap) / refine initial seeds.")
    lines.append("- Always cross-check with the raw spectrum and instrument settings.")

    return "\n".join(lines) + "\n"


def _gemini_explanation(cfg: PipelineConfig, top: pd.DataFrame) -> Optional[str]:
    if not _GEMINI_OK:
        return None
    if not cfg.use_gemini:
        return None
    # needs API key
    api_key = _get_api_key()
    if not api_key:
        return None
    if top is None or top.empty:
        return None

    # Keep prompt small
    rows = []
    for _, r in top.iterrows():
        rows.append({
            "center": float(r.get("center", np.nan)),
            "height": float(r.get("height", np.nan)),
            "fwhm": float(r.get("fwhm", np.nan)),
            "snr": float(r.get("snr", np.nan)),
            "quality": str(r.get("quality", "")),
            "pl_component": str(r.get("pl_component", "")) if "pl_component" in top.columns else "",
        })

    prompt = f"""
You are a spectroscopy assistant. Write a concise interpretation report for fitted peaks.

Technique: {cfg.technique}
Constraints/settings:
- If PL: AIC_select={cfg.pl_enable_aic}, max_peaks={cfg.pl_max_peaks}, defect_FWHM_thr={cfg.pl_defect_fwhm_threshold}

Top peaks JSON:
{json.dumps(rows, indent=2)}

Output format:
- 5-8 bullet points total
- Mention what the peaks likely represent (generic, not overconfident)
- Mention what to verify experimentally (calibration/reference/baseline/charge correction, etc.)
- Do NOT invent specific material assignments without evidence.
"""

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(cfg.gemini_model)
        resp = model.generate_content(
            prompt,
            generation_config={
                "temperature": cfg.gemini_temperature,
                "max_output_tokens": 500,
            },
        )
        text = getattr(resp, "text", None)
        return text.strip() if text else None
    except Exception:
        # an LLM failure must not break report generation - the rule-based
        # section is still written
        return None


def generate_ai_peak_report(
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
    llm_txt = _gemini_explanation(cfg, top)

    md_lines = []
    md_lines.append("# AI Peak Explanation Report")
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

    md_lines.append("## Interpretation (Rule-based)")
    md_lines.append(rule_txt)
    md_lines.append("")

    if llm_txt:
        md_lines.append("## Interpretation (Gemini)")
        md_lines.append(llm_txt)
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
