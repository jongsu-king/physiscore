"""Colour palette, fonts and plot styling for the whole suite (no Tk import).

The palette is chosen once per process from the ``theme`` key of
physisfera_config.json (``"light"`` - the default, the look of most
instrument software - or ``"dark"``). Every GUI module reads its colours
from here, and the analysis cores use the same module for plot colours, so a
single switch changes the entire program. A theme change takes effect on the
next start; the View menu says so.

Nothing here depends on customtkinter so that GUI-free code (cores, CLI,
tests) can import it.
"""
from __future__ import annotations

import os
import sys
from typing import Dict

try:
    from scripts.common import app_config
except Exception:  # pragma: no cover - import-order fallback
    app_config = None

PALETTES: Dict[str, Dict[str, str]] = {
    # Neutral light scheme: grey chrome, white work area, one restrained accent.
    "light": {
        "BG_WINDOW": "#E9ECEF",   # window background
        "BG_PANEL": "#F4F5F7",    # side panels / toolbar
        "BG_CARD": "#FFFFFF",     # cards, plot area
        "BG_SUB": "#F0F1F3",      # inputs, secondary buttons
        "BG_HOVER": "#E3E6EA",
        "BORDER": "#CFD4DA",
        "BORDER_HI": "#B8BEC6",
        "ACCENT": "#1F5FA8",      # primary action
        "ACCENT_HOV": "#174A85",
        "GREEN": "#2E7D32",
        "GREEN_HOV": "#1B5E20",
        "ORANGE": "#C2410C",
        "PURPLE": "#5B3FA0",
        "PINK": "#A4327A",
        "RED": "#B3261E",
        "TXT": "#1B1F24",
        "TXT_SUB": "#5A6472",
        "TXT_DIM": "#8A939E",
        "TXT_MUTED": "#3A4350",
        "PLOT_BG": "#FFFFFF",
        "PLOT_AXES": "#FFFFFF",
        "PLOT_FG": "#1B1F24",
        "PLOT_TICK": "#3A4350",
        "PLOT_GRID": "#D5D9DF",
        "PLOT_SPINE": "#6B7480",
        "PLOT_REF": "#9AA3AE",
        "SELECT": "#CFE0F5",
        "HEADER_BG": "#DDE2E8",   # panel header strip (dock-panel title bar)
        "HEADER_TXT": "#27303B",
        "STRIPE": "#F4F6F8",      # alternate table row
        "TOOL_BG": "#E6E9ED",     # toolbar and status bar
    },
    "dark": {
        "BG_WINDOW": "#16181C",
        "BG_PANEL": "#1C1F24",
        "BG_CARD": "#23272D",
        "BG_SUB": "#2B3037",
        "BG_HOVER": "#353B43",
        "BORDER": "#343A42",
        "BORDER_HI": "#46505A",
        "ACCENT": "#4C8DDA",
        "ACCENT_HOV": "#3B74B8",
        "GREEN": "#4CAF72",
        "GREEN_HOV": "#3D8F5D",
        "ORANGE": "#E08E3C",
        "PURPLE": "#9A7BD6",
        "PINK": "#D56AA8",
        "RED": "#E0574F",
        "TXT": "#E8EAED",
        "TXT_SUB": "#A4ACB6",
        "TXT_DIM": "#737C87",
        "TXT_MUTED": "#C9CED4",
        "PLOT_BG": "#23272D",
        "PLOT_AXES": "#1D2126",
        "PLOT_FG": "#E8EAED",
        "PLOT_TICK": "#B8BEC6",
        "PLOT_GRID": "#363C44",
        "PLOT_SPINE": "#5A636E",
        "PLOT_REF": "#6B7480",
        "SELECT": "#355A86",
        "HEADER_BG": "#2B3139",
        "HEADER_TXT": "#D3D8DE",
        "STRIPE": "#262A30",
        "TOOL_BG": "#1A1D21",
    },
}

# Series colours: a colour-blind-safe, print-safe sequence (Okabe-Ito order
# with a darker yellow), the same in both themes.
SERIES_COLORS = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00",
                 "#56B4E9", "#B8860B", "#6A3D9A", "#A6761D", "#1B9E77"]


def available_themes():
    return tuple(PALETTES)


def _configured_theme() -> str:
    env = os.environ.get("PHYSISCORE_THEME")
    if env and env.lower() in PALETTES:
        return env.lower()
    if app_config is not None:
        try:
            value = str(app_config.get("theme", "light") or "light").lower()
            if value in PALETTES:
                return value
        except Exception:
            pass
    return "light"


THEME = _configured_theme()
_P = PALETTES[THEME]

BG_WINDOW = _P["BG_WINDOW"]
BG_PANEL = _P["BG_PANEL"]
BG_CARD = _P["BG_CARD"]
BG_SUB = _P["BG_SUB"]
BG_HOVER = _P["BG_HOVER"]
BORDER = _P["BORDER"]
BORDER_HI = _P["BORDER_HI"]
ACCENT = _P["ACCENT"]
ACCENT_HOV = _P["ACCENT_HOV"]
GREEN = _P["GREEN"]
GREEN_HOV = _P["GREEN_HOV"]
ORANGE = _P["ORANGE"]
PURPLE = _P["PURPLE"]
PINK = _P["PINK"]
RED = _P["RED"]
TXT = _P["TXT"]
TXT_SUB = _P["TXT_SUB"]
TXT_DIM = _P["TXT_DIM"]
TXT_MUTED = _P["TXT_MUTED"]
PLOT_BG = _P["PLOT_BG"]
PLOT_AXES = _P["PLOT_AXES"]
PLOT_FG = _P["PLOT_FG"]
PLOT_TICK = _P["PLOT_TICK"]
PLOT_GRID = _P["PLOT_GRID"]
PLOT_SPINE = _P["PLOT_SPINE"]
PLOT_REF = _P["PLOT_REF"]
SELECT = _P["SELECT"]
HEADER_BG = _P["HEADER_BG"]
HEADER_TXT = _P["HEADER_TXT"]
STRIPE = _P["STRIPE"]
TOOL_BG = _P["TOOL_BG"]
IS_DARK = THEME == "dark"

# Geometry: square corners and compact spacing, as in instrument software
# (3.2: radii 4/6/3 -> 2; every window takes its radii from these tokens).
R_PILL = 2
R_CARD = 2
R_INPUT = 2

# Type: one point smaller than the size a window asks for (3.2), which gives
# the dense read-outs of measurement software without editing every window.
FONT_DELTA = -1


def _ui_font_family() -> str:
    if sys.platform == "win32":
        return "Segoe UI"
    if sys.platform == "darwin":
        return "Helvetica Neue"
    return "DejaVu Sans"


def _mono_font_family() -> str:
    if sys.platform == "win32":
        return "Consolas"
    if sys.platform == "darwin":
        return "Menlo"
    return "DejaVu Sans Mono"


FONT_UI = _ui_font_family()
FONT_MONO = _mono_font_family()


def _size(size) -> int:
    return max(8, int(size) + FONT_DELTA)


def font(size: int = 12, weight: str | None = None):
    """Tk font tuple in the platform UI family (compact: FONT_DELTA applied)."""
    return (FONT_UI, _size(size), weight) if weight else (FONT_UI, _size(size))


def mono(size: int = 11, weight: str | None = None):
    return (FONT_MONO, _size(size), weight) if weight else (FONT_MONO, _size(size))


# Matplotlib rcParams for on-screen figures: white/neutral axes, inward
# ticks on all four sides, thin grid - the convention of Origin-style lab
# plots rather than a web dashboard.
MPL_STYLE = {
    "figure.facecolor": PLOT_BG,
    "axes.facecolor": PLOT_AXES,
    "axes.edgecolor": PLOT_SPINE,
    "axes.labelcolor": PLOT_FG,
    "axes.linewidth": 1.0,
    "axes.titlesize": 11,
    "axes.labelsize": 10.5,
    "xtick.color": PLOT_TICK,
    "ytick.color": PLOT_TICK,
    "xtick.direction": "in",
    "ytick.direction": "in",
    "xtick.top": True,
    "ytick.right": True,
    "xtick.labelsize": 9.5,
    "ytick.labelsize": 9.5,
    "text.color": PLOT_FG,
    "grid.color": PLOT_GRID,
    "grid.linestyle": "-",
    "grid.linewidth": 0.6,
    "grid.alpha": 0.8,
    "legend.facecolor": PLOT_AXES,
    "legend.edgecolor": PLOT_SPINE,
    "legend.fontsize": 9,
    "legend.framealpha": 0.95,
    "lines.linewidth": 1.5,
    "axes.prop_cycle": None,  # set in apply_mpl()
    "font.family": "sans-serif",
    "font.sans-serif": [FONT_UI, "Arial", "Helvetica", "DejaVu Sans"],
    "mathtext.fontset": "dejavusans",
}


def apply_mpl() -> None:
    """Install the screen style into matplotlib's rcParams (idempotent)."""
    import matplotlib
    from cycler import cycler
    for k, v in MPL_STYLE.items():
        if k == "axes.prop_cycle":
            matplotlib.rcParams[k] = cycler(color=SERIES_COLORS)
            continue
        try:
            matplotlib.rcParams[k] = v
        except Exception:
            pass


def style_axes(ax, grid: bool = True) -> None:
    """Apply the screen style to an existing Axes (after ax.clear())."""
    ax.set_facecolor(PLOT_AXES)
    for sp in ax.spines.values():
        sp.set_color(PLOT_SPINE)
        sp.set_linewidth(1.0)
    ax.tick_params(axis="both", which="both", colors=PLOT_TICK, direction="in", top=True, right=True,
                   labelsize=9.5)
    ax.xaxis.label.set_color(PLOT_FG)
    ax.yaxis.label.set_color(PLOT_FG)
    ax.title.set_color(PLOT_FG)
    if grid:
        ax.grid(True, color=PLOT_GRID, linestyle="-", linewidth=0.6, alpha=0.8)
    else:
        ax.grid(False)


def style_figure(fig) -> None:
    fig.patch.set_facecolor(PLOT_BG)
    for ax in fig.axes:
        style_axes(ax, grid=False)


def series_color(i: int) -> str:
    return SERIES_COLORS[i % len(SERIES_COLORS)]
