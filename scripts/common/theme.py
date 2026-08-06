# ============================================================
# scripts/common/theme.py
# shared design tokens + helper widgets extracted from JV Analysis exe
# all tools import this module to share the same UI.
# ============================================================
import customtkinter as ctk

# ---- JV exe palette (run_jv.py measured values) ----
BG_WINDOW   = "#0A0A0A"
BG_PANEL    = "#141414"
BG_CARD     = "#1E1E1E"
BG_SUB      = "#252525"
BG_HOVER    = "#303030"
BORDER      = "#2D2D2D"
BORDER_HI   = "#3D3D3D"

ACCENT      = "#3182F6"
ACCENT_HOV  = "#2563EB"
GREEN       = "#10B981"
GREEN_HOV   = "#059669"
ORANGE      = "#F59E0B"
PURPLE      = "#8B5CF6"
PURPLE_HOV  = "#7C3AED"
PINK        = "#EC4899"
RED         = "#EF4444"

TXT         = "#FFFFFF"
TXT_SUB     = "#8B8B8B"
TXT_DIM     = "#666666"

FONT_UI     = "Segoe UI"
R_PILL      = 8
R_CARD      = 10

# matplotlib dark style (JV exe plot tone)
MPL_STYLE = {
    "figure.facecolor":  BG_CARD,
    "axes.facecolor":    "#161616",
    "axes.edgecolor":    "#444444",
    "axes.labelcolor":   "#DDDDDD",
    "xtick.color":       "#AAAAAA",
    "ytick.color":       "#AAAAAA",
    "text.color":        "#DDDDDD",
    "grid.color":        "#2A2A2A",
    "grid.linestyle":    "--",
    "grid.alpha":        0.6,
    "legend.facecolor":  BG_SUB,
    "legend.edgecolor":  "#444444",
}

SERIES_COLORS = [ACCENT, GREEN, ORANGE, PURPLE, PINK, RED,
                 "#22D3EE", "#A3E635", "#FB923C", "#818CF8"]


def apply_mpl_dark(fig=None, axes=None):
    """Apply the JV dark tone to a Figure/Axes."""
    import matplotlib
    for k, v in MPL_STYLE.items():
        try:
            matplotlib.rcParams[k] = v
        except Exception:
            pass
    if fig is not None:
        fig.patch.set_facecolor(BG_CARD)
    if axes is not None:
        if not isinstance(axes, (list, tuple)):
            axes = [axes]
        for ax in axes:
            ax.set_facecolor("#161616")
            for spine in ax.spines.values():
                spine.set_color("#444444")
            ax.tick_params(colors="#AAAAAA")
            ax.xaxis.label.set_color("#DDDDDD")
            ax.yaxis.label.set_color("#DDDDDD")
            ax.title.set_color("#FFFFFF")


# ---- shared widget factory (JV exe style) ----
def pill_button(master, text, command=None, primary=False, width=100, height=34,
                color=None, hover=None, **kw):
    fg = color or (ACCENT if primary else BG_SUB)
    hv = hover or (ACCENT_HOV if primary else BG_HOVER)
    return ctk.CTkButton(
        master, text=text, command=command, width=width, height=height,
        fg_color=fg, hover_color=hv,
        text_color="white" if (primary or color) else TXT,
        border_width=0 if (primary or color) else 1,
        border_color=BORDER_HI,
        font=(FONT_UI, 12, "bold") if primary else (FONT_UI, 12),
        corner_radius=R_PILL, **kw)


def toolbar(master, height=54):
    bar = ctk.CTkFrame(master, height=height, fg_color=BG_PANEL, corner_radius=0)
    bar.pack(fill="x", side="top")
    bar.pack_propagate(False)
    return bar


def statusbar(master, height=30):
    sb = ctk.CTkFrame(master, height=height, fg_color=BG_PANEL, corner_radius=0)
    sb.pack(fill="x", side="bottom")
    sb.pack_propagate(False)
    return sb


def card(master, **kw):
    return ctk.CTkFrame(master, fg_color=BG_CARD, corner_radius=R_CARD,
                        border_width=1, border_color=BORDER, **kw)


def stat_card(master, title, value="—", unit="", color=ACCENT):
    """JV-exe left Voc/Jsc-style stat card. (frame, value_label) return"""
    f = ctk.CTkFrame(master, fg_color=BG_CARD, corner_radius=R_CARD,
                     border_width=1, border_color=BORDER)
    ctk.CTkLabel(f, text=title, font=(FONT_UI, 11), text_color=TXT_SUB
                 ).pack(anchor="w", padx=12, pady=(8, 0))
    lbl = ctk.CTkLabel(f, text=f"{value} {unit}".strip(),
                       font=(FONT_UI, 16, "bold"), text_color=color)
    lbl.pack(anchor="w", padx=12, pady=(0, 8))
    return f, lbl


def section_label(master, text):
    return ctk.CTkLabel(master, text=text, font=(FONT_UI, 12, "bold"),
                        text_color=ACCENT)
