# jv_core.py - J-V Curve Analysis Core Logic (No UI)
import os
import re
import math
import time
import json
import subprocess
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Any

import pandas as pd
import numpy as np
import openpyxl
from openpyxl.styles import PatternFill

# =========================
# Constants & Settings
# =========================
DEFAULT_CELL_AREA_CM2 = 0.04       # active area used historically (factor -25000)
STANDARD_IRRADIANCE_MW_CM2 = 100.0  # AM1.5G, 1 sun


def _load_cell_area_cm2() -> float:
    """Read 'cell_area_cm2' from physisfera_config.json (project root).
    Falls back to the historical default 0.04 cm^2."""
    try:
        cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "physisfera_config.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            area = float(json.load(f).get("cell_area_cm2", DEFAULT_CELL_AREA_CM2))
        return area if area > 0 else DEFAULT_CELL_AREA_CM2
    except Exception:
        return DEFAULT_CELL_AREA_CM2


CELL_AREA_CM2 = _load_cell_area_cm2()
# measured current [A] * factor -> current density [mA/cm^2] (sign flip: SMU convention)
CURRENT_CONVERSION_FACTOR = -1000.0 / CELL_AREA_CM2


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


def natural_sort_key(s):
    """Natural sort key for strings containing numbers (e.g., 2k, 2.5k, 3k)."""
    def convert(text):
        if text.replace('.', '', 1).isdigit():
            return float(text)
        return text.lower()
    return [convert(c) for c in re.split(r'(\d+\.?\d*)', str(s))]

@dataclass
class JVSettings:
    x_min: float = -0.2
    x_max: float = 1.0
    y_min: float = -25.0
    y_max: float = 5.0


# =========================
# Data Parsing
# =========================
def parse_jv_file(file_path: str) -> Tuple[Optional[Dict], List[Dict]]:
    """
    Parse a single JV text file.
    Returns: (summary_data, voltage_data_list)
    """
    try:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = f.readlines()
        except UnicodeDecodeError:
            with open(file_path, 'r', encoding='cp949') as f:
                data = f.readlines()
    except Exception as e:
        return None, []

    filename = os.path.basename(file_path)
    # Remove only the .txt extension (preserve decimal numbers like 2.5k, 3.0k)
    if filename.lower().endswith('.txt'):
        display_name = filename[:-4]
    else:
        # For other extensions, remove only the last extension
        last_dot = filename.rfind('.')
        display_name = filename[:last_dot] if last_dot > 0 else filename
    # Remove date-time pattern like "2026-01-20 18-35-48" at the end
    display_name = re.sub(r'\s+\d{4}-\d{2}-\d{2}\s+\d{2}-\d{2}-\d{2}$', '', display_name)
    # Remove trailing dot after cell number (e.g., "01." -> "01")
    display_name = re.sub(r'\.$', '', display_name)
    # Handle leading file numbering if present (e.g., "01. sample name")
    display_name = re.sub(r'^\d+\.\s+', '', display_name)
    display_name = display_name.replace('_', ' ')
    # Convert temperature format (e.g., "110C" -> "110°C")
    display_name = re.sub(r'(\d+)C\b', r'\1°C', display_name)

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
                            current_value = float(values[1]) * CURRENT_CONVERSION_FACTOR
                            voltage_data.append({
                                "Voltage(V)": round(voltage_value, 4),
                                "Sample": display_name,
                                "Current": current_value
                            })
                    except (ValueError, IndexError):
                        pass

    # Fallback: files exported without the instrument summary block still carry
    # a valid J-V curve. Previously such folders aborted with "No valid data
    # found"; register the sample so the curve-derived analysis can proceed.
    if summary_data is None and voltage_data:
        summary_data = {
            "Filename": display_name,
            "Voc V": "non",
            "Jsc mA/cm2": "non",
            "Fill Factor": "non",
            "PCE (%)": "non",
        }

    return summary_data, voltage_data


def process_jv_directory(directory_path: str, progress_callback=None) -> Dict[str, Any]:
    """
    Process all JV text files in a directory.
    Returns dictionary with all processed data.
    """
    # Accept a single folder or a list of folders (JV_Analysis.exe '+ Add'
    # folder-comparison). Duplicate display names across folders get a
    # ' (2)', ' (3)'... suffix instead of being silently averaged together.
    dirs = [directory_path] if isinstance(directory_path, str) else [d for d in directory_path if d]
    file_pairs = []
    for d in dirs:
        try:
            for f in sorted(os.listdir(d)):
                if f.lower().endswith(".txt"):
                    file_pairs.append((d, f))
        except Exception:
            continue

    if not file_pairs:
        return {"error": "No text files found"}

    voltage_data = []
    table_data_list = []
    seen_names: Dict[str, int] = {}

    for idx, (d, filename) in enumerate(file_pairs):
        file_path = os.path.join(d, filename)

        if progress_callback:
            progress_callback(idx, filename, len(file_pairs))

        summary, v_data = parse_jv_file(file_path)
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

    # Helper functions for grouping
    def get_base_name(filename):
        return re.sub(r'\d+$', '', filename.strip())

    def get_number(filename):
        match = re.search(r'(\d+)$', filename.strip())
        return int(match.group(1)) if match else 0

    summary_df['Base_Name'] = summary_df['Filename'].apply(get_base_name)
    summary_df['Number'] = summary_df['Filename'].apply(get_number)

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
                new_columns[col] = re.sub(r'\d+$', '', col.strip())
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
    v_arr = combined_data['Voltage(V)'].to_numpy(dtype=float)
    for col in combined_data.columns:
        if col == 'Voltage(V)':
            continue
        p = compute_jv_parameters(v_arr, combined_data[col].to_numpy(dtype=float))
        curve_rows.append({
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
        })
    curve_analysis = pd.DataFrame(curve_rows)

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
        "cell_area_cm2": CELL_AREA_CM2,
        "total_files": len(txt_files)
    }


def save_to_excel(data: Dict[str, Any], excel_path: str) -> str:
    """Save processed data to Excel.

    Returns the path actually written ('' on failure). If the target file is
    locked (typically: the user still has it open in Excel - previously the
    save FAILED SILENTLY and the file kept stale data), a timestamped
    '<name>_HHMMSS.xlsx' is written next to it instead.
    """
    try:
        return _save_to_excel_impl(data, excel_path)
    except PermissionError:
        alt = f"{os.path.splitext(excel_path)[0]}_{time.strftime('%H%M%S')}.xlsx"
        try:
            return _save_to_excel_impl(data, alt)
        except Exception as e:
            print(f"Excel save error (fallback): {e}")
            return ""
    except Exception as e:
        print(f"Excel save error: {e}")
        return ""


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
        ax.text(0.5, 0.5, "No Data", ha='center', va='center', fontsize=14, color='#888888')
        return

    # Plot each sample
    voltage_col = 'Voltage (V)'
    sample_cols = [col for col in best_combined_data.columns if col != voltage_col]

    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
              '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

    for i, col in enumerate(sample_cols):
        color = colors[i % len(colors)]
        ax.plot(best_combined_data[voltage_col], best_combined_data[col],
                '-', linewidth=2, label=col, color=color)

    # Style - white labels
    ax.set_xlabel("Voltage (V)", fontsize=12, color='white')
    ax.set_ylabel("Current Density (mA/cm²)", fontsize=12, color='white')
    ax.set_xlim(settings.x_min, settings.x_max)
    ax.set_ylim(settings.y_min, settings.y_max)

    # Reference lines
    ax.axhline(y=0, color='#555555', linewidth=0.8, linestyle='-')
    ax.axvline(x=0, color='#555555', linewidth=0.8, linestyle='-')

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
        ax.text(0.5, 0.5, "No Data", ha='center', va='center', fontsize=14, color='#888888')
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
                ha='center', va='center', fontsize=14, color='#888888')
        return

    # Plot selected sample
    ax.plot(best_combined_data[voltage_col], best_combined_data[matching_col],
            '-', linewidth=2.5, label=matching_col, color='#3182F6')

    # Style - white labels
    ax.set_xlabel("Voltage (V)", fontsize=12, color='white')
    ax.set_ylabel("Current Density (mA/cm²)", fontsize=12, color='white')
    ax.set_xlim(settings.x_min, settings.x_max)
    ax.set_ylim(settings.y_min, settings.y_max)
    ax.set_title(f"{sample_name}", fontsize=14, color='white')

    # Reference lines
    ax.axhline(y=0, color='#555555', linewidth=0.8, linestyle='-')
    ax.axvline(x=0, color='#555555', linewidth=0.8, linestyle='-')

    # Grid
    ax.grid(True, alpha=0.3, linestyle='--')

    # Legend - overflow-safe
    smart_legend(ax)


def create_multi_iv_plot(ax, best_combined_data: pd.DataFrame, sample_names: List[str], settings: JVSettings):
    """Create I-V curve plot for multiple selected samples."""
    ax.clear()

    if best_combined_data.empty:
        ax.text(0.5, 0.5, "No Data", ha='center', va='center', fontsize=14, color='#888888')
        return

    voltage_col = 'Voltage (V)'

    colors = ['#3182F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6',
              '#EC4899', '#14B8A6', '#F97316', '#6366F1', '#84CC16']

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
                ha='center', va='center', fontsize=14, color='#888888')
        return

    # Style - white labels
    ax.set_xlabel("Voltage (V)", fontsize=12, color='white')
    ax.set_ylabel("Current Density (mA/cm²)", fontsize=12, color='white')
    ax.set_xlim(settings.x_min, settings.x_max)
    ax.set_ylim(settings.y_min, settings.y_max)

    if len(sample_names) <= 3:
        ax.set_title(", ".join(sample_names), fontsize=12, color='white')
    else:
        ax.set_title(f"Multiple Samples ({len(sample_names)})", fontsize=12, color='white')

    # Reference lines
    ax.axhline(y=0, color='#555555', linewidth=0.8, linestyle='-')
    ax.axvline(x=0, color='#555555', linewidth=0.8, linestyle='-')

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
        ax.text(0.5, 0.5, "No Data", ha='center', va='center', fontsize=14, color='#888888')
        return

    # Filter columns if samples are selected
    columns_to_plot = box_df.columns.tolist()
    if selected_samples:
        # Match selected sample names with box_df columns
        columns_to_plot = [col for col in box_df.columns if col in selected_samples]
        if not columns_to_plot:
            ax.text(0.5, 0.5, "No matching samples", ha='center', va='center', fontsize=14, color='#888888')
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
        ax.text(0.5, 0.5, "No Valid Data", ha='center', va='center', fontsize=14, color='#888888')
        return

    # Create box plot
    # matplotlib renamed boxplot's 'labels' to 'tick_labels' in 3.9 and the old
    # name is scheduled for removal - support both
    try:
        bp = ax.boxplot(data_for_plot, tick_labels=labels, patch_artist=True)
    except TypeError:
        bp = ax.boxplot(data_for_plot, labels=labels, patch_artist=True)

    # Style boxes
    colors = ['#3182F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6']
    for i, (box, median) in enumerate(zip(bp['boxes'], bp['medians'])):
        box.set_facecolor(colors[i % len(colors)])
        box.set_alpha(0.7)
        median.set_color('white')
        median.set_linewidth(2)

    # Y-axis label - white color with display formatting
    display_labels = {
        "Voc V": "Voc (V)",
        "Jsc mA/cm2": "Jsc (mA/cm²)",
        "Fill Factor": "Fill Factor (%)",
        "PCE (%)": "PCE (%)"
    }
    ylabel = display_labels.get(param_name, param_name)
    ax.set_ylabel(ylabel, fontsize=11, color='white')

    # Rotate x labels
    ax.tick_params(axis='x', rotation=45, colors='#AAAAAA')
    ax.tick_params(axis='y', colors='#AAAAAA')
    ax.grid(True, axis='y', alpha=0.3, linestyle='--')


# =========================
# Origin Integration
# =========================
try:
    import win32com.client
    WIN32COM_AVAILABLE = True
except ImportError:
    WIN32COM_AVAILABLE = False


def connect_to_origin(origin_exe_path: str = "", log_callback=None) -> Optional[Any]:
    """Connect to Origin application."""
    if not WIN32COM_AVAILABLE:
        if log_callback:
            log_callback("pywin32 not installed")
        return None

    # Try existing instance
    try:
        origin = win32com.client.Dispatch("Origin.ApplicationSI")
        origin.Visible = 1
        if log_callback:
            log_callback("Connected to existing Origin")
        return origin
    except:
        pass

    # Launch new instance
    if origin_exe_path and os.path.exists(origin_exe_path):
        if log_callback:
            log_callback(f"Launching Origin: {origin_exe_path}")
        try:
            subprocess.Popen([origin_exe_path])
            for i in range(60):
                time.sleep(1)
                try:
                    origin = win32com.client.Dispatch("Origin.ApplicationSI")
                    origin.Visible = 1
                    if log_callback:
                        log_callback("New Origin instance started")
                    return origin
                except:
                    continue
            if log_callback:
                log_callback("Timeout: Origin connection failed")
        except Exception as e:
            if log_callback:
                log_callback(f"Origin launch error: {e}")
    else:
        if log_callback:
            log_callback(f"Origin path not found: {origin_exe_path}")

    return None


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
