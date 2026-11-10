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
apply_appearance()


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
                    font=_pal.font(11))
    style.configure("Treeview.Heading", background=_pal.HEADER_BG, foreground=_pal.HEADER_TXT,
                    borderwidth=1, relief="groove", font=_pal.font(10, "bold"))
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


# ---------------------------------------------------------------------------
# Segmented buttons: white text on the selected (accent) segment, the normal
# text colour on the others. customtkinter gives every segment one text colour,
# which left either the selected or the unselected labels unreadable in the
# light theme. Applied to every CTkSegmentedButton created after this module is
# imported (all tool windows import it).
# ---------------------------------------------------------------------------
def contrast_segmented(seg, selected_text: str = "#FFFFFF", text: str = None):
    text = text or _pal.TXT

    def recolor():
        current = seg.get()
        for value, button in getattr(seg, "_buttons_dict", {}).items():
            try:
                button.configure(text_color=selected_text if value == current else text)
            except Exception:
                pass

    original = getattr(seg, "_select_button_by_value", None)
    if original is not None and not getattr(seg, "_contrast_patched", False):
        def select_and_recolor(value):
            original(value)
            recolor()
        seg._select_button_by_value = select_and_recolor
        seg._contrast_patched = True
    recolor()
    return seg


def _install_segmented_contrast():
    cls = ctk.CTkSegmentedButton
    if getattr(cls, "_physiscore_contrast", False):
        return
    original_init = cls.__init__

    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        try:
            contrast_segmented(self)
        except Exception:
            pass
    cls.__init__ = __init__
    cls._physiscore_contrast = True


_install_segmented_contrast()


# ---------------------------------------------------------------------------
# 3.2 instrument look
# ---------------------------------------------------------------------------
def install_ctk_theme():
    """Replace customtkinter's blue defaults by the palette, for every widget
    created without explicit colours (option menus, check boxes, sliders,
    progress bars, scroll bars, text boxes). Light and dark values come from
    the two palettes, so the appearance mode still switches them."""
    L, D = _pal.PALETTES["light"], _pal.PALETTES["dark"]

    def pair(key):
        return [L[key], D[key]]
    white = ["#FFFFFF", "#FFFFFF"]
    t = ctk.ThemeManager.theme
    try:
        t["CTk"]["fg_color"] = pair("BG_WINDOW")
        t["CTkToplevel"]["fg_color"] = pair("BG_WINDOW")
        t["CTkFrame"].update(corner_radius=_pal.R_CARD, fg_color=pair("BG_PANEL"),
                             top_fg_color=pair("BG_CARD"), border_color=pair("BORDER"))
        t["CTkButton"].update(corner_radius=_pal.R_PILL, fg_color=pair("ACCENT"), hover_color=pair("ACCENT_HOV"),
                              border_color=pair("BORDER_HI"), text_color=white, text_color_disabled=pair("TXT_DIM"))
        t["CTkLabel"]["text_color"] = pair("TXT")
        t["CTkEntry"].update(corner_radius=_pal.R_INPUT, border_width=1, fg_color=pair("BG_CARD"),
                             border_color=pair("BORDER_HI"), text_color=pair("TXT"),
                             placeholder_text_color=pair("TXT_DIM"))
        t["CTkCheckBox"].update(corner_radius=2, border_width=1, fg_color=pair("ACCENT"),
                                border_color=pair("BORDER_HI"), hover_color=pair("BG_HOVER"),
                                checkmark_color=white, text_color=pair("TXT"))
        t["CTkRadioButton"].update(border_width_unchecked=1, border_width_checked=5, fg_color=pair("ACCENT"),
                                   border_color=pair("BORDER_HI"), hover_color=pair("BG_HOVER"),
                                   text_color=pair("TXT"))
        t["CTkSwitch"].update(fg_color=pair("BORDER_HI"), progress_color=pair("ACCENT"),
                              button_color=pair("BG_CARD"), button_hover_color=pair("BG_HOVER"),
                              text_color=pair("TXT"))
        t["CTkProgressBar"].update(corner_radius=1, fg_color=pair("BORDER"), progress_color=pair("ACCENT"))
        t["CTkSlider"].update(corner_radius=2, button_corner_radius=2, fg_color=pair("BORDER"),
                              progress_color=pair("TXT_DIM"), button_color=pair("ACCENT"),
                              button_hover_color=pair("ACCENT_HOV"))
        t["CTkOptionMenu"].update(corner_radius=_pal.R_INPUT, fg_color=pair("BG_SUB"),
                                  button_color=pair("BG_HOVER"), button_hover_color=pair("BORDER"),
                                  text_color=pair("TXT"), text_color_disabled=pair("TXT_DIM"))
        t["CTkComboBox"].update(corner_radius=_pal.R_INPUT, border_width=1, fg_color=pair("BG_CARD"),
                                border_color=pair("BORDER_HI"), button_color=pair("BG_HOVER"),
                                button_hover_color=pair("BORDER"), text_color=pair("TXT"))
        t["CTkScrollbar"].update(corner_radius=2, button_color=pair("BORDER_HI"),
                                 button_hover_color=pair("TXT_DIM"))
        t["CTkSegmentedButton"].update(corner_radius=_pal.R_PILL, border_width=1, fg_color=pair("BORDER_HI"),
                                       selected_color=pair("ACCENT"), selected_hover_color=pair("ACCENT_HOV"),
                                       unselected_color=pair("BG_SUB"), unselected_hover_color=pair("BG_HOVER"),
                                       text_color=pair("TXT"))
        t["CTkTextbox"].update(corner_radius=_pal.R_INPUT, border_width=1, fg_color=pair("BG_CARD"),
                               border_color=pair("BORDER"), text_color=pair("TXT"),
                               scrollbar_button_color=pair("BORDER_HI"))
        t["CTkScrollableFrame"]["label_fg_color"] = pair("HEADER_BG")
        t["DropdownMenu"].update(fg_color=pair("BG_CARD"), hover_color=pair("SELECT"), text_color=pair("TXT"))
        t["CTkFont"].update(family=_pal.FONT_UI, size=_pal._size(12))
    except Exception:
        pass


def _install_theme_hook():
    """Re-apply the palette whenever some module resets customtkinter to its
    built-in "blue" theme (several standalone entry points do)."""
    if getattr(ctk, "_physiscore_theme_hook", False):
        return
    original = ctk.set_default_color_theme

    def set_default_color_theme(name):
        original(name)
        install_ctk_theme()
    ctk.set_default_color_theme = set_default_color_theme
    ctk._physiscore_theme_hook = True


def _install_tree_stripes():
    """Alternate row shading in every ttk.Treeview (rows appended in order)."""
    from tkinter import ttk
    if getattr(ttk.Treeview, "_physiscore_stripes", False):
        return
    original = ttk.Treeview.insert

    def insert(self, parent, index, iid=None, **kw):
        try:
            if not getattr(self, "_stripe_ready", False):
                self.tag_configure("stripe", background=_pal.STRIPE)
                self._stripe_ready = True
            if index == "end" and len(self.get_children(parent)) % 2 == 1:
                tags = kw.get("tags", ())
                tags = (tags,) if isinstance(tags, str) else tuple(tags or ())
                kw["tags"] = tags + ("stripe",)
        except Exception:
            pass
        return original(self, parent, index, iid, **kw)
    ttk.Treeview.insert = insert
    ttk.Treeview._physiscore_stripes = True


def _walk(widget):
    yield widget
    try:
        children = widget.winfo_children()
    except Exception:
        return
    for c in children:
        yield from _walk(c)


def _color_is(value, token: str) -> bool:
    if isinstance(value, (list, tuple)):
        value = value[1 if _pal.IS_DARK else 0] if len(value) == 2 else value[0]
    return str(value).lower() == str(token).lower()


def _first_slave(frame):
    try:
        packed = frame.pack_slaves()
    except Exception:
        packed = []
    if packed:
        return packed[0]
    try:
        gridded = frame.grid_slaves(row=0, column=0)
    except Exception:
        gridded = []
    return gridded[0] if gridded else None


def _is_title(widget) -> bool:
    if not isinstance(widget, ctk.CTkLabel):
        return False
    try:
        text = str(widget.cget("text") or "")
        f = widget.cget("font")
        image = widget.cget("image")
    except Exception:
        return False
    try:
        bold = f.cget("weight") == "bold" if hasattr(f, "cget") else "bold" in str(f)
    except Exception:
        bold = "bold" in str(f)
    return bool(text.strip()) and "\n" not in text and len(text) <= 48 and image is None and bold


def panel_header(label, frame=None):
    """Turn a group title label into a header strip across the top of its box."""
    try:
        label.configure(fg_color=_pal.HEADER_BG, text_color=_pal.HEADER_TXT, corner_radius=0,
                        anchor="w", font=_pal.font(11, "bold"), height=22)
        try:
            label._label.grid_configure(padx=(8, 6))      # text inset inside the strip
        except Exception:
            pass
        mgr = label.winfo_manager()
        if mgr == "pack":
            label.pack_configure(fill="x", padx=1, pady=(1, 6), anchor="w")
        elif mgr == "grid":
            cols = max(1, (frame or label.master).grid_size()[0])
            label.grid_configure(columnspan=cols, sticky="ew", padx=1, pady=(1, 6))
        label._physiscore_header = True
    except Exception:
        pass


def instrumentize(root) -> int:
    """Give a finished window the instrument look: every white group box gets
    square corners and a hairline border, and its bold title becomes a header
    strip (the title bar of a dock panel). Returns the number of headers made.
    Applied by analysis_shell.attach_chrome to every tool window."""
    made = 0
    for w in list(_walk(root)):
        if not isinstance(w, ctk.CTkFrame):
            continue
        try:
            fg = w.cget("fg_color")
        except Exception:
            continue
        if not _color_is(fg, _pal.BG_CARD):
            continue
        try:
            w.configure(corner_radius=_pal.R_CARD, border_width=1, border_color=_pal.BORDER)
        except Exception:
            pass
        first = _first_slave(w)
        if first is not None and _is_title(first) and not getattr(first, "_physiscore_header", False):
            panel_header(first, w)
            made += 1
        elif isinstance(first, ctk.CTkFrame) and not getattr(first, "_physiscore_header", False):
            # a title row: [bold title][other widgets...] in a transparent frame
            try:
                transparent = str(first.cget("fg_color")) == "transparent"
            except Exception:
                transparent = False
            inner = _first_slave(first) if transparent else None
            if inner is not None and _is_title(inner):
                header_row(first, inner, w)
                made += 1
    return made


def header_row(row, title, frame=None):
    """Turn a title row (title label plus small controls) into a header strip."""
    try:
        row.configure(fg_color=_pal.HEADER_BG, corner_radius=0)
        title.configure(text_color=_pal.HEADER_TXT, font=_pal.font(11, "bold"))
        mgr = row.winfo_manager()
        if mgr == "pack":
            row.pack_configure(fill="x", padx=1, pady=(1, 6), ipady=1)
            try:
                title.pack_configure(padx=(8, 6))
            except Exception:
                pass
        elif mgr == "grid":
            cols = max(1, (frame or row.master).grid_size()[0])
            row.grid_configure(columnspan=cols, sticky="ew", padx=1, pady=(1, 6), ipady=1)
            try:
                if title.winfo_manager() == "pack":
                    title.pack_configure(padx=(8, 6))
            except Exception:
                pass
        row._physiscore_header = True
    except Exception:
        pass


_install_theme_hook()
install_ctk_theme()
_install_tree_stripes()
