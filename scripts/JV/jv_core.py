# jv_core.py - J-V Curve Analysis Core Logic (No UI)
import os
import re
import math
import time
import json
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Any

import pandas as pd
import numpy as np

from scripts.common import textio as _textio
import openpyxl
from openpyxl.styles import PatternFill

from scripts.common import app_config
from scripts.common.naming import (base_name as _base_name,
                                   cell_number as _cell_number,
                                   display_name_from_path, natural_sort_key)
from scripts.common.origin import WIN32COM_AVAILABLE, connect_to_origin
from scripts.common.iv_io import GENERIC_EXTENSIONS, is_result_workbook, read_generic_iv
from scripts.common import palette as _pal

# =========================
# Constants & Settings
# =========================
DEFAULT_CELL_AREA_CM2 = app_config.DEFAULT_CELL_AREA_CM2  # historical: factor -25000
STANDARD_IRRADIANCE_MW_CM2 = 100.0  # AM1.5G, 1 sun


def cell_area_cm2(override: Optional[float] = None) -> float:
    """Active device area [cm^2], read from the config on every call.

    Deliberately not a module-level constant. The area scales Jsc -- and
    therefore PCE -- linearly, and it used to be captured once at import time,
    so correcting it in physisfera_config.json did nothing until the whole
    application was restarted.
    """
    return app_config.cell_area_cm2(override)


def current_conversion_factor(area_cm2: Optional[float] = None) -> float:
    """Measured current [A] * factor -> current density [mA/cm^2].

    Negative: the source-meter reports photocurrent with the sign opposite to
    the photovoltaic convention.
    """
    return app_config.current_conversion_factor(area_cm2)


# =========================
# Curve-derived device parameters
# =========================
def compute_jv_parameters(voltage, current_density,
                          pin_mw_cm2: float = STANDARD_IRRADIANCE_MW_CM2) -> Dict[str, float]:
    """
    Compute photovoltaic parameters directly from a light J-V curve instead of
    trusting the instrument summary block.

    voltage: V [V]; current_density: J [mA/cm^2] (either sign convention).
    Returns Voc [V], Jsc [mA/cm^2], FF [%], PCE [%], Vmpp [V], Jmpp [mA/cm^2],
    Pmax [mW/cm^2], Rs [Ohm cm^2] (slope at Voc), Rsh [Ohm cm^2] (slope at Jsc).
    NaN is returned for parameters that cannot be determined.
    """
    out = {k: float("nan") for k in
           ("Voc", "Jsc", "FF", "PCE", "Vmpp", "Jmpp", "Pmax", "Rs", "Rsh")}

    v = np.asarray(voltage, dtype=float)
    j = np.asarray(current_density, dtype=float)
    ok = np.isfinite(v) & np.isfinite(j)
    v, j = v[ok], j[ok]
    if len(v) < 5:
        return out
    order = np.argsort(v)
    v, j = v[order], j[order]
    # collapse duplicate voltages (e.g. merged fwd/rev scans)
    vu, inv = np.unique(v, return_inverse=True)
    if len(vu) != len(v):
        sums = np.bincount(inv, weights=j)
        counts = np.bincount(inv)
        j = sums / np.maximum(counts, 1)
        v = vu
    if len(v) < 5 or not (v.min() <= 0.0 <= v.max()):
        return out

    # Work with photocurrent positive at short circuit
    j0 = float(np.interp(0.0, v, j))
    sign = -1.0 if j0 < 0 else 1.0
    jw = sign * j
    jsc = float(np.interp(0.0, v, jw))
    if jsc <= 0:
        return out

    # Voc: first + -> - zero crossing at V > 0
    voc = float("nan")
    pos = np.where(v > 0)[0]
    for i in pos:
        if i == 0:
            continue
        if jw[i - 1] > 0 >= jw[i]:
            voc = v[i - 1] + (v[i] - v[i - 1]) * jw[i - 1] / (jw[i - 1] - jw[i])
            break
    if not np.isfinite(voc) or voc <= 0:
        return out

    # Max power point on a dense grid within [0, Voc]
    grid = np.linspace(0.0, voc, 2000)
    jg = np.interp(grid, v, jw)
    p = grid * jg  # mW/cm^2
    imax = int(np.argmax(p))
    pmax = float(p[imax])
    vmpp = float(grid[imax])
    jmpp = float(jg[imax])

    ff = 100.0 * pmax / (jsc * voc) if jsc * voc > 0 else float("nan")
    pce = 100.0 * pmax / pin_mw_cm2 if pin_mw_cm2 > 0 else float("nan")

    def _slope_resistance(v_center: float) -> float:
        """|dV/dJ| [Ohm cm^2] from a local linear fit around v_center."""
        win = max(0.05 * voc, 0.02)
        m = np.abs(v - v_center) <= win
        if int(np.sum(m)) < 3:
            idx = np.argsort(np.abs(v - v_center))[:5]
            m = np.zeros_like(v, dtype=bool)
            m[idx] = True
        try:
            djdv = np.polyfit(v[m], jw[m], 1)[0]  # mA/cm^2 per V
            if abs(djdv) < 1e-12:
                return float("inf")
            return abs(1.0 / djdv) * 1000.0  # -> Ohm cm^2
        except Exception:
            return float("nan")

    out.update(Voc=float(voc), Jsc=jsc, FF=float(ff), PCE=float(pce),
               Vmpp=vmpp, Jmpp=jmpp, Pmax=pmax,
               Rs=_slope_resistance(voc), Rsh=_slope_resistance(0.0))
    return out


@dataclass
class JVSettings:
    x_min: float = -0.2
    x_max: float = 1.0
    y_min: float = -25.0
    y_max: float = 5.0


# =========================
# Data Parsing
# =========================
def parse_jv_file(file_path: str,
                  area_cm2: Optional[float] = None) -> Tuple[Optional[Dict], List[Dict]]:
    """
    Parse a single JV text file.

    area_cm2: active device area for the current-density conversion. None reads
    it from the configuration at call time.
    Returns: (summary_data, voltage_data_list)
    """
    if file_path.lower().endswith(GENERIC_EXTENSIONS):
        return _parse_generic_jv(file_path, display_name_from_path(file_path), cell_area_cm2(area_cm2))
    try:
        data = _textio.read_text(file_path).splitlines(keepends=True)
    except Exception as e:
        return None, []

    display_name = display_name_from_path(file_path)
    conversion_factor = current_conversion_factor(area_cm2)

    summary_data = None
    voltage_data = []

    # Find header line for summary data
    header_line = None
    for i, line in enumerate(data):
        if "Voc V" in line and "Jsc mA/cm2" in line and "Fill Factor" in line and "Efficiency" in line:
            header_line = i
            break

    if header_line is not None:
        try:
            values = data[header_line + 1].split("\t")
            voc = format(float(values[0]), ".3g") if len(values) > 0 else "non"
        except (ValueError, IndexError):
            voc = "non"

        try:
            values = data[header_line + 1].split("\t")
            jsc = format(float(values[2]), ".2f") if len(values) > 2 else "non"
        except (ValueError, IndexError):
            jsc = "non"

        try:
            values = data[header_line + 1].split("\t")
            fill_factor = format(float(values[6].strip()), ".2f") if len(values) > 6 else "non"
        except (ValueError, IndexError):
            fill_factor = "non"

        try:
            values = data[header_line + 1].split("\t")
            efficiency = format(float(values[7].strip()), ".2f") if len(values) > 7 else "non"
        except (ValueError, IndexError):
            efficiency = "non"

        summary_data = {
            "Filename": display_name,
            "Voc V": voc,
            "Jsc mA/cm2": jsc,
            "Fill Factor": fill_factor,
            "PCE (%)": efficiency
        }

    # Parse voltage/current data
    vmeas_idx = -1
    for i, line in enumerate(data):
        if "Vmeas" in line and "Imeas" in line:
            vmeas_idx = i + 1
            break

    if vmeas_idx != -1:
        for line in data[vmeas_idx:]:
            if line.strip():
                values = line.split("\t")
                if len(values) >= 2:
                    try:
                        voltage_value = float(values[0])
                        if -3 <= voltage_value <= 3:
                            current_value = float(values[1]) * conversion_factor
                            voltage_data.append({
                                "Voltage(V)": round(voltage_value, 4),
                                "Sample": display_name,
                                "Current": current_value
                            })
                    except (ValueError, IndexError):
                        pass

    if summary_data is not None:
        summary_data["Summary source"] = "instrument"
    # Files exported without the instrument summary block still carry a valid
    # J-V curve: the summary values are computed from that curve, so the
    # statistics, box charts and best-device selection include the device.
    if summary_data is None and voltage_data:
        summary_data = _summary_from_curve(display_name, voltage_data)

    return summary_data, voltage_data


def _summary_from_curve(display_name: str, voltage_data: List[Dict]) -> Dict[str, Any]:
    v = np.array([r["Voltage(V)"] for r in voltage_data], dtype=float)
    j = np.array([r["Current"] for r in voltage_data], dtype=float)
    p = compute_jv_parameters(v, j)

    def fmt(val, spec):
        return format(val, spec) if np.isfinite(val) else "non"

    return {"Filename": display_name, "Voc V": fmt(p["Voc"], ".3g"), "Jsc mA/cm2": fmt(p["Jsc"], ".2f"),
            "Fill Factor": fmt(p["FF"], ".2f"), "PCE (%)": fmt(p["PCE"], ".2f"), "Summary source": "curve"}


def _parse_generic_jv(file_path: str, display_name: str, area: float) -> Tuple[Optional[Dict], List[Dict]]:
    """CSV/TSV/DAT/XLSX curve (see scripts.common.iv_io); summary from the curve."""
    try:
        v, j, _how = read_generic_iv(file_path, area)
    except Exception:
        return None, []
    voltage_data = [{"Voltage(V)": round(float(vv), 4), "Sample": display_name, "Current": float(jj)}
                    for vv, jj in zip(v, j) if -3 <= vv <= 3]
    if not voltage_data:
        return None, []
    return _summary_from_curve(display_name, voltage_data), voltage_data


def process_jv_directory(directory_path: str, progress_callback=None,
                         area_cm2: Optional[float] = None, diode_fit: bool = True) -> Dict[str, Any]:
    """
    Process all JV text files in a directory.

    area_cm2: active device area for the current-density conversion. None reads
    it from the configuration at call time, so a corrected area takes effect on
    the next analysis instead of on the next application start.
    diode_fit: also fit the one-diode equivalent circuit to every device
    (adds n, J0, Jph, Rs, Rsh columns to the CurveAnalysis table).
    Returns dictionary with all processed data, including 'hysteresis_df'
    (per-direction parameters and hysteresis index for files that were
    swept both ways) and 'diode_fits' (fit results keyed by sample).
    """
    area = cell_area_cm2(area_cm2)
    # Accept a single folder or a list of folders (JV_Analysis.exe '+ Add'
    # folder-comparison). Duplicate display names across folders get a
    # ' (2)', ' (3)'... suffix instead of being silently averaged together.
    dirs = [directory_path] if isinstance(directory_path, str) else [d for d in directory_path if d]
    file_pairs = []
    for d in dirs:
        try:
            for f in sorted(os.listdir(d)):
                low = f.lower()
                if f.startswith((".", "~$")):
                    continue
                if low.endswith(".txt") or (low.endswith(GENERIC_EXTENSIONS)
                                            and not is_result_workbook(os.path.join(d, f))):
                    file_pairs.append((d, f))
        except Exception:
            continue

    if not file_pairs:
        return {"error": "No text files found"}

    voltage_data = []
    table_data_list = []
    seen_names: Dict[str, int] = {}
    file_of_sample: Dict[str, str] = {}

    for idx, (d, filename) in enumerate(file_pairs):
        file_path = os.path.join(d, filename)

        if progress_callback:
            progress_callback(idx, filename, len(file_pairs))

        summary, v_data = parse_jv_file(file_path, area_cm2=area)
        if summary:
            nm = summary["Filename"]
            if nm in seen_names:
                seen_names[nm] += 1
                new_nm = f"{nm} ({seen_names[nm]})"
                summary["Filename"] = new_nm
                for r in v_data:
                    r["Sample"] = new_nm
            else:
                seen_names[nm] = 1
            table_data_list.append(summary)
            file_of_sample[summary["Filename"]] = file_path
        voltage_data.extend(v_data)
    txt_files = [f for _, f in file_pairs]

    if not table_data_list:
        return {"error": "No valid data found"}

    # Convert to DataFrames
    voltage_df = pd.DataFrame(voltage_data)
    voltage_df = voltage_df.sort_values('Voltage(V)')
    combined_data = voltage_df.groupby(['Voltage(V)', 'Sample'])['Current'].mean().unstack()
    combined_data = combined_data.reset_index()

    summary_df = pd.DataFrame(table_data_list)

    # Group cells of one condition together: "Ref 1", "Ref 2" -> "Ref"
    summary_df['Base_Name'] = summary_df['Filename'].apply(_base_name)
    summary_df['Number'] = summary_df['Filename'].apply(_cell_number)

    # Find best performance per group (all-NaN groups fall back to first entry)
    best_performance = summary_df.copy()
    best_performance['PCE_numeric'] = pd.to_numeric(best_performance['PCE (%)'], errors='coerce').fillna(-np.inf)
    best_performance = best_performance.loc[best_performance.groupby('Base_Name')['PCE_numeric'].idxmax()]
    best_performance = best_performance.drop(columns=['PCE_numeric'])

    best_performance['Original_Filename'] = best_performance['Filename']
    best_performance['Filename'] = best_performance['Base_Name']

    # Sort best_performance by Base_Name using natural sort
    best_performance['_sort_key'] = best_performance['Base_Name'].apply(lambda x: natural_sort_key(x))
    best_performance = best_performance.sort_values('_sort_key').drop(columns=['_sort_key'])

    # Filter combined data to only include best samples
    best_samples = best_performance['Original_Filename'].tolist()
    columns_to_keep = ['Voltage(V)'] + [col for col in combined_data.columns if col in best_samples]
    best_combined_data = combined_data[columns_to_keep].copy() if len(columns_to_keep) > 1 else pd.DataFrame()

    if not best_combined_data.empty:
        best_combined_data = best_combined_data.rename(columns={'Voltage(V)': 'Voltage (V)'})
        new_columns = {}
        for col in best_combined_data.columns:
            if col != 'Voltage (V)':
                new_columns[col] = _base_name(col)
        best_combined_data = best_combined_data.rename(columns=new_columns)

        # Sort columns using natural sort (keep 'Voltage (V)' first)
        other_cols = [c for c in best_combined_data.columns if c != 'Voltage (V)']
        sorted_cols = sorted(other_cols, key=natural_sort_key)
        best_combined_data = best_combined_data[['Voltage (V)'] + sorted_cols]

    best_performance = best_performance.drop(columns=['Base_Name', 'Number'])

    # Round numeric columns (4 decimals: keeps mA/cm^2 precision for slope-based
    # resistance analysis of exported data; 2 decimals truncated real information)
    for df in [combined_data]:
        if not df.empty:
            for column in df.columns:
                if column != 'Voltage(V)' and df[column].dtype in ['float64', 'float32']:
                    df[column] = df[column].round(4)

    if not best_combined_data.empty:
        for column in best_combined_data.columns:
            if column != 'Voltage (V)' and best_combined_data[column].dtype in ['float64', 'float32']:
                best_combined_data[column] = best_combined_data[column].round(4)

    # Create box chart data
    unique_base_names = sorted(summary_df['Base_Name'].unique(), key=natural_sort_key)
    params = ['Voc V', 'Jsc mA/cm2', 'Fill Factor', 'PCE (%)']
    box_charts = {}

    for param in params:
        box_data = []
        for base_name in unique_base_names:
            group_data = summary_df[summary_df['Base_Name'] == base_name].sort_values('Number')
            for i, (_, row) in enumerate(group_data.iterrows(), 1):
                row_exists = False
                for existing_row in box_data:
                    if existing_row['Row'] == i:
                        existing_row[base_name] = row[param]
                        row_exists = True
                        break
                if not row_exists:
                    # No fixed cap: previously rows beyond 8 devices per group
                    # were silently dropped from the statistics.
                    new_row = {'Row': i, base_name: row[param]}
                    box_data.append(new_row)

        box_df = pd.DataFrame(box_data)
        if not box_df.empty:
            box_df = box_df.sort_values('Row').set_index('Row')
        box_charts[param] = box_df

    # --- Curve-derived parameters for every device (independent cross-check
    #     of the instrument summary; also yields Rs/Rsh which the summary lacks)
    curve_rows = []
    diode_fits: Dict[str, Dict[str, Any]] = {}
    v_arr = combined_data['Voltage(V)'].to_numpy(dtype=float)
    for col in combined_data.columns:
        if col == 'Voltage(V)':
            continue
        j_arr = combined_data[col].to_numpy(dtype=float)
        p = compute_jv_parameters(v_arr, j_arr)
        row = {
            "Filename": col,
            "Voc (V)": round(p["Voc"], 4) if np.isfinite(p["Voc"]) else np.nan,
            "Jsc (mA/cm2)": round(p["Jsc"], 3) if np.isfinite(p["Jsc"]) else np.nan,
            "FF (%)": round(p["FF"], 2) if np.isfinite(p["FF"]) else np.nan,
            "PCE (%)": round(p["PCE"], 3) if np.isfinite(p["PCE"]) else np.nan,
            "Vmpp (V)": round(p["Vmpp"], 4) if np.isfinite(p["Vmpp"]) else np.nan,
            "Jmpp (mA/cm2)": round(p["Jmpp"], 3) if np.isfinite(p["Jmpp"]) else np.nan,
            "Pmax (mW/cm2)": round(p["Pmax"], 3) if np.isfinite(p["Pmax"]) else np.nan,
            "Rs (Ohm cm2)": round(p["Rs"], 2) if np.isfinite(p["Rs"]) else np.nan,
            "Rsh (Ohm cm2)": round(p["Rsh"], 1) if np.isfinite(p["Rsh"]) else np.nan,
        }
        # one-diode equivalent circuit (Lambert-W form); ~20 ms per device
        if diode_fit and np.isfinite(p["PCE"]):
            try:
                fit = fit_single_diode(v_arr, j_arr)
            except Exception:
                fit = {"success": False}
            if fit.get("success"):
                diode_fits[col] = fit
                row.update({
                    "n (diode fit)": round(fit["n"], 3),
                    "J0 fit (mA/cm2)": float(f'{fit["J0"]:.3e}'),
                    "Jph fit (mA/cm2)": round(fit["Jph"], 3),
                    "Rs fit (Ohm cm2)": round(fit["Rs"], 3),
                    "Rsh fit (Ohm cm2)": round(fit["Rsh"], 1),
                    "Diode fit R2": round(fit["R2"], 5),
                })
        curve_rows.append(row)
    curve_analysis = pd.DataFrame(curve_rows)

    # --- Scan-direction analysis (forward / reverse, hysteresis index) ---
    hyst_rows = []
    for name, path in file_of_sample.items():
        try:
            v_raw, j_raw = read_jv_curve(path, area_cm2=area)
            h = analyze_scan_hysteresis(v_raw, j_raw)
        except Exception:
            continue
        if h["n_segments"] < 2 or not (h["forward"] and h["reverse"]):
            continue
        f, r = h["forward"], h["reverse"]
        hyst_rows.append({
            "Filename": name,
            "Segments": h["n_segments"],
            "PCE fwd (%)": round(f["PCE"], 3), "PCE rev (%)": round(r["PCE"], 3),
            "Voc fwd (V)": round(f["Voc"], 4), "Voc rev (V)": round(r["Voc"], 4),
            "Jsc fwd (mA/cm2)": round(f["Jsc"], 3), "Jsc rev (mA/cm2)": round(r["Jsc"], 3),
            "FF fwd (%)": round(f["FF"], 2), "FF rev (%)": round(r["FF"], 2),
            "HI (%)": round(h["HI"], 2) if np.isfinite(h["HI"]) else np.nan,
        })
    hysteresis_df = pd.DataFrame(hyst_rows)

    # --- Group statistics (mean +/- std, publication-style reporting) ---
    stats_rows = []
    for base_name in unique_base_names:
        grp = summary_df[summary_df['Base_Name'] == base_name]
        row = {"Condition": base_name, "N": len(grp)}
        for param, label in [('Voc V', 'Voc (V)'), ('Jsc mA/cm2', 'Jsc (mA/cm2)'),
                             ('Fill Factor', 'FF (%)'), ('PCE (%)', 'PCE (%)')]:
            vals = pd.to_numeric(grp[param], errors='coerce').dropna()
            if len(vals):
                row[f"{label} mean"] = round(float(vals.mean()), 4)
                row[f"{label} std"] = round(float(vals.std(ddof=1)), 4) if len(vals) > 1 else 0.0
                row[f"{label} best"] = round(float(vals.max()), 4)
            else:
                row[f"{label} mean"] = np.nan
                row[f"{label} std"] = np.nan
                row[f"{label} best"] = np.nan
        stats_rows.append(row)
    statistics_df = pd.DataFrame(stats_rows)

    return {
        "combined_data": combined_data,
        "summary_df": summary_df,
        "best_performance": best_performance,
        "best_combined_data": best_combined_data,
        "box_charts": box_charts,
        "curve_analysis": curve_analysis,
        "statistics_df": statistics_df,
        "hysteresis_df": hysteresis_df,
        "diode_fits": diode_fits,
        "cell_area_cm2": area,
        "input_dirs": [os.path.abspath(d) for d in dirs],
        "total_files": len(txt_files)
    }


def save_to_excel(data: Dict[str, Any], excel_path: str) -> str:
    """Save processed data to Excel.

    Returns the path actually written ('' on failure). If the target file is
    locked (typically: the user still has it open in Excel - previously the
    save FAILED SILENTLY and the file kept stale data), a timestamped
    '<name>_HHMMSS.xlsx' is written next to it instead. A reproducibility
    side-car '<name>.analysis.json' is written next to the workbook.
    """
    try:
        saved = _save_to_excel_impl(data, excel_path)
    except PermissionError:
        alt = f"{os.path.splitext(excel_path)[0]}_{time.strftime('%H%M%S')}.xlsx"
        try:
            saved = _save_to_excel_impl(data, alt)
        except Exception as e:
            print(f"Excel save error (fallback): {e}")
            return ""
    except Exception as e:
        print(f"Excel save error: {e}")
        return ""
    if saved:
        from scripts.common.provenance import write_sidecar
        write_sidecar(saved, "J-V (light)", inputs=data.get("input_dirs"),
                      parameters={"cell_area_cm2": data.get("cell_area_cm2"), "irradiance_mW_cm2": STANDARD_IRRADIANCE_MW_CM2,
                                  "diode_fit": bool(data.get("diode_fits")), "temperature_K": 298.15},
                      results={"statistics": data.get("statistics_df"), "hysteresis": data.get("hysteresis_df"),
                               "total_files": data.get("total_files")})
    return saved


def _save_to_excel_impl(data: Dict[str, Any], excel_path: str) -> str:
    try:
        with pd.ExcelWriter(excel_path, engine="openpyxl", mode="w") as writer:
            data["combined_data"].to_excel(writer, sheet_name="CombinedData", index=False)
            data["summary_df"].to_excel(writer, sheet_name="SummaryTable", index=False)
            data["best_performance"].to_excel(writer, sheet_name="BestPerformance", index=False)
            if not data["best_combined_data"].empty:
                data["best_combined_data"].to_excel(writer, sheet_name="BestCombinedData", index=False)

            ca = data.get("curve_analysis")
            if ca is not None and not ca.empty:
                ca.to_excel(writer, sheet_name="CurveAnalysis", index=False)
            st = data.get("statistics_df")
            if st is not None and not st.empty:
                st.to_excel(writer, sheet_name="Statistics", index=False)
            hy = data.get("hysteresis_df")
            if hy is not None and not hy.empty:
                hy.to_excel(writer, sheet_name="Hysteresis", index=False)

            for param, df in data["box_charts"].items():
                if not df.empty:
                    sheet_name = f"{param.split()[0]}_BoxChart"
                    df.to_excel(writer, sheet_name=sheet_name)

        # Highlight best performers
        workbook = openpyxl.load_workbook(excel_path)
        if "SummaryTable" in workbook.sheetnames:
            sheet = workbook["SummaryTable"]
            highlight_fill = PatternFill(start_color="FFFF00", end_color="FFFF00", fill_type="solid")
            best_files = [row['Original_Filename'] for _, row in data["best_performance"].iterrows()]

            header_row = True
            for row in sheet.iter_rows():
                if header_row:
                    header_row = False
                    continue
                if row[0].value in best_files:
                    for cell in row:
                        cell.fill = highlight_fill

        workbook.save(excel_path)
        return excel_path
    except PermissionError:
        raise
    except Exception as e:
        print(f"Excel save error: {e}")
        return ""


# =========================
# Matplotlib Plotting
# =========================
try:
    from scripts.common.plot_interactions import smart_legend
except Exception:
    def smart_legend(ax, loc="upper left", **_k):
        try:
            return ax.legend(loc=loc, fontsize=9, framealpha=0.9)
        except Exception:
            return None


def create_iv_plot(ax, best_combined_data: pd.DataFrame, settings: JVSettings):
    """Create I-V curve plot on given matplotlib axes."""
    ax.clear()

    if best_combined_data.empty:
        ax.text(0.5, 0.5, "No Data", ha='center', va='center', fontsize=14, color=_pal.TXT_DIM)
        return

    # Plot each sample
    voltage_col = 'Voltage (V)'
    sample_cols = [col for col in best_combined_data.columns if col != voltage_col]

    colors = _pal.SERIES_COLORS

    for i, col in enumerate(sample_cols):
        color = colors[i % len(colors)]
        ax.plot(best_combined_data[voltage_col], best_combined_data[col],
                '-', linewidth=2, label=col, color=color)

    # Style - white labels
    ax.set_xlabel("Voltage (V)", fontsize=12, color=_pal.PLOT_FG)
    ax.set_ylabel("Current Density (mA/cm²)", fontsize=12, color=_pal.PLOT_FG)
    ax.set_xlim(settings.x_min, settings.x_max)
    ax.set_ylim(settings.y_min, settings.y_max)

    # Reference lines
    ax.axhline(y=0, color=_pal.PLOT_REF, linewidth=0.8, linestyle='-')
    ax.axvline(x=0, color=_pal.PLOT_REF, linewidth=0.8, linestyle='-')

    # Grid
    ax.grid(True, alpha=0.3, linestyle='--')

    # Legend - overflow-safe (long sample names / many samples previously
    # covered the whole plot)
    if sample_cols:
        smart_legend(ax)


def create_single_iv_plot(ax, best_combined_data: pd.DataFrame, sample_name: str, settings: JVSettings):
    """Create I-V curve plot for a single selected sample."""
    ax.clear()

    if best_combined_data.empty:
        ax.text(0.5, 0.5, "No Data", ha='center', va='center', fontsize=14, color=_pal.TXT_DIM)
        return

    voltage_col = 'Voltage (V)'

    # Find matching column (sample_name may be base name without number)
    matching_col = None
    for col in best_combined_data.columns:
        if col != voltage_col and col == sample_name:
            matching_col = col
            break

    if matching_col is None:
        ax.text(0.5, 0.5, f"Sample '{sample_name}' not found",
                ha='center', va='center', fontsize=14, color=_pal.TXT_DIM)
        return

    # Plot selected sample
    ax.plot(best_combined_data[voltage_col], best_combined_data[matching_col],
            '-', linewidth=2.5, label=matching_col, color=_pal.ACCENT)

    # Style - white labels
    ax.set_xlabel("Voltage (V)", fontsize=12, color=_pal.PLOT_FG)
    ax.set_ylabel("Current Density (mA/cm²)", fontsize=12, color=_pal.PLOT_FG)
    ax.set_xlim(settings.x_min, settings.x_max)
    ax.set_ylim(settings.y_min, settings.y_max)
    ax.set_title(f"{sample_name}", fontsize=14, color=_pal.PLOT_FG)

    # Reference lines
    ax.axhline(y=0, color=_pal.PLOT_REF, linewidth=0.8, linestyle='-')
    ax.axvline(x=0, color=_pal.PLOT_REF, linewidth=0.8, linestyle='-')

    # Grid
    ax.grid(True, alpha=0.3, linestyle='--')

    # Legend - overflow-safe
    smart_legend(ax)


def create_multi_iv_plot(ax, best_combined_data: pd.DataFrame, sample_names: List[str], settings: JVSettings):
    """Create I-V curve plot for multiple selected samples."""
    ax.clear()

    if best_combined_data.empty:
        ax.text(0.5, 0.5, "No Data", ha='center', va='center', fontsize=14, color=_pal.TXT_DIM)
        return

    voltage_col = 'Voltage (V)'

    colors = _pal.SERIES_COLORS

    plotted = False
    for i, sample_name in enumerate(sample_names):
        # Find matching column
        matching_col = None
        for col in best_combined_data.columns:
            if col != voltage_col and col == sample_name:
                matching_col = col
                break

        if matching_col is not None:
            color = colors[i % len(colors)]
            ax.plot(best_combined_data[voltage_col], best_combined_data[matching_col],
                    '-', linewidth=2, label=matching_col, color=color)
            plotted = True

    if not plotted:
        ax.text(0.5, 0.5, "No matching samples found",
                ha='center', va='center', fontsize=14, color=_pal.TXT_DIM)
        return

    # Style - white labels
    ax.set_xlabel("Voltage (V)", fontsize=12, color=_pal.PLOT_FG)
    ax.set_ylabel("Current Density (mA/cm²)", fontsize=12, color=_pal.PLOT_FG)
    ax.set_xlim(settings.x_min, settings.x_max)
    ax.set_ylim(settings.y_min, settings.y_max)

    if len(sample_names) <= 3:
        ax.set_title(", ".join(sample_names), fontsize=12, color=_pal.PLOT_FG)
    else:
        ax.set_title(f"Multiple Samples ({len(sample_names)})", fontsize=12, color=_pal.PLOT_FG)

    # Reference lines
    ax.axhline(y=0, color=_pal.PLOT_REF, linewidth=0.8, linestyle='-')
    ax.axvline(x=0, color=_pal.PLOT_REF, linewidth=0.8, linestyle='-')

    # Grid
    ax.grid(True, alpha=0.3, linestyle='--')

    # Legend - overflow-safe
    smart_legend(ax)


def create_box_plot(ax, box_df: pd.DataFrame, param_name: str, selected_samples: List[str] = None):
    """Create box plot on given matplotlib axes.

    Args:
        ax: Matplotlib axes
        box_df: DataFrame with box plot data (columns are sample names)
        param_name: Parameter name (e.g., 'PCE (%)')
        selected_samples: List of selected sample names to display. If None or empty, show all.
    """
    ax.clear()

    if box_df.empty:
        ax.text(0.5, 0.5, "No Data", ha='center', va='center', fontsize=14, color=_pal.TXT_DIM)
        return

    # Filter columns if samples are selected
    columns_to_plot = box_df.columns.tolist()
    if selected_samples:
        # Match selected sample names with box_df columns
        columns_to_plot = [col for col in box_df.columns if col in selected_samples]
        if not columns_to_plot:
            ax.text(0.5, 0.5, "No matching samples", ha='center', va='center', fontsize=14, color=_pal.TXT_DIM)
            return

    # Convert to numeric
    data_for_plot = []
    labels = []
    for col in columns_to_plot:
        numeric_data = pd.to_numeric(box_df[col], errors='coerce').dropna().tolist()
        if numeric_data:
            data_for_plot.append(numeric_data)
            labels.append(col)

    if not data_for_plot:
        ax.text(0.5, 0.5, "No Valid Data", ha='center', va='center', fontsize=14, color=_pal.TXT_DIM)
        return

    # Create box plot
    # matplotlib renamed boxplot's 'labels' to 'tick_labels' in 3.9 and the old
    # name is scheduled for removal - support both
    try:
        bp = ax.boxplot(data_for_plot, tick_labels=labels, patch_artist=True)
    except TypeError:
        bp = ax.boxplot(data_for_plot, labels=labels, patch_artist=True)

    # Style boxes
    colors = _pal.SERIES_COLORS
    for i, (box, median) in enumerate(zip(bp['boxes'], bp['medians'])):
        box.set_facecolor(colors[i % len(colors)])
        box.set_alpha(0.7)
        median.set_color(_pal.PLOT_FG)
        median.set_linewidth(2)

    # Y-axis label - white color with display formatting
    display_labels = {
        "Voc V": "Voc (V)",
        "Jsc mA/cm2": "Jsc (mA/cm²)",
        "Fill Factor": "Fill Factor (%)",
        "PCE (%)": "PCE (%)"
    }
    ylabel = display_labels.get(param_name, param_name)
    ax.set_ylabel(ylabel, fontsize=11, color=_pal.PLOT_FG)

    # Rotate x labels
    ax.tick_params(axis='x', rotation=45, colors=_pal.PLOT_TICK)
    ax.tick_params(axis='y', colors=_pal.PLOT_TICK)
    ax.grid(True, axis='y', alpha=0.3, linestyle='--')


# =========================
# Origin Integration
# =========================
# connect_to_origin lives in scripts/common/origin.py and is imported above,
# so all nine tools share one connection routine.

def save_selected_to_transit_excel(
    best_combined_data: pd.DataFrame,
    box_charts: Dict[str, pd.DataFrame],
    selected_samples: List[str],
    original_excel_path: str,
    log_callback=None
) -> str:
    """
    Save selected sample data to a transit Excel file for Origin.

    Args:
        best_combined_data: Full best combined data DataFrame
        box_charts: Full box charts dictionary
        selected_samples: List of selected sample names. If empty, use all samples.
        original_excel_path: Path to the original Excel file
        log_callback: Optional callback for logging

    Returns:
        Path to the transit Excel file
    """
    # Generate transit file path
    base_dir = os.path.dirname(original_excel_path)
    base_name = os.path.splitext(os.path.basename(original_excel_path))[0]
    transit_path = os.path.join(base_dir, f"{base_name}_transit.xlsx")

    # Filter data based on selection
    voltage_col = 'Voltage (V)'

    # If no selection, use all samples
    if not selected_samples:
        filtered_combined_data = best_combined_data.copy()
        filtered_box_charts = {k: v.copy() for k, v in box_charts.items()}
    else:
        # Filter best_combined_data columns
        cols_to_keep = [voltage_col] + [col for col in best_combined_data.columns
                                         if col != voltage_col and col in selected_samples]
        filtered_combined_data = best_combined_data[cols_to_keep].copy() if len(cols_to_keep) > 1 else pd.DataFrame()

        # Filter box_charts columns
        filtered_box_charts = {}
        for param, box_df in box_charts.items():
            if not box_df.empty:
                cols = [col for col in box_df.columns if col in selected_samples]
                if cols:
                    filtered_box_charts[param] = box_df[cols].copy()
                else:
                    filtered_box_charts[param] = pd.DataFrame()
            else:
                filtered_box_charts[param] = pd.DataFrame()

    # Save to transit Excel
    try:
        with pd.ExcelWriter(transit_path, engine="openpyxl", mode="w") as writer:
            if not filtered_combined_data.empty:
                filtered_combined_data.to_excel(writer, sheet_name="BestCombinedData", index=False)

            for param, df in filtered_box_charts.items():
                if not df.empty:
                    sheet_name = f"{param.split()[0]}_BoxChart"
                    df.to_excel(writer, sheet_name=sheet_name)

        if log_callback:
            sample_count = len(selected_samples) if selected_samples else "all"
            log_callback(f"Transit file saved: {sample_count} samples -> {os.path.basename(transit_path)}")

        return transit_path

    except Exception as e:
        if log_callback:
            log_callback(f"Transit file save error: {e}")
        return ""


def plot_iv_to_origin(origin, best_combined_data: pd.DataFrame, settings: JVSettings, log_callback=None):
    """Plot I-V curve to Origin."""
    if best_combined_data.empty:
        if log_callback:
            log_callback("BestCombinedData is empty")
        return

    if log_callback:
        log_callback("Creating Origin I-V plot...")

    columns = best_combined_data.columns.tolist()
    num_cols = len(columns)

    wb_name = origin.CreatePage(2, "BestCombinedData", "Origin")
    origin.Execute(f"page.active$ = {wb_name};")
    origin.Execute(f"wks.ncols = {num_cols};")

    # X column (Voltage)
    origin.Execute(f'wks.col1.lname$ = "{columns[0]}";')
    origin.Execute("wks.col1.type = 4;")
    origin.Execute('wks.col1.units$ = "V";')

    x_data = best_combined_data.iloc[:, 0].fillna('').tolist()
    origin.PutWorksheet(f"[{wb_name}]Sheet1", x_data, 0, 0)

    # Y columns (Current)
    for i in range(1, num_cols):
        col_idx = i + 1
        col_name = columns[i]
        origin.Execute(f'wks.col{col_idx}.lname$ = "{col_name}";')
        origin.Execute(f"wks.col{col_idx}.type = 1;")
        y_data = best_combined_data.iloc[:, i].fillna('').tolist()
        origin.PutWorksheet(f"[{wb_name}]Sheet1", y_data, 0, i)

    if log_callback:
        log_callback("Data written to worksheet")

    # Create plot
    origin.Execute(f"plotxy iy:=[{wb_name}]Sheet1!(1,2:{num_cols}) plot:=202;")

    # Style
    _customize_iv_graph(origin, settings)

    if log_callback:
        log_callback("Origin I-V plot complete")


def _customize_iv_graph(origin, settings: JVSettings):
    """Apply styling to I-V graph in Origin."""
    origin.Execute("set %C -k 20;")
    origin.Execute("label -yl Current Density (mA/cm\\+(2));")
    origin.Execute("xb.fsize = 40;")
    origin.Execute("yl.fsize = 40;")
    origin.Execute("layer.y.inc = 5;")
    origin.Execute("layer.x.inc = .5;")
    origin.Execute("layer.y.label.pt = 30;")
    origin.Execute("layer.x.label.pt = 30;")
    origin.Execute("layer.x.showAxes = 3;")
    origin.Execute("layer.x.showLabels = 1;")
    origin.Execute("layer.y.showAxes = 3;")
    origin.Execute("layer.y.showLabels = 1;")
    origin.Execute("layer.x2.ticks = 0;")
    origin.Execute("layer.y2.ticks = 0;")
    origin.Execute(f"layer.x.from = {settings.x_min};")
    origin.Execute(f"layer.x.to = {settings.x_max};")
    origin.Execute(f"layer.y.from = {settings.y_min};")
    origin.Execute(f"layer.y.to = {settings.y_max};")
    origin.Execute("draw -n RefLineX -l -v 0;")
    origin.Execute("draw -n RefLineY -l -h 0;")
    origin.Execute("legend -r;")
    origin.Execute("doc -uw;")


def plot_box_to_origin(origin, box_charts: Dict[str, pd.DataFrame], log_callback=None):
    """Plot all box charts to Origin."""
    for param_name, box_df in box_charts.items():
        if not box_df.empty:
            _plot_single_box_chart(origin, box_df, param_name, log_callback)

    if log_callback:
        log_callback("Origin box plots complete")


def _plot_single_box_chart(origin, box_df: pd.DataFrame, parameter_name: str, log_callback=None):
    """Plot single box chart to Origin."""
    if log_callback:
        log_callback(f"Creating box plot: {parameter_name}")

    safe_name = re.sub(r'[^\w]', '_', parameter_name.split()[0]) + "_Box"
    wb_name = origin.CreatePage(2, safe_name, "Origin")

    columns = box_df.columns.tolist()
    num_cols = len(columns)

    origin.Execute(f"win -a {wb_name};")
    origin.Execute(f"wks.ncols = {num_cols};")

    for i, col_name in enumerate(columns):
        col_idx = i + 1
        origin.Execute(f'wks.col{col_idx}.lname$ = "{col_name}";')
        origin.Execute(f"wks.col{col_idx}.type = 1;")
        y_data = box_df[col_name].fillna('').tolist()
        origin.PutWorksheet(f"[{wb_name}]Sheet1", y_data, 0, i)

    origin.Execute(f"win -a {wb_name};")
    origin.Execute(f"worksheet -s 1 0 {num_cols} 0;")
    origin.Execute("worksheet -p 206 Box;")

    # Y-axis label with proper formatting
    label_map = {
        "Voc V": "V\\-(oc) (V)",
        "Jsc mA/cm2": "J\\-(sc) (mA/cm\\+(2))",
        "Fill Factor": "Fill Factor (%)",
        "PCE (%)": "PCE (%)"
    }
    label = label_map.get(parameter_name, parameter_name)
    origin.Execute(f"label -yl {label};")

    # Style
    origin.Execute("layer.x.label.pt = 20;")
    origin.Execute("layer.y.label.pt = 20;")
    origin.Execute("yl.fsize = 30;")
    origin.Execute("layer.x.label.rotate = 45;")
    origin.Execute("layer.plot1.boxchart.type=3;")
    origin.Execute("legend -a off;")
    origin.Execute("legend -d;")
    origin.Execute("label -r Legend;")
    origin.Execute("set %C -k 20")
    origin.Execute("layer.x.showAxes = 3;")
    
    origin.Execute("layer.x.showLabels = 1;")
    
    origin.Execute("layer.y.showAxes = 3;")
    
    origin.Execute("layer.y.showLabels = 1;")
    origin.Execute("layer.x2.ticks = 0;")
    origin.Execute("layer.y2.ticks = 0;")
    

    # Box plot fill styling (OriginPro 2018 compatible)
    # -pf 1: enable fill area
    # -pfb color#: fill background color
    # -c color#: border/line color
    origin.Execute("set %C -gm 1")
    origin.Execute("set %C -z 15")
    origin.Execute("set %C -pf 1;")    # turn fill on
    origin.Execute("set %C -pfb -4;")   # inner fill color (color index 2: red)
    origin.Execute("set %C -pbci 1;")     # border color (color index 1: black)

    origin.Execute("doc -uw;")


# =========================
# Single-diode equivalent circuit (explicit Lambert-W form)
# =========================
Q_E = 1.602176634e-19          # C
K_B = 1.380649e-23             # J/K


def thermal_voltage(temperature_k: float = 298.15) -> float:
    """kT/q [V]."""
    return K_B * float(temperature_k) / Q_E


def _lambertw_exp(z):
    """W(exp(z)) on the principal branch, stable for arbitrarily large z.

    exp(z) overflows beyond z ~ 709, but the quantity that enters the diode
    equation is W(exp(z)), which grows only like z - ln z. For large z the
    fixed point of w + ln w = z is found by Newton iteration instead.
    """
    from scipy.special import lambertw
    z = np.asarray(z, dtype=float)
    out = np.empty_like(z)
    small = z < 500.0
    if np.any(small):
        out[small] = lambertw(np.exp(z[small])).real
    if np.any(~small):
        zl = z[~small]
        w = zl - np.log(zl)
        for _ in range(30):
            w = w - (w + np.log(w) - zl) / (1.0 + 1.0 / w)
        out[~small] = w
    return out


def single_diode_current(voltage, jph, j0, n, rs, rsh, temperature_k: float = 298.15):
    """Current density [mA/cm^2] of the one-diode model, photocurrent positive.

        J = Jph - J0 [exp((V + J Rs)/(n kT/q)) - 1] - (V + J Rs)/Rsh

    solved explicitly with the Lambert W function (Jain & Kapoor, Sol. Energy
    Mater. Sol. Cells 81, 269 (2004)). Jph, J0 in mA/cm^2; Rs, Rsh in Ohm cm^2.
    """
    v = np.asarray(voltage, dtype=float)
    vt = float(n) * thermal_voltage(temperature_k)
    jph_a, j0_a = float(jph) / 1000.0, float(j0) / 1000.0   # A/cm^2 so that J*R is a voltage
    rs, rsh = float(rs), float(rsh)
    if rs <= 0:
        return 1000.0 * (jph_a - j0_a * np.expm1(np.clip(v / vt, -700, 700)) - v / rsh)
    log_a = math.log(rs * rsh * j0_a / (vt * (rs + rsh)))
    z = log_a + rsh * (rs * (jph_a + j0_a) + v) / (vt * (rs + rsh))
    w = _lambertw_exp(z)
    j = (rsh * (jph_a + j0_a) - v) / (rs + rsh) - (vt / rs) * w
    return 1000.0 * j


def fit_single_diode(voltage, current_density, temperature_k: float = 298.15,
                     pin_mw_cm2: float = STANDARD_IRRADIANCE_MW_CM2) -> Dict[str, Any]:
    """Fit the one-diode model to an illuminated J-V curve.

    Returns Jph, J0 [mA/cm^2], n, Rs, Rsh [Ohm cm^2], the goodness of fit
    (R^2, RMSE in mA/cm^2) and the model curve on the input voltages. The
    fit works in log space for Jph, J0, Rs and Rsh (they span decades) and
    starts from the curve-derived Jsc, Voc, Rs and Rsh so that it converges
    from a physically sensible point. Three ideality-factor starts are tried
    and the lowest-cost solution kept.
    """
    from scipy.optimize import least_squares

    out = {k: float("nan") for k in ("Jph", "J0", "n", "Rs", "Rsh", "R2", "RMSE", "cost")}
    out.update(success=False, message="", y_fit=None, voltage=None)

    v = np.asarray(voltage, dtype=float)
    j = np.asarray(current_density, dtype=float)
    ok = np.isfinite(v) & np.isfinite(j)
    v, j = v[ok], j[ok]
    if len(v) < 8:
        out["message"] = "too few points"
        return out
    order = np.argsort(v)
    v, j = v[order], j[order]
    vu, inv = np.unique(v, return_inverse=True)
    if len(vu) != len(v):
        j = np.bincount(inv, weights=j) / np.maximum(np.bincount(inv), 1)
        v = vu

    base = compute_jv_parameters(v, j, pin_mw_cm2)
    if not np.isfinite(base["Jsc"]) or not np.isfinite(base["Voc"]):
        out["message"] = "no photovoltaic response (Jsc/Voc undefined)"
        return out
    sign = -1.0 if float(np.interp(0.0, v, j)) < 0 else 1.0
    jw = sign * j
    jsc, voc = base["Jsc"], base["Voc"]
    rs0 = base["Rs"] if np.isfinite(base["Rs"]) and base["Rs"] > 0 else 1.0
    rsh0 = base["Rsh"] if np.isfinite(base["Rsh"]) and base["Rsh"] > 0 else 1e4
    rs0 = float(np.clip(rs0, 1e-2, 1e2))
    rsh0 = float(np.clip(rsh0, 10.0, 1e7))
    vt = thermal_voltage(temperature_k)

    # fit only the region that carries information about the diode: from
    # the most negative bias up to a little beyond Voc
    m = v <= voc + 0.15
    vf, jf = v[m], jw[m]
    scale = max(jsc, 1e-6)

    def residual(theta):
        jph, j0, n, rs, rsh = 10 ** theta[0], 10 ** theta[1], theta[2], 10 ** theta[3], 10 ** theta[4]
        with np.errstate(all="ignore"):
            model = single_diode_current(vf, jph, j0, n, rs, rsh, temperature_k)
        r = (model - jf) / scale
        r[~np.isfinite(r)] = 10.0
        return r

    lo = [math.log10(0.5 * jsc), -25.0, 0.5, -3.0, 0.0]
    hi = [math.log10(1.5 * jsc), 0.0, 6.0, 3.0, 9.0]
    best = None
    for n0 in (1.0, 1.5, 2.0):
        j0_0 = jsc / max(math.expm1(voc / (n0 * vt)), 1e-300)
        theta0 = [math.log10(jsc), math.log10(max(j0_0, 1e-25)), n0,
                  math.log10(rs0), math.log10(rsh0)]
        theta0 = [min(max(t, l), h) for t, l, h in zip(theta0, lo, hi)]
        try:
            res = least_squares(residual, theta0, bounds=(lo, hi), method="trf",
                                x_scale="jac", max_nfev=4000)
        except Exception as exc:  # noqa: BLE001
            out["message"] = str(exc)
            continue
        if best is None or res.cost < best.cost:
            best = res
    if best is None:
        return out

    jph, j0, n, rs, rsh = 10 ** best.x[0], 10 ** best.x[1], best.x[2], 10 ** best.x[3], 10 ** best.x[4]
    y_fit = sign * single_diode_current(v, jph, j0, n, rs, rsh, temperature_k)
    resid = sign * y_fit - jw
    ss_tot = float(np.sum((jw - jw.mean()) ** 2))
    out.update(Jph=float(jph), J0=float(j0), n=float(n), Rs=float(rs), Rsh=float(rsh),
               R2=1.0 - float(np.sum(resid ** 2)) / ss_tot if ss_tot > 0 else float("nan"),
               RMSE=float(np.sqrt(np.mean(resid ** 2))), cost=float(best.cost),
               success=bool(best.success), message=str(best.message),
               y_fit=y_fit, voltage=v)
    return out


# =========================
# Scan direction and hysteresis
# =========================
def read_jv_curve(file_path: str, area_cm2: Optional[float] = None):
    """Return (V, J) of one source-meter file in the order measured, without
    the duplicate-voltage averaging that `parse_jv_file` performs. Needed to
    separate forward and reverse sweeps."""
    try:
        lines = _textio.read_text(file_path).splitlines(keepends=True)
    except Exception:
        return np.array([]), np.array([])
    factor = current_conversion_factor(area_cm2)
    start = next((i + 1 for i, ln in enumerate(lines) if "Vmeas" in ln and "Imeas" in ln), None)
    if start is None:
        return np.array([]), np.array([])
    v, j = [], []
    for ln in lines[start:]:
        parts = ln.split("\t")
        if len(parts) < 2:
            continue
        try:
            vv, ii = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if -3 <= vv <= 3:
            v.append(vv)
            j.append(ii * factor)
    return np.asarray(v, dtype=float), np.asarray(j, dtype=float)


def split_scan_directions(voltage, current_density, min_points: int = 5) -> List[Dict[str, Any]]:
    """Split a sweep (in measured order) into monotonic segments.

    Returns a list of {"direction": "forward" | "reverse", "v", "j"}; a
    forward segment goes from low to high voltage (Jsc -> Voc). Segments
    shorter than `min_points` are dropped.
    """
    v = np.asarray(voltage, dtype=float)
    j = np.asarray(current_density, dtype=float)
    if len(v) < min_points:
        return []
    dv = np.diff(v)
    sgn = np.sign(dv)
    # carry the previous direction across repeated voltages
    for i in range(1, len(sgn)):
        if sgn[i] == 0:
            sgn[i] = sgn[i - 1]
    segments, start = [], 0
    for i in range(1, len(sgn)):
        if sgn[i] != 0 and sgn[i - 1] != 0 and sgn[i] != sgn[i - 1]:
            segments.append((start, i + 1))
            start = i
    segments.append((start, len(v)))
    out = []
    for s, e in segments:
        if e - s < min_points:
            continue
        direction = "forward" if v[e - 1] > v[s] else "reverse"
        out.append({"direction": direction, "v": v[s:e].copy(), "j": j[s:e].copy()})
    return out


def hysteresis_index(pce_reverse: float, pce_forward: float) -> float:
    """HI = (PCE_rev - PCE_fwd) / PCE_rev, in percent (Snaith et al., JPCL 5,
    1511 (2014)). Positive: the reverse (Voc -> Jsc) scan over-estimates."""
    if not (np.isfinite(pce_reverse) and np.isfinite(pce_forward)) or pce_reverse == 0:
        return float("nan")
    return 100.0 * (pce_reverse - pce_forward) / pce_reverse


def analyze_scan_hysteresis(voltage, current_density, pin_mw_cm2: float = STANDARD_IRRADIANCE_MW_CM2) -> Dict[str, Any]:
    """Per-direction photovoltaic parameters and the hysteresis index of a
    sweep measured in both directions. Keys: n_segments, forward, reverse
    (parameter dicts or None), HI (%), dVoc, dJsc, dFF (reverse - forward)."""
    segs = split_scan_directions(voltage, current_density)
    fwd = next((s for s in segs if s["direction"] == "forward"), None)
    rev = next((s for s in segs if s["direction"] == "reverse"), None)
    res: Dict[str, Any] = {"n_segments": len(segs), "forward": None, "reverse": None,
                           "HI": float("nan"), "dVoc": float("nan"), "dJsc": float("nan"),
                           "dFF": float("nan")}
    if fwd is not None:
        res["forward"] = compute_jv_parameters(fwd["v"], fwd["j"], pin_mw_cm2)
    if rev is not None:
        res["reverse"] = compute_jv_parameters(rev["v"], rev["j"], pin_mw_cm2)
    if res["forward"] and res["reverse"]:
        f, r = res["forward"], res["reverse"]
        res["HI"] = hysteresis_index(r["PCE"], f["PCE"])
        for key, name in (("Voc", "dVoc"), ("Jsc", "dJsc"), ("FF", "dFF")):
            res[name] = float(r[key] - f[key]) if np.isfinite(r[key]) and np.isfinite(f[key]) else float("nan")
    return res


def jsc_mismatch(jsc_jv: float, jsc_eqe: float) -> float:
    """Relative difference (%) between the J-V short-circuit current density
    and the AM1.5G-integrated EQE value: (Jsc_JV - Jsc_EQE) / Jsc_EQE. Values
    beyond about +-5% point to spectral mismatch, an area error or
    light-intensity miscalibration."""
    if not (np.isfinite(jsc_jv) and np.isfinite(jsc_eqe)) or jsc_eqe == 0:
        return float("nan")
    return 100.0 * (jsc_jv - jsc_eqe) / jsc_eqe
