"""Index of the analyses already exported under a folder.

Every export Physiscore writes has a side-car (``<export>.analysis.json``,
see :mod:`scripts.common.provenance`) with the tool, the date, the input
files, the parameters and the numbers. This module finds those side-cars
under a project folder and turns them into tables: one line per export for
the launcher's Results tab, a long table of every number, and a workbook
that collects the results of a whole project in one file.

It reads only what the program itself wrote and does no analysis.
"""
from __future__ import annotations

import datetime as _dt
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from scripts.common import provenance

LABEL_KEYS = ("File", "Sample", "Group", "Label", "Name", "Peak", "Phase", "file", "sample", "group", "name")
SKIP_QUANTITIES = ("Checks", "Error")
INDEX_TOOL = "Results index"            # the collected workbook itself (left out of the index)
MAX_LIST_INLINE = 8
Row = Tuple[str, str, str, Any]            # table, row label, quantity, value


@dataclass
class Entry:
    sidecar: str
    tool: str = ""
    timestamp: str = ""
    version: str = ""
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @property
    def export(self) -> str:
        """The exported file this side-car describes (it may have been moved or deleted)."""
        folder = os.path.dirname(self.sidecar)
        stem = os.path.basename(self.sidecar)[:-len(provenance.SIDECAR_SUFFIX)]
        for out in self.outputs:
            local = os.path.join(folder, os.path.basename(str(out)))
            if os.path.isfile(local):
                return local
        try:
            for name in sorted(os.listdir(folder)):
                if os.path.splitext(name)[0] == stem and not name.endswith(provenance.SIDECAR_SUFFIX):
                    return os.path.join(folder, name)
        except OSError:
            pass
        for out in self.outputs:
            if os.path.isfile(str(out)):
                return str(out)
        return ""

    @property
    def when(self) -> Optional[_dt.datetime]:
        try:
            return _dt.datetime.fromisoformat(self.timestamp)
        except (TypeError, ValueError):
            return None

    @property
    def date(self) -> str:
        w = self.when
        return w.strftime("%Y-%m-%d %H:%M") if w else ""

    @property
    def sample(self) -> str:
        names = [os.path.splitext(os.path.basename(p))[0] if os.path.isabs(p) else p for p in self.inputs if p]
        if len(names) == 1:
            return names[0]
        if len(names) > 1:
            common = os.path.commonprefix(names).rstrip(" _-.(")
            return f"{common}… ({len(names)} files)" if len(common) >= 3 else f"{len(names)} files"
        return os.path.basename(self.sidecar)[:-len(provenance.SIDECAR_SUFFIX)]

    @property
    def name(self) -> str:
        e = self.export
        return os.path.basename(e) if e else os.path.basename(self.sidecar)


def _is_scalar(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def _row_label(row: Dict[str, Any], index: int) -> str:
    for k in LABEL_KEYS:
        if k in row and row[k] not in (None, ""):
            return str(row[k])
    return f"#{index + 1}"


def flatten(results: Any, table: str = "summary") -> List[Row]:
    """Every number of a side-car's ``results`` as (table, row, quantity, value)."""
    out: List[Row] = []
    if not isinstance(results, dict):
        return out
    for key, v in results.items():
        key = str(key)
        if _is_scalar(v):
            out.append((table, "", key, v))
        elif isinstance(v, dict):
            sub = key if table == "summary" else f"{table}.{key}"
            out.extend(flatten(v, sub))
        elif isinstance(v, list):
            if v and all(isinstance(r, dict) for r in v):
                sub = key if table == "summary" else f"{table}.{key}"
                for i, r in enumerate(v):
                    label = _row_label(r, i)
                    for q, val in r.items():
                        if _is_scalar(val) and str(q) not in LABEL_KEYS:
                            out.append((sub, label, str(q), val))
            elif v and all(_is_scalar(x) for x in v) and len(v) <= MAX_LIST_INLINE:
                out.append((table, "", key, ", ".join(fmt(x) for x in v)))
    return out


def fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return ""
        a = abs(v)
        if a != 0 and (a >= 1e5 or a < 1e-3):
            return f"{v:.3e}"
        return f"{v:.4g}"
    return str(v)


def headline(entry: Entry, n: int = 4) -> str:
    """A few of the numbers of an export, for a one-line listing."""
    if entry.error:
        return entry.error
    rows = [r for r in flatten(entry.results) if r[2] not in SKIP_QUANTITIES]
    numeric = [r for r in rows if isinstance(r[3], (int, float)) and not isinstance(r[3], bool)]
    if not numeric:
        return ""
    first_label = numeric[0][1]
    picked = [r for r in numeric if r[1] == first_label][:n]
    labels = {r[1] for r in numeric if r[1]}
    text = "  ·  ".join(f"{r[2]} {fmt(r[3])}" for r in picked)
    if first_label:
        text = f"{first_label}: {text}"
        if len(labels) > 1:
            text += f"   (+{len(labels) - 1} more)"
    return text


def read_entry(path: str) -> Entry:
    try:
        rec = provenance.read_sidecar(path)
    except Exception as exc:                            # a damaged side-car is listed, not fatal
        return Entry(sidecar=path, error=f"unreadable side-car ({type(exc).__name__})")
    if not isinstance(rec, dict):
        return Entry(sidecar=path, error="unreadable side-car")
    return Entry(
        sidecar=path,
        tool=str(rec.get("tool") or ""),
        timestamp=str(rec.get("timestamp") or ""),
        version=str(rec.get("physiscore_version") or ""),
        inputs=[str(p) for p in (rec.get("inputs") or []) if p],
        outputs=[str(p) for p in (rec.get("outputs") or []) if p],
        parameters=rec.get("parameters") if isinstance(rec.get("parameters"), dict) else {},
        results=rec.get("results") if isinstance(rec.get("results"), dict) else {},
    )


def find_sidecars(folder: str, max_depth: int = 4, limit: int = 5000) -> List[str]:
    found: List[str] = []
    base = os.path.abspath(folder)
    for root, dirs, files in os.walk(base):
        depth = 0 if root == base else os.path.relpath(root, base).count(os.sep) + 1
        dirs[:] = sorted(d for d in dirs if not d.startswith(".")) if depth < max_depth else []
        for name in sorted(files):
            if name.endswith(provenance.SIDECAR_SUFFIX) and not name.startswith("."):
                found.append(os.path.join(root, name))
                if len(found) >= limit:
                    return found
    return found


def scan(folder: str, max_depth: int = 4, limit: int = 5000,
         cancelled: Optional[Callable[[], bool]] = None) -> List[Entry]:
    """Side-cars under ``folder``, newest first."""
    entries: List[Entry] = []
    for path in find_sidecars(folder, max_depth, limit):
        if cancelled is not None and cancelled():
            break
        entry = read_entry(path)
        if entry.tool != INDEX_TOOL:
            entries.append(entry)
    entries.sort(key=lambda e: (e.timestamp or "", e.sidecar), reverse=True)
    return entries


def index_table(entries: Iterable[Entry], folder: str = "") -> pd.DataFrame:
    """One line per export."""
    rows = []
    for e in entries:
        exp = e.export
        rows.append({
            "Date": e.date, "Tool": e.tool, "Sample": e.sample, "Headline": headline(e),
            "Export": _rel(exp or e.sidecar, folder), "Inputs": len(e.inputs),
            "Version": e.version, "Side-car": _rel(e.sidecar, folder),
        })
    return pd.DataFrame(rows, columns=["Date", "Tool", "Sample", "Headline", "Export", "Inputs", "Version", "Side-car"])


def long_table(entries: Iterable[Entry], folder: str = "") -> pd.DataFrame:
    """Every exported number, one per line."""
    rows = []
    for e in entries:
        exp = _rel(e.export or e.sidecar, folder)
        for table, label, quantity, value in flatten(e.results):
            rows.append({"Date": e.date, "Tool": e.tool, "Sample": label or e.sample, "Table": table,
                         "Quantity": quantity, "Value": value, "Export": exp, "Version": e.version})
    return pd.DataFrame(rows, columns=["Date", "Tool", "Sample", "Table", "Quantity", "Value", "Export", "Version"])


def tool_tables(entries: Iterable[Entry], folder: str = "") -> Dict[str, pd.DataFrame]:
    """Wide tables: one per tool and result table, a line per sample, a column per quantity."""
    grouped: Dict[Tuple[str, str], Dict[Tuple[str, str, str], Dict[str, Any]]] = {}
    for e in entries:
        exp = _rel(e.export or e.sidecar, folder)
        for table, label, quantity, value in flatten(e.results):
            rows = grouped.setdefault((e.tool or "Unknown", table), {})
            row = rows.setdefault((e.date, exp, label), {"Date": e.date, "Sample": label or e.sample, "Export": exp})
            row[quantity] = value
    out: Dict[str, pd.DataFrame] = {}
    for (tool, table), rows in grouped.items():
        name = tool if table in ("summary", "files") else f"{tool} - {table}"
        out[name] = pd.DataFrame(list(rows.values()))
    return out


def _rel(path: str, folder: str) -> str:
    if not path:
        return ""
    if folder:
        try:
            rel = os.path.relpath(path, folder)
            if not rel.startswith(".."):
                return rel
        except ValueError:
            pass
    return path


def _sheet_names(names: Iterable[str]) -> Dict[str, str]:
    used: Dict[str, str] = {}
    taken = {"index", "all values"}
    for name in names:
        clean = re.sub(r"[\[\]:*?/\\]", " ", name).strip()[:31] or "Sheet"
        base, k = clean, 2
        while clean.lower() in taken:
            tail = f" ({k})"
            clean = base[:31 - len(tail)] + tail
            k += 1
        taken.add(clean.lower())
        used[name] = clean
    return used


def write_excel(entries: List[Entry], path: str, folder: str = "") -> str:
    """Collect the results of a project in one workbook.

    Sheets: ``Index`` (one line per export), one sheet per tool and result
    table (a line per sample), and ``All values`` (the long table).
    """
    tables = tool_tables(entries, folder)
    names = _sheet_names(tables.keys())
    with pd.ExcelWriter(path) as xw:
        index_table(entries, folder).to_excel(xw, sheet_name="Index", index=False)
        for key in sorted(tables):
            tables[key].to_excel(xw, sheet_name=names[key], index=False)
        long_table(entries, folder).to_excel(xw, sheet_name="All values", index=False)
    # the workbook gets its own side-car, so a later scan of the folder treats it
    # as a Physiscore export (not as a measurement) and leaves it out of the index
    provenance.write_sidecar(path, INDEX_TOOL, inputs=[e.sidecar for e in entries],
                             parameters={"folder": folder}, results={"exports": len(entries)})
    return path


def summary(entries: List[Entry]) -> str:
    if not entries:
        return "No exported analyses found"
    counts: Dict[str, int] = {}
    for e in entries:
        counts[e.tool or "Unknown"] = counts.get(e.tool or "Unknown", 0) + 1
    parts = ", ".join(f"{n} {t}" for t, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
    return f"{len(entries)} exports: {parts}"
