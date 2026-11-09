"""Shared design tokens and small widget factories for the Tk/customtkinter GUI.

All colours, radii and fonts come from :mod:`scripts.common.palette` (light or
dark, chosen from the configuration). This module adds the customtkinter
widget helpers that every tool window uses so that buttons, cards and tables
look the same everywhere.
"""
from __future__ import annotations

import customtkinter as ctk

from scripts.common.palette import *  # noqa: F401,F403 - re-export the tokens
from scripts.common import palette as _pal

# Backwards-compatible aliases used by older modules.
MPL_STYLE = _pal.MPL_STYLE
SERIES_COLORS = _pal.SERIES_COLORS


def apply_appearance():
    """Set customtkinter's appearance mode to match the palette."""
    try:
        ctk.set_appearance_mode("Dark" if _pal.IS_DARK else "Light")
        ctk.set_default_color_theme("blue")
    except Exception:
        pass


def apply_mpl_dark(fig=None, axes=None):
    """Historical name kept for callers; applies the current plot style."""
    _pal.apply_mpl()
    if fig is not None:
        fig.patch.set_facecolor(_pal.PLOT_BG)
    if axes is not None:
        if not isinstance(axes, (list, tuple)):
            axes = [axes]
        for ax in axes:
            _pal.style_axes(ax, grid=False)


apply_mpl = apply_mpl_dark


# ---- widget factory -------------------------------------------------------
def pill_button(master, text, command=None, primary=False, width=100, height=30,
                color=None, hover=None, **kw):
    """Standard button: solid accent for the primary action, flat grey with a
    hairline border for everything else."""
    fg = color or (_pal.ACCENT if primary else _pal.BG_SUB)
    hv = hover or (_pal.ACCENT_HOV if primary else _pal.BG_HOVER)
    return ctk.CTkButton(
        master, text=text, command=command, width=width, height=height,
        fg_color=fg, hover_color=hv,
        text_color="white" if (primary or color) else _pal.TXT,
        border_width=0 if (primary or color) else 1,
        border_color=_pal.BORDER_HI,
        font=_pal.font(12, "bold") if primary else _pal.font(12),
        corner_radius=_pal.R_PILL, **kw)


def secondary_button(master, text, command=None, width=100, height=28, **kw):
    return pill_button(master, text, command=command, width=width, height=height, **kw)


def toolbar(master, height=44):
    bar = ctk.CTkFrame(master, height=height, fg_color=_pal.BG_PANEL, corner_radius=0)
    bar.pack(fill="x", side="top")
    bar.pack_propagate(False)
    return bar


def statusbar(master, height=24):
    sb = ctk.CTkFrame(master, height=height, fg_color=_pal.BG_PANEL, corner_radius=0)
    sb.pack(fill="x", side="bottom")
    sb.pack_propagate(False)
    return sb


def card(master, **kw):
    kw.setdefault("fg_color", _pal.BG_CARD)
    kw.setdefault("corner_radius", _pal.R_CARD)
    kw.setdefault("border_width", 1)
    kw.setdefault("border_color", _pal.BORDER)
    return ctk.CTkFrame(master, **kw)


def group(master, title, **kw):
    """A card with a small caption, the Tk equivalent of a labelled group box.
    Returns (frame, body) - put widgets into `body`."""
    f = card(master, **kw)
    ctk.CTkLabel(f, text=title, font=_pal.font(11, "bold"), text_color=_pal.TXT_SUB,
                 anchor="w").pack(fill="x", padx=10, pady=(6, 0))
    body = ctk.CTkFrame(f, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=8, pady=(2, 8))
    return f, body


def stat_card(master, title, value="-", unit="", color=None):
    """Compact read-out: caption above a value. Returns (frame, value_label)."""
    f = card(master)
    ctk.CTkLabel(f, text=title, font=_pal.font(10), text_color=_pal.TXT_SUB
                 ).pack(anchor="w", padx=10, pady=(6, 0))
    lbl = ctk.CTkLabel(f, text=f"{value} {unit}".strip(),
                       font=_pal.font(14, "bold"), text_color=color or _pal.TXT)
    lbl.pack(anchor="w", padx=10, pady=(0, 6))
    return f, lbl


def section_label(master, text):
    return ctk.CTkLabel(master, text=text, font=_pal.font(11, "bold"),
                        text_color=_pal.TXT_SUB, anchor="w")


def entry(master, width=90, height=26, **kw):
    kw.setdefault("fg_color", _pal.BG_CARD)
    kw.setdefault("border_color", _pal.BORDER)
    kw.setdefault("text_color", _pal.TXT)
    kw.setdefault("font", _pal.font(11))
    kw.setdefault("corner_radius", _pal.R_INPUT)
    return ctk.CTkEntry(master, width=width, height=height, **kw)


def style_treeview(style=None, rowheight=22):
    """Configure ttk.Treeview to the palette (call once per window)."""
    from tkinter import ttk
    style = style or ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("Treeview", background=_pal.BG_CARD, foreground=_pal.TXT,
                    fieldbackground=_pal.BG_CARD, borderwidth=0, rowheight=rowheight,
                    font=_pal.font(10))
    style.configure("Treeview.Heading", background=_pal.BG_SUB, foreground=_pal.TXT,
                    borderwidth=1, relief="flat", font=_pal.font(10, "bold"))
    style.map("Treeview", background=[("selected", _pal.SELECT)],
              foreground=[("selected", _pal.TXT)])
    style.map("Treeview.Heading", background=[("active", _pal.BG_HOVER)])
    style.configure("Vertical.TScrollbar", background=_pal.BG_SUB, troughcolor=_pal.BG_PANEL,
                    bordercolor=_pal.BORDER, arrowcolor=_pal.TXT_SUB)
    style.configure("Horizontal.TScrollbar", background=_pal.BG_SUB, troughcolor=_pal.BG_PANEL,
                    bordercolor=_pal.BORDER, arrowcolor=_pal.TXT_SUB)
    return style


# ---- key/value read-out table -------------------------------------------
def kv_table(master, height=8, key_width=150, value_width=120):
    """Two-column ttk.Treeview (Quantity | Value) for result read-outs."""
    from tkinter import ttk
    style_treeview()
    tree = ttk.Treeview(master, columns=("k", "v"), show="headings", height=height, selectmode="browse")
    tree.heading("k", text="Quantity")
    tree.heading("v", text="Value")
    tree.column("k", width=key_width, minwidth=90, anchor="w", stretch=True)
    tree.column("v", width=value_width, minwidth=70, anchor="e", stretch=True)
    try:
        from scripts.common import plot_interactions as _pi
        _pi.attach_tree_context_menu(master, tree)
    except Exception:
        pass
    return tree


def fill_kv(tree, items):
    """items: iterable of (key, value[, fmt]) - value None/NaN shown as '-'."""
    import math
    tree.delete(*tree.get_children())
    for it in items:
        key, val = it[0], it[1]
        fmt = it[2] if len(it) > 2 else None
        if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
            txt = "-"
        elif fmt:
            try:
                txt = format(val, fmt)
            except Exception:
                txt = str(val)
        else:
            txt = str(val)
        tree.insert("", "end", values=(key, txt))
