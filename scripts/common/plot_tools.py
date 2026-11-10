"""Shared graph tools for every analysis window (3.5).

Four things the plot windows had no common answer for:

    data reader     click a curve to read the nearest measured point; a second
                    click gives the differences and the slope between the two
    plot details    axis titles, limits, scales and the style of each curve
    figure export   journal presets - width and height in mm, font size, dpi
    data worksheet  the numbers behind every curve of the figure, as a table
                    that can be copied to Origin or Excel or saved as CSV

The geometry and the export are plain functions, so they are tested without a
display; the dialogs are thin Tk layers over them. Nothing here changes the
analysis: these tools act on the figure that is already on screen.
"""
from __future__ import annotations

import math
import os
import pickle
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

MM = 1.0 / 25.4                      # inch per millimetre

# width, height (mm) and font size (pt). The widths are the usual one, one and
# a half and two column widths of two-column journals.
PRESETS: Dict[str, Optional[Dict[str, float]]] = {
    "Single column (85 mm)": dict(width_mm=85.0, height_mm=64.0, font_pt=8.0, line_pt=1.0),
    "1.5 column (114 mm)": dict(width_mm=114.0, height_mm=86.0, font_pt=8.0, line_pt=1.0),
    "Double column (174 mm)": dict(width_mm=174.0, height_mm=110.0, font_pt=9.0, line_pt=1.2),
    "Slide 16:9 (254 mm)": dict(width_mm=254.0, height_mm=143.0, font_pt=14.0, line_pt=2.0),
    "As displayed": None,
}
FORMATS = {"PNG": ".png", "TIFF": ".tif", "PDF": ".pdf", "SVG": ".svg", "EPS": ".eps"}
LINE_STYLES = {"solid": "-", "dashed": "--", "dotted": ":", "dash-dot": "-.", "none": "None"}
MARKERS = {"none": "None", "circle": "o", "square": "s", "triangle": "^", "diamond": "D",
           "cross": "x", "plus": "+"}


# --------------------------------------------------------------------------- curves
def _is_data_line(ax, line) -> bool:
    """A curve drawn in data coordinates (not an axhline/axvline, not a marker
    the data reader put there)."""
    if getattr(line, "_physiscore_reader", False):
        return False
    try:
        return line.get_transform() == ax.transData and len(line.get_xdata()) > 0
    except Exception:
        return False


def curves(ax, min_points: int = 1) -> List[Dict[str, Any]]:
    """Curves of one axes: lines first, then scatter collections."""
    out = []
    n = 0
    for line in ax.get_lines():
        if not _is_data_line(ax, line):
            continue
        try:
            x = np.asarray(line.get_xdata(orig=False), float)
            y = np.asarray(line.get_ydata(orig=False), float)
        except Exception:
            continue
        if len(x) < min_points or len(x) != len(y):
            continue
        n += 1
        label = str(line.get_label() or "")
        out.append({"label": label if label and not label.startswith("_") else f"curve {n}",
                    "named": bool(label and not label.startswith("_")),
                    "x": x, "y": y, "artist": line})
    for col in ax.collections:
        try:
            off = np.asarray(col.get_offsets(), float)
        except Exception:
            continue
        if off.ndim != 2 or off.shape[0] < min_points or off.shape[1] != 2:
            continue
        n += 1
        label = str(col.get_label() or "")
        out.append({"label": label if label and not label.startswith("_") else f"points {n}",
                    "named": bool(label and not label.startswith("_")),
                    "x": off[:, 0], "y": off[:, 1], "artist": col})
    return out


def nearest_point(fig, x_px: float, y_px: float, max_px: float = 40.0) -> Optional[Dict[str, Any]]:
    """The data point of any curve in the figure closest to a display position
    (pixels). None when nothing lies within `max_px`."""
    best = None
    for ax in fig.axes:
        for c in curves(ax):
            x, y = c["x"], c["y"]
            ok = np.isfinite(x) & np.isfinite(y)
            if ax.get_xscale() == "log":
                ok &= x > 0
            if ax.get_yscale() == "log":
                ok &= y > 0
            if not np.any(ok):
                continue
            idx = np.nonzero(ok)[0]
            try:
                disp = ax.transData.transform(np.column_stack([x[idx], y[idx]]))
            except Exception:
                continue
            d = np.hypot(disp[:, 0] - x_px, disp[:, 1] - y_px)
            if not np.any(np.isfinite(d)):
                continue
            k = int(np.nanargmin(d))
            if best is None or d[k] < best["dist"]:
                best = {"ax": ax, "label": c["label"], "x": float(x[idx[k]]), "y": float(y[idx[k]]),
                        "index": int(idx[k]), "dist": float(d[k])}
    if best is None or best["dist"] > max_px:
        return None
    return best


def _g(v: float) -> str:
    return f"{v:.5g}"


def point_text(p: Dict[str, Any]) -> str:
    return f"{p['label']}:  x = {_g(p['x'])}   y = {_g(p['y'])}   (point {p['index'] + 1})"


def two_point_text(p1: Dict[str, Any], p2: Dict[str, Any], xlog: bool = False, ylog: bool = False) -> str:
    """Differences between two read points. On logarithmic axes the slope that
    matters is the one of the straight line seen on screen, so it is given in
    the same units: d log y / d log x, or decades of y per unit of x."""
    dx, dy = p2["x"] - p1["x"], p2["y"] - p1["y"]
    parts = [f"dx = {_g(dx)}", f"dy = {_g(dy)}"]
    if dx != 0:
        parts.append(f"dy/dx = {_g(dy / dx)}")
    pos = p1["x"] > 0 and p2["x"] > 0
    posy = p1["y"] > 0 and p2["y"] > 0
    if xlog and ylog and pos and posy and p1["x"] != p2["x"]:
        parts.append(f"log-log slope = {_g(math.log10(p2['y'] / p1['y']) / math.log10(p2['x'] / p1['x']))}")
    elif ylog and posy and dx != 0:
        parts.append(f"decades of y per x = {_g(math.log10(p2['y'] / p1['y']) / dx)}")
    elif xlog and pos and p1["x"] != p2["x"]:
        parts.append(f"dy per decade of x = {_g(dy / math.log10(p2['x'] / p1['x']))}")
    return "   ".join(parts)


# --------------------------------------------------------------------------- worksheet
def figure_table(fig):
    """Every curve of the figure as X/Y column pairs (the layout of an Origin
    worksheet). Columns are padded with NaN to the longest curve."""
    import pandas as pd
    cols: Dict[str, np.ndarray] = {}
    many_axes = len(fig.axes) > 1
    for ia, ax in enumerate(fig.axes):
        xl = (ax.get_xlabel() or "x").replace("\n", " ")
        yl = (ax.get_ylabel() or "y").replace("\n", " ")
        prefix = f"[{ia + 1}] " if many_axes else ""
        for c in curves(ax, min_points=2):
            base = f"{prefix}{c['label']}"
            kx, ky = f"{base} | {xl}", f"{base} | {yl}"
            k = 2
            while kx in cols or ky in cols:
                kx, ky = f"{base} ({k}) | {xl}", f"{base} ({k}) | {yl}"
                k += 1
            cols[kx], cols[ky] = c["x"], c["y"]
    if not cols:
        return pd.DataFrame()
    n = max(len(v) for v in cols.values())
    return pd.DataFrame({k: np.concatenate([v, np.full(n - len(v), np.nan)]) for k, v in cols.items()})


def column_letters(n: int) -> List[str]:
    """A, B, ... Z, AA, AB ... with the X/Y designation Origin shows."""
    out = []
    for i in range(n):
        s, k = "", i
        while True:
            s = chr(65 + k % 26) + s
            k = k // 26 - 1
            if k < 0:
                break
        out.append(f"{s}({'X' if i % 2 == 0 else 'Y'})")
    return out


# --------------------------------------------------------------------------- export
def _copy(fig, publication: bool):
    if publication:
        try:
            from scripts.common.analysis_shell import _publication_copy
            pub = _publication_copy(fig)
            if pub is not None:
                return pub
        except Exception:
            pass
    try:
        return pickle.loads(pickle.dumps(fig))
    except Exception:
        return None


def pixel_size(width_mm: float, height_mm: float, dpi: float) -> Tuple[int, int]:
    """Pixels of a raster file of this physical size. The renderer cuts a
    fractional pixel off rather than rounding it, so 85 mm at 600 dpi is 2007
    pixels wide, not 2008."""
    return int(float(width_mm) * MM * float(dpi)), int(float(height_mm) * MM * float(dpi))


def export_figure(fig, path: str, width_mm: Optional[float] = None, height_mm: Optional[float] = None,
                  font_pt: Optional[float] = None, dpi: int = 600, publication: bool = True,
                  transparent: bool = False, line_pt: Optional[float] = None) -> Dict[str, Any]:
    """Save a copy of `fig` at a stated physical size. The figure on screen is
    never modified. With a size given the file has exactly that size (no tight
    cropping), which is what a journal's column width asks for. Returns the
    size written."""
    work = _copy(fig, publication)
    own = work is not None
    if work is None:
        work = fig                                   # cannot be copied: save as displayed
    sized = bool(own and width_mm and height_mm)
    if sized:
        work.set_size_inches(float(width_mm) * MM, float(height_mm) * MM)
    if own and font_pt:
        f = float(font_pt)
        for ax in work.axes:
            ax.title.set_fontsize(f)
            ax.xaxis.label.set_fontsize(f)
            ax.yaxis.label.set_fontsize(f)
            ax.tick_params(axis="both", which="both", labelsize=f)
            leg = ax.get_legend()
            if leg is not None:
                for t in leg.get_texts():
                    t.set_fontsize(max(5.0, f - 1.0))
            for t in ax.texts:
                t.set_fontsize(max(5.0, f - 1.0))
        for t in work.texts:
            t.set_fontsize(f)
    if own and line_pt:
        w = float(line_pt)
        for ax in work.axes:
            for line in ax.get_lines():
                if line.get_linestyle() not in ("None", "", " "):
                    line.set_linewidth(w if line.get_linewidth() >= 1.0 else max(0.5, 0.6 * w))
                line.set_markersize(min(line.get_markersize(), 3.0 + 2.0 * w))
            for spine in ax.spines.values():
                spine.set_linewidth(max(0.5, 0.8 * w))
            ax.tick_params(axis="both", which="major", width=max(0.5, 0.8 * w), length=3.0 + w)
            ax.tick_params(axis="both", which="minor", width=max(0.4, 0.6 * w), length=1.5 + 0.5 * w)
    if sized:
        try:
            work.tight_layout(pad=0.6)
        except Exception:
            pass
    kw: Dict[str, Any] = {"dpi": int(dpi)}
    if transparent:
        kw["transparent"] = True
    else:
        kw["facecolor"] = "white" if publication else work.get_facecolor()
    if not sized:
        kw["bbox_inches"] = "tight"
    if path.lower().endswith((".tif", ".tiff")):
        kw["pil_kwargs"] = {"compression": "tiff_lzw"}
    work.savefig(path, **kw)
    w_in, h_in = work.get_size_inches()
    return {"path": path, "width_mm": float(w_in / MM), "height_mm": float(h_in / MM), "dpi": int(dpi),
            "pixels": (int(w_in * dpi), int(h_in * dpi)), "exact_size": sized}


# --------------------------------------------------------------------------- data reader
class DataReader:
    """Click-to-read on a matplotlib canvas. One click marks the nearest data
    point; the second click marks another and reports the differences; a third
    starts again."""

    def __init__(self, canvas, fig, on_text=None):
        self.canvas, self.fig, self.on_text = canvas, fig, on_text
        self.active = False
        self.points: List[Dict[str, Any]] = []
        self._artists: list = []
        self._cid = None

    def _say(self, text):
        if self.on_text:
            try:
                self.on_text(text)
            except Exception:
                pass

    def enable(self):
        if self.active:
            return
        self.active = True
        self._cid = self.canvas.mpl_connect("button_press_event", self._click)
        try:
            self.canvas.get_tk_widget().configure(cursor="crosshair")
        except Exception:
            pass
        self._say("Data reader on: click a curve; a second click gives the differences. Esc or the menu turns it off.")

    def disable(self):
        if not self.active:
            return
        self.active = False
        if self._cid is not None:
            try:
                self.canvas.mpl_disconnect(self._cid)
            except Exception:
                pass
            self._cid = None
        try:
            self.canvas.get_tk_widget().configure(cursor="")
        except Exception:
            pass
        self.clear()
        self._say("Data reader off")

    def toggle(self):
        self.disable() if self.active else self.enable()
        return self.active

    def clear(self):
        for a in self._artists:
            try:
                a.remove()
            except Exception:
                pass
        self._artists = []
        self.points = []
        try:
            self.canvas.draw_idle()
        except Exception:
            pass

    def _click(self, ev):
        if getattr(ev, "button", None) != 1 or ev.x is None or ev.y is None:
            return
        self.read_at(ev.x, ev.y)

    def read_at(self, x_px, y_px):
        """Read the point nearest to a display position; returns the text shown."""
        from scripts.common import palette as _pal
        hit = nearest_point(self.fig, x_px, y_px)
        if hit is None:
            self._say("Data reader: no data point near the cursor")
            return ""
        if len(self.points) >= 2:
            self.clear()
        ax = hit["ax"]
        n = len(self.points) + 1
        mark, = ax.plot([hit["x"]], [hit["y"]], linestyle="None", marker="o", markersize=10,
                        markerfacecolor="none", markeredgecolor=_pal.RED, markeredgewidth=1.6,
                        zorder=60, scalex=False, scaley=False)
        mark._physiscore_reader = True
        note = ax.annotate(f"{n}: ({_g(hit['x'])}, {_g(hit['y'])})", xy=(hit["x"], hit["y"]),
                           xytext=(9, 9), textcoords="offset points", fontsize=8.5, color=_pal.TXT,
                           bbox=dict(boxstyle="square,pad=0.3", fc=_pal.BG_CARD, ec=_pal.BORDER_HI, lw=0.8),
                           zorder=61, annotation_clip=False)
        self._artists += [mark, note]
        self.points.append(hit)
        text = point_text(hit)
        if len(self.points) == 2 and self.points[0]["ax"] is self.points[1]["ax"]:
            p1, p2 = self.points
            link, = ax.plot([p1["x"], p2["x"]], [p1["y"], p2["y"]], linestyle="--", linewidth=1.0,
                            color=_pal.RED, zorder=59, scalex=False, scaley=False)
            link._physiscore_reader = True
            self._artists.append(link)
            text = two_point_text(p1, p2, ax.get_xscale() == "log", ax.get_yscale() == "log")
        try:
            self.canvas.draw_idle()
        except Exception:
            pass
        self._say(text)
        return text


def reader_for(owner, canvas, fig) -> DataReader:
    """The one reader of a canvas (created on first use, kept on the canvas)."""
    rd = getattr(canvas, "_physiscore_reader_obj", None)
    if rd is None or rd.fig is not fig:
        def say(text):
            try:
                from scripts.common import analysis_shell as _shell
                _shell.set_status(owner, text)
            except Exception:
                pass
        rd = DataReader(canvas, fig, on_text=say)
        canvas._physiscore_reader_obj = rd
        try:
            canvas.get_tk_widget().bind("<Escape>", lambda e: rd.disable(), add="+")
            owner.bind("<Escape>", lambda e: rd.disable(), add="+")
        except Exception:
            pass
    return rd


def toggle_reader(owner, canvas, fig) -> bool:
    return reader_for(owner, canvas, fig).toggle()


# --------------------------------------------------------------------------- dialogs
def _dialog(parent, title, geometry):
    import customtkinter as ctk
    from scripts.common import palette as _pal
    top = ctk.CTkToplevel(parent)
    top.title(title)
    top.geometry(geometry)
    top.configure(fg_color=_pal.BG_WINDOW)
    try:
        top.transient(parent)
    except Exception:
        pass
    top.after(120, lambda: (top.lift(), top.focus_force()))
    return top


def _float_or_none(text: str) -> Optional[float]:
    text = (text or "").strip()
    if not text or text.lower() in ("auto", "-"):
        return None
    return float(text)


class PlotDetailsDialog:
    """Axis titles, ranges, scales and curve styles of the figure on screen."""

    def __init__(self, parent, fig, canvas=None):
        import tkinter as tk
        from tkinter import ttk
        import customtkinter as ctk
        from scripts.common import palette as _pal
        from scripts.common import theme as _theme
        self.fig, self.canvas = fig, canvas or getattr(fig, "canvas", None)
        self._pal, self._ctk = _pal, ctk
        self.top = top = _dialog(parent, "Plot details", "760x560")
        top.grid_columnconfigure(1, weight=1)
        top.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(top, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 4))
        ctk.CTkLabel(head, text="Axes", font=_pal.font(11, "bold"), text_color=_pal.TXT_SUB).pack(side="left")
        names = [self._axes_name(i, ax) for i, ax in enumerate(fig.axes)] or ["(no axes)"]
        self.var_axes = tk.StringVar(value=names[0])
        self.opt_axes = ctk.CTkOptionMenu(head, values=names, variable=self.var_axes, width=320, height=26,
                                          fg_color=_pal.BG_SUB, button_color=_pal.BG_SUB,
                                          button_hover_color=_pal.BG_HOVER, text_color=_pal.TXT,
                                          font=_pal.font(11), corner_radius=_pal.R_INPUT,
                                          command=lambda _v: self._load())
        self.opt_axes.pack(side="left", padx=8)

        # ---- axis settings
        gf, g = _theme.group(top, "Axis")
        gf.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=4)
        self.v: Dict[str, Any] = {}

        def row(r, label, key, width=180):
            ctk.CTkLabel(g, text=label, font=_pal.font(11), text_color=_pal.TXT, anchor="w").grid(
                row=r, column=0, sticky="w", padx=(2, 8), pady=3)
            var = tk.StringVar()
            _theme.entry(g, width=width, textvariable=var).grid(row=r, column=1, columnspan=2, sticky="w", pady=3)
            self.v[key] = var

        row(0, "Title", "title")
        row(1, "X title", "xlabel")
        row(2, "Y title", "ylabel")
        for r, (label, k0, k1) in enumerate((("X from / to", "xmin", "xmax"), ("Y from / to", "ymin", "ymax")), start=3):
            ctk.CTkLabel(g, text=label, font=_pal.font(11), text_color=_pal.TXT, anchor="w").grid(
                row=r, column=0, sticky="w", padx=(2, 8), pady=3)
            for c, k in enumerate((k0, k1), start=1):
                var = tk.StringVar()
                _theme.entry(g, width=86, textvariable=var).grid(row=r, column=c, sticky="w", padx=(0, 8), pady=3)
                self.v[k] = var
        for r, (label, key) in enumerate((("X scale", "xscale"), ("Y scale", "yscale")), start=5):
            ctk.CTkLabel(g, text=label, font=_pal.font(11), text_color=_pal.TXT, anchor="w").grid(
                row=r, column=0, sticky="w", padx=(2, 8), pady=3)
            var = tk.StringVar(value="linear")
            seg = ctk.CTkSegmentedButton(g, values=["linear", "log"], variable=var, height=24, font=_pal.font(11),
                                         selected_color=_pal.ACCENT, selected_hover_color=_pal.ACCENT_HOV,
                                         unselected_color=_pal.BG_SUB, unselected_hover_color=_pal.BG_HOVER,
                                         text_color=_pal.TXT, corner_radius=_pal.R_PILL)
            seg.grid(row=r, column=1, columnspan=2, sticky="w", pady=3)
            self.v[key] = var
        self.v["grid"] = tk.BooleanVar(value=False)
        self.v["legend"] = tk.BooleanVar(value=True)
        for r, (label, key) in enumerate((("Grid lines", "grid"), ("Legend", "legend")), start=7):
            ctk.CTkCheckBox(g, text=label, variable=self.v[key], font=_pal.font(11), text_color=_pal.TXT,
                            checkbox_width=16, checkbox_height=16, corner_radius=2, border_width=1,
                            fg_color=_pal.ACCENT, hover_color=_pal.ACCENT_HOV).grid(
                row=r, column=0, columnspan=3, sticky="w", padx=2, pady=4)
        ctk.CTkLabel(g, text="Leave a range empty for automatic limits.", font=_pal.font(10),
                     text_color=_pal.TXT_MUTED, anchor="w").grid(row=9, column=0, columnspan=3, sticky="w",
                                                                 padx=2, pady=(6, 0))

        # ---- curves
        cf, c = _theme.group(top, "Curves")
        cf.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=4)
        _theme.style_treeview(rowheight=22)
        self.tree = ttk.Treeview(c, columns=("n", "w", "s", "m", "v"), show="headings", height=8,
                                 selectmode="browse")
        for col, text, width in (("n", "Curve", 170), ("w", "Width", 50), ("s", "Line", 70),
                                 ("m", "Symbol", 70), ("v", "Shown", 50)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w" if col == "n" else "center", stretch=(col == "n"))
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._load_curve())

        ed = ctk.CTkFrame(c, fg_color="transparent")
        ed.pack(fill="x", pady=(8, 0))
        self.c: Dict[str, Any] = {"label": tk.StringVar(), "width": tk.StringVar(value="1.6"),
                                  "style": tk.StringVar(value="solid"), "marker": tk.StringVar(value="none"),
                                  "shown": tk.BooleanVar(value=True), "color": None}
        ctk.CTkLabel(ed, text="Name", font=_pal.font(11), text_color=_pal.TXT).grid(row=0, column=0, sticky="w", pady=3)
        _theme.entry(ed, width=200, textvariable=self.c["label"]).grid(row=0, column=1, columnspan=3, sticky="w",
                                                                       padx=6, pady=3)
        ctk.CTkLabel(ed, text="Width", font=_pal.font(11), text_color=_pal.TXT).grid(row=1, column=0, sticky="w", pady=3)
        _theme.entry(ed, width=60, textvariable=self.c["width"]).grid(row=1, column=1, sticky="w", padx=6, pady=3)

        def option(r, col, label, key, values):
            ctk.CTkLabel(ed, text=label, font=_pal.font(11), text_color=_pal.TXT).grid(row=r, column=col, sticky="w",
                                                                                       pady=3)
            ctk.CTkOptionMenu(ed, values=list(values), variable=self.c[key], width=96, height=24,
                              fg_color=_pal.BG_SUB, button_color=_pal.BG_SUB, button_hover_color=_pal.BG_HOVER,
                              text_color=_pal.TXT, font=_pal.font(11), corner_radius=_pal.R_INPUT).grid(
                row=r, column=col + 1, sticky="w", padx=6, pady=3)

        option(2, 0, "Line", "style", LINE_STYLES)
        option(2, 2, "Symbol", "marker", MARKERS)
        ctk.CTkLabel(ed, text="Colour", font=_pal.font(11), text_color=_pal.TXT).grid(row=3, column=0, sticky="w", pady=3)
        sw = ctk.CTkFrame(ed, fg_color="transparent")
        sw.grid(row=3, column=1, columnspan=3, sticky="w", padx=6, pady=3)
        self._swatches = []
        colours = [_pal.series_color(i) for i in range(8)] + [_pal.PLOT_FG, _pal.TXT_MUTED]
        for col in colours:
            b = ctk.CTkButton(sw, text="", width=20, height=20, fg_color=col, hover_color=col, corner_radius=2,
                              border_width=1, border_color=_pal.BORDER, command=lambda col=col: self._pick(col))
            b.pack(side="left", padx=2)
            self._swatches.append((col, b))
        ctk.CTkCheckBox(ed, text="Shown", variable=self.c["shown"], font=_pal.font(11), text_color=_pal.TXT,
                        checkbox_width=16, checkbox_height=16, corner_radius=2, border_width=1,
                        fg_color=_pal.ACCENT, hover_color=_pal.ACCENT_HOV).grid(row=4, column=0, columnspan=2,
                                                                               sticky="w", pady=4)
        _theme.secondary_button(ed, "Apply to curve", command=self.apply_curve, width=120).grid(
            row=4, column=2, columnspan=2, sticky="e", pady=4)

        foot = ctk.CTkFrame(top, fg_color="transparent")
        foot.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=(4, 10))
        _theme.secondary_button(foot, "Close", command=top.destroy, width=90).pack(side="right", padx=(6, 0))
        ctk.CTkButton(foot, text="Apply", width=90, height=28, fg_color=_pal.ACCENT, hover_color=_pal.ACCENT_HOV,
                      text_color="white", corner_radius=_pal.R_PILL, font=_pal.font(11, "bold"),
                      command=self.apply_axes).pack(side="right", padx=(6, 0))
        _theme.secondary_button(foot, "Auto range", command=self.auto_range, width=100).pack(side="right")
        self.lbl = ctk.CTkLabel(foot, text="Changes act on the graph on screen; a new run redraws it.",
                                font=_pal.font(10), text_color=_pal.TXT_MUTED, anchor="w")
        self.lbl.pack(side="left")
        self._curves: List[Dict[str, Any]] = []
        self._load()

    # ---- helpers
    @staticmethod
    def _axes_name(i, ax):
        y = (ax.get_ylabel() or "").replace("\n", " ")
        x = (ax.get_xlabel() or "").replace("\n", " ")
        return f"{i + 1}: {y or 'y'} vs {x or 'x'}"[:60]

    def _ax(self):
        if not self.fig.axes:
            return None
        try:
            i = int(self.var_axes.get().split(":")[0]) - 1
        except Exception:
            i = 0
        return self.fig.axes[max(0, min(i, len(self.fig.axes) - 1))]

    def _redraw(self):
        try:
            self.canvas.draw_idle()
        except Exception:
            pass

    def _load(self):
        ax = self._ax()
        if ax is None:
            return
        self.v["title"].set(ax.get_title())
        self.v["xlabel"].set(ax.get_xlabel())
        self.v["ylabel"].set(ax.get_ylabel())
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
        for k, val in (("xmin", x0), ("xmax", x1), ("ymin", y0), ("ymax", y1)):
            self.v[k].set(_g(val))
        self.v["xscale"].set("log" if ax.get_xscale() == "log" else "linear")
        self.v["yscale"].set("log" if ax.get_yscale() == "log" else "linear")
        self.v["grid"].set(bool(getattr(ax, "_physiscore_grid", False)))
        leg = ax.get_legend()
        self.v["legend"].set(bool(leg is not None and leg.get_visible()))
        self._fill_curves()

    def _fill_curves(self):
        ax = self._ax()
        self._curves = [c for c in curves(ax) if hasattr(c["artist"], "get_linestyle")
                        and hasattr(c["artist"], "set_marker")]
        self.tree.delete(*self.tree.get_children())
        inv_s = {v: k for k, v in LINE_STYLES.items()}
        inv_m = {v: k for k, v in MARKERS.items()}
        for i, c in enumerate(self._curves):
            a = c["artist"]
            self.tree.insert("", "end", iid=str(i), values=(
                c["label"], f"{a.get_linewidth():.2g}", inv_s.get(str(a.get_linestyle()), str(a.get_linestyle())),
                inv_m.get(str(a.get_marker()), str(a.get_marker())), "yes" if a.get_visible() else "no"))
        if self._curves:
            self.tree.selection_set("0")

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return self._curves[int(sel[0])]
        except Exception:
            return None

    def _load_curve(self):
        c = self._selected()
        if c is None:
            return
        a = c["artist"]
        inv_s = {v: k for k, v in LINE_STYLES.items()}
        inv_m = {v: k for k, v in MARKERS.items()}
        self.c["label"].set(c["label"] if c["named"] else "")
        self.c["width"].set(f"{a.get_linewidth():.2g}")
        self.c["style"].set(inv_s.get(str(a.get_linestyle()), "solid"))
        self.c["marker"].set(inv_m.get(str(a.get_marker()), "none"))
        self.c["shown"].set(bool(a.get_visible()))
        self._pick(None)

    def _pick(self, colour):
        self.c["color"] = colour
        for col, b in self._swatches:
            try:
                b.configure(border_width=3 if col == colour else 1,
                            border_color=self._pal.TXT if col == colour else self._pal.BORDER)
            except Exception:
                pass

    # ---- actions
    def apply_curve(self):
        from tkinter import messagebox
        c = self._selected()
        if c is None:
            return
        a = c["artist"]
        try:
            width = float(self.c["width"].get())
        except ValueError:
            messagebox.showerror("Plot details", "Width: not a number", parent=self.top)
            return
        a.set_linewidth(max(0.1, width))
        a.set_linestyle(LINE_STYLES.get(self.c["style"].get(), "-"))
        a.set_marker(MARKERS.get(self.c["marker"].get(), "None"))
        a.set_visible(bool(self.c["shown"].get()))
        if self.c["color"]:
            a.set_color(self.c["color"])
        name = self.c["label"].get().strip()
        if name:
            a.set_label(name)
        ax = self._ax()
        leg = ax.get_legend()
        if leg is not None:
            try:
                from scripts.common import plot_interactions as _pi
                shown = leg.get_visible()
                _pi.smart_legend(ax)
                if ax.get_legend() is not None:
                    ax.get_legend().set_visible(shown)
            except Exception:
                pass
        keep = self.tree.selection()
        self._fill_curves()
        if keep and self.tree.exists(keep[0]):
            self.tree.selection_set(keep[0])
        self._redraw()

    def apply_axes(self):
        from tkinter import messagebox
        ax = self._ax()
        if ax is None:
            return
        try:
            lim = {k: _float_or_none(self.v[k].get()) for k in ("xmin", "xmax", "ymin", "ymax")}
        except ValueError:
            messagebox.showerror("Plot details", "A range value is not a number.", parent=self.top)
            return
        for axis, lo, hi in (("x", lim["xmin"], lim["xmax"]), ("y", lim["ymin"], lim["ymax"])):
            if self.v[axis + "scale"].get() == "log" and any(v is not None and v <= 0 for v in (lo, hi)):
                messagebox.showerror("Plot details", f"{axis.upper()} range: a logarithmic axis needs limits above zero.",
                                     parent=self.top)
                return
        ax.set_title(self.v["title"].get())
        ax.set_xlabel(self.v["xlabel"].get())
        ax.set_ylabel(self.v["ylabel"].get())
        try:
            ax.set_xscale(self.v["xscale"].get())
            ax.set_yscale(self.v["yscale"].get())
        except Exception as e:
            messagebox.showerror("Plot details", f"Scale: {e}", parent=self.top)
            return
        if lim["xmin"] is None and lim["xmax"] is None:
            ax.autoscale(enable=True, axis="x")
        else:
            ax.set_xlim(left=lim["xmin"], right=lim["xmax"])
        if lim["ymin"] is None and lim["ymax"] is None:
            ax.autoscale(enable=True, axis="y")
        else:
            ax.set_ylim(bottom=lim["ymin"], top=lim["ymax"])
        on = bool(self.v["grid"].get())
        ax._physiscore_grid = on
        ax.grid(on, color=self._pal.PLOT_GRID, linewidth=0.6)
        leg = ax.get_legend()
        if self.v["legend"].get() and leg is None:
            try:
                from scripts.common import plot_interactions as _pi
                _pi.smart_legend(ax)
            except Exception:
                pass
        elif leg is not None:
            leg.set_visible(bool(self.v["legend"].get()))
        self._redraw()

    def auto_range(self):
        ax = self._ax()
        if ax is None:
            return
        ax.relim(visible_only=True)
        ax.autoscale(enable=True, axis="both")
        ax.autoscale_view()
        self._redraw()
        try:
            self.fig.canvas.draw()
        except Exception:
            pass
        self._load()


class ExportDialog:
    """Figure export at a stated physical size."""

    def __init__(self, parent, fig, on_saved=None):
        import tkinter as tk
        import customtkinter as ctk
        from scripts.common import palette as _pal
        from scripts.common import theme as _theme
        from scripts.common import app_config
        self.fig, self.on_saved = fig, on_saved
        self.top = top = _dialog(parent, "Export figure", "470x430")
        last = app_config.get("figure_export", {}) or {}
        gf, g = _theme.group(top, "Size and style")
        gf.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        g.grid_columnconfigure(1, weight=1)
        self.v = {
            "preset": tk.StringVar(value=last.get("preset") if last.get("preset") in PRESETS else next(iter(PRESETS))),
            "width": tk.StringVar(), "height": tk.StringVar(), "font": tk.StringVar(), "line": tk.StringVar(),
            "dpi": tk.StringVar(value=str(last.get("dpi", 600))),
            "format": tk.StringVar(value=last.get("format") if last.get("format") in FORMATS else "PNG"),
            "style": tk.StringVar(value=last.get("style", "Publication")),
            "transparent": tk.BooleanVar(value=bool(last.get("transparent", False))),
        }

        def label(r, text):
            ctk.CTkLabel(g, text=text, font=_pal.font(11), text_color=_pal.TXT, anchor="w").grid(
                row=r, column=0, sticky="w", padx=(2, 10), pady=4)

        def menu(r, key, values, width=220):
            ctk.CTkOptionMenu(g, values=list(values), variable=self.v[key], width=width, height=26,
                              fg_color=_pal.BG_SUB, button_color=_pal.BG_SUB, button_hover_color=_pal.BG_HOVER,
                              text_color=_pal.TXT, font=_pal.font(11), corner_radius=_pal.R_INPUT,
                              command=lambda _v: self._preset() if key == "preset" else self._info()).grid(
                row=r, column=1, sticky="w", pady=4)

        label(0, "Preset")
        menu(0, "preset", PRESETS)
        label(1, "Width x height (mm)")
        box = ctk.CTkFrame(g, fg_color="transparent")
        box.grid(row=1, column=1, sticky="w", pady=4)
        self.e_w = _theme.entry(box, width=70, textvariable=self.v["width"])
        self.e_w.pack(side="left")
        ctk.CTkLabel(box, text=" x ", font=_pal.font(11), text_color=_pal.TXT_SUB).pack(side="left")
        self.e_h = _theme.entry(box, width=70, textvariable=self.v["height"])
        self.e_h.pack(side="left")
        label(2, "Font size (pt)")
        self.e_f = _theme.entry(g, width=70, textvariable=self.v["font"])
        self.e_f.grid(row=2, column=1, sticky="w", pady=4)
        label(3, "Line width (pt)")
        self.e_l = _theme.entry(g, width=70, textvariable=self.v["line"])
        self.e_l.grid(row=3, column=1, sticky="w", pady=4)
        label(4, "Resolution (dpi)")
        menu(4, "dpi", ("300", "600", "1200"), width=100)
        label(5, "Format")
        menu(5, "format", FORMATS, width=100)
        label(6, "Style")
        menu(6, "style", ("Publication", "As displayed"), width=140)
        ctk.CTkCheckBox(g, text="Transparent background", variable=self.v["transparent"], font=_pal.font(11),
                        text_color=_pal.TXT, checkbox_width=16, checkbox_height=16, corner_radius=2,
                        border_width=1, fg_color=_pal.ACCENT, hover_color=_pal.ACCENT_HOV).grid(
            row=7, column=0, columnspan=2, sticky="w", padx=2, pady=4)
        self.lbl = ctk.CTkLabel(g, text="", font=_pal.mono(10), text_color=_pal.TXT_SUB, anchor="w", justify="left")
        self.lbl.grid(row=8, column=0, columnspan=2, sticky="w", padx=2, pady=(6, 0))
        foot = ctk.CTkFrame(top, fg_color="transparent")
        foot.pack(fill="x", padx=10, pady=(4, 10))
        _theme.secondary_button(foot, "Close", command=top.destroy, width=90).pack(side="right", padx=(6, 0))
        ctk.CTkButton(foot, text="Save...", width=100, height=28, fg_color=_pal.ACCENT, hover_color=_pal.ACCENT_HOV,
                      text_color="white", corner_radius=_pal.R_PILL, font=_pal.font(11, "bold"),
                      command=self.save).pack(side="right")
        for key in ("width", "height", "dpi"):
            self.v[key].trace_add("write", lambda *a: self._info())
        self._preset()

    def _preset(self):
        p = PRESETS.get(self.v["preset"].get())
        state = "normal"
        if p is None:
            w_in, h_in = self.fig.get_size_inches()
            self.v["width"].set(f"{w_in / MM:.0f}")
            self.v["height"].set(f"{h_in / MM:.0f}")
            self.v["font"].set("")
            self.v["line"].set("")
            state = "disabled"
        else:
            self.v["width"].set(f"{p['width_mm']:g}")
            self.v["height"].set(f"{p['height_mm']:g}")
            self.v["font"].set(f"{p['font_pt']:g}")
            self.v["line"].set(f"{p['line_pt']:g}")
        for e in (self.e_w, self.e_h, self.e_f, self.e_l):
            try:
                e.configure(state=state)
            except Exception:
                pass
        self._info()

    def settings(self) -> Dict[str, Any]:
        as_displayed = PRESETS.get(self.v["preset"].get()) is None
        out: Dict[str, Any] = {"dpi": int(self.v["dpi"].get()), "publication": self.v["style"].get() == "Publication",
                               "transparent": bool(self.v["transparent"].get())}
        if not as_displayed:
            out["width_mm"] = float(self.v["width"].get())
            out["height_mm"] = float(self.v["height"].get())
            out["font_pt"] = _float_or_none(self.v["font"].get())
            out["line_pt"] = _float_or_none(self.v["line"].get())
            if not (10 <= out["width_mm"] <= 1000 and 10 <= out["height_mm"] <= 1000):
                raise ValueError("width and height must lie between 10 and 1000 mm")
        return out

    def _info(self):
        try:
            w, h, dpi = float(self.v["width"].get()), float(self.v["height"].get()), int(self.v["dpi"].get())
            self.lbl.configure(text=f"{w:g} x {h:g} mm  =  {w * MM:.2f} x {h * MM:.2f} in  =  "
                                    "{} x {} px".format(*pixel_size(w, h, dpi)))
        except Exception:
            self.lbl.configure(text="")

    def save(self):
        from tkinter import filedialog, messagebox
        from scripts.common import app_config
        try:
            s = self.settings()
        except ValueError as e:
            messagebox.showerror("Export figure", f"Size: {e}", parent=self.top)
            return
        ext = FORMATS[self.v["format"].get()]
        path = filedialog.asksaveasfilename(parent=self.top, defaultextension=ext, title="Export figure",
                                            filetypes=[(f"{self.v['format'].get()} file", "*" + ext)])
        if not path:
            return
        try:
            info = export_figure(self.fig, path, **s)
        except Exception as e:
            messagebox.showerror("Export figure", f"Save failed: {e}", parent=self.top)
            return
        try:
            app_config.update({"figure_export": {"preset": self.v["preset"].get(), "dpi": s["dpi"],
                                                 "format": self.v["format"].get(), "style": self.v["style"].get(),
                                                 "transparent": s["transparent"]}})
        except Exception:
            pass
        text = f"Saved {os.path.basename(path)}  ({info['width_mm']:.0f} x {info['height_mm']:.0f} mm, {info['dpi']} dpi)"
        self.lbl.configure(text=text)
        if self.on_saved:
            try:
                self.on_saved(text)
            except Exception:
                pass


class WorksheetWindow:
    """The numbers behind the figure, as X/Y column pairs."""

    MAX_ROWS = 2000

    def __init__(self, parent, fig):
        from tkinter import ttk
        import customtkinter as ctk
        from scripts.common import palette as _pal
        from scripts.common import theme as _theme
        self.df = figure_table(fig)
        self.top = top = _dialog(parent, "Data worksheet", "980x560")
        bar = ctk.CTkFrame(top, fg_color=_pal.TOOL_BG, corner_radius=0, height=36)
        bar.pack(fill="x")
        _theme.secondary_button(bar, "Copy all", command=self.copy, width=90).pack(side="left", padx=(8, 4), pady=4)
        _theme.secondary_button(bar, "Save CSV...", command=self.save_csv, width=100).pack(side="left", padx=4, pady=4)
        _theme.secondary_button(bar, "Save Excel...", command=self.save_xlsx, width=110).pack(side="left", padx=4, pady=4)
        n_rows, n_cols = self.df.shape
        note = f"{n_cols // 2} curve(s), {n_rows} row(s)"
        if n_rows > self.MAX_ROWS:
            note += f" - the first {self.MAX_ROWS} rows are shown; copy and save use all rows"
        self.lbl = ctk.CTkLabel(bar, text=note, font=_pal.font(11), text_color=_pal.TXT_SUB)
        self.lbl.pack(side="left", padx=12)
        body = ctk.CTkFrame(top, fg_color=_pal.BG_CARD, corner_radius=0, border_width=1, border_color=_pal.BORDER)
        body.pack(fill="both", expand=True, padx=8, pady=8)
        _theme.style_treeview(rowheight=20)
        cols = [f"c{i}" for i in range(n_cols)]
        self.tree = ttk.Treeview(body, columns=cols, show="headings", selectmode="extended")
        letters = column_letters(n_cols)
        for cid, letter, name in zip(cols, letters, self.df.columns):
            self.tree.heading(cid, text=f"{letter}  {name}")
            self.tree.column(cid, width=150, minwidth=80, anchor="e", stretch=False)
        ys = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(body, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(1, 0), pady=(1, 0))
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        values = self.df.to_numpy()
        for row in values[: self.MAX_ROWS]:
            self.tree.insert("", "end", values=["" if not np.isfinite(v) else f"{v:.6g}" for v in row])
        if n_cols == 0:
            self.lbl.configure(text="The figure holds no curves.")

    def text(self) -> str:
        return self.df.to_csv(sep="\t", index=False, float_format="%.8g")

    def copy(self):
        try:
            self.top.clipboard_clear()
            self.top.clipboard_append(self.text())
            self.lbl.configure(text=f"Copied {self.df.shape[0]} rows x {self.df.shape[1]} columns (tab separated)")
        except Exception:
            pass

    def save_csv(self):
        from tkinter import filedialog, messagebox
        path = filedialog.asksaveasfilename(parent=self.top, defaultextension=".csv", title="Save worksheet",
                                            filetypes=[("CSV file", "*.csv")])
        if not path:
            return
        try:
            self.df.to_csv(path, index=False, float_format="%.8g")
            self.lbl.configure(text=f"Saved {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Data worksheet", f"Save failed: {e}", parent=self.top)

    def save_xlsx(self):
        from tkinter import filedialog, messagebox
        path = filedialog.asksaveasfilename(parent=self.top, defaultextension=".xlsx", title="Save worksheet",
                                            filetypes=[("Excel workbook", "*.xlsx")])
        if not path:
            return
        try:
            self.df.to_excel(path, index=False, sheet_name="Worksheet")
            self.lbl.configure(text=f"Saved {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Data worksheet", f"Save failed: {e}", parent=self.top)


# --------------------------------------------------------------------------- entry points
def open_plot_details(owner, fig, canvas=None):
    if fig is None or not fig.axes:
        from tkinter import messagebox
        messagebox.showinfo("Plot details", "There is no graph yet.", parent=owner)
        return None
    return PlotDetailsDialog(owner, fig, canvas)


def open_export(owner, fig):
    if fig is None:
        from tkinter import messagebox
        messagebox.showinfo("Export figure", "There is no figure to save.", parent=owner)
        return None

    def saved(text):
        try:
            from scripts.common import analysis_shell as _shell
            _shell.set_status(owner, text)
        except Exception:
            pass
    return ExportDialog(owner, fig, on_saved=saved)


def open_worksheet(owner, fig):
    if fig is None:
        from tkinter import messagebox
        messagebox.showinfo("Data worksheet", "There is no figure yet.", parent=owner)
        return None
    return WorksheetWindow(owner, fig)
