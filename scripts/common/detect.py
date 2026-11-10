"""Measurement-type detection for data files.

The launcher's workspace lists the files of a folder with the measurement each
one most likely holds, so that a double-click opens the right tool. Detection
is a short list of scored rules over three kinds of evidence:

1. the file name (``trpl``, ``eqe``, ``dark``, ``sclc``, ...),
2. the column names of the table (``Frequency`` with ``Z'``, ``Time`` with
   ``Counts``, ...),
3. the numbers themselves (a log-spaced first column with three columns is an
   impedance spectrum; a voltage axis whose current changes sign is an
   illuminated J-V curve; ...).

Every score comes with the sentence that produced it (``Detection.evidence``),
and the result is labelled high / medium / low. A low-confidence guess is a
suggestion, never a silent decision: the launcher asks before opening it.
Nothing leaves the computer and nothing is learned from the files.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

# kind -> (launcher tool name, label shown in the workspace)
KINDS: Dict[str, Tuple[str, str]] = {
    "jv": ("J-V Curve", "J-V (illuminated)"),
    "dark_jv": ("J-V Dark", "J-V (dark)"),
    "sclc": ("SCLC", "SCLC (single-carrier J-V)"),
    "intensity": ("Light intensity", "Light-intensity series"),
    "eqe": ("EQE", "EQE"),
    "stability": ("Stability", "Stability trace"),
    "eis": ("Impedance", "Impedance spectrum"),
    "cv": ("C-V (Mott-Schottky)", "Capacitance-voltage"),
    "trpl": ("TRPL", "Time-resolved PL"),
    "abs": ("Absorbance", "Absorbance (UV-Vis)"),
    "pl": ("PL", "Photoluminescence"),
    "xrd": ("XRD", "X-ray diffraction"),
    "raman": ("Raman", "Raman"),
    "ftir": ("FTIR", "FTIR"),
    "xps": ("XPS", "XPS"),
    "sem": ("FE-SEM", "SEM image"),
}
FOLDER_TOOLS = ("J-V Curve", "J-V Dark")          # these tools process a folder, not single files

TABLE_EXTENSIONS = (".txt", ".csv", ".tsv", ".dat", ".xy", ".asc", ".prn", ".xlsx", ".xls")
IMAGE_EXTENSIONS = (".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp")
MAX_READ_BYTES = 30 * 1024 * 1024                 # larger files are classified by name only

HIGH, MEDIUM, LOW = 5.0, 3.0, 1.5

_B, _E = r"(?<![a-z])", r"(?![a-z])"              # token edges: no letter on either side

# (kind, pattern on the lower-case file name without extension, weight)
_NAME_RULES: List[Tuple[str, str, float]] = [
    ("trpl", rf"trpl|tcspc|{_B}tr[-_ ]pl{_E}|pl[-_ ]?decay|lifetime", 4.0),
    ("eqe", rf"{_B}eqe{_E}|ipce|{_B}qe{_E}", 4.0),
    ("abs", rf"uv[-_ ]?vis|absorb|{_B}abs{_E}|tauc|transmittance", 4.0),
    ("pl", rf"{_B}pl{_E}|photolum|{_B}sspl{_E}", 3.5),
    ("xrd", rf"xrd|diffract|2theta|{_B}gi[-_ ]?wa?xs{_E}", 4.0),
    ("raman", r"raman", 4.0),
    ("ftir", rf"ftir|ft[-_ ]ir|{_B}atr{_E}|{_B}ir{_E}", 3.5),
    ("xps", rf"{_B}xps{_E}|{_B}ups{_E}", 4.0),
    ("sclc", rf"sclc|electron[-_ ]?only|hole[-_ ]?only|{_B}(?:eod|hod){_E}|single[-_ ]?carrier", 4.5),
    ("eis", rf"{_B}eis{_E}|impedance|nyquist|{_B}peis{_E}", 4.0),
    ("cv", rf"mott|schottky|{_B}c[-_ ]?v{_E}|capacitance", 4.0),
    ("stability", r"stabil|mppt|mpp[-_ ]?track|ag(?:e)?ing|isos|degrad|t80", 4.0),
    ("intensity", rf"suns[-_ ]?voc|intensity|irradiance|{_B}suns{_E}", 3.5),
    ("dark_jv", rf"{_B}dark{_E}", 3.0),
    ("jv", rf"{_B}j[-_ ]?v{_E}|{_B}i[-_ ]?v{_E}|illum|am1\.?5|1[-_ ]?sun|{_B}(?:fwd|rev|forward|reverse){_E}", 2.5),
    ("sem", rf"{_B}(?:fe[-_ ]?)?sem{_E}", 3.0),
]

_WL = r"wavelength|lambda|\bnm\b|\bwl\b"
# (kind, patterns that must each match some column name, weight, description)
_COLUMN_RULES: List[Tuple[str, Tuple[str, ...], float, str]] = [
    ("eis", (r"freq|\bhz\b|^f\b", r"z'|z_?re|re\s*\(?z|real|z_?im|imag|\|z\||phase"), 4.5, "frequency and impedance columns"),
    ("cv", (r"volt|bias|^v\b|v_?dc", r"capac|^c\b|^cp\b|^cs\b|^c\s*\("), 4.5, "voltage and capacitance columns"),
    ("trpl", (r"time|delay|^t\b", r"count|decay"), 4.5, "time and counts columns"),
    ("stability", (r"time|hour|elapsed|duration|^t\b", r"pce|effic|normali[sz]ed|pmax|pmpp|\beta\b"), 4.5,
     "time and efficiency columns"),
    ("intensity", (r"intens|irradi|\bsuns?\b|light", r"v_?oc"), 4.5, "irradiance and Voc columns"),
    ("eqe", (_WL, r"eqe|ipce|\bqe\b|quantum"), 4.5, "wavelength and EQE columns"),
    ("abs", (_WL, r"^abs|absorb|transmit|%\s*t\b|reflect|\bod\b"), 4.5, "wavelength and absorbance columns"),
    ("pl", (_WL + r"|energy", r"\bpl\b|photolum|emission"), 4.0, "wavelength and PL columns"),
    ("xrd", (r"2\s*-?\s*theta|2θ|two.?theta|\b2th\b",), 4.5, "a 2-theta column"),
    ("raman", (r"raman",), 4.5, "a Raman-shift column"),
    ("ftir", (r"wavenumber|cm-?1|cm\^-1", r"transmit|%\s*t\b|absorb"), 4.0, "wavenumber and transmittance columns"),
    ("xps", (r"binding",), 4.5, "a binding-energy column"),
    ("jv", (r"vmeas|volt|bias|^v\b", r"imeas|curr|^i\b|^j\b|density"), 2.5, "voltage and current columns"),
]


@dataclass
class Detection:
    """What one file most likely is."""
    path: str
    kind: str = ""                     # key of KINDS; "" when nothing matched
    score: float = 0.0
    evidence: List[str] = field(default_factory=list)
    alternatives: List[Tuple[str, float]] = field(default_factory=list)   # other kinds, best first
    columns: List[str] = field(default_factory=list)
    shape: Tuple[int, int] = (0, 0)
    error: str = ""

    @property
    def tool(self) -> str:
        return KINDS[self.kind][0] if self.kind else ""

    @property
    def label(self) -> str:
        return KINDS[self.kind][1] if self.kind else "Not recognised"

    @property
    def confidence(self) -> str:
        if not self.kind:
            return "none"
        return "high" if self.score >= HIGH else "medium" if self.score >= MEDIUM else "low"

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    def describe(self) -> str:
        """`400 x 3  ·  Frequency (Hz), Z' (Ohm), Z'' (Ohm)`."""
        if self.error:
            return self.error
        if not self.columns:
            return ""
        cols = ", ".join(self.columns[:4]) + (", ..." if len(self.columns) > 4 else "")
        return f"{self.shape[0]} x {self.shape[1]}  ·  {cols}"

    def why(self) -> str:
        return "; ".join(self.evidence)


# ---------------------------------------------------------------- evidence
def name_scores(path: str) -> Dict[str, Tuple[float, str]]:
    """Scores from the file name and from the name of the folder it lies in."""
    out: Dict[str, Tuple[float, str]] = {}
    base = os.path.splitext(os.path.basename(path))[0].lower()
    parent = os.path.basename(os.path.dirname(os.path.abspath(path))).lower()
    for kind, pattern, weight in _NAME_RULES:
        if re.search(pattern, base):
            out[kind] = (weight, f"file name ({re.search(pattern, base).group(0)})")
        elif parent and re.search(pattern, parent):
            out.setdefault(kind, (0.6 * weight, f"folder name ({re.search(pattern, parent).group(0)})"))
    return out


def column_scores(columns: Sequence[str]) -> Dict[str, Tuple[float, str]]:
    """Scores from the column names. Columns named by position carry no information."""
    cols = [str(c).strip().lower() for c in columns]
    cols = [c for c in cols if c and not re.fullmatch(r"(?:col|column|unnamed:?)\s*\d+", c)]
    out: Dict[str, Tuple[float, str]] = {}
    if not cols:
        return out
    for kind, patterns, weight, text in _COLUMN_RULES:
        if all(any(re.search(p, c) for c in cols) for p in patterns):
            out[kind] = (weight, text)
    return out


def _monotonic(x: np.ndarray) -> bool:
    d = np.diff(x)
    return bool(len(d) and (np.all(d >= 0) or np.all(d <= 0)))


def numeric_scores(x: np.ndarray, y: np.ndarray, n_cols: int) -> Dict[str, Tuple[float, str]]:
    """Scores from the first two numeric columns. These are weak hints: on their
    own they give at most a low-confidence suggestion."""
    out: Dict[str, Tuple[float, str]] = {}
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = np.asarray(x, float)[ok], np.asarray(y, float)[ok]
    n = len(x)
    if n < 5:
        return out
    lo, hi = float(np.min(x)), float(np.max(x))
    mono = _monotonic(x)
    y_lo, y_hi = float(np.min(y)), float(np.max(y))

    # impedance: positive, log-spaced frequency over decades, three or more columns
    if n_cols >= 3 and lo > 0 and hi / lo >= 1e3 and mono and n >= 10:
        steps = np.abs(np.diff(np.log10(x)))
        if np.median(steps) > 0 and np.max(steps) < 6 * np.median(steps):
            out["eis"] = (2.5, "log-spaced first column over %.0f decades with %d columns" % (np.log10(hi / lo), n_cols))
            return out

    # voltage axis
    if -6.0 <= lo and hi <= 6.0 and (hi - lo) >= 0.3 and n >= 8:
        nz = y != 0
        xx, yy = x[nz], y[nz]
        mag = np.abs(yy)
        span = float(np.max(mag) / np.min(mag)) if len(mag) else 1.0
        flips = np.nonzero(np.diff(np.sign(yy)) != 0)[0]
        v_cross = 0.5 * (xx[flips] + xx[flips + 1]) if len(flips) else np.array([])
        if n_cols == 2 and y_lo > 0 and y_hi < 1e-3 and span < 50:
            out["cv"] = (2.0, "voltage axis with a small, slowly varying positive second column (farads)")
        elif 1 <= len(flips) <= 6 and hi <= 3.0 and float(np.min(np.abs(v_cross))) > 0.15:
            out["jv"] = (2.0, "voltage axis and a current that changes sign at %.2f V" % float(np.median(v_cross)))
        elif span >= 1e2:
            if lo >= -0.05:
                out["sclc"] = (1.5, "positive voltages and a current spanning %.0f decades" % np.log10(span))
                out["dark_jv"] = (1.2, "current spanning decades without a photocurrent")
            else:
                out["dark_jv"] = (1.8, "current spanning %.0f decades without a photocurrent" % np.log10(span))
        if out:
            return out

    if not mono:
        return out

    # diffraction angle: 2-theta from a few degrees to below 150, fine steps
    step = (hi - lo) / max(n - 1, 1)
    if 2.0 <= lo < 40 and 30 <= hi <= 150 and n >= 200 and step <= 0.11 and y_lo >= 0:
        out["xrd"] = (2.0, "angle axis %.0f-%.0f with %.3g steps and non-negative counts" % (lo, hi, step))
        return out

    # wavelength axis (nm)
    if 180 <= lo and hi <= 2600 and (hi - lo) >= 80 and n >= 20:
        peak = int(np.argmax(y))
        edges = max(abs(y[0]), abs(y[-1]))
        if y_hi > 0 and 0.1 * n < peak < 0.9 * n and edges < 0.15 * y_hi and (y_hi > 150 or y_lo < 0 or n_cols == 2):
            out["pl"] = (1.6, "wavelength axis with one band that returns to the baseline")
        ys = y[np.argsort(x)]
        if 15 <= y_hi <= 100.5 and y_lo >= -2 and np.mean(ys[: n // 3]) > 3 * abs(np.mean(ys[-max(3, n // 10):])):
            out["eqe"] = (1.6, "wavelength axis, values within 0-100 % that fall towards long wavelengths")
        elif y_hi <= 6 and y_lo > -0.5 and np.mean(ys[: n // 3]) > 2 * abs(np.mean(ys[-max(3, n // 10):])):
            out["abs"] = (1.6, "wavelength axis, values of a few absorbance units that fall towards long wavelengths")
        if out:
            return out

    # wavenumber axis (cm-1)
    if 300 <= lo <= 1000 and 3000 <= hi <= 4500 and n >= 200:
        if 0 <= y_lo and y_hi <= 120 and y_hi > 20:
            out["ftir"] = (1.6, "wavenumber axis 400-4000 with values in per cent")
        else:
            out["ftir"] = (1.0, "wavenumber axis 400-4000")
            out["raman"] = (0.8, "wavenumber axis")
        return out

    # time axis: a decay over orders of magnitude, or a slow drift around the first value
    if lo >= 0 and x[0] <= x[-1] and n >= 20:
        peak = int(np.argmax(y))
        tail = np.median(y[-max(3, n // 20):])
        first = np.median(y[: max(3, n // 20)])
        if y_hi > 0 and peak < 0.35 * n and tail < 0.03 * y_hi and y_lo >= -0.02 * y_hi:
            out["trpl"] = (2.0, "a peak near the start that decays by more than 1.5 decades")
        elif first > 0 and 0.2 <= tail / first <= 1.3 and y_lo > 0 and y_hi / first <= 1.5 and hi >= 10 * step and n_cols == 2:
            out["stability"] = (1.0, "a positive trace that stays near its first value")
    return out


# ---------------------------------------------------------------- one file
def _read_table(path: str):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        import pandas as pd
        return pd.read_excel(path, nrows=4000)
    from scripts.common.curve_io import read_text_table
    return read_text_table(path)


def _numeric_columns(df) -> List[np.ndarray]:
    import pandas as pd
    cols = []
    for c in df.columns:
        v = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
        if np.isfinite(v).sum() >= max(3, 0.6 * len(v)):
            cols.append(v)
    return cols


def is_export(path: str) -> bool:
    """True for a table Physiscore wrote itself (it has a side-car next to it)."""
    from scripts.common.provenance import sidecar_path
    return os.path.isfile(sidecar_path(path))


def detect_file(path: str, read: bool = True) -> Detection:
    """Classify one file. `read=False` uses the name only (fast, for very large folders)."""
    d = Detection(path=path)
    ext = os.path.splitext(path)[1].lower()
    scores: Dict[str, float] = {}
    notes: Dict[str, List[str]] = {}

    def add(found: Dict[str, Tuple[float, str]]) -> None:
        for kind, (w, text) in found.items():
            scores[kind] = scores.get(kind, 0.0) + w
            notes.setdefault(kind, []).append(text)

    names = name_scores(path)
    if ext in IMAGE_EXTENSIONS:
        if ext in (".tif", ".tiff"):
            add({"sem": (3.5, "TIFF image")})
        if "sem" in names:
            add({"sem": names["sem"]})
        if re.search(r"\d+\s*k?x\b|x\s*\d+\s*k\b|\bmag", os.path.basename(path).lower()):
            add({"sem": (1.5, "magnification in the file name")})
        if scores:
            d.kind, d.score, d.evidence = "sem", scores["sem"], notes["sem"]
        return d
    names.pop("sem", None)
    add(names)

    if read and ext in TABLE_EXTENSIONS:
        try:
            if os.path.getsize(path) > MAX_READ_BYTES:
                raise ValueError("file larger than 30 MB: classified by name only")
            df = _read_table(path)
            d.columns = [str(c) for c in df.columns]
            d.shape = (int(len(df)), int(df.shape[1]))
            add(column_scores(d.columns))
            num = _numeric_columns(df)
            if len(num) >= 2:
                add(numeric_scores(num[0], num[1], len(num)))
        except Exception as exc:  # noqa: BLE001 - an unreadable file is still listed
            d.error = str(exc).splitlines()[0][:160] if str(exc) else type(exc).__name__

    # a name that says "dark" or "sclc" decides between the three current-voltage tools
    if "dark_jv" in names and "jv" in scores and "sclc" not in names:
        scores["dark_jv"] = scores.get("dark_jv", 0.0) + scores.pop("jv")
        notes.setdefault("dark_jv", []).extend(notes.pop("jv", []))
    if "sclc" in names:
        for other in ("jv", "dark_jv"):
            if other in scores:
                scores["sclc"] += 0.5 * scores.pop(other)
                notes.pop(other, None)
    # "PL" in the name of a decay trace: the time axis wins
    if "trpl" in scores and "pl" in scores and scores["trpl"] >= scores["pl"]:
        scores.pop("pl")
        notes.pop("pl", None)

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    ranked = [(k, s) for k, s in ranked if s >= 0.8]
    if ranked:
        d.kind, d.score = ranked[0]
        d.evidence = notes.get(d.kind, [])
        d.alternatives = ranked[1:4]
    return d


# ---------------------------------------------------------------- a folder
def list_candidates(folder: str, max_depth: int = 2, limit: int = 2000) -> List[str]:
    """Data files below `folder` (hidden files, editor lock files, side-cars and
    Physiscore's own exports are left out), depth first, sorted by name."""
    out: List[str] = []
    folder = os.path.abspath(folder)
    base_depth = folder.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(x for x in dirs if not x.startswith((".", "__")))
        if root.rstrip(os.sep).count(os.sep) - base_depth >= max_depth:
            dirs[:] = []
        for name in sorted(files, key=str.lower):
            if name.startswith((".", "~$")) or name.endswith(".analysis.json"):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in TABLE_EXTENSIONS and ext not in IMAGE_EXTENSIONS:
                continue
            path = os.path.join(root, name)
            if is_export(path):
                continue
            out.append(path)
            if len(out) >= limit:
                return out
    return out


def iter_folder(folder: str, max_depth: int = 2, limit: int = 2000, read: bool = True):
    """Classify the data files below `folder` one at a time: yields
    ``(index, total, detection)``. The detection is None for an image that does
    not look like a micrograph (exported figures, photographs). A caller that
    must stay responsive pulls a few items per tick (the Workspace tab does)."""
    paths = list_candidates(folder, max_depth=max_depth, limit=limit)
    for i, p in enumerate(paths):
        d: Optional[Detection] = detect_file(p, read=read)
        if os.path.splitext(p)[1].lower() in IMAGE_EXTENSIONS and not d.kind:
            d = None
        yield i + 1, len(paths), d


def scan_folder(folder: str, max_depth: int = 2, limit: int = 2000, read: bool = True,
                progress: Optional[Callable[[int, int], None]] = None,
                cancelled: Optional[Callable[[], bool]] = None) -> List[Detection]:
    """Classify every data file below `folder` (see `iter_folder`)."""
    out: List[Detection] = []
    for i, n, d in iter_folder(folder, max_depth=max_depth, limit=limit, read=read):
        if d is not None:
            out.append(d)
        if progress is not None:
            progress(i, n)
        if cancelled is not None and cancelled():
            break
    return out


def group_by_tool(detections: Sequence[Detection]) -> Dict[str, List[Detection]]:
    """Tool name -> its files, in the order of KINDS; unrecognised files under ''."""
    order = [KINDS[k][0] for k in KINDS] + [""]
    out: Dict[str, List[Detection]] = {}
    for tool in order:
        hits = [d for d in detections if d.tool == tool]
        if hits:
            out[tool] = hits
    return out


def summary(detections: Sequence[Detection]) -> str:
    """`42 files: 30 J-V (illuminated), 6 EQE, 4 XRD, 2 not recognised`."""
    if not detections:
        return "no data files"
    parts = []
    for kind in list(KINDS) + [""]:
        n = sum(1 for d in detections if d.kind == kind)
        if n:
            parts.append(f"{n} {KINDS[kind][1] if kind else 'not recognised'}")
    return f"{len(detections)} file{'s' if len(detections) != 1 else ''}: " + ", ".join(parts)
