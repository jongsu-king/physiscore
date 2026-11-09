# ============================================================
# Physiscore_Launcher.py - main window of the analysis suite
#  - menu bar (File / Analysis / Tools / Help) and a compact tool grid
#  - Settings: Origin path, API key, cell area, theme
#  - status bar: cell area, Origin, version
#  - command line: --version, --selftest [--out f], --update, --spectra TAB,
#    --tool NAME (open one analysis window directly)
# ============================================================
import importlib
import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from scripts.common import app_config  # noqa: E402
from scripts.common import palette as _pal  # noqa: E402

CONFIG_FILE = app_config.config_path()
APP_VERSION = "3.1.2"
REPO_URL = "https://github.com/jongsu-king/physiscore"

ctk.set_appearance_mode("Dark" if _pal.IS_DARK else "Light")
ctk.set_default_color_theme("blue")

CATEGORIES = ["All", "Device", "Optical", "Structural", "Vibrational", "Surface"]

# (name, category, icon file, module path, auto-fit tab or None, description)
# module path "exe:<file>" prefers an external program (Windows) and falls back
# to the built-in module; "spectra:<TAB>" opens the auto-fit workspace.
TOOLS = [
    ("J-V Curve", "Device", "J-V Curve.png", "exe:JV_Analysis.exe", None,
     "Voc, Jsc, FF, PCE, Rs, Rsh from the curve; one-diode fit; forward/reverse hysteresis; group statistics"),
    ("J-V Dark", "Device", "J-V dark.png", "scripts.Dark_JV.run_jv_dark", None,
     "Ideality factor, J0, Rsh and Rs from dark curves; full diode fit and Cheung analysis"),
    ("Device summary", "Device", "J-V Curve.png", "scripts.Device.run_device", None,
     "J-V + EQE (+ absorbance, PL) of one device: Jsc cross-check, band gap from three techniques, Voc vs Voc,rad and Voc,SQ"),
    ("EQE", "Device", "EQE.png", "scripts.EQE.run_eqe", None,
     "AM1.5G-integrated Jsc, band gap (Rau), Urbach energy, Voc,rad and voltage-loss breakdown"),
    ("Absorbance", "Optical", "Abs.png", "scripts.Abs.run_abs", None,
     "Tauc plot with automatic linear-region selection, Urbach tail, derivative band gap"),
    ("PL", "Optical", "PL.png", "scripts.PL.run_pl", "PL",
     "Baseline, Gaussian/Voigt fitting, energy axis with Jacobian, quenching efficiency"),
    ("XRD", "Structural", "XRD.png", "scripts.XRD.run_xrd", "XRD",
     "Background, pseudo-Voigt peak fitting, d-spacing, Scherrer, Williamson-Hall, Kalpha2 stripping"),
    ("FE-SEM", "Structural", "FE-SEM.png", "scripts.SEM.run_sem", None,
     "Grain segmentation, size distribution with log-normal statistics"),
    ("Raman", "Vibrational", "Raman.png", "scripts.Raman.run_raman", None,
     "Baseline, band detection and Lorentzian fitting, peak-shift tables, band library"),
    ("FTIR", "Vibrational", "FTIR.png", "scripts.FTIR.run_ftir", None,
     "Transmittance/absorbance, baseline, band fitting, peak-shift tables, band library"),
    ("XPS", "Surface", "logo.png", "spectra:XPS", None,
     "Shirley background, Voigt singlet/doublet fitting, charge referencing, atomic concentration"),
]

BUILTIN_FALLBACK = {"exe:JV_Analysis.exe": "scripts.JV.run_jv"}


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
    """Resource folder in both frozen and source runs."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        p = os.path.join(base, sub)
        if os.path.isdir(p):
            return p
        return os.path.join(os.path.dirname(sys.executable), sub)
    return os.path.join(BASE_DIR, sub)


# ------------------------------------------------------------
# Settings dialog
# ------------------------------------------------------------
class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title("Settings")
        self.geometry("560x420")
        self.resizable(False, False)
        self.configure(fg_color=_pal.BG_WINDOW)
        self.transient(parent)
        self.grab_set()

        body = ctk.CTkFrame(self, fg_color=_pal.BG_CARD, corner_radius=_pal.R_CARD,
                            border_width=1, border_color=_pal.BORDER)
        body.pack(fill="both", expand=True, padx=12, pady=12)

        def label(text, pady=(10, 2)):
            ctk.CTkLabel(body, text=text, font=_pal.font(11, "bold"), text_color=_pal.TXT_SUB,
                         anchor="w").pack(fill="x", padx=16, pady=pady)

        def field(placeholder="", show=None):
            e = ctk.CTkEntry(body, height=28, fg_color=_pal.BG_SUB, border_color=_pal.BORDER,
                             text_color=_pal.TXT, font=_pal.font(11), corner_radius=_pal.R_INPUT,
                             placeholder_text=placeholder, show=show or "")
            return e

        # cell area
        label("Device active area (cm²)", pady=(14, 2))
        row0 = ctk.CTkFrame(body, fg_color="transparent")
        row0.pack(fill="x", padx=16)
        self.ent_area = field("0.04")
        self.ent_area.pack(side="left", fill="x", expand=True)
        self.ent_area.insert(0, f"{app_config.cell_area_cm2():g}")
        ctk.CTkLabel(row0, text="Scales Jsc and PCE linearly; re-read for every analysis.",
                     font=_pal.font(10), text_color=_pal.TXT_DIM).pack(side="left", padx=10)

        # Origin
        label("OriginLab executable (Windows, optional)")
        row1 = ctk.CTkFrame(body, fg_color="transparent")
        row1.pack(fill="x", padx=16)
        self.ent_origin = field(r"C:\Program Files\OriginLab\...\Origin64.exe")
        self.ent_origin.pack(side="left", fill="x", expand=True)
        if parent.origin_path:
            self.ent_origin.insert(0, parent.origin_path)
        ctk.CTkButton(row1, text="Browse...", width=84, height=28, fg_color=_pal.BG_SUB,
                      hover_color=_pal.BG_HOVER, border_width=1, border_color=_pal.BORDER_HI,
                      text_color=_pal.TXT, corner_radius=_pal.R_PILL, font=_pal.font(11),
                      command=self._browse).pack(side="left", padx=(8, 0))

        # API key
        label("Gemini API key (optional; enables the interpretation panels only)")
        row2 = ctk.CTkFrame(body, fg_color="transparent")
        row2.pack(fill="x", padx=16)
        self.ent_key = field("AIza...", show="*")
        self.ent_key.pack(side="left", fill="x", expand=True)
        if parent.gemini_api_key:
            self.ent_key.insert(0, parent.gemini_api_key)
        self._shown = False
        ctk.CTkButton(row2, text="Show", width=64, height=28, fg_color=_pal.BG_SUB,
                      hover_color=_pal.BG_HOVER, border_width=1, border_color=_pal.BORDER_HI,
                      text_color=_pal.TXT, corner_radius=_pal.R_PILL, font=_pal.font(11),
                      command=self._toggle_show).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(body, text="Stored only in physisfera_config.json on this computer. "
                                "No numerical result depends on it.",
                     font=_pal.font(10), text_color=_pal.TXT_DIM, anchor="w").pack(fill="x", padx=16)

        # theme
        label("Appearance (applies after restart)")
        self.theme_var = ctk.StringVar(value=_pal.THEME.capitalize())
        ctk.CTkSegmentedButton(body, values=["Light", "Dark"], variable=self.theme_var, height=26,
                               font=_pal.font(11), corner_radius=_pal.R_PILL,
                               selected_color=_pal.ACCENT, selected_hover_color=_pal.ACCENT_HOV,
                               unselected_color=_pal.BG_SUB, unselected_hover_color=_pal.BG_HOVER,
                               text_color=_pal.TXT).pack(anchor="w", padx=16)

        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(12, 12), side="bottom")
        ctk.CTkButton(btns, text="Cancel", width=90, height=30, fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
                      text_color=_pal.TXT, border_width=1, border_color=_pal.BORDER_HI,
                      corner_radius=_pal.R_PILL, font=_pal.font(11), command=self.destroy).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btns, text="Save", width=100, height=30, fg_color=_pal.ACCENT, hover_color=_pal.ACCENT_HOV,
                      text_color="white", font=_pal.font(11, "bold"), corner_radius=_pal.R_PILL,
                      command=self._save).pack(side="right")
        self.after(80, self.focus)

    def _browse(self):
        path = filedialog.askopenfilename(title="Select Origin executable",
                                          filetypes=[("Executable", "*.exe"), ("All files", "*.*")])
        if path:
            self.ent_origin.delete(0, "end")
            self.ent_origin.insert(0, path)

    def _toggle_show(self):
        self._shown = not self._shown
        self.ent_key.configure(show="" if self._shown else "*")

    def _save(self):
        try:
            area = float(self.ent_area.get())
            if not area > 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Settings", "The device area must be a positive number (cm²).", parent=self)
            return
        self.parent.origin_path = self.ent_origin.get().strip()
        self.parent.gemini_api_key = self.ent_key.get().strip()
        theme = self.theme_var.get().lower()
        self.parent.save_config(extra={"cell_area_cm2": area, "theme": theme})
        self.parent.refresh_statusbar()
        if theme != _pal.THEME:
            self.parent.set_status("Appearance saved; restart Physiscore to apply it.")
        else:
            self.parent.set_status("Settings saved.")
        self.destroy()


# ------------------------------------------------------------
# Main window
# ------------------------------------------------------------
class LauncherApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Physiscore")
        self.geometry("1180x740")
        self.minsize(960, 620)
        self.configure(fg_color=_pal.BG_WINDOW)

        self.origin_path = ""
        self.gemini_api_key = ""
        self.load_config()

        self.logo_dir = resource_dir("logo")
        self.modules = {}          # module_path -> module | None | "loading" | str(exe path)
        self.cards = {}
        self.current_category = "All"
        self.updater = None

        self._build_menubar()
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self.refresh_cards()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self._setup_updates()
        # imports run in a worker thread; the main thread polls the results
        # (an after() issued from the worker is dropped by some Tk builds)
        self._preload_done = False
        threading.Thread(target=self._preload_modules, daemon=True).start()
        self.after(100, self._poll_modules)

    # ---------------- config ----------------
    def load_config(self):
        data = app_config.load(refresh=True)
        self.origin_path = data.get("origin_path", "")
        self.gemini_api_key = data.get("gemini_api_key", "")
        if self.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = self.gemini_api_key
            os.environ.setdefault("GOOGLE_API_KEY", self.gemini_api_key)

    def save_config(self, extra=None):
        values = {"origin_path": self.origin_path, "gemini_api_key": self.gemini_api_key}
        if extra:
            values.update(extra)
        try:
            app_config.update(values)
        except Exception as e:
            print(f"Config save error: {e}")
        if self.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = self.gemini_api_key
            os.environ.setdefault("GOOGLE_API_KEY", self.gemini_api_key)

    # ---------------- menu bar ----------------
    def _build_menubar(self):
        bar = tk.Menu(self, tearoff=False)

        m_file = tk.Menu(bar, tearoff=False)
        m_file.add_command(label="Settings...", accelerator="Ctrl+,", command=self.open_settings)
        m_file.add_command(label="Open settings folder", command=self._open_config_folder)
        m_file.add_separator()
        m_file.add_command(label="Quit", accelerator="Ctrl+Q", command=self.on_closing)
        bar.add_cascade(label="File", menu=m_file)

        m_an = tk.Menu(bar, tearoff=False)
        for name, _cat, _icon, mod_path, tab, _desc in TOOLS:
            m_an.add_command(label=name, command=lambda m=mod_path, n=name: self.open_tool(m, n))
        m_an.add_separator()
        m_an.add_command(label="Auto-fit workspace: PL", command=lambda: self.open_spectra("PL"))
        m_an.add_command(label="Auto-fit workspace: XRD", command=lambda: self.open_spectra("XRD"))
        m_an.add_command(label="Auto-fit workspace: XPS", command=lambda: self.open_spectra("XPS"))
        bar.add_cascade(label="Analysis", menu=m_an)

        m_tools = tk.Menu(bar, tearoff=False)
        self.update_menu = tk.Menu(m_tools, tearoff=False)
        m_tools.add_cascade(label="Updates", menu=self.update_menu)
        m_tools.add_command(label="Run self-test", command=self._run_selftest)
        m_tools.add_command(label="Command-line interface (help)", command=self._show_cli_help)
        bar.add_cascade(label="Tools", menu=m_tools)

        m_help = tk.Menu(bar, tearoff=False)
        m_help.add_command(label="Methods and algorithms", command=lambda: self._open_url(f"{REPO_URL}/blob/main/docs/METHODS.md"))
        m_help.add_command(label="Installation guide", command=lambda: self._open_url(f"{REPO_URL}/blob/main/docs/INSTALL.md"))
        m_help.add_command(label="Report an issue", command=lambda: self._open_url(f"{REPO_URL}/issues"))
        m_help.add_separator()
        m_help.add_command(label="About Physiscore", command=self._about)
        bar.add_cascade(label="Help", menu=m_help)
        self.configure(menu=bar)
        self.bind("<Control-q>", lambda e: self.on_closing())
        self.bind("<Control-comma>", lambda e: self.open_settings())

    def _open_url(self, url):
        import webbrowser
        webbrowser.open(url)

    def _open_config_folder(self):
        folder = os.path.dirname(app_config.config_path())
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            messagebox.showinfo("Settings folder", f"{folder}\n\n({e})")

    def _about(self):
        messagebox.showinfo(
            "About Physiscore",
            f"Physiscore {APP_VERSION}\n"
            "Physics-constrained analysis of thin-film photovoltaic device and material measurements:\n"
            "J-V (light and dark), EQE, absorbance, PL, XRD, SEM, Raman, FTIR, XPS.\n\n"
            "Hybrid Materials and Optoelectronics Laboratory (H-MOL), Incheon National University.\n"
            "MIT License.  Concept DOI 10.5281/zenodo.22267588\n"
            f"{REPO_URL}")

    def _show_cli_help(self):
        messagebox.showinfo(
            "Command line",
            "Physiscore --tool \"J-V Curve\"      open one analysis window\n"
            "Physiscore --spectra XRD|PL|XPS      auto-fit workspace\n"
            "Physiscore --selftest [--out f.json] headless check\n"
            "Physiscore --update                  check for / install updates\n"
            "Physiscore --version\n\n"
            "Batch analysis without the GUI: python -m physiscore_cli --help")

    def _run_selftest(self):
        self.set_status("Running self-test...")

        def work():
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = selftest(None)
            self.after(0, lambda: (self.set_status("Self-test passed" if code == 0 else "Self-test FAILED"),
                                   messagebox.showinfo("Self-test", buf.getvalue()[:4000])))
        threading.Thread(target=work, daemon=True).start()

    # ---------------- updates ----------------
    def _setup_updates(self):
        self.update_menu.add_command(label="Installation and updates (web)",
                                     command=lambda: self._open_url(f"{REPO_URL}/blob/main/docs/INSTALL.md"))
        self.update_menu.add_separator()
        try:
            import selfupdate
            self.updater = selfupdate.Updater(make_update_app(selfupdate))
            selfupdate.attach_tk(self, self.updater, self.update_menu, lang="en",
                                 status=lambda text: text and self.set_status(text))
        except Exception as e:  # updates must never stop the analysis suite
            print(f"[Physiscore] update support unavailable: {e}")

    # ---------------- toolbar ----------------
    def _build_toolbar(self):
        bar = ctk.CTkFrame(self, height=44, fg_color=_pal.BG_PANEL, corner_radius=0)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        ctk.CTkLabel(bar, text="Physiscore", font=_pal.font(13, "bold"), text_color=_pal.TXT
                     ).pack(side="left", padx=(14, 4))
        ctk.CTkLabel(bar, text="analysis suite", font=_pal.font(11), text_color=_pal.TXT_SUB
                     ).pack(side="left", padx=(0, 16))

        self.seg = ctk.CTkSegmentedButton(
            bar, values=CATEGORIES, height=28, fg_color=_pal.BG_SUB,
            selected_color=_pal.ACCENT, selected_hover_color=_pal.ACCENT_HOV,
            unselected_color=_pal.BG_SUB, unselected_hover_color=_pal.BG_HOVER,
            text_color=_pal.TXT, font=_pal.font(11), corner_radius=_pal.R_PILL, command=self._on_category)
        self.seg.set("All")
        self.seg.pack(side="left", padx=4, pady=8)

        ctk.CTkButton(bar, text="Settings", width=84, height=28, fg_color=_pal.BG_SUB, hover_color=_pal.BG_HOVER,
                      text_color=_pal.TXT, border_width=1, border_color=_pal.BORDER_HI, font=_pal.font(11),
                      corner_radius=_pal.R_PILL, command=self.open_settings).pack(side="right", padx=12, pady=8)

        self.search_var = ctk.StringVar()
        ent = ctk.CTkEntry(bar, width=200, height=28, fg_color=_pal.BG_CARD, border_color=_pal.BORDER,
                           text_color=_pal.TXT, font=_pal.font(11), corner_radius=_pal.R_INPUT,
                           placeholder_text="Filter tools", textvariable=self.search_var)
        ent.pack(side="right", padx=(0, 4), pady=8)
        ent.bind("<KeyRelease>", lambda e: self.refresh_cards())

    # ---------------- body ----------------
    def _build_body(self):
        self.body = ctk.CTkScrollableFrame(self, fg_color=_pal.BG_WINDOW,
                                           scrollbar_button_color=_pal.BORDER_HI,
                                           scrollbar_button_hover_color=_pal.TXT_DIM)
        self.body.pack(fill="both", expand=True, padx=10, pady=(8, 4))

    # ---------------- status bar ----------------
    def _build_statusbar(self):
        sb = ctk.CTkFrame(self, height=24, fg_color=_pal.BG_PANEL, corner_radius=0)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)
        self.lbl_ready = ctk.CTkLabel(sb, text="Ready", font=_pal.font(10), text_color=_pal.TXT_SUB, anchor="w")
        self.lbl_ready.pack(side="left", padx=10)
        self.lbl_env = ctk.CTkLabel(sb, text="", font=_pal.font(10), text_color=_pal.TXT_DIM, anchor="e")
        self.lbl_env.pack(side="right", padx=10)
        self.refresh_statusbar()

    def refresh_statusbar(self):
        area = app_config.cell_area_cm2()
        o = "Origin: configured" if self.origin_path else "Origin: not set"
        k = "Interpretation: on" if self.gemini_api_key else "Interpretation: off"
        self.lbl_env.configure(text=f"Cell area {area:g} cm²   |   {o}   |   {k}   |   v{APP_VERSION}")

    def set_status(self, text):
        try:
            self.lbl_ready.configure(text=text)
        except Exception:
            pass

    # ---------------- module loading ----------------
    def _preload_modules(self):
        for _, _, _, mod_path, _, _ in TOOLS:
            self.modules[mod_path] = "loading"
        for _, _, _, mod_path, _, _ in TOOLS:
            if mod_path.startswith("exe:"):
                exe = find_external_exe(mod_path[4:]) if sys.platform == "win32" else None
                fallback = BUILTIN_FALLBACK.get(mod_path)
                if exe or not fallback:
                    self.modules[mod_path] = exe
                else:
                    try:
                        self.modules[mod_path] = importlib.import_module(fallback)
                    except Exception as e:
                        print(f"[Physiscore] {fallback} import failed: {e}")
                        self.modules[mod_path] = None
            elif mod_path.startswith("spectra:"):
                try:
                    self.modules[mod_path] = importlib.import_module("spectra.app")
                except Exception as e:
                    print(f"[Physiscore] spectra import failed: {e}")
                    self.modules[mod_path] = None
            else:
                try:
                    self.modules[mod_path] = importlib.import_module(mod_path)
                except Exception as e:
                    print(f"[Physiscore] {mod_path} import failed: {e}")
                    self.modules[mod_path] = None
        self._preload_done = True

    def _poll_modules(self):
        for mod_path in list(self.cards):
            self._update_card_state(mod_path)
        if not self._preload_done:
            self.after(150, self._poll_modules)

    def _update_card_state(self, mod_path):
        card = self.cards.get(mod_path)
        if not card:
            return
        mod = self.modules.get(mod_path, "loading")
        lbl, btn = card["status"], card["btn"]
        is_exe = mod_path.startswith("exe:") and isinstance(mod, str)
        if isinstance(mod, str) and mod == "loading":
            lbl.configure(text="Loading...", text_color=_pal.TXT_DIM)
            btn.configure(state="disabled", fg_color=_pal.BG_SUB, text_color=_pal.TXT_DIM)
        elif mod is None:
            lbl.configure(text="Unavailable (see console)", text_color=_pal.RED)
            btn.configure(state="disabled", fg_color=_pal.BG_SUB, text_color=_pal.TXT_DIM)
        else:
            lbl.configure(text="External program" if is_exe else "Ready", text_color=_pal.TXT_SUB)
            btn.configure(state="normal", fg_color=_pal.ACCENT, text_color="white")

    # ---------------- cards ----------------
    def refresh_cards(self):
        for w in self.body.winfo_children():
            w.destroy()
        self.cards.clear()
        q = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        cat = self.current_category
        visible = [t for t in TOOLS if (cat == "All" or t[1] == cat)
                   and (not q or q in t[0].lower() or q in t[5].lower())]
        grid = ctk.CTkFrame(self.body, fg_color="transparent")
        grid.pack(fill="both", expand=True)
        cols = 2
        for i in range(cols):
            grid.grid_columnconfigure(i, weight=1, uniform="col")
        for idx, tool in enumerate(visible):
            r, c = divmod(idx, cols)
            self._build_card(grid, r, c, *tool)
        self.set_status(f"{len(visible)} analysis tools")

    def _build_card(self, parent, r, c, name, category, icon, mod_path, spectra_tab, description):
        card = ctk.CTkFrame(parent, fg_color=_pal.BG_CARD, corner_radius=_pal.R_CARD,
                            border_width=1, border_color=_pal.BORDER)
        card.grid(row=r, column=c, padx=6, pady=6, sticky="nsew")
        card.grid_columnconfigure(1, weight=1)

        img = None
        p = os.path.join(self.logo_dir, icon)
        if os.path.exists(p):
            try:
                pil = Image.open(p)
                img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(36, 36))
            except Exception:
                img = None
        icon_lbl = ctk.CTkLabel(card, text="" if img else name[:2], image=img, width=40,
                                font=_pal.font(12, "bold"), text_color=_pal.TXT_SUB)
        icon_lbl.grid(row=0, column=0, rowspan=2, padx=(12, 8), pady=(10, 6), sticky="n")

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=(10, 0))
        ctk.CTkLabel(head, text=name, font=_pal.font(12, "bold"), text_color=_pal.TXT).pack(side="left")
        ctk.CTkLabel(head, text=category, font=_pal.font(10), text_color=_pal.TXT_DIM).pack(side="left", padx=8)

        ctk.CTkLabel(card, text=description, font=_pal.font(10), text_color=_pal.TXT_SUB,
                     justify="left", anchor="w", wraplength=440).grid(row=1, column=1, sticky="ew", padx=(0, 12))

        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(6, 10))
        btn = ctk.CTkButton(btns, text="Open", width=90, height=26, fg_color=_pal.BG_SUB, text_color=_pal.TXT_DIM,
                            state="disabled", hover_color=_pal.ACCENT_HOV, font=_pal.font(11, "bold"),
                            corner_radius=_pal.R_PILL, command=lambda m=mod_path, n=name: self.open_tool(m, n))
        btn.pack(side="left")
        if spectra_tab:
            ctk.CTkButton(btns, text="Auto-fit workspace", width=130, height=26, fg_color=_pal.BG_SUB,
                          hover_color=_pal.BG_HOVER, text_color=_pal.TXT, border_width=1, border_color=_pal.BORDER_HI,
                          font=_pal.font(11), corner_radius=_pal.R_PILL,
                          command=lambda t=spectra_tab: self.open_spectra(t)).pack(side="left", padx=(8, 0))
        status = ctk.CTkLabel(btns, text="Loading...", font=_pal.font(10), text_color=_pal.TXT_DIM, anchor="e")
        status.pack(side="right")
        self.cards[mod_path] = {"status": status, "btn": btn}
        self._update_card_state(mod_path)

    # ---------------- launching ----------------
    def open_tool(self, mod_path, name):
        mod = self.modules.get(mod_path)
        if mod_path.startswith("spectra:"):
            self.open_spectra(mod_path.split(":", 1)[1])
            return
        if mod_path.startswith("exe:") and not hasattr(mod, "AnalysisWindow"):
            exe = mod if isinstance(mod, str) else find_external_exe(mod_path[4:])
            if not exe or not os.path.isfile(exe):
                messagebox.showerror("Error", f"The external program for {name} was not found.")
                return
            try:
                self._sync_config_to(os.path.dirname(exe))
                subprocess.Popen([exe], cwd=os.path.dirname(exe))
                self.set_status(f"Started {name} (external program)")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to start {name}:\n{e}")
            return
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
            messagebox.showerror("Error", f"Failed to open {name}:\n{e}")
        finally:
            try:
                self.deiconify()
            except Exception:
                pass

    def _sync_config_to(self, folder):
        """Share Origin path and API key with the external program's config."""
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
            data["cell_area_cm2"] = app_config.cell_area_cm2()
            with open(target, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"config sync skip: {e}")

    def open_spectra(self, tab):
        """Auto-fit workspace in a separate process (its own Tk main loop)."""
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--spectra", tab]
            else:
                cmd = [sys.executable, "-m", "spectra.app", tab]
            subprocess.Popen(cmd, cwd=BASE_DIR)
            self.set_status(f"Opened the {tab} auto-fit workspace")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open the workspace:\n{e}")

    def open_settings(self):
        SettingsDialog(self)

    def _on_category(self, value):
        self.current_category = value
        self.refresh_cards()

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


def make_update_app(selfupdate):
    return selfupdate.App(repo="jongsu-king/physiscore", name="Physiscore",
                          version=APP_VERSION, env_prefix="PHYSISCORE")


def selftest(out=None) -> int:
    """Headless check used by the installer builds: import every analysis core and
    GUI module and compute reference quantities of synthetic data."""
    import numpy as np
    result = {"version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)), "imports": {}}
    for mod in ("scripts.common.spectral", "scripts.common.vibrational", "scripts.JV.jv_core",
                "scripts.Dark_JV.dark_jv_core", "scripts.EQE.eqe_core", "scripts.Abs.abs_core",
                "scripts.PL.pl_core", "scripts.XRD.xrd_core", "scripts.SEM.sem_core", "spectra.core.xps",
                "scripts.common.device_summary", "scripts.common.batch", "scripts.common.iv_io",
                "scripts.common.provenance", "scripts.Device.run_device", "scripts.common.compare_window",
                "scripts.JV.run_jv", "scripts.Dark_JV.run_jv_dark", "scripts.EQE.run_eqe",
                "scripts.SEM.run_sem", "scripts.Abs.run_abs", "scripts.Raman.run_raman",
                "scripts.FTIR.run_ftir", "scripts.XRD.run_xrd", "scripts.PL.run_pl", "spectra.app"):
        try:
            importlib.import_module(mod)
            result["imports"][mod] = "ok"
        except Exception as e:  # noqa: BLE001
            result["imports"][mod] = f"failed: {e!r}"
    checks = {}
    try:
        from scripts.JV.jv_core import compute_jv_parameters, fit_single_diode, single_diode_current
        v = np.linspace(-0.2, 1.1, 261)
        j = single_diode_current(v, 22.0, 1e-9, 1.5, 2.0, 2000.0)
        p = compute_jv_parameters(v, j, pin_mw_cm2=100.0)
        fit = fit_single_diode(v, j)
        checks["jv"] = {k: float(p[k]) for k in ("Voc", "Jsc", "FF", "PCE")}
        checks["jv"]["n_fit"] = float(fit["n"])
        checks["jv_ok"] = bool(p["PCE"] > 0 and abs(fit["n"] - 1.5) < 0.1)
    except Exception as e:  # noqa: BLE001
        checks["jv"] = f"failed: {e!r}"
        checks["jv_ok"] = False
    try:
        from scripts.EQE.eqe_core import shockley_queisser
        sq = shockley_queisser(1.34)
        checks["sq_1p34eV"] = {k: float(sq[k]) for k in ("Jsc_SQ", "Voc_SQ", "PCE_SQ")}
        checks["sq_ok"] = bool(32.5 < sq["PCE_SQ"] < 34.5)
    except Exception as e:  # noqa: BLE001
        checks["sq_1p34eV"] = f"failed: {e!r}"
        checks["sq_ok"] = False
    try:
        from scripts.common.vibrational import load_library
        checks["band_library_entries"] = len(load_library())
        checks["library_ok"] = checks["band_library_entries"] > 40
    except Exception as e:  # noqa: BLE001
        checks["band_library_entries"] = f"failed: {e!r}"
        checks["library_ok"] = False
    result["checks"] = checks
    ok = (all(v == "ok" for v in result["imports"].values())
          and checks.get("jv_ok") and checks.get("sq_ok") and checks.get("library_ok"))
    result["ok"] = bool(ok)
    result["executable"] = sys.executable
    result["config"] = app_config.config_path()
    result["theme"] = _pal.THEME
    text = json.dumps(result, indent=2)
    if not ok:
        print(text, file=sys.stderr)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return 0 if ok else 1


def _open_single_tool(name: str) -> int:
    """`--tool NAME`: open one analysis window without the launcher grid."""
    match = next((t for t in TOOLS if t[0].lower() == name.lower()), None)
    if match is None:
        print("unknown tool; choose one of: " + ", ".join(t[0] for t in TOOLS), file=sys.stderr)
        return 2
    mod_path = match[3]
    if mod_path.startswith("spectra:"):
        from spectra.app import App as SpectraApp
        SpectraApp(start_tab=mod_path.split(":", 1)[1]).mainloop()
        return 0
    mod_path = BUILTIN_FALLBACK.get(mod_path, mod_path)
    mod = importlib.import_module(mod_path)
    root = ctk.CTk()
    root.withdraw()
    data = app_config.load(refresh=True)
    win = mod.AnalysisWindow(root, data.get("origin_path", ""), data.get("gemini_api_key", ""))
    win.protocol("WM_DELETE_WINDOW", lambda: (root.quit(), root.destroy()))
    root.mainloop()
    return 0


if __name__ == "__main__":
    if "--version" in sys.argv:
        print(f"Physiscore {APP_VERSION}")
        sys.exit(0)
    if "--selftest" in sys.argv:
        _out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
        sys.exit(selftest(_out))
    if "--update" in sys.argv:
        import selfupdate
        sys.exit(selfupdate.cli(selfupdate.Updater(make_update_app(selfupdate))))
    if "--spectra" in sys.argv:
        _i = sys.argv.index("--spectra")
        _tab = sys.argv[_i + 1] if len(sys.argv) > _i + 1 else "PL"
        try:
            from spectra.app import App as SpectraApp
            SpectraApp(start_tab=_tab).mainloop()
        except Exception as e:
            print(f"spectra run failed: {e}")
        sys.exit(0)
    if "--tool" in sys.argv:
        _i = sys.argv.index("--tool")
        sys.exit(_open_single_tool(sys.argv[_i + 1] if len(sys.argv) > _i + 1 else ""))
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
    except Exception:
        pass
    app = LauncherApp()
    app.mainloop()
