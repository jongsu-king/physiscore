#!/usr/bin/env python3
"""Physiscore command-line interface: the same analysis cores as the GUI,
for scripted and reproducible batch processing.

    python physiscore_cli.py jv   FOLDER [--area 0.04] [--out result.xlsx] [--json]
    python physiscore_cli.py dark FOLDER [--area 0.04] [--out result.xlsx] [--json]
    python physiscore_cli.py eqe  FILE [--sheet NAME] [--voc 1.10] [--temperature 300] [--json]
    python physiscore_cli.py abs  FILE [--sheet NAME] [--column NAME] [--mode direct|indirect] [--thickness NM] [--json]
    python physiscore_cli.py xrd  FILE [--instrument-fwhm DEG] [--k 0.9] [--strip-ka2] [--out peaks.csv] [--json]
    python physiscore_cli.py pl   FILE [--rigidity 6] [--protection 0.01] [--filter 5] [--max-peaks 3] [--json]
    python physiscore_cli.py vib  FILE --technique raman|ftir [--baseline arpls] [--lam 1e5] [--json]
    python physiscore_cli.py sem-stats FILE_OR_VALUES... [--json]
    python physiscore_cli.py sq   EG_EV [--temperature 300]
    python physiscore_cli.py validate [--csv]

Every command prints a human-readable summary; `--json` prints the full
result as JSON (NaN -> null) so it can be consumed by other programs.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any, Dict

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _clean(obj: Any) -> Any:
    """Make a result JSON-serialisable (numpy scalars, NaN, DataFrames)."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return _clean(obj.to_dict(orient="records"))
    if isinstance(obj, np.ndarray):
        return _clean(obj.tolist())
    if isinstance(obj, (np.floating, float)):
        return None if (math.isnan(obj) or math.isinf(obj)) else float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def _emit(result: Dict[str, Any], as_json: bool, summary_lines=None) -> None:
    if as_json:
        print(json.dumps(_clean(result), indent=2))
    else:
        for line in summary_lines or []:
            print(line)


def _read_xy(path: str, sheet=None, column=None):
    """First column = x, `column` (or the first numeric column after it) = y."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(path, sheet_name=sheet or 0)
    else:
        from spectra.core.utils import robust_read_csv
        df = robust_read_csv(path)
    df.columns = [str(c) for c in df.columns]
    x = pd.to_numeric(df.iloc[:, 0], errors="coerce").to_numpy(float)
    if column is None:
        for c in df.columns[1:]:
            if pd.to_numeric(df[c], errors="coerce").notna().sum() > 3:
                column = c
                break
    if column is None:
        raise SystemExit("no numeric y column found")
    y = pd.to_numeric(df[column], errors="coerce").to_numpy(float)
    ok = np.isfinite(x) & np.isfinite(y)
    return x[ok], y[ok], column, df


def _fmt(v, fmt=".4g"):
    try:
        return format(v, fmt) if v is not None and np.isfinite(v) else "-"
    except Exception:
        return str(v)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_jv(a):
    from scripts.JV import jv_core
    data = jv_core.process_jv_directory(a.folder, area_cm2=a.area, diode_fit=not a.no_diode_fit)
    if "error" in data:
        raise SystemExit(data["error"])
    out = a.out or os.path.join(a.folder, f"{os.path.basename(os.path.normpath(a.folder))}.xlsx")
    saved = jv_core.save_to_excel(data, out)
    stats, ca, hy = data["statistics_df"], data["curve_analysis"], data["hysteresis_df"]
    lines = [f"J-V: {data['total_files']} files, cell area {data['cell_area_cm2']:g} cm2, Excel -> {saved}", "",
             stats.to_string(index=False), "", "Curve analysis:", ca.to_string(index=False)]
    if hy is not None and not hy.empty:
        lines += ["", "Hysteresis:", hy.to_string(index=False)]
    _emit({"statistics": stats, "curve_analysis": ca, "hysteresis": hy, "excel": saved,
           "cell_area_cm2": data["cell_area_cm2"]}, a.json, lines)


def cmd_dark(a):
    from scripts.Dark_JV import dark_jv_core
    data = dark_jv_core.process_dark_jv_directory(a.folder, area_cm2=a.area)
    if "error" in data:
        raise SystemExit(data["error"])
    out = a.out or os.path.join(a.folder, f"{os.path.basename(os.path.normpath(a.folder))}_Dark.xlsx")
    saved = dark_jv_core.save_to_excel(data, out)
    sd = data["summary_df"]
    _emit({"summary": sd, "excel": saved}, a.json,
          [f"Dark J-V: {data['total_files']} files, Excel -> {saved}", "", sd.to_string(index=False)])


def cmd_eqe(a):
    from scripts.EQE import eqe_core
    x, y, col, _ = _read_xy(a.file, a.sheet, a.column)
    r = eqe_core.analyze_eqe(x, y, temperature_k=a.temperature, voc_measured_v=a.voc)
    lines = [f"EQE: {a.file} [{col}]",
             f"  Jsc (AM1.5G)          {_fmt(r['Jsc_mA_cm2'], '.3f')} mA/cm2",
             f"  Eg (Rau)              {_fmt(r['Eg_Rau_eV'], '.4f')} eV   sigma {_fmt(1000 * r['Eg_sigma_eV'], '.0f')} meV",
             f"  Eg (inflection)       {_fmt(r['Eg_inflection_eV'], '.4f')} eV",
             f"  Urbach energy         {_fmt(r['Eu_meV'], '.1f')} meV (R2 {_fmt(r['Eu_R2'], '.4f')})",
             f"  J0,rad                {_fmt(r['J0_rad_mA_cm2'], '.3e')} mA/cm2",
             f"  Voc,rad               {_fmt(r['Voc_rad_V'], '.4f')} V",
             f"  SQ limit              Jsc {_fmt(r['Jsc_SQ'], '.2f')} mA/cm2, Voc {_fmt(r['Voc_SQ'], '.4f')} V, "
             f"FF {_fmt(r['FF_SQ'], '.3f')}, PCE {_fmt(r['PCE_SQ'], '.2f')} %"]
    if "dV3_nonrad" in r:
        lines += [f"  dV1 / dV2 / dV3       {_fmt(r['dV1_SQ'], '.3f')} / {_fmt(r['dV2_rad'], '.3f')} / {_fmt(r['dV3_nonrad'], '.3f')} V",
                  f"  EQE_EL (from dV3)     {_fmt(r['EQE_EL'], '.2e')}"]
    _emit(r, a.json, lines)


def cmd_abs(a):
    from scripts.Abs import abs_core
    x, y, col, _ = _read_xy(a.file, a.sheet, a.column)
    r = abs_core.analyze_absorbance(x, y, mode=a.mode, thickness_nm=a.thickness, expected_eg=a.expected_eg)
    lines = [f"Absorbance: {a.file} [{col}], {a.mode} transition",
             f"  Eg (Tauc)             {_fmt(r['Eg_Tauc_eV'], '.4f')} +- {_fmt(r['Eg_err_eV'], '.4f')} eV  "
             f"(region {_fmt(r['Tauc_lo_eV'], '.3f')}-{_fmt(r['Tauc_hi_eV'], '.3f')} eV, R2 {_fmt(r['Tauc_R2'], '.4f')})",
             f"  Eg (derivative)       {_fmt(r['Eg_derivative_eV'], '.4f')} eV",
             f"  Urbach energy         {_fmt(r['Eu_meV'], '.1f')} meV (R2 {_fmt(r['Eu_R2'], '.4f')})"]
    _emit(r, a.json, lines)


def cmd_xrd(a):
    from scripts.XRD import xrd_core
    x, y = xrd_core.load_data(a.file)
    if a.strip_ka2:
        y = xrd_core.strip_kalpha2(x, y)
    peaks, y_fit = xrd_core.detect_peaks_and_fit(x, y, instrumental_fwhm_deg=a.instrument_fwhm, scherrer_k=a.k)
    result: Dict[str, Any] = {"peaks": peaks}
    lines = [f"XRD: {a.file}  ({len(peaks)} reflections, Kalpha2 {'stripped' if a.strip_ka2 else 'kept'})", "",
             peaks.round(5).to_string(index=False)]
    if len(peaks) >= 2:
        wh = xrd_core.williamson_hall(peaks["2Theta"], peaks["FWHM"], instrumental_fwhm_deg=a.instrument_fwhm, k=a.k)
        result["williamson_hall"] = {k: v for k, v in wh.items() if k not in ("x", "y")}
        lines += ["", f"Williamson-Hall: D = {_fmt(wh['D_nm'], '.1f')} +- {_fmt(wh['D_err_nm'], '.1f')} nm, "
                      f"strain = {_fmt(wh['strain'], '.2e')} +- {_fmt(wh['strain_err'], '.1e')}, R2 {_fmt(wh['R2'], '.3f')}"]
    ci = xrd_core.crystallinity_index(x, y)
    result["crystallinity_index_percent"] = ci["CI_percent"]
    lines.append(f"Crystallinity index: {_fmt(ci['CI_percent'], '.1f')} %")
    if a.out:
        peaks.to_csv(a.out, index=False)
        lines.append(f"peaks -> {a.out}")
    _emit(result, a.json, lines)


def cmd_pl(a):
    from scripts.PL import pl_core
    x, y, col, df = _read_xy(a.file, a.sheet, a.column)
    _, _, y_corr = pl_core.process_spectrum(x, y, a.filter, a.rigidity, a.protection)
    single = pl_core.fit_peak_gaussian(x, y_corr)
    metrics = pl_core.peak_metrics(x, y_corr)
    e, ye = pl_core.to_energy_axis(x, y_corr)
    fe = pl_core.fit_peak_gaussian(e, ye)
    result: Dict[str, Any] = {"column": col, "peak_nm": single["center"], "fwhm_nm": single["fwhm"],
                              "peak_eV": fe["center"], "fwhm_meV": 1000 * fe["fwhm"], "metrics": metrics}
    lines = [f"PL: {a.file} [{col}]",
             f"  Peak                  {_fmt(single['center'], '.2f')} nm   |  {_fmt(fe['center'], '.4f')} eV (Jacobian)",
             f"  FWHM                  {_fmt(single['fwhm'], '.2f')} nm   |  {_fmt(1000 * fe['fwhm'], '.1f')} meV",
             f"  Integrated intensity  {_fmt(metrics['area'], '.4g')}   centroid {_fmt(metrics['centroid'], '.2f')} nm   "
             f"asymmetry {_fmt(metrics['asymmetry'], '.3f')}"]
    if a.max_peaks > 1:
        res = pl_core.fit_multi_peak(x, y_corr, max_peaks=a.max_peaks)
        result["components"] = pd.DataFrame(res.table())
        lines += ["", f"Components (AICc, up to {a.max_peaks}): {len(res.peaks)}",
                  pd.DataFrame(res.table())[["center", "height", "fwhm", "area"]].round(3).to_string(index=False)]
    _emit(result, a.json, lines)


def cmd_vib(a):
    from scripts.common import vibrational as vb
    x, y, col, _ = _read_xy(a.file, a.sheet, a.column)
    res = vb.analyze_layer(x, y, technique=a.technique, baseline=a.baseline, lam=a.lam,
                           smooth_window=a.smooth, prominence_frac=a.prominence / 100.0)
    fits, assign = res["fits"], res["assignments"]
    lines = [f"{a.technique.upper()}: {a.file} [{col}]  {len(res['positions'])} bands", ""]
    if fits is not None and not fits.empty:
        lines += ["Band fits:", fits[["center", "height", "fwhm", "area", "r2"]].round(3).to_string(index=False), ""]
    if assign is not None and not assign.empty:
        lines += ["Library suggestions (indicative):",
                  assign[["position", "assignment", "material", "distance"]].round(1).to_string(index=False)]
    _emit({"positions": res["positions"], "fits": fits, "assignments": assign}, a.json, lines)


def cmd_sem_stats(a):
    from scripts.SEM import sem_core
    values = []
    for item in a.values:
        if os.path.exists(item):
            ext = os.path.splitext(item)[1].lower()
            df = pd.read_excel(item) if ext in (".xlsx", ".xls") else pd.read_csv(item)
            col = next((c for c in df.columns if "nm" in str(c).lower() or "size" in str(c).lower() or "diam" in str(c).lower()), df.columns[-1])
            values += pd.to_numeric(df[col], errors="coerce").dropna().tolist()
        else:
            values.append(float(item))
    st = sem_core.size_statistics(values)
    lines = [f"Grain size: N = {int(st['n'])}",
             f"  mean +- std           {_fmt(st['mean'], '.1f')} +- {_fmt(st['std'], '.1f')} nm",
             f"  median D50            {_fmt(st['D50'], '.1f')} nm   D10 {_fmt(st['D10'], '.1f')}   D90 {_fmt(st['D90'], '.1f')} nm",
             f"  log-normal            geometric mean {_fmt(st['geo_mean'], '.1f')} nm, GSD {_fmt(st['gsd'], '.3f')}, mode {_fmt(st['lognorm_mode'], '.1f')} nm"]
    _emit(st, a.json, lines)


def cmd_sq(a):
    from scripts.EQE import eqe_core
    sq = eqe_core.shockley_queisser(a.eg, a.temperature)
    _emit(sq, a.json, [f"Shockley-Queisser limit at Eg = {a.eg} eV, T = {a.temperature} K:",
                       f"  Jsc {_fmt(sq['Jsc_SQ'], '.2f')} mA/cm2   Voc {_fmt(sq['Voc_SQ'], '.4f')} V   "
                       f"FF {_fmt(sq['FF_SQ'], '.3f')}   PCE {_fmt(sq['PCE_SQ'], '.2f')} %"])


def cmd_validate(a):
    import subprocess
    cmd = [sys.executable, os.path.join(ROOT, "tools", "validation_report.py")] + (["--csv"] if a.csv else [])
    raise SystemExit(subprocess.call(cmd))


# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="physiscore", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--json", action="store_true", help="print the full result as JSON")

    p = sub.add_parser("jv", help="illuminated J-V folder"); p.add_argument("folder")
    p.add_argument("--area", type=float, default=None, help="device area in cm2 (default: configuration)")
    p.add_argument("--out", help="Excel path"); p.add_argument("--no-diode-fit", action="store_true"); common(p); p.set_defaults(func=cmd_jv)

    p = sub.add_parser("dark", help="dark J-V folder"); p.add_argument("folder")
    p.add_argument("--area", type=float, default=None); p.add_argument("--out"); common(p); p.set_defaults(func=cmd_dark)

    p = sub.add_parser("eqe", help="EQE spectrum (wavelength nm, EQE % or fraction)"); p.add_argument("file")
    p.add_argument("--sheet"); p.add_argument("--column"); p.add_argument("--voc", type=float, default=None, help="measured Voc (V) for the loss analysis")
    p.add_argument("--temperature", type=float, default=300.0); common(p); p.set_defaults(func=cmd_eqe)

    p = sub.add_parser("abs", help="UV-Vis absorbance (wavelength nm, A)"); p.add_argument("file")
    p.add_argument("--sheet"); p.add_argument("--column"); p.add_argument("--mode", default="direct", choices=sorted(["direct", "indirect", "direct_forbidden", "indirect_forbidden"]))
    p.add_argument("--thickness", type=float, default=None, help="film thickness (nm) to report alpha"); p.add_argument("--expected-eg", type=float, default=None)
    common(p); p.set_defaults(func=cmd_abs)

    p = sub.add_parser("xrd", help="XRD pattern (2theta, intensity)"); p.add_argument("file")
    p.add_argument("--instrument-fwhm", type=float, default=0.0); p.add_argument("--k", type=float, default=0.9)
    p.add_argument("--strip-ka2", action="store_true"); p.add_argument("--out", help="CSV of the peak table"); common(p); p.set_defaults(func=cmd_xrd)

    p = sub.add_parser("pl", help="PL spectrum (wavelength nm, intensity)"); p.add_argument("file")
    p.add_argument("--sheet"); p.add_argument("--column"); p.add_argument("--filter", type=float, default=5)
    p.add_argument("--rigidity", type=float, default=6); p.add_argument("--protection", type=float, default=0.01)
    p.add_argument("--max-peaks", type=int, default=3); common(p); p.set_defaults(func=cmd_pl)

    p = sub.add_parser("vib", help="Raman or FTIR spectrum"); p.add_argument("file")
    p.add_argument("--technique", required=True, choices=["raman", "ftir"]); p.add_argument("--sheet"); p.add_argument("--column")
    p.add_argument("--baseline", default="arpls", choices=["arpls", "als", "linear", "min", "none"]); p.add_argument("--lam", type=float, default=1e5)
    p.add_argument("--smooth", type=int, default=0); p.add_argument("--prominence", type=float, default=2.0, help="percent of the range")
    common(p); p.set_defaults(func=cmd_vib)

    p = sub.add_parser("sem-stats", help="grain-size statistics of values or a CSV/Excel column"); p.add_argument("values", nargs="+")
    common(p); p.set_defaults(func=cmd_sem_stats)

    p = sub.add_parser("sq", help="Shockley-Queisser limit for a band gap"); p.add_argument("eg", type=float)
    p.add_argument("--temperature", type=float, default=300.0); common(p); p.set_defaults(func=cmd_sq)

    p = sub.add_parser("validate", help="regenerate the validation table"); p.add_argument("--csv", action="store_true"); p.set_defaults(func=cmd_validate)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
