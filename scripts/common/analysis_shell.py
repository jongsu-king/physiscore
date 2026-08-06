# ============================================================
# scripts/common/analysis_shell.py
# Standard chrome that injects the SAME top toolbar + bottom status bar into every tool window.
# JV Analysis exe layout: [Open] [Process] [Fit] ... [AI] [Origin] [PNG] [Excel]
#  - button order/position/size/color are identical across all tools
#  - unified window size (1500x920), title (<tool> - Physiscore), background (#0A0A0A)
#  - auto-detects grid or pack layout and injects at top/bottom accordingly
# ============================================================
import os
import customtkinter as ctk
from tkinter import filedialog, messagebox

# JV exe palette
BG_WINDOW = "#0A0A0A"
BG_PANEL  = "#141414"
BG_SUB    = "#252525"
BG_HOVER  = "#303030"
BORDER_HI = "#3D3D3D"
ACCENT    = "#3182F6"
ACC_HOV   = "#2563EB"
GREEN     = "#10B981"
GREEN_HOV = "#059669"
PURPLE    = "#8B5CF6"
PURPLE_HOV= "#7C3AED"
PINK      = "#EC4899"
PINK_HOV  = "#DB2777"
TXT       = "#FFFFFF"
TXT_SUB   = "#8B8B8B"
FONT      = "Segoe UI"

STD_GEOMETRY = "1500x920"

# JV Analysis exe rule: only the primary action (run/Process) is solid blue; the rest are all
# dark-gray buttons distinguished only by subtle text color.
# per-slot style: (bg, hover, left/right, bold, text color)
_SLOT_STYLE = {
    "open":   (BG_SUB, BG_HOVER, "left",  False, TXT),
    "run":    (ACCENT, ACC_HOV,  "left",  True,  "white"),   # the only solid accent
    "fit":    (BG_SUB, BG_HOVER, "left",  False, "#A78BFA"), # purple text
    "extra":  (BG_SUB, BG_HOVER, "left",  False, TXT),
    "excel":  (BG_SUB, BG_HOVER, "right", False, "#34D399"), # green text
    "png":    (BG_SUB, BG_HOVER, "right", False, TXT),
    "origin": (BG_SUB, BG_HOVER, "right", False, "#F472B6"), # pink text
    "ai":     (BG_SUB, BG_HOVER, "right", False, "#A78BFA"), # purple text
}
# fixed right-slot order (from the far right): excel, png, origin, ai
_RIGHT_ORDER = ["excel", "png", "origin", "ai"]
# fixed left-slot order: open, run, fit, extra...
_LEFT_ORDER = ["open", "run", "fit", "extra"]


def _wrap(cb):
    def inner():
        try:
            cb()
        except Exception as e:
            messagebox.showerror("Error", str(e))
    return inner


def _publication_copy(fig):
    """Return a publication-styled deep copy of a figure: white background,
    black text/axes/ticks, inward ticks on all four sides, no grid.
    The on-screen dark-theme figure is left untouched.
    Returns None if the figure cannot be copied (fall back to screen theme)."""
    try:
        import pickle
        fig2 = pickle.loads(pickle.dumps(fig))
    except Exception:
        return None

    try:
        fig2.patch.set_facecolor("white")
        fig2.patch.set_alpha(1.0)
        for ax in fig2.axes:
            ax.set_facecolor("white")
            for spine in ax.spines.values():
                spine.set_color("black")
                spine.set_linewidth(1.1)
            ax.tick_params(axis="both", which="both", colors="black",
                           direction="in", top=True, right=True)
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
            # recolor light annotation text placed directly on the axes
            for t in ax.texts:
                c = t.get_color()
                if isinstance(c, str) and c.lower() in ("white", "#ffffff", "#aaaaaa", "#888888"):
                    t.set_color("black")
        return fig2
    except Exception:
        return None


def save_fig_png(win, candidates=("fig", "fig_res", "figure", "fig_main")):
    """Shared figure export used by every tool's PNG button.

    Exports a publication-styled copy (white background, black labels, inward
    ticks, 600 dpi raster). SVG/PDF vector output is available from the
    file-type dropdown - preferred by most journals."""
    fig = None
    for holder in (win, getattr(win, "tab", None)):
        if holder is None:
            continue
        for name in candidates:
            f = getattr(holder, name, None)
            if f is not None and hasattr(f, "savefig"):
                fig = f
                break
        if fig:
            break
    if fig is None:
        messagebox.showwarning("Export", "Could not find a graph (Figure) to save.")
        return
    path = filedialog.asksaveasfilename(
        defaultextension=".png",
        filetypes=[("PNG image (600 dpi, publication)", "*.png"),
                   ("SVG vector", "*.svg"),
                   ("PDF vector", "*.pdf"),
                   ("TIFF image (600 dpi)", "*.tif")],
        title="Save plot (publication style)")
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
            fig.savefig(path, dpi=300, facecolor=fig.get_facecolor(),
                        bbox_inches="tight")
        messagebox.showinfo("Export", f"Saved:\n{os.path.basename(path)}")
    except Exception as e:
        messagebox.showerror("Export", f"Save failed: {e}")


def attach_chrome(win, tool_name, actions, status_left="Ready", hints=""):
    """Inject the standard chrome.

    win       : CTkToplevel (called after its inner UI is already built)
    tool_name : name shown in the title/toolbar
    actions   : {"open": ("label", callable) | callable, "run": ..., "fit": ...,
                 "extra": [("label", cb), ...], "excel": ..., "png": ...,
                 "origin": ... or [("label", cb), ...], "ai": ...}
                pass True for png to use the shared save_fig_png.
    hints     : shortcut/help text on the right of the status bar
    return      : status label (tools can call win._shell_status.configure(text=...))
    """
    # ---- unified spec ----
    try:
        win.title(f"{tool_name} — Physiscore")
        win.geometry(STD_GEOMETRY)
        win.minsize(1180, 720)
        win.configure(fg_color=BG_WINDOW)
    except Exception:
        pass

    # ---- build toolbar ----
    bar = ctk.CTkFrame(win, height=52, fg_color=BG_PANEL, corner_radius=0)
    bar.pack_propagate(False)

    ctk.CTkLabel(bar, text=tool_name, font=(FONT, 15, "bold"),
                 text_color=TXT).pack(side="left", padx=(14, 12))

    def norm(v, default_label):
        """(label, cb) or callable -> (label, cb)"""
        if v is None:
            return None
        if callable(v):
            return (default_label, v)
        return v

    def make_btn(parent, label, cb, slot):
        color, hov, _side, bold, tcol = _SLOT_STYLE[slot]
        is_run = (slot == "run")
        return ctk.CTkButton(
            parent, text=label, command=_wrap(cb),
            height=30, width=max(74, 12 + 8 * len(label)),
            fg_color=color, hover_color=hov, text_color=tcol,
            border_width=0 if is_run else 1,
            border_color=BORDER_HI,
            font=(FONT, 12, "bold") if bold else (FONT, 12),
            corner_radius=6)

    # left slots (always same order)
    defaults_left = {"open": "📁 Open", "run": "▶ Process", "fit": "⚡ Auto Fit"}
    for slot in _LEFT_ORDER:
        v = actions.get(slot)
        if v is None:
            continue
        items = v if isinstance(v, list) else [norm(v, defaults_left.get(slot, ""))]
        for it in items:
            if it is None:
                continue
            lbl, cb = it
            make_btn(bar, lbl, cb, slot).pack(side="left", padx=4, pady=9)

    # right slots (always same order: far-right Excel -> PNG -> Origin -> AI)
    defaults_right = {"excel": "Excel", "png": "PNG", "origin": "Origin", "ai": "🤖 AI"}
    for slot in _RIGHT_ORDER:
        v = actions.get(slot)
        if v is None:
            continue
        if slot == "png" and v is True:
            v = ("PNG", lambda w=win: save_fig_png(w))
        items = v if isinstance(v, list) else [norm(v, defaults_right[slot])]
        for it in reversed(items):
            if it is None:
                continue
            lbl, cb = it
            make_btn(bar, lbl, cb, slot).pack(side="right", padx=4, pady=9)

    # ---- build status bar ----
    sb = ctk.CTkFrame(win, height=28, fg_color=BG_PANEL, corner_radius=0)
    sb.pack_propagate(False)
    status = ctk.CTkLabel(sb, text=status_left, font=(FONT, 11), text_color=TXT_SUB)
    status.pack(side="left", padx=12)
    if hints:
        ctk.CTkLabel(sb, text=hints, font=(FONT, 10),
                     text_color="#666666").pack(side="right", padx=12)
    win._shell_status = status

    # ---- inject above/below the existing layout (auto-detect grid/pack) ----
    grid_slaves = win.grid_slaves()
    if grid_slaves:
        # shift all existing grid rows down by 1 and add a status-bar row at the bottom
        infos = [(w, w.grid_info()) for w in grid_slaves]
        maxrow = max(int(gi["row"]) for _, gi in infos)
        ncols = max(int(gi["column"]) + int(gi.get("columnspan", 1)) for _, gi in infos)
        for w, gi in infos:
            w.grid_configure(row=int(gi["row"]) + 1)
        # shift row weights
        for r in range(maxrow + 1, 0, -1):
            cfg = win.grid_rowconfigure(r - 1)
            win.grid_rowconfigure(r, weight=cfg["weight"], minsize=cfg["minsize"])
        win.grid_rowconfigure(0, weight=0, minsize=52)
        win.grid_rowconfigure(maxrow + 2, weight=0, minsize=28)
        bar.grid(row=0, column=0, columnspan=max(ncols, 1), sticky="ew")
        sb.grid(row=maxrow + 2, column=0, columnspan=max(ncols, 1), sticky="ew")
    else:
        pack_slaves = win.pack_slaves()
        if pack_slaves:
            # must be packed before the expanding widget so the status bar is not pushed off
            bar.pack(side="top", fill="x", before=pack_slaves[0])
            sb.pack(side="bottom", fill="x", before=pack_slaves[0])
        else:
            bar.pack(side="top", fill="x")
            sb.pack(side="bottom", fill="x")

    return status
