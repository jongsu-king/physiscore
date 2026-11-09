"""Reproducibility side-car files.

Every table Physiscore exports can be accompanied by a small JSON file that
records what produced it: program version, date, input files, the analysis
parameters and a summary of the results. The side-car is what lets a number in
a manuscript be traced back to the exact analysis, and it is machine-readable
so a later script (or the CLI) can re-run or compare it.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import platform
import sys
from typing import Any, Dict, Optional

import numpy as np

SIDECAR_SUFFIX = ".analysis.json"


def app_version() -> str:
    try:
        from Physiscore_Launcher import APP_VERSION
        return APP_VERSION
    except Exception:
        return "unknown"


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _jsonable(obj.tolist())
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if hasattr(obj, "to_dict"):
        try:
            return _jsonable(obj.to_dict(orient="records"))
        except TypeError:
            return _jsonable(obj.to_dict())
    if isinstance(obj, (str, int)) or obj is None:
        return obj
    return str(obj)


def build_record(tool: str, inputs=None, parameters: Optional[Dict[str, Any]] = None,
                 results: Optional[Dict[str, Any]] = None, outputs=None) -> Dict[str, Any]:
    return {
        "physiscore_version": app_version(),
        "tool": tool,
        "timestamp": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "inputs": [os.path.abspath(p) for p in (inputs or []) if p],
        "outputs": [os.path.abspath(p) for p in (outputs or []) if p],
        "parameters": _jsonable(parameters or {}),
        "results": _jsonable(results or {}),
    }


def sidecar_path(for_file: str) -> str:
    """`result.xlsx` -> `result.analysis.json` (next to the export)."""
    base, _ext = os.path.splitext(for_file)
    return base + SIDECAR_SUFFIX


def write_sidecar(for_file: str, tool: str, inputs=None, parameters=None, results=None) -> str:
    """Write the side-car for an exported file and return its path. Never
    raises: a failed side-car must not fail the export it documents."""
    path = sidecar_path(for_file)
    try:
        rec = build_record(tool, inputs=inputs, parameters=parameters, results=results, outputs=[for_file])
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, indent=2, ensure_ascii=False)
        return path
    except Exception:
        return ""


def read_sidecar(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
