from __future__ import annotations
import math
import numpy as np
from typing import Tuple

def robust_noise_sigma(y: np.ndarray) -> float:
    y = np.asarray(y, float)
    if len(y) < 10:
        return float(np.std(y)) if len(y) else 1.0
    dy = np.diff(y)
    mad = np.median(np.abs(dy - np.median(dy)))
    sigma = (mad / 0.6745) / math.sqrt(2.0) if mad > 0 else float(np.std(dy) / math.sqrt(2.0))
    return float(sigma) if sigma > 0 else 1.0

def safe_sorted_xy(x: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    order = np.argsort(x)
    return x[order], y[order]

def auto_distance_pts(x: np.ndarray, min_sep_x: float) -> int:
    if len(x) < 2:
        return 1
    dx = float(np.median(np.diff(x)))
    if dx <= 0:
        return 6
    return max(1, int(round(min_sep_x / dx)))

def quality_from_snr(snr: float) -> str:
    if snr >= 12: return "GOOD"
    if snr >= 6:  return "OK"
    return "BAD"


def robust_read_csv(path: str):
    """Read an x,y data CSV robustly.

    Instrument exports (e.g. Thermo Avantage XPS region exports like
    'glass-O1s.csv') prepend non-tabular metadata lines ('2', '', 'O1s', '1')
    before the numeric block, which makes a plain pd.read_csv() raise
    ParserError. This reader first tries a plain parse and otherwise skips to
    the first numeric 'x<sep>y' line, auto-detecting the separator.
    """
    import io
    import re
    import pandas as pd

    try:
        df = pd.read_csv(path)
        if df.shape[1] >= 2:
            num0 = pd.to_numeric(df.iloc[:, 0], errors="coerce")
            if num0.notna().sum() >= max(3, int(0.5 * len(df))):
                return df
    except Exception:
        pass

    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    num_re = re.compile(
        r"^\s*[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\s*[,;\t ]\s*[-+]?\d")
    start = next((i for i, ln in enumerate(lines) if num_re.match(ln)), None)
    if start is None:
        raise ValueError("No numeric x,y data block found in file.")
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])),
                     header=None, sep=None, engine="python")
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="any")
    if df.shape[1] < 2:
        raise ValueError("Need at least 2 numeric columns (x, y).")
    df.columns = [f"col{i}" for i in range(df.shape[1])]
    return df.reset_index(drop=True)

