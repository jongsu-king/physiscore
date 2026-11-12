"""Reading J-V curves from generic tabular files (CSV, TSV, DAT, XLSX).

The source-meter text export with a `Vmeas / Imeas` block is handled by the
J-V cores directly. Many labs instead keep curves as spreadsheets or CSV files
written by other instruments or scripts. This module recognises the voltage
and current columns by their headers and converts the current to current
density:

* a header containing `mA/cm` (or starting with `J`) is taken as current
  density in mA/cm2;
* a header containing `(mA)` is current in mA, `(A)`, `Imeas`, `Current` or
  `I` current in A; both are divided by the device area;
* without recognisable headers, column 0 is voltage and column 1 current
  density in mA/cm2.

The sign is normalised to the program's plotting convention (photocurrent
negative, i.e. J(0) < 0 for an illuminated cell); the analysis itself is
sign-invariant.
"""
from __future__ import annotations

import os
import re
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from scripts.common import textio

GENERIC_EXTENSIONS = (".csv", ".tsv", ".dat", ".xlsx", ".xls")
RESULT_SHEETS = {"CombinedData", "SummaryTable", "BestPerformance", "BestCombinedData", "CurveAnalysis"}


def has_sidecar(path: str) -> bool:
    """True when a Physiscore side-car (<name>.analysis.json) sits next to the file,
    i.e. the file is an export of this program."""
    return os.path.exists(os.path.splitext(path)[0] + ".analysis.json")


def is_result_workbook(path: str) -> bool:
    """True for files Physiscore itself wrote (they must not be re-read as input):
    any file with a side-car, and workbooks with the J-V result sheets."""
    if has_sidecar(path):
        return True
    if not path.lower().endswith((".xlsx", ".xls")):
        return False
    try:
        sheets = set(pd.ExcelFile(path).sheet_names)
    except Exception:
        return True          # unreadable workbook: skip it
    return bool(sheets & RESULT_SHEETS)


def _read_table(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path)
    # skip a non-numeric preamble: find the header row just above the first numeric row
    lines = textio.read_text(path).splitlines()
    num = re.compile(r"^\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?\s*[,;\t ]\s*[-+]?(\d|\.)")
    first = next((i for i, ln in enumerate(lines) if num.match(ln)), None)
    if first is None:
        raise ValueError("no numeric data rows")
    header = first - 1 if first > 0 and lines[first - 1].strip() else None
    from io import StringIO
    block = "\n".join(lines[header if header is not None else first:])
    return pd.read_csv(StringIO(block), sep=None, engine="python", header=0 if header is not None else None)


def _classify(col: str) -> Optional[str]:
    c = str(col).strip().lower().replace(" ", "")
    if "ma/cm" in c or c.startswith("j") or "density" in c:
        return "J"
    if c.startswith("v") or "volt" in c or "bias" in c:
        return "V"
    if "(ma)" in c or c.endswith("_ma") or c == "ma":
        return "ImA"
    if c.startswith("i") or "current" in c or "(a)" in c or c == "a":
        return "IA"
    return None


def read_generic_iv(path: str, area_cm2: float) -> Tuple[np.ndarray, np.ndarray, str]:
    """(V [V], J [mA/cm2], description of the column interpretation)."""
    df = _read_table(path)
    df = df.dropna(axis=1, how="all")
    if df.shape[1] < 2:
        raise ValueError("need at least two columns (voltage, current)")
    kinds = {c: _classify(c) for c in df.columns} if not all(isinstance(c, (int, np.integer)) for c in df.columns) else {}
    v_col = next((c for c, k in kinds.items() if k == "V"), df.columns[0])
    i_col = next((c for c, k in kinds.items() if k in ("J", "ImA", "IA") and c != v_col), None)
    if i_col is None:
        i_col = next(c for c in df.columns if c != v_col)
    kind = kinds.get(i_col) or "J"
    v = pd.to_numeric(df[v_col], errors="coerce").to_numpy(float)
    i = pd.to_numeric(df[i_col], errors="coerce").to_numpy(float)
    ok = np.isfinite(v) & np.isfinite(i)
    v, i = v[ok], i[ok]
    if kind == "IA":
        j = i * 1000.0 / area_cm2
        how = f"'{i_col}' read as current in A, divided by {area_cm2:g} cm2"
    elif kind == "ImA":
        j = i / area_cm2
        how = f"'{i_col}' read as current in mA, divided by {area_cm2:g} cm2"
    else:
        j = i.copy()
        how = f"'{i_col}' read as current density in mA/cm2"
    # plotting convention: photocurrent negative at short circuit
    if len(v) > 2 and v.min() <= 0 <= v.max():
        order = np.argsort(v)
        if float(np.interp(0.0, v[order], j[order])) > 0:
            j = -j
            how += "; sign flipped to the photocurrent-negative convention"
    return v, j, f"'{v_col}' as voltage, {how}"
