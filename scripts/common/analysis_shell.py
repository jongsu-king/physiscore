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
from scripts.common import theme as _theme   # installs the instrument theme (3.2)

try:  # tool windows opened without the launcher (smoke tests, --tool) must still follow the palette
    ctk.set_appearance_mode("Dark" if _pal.IS_DARK else "Light")
except Exception:
    pass

STD_GEOMETRY = "1500x920"

# toolbar slot style: (bg, hover, bold, text colour)
_SLOT_STYLE = {
    "open":   (_pal.BG_PANEL, _pal.BG_HOVER, False, _pal.TXT),
    "run":    (_pal.ACCENT, _pal.ACCENT_HOV, True, "white"),
    "fit":    (_pal.BG_PANEL, _pal.BG_HOVER, False, _pal.TXT),
    "extra":  (_pal.BG_PANEL, _pal.BG_HOVER, False, _pal.TXT),
    "excel":  (_pal.BG_PANEL, _pal.BG_HOVER, False, _pal.TXT),
    "png":    (_pal.BG_PANEL, _pal.BG_HOVER, False, _pal.TXT),
    "report": (_pal.BG_PANEL, _pal.BG_HOVER, False, _pal.TXT),
    "origin": (_pal.BG_PANEL, _pal.BG_HOVER, False, _pal.TXT),
    "ai":     (_pal.BG_PANEL, _pal.BG_HOVER, False, _pal.TXT_SUB),
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
        _pal.originize(fig2)
        fig2.patch.set_facecolor("white")
        fig2.patch.set_alpha(1.0)
        light = {c.lower() for c in (_pal.PLOT_FG, _pal.PLOT_TICK, _pal.TXT, _pal.TXT_MUTED, "white",
                                     "#ffffff", "#aaaaaa", "#888888", "#dddddd")}
        for ax in fig2.axes:
            ax.set_facecolor("white")
            for spine in ax.spines.values():
                spine.set_color("black")
                spine.set_linewidth(1.5)
            ax.tick_params(axis="both", which="both", colors="black", direction="in")
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


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------
def make_thread_safe(widget, interval_ms: int = 40):
    """Make `widget.after(...)` safe to call from worker threads.

    Every tool runs its processing in a thread and hands results back with
    `self.after(0, callback)`. Tk is single-threaded: with some Tcl/Tk builds
    (observed with Tk 9.0 on macOS) an `after` issued from another thread is
    silently dropped, so the window never receives its results. This wrapper
    queues calls made off the main thread and a main-thread poller (started
    here, on the main thread) dispatches them. Calls from the main thread go
    straight to Tk as before.
    """
    import queue
    import threading
    import traceback

    if getattr(widget, "_mt_safe", False):
        return widget
    q: "queue.Queue" = queue.Queue()
    orig_after = widget.after
    orig_after_cancel = widget.after_cancel
    main = threading.main_thread()

    def after(ms, func=None, *args):
        if func is None or threading.current_thread() is main:
            return orig_after(ms, func, *args) if func is not None else orig_after(ms)
        q.put((ms, func, args))
        return f"queued-{id(func)}"

    def after_cancel(ident):
        if isinstance(ident, str) and ident.startswith("queued-"):
            return None
        return orig_after_cancel(ident)

    def drain():
        try:
            while True:
                ms, func, args = q.get_nowait()
                if ms <= 0:
                    try:
                        func(*args)
                    except Exception:  # noqa: BLE001 - a bad callback must not stop the poller
                        traceback.print_exc()
                else:
                    orig_after(ms, func, *args)
        except queue.Empty:
            pass
        try:
            if widget.winfo_exists():
                orig_after(interval_ms, drain)
        except Exception:
            pass

    widget.after = after
    widget.after_cancel = after_cancel
    widget._mt_safe = True
    try:
        orig_after(interval_ms, drain)
    except Exception:
        pass
    return widget


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
# Section of docs/METHODS.md behind "Help > Methods of this tool".  A window may
# also name its own in a METHOD_SECTION attribute (the curve tools do).
_METHOD_SECTIONS = {
    "J-V Curve Analysis": "1.", "J-V Dark Analysis": "2.", "EQE Analysis": "3.",
    "Absorbance / Tauc Analysis": "4.", "XRD Analysis": "5.", "PL Analysis": "6.",
    "Raman Analysis": "7.", "FTIR Analysis": "7.", "FE-SEM Analysis": "8.",
    "Device summary": "11.",
}


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
    m_ex.add_command(label="Export figure (journal preset)...", accelerator="Ctrl+Shift+S",
                     command=_wrap(lambda: _plot_tool(win, "export")))
    m_ex.add_command(label="Copy figure to clipboard", command=_wrap(lambda: copy_figure_to_clipboard(win)))
    m_ex.add_command(label="Data worksheet...", accelerator="Ctrl+D",
                     command=_wrap(lambda: _plot_tool(win, "worksheet")))
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
        on = bool(getattr(ax, "_physiscore_grid", False))
        ax._physiscore_grid = not on          # remembered by palette.originize at every draw
        ax.grid(not on, color=_pal.PLOT_GRID, linewidth=0.6)

    m_view.add_command(label="Auto range", command=lambda: _each_axes(_auto_range))
    m_view.add_command(label="Toggle legend", command=lambda: _each_axes(_toggle_legend))
    m_view.add_command(label="Toggle grid", command=lambda: _each_axes(_toggle_grid))
    m_view.add_separator()
    m_view.add_command(label="Data reader", accelerator="Ctrl+R", command=_wrap(lambda: _plot_tool(win, "reader")))
    m_view.add_command(label="Plot details...", accelerator="Ctrl+P",
                       command=_wrap(lambda: _plot_tool(win, "details")))
    bar.add_cascade(label="View", menu=m_view)

    m_help = tk.Menu(bar, tearoff=False)
    if hints:
        m_help.add_command(label="Mouse and keyboard...", command=lambda: messagebox.showinfo(
            f"{tool_name} - mouse and keyboard", hints.replace("  |  ", "\n")))
    def _methods_online():
        __import__("webbrowser").open("https://github.com/jongsu-king/physiscore/blob/main/docs/METHODS.md")

    def _methods_offline():
        # The bundled copy, at the section of this tool when the window names one.
        try:
            from scripts.common import docs_viewer
            section = getattr(win, "METHOD_SECTION", "") or _METHOD_SECTIONS.get(tool_name)
            if docs_viewer.open_doc("METHODS", section=section) is not None:
                return
        except Exception:
            pass
        _methods_online()

    m_help.add_command(label="Methods of this tool", command=_methods_offline)
    m_help.add_command(label="Methods (online)", command=_methods_online)
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
    for seq, which in (("<Control-r>", "reader"), ("<Control-p>", "details"), ("<Control-d>", "worksheet"),
                       ("<Control-Shift-S>", "export")):
        # a text field keeps its own editing keys (Ctrl+D deletes a character there)
        win.bind(seq, _wrap(lambda w=which: None if _typing(win) else _plot_tool(win, w)))
    return bar


def _typing(win) -> bool:
    """True while the keyboard focus is in a text field."""
    try:
        w = win.focus_get()
        return w is not None and w.winfo_class() in ("Entry", "TEntry", "Text", "Spinbox", "TSpinbox", "TCombobox")
    except Exception:
        return False


def _plot_tool(win, which):
    """Shared graph tools (scripts/common/plot_tools.py) on the window's figure."""
    from scripts.common import plot_tools as _pt
    fig = find_figure(win)
    if fig is None:
        messagebox.showinfo("Graph", "There is no graph in this window yet.", parent=win)
        return None
    if which == "reader":
        on = _pt.toggle_reader(win, fig.canvas, fig)
        return on
    if which == "details":
        return _pt.open_plot_details(win, fig, fig.canvas)
    if which == "worksheet":
        return _pt.open_worksheet(win, fig)
    return _pt.open_export(win, fig)


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
    make_thread_safe(win)
    tab = getattr(win, "tab", None)
    if tab is not None and hasattr(tab, "after"):
        make_thread_safe(tab)

    _make_menubar(win, tool_name, actions, hints)

    # ---- toolbar (3.2: compact, flat buttons in groups, hairline under it) ----
    bar = ctk.CTkFrame(win, height=36, fg_color=_pal.TOOL_BG, corner_radius=0)
    bar.pack_propagate(False)
    ctk.CTkFrame(bar, height=1, fg_color=_pal.BORDER_HI, corner_radius=0).place(
        relx=0, rely=1.0, relwidth=1.0, anchor="sw")
    ctk.CTkLabel(bar, text=tool_name, font=_pal.font(12, "bold"), text_color=_pal.TXT
                 ).pack(side="left", padx=(10, 12))

    def make_btn(parent, label, cb, slot):
        color, hov, bold, tcol = _SLOT_STYLE[slot]
        is_run = slot == "run"
        return ctk.CTkButton(
            parent, text=label, command=_wrap(cb), height=24,
            width=max(58, 12 + 7 * len(label)),
            fg_color=color, hover_color=hov, text_color=tcol,
            border_width=0 if is_run else 1, border_color=_pal.BORDER_HI,
            font=_pal.font(11, "bold") if bold else _pal.font(11),
            corner_radius=_pal.R_PILL)

    def separator():
        ctk.CTkFrame(bar, width=1, height=20, fg_color=_pal.BORDER_HI, corner_radius=0
                     ).pack(side="left", padx=7, pady=8)

    for slot in _LEFT_ORDER:
        v = actions.get(slot)
        if v is None:
            continue
        items = v if isinstance(v, list) else [_norm(v, _DEFAULT_LABELS.get(slot, ""))]
        for it in items:
            if it is None:
                continue
            make_btn(bar, it[0], it[1], slot).pack(side="left", padx=2, pady=6)
        if slot in ("open", "run"):
            separator()

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
            make_btn(bar, it[0], it[1], slot).pack(side="right", padx=2, pady=6)

    # ---- status bar ----
    sb = ctk.CTkFrame(win, height=22, fg_color=_pal.TOOL_BG, corner_radius=0)
    sb.pack_propagate(False)
    ctk.CTkFrame(sb, height=1, fg_color=_pal.BORDER_HI, corner_radius=0).place(
        relx=0, rely=0, relwidth=1.0, anchor="nw")
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
        win.grid_rowconfigure(0, weight=0, minsize=36)
        win.grid_rowconfigure(maxrow + 2, weight=0, minsize=22)
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

    # group boxes -> square boxes with header strips (3.2)
    try:
        _theme.instrumentize(win)
    except Exception:
        pass
    return status
