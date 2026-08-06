"""
raman_core.py - Raman Analysis Core Logic
"""
import pandas as pd
import numpy as np
import os
import subprocess
import time
from scipy.signal import find_peaks
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except Exception:
    genai = None
    GENAI_AVAILABLE = False
import json
import re

try:
    import win32com.client
    WIN32COM_AVAILABLE = True
except ImportError:
    WIN32COM_AVAILABLE = False

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
    # Raman: Peaks are maxima (positive intensity), unlike FTIR dips.
    # Do NOT invert intensities here.
    wavenumbers = np.asarray(wavenumbers)
    intensities = np.asarray(intensities)
    if intensities.size < 3:
        # empty/degenerate input (e.g. a file whose rows all failed to parse)
        return np.array([]), np.array([], dtype=int)
    data_range = intensities.max() - intensities.min()
    # Height threshold can be adjusted, here using prominence logic similar to FTIR but for positive peaks
    peak_indices, _ = find_peaks(intensities, prominence=data_range * 0.02)
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
        # Raman: Higher value = Stronger signal
        rel_str = (val - min_T) / range_T if range_T != 0 else 0
        s_str = "Very Strong" if rel_str > 0.8 else "Strong" if rel_str > 0.5 else "Medium" if rel_str > 0.2 else "Weak"
        peak_details.append(f"{{Wavenumber: {wn:.1f}, Strength: {s_str}}}")

    prompt = f"""
    You are an expert in Raman Spectroscopy. Analyze the following peaks.

    [Sample Context]
    {context}

    [Detected Peaks (cm-1)]
    {chr(10).join(peak_details)}
    
    [Task]
    Analyze peaks for Raman spectroscopy assignment. Provide the description in **English**.
    Return JSON list: [{{ "wavenumber": float, "assignment": str, "material": str, "description": str, "confidence": str, "other_possibilities": str }}]
    """
    
    response = model.generate_content(prompt)
    clean = re.sub(r"```json|```", "", response.text).strip()
    try:
        return json.loads(clean)
    except:
        start = clean.find('[')
        end = clean.rfind(']') + 1
        if start != -1 and end != -1: return json.loads(clean[start:end])
        return []

def analyze_peak_shift(api_key, model_name, context, name_a, pa, name_b, pb):
    if genai is None:
        raise RuntimeError("google-generativeai package is not installed. (pip install google-generativeai)")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    shift = pb - pa
    prompt = f"""
    Context: {context}
    Compare (Raman): {name_a} ({pa:.1f}) vs {name_b} ({pb:.1f})
    Shift: {shift:.2f} cm-1
    Explain chemical cause (e.g., stress, crystallinity, temperature, doping) in English (Focus on Raman).
    Provide a detailed explanation and a summary. 
    Return JSON: {{ "shift_value": float, "shift_type": str, "cause": str, "detailed_explanation": str, "summary": str, "implication": str }}
    """
    response = model.generate_content(prompt)
    clean = re.sub(r"```json|```", "", response.text).strip()
    try:
        return json.loads(clean)
    except:
        start = clean.find('{')
        end = clean.rfind('}') + 1
        return json.loads(clean[start:end]) if start != -1 else {"error": "Parsing failed"}

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
                "Raman Shift (cm-1)": info.get('wavenumber'),
                "Assignment": info.get('assignment'),
                "Material": info.get('material'),
                "Confidence": info.get('confidence'),
                "Description": info.get('description')
            }
            all_data.append(row)

    if not all_data: return False

    df = pd.DataFrame(all_data)
    cols = ["Layer", "Sample Info", "Raman Shift (cm-1)", "Assignment", "Material", "Confidence", "Description"]
    df = df[cols]
    df.to_excel(file_path, index=False)
    return True

def connect_to_origin(origin_exe_path: str = "", log_callback=None):
    """Connect to Origin application."""
    if not WIN32COM_AVAILABLE:
        if log_callback: log_callback("pywin32 not installed")
        return None

    try:
        origin = win32com.client.Dispatch("Origin.ApplicationSI")
        origin.Visible = 1
        if log_callback: log_callback("Connected to existing Origin")
        return origin
    except: pass

    if origin_exe_path and os.path.exists(origin_exe_path):
        if log_callback: log_callback(f"Launching Origin: {origin_exe_path}")
        try:
            subprocess.Popen([origin_exe_path])
            for _ in range(30):
                time.sleep(1)
                try:
                    origin = win32com.client.Dispatch("Origin.ApplicationSI")
                    origin.Visible = 1
                    if log_callback: log_callback("New Origin instance started")
                    return origin
                except: continue
        except Exception as e:
            if log_callback: log_callback(f"Origin launch error: {e}")
    return None

def plot_raman_to_origin(origin, layers, colors=None, log_callback=None):
    """Plot Raman spectra to Origin in a single combined graph."""
    if not layers:
        if log_callback: log_callback("No layers to plot")
        return

    if log_callback: log_callback("Creating a single Origin Raman plot for all layers...")

    # 1. Create a single workbook to hold all data
    wb_name = origin.CreatePage(2, "Raman_Data", "Origin")
    origin.Execute(f"page.active$ = {wb_name};")
    num_layers = len(layers)
    origin.Execute(f"wks.ncols = {1 + num_layers};")

    # 2. X-axis setup (Raman Shift) - common to all layers
    origin.Execute(f'wks.col1.lname$ = "Raman Shift";')
    origin.Execute(f'wks.col1.units$ = "cm\\+(-1)";')
    origin.Execute(f'wks.col1.type = 4;') # 4 = X-axis type
    origin.PutWorksheet(f"[{wb_name}]Sheet1", layers[0]['wavenumbers'].tolist(), 0, 0)

    # 3. Insert Y-axis (Intensity) data for each layer
    for i, L in enumerate(layers):
        col_idx = i + 2
        display_name = L.get('context').strip() if L.get('context') and L.get('context').strip() else L.get('name')
        origin.Execute(f'wks.col{col_idx}.lname$ = "{display_name}";')
        origin.Execute(f'wks.col{col_idx}.type = 1;') # 1 = Y-axis type
        origin.PutWorksheet(f"[{wb_name}]Sheet1", L['intensities'].tolist(), 0, i + 1)

    # 4. Create a single graph window and plot all Y data
    gp_name = origin.CreatePage(3, "Raman_Combined_Graph", "Origin")
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
    origin.Execute("layer.x.label.pt = 30; layer.y.label.pt = 30;")
    origin.Execute("layer.x.showAxes = 3; layer.y.showAxes = 3;")
    origin.Execute("layer.x.showLabels = 1; layer.y.showLabels = 0;")
    origin.Execute("layer.x.ticks.in = 1; layer.x.ticks.out = 0;")
    origin.Execute("layer.y.ticks = 0;")
    origin.Execute("layer.y.label.numformat = 1; layer.y.label.decimal = 2;") # drop m prefix, fix 2 decimals
    origin.Execute("layer.x2.ticks = 0; layer.y2.ticks = 0;") # remove top/right ticks
    origin.Execute("label -xl Raman Shift (cm\\+(-1));")
    origin.Execute("label -yl Intensity (a.u.);")

    # Set X-axis range (data range) and Y-axis range (0 to 1)
    all_wn = layers[0]['wavenumbers']
    origin.Execute(f"layer.x.from = {np.min(all_wn)}; layer.x.to = {np.max(all_wn)};")
    origin.Execute("layer.y.from = 0; layer.y.to = 1;")

    origin.Execute("legend -r;")
    origin.Execute("legend.showframe = 0;")

    origin.Execute("doc -uw;")
    if log_callback: log_callback("Origin Raman combined plotting complete")