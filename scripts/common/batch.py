"""Per-file analysers and table readers shared by the comparison windows and
the command-line batch mode (GUI-free).

Each analyser takes (x, y) of one spectrum and returns a flat dict of scalar
results, so many files can be tabulated side by side. The defaults are the
same as the single-file tools; anything a user tunes in a tool window can be
passed as keyword arguments.
"""
from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

DATA_EXTENSIONS = (".csv", ".txt", ".tsv", ".dat", ".xlsx", ".xls", ".xy")


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def read_table(path: str, sheet=None) -> pd.DataFrame:
    """A data table from CSV/TXT/TSV/DAT/XY (metadata preamble skipped) or
    Excel (first sheet unless `sheet` is given)."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(path, sheet_name=sheet if sheet not in (None, "") else 0)
    else:
        from spectra.core.utils import robust_read_csv
        df = robust_read_csv(path)
    df.columns = [str(c) for c in df.columns]
    return df


def numeric_columns(df: pd.DataFrame) -> List[str]:
    """Columns after the first (x) one that hold at least 4 numbers."""
    return [c for c in df.columns[1:] if pd.to_numeric(df[c], errors="coerce").notna().sum() > 3]


def read_xy(path: str, sheet=None, column: Optional[str] = None) -> Tuple[np.ndarray, np.ndarray, str]:
    """(x, y, y-column name): x is column 0, y the named column or the first
    numeric one after x. Rows with a non-number in either are dropped and the
    result is sorted by x."""
    df = read_table(path, sheet)
    cols = numeric_columns(df)
    if not cols:
        raise ValueError(f"{os.path.basename(path)}: no numeric y column")
    col = column if column in cols else cols[0]
    x = pd.to_numeric(df.iloc[:, 0], errors="coerce").to_numpy(float)
    y = pd.to_numeric(df[col], errors="coerce").to_numpy(float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    order = np.argsort(x)
    return x[order], y[order], col


def read_all_columns(path: str, sheet=None) -> List[Tuple[np.ndarray, np.ndarray, str]]:
    """Every numeric y column of a file as its own spectrum."""
    df = read_table(path, sheet)
    x = pd.to_numeric(df.iloc[:, 0], errors="coerce").to_numpy(float)
    out = []
    for col in numeric_columns(df):
        y = pd.to_numeric(df[col], errors="coerce").to_numpy(float)
        ok = np.isfinite(x) & np.isfinite(y)
        order = np.argsort(x[ok])
        out.append((x[ok][order], y[ok][order], col))
    return out


def list_data_files(folder: str, extensions=DATA_EXTENSIONS) -> List[str]:
    """Data files of a folder (natural order), skipping hidden/lock files and
    the workbooks and side-cars Physiscore writes itself."""
    from scripts.common.iv_io import is_result_workbook
    from scripts.common.naming import natural_sort_key
    out = []
    for f in sorted(os.listdir(folder), key=natural_sort_key):
        p = os.path.join(folder, f)
        if not os.path.isfile(p) or f.startswith((".", "~$")) or f.endswith(".analysis.json"):
            continue
        if f.lower().endswith(extensions) and not is_result_workbook(p) and "_summary" not in f.lower():
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# analysers: (x, y, **options) -> dict of scalars
# ---------------------------------------------------------------------------
def analyse_eqe(x, y, temperature_k: float = 300.0, voc: Optional[float] = None) -> Dict[str, float]:
    from scripts.EQE import eqe_core
    r = eqe_core.analyze_eqe(x, y, temperature_k=temperature_k, voc_measured_v=voc)
    out = {"Jsc (mA/cm2)": r["Jsc_mA_cm2"], "Eg Rau (eV)": r["Eg_Rau_eV"],
           "sigma (meV)": 1000 * r["Eg_sigma_eV"] if np.isfinite(r["Eg_sigma_eV"]) else np.nan,
           "Eg inflection (eV)": r["Eg_inflection_eV"], "Eu (meV)": r["Eu_meV"],
           "Voc,rad (V)": r["Voc_rad_V"], "Voc,SQ (V)": r["Voc_SQ"], "EQE max (%)": float(np.nanmax(
               eqe_core.eqe_to_fraction(y))) * 100.0}
    if voc is not None and "dV3_nonrad" in r:
        out["dV3 non-rad (V)"] = r["dV3_nonrad"]
    return out


def analyse_abs(x, y, mode: str = "direct", thickness_nm: Optional[float] = None,
                expected_eg: Optional[float] = None) -> Dict[str, float]:
    from scripts.Abs import abs_core
    r = abs_core.analyze_absorbance(x, y, mode=mode, thickness_nm=thickness_nm, expected_eg=expected_eg)
    return {"Eg Tauc (eV)": r["Eg_Tauc_eV"], "Eg error (eV)": r["Eg_err_eV"], "Tauc R2": r["Tauc_R2"],
            "region lo (eV)": r["Tauc_lo_eV"], "region hi (eV)": r["Tauc_hi_eV"],
            "Eg derivative (eV)": r["Eg_derivative_eV"], "Eu (meV)": r["Eu_meV"]}


def analyse_pl(x, y, filter_width: float = 5, rigidity: float = 6, protection: float = 0.01) -> Dict[str, float]:
    from scripts.PL import pl_core
    _, _, yc = pl_core.process_spectrum(x, y, filter_width, rigidity, protection)
    g = pl_core.fit_peak_gaussian(x, yc)
    m = pl_core.peak_metrics(x, yc)
    e, ye = pl_core.to_energy_axis(x, yc)
    ge = pl_core.fit_peak_gaussian(e, ye)
    return {"Peak (nm)": g["center"] if g["success"] else m["peak_x"], "FWHM (nm)": g["fwhm"] if g["success"] else m["fwhm"],
            "Peak (eV)": ge["center"] if ge["success"] else np.nan,
            "FWHM (meV)": 1000 * ge["fwhm"] if ge["success"] else np.nan,
            "Max intensity": m["max"], "Integrated intensity": m["area"], "Centroid (nm)": m["centroid"],
            "Asymmetry": m["asymmetry"]}


def analyse_xrd(x, y, instrumental_fwhm_deg: float = 0.0, k: float = 0.9) -> Dict[str, float]:
    from scripts.XRD import xrd_core
    peaks, _ = xrd_core.detect_peaks_and_fit(x, y, instrumental_fwhm_deg=instrumental_fwhm_deg, scherrer_k=k)
    out = {"Reflections": int(len(peaks))}
    if len(peaks):
        top = peaks.iloc[0]
        out.update({"Strongest 2theta (deg)": float(top["2Theta"]), "Strongest FWHM (deg)": float(top["FWHM"]),
                    "Strongest tau (nm)": float(top["Crystallite_nm"]), "Strongest intensity": float(top["Intensity"])})
    if len(peaks) >= 2:
        wh = xrd_core.williamson_hall(peaks["2Theta"], peaks["FWHM"], instrumental_fwhm_deg, k)
        out.update({"W-H D (nm)": wh["D_nm"], "W-H strain": wh["strain"]})
    out["Crystallinity (%)"] = xrd_core.crystallinity_index(x, y)["CI_percent"]
    return out


def analyse_vib(x, y, technique: str = "raman", baseline: str = "arpls", lam: float = 1e5) -> Dict[str, float]:
    from scripts.common import vibrational as vb
    res = vb.analyze_layer(x, y, technique=technique, baseline=baseline, lam=lam)
    pos = np.asarray(res["positions"], dtype=float)
    out = {"Bands": int(len(pos))}
    fits = res["fits"]
    if fits is not None and not fits.empty:
        top = fits.sort_values("height", ascending=False).iloc[0]
        out.update({"Strongest band (cm-1)": float(top["center"]), "Strongest FWHM (cm-1)": float(top["fwhm"])})
    out["Band positions (cm-1)"] = ", ".join(f"{p:.0f}" for p in pos[:12])
    return out


ANALYSERS: Dict[str, Callable] = {"eqe": analyse_eqe, "abs": analyse_abs, "pl": analyse_pl,
                                  "xrd": analyse_xrd, "raman": lambda x, y, **kw: analyse_vib(x, y, "raman", **kw),
                                  "ftir": lambda x, y, **kw: analyse_vib(x, y, "ftir", **kw)}


def run_batch(technique: str, files: List[str], sheet=None, column: Optional[str] = None,
              all_columns: bool = False, **options) -> pd.DataFrame:
    """Analyse every file (or every column of every file with `all_columns`)
    and return one row per spectrum: File, Column, results..., Error."""
    fn = ANALYSERS[technique]
    rows = []
    for path in files:
        try:
            spectra = read_all_columns(path, sheet) if all_columns else [read_xy(path, sheet, column)]
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the batch
            rows.append({"File": os.path.basename(path), "Column": "", "Error": str(exc)})
            continue
        for x, y, col in spectra:
            row = {"File": os.path.basename(path), "Column": col}
            try:
                row.update(fn(x, y, **options))
                row["Error"] = ""
            except Exception as exc:  # noqa: BLE001
                row["Error"] = str(exc)
            rows.append(row)
    df = pd.DataFrame(rows)
    if "Error" in df.columns:
        df = df[[c for c in df.columns if c != "Error"] + ["Error"]]
    return df
