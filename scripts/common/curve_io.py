"""Column-aware table reading for the curve tools (SCLC, intensity series,
TRPL, impedance, C-V, stability).

Instrument exports differ in column order and naming, so each tool states
which quantities it needs as a list of name patterns; a column is taken by
name when a pattern matches and by position otherwise. The choice is returned
with the data so that the window and the report can state which column was
read as what.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from scripts.common import textio


_NUMBER = re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")
_DECIMAL_COMMA = re.compile(r"^[-+]?\d+,\d+(?:[eE][-+]?\d+)?$")
_BLANK = ("", "nan", "na", "n/a", "-", "--", "inf", "-inf")
_SEPARATORS = ("\t", ";", ",", None)          # None: any run of blanks


def _cells(line: str, sep: Optional[str]) -> List[str]:
    parts = line.split() if sep is None else line.split(sep)
    out = []
    for c in parts:
        c = c.strip().strip('"').strip()
        if sep != "," and _DECIMAL_COMMA.match(c):
            c = c.replace(",", ".")              # decimal comma of a semicolon or tab separated export
        out.append(c)
    return out


def _is_data(cells: List[str]) -> bool:
    """A row of numbers: at least two, and nothing in it that is not a number
    (empty cells of an optional column are allowed)."""
    n = 0
    for c in cells:
        if _NUMBER.match(c):
            n += 1
        elif c.lower() not in _BLANK:
            return False
    return n >= 2


def read_text_table(path: str) -> pd.DataFrame:
    """Numeric block of a text export, with the column names kept.

    The separator (tab, semicolon, comma or blanks) is the one that yields the
    most rows of numbers; a decimal comma is accepted when the separator is
    not a comma. Lines before the block are metadata, except the one or two
    lines directly above it with the same number of fields, which are read as
    column names (and units). Without such a line the columns are col0, col1,
    ... and the caller falls back to positions.
    """
    text = textio.read_text(path)
    lines = [ln for ln in text.splitlines()]
    probe = [ln for ln in lines if ln.strip()][:400]
    best_sep, best_n = None, 0
    for sep in _SEPARATORS:
        n = sum(1 for ln in probe if _is_data(_cells(ln, sep)))
        if n > best_n:
            best_sep, best_n = sep, n
    if best_n < 3:
        raise ValueError(f"{os.path.basename(path)}: no block of numeric rows")
    rows: List[Tuple[int, List[str]]] = []
    for i, ln in enumerate(lines):
        if ln.strip():
            c = _cells(ln, best_sep)
            if _is_data(c):
                rows.append((i, c))
    widths = [len(c) for _i, c in rows]
    width = max(set(widths), key=widths.count)
    rows = [(i, c) for i, c in rows if len(c) == width]
    first = rows[0][0]
    head: List[List[str]] = []
    k = first - 1
    comment_below = None
    while k >= 0 and len(head) < 2:
        if not lines[k].strip():
            if head:
                break
            k -= 1
            continue
        comment = lines[k].lstrip().startswith(("#", "%"))
        if head and comment != comment_below:
            break                                      # a comment above a plain header line is metadata
        c = _cells(lines[k].lstrip().lstrip("#%").strip() if comment else lines[k], best_sep)
        if len(c) != width or _is_data(c):
            break
        head.insert(0, c)
        comment_below = comment
        k -= 1
    if head:
        names = []
        for j in range(width):
            name = head[0][j]
            if len(head) > 1 and head[1][j] and "(" not in name:
                name = f"{name} ({head[1][j]})"       # second line: units
            names.append(name or f"col{j}")
    else:
        names = [f"col{j}" for j in range(width)]
    seen: Dict[str, int] = {}
    for j, nme in enumerate(names):                    # duplicate names would collapse into one column
        if nme in seen:
            seen[nme] += 1
            names[j] = f"{nme} [{seen[nme]}]"
        else:
            seen[nme] = 1
    values = np.array([[float(c) if _NUMBER.match(c) else np.nan for c in cells] for _i, cells in rows], float)
    return pd.DataFrame(values, columns=names)


def read_numeric_table(path: str, sheet=None) -> pd.DataFrame:
    """The numeric columns of a CSV/TXT/TSV/DAT/Excel table (metadata preamble
    skipped, column names kept). Columns with fewer than three numbers are
    dropped, as are rows without any number."""
    if os.path.splitext(path)[1].lower() in (".xlsx", ".xls"):
        from scripts.common.batch import read_table
        df = read_table(path, sheet)
    else:
        df = read_text_table(path)
    out = {}
    for c in df.columns:
        col = pd.to_numeric(df[c], errors="coerce")
        if col.notna().sum() >= 3:
            out[str(c).strip()] = col
    if not out:
        raise ValueError(f"{os.path.basename(path)}: no numeric columns")
    res = pd.DataFrame(out)
    return res.dropna(how="all").reset_index(drop=True)


def find_column(df: pd.DataFrame, patterns: Sequence[str], exclude: Sequence[str] = ()) -> Optional[str]:
    """First column whose name matches one of the regular expressions
    (case-insensitive), skipping the columns in `exclude`."""
    for pat in patterns:
        rx = re.compile(pat, re.IGNORECASE)
        for c in df.columns:
            if c in exclude:
                continue
            if rx.search(str(c)):
                return c
    return None


def pick_columns(df: pd.DataFrame, spec: Sequence[Tuple[str, Sequence[str], Optional[int]]]
                 ) -> Tuple[Dict[str, np.ndarray], Dict[str, str]]:
    """Resolve the quantities of `spec` = [(key, name patterns, fallback
    position or None), ...]. Returns ({key: values}, {key: 'column name'}).
    A key without a match and without a usable fallback is left out."""
    used: List[str] = []
    data: Dict[str, np.ndarray] = {}
    names: Dict[str, str] = {}
    cols = list(df.columns)
    # by name first, so that a positional fallback never steals a named column
    for key, patterns, _pos in spec:
        c = find_column(df, patterns, exclude=used)
        if c is not None:
            used.append(c)
            names[key] = c
    for key, _patterns, pos in spec:
        if key in names or pos is None:
            continue
        free = [c for c in cols if c not in used]
        if pos < len(cols) and cols[pos] not in used:
            c = cols[pos]
        elif free:
            c = free[0]
        else:
            continue
        used.append(c)
        names[key] = f"{c} (by position)"
        data[key] = df[c].to_numpy(float)
    for key, c in names.items():
        if key not in data:
            data[key] = df[c].to_numpy(float)
    return data, names


def finite_rows(*arrays: np.ndarray) -> Tuple[np.ndarray, ...]:
    """Keep the rows where every array is finite."""
    ok = np.ones(len(arrays[0]), bool)
    for a in arrays:
        ok &= np.isfinite(a)
    return tuple(np.asarray(a, float)[ok] for a in arrays)


def linfit(x: np.ndarray, y: np.ndarray) -> Dict[str, float]:
    """Ordinary least-squares line with standard errors and R2."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    if n < 2 or np.ptp(x) == 0:
        return {"slope": np.nan, "intercept": np.nan, "slope_err": np.nan, "intercept_err": np.nan, "r2": np.nan, "n": n}
    xm, ym = x.mean(), y.mean()
    sxx = float(((x - xm) ** 2).sum())
    slope = float(((x - xm) * (y - ym)).sum() / sxx)
    icpt = float(ym - slope * xm)
    res = y - (slope * x + icpt)
    ss_res, ss_tot = float((res ** 2).sum()), float(((y - ym) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    if n > 2:
        s2 = ss_res / (n - 2)
        se_slope = float(np.sqrt(s2 / sxx))
        se_icpt = float(np.sqrt(s2 * (1.0 / n + xm ** 2 / sxx)))
    else:
        se_slope = se_icpt = np.nan
    return {"slope": slope, "intercept": icpt, "slope_err": se_slope, "intercept_err": se_icpt, "r2": r2, "n": n}


def t_factor(n: int, level: float = 0.95) -> float:
    """Two-sided Student-t factor for a line fitted to n points."""
    from scipy import stats
    dof = max(n - 2, 1)
    return float(stats.t.ppf(0.5 + level / 2.0, dof))
