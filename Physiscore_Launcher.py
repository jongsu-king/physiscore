# ============================================================
# Physiscore_Launcher.py
# unified launcher with the same UI format as JV Analysis exe (new file)
#  - top toolbar: category segments + Settings button (Origin/API key popup)
#  - body: analysis-tool cards for the selected category
#  - bottom status bar: Ready / Origin & API status
#  - PL & XRD merge the Pro (spectra auto-fit) into a single card
#  - does not modify the existing main gui_test3.py
# ============================================================
import os
import sys
import json
import threading
import subprocess
import importlib

import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image
                                                                                                                                    
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.common import app_config  # noqa: E402  (needs BASE_DIR on sys.path)

CONFIG_FILE = app_config.config_path()
APP_VERSION = "2.0.0"

# ------------------------------------------------------------
# JV Analysis exe design tokens (measured from run_jv.py)
# ------------------------------------------------------------
BG_WINDOW   = "#0A0A0A"   # deepest background
BG_PANEL    = "#141414"   # left/toolbar panel
BG_CARD     = "#1E1E1E"   # card
BG_SUB      = "#252525"   # input/sub area
BG_HOVER    = "#303030"
BORDER      = "#2D2D2D"
BORDER_HI   = "#3D3D3D"

ACCENT      = "#3182F6"   # JV blue
ACCENT_HOV  = "#2563EB"
GREEN       = "#10B981"
GREEN_HOV   = "#059669"
ORANGE      = "#F59E0B"
PURPLE      = "#8B5CF6"
PINK        = "#EC4899"
RED         = "#EF4444"

TXT         = "#FFFFFF"
TXT_SUB     = "#8B8B8B"
TXT_DIM     = "#666666"

FONT_UI     = "Segoe UI"
R_PILL      = 8           # JV exe pill radius
R_CARD      = 10

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# ------------------------------------------------------------
# analysis-tool registry (overlapping Pro merged into the main card)
#  key: (display name, category, icon file, module path, spectra tab or None)
# ------------------------------------------------------------
CATEGORIES = ["All", "Optoelectronic", "Structural", "Optical", "Spectroscopic"]

# using "exe:<filename>" as mod_path runs that external (upgraded) exe directly.
TOOLS = [
    ("J-V Curve",      "Optoelectronic", "J-V Curve.png", "exe:JV_Analysis.exe",         None),
    ("J-V Dark",       "Optoelectronic", "J-V dark.png",  "scripts.Dark_JV.run_jv_dark", None),
    ("EQE",            "Optoelectronic", "EQE.png",       "scripts.EQE.run_eqe",         None),
    ("FE-SEM",         "Structural",     "FE-SEM.png",    "scripts.SEM.run_sem",         None),
    ("XRD",            "Structural",     "XRD.png",       "scripts.XRD.run_xrd",         "XRD"),
    ("Abs",            "Optical",        "Abs.png",       "scripts.Abs.run_abs",         None),
    ("PL",             "Optical",        "PL.png",        "scripts.PL.run_pl",           "PL"),
    ("Raman",          "Spectroscopic",  "Raman.png",     "scripts.Raman.run_raman",     None),
    ("FTIR",           "Spectroscopic",  "FTIR.png",      "scripts.FTIR.run_ftir",       None),
]

# candidate paths for the upgraded external exe (sibling folder first)
def find_external_exe(filename):
    candidates = [
        os.path.join(BASE_DIR, filename),
        os.path.join(BASE_DIR, os.path.splitext(filename)[0], filename),
        os.path.join(os.path.dirname(BASE_DIR), os.path.splitext(filename)[0], filename),
        os.path.join(os.path.dirname(BASE_DIR), filename),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def resource_dir(sub: str) -> str:
    """Find resource folder in both frozen(exe) and source runs."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        p = os.path.join(base, sub)
        if os.path.isdir(p):
            return p
        return os.path.join(os.path.dirname(sys.executable), sub)
    return os.path.join(BASE_DIR, sub)


# ------------------------------------------------------------
# Settings popup (Origin path + Gemini API key)
# ------------------------------------------------------------
class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Settings")
        self.geometry("560x330")
        self.resizable(False, False)
        self.configure(fg_color=BG_WINDOW)
        self.transient(parent)
        self.grab_set()

        body = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=R_CARD,
                            border_width=1, border_color=BORDER)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(body, text="Settings", font=(FONT_UI, 17, "bold"),
                     text_color=TXT).pack(anchor="w", padx=18, pady=(14, 2))
        ctk.CTkLabel(body, text="Configure the Origin executable and Gemini API Key.",
                     font=(FONT_UI, 11), text_color=TXT_SUB).pack(anchor="w", padx=18, pady=(0, 12))

        # --- Origin path ---
        ctk.CTkLabel(body, text="OriginLab Executable", font=(FONT_UI, 12, "bold"),
                     text_color=ACCENT).pack(anchor="w", padx=18)
        row1 = ctk.CTkFrame(body, fg_color="transparent")
        row1.pack(fill="x", padx=18, pady=(4, 12))
        self.ent_origin = ctk.CTkEntry(row1, height=34, fg_color=BG_SUB,
                                       border_color=BORDER, text_color=TXT,
                                       placeholder_text=r"C:\Program Files\OriginLab\...\Origin64.exe")
        self.ent_origin.pack(side="left", fill="x", expand=True)
        if parent.origin_path:
            self.ent_origin.insert(0, parent.origin_path)
        ctk.CTkButton(row1, text="Browse", width=84, height=34,
                      fg_color=BG_SUB, hover_color=BG_HOVER, border_width=1,
                      border_color=BORDER_HI, text_color=TXT, corner_radius=R_PILL,
                      command=self._browse).pack(side="left", padx=(8, 0))

        # --- Gemini API key ---
        ctk.CTkLabel(body, text="Gemini API Key", font=(FONT_UI, 12, "bold"),
                     text_color=ACCENT).pack(anchor="w", padx=18)
        row2 = ctk.CTkFrame(body, fg_color="transparent")
        row2.pack(fill="x", padx=18, pady=(4, 4))
        self.ent_key = ctk.CTkEntry(row2, height=34, fg_color=BG_SUB, show="*",
                                    border_color=BORDER, text_color=TXT,
                                    placeholder_text="AIza...")
        self.ent_key.pack(side="left", fill="x", expand=True)
        if parent.gemini_api_key:
            self.ent_key.insert(0, parent.gemini_api_key)
        self._shown = False
        ctk.CTkButton(row2, text="Show", width=64, height=34,
                      fg_color=BG_SUB, hover_color=BG_HOVER, border_width=1,
                      border_color=BORDER_HI, text_color=TXT, corner_radius=R_PILL,
                      command=self._toggle_show).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(body, text="The key is stored only in physisfera_config.json on this PC.",
                     font=(FONT_UI, 10), text_color=TXT_DIM).pack(anchor="w", padx=18)

        # --- buttons ---
        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.pack(fill="x", padx=18, pady=(14, 14), side="bottom")
        ctk.CTkButton(btns, text="Cancel", width=90, height=36,
                      fg_color=BG_SUB, hover_color=BG_HOVER, text_color=TXT,
                      border_width=1, border_color=BORDER_HI, corner_radius=R_PILL,
                      command=self.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btns, text="Save", width=110, height=36,
                      fg_color=ACCENT, hover_color=ACCENT_HOV, text_color="white",
                      font=(FONT_UI, 13, "bold"), corner_radius=R_PILL,
                      command=self._save).pack(side="right")

        self.after(80, self.focus)

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select Origin Executable",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")])
        if path:
            self.ent_origin.delete(0, "end")
            self.ent_origin.insert(0, path)

    def _toggle_show(self):
        self._shown = not self._shown
        self.ent_key.configure(show="" if self._shown else "*")

    def _save(self):
        self.parent.origin_path = self.ent_origin.get().strip()
        self.parent.gemini_api_key = self.ent_key.get().strip()
        self.parent.save_config()
        self.parent.refresh_statusbar()
        self.parent.toast("Settings saved")
        self.destroy()


# ------------------------------------------------------------
# main launcher
# ------------------------------------------------------------
class LauncherApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Physiscore — Analysis Suite")
        self.geometry("1180x760")
        self.minsize(980, 640)
        self.configure(fg_color=BG_WINDOW)

        self.origin_path = ""
        self.gemini_api_key = ""
        self.load_config()

        self.logo_dir = resource_dir("logo")
        self.modules = {}          # module_path -> module | None(failed) | "loading"
        self.cards = {}            # module_path -> card widgets
        self.current_category = "All"
        self._toast = None

        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self.refresh_cards()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # load modules in the background (show start screen immediately)
        threading.Thread(target=self._preload_modules, daemon=True).start()

    # ---------------- config ----------------
    def load_config(self):
        data = app_config.load(refresh=True)
        self.origin_path = data.get("origin_path", "")
        self.gemini_api_key = data.get("gemini_api_key", "")
        if self.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = self.gemini_api_key
            os.environ.setdefault("GOOGLE_API_KEY", self.gemini_api_key)

    def save_config(self):
        # merge-preserve: keep keys managed elsewhere (cell_area_cm2 for the
        # JV/Dark-JV cores, name_presets for the sample-naming menu) instead of
        # overwriting the file. app_config.update also writes atomically, so an
        # interrupted save cannot truncate the config.
        try:
            app_config.update({"origin_path": self.origin_path,
                               "gemini_api_key": self.gemini_api_key})
        except Exception as e:
            print(f"Config save error: {e}")
        if self.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = self.gemini_api_key
            os.environ.setdefault("GOOGLE_API_KEY", self.gemini_api_key)

    # ---------------- UI: toolbar ----------------
    def _build_toolbar(self):
        bar = ctk.CTkFrame(self, height=54, fg_color=BG_PANEL, corner_radius=0)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        ctk.CTkLabel(bar, text="Physiscore", font=(FONT_UI, 17, "bold"),
                     text_color=TXT).pack(side="left", padx=(16, 4))
        ctk.CTkLabel(bar, text="Analysis Suite", font=(FONT_UI, 11),
                     text_color=TXT_SUB).pack(side="left", padx=(0, 18))

        # category segments (JV exe pill style)
        self.seg = ctk.CTkSegmentedButton(
            bar, values=CATEGORIES, height=34,
            fg_color=BG_SUB,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOV,
            unselected_color=BG_SUB, unselected_hover_color=BG_HOVER,
            text_color=TXT, font=(FONT_UI, 12),
            corner_radius=R_PILL, command=self._on_category)
        self.seg.set("All")
        self.seg.pack(side="left", padx=4, pady=10)

        # right: Settings
        ctk.CTkButton(bar, text="⚙  Settings", width=110, height=34,
                      fg_color=BG_SUB, hover_color=BG_HOVER, text_color=TXT,
                      border_width=1, border_color=BORDER_HI,
                      font=(FONT_UI, 12), corner_radius=R_PILL,
                      command=self.open_settings).pack(side="right", padx=16, pady=10)

        # search
        self.search_var = ctk.StringVar()
        ent = ctk.CTkEntry(bar, width=210, height=34, fg_color=BG_SUB,
                           border_color=BORDER, text_color=TXT,
                           placeholder_text="Search tools...",
                           textvariable=self.search_var)
        ent.pack(side="right", padx=(0, 4), pady=10)
        ent.bind("<KeyRelease>", lambda e: self.refresh_cards())

    # ---------------- UI: body ----------------
    def _build_body(self):
        self.body = ctk.CTkScrollableFrame(self, fg_color=BG_WINDOW,
                                           scrollbar_button_color=BG_PANEL,
                                           scrollbar_button_hover_color=BG_HOVER)
        self.body.pack(fill="both", expand=True, padx=14, pady=(10, 6))

    # ---------------- UI: statusbar ----------------
    def _build_statusbar(self):
        sb = ctk.CTkFrame(self, height=30, fg_color=BG_PANEL, corner_radius=0)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)
        self.lbl_ready = ctk.CTkLabel(sb, text="Ready", font=(FONT_UI, 11),
                                      text_color=TXT_SUB)
        self.lbl_ready.pack(side="left", padx=14)
        self.lbl_env = ctk.CTkLabel(sb, text="", font=(FONT_UI, 11),
                                    text_color=TXT_DIM)
        self.lbl_env.pack(side="right", padx=14)
        self.refresh_statusbar()

    def refresh_statusbar(self):
        o = "Origin: ✓" if self.origin_path else "Origin: —"
        k = "API Key: ✓" if self.gemini_api_key else "API Key: —"
        self.lbl_env.configure(text=f"{o}   ·   {k}   ·   v{APP_VERSION}")

    # ---------------- module loading ----------------
    def _preload_modules(self):
        for _, _, _, mod_path, _ in TOOLS:
            self.modules[mod_path] = "loading"
        for _, _, _, mod_path, _ in TOOLS:
            if mod_path.startswith("exe:"):
                # external exe: check file existence instead of importing
                exe = find_external_exe(mod_path[4:])
                self.modules[mod_path] = exe  # path(str) or None
            else:
                try:
                    self.modules[mod_path] = importlib.import_module(mod_path)
                except Exception as e:
                    print(f"[Physiscore] {mod_path} import failed: {e}")
                    self.modules[mod_path] = None
            try:
                self.after(0, self._update_card_state, mod_path)
            except Exception:
                return  # window already closed

    def _update_card_state(self, mod_path):
        card = self.cards.get(mod_path)
        if not card:
            return
        mod = self.modules.get(mod_path)
        badge, btn = card["badge"], card["btn"]
        is_exe = mod_path.startswith("exe:")
        if mod == "loading":
            badge.configure(text="LOADING", fg_color=BG_SUB, text_color=TXT_SUB)
            btn.configure(state="disabled", fg_color=BG_SUB, text_color=TXT_SUB)
        elif mod is None:
            # if external exe missing, show as info-only (disabled); if a module, ERROR
            badge.configure(text="EXE not found" if is_exe else "ERROR",
                            fg_color=RED, text_color="white")
            btn.configure(state="disabled", fg_color=BG_SUB, text_color=TXT_SUB)
        else:
            badge.configure(text="UPGRADED" if is_exe else "READY",
                            fg_color=PURPLE if is_exe else GREEN, text_color="white")
            btn.configure(state="normal", fg_color=ACCENT, text_color="white")

    # ---------------- render cards ----------------
    def refresh_cards(self):
        for w in self.body.winfo_children():
            w.destroy()
        self.cards.clear()

        q = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        cat = self.current_category

        visible = [t for t in TOOLS
                   if (cat == "All" or t[1] == cat)
                   and (not q or q in t[0].lower())]

        grid = ctk.CTkFrame(self.body, fg_color="transparent")
        grid.pack(fill="both", expand=True)
        cols = 3
        for i in range(cols):
            grid.grid_columnconfigure(i, weight=1, uniform="col")

        for idx, (name, category, icon, mod_path, spectra_tab) in enumerate(visible):
            r, c = divmod(idx, cols)
            self._build_card(grid, r, c, name, category, icon, mod_path, spectra_tab)

        self.lbl_ready.configure(text=f"Ready · {len(visible)} tools")

    def _build_card(self, parent, r, c, name, category, icon, mod_path, spectra_tab):
        card = ctk.CTkFrame(parent, fg_color=BG_CARD, corner_radius=R_CARD,
                            border_width=1, border_color=BORDER)
        card.grid(row=r, column=c, padx=8, pady=8, sticky="nsew")
        card.bind("<Enter>", lambda e: card.configure(border_color=ACCENT))
        card.bind("<Leave>", lambda e: card.configure(border_color=BORDER))

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(14, 6))

        img = None
        p = os.path.join(self.logo_dir, icon)
        if os.path.exists(p):
            try:
                pil = Image.open(p)
                img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(44, 44))
            except Exception:
                img = None
        if img:
            ctk.CTkLabel(top, text="", image=img).pack(side="left")
        ctk.CTkLabel(top, text=name, font=(FONT_UI, 15, "bold"),
                     text_color=TXT).pack(side="left", padx=(10, 0))

        badge = ctk.CTkLabel(top, text="LOADING", font=(FONT_UI, 9, "bold"),
                             fg_color=BG_SUB, text_color=TXT_SUB,
                             corner_radius=6, padx=8, pady=3)
        badge.pack(side="right")

        ctk.CTkLabel(card, text=category, font=(FONT_UI, 10),
                     text_color=TXT_SUB).pack(anchor="w", padx=16)

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(10, 14))
        btn = ctk.CTkButton(btns, text="Open", height=34,
                            fg_color=BG_SUB, text_color=TXT_SUB, state="disabled",
                            hover_color=ACCENT_HOV, font=(FONT_UI, 12, "bold"),
                            corner_radius=R_PILL,
                            command=lambda m=mod_path, n=name: self.open_tool(m, n))
        btn.pack(side="left", fill="x", expand=True)

        if spectra_tab:
            ctk.CTkButton(btns, text="Auto-Fit", width=76, height=34,
                          fg_color=BG_SUB, hover_color=BG_HOVER, text_color=GREEN,
                          border_width=1, border_color=BORDER_HI,
                          font=(FONT_UI, 11), corner_radius=R_PILL,
                          command=lambda t=spectra_tab: self.open_spectra(t)
                          ).pack(side="left", padx=(8, 0))

        self.cards[mod_path] = {"badge": badge, "btn": btn}
        self._update_card_state(mod_path)

    # ---------------- launch ----------------
    def open_tool(self, mod_path, name):
        mod = self.modules.get(mod_path)

        # (1) run the external upgraded exe directly (e.g. JV_Analysis.exe)
        if mod_path.startswith("exe:"):
            exe = mod if isinstance(mod, str) else find_external_exe(mod_path[4:])
            if not exe or not os.path.isfile(exe):
                messagebox.showerror(
                    "Error",
                    f"Cannot find the upgraded executable for {name}.\n"
                    f"(place {mod_path[4:]} in this folder or a sibling folder)")
                return
            try:
                # sync current settings to physisfera_config.json in the exe's folder
                self._sync_config_to(os.path.dirname(exe))
                subprocess.Popen([exe], cwd=os.path.dirname(exe))
                self.toast(f"Launched {name} (upgraded)")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to run {name}:\n{e}")
            return

        # (2) built-in tkinter module
        if mod in (None, "loading"):
            messagebox.showerror("Error", f"The {name} module is not ready yet.")
            return
        try:
            win_cls = getattr(mod, "AnalysisWindow")
        except AttributeError:
            messagebox.showerror("Error", f"AnalysisWindow not found in {mod_path}.")
            return
        try:
            self.iconify()
            win = win_cls(self, self.origin_path, self.gemini_api_key)
            self.wait_window(win)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to run {name}:\n{e}")
        finally:
            self.deiconify()

    def _sync_config_to(self, folder):
        """Share Origin/API key via physisfera_config.json in the external exe folder."""
        try:
            target = os.path.join(folder, "physisfera_config.json")
            data = {}
            if os.path.exists(target):
                with open(target, "r", encoding="utf-8") as f:
                    data = json.load(f)
            if self.origin_path:
                data["origin_path"] = self.origin_path
            if self.gemini_api_key:
                data["gemini_api_key"] = self.gemini_api_key
            with open(target, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"config sync skip: {e}")

    def open_spectra(self, tab):
        """PL/XRD advanced auto-fit (spectra) - run as a separate process (avoid nested mainloop)"""
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--spectra", tab]
            else:
                cmd = [sys.executable, "-m", "spectra.app", tab]
            subprocess.Popen(cmd, cwd=BASE_DIR)
            self.toast(f"Launched Auto-Fit {tab} window")
        except Exception as e:
            messagebox.showerror("Error", f"Auto-Fit failed:\n{e}")

    def open_settings(self):
        SettingsDialog(self)

    def _on_category(self, value):
        self.current_category = value
        self.refresh_cards()

    def toast(self, msg):
        if self._toast is not None and self._toast.winfo_exists():
            self._toast.destroy()
        self._toast = ctk.CTkLabel(self, text=f"✓ {msg}", fg_color=GREEN,
                                   text_color="white", corner_radius=R_PILL,
                                   font=(FONT_UI, 12, "bold"), padx=16, pady=8)
        self._toast.place(relx=0.5, rely=0.93, anchor="center")
        self.after(1800, lambda: self._toast.destroy()
                   if self._toast and self._toast.winfo_exists() else None)

    def on_closing(self):
        try:
            for aid in self.tk.call("after", "info"):
                try:
                    self.after_cancel(aid)
                except Exception:
                    pass
        except Exception:
            pass
        self.quit()
        self.destroy()


if __name__ == "__main__":
    if "--spectra" in sys.argv:
        _i = sys.argv.index("--spectra")
        _tab = sys.argv[_i + 1] if len(sys.argv) > _i + 1 else "PL"
        try:
            from spectra.app import App as SpectraApp
            SpectraApp(start_tab=_tab).mainloop()
        except Exception as e:
            print(f"spectra run failed: {e}")
        sys.exit(0)
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = LauncherApp()
    app.mainloop()
