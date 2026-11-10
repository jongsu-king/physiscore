"""Instrument look (3.2): design tokens, the customtkinter theme and the
panel-header pass applied to every tool window."""
import pytest

from scripts.common import palette as _pal


def test_compact_tokens():
    assert _pal.R_CARD == _pal.R_PILL == _pal.R_INPUT == 2
    assert _pal.font(12) == (_pal.FONT_UI, 11)
    assert _pal.font(12, "bold") == (_pal.FONT_UI, 11, "bold")
    assert _pal.font(8)[1] == 8                       # never below 8 pt
    for theme in _pal.PALETTES.values():
        for key in ("HEADER_BG", "HEADER_TXT", "STRIPE", "TOOL_BG"):
            assert key in theme


def test_customtkinter_theme_follows_the_palette():
    ctk = pytest.importorskip("customtkinter")
    from scripts.common import theme  # noqa: F401  installs the theme and the hook
    light, dark = _pal.PALETTES["light"], _pal.PALETTES["dark"]
    t = ctk.ThemeManager.theme
    assert t["CTkOptionMenu"]["fg_color"] == [light["BG_SUB"], dark["BG_SUB"]]
    ctk.set_default_color_theme("blue")               # what standalone entry points call
    assert ctk.ThemeManager.theme["CTkOptionMenu"]["fg_color"] == [light["BG_SUB"], dark["BG_SUB"]]
    assert ctk.ThemeManager.theme["CTkCheckBox"]["corner_radius"] == 2


def _tk_root():
    ctk = pytest.importorskip("customtkinter")
    import tkinter
    try:
        root = ctk.CTk()
    except tkinter.TclError:
        pytest.skip("no display")
    root.withdraw()
    return ctk, root


def test_group_titles_become_header_strips():
    ctk, root = _tk_root()
    from scripts.common import theme
    try:
        packed = theme.card(root)
        packed.pack()
        t1 = ctk.CTkLabel(packed, text="Load Data", font=_pal.font(12, "bold"))
        t1.pack()
        ctk.CTkLabel(packed, text="body text").pack()

        gridded = theme.card(root)
        gridded.pack()
        ctk.CTkLabel(gridded, text="x").grid(row=0, column=0)
        row = ctk.CTkFrame(gridded, fg_color="transparent")
        row.grid(row=0, column=0, columnspan=2)
        ctk.CTkLabel(gridded, text="y").grid(row=1, column=1)
        t2 = ctk.CTkLabel(row, text="Results", font=ctk.CTkFont(size=12, weight="bold"))
        t2.pack(side="left")

        plain = theme.card(root)
        plain.pack()
        ctk.CTkLabel(plain, text="not a title").pack()

        made = theme.instrumentize(root)
        assert made == 2
        assert str(t1.cget("fg_color")).lower() == _pal.HEADER_BG.lower()
        assert str(row.cget("fg_color")).lower() == _pal.HEADER_BG.lower()
        assert int(row.grid_info()["row"]) == 0 and int(row.grid_info()["columnspan"]) == 2
        assert theme.instrumentize(root) == 0          # idempotent
    finally:
        root.destroy()
