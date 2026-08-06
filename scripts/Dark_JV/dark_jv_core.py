# dark_jv_core.py - Dark J-V Curve Analysis Core Logic
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

# =========================
# Constants & Settings
# =========================
DEFAULT_CELL_AREA_CM2 = 0.04
KT_Q_298K = 0.025693  # thermal voltage kT/q at 298.15 K [V]


def _load_cell_area_cm2() -> float:
    """Read 'cell_area_cm2' from physisfera_config.json (project root)."""
    try:
        cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "physisfera_config.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            area = float(json.load(f).get("cell_area_cm2", DEFAULT_CELL_AREA_CM2))
        return area if area > 0 else DEFAULT_CELL_AREA_CM2
    except Exception:
        return DEFAULT_CELL_AREA_CM2


CELL_AREA_CM2 = _load_cell_area_cm2()
CURRENT_CONVERSION_FACTOR = -1000.0 / CELL_AREA_CM2


# =========================
# Dark-diode analysis
# =========================
def analyze_dark_diode(voltage, j_abs, temperature_k: float = 298.15) -> Dict[str, float]:
    """
    Extract diode parameters from a dark |J|-V curve (J in mA/cm^2).

      - Rsh_dark [Ohm cm^2]: ohmic (dV/dJ) slope in the low-bias region |V| <= 0.15 V.
      - n (ideality) and J0 [mA/cm^2]: from ln(J) = ln(J0) + V/(n*kT/q), fitted in the
        forward-bias exponential region. The window is auto-selected as the sliding
        0.25 V segment (V >= 0.15 V) with the highest linearity (R^2).

    Returns dict with keys: n, J0_mA_cm2, Rsh_dark_Ohm_cm2, fit_R2, fit_Vmin, fit_Vmax.
    """
    out = {"n": float("nan"), "J0_mA_cm2": float("nan"),
           "Rsh_dark_Ohm_cm2": float("nan"), "fit_R2": float("nan"),
           "fit_Vmin": float("nan"), "fit_Vmax": float("nan")}

    v = np.asarray(voltage, dtype=float)
    j = np.abs(np.asarray(j_abs, dtype=float))
    ok = np.isfinite(v) & np.isfinite(j)
    v, j = v[ok], j[ok]
    if len(v) < 8:
        return out
    order = np.argsort(v)
    v, j = v[order], j[order]

    kt_q = 1.380649e-23 * temperature_k / 1.602176634e-19

    # --- shunt resistance from low-bias ohmic slope ---
    m_lo = np.abs(v) <= 0.15
    if int(np.sum(m_lo)) >= 3:
        try:
            # J [mA/cm^2] vs V: slope in mA cm^-2 V^-1 -> Rsh = 1000/slope [Ohm cm^2]
            sl = np.polyfit(v[m_lo], np.sign(v[m_lo]) * j[m_lo], 1)[0]
            if sl > 1e-12:
                out["Rsh_dark_Ohm_cm2"] = float(1000.0 / sl)
        except Exception:
            pass

    # --- ideality factor: best sliding window on ln(J) vs V ---
    m_fw = (v >= 0.15) & (j > 0)
    vf, jf = v[m_fw], j[m_fw]
    if len(vf) >= 6:
        ln_j = np.log(jf)
        best = None
        win = 0.25
        starts = np.arange(vf.min(), max(vf.max() - win, vf.min()) + 1e-9, 0.02)
        for s in starts:
            m = (vf >= s) & (vf <= s + win)
            if int(np.sum(m)) < 5:
                continue
            xw, yw = vf[m], ln_j[m]
            try:
                slope, intercept = np.polyfit(xw, yw, 1)
            except Exception:
                continue
            if slope <= 0:
                continue
            yhat = slope * xw + intercept
            ss_tot = float(np.sum((yw - yw.mean()) ** 2))
            r2 = 1 - float(np.sum((yw - yhat) ** 2)) / ss_tot if ss_tot > 0 else 0.0
            n_val = 1.0 / (kt_q * slope)
            # physically meaningful ideality only
            if 0.5 <= n_val <= 10 and (best is None or r2 > best[0]):
                best = (r2, n_val, math.exp(intercept), float(xw.min()), float(xw.max()))
        if best is not None:
            out["fit_R2"], out["n"], out["J0_mA_cm2"], out["fit_Vmin"], out["fit_Vmax"] = best

    return out


def natural_sort_key(s):
    """Natural sort key for strings containing numbers (e.g., 2k, 2.5k, 3k)."""
    def convert(text):
        if text.replace('.', '', 1).isdigit():
            return float(text)
        return text.lower()
    return [convert(c) for c in re.split(r'(\d+\.?\d*)', str(s))]

@dataclass
class DarkJVSettings:
    x_min: float = -1.5
    x_max: float = 1.5
    y_min: float = 1e-5  # Original current value
    y_max: float = 100.0 # Original current value


# =========================
# Data Parsing
# =========================
def parse_dark_jv_file(file_path: str) -> Tuple[Optional[Dict], List[Dict]]:
    """
    Parse a single Dark JV text file.
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

    # For Dark JV, we don't need Voc, Jsc, FF, PCE - just file name and RShunt
    # Find header line for summary data
    header_line = None
    for i, line in enumerate(data):
        if "RShunt ohms" in line:
            header_line = i
            break

    if header_line is not None:
        try:
            headers = data[header_line].split("\t")
            values = data[header_line + 1].split("\t")
            # Locate the RShunt column by header name instead of a hardcoded index
            r_idx = next((k for k, hcell in enumerate(headers) if "RShunt" in hcell), 11)
            rshunt = format(float(values[r_idx]), ".2f") if len(values) > r_idx else "non"
        except (ValueError, IndexError, StopIteration):
            rshunt = "non"

        summary_data = {
            "Filename": display_name,
            "RShunt (ohms)": rshunt
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
                            # Dark current: use absolute value
                            current_value = abs(float(values[1]) * CURRENT_CONVERSION_FACTOR)
                            voltage_data.append({
                                "Voltage(V)": round(voltage_value, 4),
                                "Sample": display_name,
                                "Current": current_value
                            })
                    except (ValueError, IndexError):
                        pass

    # Fallback: files without the "RShunt ohms" summary line still carry a
    # valid dark curve - register the sample so diode analysis can proceed.
    if summary_data is None and voltage_data:
        summary_data = {
            "Filename": display_name,
            "RShunt (ohms)": "non",
        }

    return summary_data, voltage_data


def process_dark_jv_directory(directory_path: str, progress_callback=None) -> Dict[str, Any]:
    """
    Process all Dark JV text files in a directory.
    Returns dictionary with all processed data (simplified - no best performance logic).
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

        summary, v_data = parse_dark_jv_file(file_path)
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

    # Sort combined_data columns using natural sort
    other_cols = [c for c in combined_data.columns if c != 'Voltage(V)']
    sorted_cols = sorted(other_cols, key=natural_sort_key)
    combined_data = combined_data[['Voltage(V)'] + sorted_cols]

    # NOTE: do NOT round dark currents to fixed decimals. The data spans many
    # decades (1e-5 ... 100 mA/cm^2) and is displayed on a log axis; rounding to
    # 2 decimals destroyed everything below ~0.005 mA/cm^2 (low-bias region).
    # Full precision is kept for plotting, export, and diode fitting.

    # --- Diode analysis per sample: ideality n, saturation J0, dark Rsh ---
    diode_rows = []
    v_arr = combined_data['Voltage(V)'].to_numpy(dtype=float)
    for col in combined_data.columns:
        if col == 'Voltage(V)':
            continue
        d = analyze_dark_diode(v_arr, combined_data[col].to_numpy(dtype=float))
        diode_rows.append({
            "Filename": col,
            "Ideality n": round(d["n"], 3) if np.isfinite(d["n"]) else np.nan,
            "J0 (mA/cm2)": float(f'{d["J0_mA_cm2"]:.3e}') if np.isfinite(d["J0_mA_cm2"]) else np.nan,
            "Rsh_dark (Ohm cm2)": round(d["Rsh_dark_Ohm_cm2"], 1) if np.isfinite(d["Rsh_dark_Ohm_cm2"]) else np.nan,
            "n fit R2": round(d["fit_R2"], 4) if np.isfinite(d["fit_R2"]) else np.nan,
            "n fit range (V)": (f'{d["fit_Vmin"]:.2f}-{d["fit_Vmax"]:.2f}'
                                if np.isfinite(d["fit_Vmin"]) else ""),
        })
    diode_df = pd.DataFrame(diode_rows)
    if not diode_df.empty and not summary_df.empty:
        summary_df = summary_df.merge(diode_df, on="Filename", how="left")

    # Calculate data range for auto-scaling
    current_cols = [c for c in combined_data.columns if c != 'Voltage(V)']
    if current_cols:
        all_currents = combined_data[current_cols].values.flatten()
        all_currents = all_currents[~np.isnan(all_currents)]  # Remove NaN
        all_currents = all_currents[all_currents > 0]  # Only positive values for log scale

        if len(all_currents) > 0:
            data_min = np.min(all_currents)
            data_max = np.max(all_currents)
            # Add margin for better visualization (0.1x to 10x)
            y_min_auto = data_min * 0.1
            y_max_auto = data_max * 10.0
        else:
            y_min_auto = 1e-6
            y_max_auto = 100.0
    else:
        y_min_auto = 1e-6
        y_max_auto = 100.0

    return {
        "combined_data": combined_data,
        "summary_df": summary_df,
        "total_files": len(txt_files),
        "y_min_auto": y_min_auto,
        "y_max_auto": y_max_auto
    }


def save_to_excel(data: Dict[str, Any], excel_path: str) -> str:
    """Save processed data to Excel.

    Returns the path actually written ('' on failure). If the target file is
    locked (open in Excel), writes '<name>_HHMMSS.xlsx' instead of silently
    leaving stale data behind.
    """
    def _write(path):
        with pd.ExcelWriter(path, engine="openpyxl", mode="w") as writer:
            data["combined_data"].to_excel(writer, sheet_name="CombinedData", index=False)
            data["summary_df"].to_excel(writer, sheet_name="SummaryTable", index=False)
        return path

    try:
        return _write(excel_path)
    except PermissionError:
        alt = f"{os.path.splitext(excel_path)[0]}_{time.strftime('%H%M%S')}.xlsx"
        try:
            return _write(alt)
        except Exception as e:
            print(f"Excel save error (fallback): {e}")
            return ""
    except Exception as e:
        print(f"Excel save error: {e}")
        return ""


# =========================
# Matplotlib Plotting (LOG SCALE)
# =========================
try:
    from scripts.common.plot_interactions import smart_legend
except Exception:
    def smart_legend(ax, loc="upper left", **_k):
        try:
            return ax.legend(loc=loc, fontsize=9, framealpha=0.9)
        except Exception:
            return None

def create_dark_iv_plot(ax, combined_data: pd.DataFrame, settings: DarkJVSettings):
    """Create Dark I-V curve plot on given matplotlib axes with LOG Y-AXIS."""
    ax.clear()

    if combined_data.empty:
        ax.text(0.5, 0.5, "No Data", ha='center', va='center', fontsize=14, color='#888888')
        return

    # Plot each sample
    voltage_col = 'Voltage(V)'
    sample_cols = [col for col in combined_data.columns if col != voltage_col]

    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
              '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

    for i, col in enumerate(sample_cols):
        color = colors[i % len(colors)]
        voltage = combined_data[voltage_col]
        current = combined_data[col]

        # Use semilogy for log scale (original values, not log-transformed)
        ax.semilogy(voltage, current, '-', linewidth=2, label=col, color=color)

    # Style - white labels
    ax.set_xlabel("Voltage (V)", fontsize=12, color='white')
    ax.set_ylabel("Current Density (mA/cm²)", fontsize=12, color='white')
    ax.set_xlim(settings.x_min, settings.x_max)
    ax.set_ylim(settings.y_min, settings.y_max)

    # Reference lines
    ax.axhline(y=1, color='#555555', linewidth=0.8, linestyle='-')
    ax.axvline(x=0, color='#555555', linewidth=0.8, linestyle='-')

    # Grid
    ax.grid(True, which='both', alpha=0.3, linestyle='--')

    # Legend - overflow-safe (long sample names / many samples previously
    # covered the whole plot)
    if sample_cols:
        smart_legend(ax)


def create_single_dark_iv_plot(ax, combined_data: pd.DataFrame, sample_name: str, settings: DarkJVSettings):
    """Create Dark I-V curve plot for a single selected sample with LOG Y-AXIS."""
    ax.clear()

    if combined_data.empty:
        ax.text(0.5, 0.5, "No Data", ha='center', va='center', fontsize=14, color='#888888')
        return

    voltage_col = 'Voltage(V)'

    # Find matching column
    matching_col = None
    for col in combined_data.columns:
        if col != voltage_col and col == sample_name:
            matching_col = col
            break

    if matching_col is None:
        ax.text(0.5, 0.5, f"Sample '{sample_name}' not found",
                ha='center', va='center', fontsize=14, color='#888888')
        return

    voltage = combined_data[voltage_col]
    current = combined_data[matching_col]

    # Plot selected sample with semilogy
    ax.semilogy(voltage, current, '-', linewidth=2.5, label=matching_col, color='#3182F6')

    # Style - white labels
    ax.set_xlabel("Voltage (V)", fontsize=12, color='white')
    ax.set_ylabel("Current Density (mA/cm²)", fontsize=12, color='white')
    ax.set_xlim(settings.x_min, settings.x_max)
    ax.set_ylim(settings.y_min, settings.y_max)
    ax.set_title(f"{sample_name}", fontsize=14, color='white')

    # Reference lines
    ax.axhline(y=1, color='#555555', linewidth=0.8, linestyle='-')
    ax.axvline(x=0, color='#555555', linewidth=0.8, linestyle='-')

    # Grid
    ax.grid(True, which='both', alpha=0.3, linestyle='--')

    # Legend - overflow-safe
    smart_legend(ax)


def create_multi_dark_iv_plot(ax, combined_data: pd.DataFrame, sample_names: List[str], settings: DarkJVSettings):
    """Create Dark I-V curve plot for multiple selected samples with LOG Y-AXIS."""
    ax.clear()

    if combined_data.empty:
        ax.text(0.5, 0.5, "No Data", ha='center', va='center', fontsize=14, color='#888888')
        return

    voltage_col = 'Voltage(V)'

    colors = ['#3182F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6',
              '#EC4899', '#14B8A6', '#F97316', '#6366F1', '#84CC16']

    plotted = False
    for i, sample_name in enumerate(sample_names):
        # Find matching column
        matching_col = None
        for col in combined_data.columns:
            if col != voltage_col and col == sample_name:
                matching_col = col
                break

        if matching_col is not None:
            color = colors[i % len(colors)]
            voltage = combined_data[voltage_col]
            current = combined_data[matching_col]

            ax.semilogy(voltage, current, '-', linewidth=2, label=matching_col, color=color)
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
    ax.axhline(y=1, color='#555555', linewidth=0.8, linestyle='-')
    ax.axvline(x=0, color='#555555', linewidth=0.8, linestyle='-')

    # Grid
    ax.grid(True, which='both', alpha=0.3, linestyle='--')

    # Legend - overflow-safe
    smart_legend(ax)


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


def plot_dark_iv_to_origin(origin, combined_data: pd.DataFrame, settings: DarkJVSettings, log_callback=None):
    """Plot Dark I-V curve to Origin with LOG Y-AXIS."""
    if combined_data.empty:
        if log_callback:
            log_callback("CombinedData is empty")
        return

    if log_callback:
        log_callback("Creating Origin Dark I-V plot...")

    columns = combined_data.columns.tolist()
    num_cols = len(columns)

    wb_name = origin.CreatePage(2, "DarkJV_Data", "Origin")
    origin.Execute(f"page.active$ = {wb_name};")
    origin.Execute(f"wks.ncols = {num_cols};")

    # X column (Voltage)
    origin.Execute(f'wks.col1.lname$ = "{columns[0]}";')
    origin.Execute("wks.col1.type = 4;")
    origin.Execute('wks.col1.units$ = "V";')

    x_data = combined_data.iloc[:, 0].fillna('').tolist()
    origin.PutWorksheet(f"[{wb_name}]Sheet1", x_data, 0, 0)

    # Y columns (Current - original values, NOT log-transformed)
    for i in range(1, num_cols):
        col_idx = i + 1
        col_name = columns[i]
        origin.Execute(f'wks.col{col_idx}.lname$ = "{col_name}";')
        origin.Execute(f"wks.col{col_idx}.type = 1;")

        y_data = combined_data.iloc[:, i].fillna('').tolist()
        origin.PutWorksheet(f"[{wb_name}]Sheet1", y_data, 0, i)

    if log_callback:
        log_callback("Data written to worksheet")

    # Create plot (Line plot)
    origin.Execute(f"plotxy iy:=[{wb_name}]Sheet1!(1,2:{num_cols}) plot:=200;")

    # Style
    _customize_dark_iv_graph(origin, settings)

    if log_callback:
        log_callback("Origin Dark I-V plot complete")


def _customize_dark_iv_graph(origin, settings: DarkJVSettings):
    """Apply styling to Dark I-V graph in Origin."""
    # Y-axis labels
    origin.Execute("label -yl Current Density (mA/cm\\+(2));")

    # Font sizes
    origin.Execute("xb.fsize = 40;")
    origin.Execute("yl.fsize = 40;")

    # Y-axis: LOG SCALE (must be set before other layer properties)
    origin.Execute("layer.y.type = 2;")

    # Axis increments
    origin.Execute("layer.x.inc = 0.5;")

    # Axis label point sizes
    origin.Execute("layer.y.label.pt = 30;")
    origin.Execute("layer.x.label.pt = 30;")

    # Show all axes (box)
    origin.Execute("layer.x.showAxes = 3;")
    origin.Execute("layer.x.showLabels = 1;")
    origin.Execute("layer.y.showAxes = 3;")
    origin.Execute("layer.y.showLabels = 1;")
    origin.Execute("layer.x2.ticks = 0;")
    origin.Execute("layer.y2.ticks = 0;")

    # Hide top and right axis ticks
    origin.Execute("layer.x2.ticks = 0;")
    origin.Execute("layer.y2.ticks = 0;")

    # Axis range
    origin.Execute(f"layer.x.from = {settings.x_min};")
    origin.Execute(f"layer.x.to = {settings.x_max};")
    origin.Execute(f"layer.y.from = {settings.y_min};")
    origin.Execute(f"layer.y.to = {settings.y_max};")

    # Reference lines
    origin.Execute("draw -n RefLineX -l -v 0;")

    # Legend
    origin.Execute("legend -r;")

    # Line thickness (ensure plot 1 is active)
    origin.Execute("layer -p 1;")
    origin.Execute("set %C -w 1500;")

    # Refresh
    origin.Execute("doc -uw;")
