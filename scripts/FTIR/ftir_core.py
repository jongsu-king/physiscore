"""
ftir_core.py - FTIR Analysis Core Logic
"""
import pandas as pd
import numpy as np
import os

from scripts.common.origin import WIN32COM_AVAILABLE, connect_to_origin
from scipy.signal import find_peaks
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except Exception:
    genai = None
    GENAI_AVAILABLE = False
import json
import re

def load_data(file_path, max_layers=10):
    try:
        if file_path.endswith('.xlsx'):
            df = pd.read_excel(file_path, header=0)
        else:
            try:
                df = pd.read_csv(file_path, header=0)
                if df.shape[1] < 2: df = pd.read_csv(file_path, sep='\t', header=0)
            except:
                df = pd.read_csv(file_path, sep='\t', header=None)

        df = df.apply(pd.to_numeric, errors='coerce').dropna()
        cols = df.shape[1]
        if cols < 2: raise ValueError("Data must have at least 2 columns")

        x_col = df.columns[0]
        wavenumbers = df[x_col].values

        layers_data = []
        # Iterate over min(number of data columns, max_layers)
        num_layers = min(cols - 1, max_layers)

        for i in range(num_layers):
            y_col = df.columns[i + 1]
            intensities = df[y_col].values

            header_text = str(y_col).strip()
            if "Unnamed" in header_text or header_text == "nan":
                sample_info = ""
            else:
                sample_info = header_text

            layers_data.append({
                "wavenumbers": wavenumbers,
                "intensities": intensities,
                "name": f"Layer {i+1}",
                "context": sample_info
            })
        return layers_data
    except Exception as e:
        raise e

def detect_peaks(wavenumbers, intensities):
    wavenumbers = np.asarray(wavenumbers)
    intensities = np.asarray(intensities)
    if intensities.size < 3:
        # empty/degenerate input (e.g. a file whose rows all failed to parse)
        return np.array([]), np.array([], dtype=int)
    data_range = intensities.max() - intensities.min()
    # Increased sensitivity: 2% -> 1% prominence
    peak_indices, _ = find_peaks(-intensities, prominence=data_range * 0.01)
    peaks = wavenumbers[peak_indices]
    return peaks, peak_indices

def analyze_with_gemini(api_key, model_name, context, peaks, peak_indices, intensities):
    if genai is None:
        raise RuntimeError("google-generativeai package is not installed. (pip install google-generativeai)")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    min_T, max_T = intensities.min(), intensities.max()
    range_T = max_T - min_T
    peak_details = []

    for idx, wn in zip(peak_indices, peaks):
        val = intensities[idx]
        rel_str = (max_T - val) / range_T if range_T != 0 else 0
        s_str = "Very Strong" if rel_str > 0.8 else "Strong" if rel_str > 0.5 else "Medium" if rel_str > 0.2 else "Weak"
        peak_details.append(f"{{Wavenumber: {wn:.1f}, Strength: {s_str}}}")

    prompt = f"""
    You are an expert in FTIR Spectroscopy. Analyze the following peaks.

    [Sample Context]
    {context}

    [Detected Peaks (cm-1)]
    {chr(10).join(peak_details)}

    [Task]
    Analyze peaks for FTIR assignment. Provide the description in **English**.
    Return JSON list: [{{ "wavenumber": float, "assignment": str, "material": str, "description": str, "confidence": str, "other_possibilities": str }}]
    """

    response = model.generate_content(prompt)
    clean = re.sub(r"```json|```", "", response.text).strip()
    results = []
    try:
        results = json.loads(clean)
    except:
        start = clean.find('[')
        end = clean.rfind(']') + 1
        if start != -1 and end != -1:
            try:
                results = json.loads(clean[start:end])
            except:
                pass

    if isinstance(results, list):
        for item in results:
            if "wavenumber" in item:
                try:
                    item["wavenumber"] = float(item["wavenumber"])
                except (ValueError, TypeError):
                    item["wavenumber"] = 0.0

    return results

def analyze_peak_shift(api_key, model_name, context, name_a, pa, name_b, pb):
    if genai is None:
        raise RuntimeError("google-generativeai package is not installed. (pip install google-generativeai)")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    shift = pb - pa
    prompt = f"""
    Context: {context}
    Compare (FTIR): {name_a} ({pa:.1f}) vs {name_b} ({pb:.1f})
    Shift: {shift:.2f}
    Explain chemical cause in English (Focus on FTIR). Provide a detailed explanation and a summary. Return JSON: {{ "shift_value": float, "shift_type": str, "cause": str, "detailed_explanation": str, "summary": str, "implication": str }}
    """
    response = model.generate_content(prompt)
    clean = re.sub(r"```json|```", "", response.text).strip()
    try:
        return json.loads(clean)
    except:
        start = clean.find('{')
        end = clean.rfind('}') + 1
        return json.loads(clean[start:end]) if start != -1 else {"error": "Parsing failed"}

def compare_spectra_with_gemini(api_key, model_name, context, name_a, peaks_a, ints_a, name_b, peaks_b, ints_b):
    if genai is None:
        raise RuntimeError("google-generativeai package is not installed. (pip install google-generativeai)")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)

    # Helper to format peak list (Top 10 strong peaks to save tokens)
    def format_peaks(peaks, intensities):
        # FTIR: Lower intensity (transmittance) means stronger absorption peak
        # Sort by intensity ascending
        if len(peaks) == 0: return "No peaks detected"

        sorted_indices = np.argsort(intensities)
        top_indices = sorted_indices[:10]

        desc = []
        for i in top_indices:
            desc.append(f"{peaks[i]:.1f}")
        return ", ".join(desc)

    p_str_a = format_peaks(peaks_a, ints_a)
    p_str_b = format_peaks(peaks_b, ints_b)

    prompt = f"""
    You are an expert in FTIR Spectroscopy. Compare the following two samples based on their major peaks.

    [Context]
    {context}

    [Sample A: {name_a}]
    Major Peaks (cm-1): {p_str_a}

    [Sample B: {name_b}]
    Major Peaks (cm-1): {p_str_b}

    [Task]
    Compare the spectral features. Identify significant differences (new peaks, shifts, missing peaks).
    Explain the chemical implications of these differences in **English**.

    Return JSON: {{ "summary": str, "differences": [str], "chemical_implications": str, "conclusion": str }}
    """
    response = model.generate_content(prompt)
    clean = re.sub(r"```json|```", "", response.text).strip()
    try:
        return json.loads(clean)
    except:
        start = clean.find('{')
        end = clean.rfind('}') + 1
        return json.loads(clean[start:end]) if start != -1 else {"error": "Parsing failed", "raw": response.text}

def save_all_layers_to_excel(file_path, layers):
    all_data = []
    for layer in layers:
        layer_name = layer.get('name', 'Unknown')
        context = layer.get('context', '')
        peak_data = layer.get('peak_data', {})

        if not peak_data: continue

        for wn, info in peak_data.items():
            row = {
                "Layer": layer_name,
                "Sample Info": context,
                "Wavenumber": info.get('wavenumber'),
                "Assignment": info.get('assignment'),
                "Material": info.get('material'),
                "Confidence": info.get('confidence'),
                "Description": info.get('description')
            }
            all_data.append(row)

    if not all_data: return False

    df = pd.DataFrame(all_data)
    cols = ["Layer", "Sample Info", "Wavenumber", "Assignment", "Material", "Confidence", "Description"]
    df = df[cols]
    df.to_excel(file_path, index=False)
    return True

# connect_to_origin lives in scripts/common/origin.py (imported above); all nine
# tools share one connection routine.


def plot_ftir_to_origin(origin, layers, colors=None, log_callback=None):
    """Plot FTIR spectra to Origin."""
    if not layers:
        if log_callback: log_callback("No layers to plot")
        return

    if log_callback: log_callback("Creating a single Origin FTIR plot for all layers...")

    # 1. Create a single workbook to hold all data
    wb_name = origin.CreatePage(2, "FTIR_Data", "Origin")
    origin.Execute(f"page.active$ = {wb_name};")
    num_layers = len(layers)
    origin.Execute(f"wks.ncols = {1 + num_layers};")

    # 2. X-axis setup (Wavenumber) - common to all layers
    origin.Execute(f'wks.col1.lname$ = "Wavenumber";')
    origin.Execute(f'wks.col1.units$ = "cm\\+(-1)";')
    origin.Execute(f'wks.col1.type = 4;') # 4 = X-axis type
    origin.PutWorksheet(f"[{wb_name}]Sheet1", layers[0]['wavenumbers'].tolist(), 0, 0)

    # 3. Insert Y-axis (transmittance) data for each layer
    for i, L in enumerate(layers):
        col_idx = i + 2
        display_name = L.get('context').strip() if L.get('context') and L.get('context').strip() else L.get('name')
        origin.Execute(f'wks.col{col_idx}.lname$ = "{display_name}";')
        origin.Execute(f'wks.col{col_idx}.type = 1;') # 1 = Y-axis type
        origin.PutWorksheet(f"[{wb_name}]Sheet1", L['intensities'].tolist(), 0, i + 1)

    # 4. Create a single graph window and plot all Y data
    gp_name = origin.CreatePage(3, "FTIR_Combined_Graph", "Origin")
    # Plot all remaining columns (Y) against the first column (X)
    origin.Execute(f"plotxy iy:=[{wb_name}]Sheet1!(1, 2:{1+num_layers}) plot:=200 o:=[{gp_name}]1!;")

    # 5. Styling and axis settings
    origin.Execute(f"win -a {gp_name};")

    for i in range(num_layers):
        origin.Execute(f"layer.plot = {i+1};")
        if colors:
            c_hex = colors[i % len(colors)]
            origin.Execute(f"set %C -cl color(\"{c_hex}\");")
        origin.Execute("set %C -w 1500;") # line width 1.5

    origin.Execute("xb.fsize = 40; yl.fsize = 40;")
    origin.Execute("layer.y.inc = 0.01;")
    origin.Execute("layer.x.label.pt = 25; layer.y.label.pt = 25;")
    origin.Execute("layer.x.showAxes = 3; layer.y.showAxes = 3;") # keep border lines
    origin.Execute("layer.x.showLabels = 1; layer.y.showLabels = 1;")
    origin.Execute("layer.x.ticks.in = 1; layer.x.ticks.out = 0;")
    origin.Execute("layer.y.ticks.in = 1; layer.y.ticks.out = 0;")
    origin.Execute("layer.y.label.numformat = 1; layer.y.label.decimal = 2;") # drop m prefix, fix 2 decimals
    origin.Execute("layer.x2.ticks = 0; layer.y2.ticks = 0;")
    origin.Execute("label -xl Wavenumber (cm\\+(-1));")
    origin.Execute("label -yl Transmittance (a.u.);")

    # FTIR convention: reversed X-axis (high -> low wavenumber)
    all_wn = layers[0]['wavenumbers']
    origin.Execute(f"layer.x.from = {np.max(all_wn)}; layer.x.to = {np.min(all_wn)};")

    origin.Execute("legend -r;")
    origin.Execute("legend.showframe = 0;")

    origin.Execute("doc -uw;")
    if log_callback: log_callback("Origin FTIR combined plotting complete")
