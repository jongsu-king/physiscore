"""Common window chrome for every analysis tool.

`attach_chrome` gives a tool window the same menu bar, toolbar and status
bar as all the others:

* a native menu bar (File / Analysis / Export / View / Help) built from the
  tool's action table, with the usual accelerators (Ctrl+O open, F5 run,
  Ctrl+E Excel, Ctrl+S figure, Ctrl+Q close);
* a compact toolbar with plain text buttons in a fixed order, the primary
  action (run) being the only solid button;
* a status bar with the tool's status text on the left and a live cursor
  read-out (x, y of the plot under the pointer) on the right.

It also provides the publication-style figure export used by every PNG
button (white background, black axes, inward ticks, 600 dpi, or SVG/PDF).
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from scripts.common import palette as _pal

STD_GEOMETRY = "1500x920"

# toolbar slot style: (bg, hover, bold, text colour)
_SLOT_STYLE = {
    "open":   (_pal.BG_SUB, _pal.BG_HOVER, False, _pal.TXT),
    "run":    (_pal.ACCENT, _pal.ACCENT_HOV, True, "white"),
    "fit":    (_pal.BG_SUB, _pal.BG_HOVER, False, _pal.TXT),
    "extra":  (_pal.BG_SUB, _pal.BG_HOVER, False, _pal.TXT),
    "excel":  (_pal.BG_SUB, _pal.BG_HOVER, False, _pal.TXT),
    "png":    (_pal.BG_SUB, _pal.BG_HOVER, False, _pal.TXT),
    "report": (_pal.BG_SUB, _pal.BG_HOVER, False, _pal.TXT),
    "origin": (_pal.BG_SUB, _pal.BG_HOVER, False, _pal.TXT),
    "ai":     (_pal.BG_SUB, _pal.BG_HOVER, False, _pal.TXT_SUB),
}
_RIGHT_ORDER = ["excel", "png", "report", "origin", "ai"]
_LEFT_ORDER = ["open", "run", "fit", "extra"]
_DEFAULT_LABELS = {"open": "Open", "run": "Process", "fit": "Auto fit", "excel": "Excel",
                   "png": "Figure", "report": "Report", "origin": "Origin", "ai": "Interpretation"}

_CANVAS_ATTRS = ("canvas_plot", "canvas", "canvas_res", "canvas_prev")
_FIG_ATTRS = ("fig", "fig_res", "figure", "fig_main")


def _wrap(cb):
    def inner(*_a):
        try:
            cb()
        except Exception as e:  # noqa: BLE001 - surface to the user, keep the loop alive
            messagebox.showerror("Error", str(e))
    return inner


def _norm(v, default_label):
    if v is None:
        return None
    if callable(v):
        return (default_label, v)
    return v


# ---------------------------------------------------------------------------
# Publication-style figure export
# ---------------------------------------------------------------------------
def _publication_copy(fig):
    """Deep copy of a figure restyled for print: white background, black
    axes/text, inward ticks on all four sides, no grid. Returns None when the
    figure cannot be pickled (then the screen figure is saved as is)."""
    try:
        import pickle
        fig2 = pickle.loads(pickle.dumps(fig))
    except Exception:
        return None
    try:
        fig2.patch.set_facecolor("white")
        fig2.patch.set_alpha(1.0)
        light = {c.lower() for c in (_pal.PLOT_FG, _pal.PLOT_TICK, _pal.TXT, _pal.TXT_MUTED, "white",
                                     "#ffffff", "#aaaaaa", "#888888", "#dddddd")}
        for ax in fig2.axes:
            ax.set_facecolor("white")
            for spine in ax.spines.values():
                spine.set_color("black")
                spine.set_linewidth(1.1)
            ax.tick_params(axis="both", which="both", colors="black", direction="in", top=True, right=True)
            ax.xaxis.label.set_color("black")
            ax.yaxis.label.set_color("black")
            ax.title.set_color("black")
            for lbl in ax.get_xticklabels() + ax.get_yticklabels():
                lbl.set_color("black")
            ax.grid(False)
            leg = ax.get_legend()
            if leg is not None:
                for txt in leg.get_texts():
                    txt.set_color("black")
                frame = leg.get_frame()
                frame.set_facecolor("white")
                frame.set_edgecolor("black")
                frame.set_alpha(1.0)
            for t in ax.texts:
                c = t.get_color()
                if isinstance(c, str) and c.lower() in light:
                    t.set_color("black")
        return fig2
    except Exception:
        return None


def find_figure(win):
    for holder in (win, getattr(win, "tab", None)):
        if holder is None:
            continue
        for name in _FIG_ATTRS:
            f = getattr(holder, name, None)
            if f is not None and hasattr(f, "savefig"):
                return f
    return None


def save_fig_png(win, candidates=_FIG_ATTRS):
    """Shared figure export (PNG 600 dpi, TIFF, SVG or PDF; publication style)."""
    fig = find_figure(win)
    if fig is None:
        messagebox.showwarning("Export", "There is no figure to save.")
        return
    path = filedialog.asksaveasfilename(
        defaultextension=".png",
        filetypes=[("PNG image, 600 dpi", "*.png"), ("SVG vector", "*.svg"),
                   ("PDF vector", "*.pdf"), ("TIFF image, 600 dpi", "*.tif")],
        title="Save figure")
    if not path:
        return
    try:
        pub = _publication_copy(fig)
        if pub is not None:
            pub.savefig(path, dpi=600, facecolor="white", bbox_inches="tight")
            try:
                import matplotlib.pyplot as _plt
                _plt.close(pub)
            except Exception:
                pass
        else:
            fig.savefig(path, dpi=300, facecolor=fig.get_facecolor(), bbox_inches="tight")
        set_status(win, f"Saved {os.path.basename(path)}")
    except Exception as e:
        messagebox.showerror("Export", f"Save failed: {e}")


def copy_figure_to_clipboard(win):
    """Copy the current figure as PNG to the clipboard (Windows and macOS)."""
    fig = find_figure(win)
    if fig is None:
        return
    import io
    import tempfile
    buf = io.BytesIO()
    pub = _publication_copy(fig) or fig
    pub.savefig(buf, format="png", dpi=200, facecolor="white", bbox_inches="tight")
    data = buf.getvalue()
    try:
        if sys.platform == "win32":
            from PIL import Image
            import io as _io
            img = Image.open(_io.BytesIO(data)).convert("RGB")
            out = _io.BytesIO()
            img.save(out, "BMP")
            bmp = out.getvalue()[14:]
            import win32clipboard  # type: ignore
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, bmp)
            win32clipboard.CloseClipboard()
        elif sys.platform == "darwin":
            import subprocess
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
                fh.write(data)
                tmp = fh.name
            subprocess.run(["osascript", "-e",
                            f'set the clipboard to (read (POSIX file "{tmp}") as «class PNGf»)'],
                           check=False, capture_output=True)
        else:
            raise RuntimeError("clipboard images are not supported on this platform; use Save figure")
        set_status(win, "Figure copied to clipboard")
    except Exception as e:
        messagebox.showinfo("Copy figure", f"Could not copy to the clipboard: {e}")


def set_status(win, text):
    lbl = getattr(win, "_shell_status", None)
    if lbl is not None:
        try:
            lbl.configure(text=text)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Chrome
# ---------------------------------------------------------------------------
def _make_menubar(win, tool_name, actions, hints):
    bar = tk.Menu(win, tearoff=False)

    def add_items(menu, items, default):
        if items is None:
            return 0
        items = items if isinstance(items, list) else [_norm(items, default)]
        n = 0
        for it in items:
            if it is None:
                continue
            label, cb = it
            menu.add_command(label=label, command=_wrap(cb))
            n += 1
        return n

    m_file = tk.Menu(bar, tearoff=False)
    n = add_items(m_file, actions.get("open"), _DEFAULT_LABELS["open"])
    if n:
        m_file.add_separator()
    m_file.add_command(label="Close window", accelerator="Ctrl+Q", command=lambda: win.destroy())
    bar.add_cascade(label="File", menu=m_file)

    m_an = tk.Menu(bar, tearoff=False)
    n = add_items(m_an, actions.get("run"), _DEFAULT_LABELS["run"])
    n += add_items(m_an, actions.get("fit"), _DEFAULT_LABELS["fit"])
    n += add_items(m_an, actions.get("extra"), "")
    if actions.get("ai") is not None:
        if n:
            m_an.add_separator()
        add_items(m_an, actions.get("ai"), _DEFAULT_LABELS["ai"])
    bar.add_cascade(label="Analysis", menu=m_an)

    m_ex = tk.Menu(bar, tearoff=False)
    add_items(m_ex, actions.get("excel"), _DEFAULT_LABELS["excel"])
    png = actions.get("png")
    if png is True:
        m_ex.add_command(label="Save figure...", accelerator="Ctrl+S", command=_wrap(lambda: save_fig_png(win)))
    elif png is not None:
        add_items(m_ex, png, _DEFAULT_LABELS["png"])
    m_ex.add_command(label="Copy figure to clipboard", command=_wrap(lambda: copy_figure_to_clipboard(win)))
    if actions.get("report") is not None:
        add_items(m_ex, actions.get("report"), _DEFAULT_LABELS["report"])
    if actions.get("origin") is not None:
        m_ex.add_separator()
        add_items(m_ex, actions.get("origin"), _DEFAULT_LABELS["origin"])
    bar.add_cascade(label="Export", menu=m_ex)

    m_view = tk.Menu(bar, tearoff=False)

    def _each_axes(fn):
        fig = find_figure(win)
        if fig is None:
            return
        for ax in fig.axes:
            try:
                fn(ax)
            except Exception:
                pass
        try:
            fig.canvas.draw_idle()
        except Exception:
            pass

    def _auto_range(ax):
        ax.relim(visible_only=True)
        ax.autoscale(enable=True, axis="both")
        ax.autoscale_view()

    def _toggle_legend(ax):
        leg = ax.get_legend()
        if leg is not None:
            leg.set_visible(not leg.get_visible())

    def _toggle_grid(ax):
        on = any(l.get_visible() for l in ax.get_xgridlines())
        ax.grid(not on)

    m_view.add_command(label="Auto range", command=lambda: _each_axes(_auto_range))
    m_view.add_command(label="Toggle legend", command=lambda: _each_axes(_toggle_legend))
    m_view.add_command(label="Toggle grid", command=lambda: _each_axes(_toggle_grid))
    bar.add_cascade(label="View", menu=m_view)

    m_help = tk.Menu(bar, tearoff=False)
    if hints:
        m_help.add_command(label="Mouse and keyboard...", command=lambda: messagebox.showinfo(
            f"{tool_name} - mouse and keyboard", hints.replace("  |  ", "\n")))
    m_help.add_command(label="Methods (online)", command=lambda: __import__("webbrowser").open(
        "https://github.com/jongsu-king/physiscore/blob/main/docs/METHODS.md"))
    m_help.add_command(label="About Physiscore", command=lambda: _about(win))
    bar.add_cascade(label="Help", menu=m_help)

    try:
        win.configure(menu=bar)
    except Exception:
        pass

    # accelerators
    runs = actions.get("run")
    run_cb = (runs[0][1] if isinstance(runs, list) and runs else (runs[1] if isinstance(runs, tuple) else runs))
    opens = actions.get("open")
    open_cb = (opens[0][1] if isinstance(opens, list) and opens else (opens[1] if isinstance(opens, tuple) else opens))
    excel = actions.get("excel")
    excel_cb = (excel[0][1] if isinstance(excel, list) and excel else (excel[1] if isinstance(excel, tuple) else excel))
    if callable(run_cb):
        win.bind("<F5>", _wrap(run_cb))
    if callable(open_cb):
        win.bind("<Control-o>", _wrap(open_cb))
    if callable(excel_cb):
        win.bind("<Control-e>", _wrap(excel_cb))
    if png is not None:
        win.bind("<Control-s>", _wrap(lambda: save_fig_png(win)))
    win.bind("<Control-q>", lambda e: win.destroy())
    return bar


def _about(win):
    try:
        from Physiscore_Launcher import APP_VERSION
    except Exception:
        APP_VERSION = ""
    messagebox.showinfo(
        "About Physiscore",
        f"Physiscore {APP_VERSION}\n"
        "Physics-constrained analysis of thin-film photovoltaic measurements\n\n"
        "Hybrid Materials and Optoelectronics Laboratory (H-MOL),\n"
        "Incheon National University. MIT License.\n\n"
        "Concept DOI 10.5281/zenodo.22267588\n"
        "https://github.com/jongsu-king/physiscore", parent=win)


def attach_cursor_readout(win, canvas, label=None, fmt="x = {x:.4g}   y = {y:.4g}"):
    """Show the data coordinates under the pointer in the status bar."""
    label = label or getattr(win, "_shell_cursor", None)
    if label is None or canvas is None:
        return None

    def on_move(event):
        try:
            if event.inaxes is None or event.xdata is None:
                label.configure(text="")
            else:
                label.configure(text=fmt.format(x=event.xdata, y=event.ydata))
        except Exception:
            pass

    try:
        return canvas.mpl_connect("motion_notify_event", on_move)
    except Exception:
        return None


def attach_chrome(win, tool_name, actions, status_left="Ready", hints=""):
    """Inject the standard chrome into a tool window.

    actions: {"open": (label, cb) | cb | [(label, cb), ...], "run": ..., "fit": ...,
              "extra": [...], "excel": ..., "png": True | (label, cb), "report": ...,
              "origin": ... | [...], "ai": ...}
    Returns the status label (also stored as win._shell_status).
    """
    try:
        win.title(f"{tool_name} - Physiscore")
        win.geometry(STD_GEOMETRY)
        win.minsize(1180, 720)
        win.configure(fg_color=_pal.BG_WINDOW)
    except Exception:
        pass

    _make_menubar(win, tool_name, actions, hints)

    # ---- toolbar ----
    bar = ctk.CTkFrame(win, height=40, fg_color=_pal.BG_PANEL, corner_radius=0)
    bar.pack_propagate(False)
    ctk.CTkLabel(bar, text=tool_name, font=_pal.font(12, "bold"), text_color=_pal.TXT
                 ).pack(side="left", padx=(12, 14))

    def make_btn(parent, label, cb, slot):
        color, hov, bold, tcol = _SLOT_STYLE[slot]
        is_run = slot == "run"
        return ctk.CTkButton(
            parent, text=label, command=_wrap(cb), height=26,
            width=max(64, 10 + 7 * len(label)),
            fg_color=color, hover_color=hov, text_color=tcol,
            border_width=0 if is_run else 1, border_color=_pal.BORDER_HI,
            font=_pal.font(11, "bold") if bold else _pal.font(11),
            corner_radius=_pal.R_PILL)

    for slot in _LEFT_ORDER:
        v = actions.get(slot)
        if v is None:
            continue
        items = v if isinstance(v, list) else [_norm(v, _DEFAULT_LABELS.get(slot, ""))]
        for it in items:
            if it is None:
                continue
            make_btn(bar, it[0], it[1], slot).pack(side="left", padx=3, pady=7)
        if slot == "run":
            ctk.CTkFrame(bar, width=1, height=22, fg_color=_pal.BORDER).pack(side="left", padx=6, pady=9)

    for slot in _RIGHT_ORDER:
        v = actions.get(slot)
        if v is None:
            continue
        if slot == "png" and v is True:
            v = ("Figure", lambda w=win: save_fig_png(w))
        items = v if isinstance(v, list) else [_norm(v, _DEFAULT_LABELS[slot])]
        for it in reversed(items):
            if it is None:
                continue
            make_btn(bar, it[0], it[1], slot).pack(side="right", padx=3, pady=7)

    # ---- status bar ----
    sb = ctk.CTkFrame(win, height=24, fg_color=_pal.BG_PANEL, corner_radius=0)
    sb.pack_propagate(False)
    status = ctk.CTkLabel(sb, text=status_left, font=_pal.font(10), text_color=_pal.TXT_SUB, anchor="w")
    status.pack(side="left", padx=10)
    cursor = ctk.CTkLabel(sb, text="", font=_pal.mono(10), text_color=_pal.TXT_SUB, anchor="e")
    cursor.pack(side="right", padx=10)
    win._shell_status = status
    win._shell_cursor = cursor

    # ---- place above/below the existing layout ----
    grid_slaves = win.grid_slaves()
    if grid_slaves:
        infos = [(w, w.grid_info()) for w in grid_slaves]
        maxrow = max(int(gi["row"]) for _, gi in infos)
        ncols = max(int(gi["column"]) + int(gi.get("columnspan", 1)) for _, gi in infos)
        for w, gi in infos:
            w.grid_configure(row=int(gi["row"]) + 1)
        for r in range(maxrow + 1, 0, -1):
            cfg = win.grid_rowconfigure(r - 1)
            win.grid_rowconfigure(r, weight=cfg["weight"], minsize=cfg["minsize"])
        win.grid_rowconfigure(0, weight=0, minsize=40)
        win.grid_rowconfigure(maxrow + 2, weight=0, minsize=24)
        bar.grid(row=0, column=0, columnspan=max(ncols, 1), sticky="ew")
        sb.grid(row=maxrow + 2, column=0, columnspan=max(ncols, 1), sticky="ew")
    else:
        pack_slaves = win.pack_slaves()
        if pack_slaves:
            bar.pack(side="top", fill="x", before=pack_slaves[0])
            sb.pack(side="bottom", fill="x", before=pack_slaves[0])
        else:
            bar.pack(side="top", fill="x")
            sb.pack(side="bottom", fill="x")

    # cursor read-out on every canvas the tool exposes
    for holder in (win, getattr(win, "tab", None)):
        if holder is None:
            continue
        for name in _CANVAS_ATTRS:
            cv = getattr(holder, name, None)
            if cv is not None and hasattr(cv, "mpl_connect"):
                attach_cursor_readout(win, cv, cursor)
    return status
