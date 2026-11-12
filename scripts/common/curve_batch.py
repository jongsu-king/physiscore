"""The six curve analyses without a window.

One place states, for SCLC, light-intensity dependence, TRPL, impedance, C-V
and stability, how a file is read, which parameters the analysis takes, how
they are passed to the core, and which numbers go in the summary table. The
windows (`scripts/<Tool>/run_*.py`) and the command line (`physiscore sclc`,
...) both go through it, so a file analysed with the same parameters gives the
same numbers either way.

Nothing here imports Tk.
"""
from __future__ import annotations

import importlib
import math
import os
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from scripts.common import app_config, curve_io
from scripts.common.provenance import write_sidecar


def _ratio(num: str, den: str):
    def value(r):
        d = r.get(den)
        return r[num] / d if d is not None and np.isfinite(d) and d else None
    return value


def _sub(outer: str, inner: str, scale: float = 1.0):
    def value(r):
        v = (r.get(outer) or {}).get(inner)
        return None if v is None else v * scale
    return value


# slug -> what the tool is.  `batch`: (heading, key | callable(result), unit) of the summary table.
TOOLS: Dict[str, Dict[str, Any]] = {
    "sclc": {
        "name": "SCLC", "core": "scripts.SCLC.sclc_core", "interpret": "interpret_sclc",
        "defaults": {"thickness_nm": 500.0, "eps_r": 25.0, "area_cm2": None, "temperature_k": 300.0,
                     "branch": "auto", "sweep": "up", "v_bi": 0.0, "window": 5, "field_dependent": False},
        "batch": [("V_TFL", "V_TFL", "V"), ("n_t", "n_t_cm3", "cm-3"), ("Mobility", "mobility_cm2_Vs", "cm2/Vs"),
                  ("Conductivity", "sigma_S_cm", "S/cm")],
    },
    "intensity": {
        "name": "Light intensity", "core": "scripts.Intensity.intensity_core", "interpret": "interpret_intensity",
        "defaults": {"temperature_k": 300.0, "i_min": None, "i_max": None, "area_cm2": None, "sweep": "reverse"},
        "batch": [("n_id", _sub("voc_fit", "n_id"), ""), ("alpha", _sub("jsc_fit", "alpha"), ""),
                  ("pFF", _sub("pseudo", "pFF", 100.0), "%"), ("Transport loss", "transport_loss_FF", "% abs")],
    },
    "trpl": {
        "name": "TRPL", "core": "scripts.TRPL.trpl_core", "interpret": "interpret_trpl",
        "defaults": {"model": "auto", "background": "auto", "skip": 0.0, "t_end": None, "time_unit": "ns",
                     "irf": "none", "irf_fwhm": 0.0, "irf_file": "", "mobility_cm2_Vs": 0.0, "temperature_k": 300.0},
        "batch": [("Model", "model", ""), ("Response", "irf", ""),
                  ("tau short", lambda r: float(np.nanmin(np.atleast_1d(r["taus"]))), ""),
                  ("<tau> amp.", "tau_amp", ""), ("<tau> int.", "tau_int", ""),
                  ("tau 1/e", "tau_1e", ""), ("chi2 red.", "chi2_red", ""), ("Unit", "time_unit", "")],
    },
    "eis": {
        "name": "Impedance", "core": "scripts.EIS.eis_core", "interpret": "interpret_eis",
        "defaults": {"model": "auto", "convention": "auto", "f_min": None, "f_max": None, "area_cm2": 0.0,
                     "thickness_nm": 0.0},
        "batch": [("Circuit", "model", ""), ("Rs", "Rs", "Ohm"), ("R total", "R_total", "Ohm"),
                  ("Fit rms", "rms_pct", "%"), ("KK rms", _sub("kk", "rms_pct"), "%"),
                  ("DRT processes", lambda r: r["drt"]["n_processes"] if r.get("drt") else None, "")],
    },
    "cv": {
        "name": "C-V (Mott-Schottky)", "core": "scripts.CV.cv_core", "interpret": "interpret_cv",
        "defaults": {"area_cm2": None, "eps_r": 25.0, "thickness_nm": 0.0, "temperature_k": 300.0, "c_unit": "F",
                     "m": 2.0, "v_min": None, "v_max": None},
        "batch": [("N", "N_cm3", "cm-3"), ("V_bi", "V_bi", "V"), ("W (0 V)", "W0_nm", "nm"),
                  ("N / N_min", _ratio("N_cm3", "N_min_cm3"), "")],
    },
    "stability": {
        "name": "Stability", "core": "scripts.Stability.stability_core", "interpret": "interpret_stability",
        "defaults": {"time_unit": "h", "norm": "initial", "n_initial": 1, "threshold": 0.8, "model": "auto",
                     "protocol": "not stated"},
        "batch": [("Model", "model", ""), ("T measured", "T_measured", "h"), ("T extrapolated", "T_extrapolated", "h"),
                  ("Ts", lambda r: r["Ts_measured"] if r["Ts_reached"] else r["Ts_extrapolated"], "h"),
                  ("Loss rate", "rate_pct_per_1000h", "%/1000 h"), ("Final", lambda r: 100.0 * r["final"], "%")],
    },
}
AREA_FROM_SETTINGS = ("sclc", "intensity", "cv")       # tools whose area defaults to the configured cell area
MAX_TABLE_FILES = 20                                 # files whose curves get their own sheets


def fmt_value(v: Any) -> str:
    """One number format for every table of these analyses."""
    if v is None:
        return "-"
    if isinstance(v, str):
        return v
    if isinstance(v, (bool, np.bool_)):
        return "yes" if v else "no"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if not math.isfinite(f):
        return "-"
    a = abs(f)
    if a != 0 and (a >= 1e5 or a < 1e-3):
        return f"{f:.3e}"
    return f"{f:.4g}"


def tool_name(tool: str) -> str:
    return TOOLS[tool]["name"]


def core(tool: str):
    return importlib.import_module(TOOLS[tool]["core"])


def batch_columns(tool: str) -> List[tuple]:
    return list(TOOLS[tool]["batch"])


def choices(tool: str) -> Dict[str, List[str]]:
    """The values each option of the tool accepts (the lists of its core)."""
    c = core(tool)
    return {
        "sclc": lambda: {"branch": ["auto", "positive", "negative"], "sweep": ["up", "down", "all"]},
        "intensity": lambda: {"sweep": ["reverse", "forward", "combined"]},
        "trpl": lambda: {"model": ["auto"] + list(c.MODELS), "time_unit": list(c.TIME_UNITS),
                         "irf": list(c.IRF_KINDS)},
        "eis": lambda: {"model": ["auto"] + list(c.MODELS), "convention": ["auto", "Z''", "-Z''"]},
        "cv": lambda: {"c_unit": ["F", "mF", "uF", "nF", "pF"]},
        "stability": lambda: {"time_unit": list(c.TIME_TO_HOURS), "norm": ["initial", "maximum", "none"],
                              "model": ["auto"] + list(c.MODELS), "protocol": list(c.PROTOCOLS)},
    }[tool]()


def parameters(tool: str, given: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Defaults of the tool with the given values on top; an option left out
    (None) keeps its default, and the area of a device tool falls back to the
    cell area of the settings."""
    out = dict(TOOLS[tool]["defaults"])
    unknown = sorted(set(given or {}) - set(out))
    if unknown:
        raise ValueError(f"{tool_name(tool)} has no parameter named {', '.join(unknown)}")
    for k, v in (given or {}).items():
        if v is not None:
            out[k] = v
    if tool in AREA_FROM_SETTINGS and out.get("area_cm2") is None:
        out["area_cm2"] = app_config.cell_area_cm2()
    for key, allowed in choices(tool).items():
        if out[key] not in allowed:
            raise ValueError(f"{tool_name(tool)}: {key} = {out[key]!r} is not one of {', '.join(allowed)}")
    return out


def parse_background(value: Any) -> Any:
    """TRPL background: 'auto', 'none' or a number (text with a decimal comma is read)."""
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    text = str(value if value is not None else "").strip().lower() or "auto"
    try:
        return float(text.replace(",", "."))
    except ValueError:
        if text not in ("auto", "none"):
            raise ValueError("Background: enter 'auto', 'none' or a number") from None
    return text


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def load(tool: str, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """One file -> the arrays the analysis takes, with a note on how it was read."""
    c = core(tool)
    if os.path.isdir(path):
        raise ValueError("this is a folder; give the files in it")
    if not os.path.isfile(path):
        raise ValueError("file not found")
    if tool == "sclc":
        v, j, how = c.read_curve(path, params["area_cm2"])
        return {"v": v, "j": j, "_how": how}
    df = curve_io.read_numeric_table(path)
    data, names = curve_io.pick_columns(df, c.COLUMN_SPEC)
    data["_columns"] = names
    return data


def load_jv_set(paths: Sequence[str], params: Dict[str, Any]) -> Dict[str, Any]:
    """An intensity series from J-V files whose names carry the irradiance."""
    c = core("intensity")
    data = c.from_jv_files(list(paths), params["area_cm2"], sweep=params["sweep"])
    if len(data["intensity"]) < 3:
        raise ValueError("fewer than three of these J-V files carry an irradiance in their name "
                         "(examples: cell_0.1sun.txt, cell_53mW.txt, cell_OD1.0.txt)")
    data["_how"] = (f"{len(data['files'])} J-V files, irradiance from the file names, "
                    f"{params['sweep']} sweep, area {params['area_cm2']:g} cm2")
    return data


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------
def analyse(tool: str, data: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    c, p = core(tool), params
    if tool == "sclc":
        return c.analyse(data["v"], data["j"], p["thickness_nm"], p["eps_r"], temperature_k=p["temperature_k"],
                         branch=p["branch"], sweep=p["sweep"], v_bi=p["v_bi"], window=int(p["window"]),
                         field_dependent=bool(p["field_dependent"]))
    if tool == "intensity":
        return c.analyse(data["intensity"], data["voc"], jsc=data.get("jsc"), ff=data.get("ff"),
                         pce=data.get("pce"), temperature_k=p["temperature_k"], i_min=p["i_min"], i_max=p["i_max"])
    if tool == "trpl":
        irf_t = irf_y = None
        if p["irf"] == "measured":
            irf_t, irf_y = c.read_response(p.get("irf_file") or "")
        return c.analyse(data["t"], data["y"], model=p["model"], background=parse_background(p["background"]),
                         skip=p["skip"], t_end=p["t_end"], irf_fwhm=p["irf_fwhm"],
                         mobility_cm2_Vs=p["mobility_cm2_Vs"], time_unit=p["time_unit"],
                         temperature_k=p["temperature_k"], irf=p["irf"], irf_t=irf_t, irf_y=irf_y)
    if tool == "eis":
        for key in ("f", "zre", "zim"):
            if key not in data:
                raise ValueError("the file needs three columns: frequency, Z' and Z''")
        return c.analyse(data["f"], data["zre"], data["zim"], model=p["model"], convention=p["convention"],
                         f_min=p["f_min"], f_max=p["f_max"], area_cm2=p["area_cm2"], thickness_nm=p["thickness_nm"])
    if tool == "cv":
        return c.analyse(data["v"], data["c"], p["area_cm2"], p["eps_r"], c_unit=p["c_unit"],
                         thickness_nm=p["thickness_nm"], temperature_k=p["temperature_k"], m=p["m"],
                         v_min=p["v_min"], v_max=p["v_max"])
    if tool == "stability":
        return c.analyse(data["t"], data["y"], time_unit=p["time_unit"], norm=p["norm"], threshold=p["threshold"],
                         model=p["model"], protocol=p["protocol"], n_initial=int(p["n_initial"]))
    raise KeyError(tool)


def summary_rows(tool: str, result: Dict[str, Any]) -> List[tuple]:
    return list(core(tool).summary_rows(result))


def checks(tool: str, result: Dict[str, Any]) -> List[str]:
    return list(core(tool).checks(result))


def interpret(tool: str, result: Dict[str, Any], subject: str = ""):
    """Rule-based interpretation (scripts.common.interpret.Report)."""
    from scripts.common import interpret_transport
    return getattr(interpret_transport, TOOLS[tool]["interpret"])(result, subject)


# kinds of the detector that one tool reads without a remark (default: its own kind)
_SAME_FAMILY = {"sclc": ("sclc", "dark_jv", "jv")}


def file_check(tool: str, path: str) -> List[str]:
    """One remark when the file reads, with high confidence, as another kind of
    measurement than the tool analyses (an impedance spectrum given to TRPL)."""
    from scripts.common import detect
    try:
        d = detect.detect_file(path)
    except Exception:                       # noqa: BLE001 - the remark is optional
        return []
    if not d.kind or d.confidence != "high" or d.kind in _SAME_FAMILY.get(tool, (tool,)):
        return []
    return [f"This file reads as '{d.label}' ({d.why()}) but was analysed as {tool_name(tool)} data: "
            "check that the right file was opened."]


def _item(tool: str, label: str, make_data, params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        data = make_data()
        result = analyse(tool, data, params)
        return {"file": label, "data": data, "result": result, "error": "", "checks": checks(tool, result)}
    except Exception as e:                  # noqa: BLE001 - one bad file must not stop the others
        return {"file": label, "data": None, "result": None, "error": f"{type(e).__name__}: {e}", "checks": []}


def run_file(tool: str, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """{'file', 'path', 'data', 'result', 'error', 'checks'}; a file that cannot
    be read or analysed carries the reason in 'error' and None as its result."""
    it = _item(tool, os.path.splitext(os.path.basename(path))[0], lambda: load(tool, path, params), params)
    it["path"] = path
    if it["result"] is not None:
        it["checks"] = file_check(tool, path) + it["checks"]
    return it


def run_files(tool: str, paths: Sequence[str], params: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [run_file(tool, p, params) for p in paths]


def run_jv_set(paths: Sequence[str], params: Dict[str, Any]) -> Dict[str, Any]:
    """The light-intensity analysis of one series of J-V files."""
    paths = list(paths)
    folder = os.path.basename(os.path.dirname(os.path.abspath(paths[0]))) or "J-V"
    it = _item("intensity", f"{folder} ({len(paths)} J-V files)", lambda: load_jv_set(paths, params), params)
    it["inputs"] = (it["data"] or {}).get("files") or paths
    return it


# ---------------------------------------------------------------------------
# per-file tables of the workbook
# ---------------------------------------------------------------------------
def _has(a) -> bool:
    return a is not None and len(a) > 0 and bool(np.isfinite(np.asarray(a, float)).any())


def _tables_sclc(data, r):
    return {"Curve": pd.DataFrame({"V (V)": r["v"], "J (mA/cm2)": r["j"], "d log J / d log V": r["local_slope"]})}


def _tables_intensity(data, r):
    cols = {"Irradiance": r["intensity"], "Voc (V)": r["voc"]}
    for key, heading in (("jsc", "Jsc (mA/cm2)"), ("ff", "FF (%)"), ("pce", "PCE (%)")):
        if _has(r.get(key)):
            cols[heading] = r[key]
    cols["Used in the fit"] = np.asarray(r["fit_mask"], bool)
    out = {"Series": pd.DataFrame(cols)}
    if r.get("pseudo"):
        out["Pseudo J-V"] = pd.DataFrame({"V (V)": r["pseudo"]["v"], "J (mA/cm2)": r["pseudo"]["j"]})
    return out


def _tables_trpl(data, r):
    u = r["time_unit"]
    out = {"Decay": pd.DataFrame({f"t - t_peak ({u})": r["t"], "Signal - background": r["y"], "Raw": r["y_raw"],
                                  "In fit window": np.asarray(r["mask"], bool)}),
           "Fit": pd.DataFrame({f"t ({u})": r["t_fit"], "Signal": r["y_fit"], "Model": r["fit"],
                                "Weighted residual": r["residuals"]})}
    comps = r.get("components") or []
    for i, cmp in enumerate(comps if len(comps) > 1 else []):
        out["Fit"][f"Component {i + 1}"] = cmp
    if r.get("irf_curve") is not None:
        out["Fit"]["Response (scaled to the peak)"] = r["irf_curve"]
    td, tau = r["tau_diff"]
    if len(td):
        out["Differential lifetime"] = pd.DataFrame({f"t ({u})": td, f"tau_diff ({u})": tau})
    return out


def _tables_eis(data, r):
    z, zf, kk = r["z"], r["zfit"], r["kk"]
    out = {"Spectrum": pd.DataFrame({
        "f (Hz)": r["f"], "Z' (Ohm)": z.real, "Z'' (Ohm)": z.imag, "Fit Z' (Ohm)": zf.real,
        "Fit Z'' (Ohm)": zf.imag, "Fit residual Z' (%)": r["res_re_pct"], "Fit residual Z'' (%)": r["res_im_pct"],
        "KK residual Z' (%)": kk["res_re_pct"], "KK residual Z'' (%)": kk["res_im_pct"],
        "C = Im(1/Z)/omega (F)": r["C_spectrum_F"]})}
    d = r.get("drt")
    if d:
        out["DRT"] = pd.DataFrame({"tau (s)": d["tau"], "f = 1/(2 pi tau) (Hz)": 1.0 / (2 * np.pi * d["tau"]),
                                   "gamma (Ohm)": d["gamma"]})
        out["Spectrum"]["DRT Z' (Ohm)"] = d["zfit"].real
        out["Spectrum"]["DRT Z'' (Ohm)"] = d["zfit"].imag
    return out


def _tables_cv(data, r):
    return {"Curve": pd.DataFrame({"V (V)": r["v"], "C (F)": r["c"], "1/C2 (F-2)": r["inv_c2"], "W (nm)": r["w_nm"],
                                   "N(W) (cm-3)": r["n_profile_cm3"]})}


def _tables_stability(data, r):
    model = core("stability").model_curve(r["model"], r["p"], r["t"])
    return {"Trace": pd.DataFrame({"t (h)": r["t"], "Raw": r["raw"], "Normalised": r["e"], "Model": model})}


_TABLES = {"sclc": _tables_sclc, "intensity": _tables_intensity, "trpl": _tables_trpl, "eis": _tables_eis,
           "cv": _tables_cv, "stability": _tables_stability}


def tables(tool: str, data: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
    """The curves behind the numbers of one file: sheet name -> table."""
    return _TABLES[tool](data, result)


# ---------------------------------------------------------------------------
# summary tables and export
# ---------------------------------------------------------------------------
def batch_value(spec: tuple, result: Dict[str, Any]) -> Any:
    key = spec[1]
    try:
        return key(result) if callable(key) else result.get(key)
    except Exception:                       # noqa: BLE001 - a missing quantity is an empty cell
        return None


def batch_heading(spec: tuple) -> str:
    return f"{spec[0]} ({spec[2]})" if len(spec) > 2 and spec[2] else str(spec[0])


def summary_table(items: Sequence[Dict[str, Any]], batch: Sequence[tuple]) -> pd.DataFrame:
    """One row per file with the headline numbers."""
    rows = []
    for it in items:
        row: Dict[str, Any] = {"File": it["file"]}
        for b in batch:
            row[batch_heading(b)] = batch_value(b, it["result"]) if it["result"] is not None else None
        row["Checks"] = len(it["checks"])
        row["Error"] = it["error"]
        rows.append(row)
    return pd.DataFrame(rows)


def results_table(items: Sequence[Dict[str, Any]], rows_of: Callable[[Dict[str, Any]], Sequence[tuple]]) -> pd.DataFrame:
    """Every reported quantity of every file, one per row."""
    rows = []
    for it in items:
        if it["result"] is None:
            continue
        for q, v, u in rows_of(it["result"]):
            rows.append({"File": it["file"], "Quantity": q,
                         "Value": v if isinstance(v, (int, float, str)) else fmt_value(v), "Unit": u})
    return pd.DataFrame(rows)


def summary_frame(tool: str, items: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    return summary_table(items, TOOLS[tool]["batch"])


def results_frame(tool: str, items: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    return results_table(items, lambda r: summary_rows(tool, r))


def write_workbook(path: str, name: str, items: Sequence[Dict[str, Any]], params: Dict[str, Any],
                   batch: Sequence[tuple], rows_of: Callable, tables_of: Optional[Callable] = None,
                   inputs: Optional[Sequence[str]] = None) -> str:
    """Summary, Results, Checks and Parameters sheets, the curves of up to 20
    files, and the analysis record next to the workbook."""
    summary = summary_table(items, batch)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        summary.to_excel(xw, sheet_name="Summary", index=False)
        results_table(items, rows_of).to_excel(xw, sheet_name="Results", index=False)
        found = [{"File": it["file"], "Check": c} for it in items for c in it["checks"]]
        pd.DataFrame(found or [{"File": "", "Check": "No check raised a remark."}]).to_excel(
            xw, sheet_name="Checks", index=False)
        pd.DataFrame([{"Parameter": k, "Value": "" if v is None else v} for k, v in params.items()]).to_excel(
            xw, sheet_name="Parameters", index=False)
        used = {"Summary", "Results", "Checks", "Parameters"}
        n = 0
        for it in items:
            if it["result"] is None or tables_of is None:
                continue
            n += 1
            if n > MAX_TABLE_FILES:
                break
            for title, df in (tables_of(it["data"], it["result"]) or {}).items():
                sheet = (f"{n} {title}" if len(items) > 1 else title)[:31]
                k = 2
                while sheet in used:
                    sheet = f"{sheet[:28]}_{k}"
                    k += 1
                used.add(sheet)
                df.to_excel(xw, sheet_name=sheet, index=False)
    if inputs is None:
        inputs = []
        for it in items:
            inputs.extend(it.get("inputs") or [it.get("path") or it["file"]])
    write_sidecar(path, name, inputs=list(inputs), parameters=dict(params),
                  results={"files": summary.where(pd.notna(summary), None).to_dict(orient="records")})
    return path


def write_excel(tool: str, items: Sequence[Dict[str, Any]], path: str, params: Dict[str, Any]) -> str:
    return write_workbook(path, tool_name(tool), items, params, TOOLS[tool]["batch"],
                          lambda r: summary_rows(tool, r), lambda d, r: tables(tool, d, r))
