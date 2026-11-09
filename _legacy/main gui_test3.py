import customtkinter as ctk
from tkinter import filedialog, messagebox
import os
import sys
import json
import subprocess
from PIL import Image
import importlib

# -----------------------------------------------------------
# scripts folder path
# -----------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")

# register sys.path (package root only needs BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

if SCRIPTS_DIR not in sys.path:
    sys.path.append(SCRIPTS_DIR)

# ========================================================
# Safe Import
# ========================================================
run_jv = None
run_jv_dark = None
run_eqe = None
run_sem = None
run_abs = None
run_raman = None
run_ftir = None
run_xrd = None
run_pl = None
spectra_app = None

try:
    from scripts.JV import run_jv
except Exception as e:
    print(f"Warning: 'scripts/JV/run_jv.py' failed to import: {e}")
    run_jv = None

try:
    from scripts.Dark_JV import run_jv_dark
except Exception as e:
    print(f"Warning: 'scripts/Dark_JV/run_jv_dark.py' failed to import: {e}")
    run_jv_dark = None

try:
    from scripts.EQE import run_eqe
except Exception as e:
    print(f"Warning: 'scripts/EQE/run_eqe.py' failed to import: {e}")
    run_eqe = None

try:
    from scripts.SEM import run_sem
except Exception as e:
    print(f"Warning: 'scripts/SEM/run_sem.py' failed to import: {e}")
    run_sem = None

try:
    from scripts.Abs import run_abs
except Exception as e:
    print(f"Warning: 'scripts/Abs/run_abs.py' failed to import: {e}")
    run_abs = None

try:
    from scripts.Raman import run_raman
except Exception as e:
    print(f"Warning: 'scripts/Raman/run_raman.py' failed to import: {e}")
    run_raman = None

try:
    from scripts.FTIR import run_ftir
except Exception as e:
    print(f"Warning: 'scripts/FTIR/run_ftir.py' failed to import: {e}")
    run_ftir = None

try:
    from scripts.XRD import run_xrd
except Exception as e:
    print(f"Warning: 'scripts/XRD/run_xrd.py' failed to import: {e}")
    run_xrd = None


try:
    from scripts.PL import run_pl
except Exception as e:
    print(f"Warning: 'scripts/PL/run_pl.py' failed to import: {e}")
    run_pl = None

# Load spectra app module (package import)
try:
    spectra_app = importlib.import_module("spectra.app")
except ImportError as e:
    print(f"Warning: 'spectra/app.py' not found or failed to load: {e}")
    spectra_app = None

# ========================================================
# Theme / Design Tokens
# ========================================================
ctk.set_appearance_mode("Dark")  # Only Dark Mode
ctk.set_default_color_theme("blue")

# Modern Color Palette with Enhanced Aesthetics
BG_PRIMARY = "#0a0e27"      # deep background
BG_SECONDARY = "#0f1629"    # card background
BG_TERTIARY = "#151f3a"     # input background
BG_HOVER = "#1a1f3a"        # hover background
BORDER = "#2a3f5f"          # border color
BORDER_LIGHT = "#3a4f7f"    # light border
BORDER_ACCENT = "#6366f1"   # accent border

TEXT_PRIMARY = "#e8eef7"    # primary text
TEXT_SECONDARY = "#a0aab8"  # secondary text
TEXT_TERTIARY = "#7a8094"   # dimmer text

ACCENT = "#6366f1"          # indigo (primary accent)
ACCENT_LIGHT = "#818cf8"    # light indigo
ACCENT_HOVER = "#4f46e5"    # dark indigo
ACCENT_GLOW = "#a5b4fc"     # glow indigo

SUCCESS = "#10b981"         # green (success/ready)
SUCCESS_LIGHT = "#34d399"   # light green
WARNING = "#f59e0b"         # amber (warning)
WARNING_LIGHT = "#fbbf24"   # light amber
DANGER = "#ef4444"          # red (danger/error)
DANGER_LIGHT = "#f87171"    # light red

# Component Constants
CORNER_RADIUS_LG = 16        # large corner
CORNER_RADIUS_MD = 12        # medium corner
CORNER_RADIUS_SM = 8         # small corner

FONT_TITLE = ("Segoe UI", 32, "bold")
FONT_HEADER_BIG = ("Segoe UI", 38, "bold")
FONT_H1 = ("Segoe UI", 16, "bold")
FONT_H2 = ("Segoe UI", 15, "bold")
FONT_BODY = ("Segoe UI", 12)
FONT_SMALL = ("Segoe UI", 10)

def safe_load_ctk_image(path: str, size=(64, 64)):
    if not os.path.exists(path):
        return None
    try:
        img = Image.open(path)
        return ctk.CTkImage(light_image=img, dark_image=img, size=size)
    except Exception:
        return None

# ========================================================
# Fancy Widgets
# ========================================================
class CustomEntry(ctk.CTkEntry):
    """Entry with enhanced focus state and glow effect."""
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.default_color = BORDER
    
    def _on_focus_in(self, event=None):
        self.configure(border_color=ACCENT_GLOW, border_width=2)
    
    def _on_focus_out(self, event=None):
        self.configure(border_color=self.default_color, border_width=1)

class Badge(ctk.CTkLabel):
    """Enhanced badge with dynamic styling."""
    def __init__(self, master, text, fg, **kwargs):
        # Determine text color based on background
        if fg == DANGER:
            text_color = "white"
        elif fg == SUCCESS:
            text_color = "white"
        else:  # ACCENT
            text_color = "white"
        
        super().__init__(
            master,
            text=text,
            fg_color=fg,
            text_color=text_color,
            corner_radius=CORNER_RADIUS_SM,
            padx=12,
            pady=5,
            font=("Segoe UI", 10, "bold"),
            **kwargs
        )

class Card(ctk.CTkFrame):
    """Enhanced Card with glow effects on hover."""
    def __init__(self, master, hover=False, **kwargs):
        super().__init__(
            master,
            fg_color=BG_SECONDARY,
            corner_radius=CORNER_RADIUS_LG,
            border_width=2,
            border_color=BORDER,
            **kwargs
        )
        self.hover = hover
        self.original_border = BORDER
        if hover:
            self.bind("<Enter>", self._on_enter)
            self.bind("<Leave>", self._on_leave)
    
    def _on_enter(self, event=None):
        if self.hover:
            self.configure(border_color=ACCENT_GLOW, fg_color=BG_HOVER)
    
    def _on_leave(self, event=None):
        if self.hover:
            self.configure(border_color=self.original_border, fg_color=BG_SECONDARY)

class AnalysisParamFrame(ctk.CTkFrame):
    """Enhanced parameter input frame with visual depth."""
    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            fg_color=BG_SECONDARY,
            corner_radius=CORNER_RADIUS_LG,
            border_width=2,
            border_color=BORDER_LIGHT,
            **kwargs
        )

        self.params = {
            "Filter Width": ("21", "Noise-removal window. Larger = smoother curve (odd number recommended)."),
            "Poly Order": ("3", "Curve complexity. How much fine peak structure is preserved (must be smaller than Width)."),
            "Baseline Smooth (λ)": ("1e06", "Baseline stiffness. Higher = baseline closer to a straight line."),
            "Peak Threshold (p)": ("0.01", "Peak-protection value. Smaller = real peaks less likely mistaken as baseline."),
        }

        self.entries = {}
        for i, (label_text, (default, desc)) in enumerate(self.params.items()):
            lbl = ctk.CTkLabel(self, text=label_text)
            lbl.grid(row=i, column=0, padx=10, pady=5, sticky="w")

            entry = ctk.CTkEntry(self, width=100)
            entry.insert(0, default)
            entry.grid(row=i, column=1, padx=10, pady=5)
            self.entries[label_text] = entry

            info_btn = ctk.CTkButton(
                self,
                text="?",
                width=24,
                fg_color="gray",
                hover_color="#555",
                command=lambda d=desc: messagebox.showinfo("Description", d),
            )
            info_btn.grid(row=i, column=2, padx=5, pady=5)

    def get_params(self):
        """Validate and return params dict or None on error."""
        try:
            w = int(self.entries["Filter Width"].get())
            p = int(self.entries["Poly Order"].get())
            if p >= w:
                raise ValueError("Poly Order must be smaller than Filter Width.")
            return {
                "sg_window": w,
                "sg_poly": p,
                "als_lam": float(self.entries["Baseline Smooth (λ)"].get()),
                "als_p": float(self.entries["Peak Threshold (p)"].get()),
            }
        except Exception as e:
            messagebox.showerror("Error", f"Check your input: {e}")
            return None

class PhysisferaApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Physiscore")

        self.W, self.H = 1200, 860
        self.geometry(f"{self.W}x{self.H}")
        self.after(20, self.center_window)

        # Config
        self.origin_path = ""
        self.gemini_api_key = ""
        self.config_file = os.path.join(BASE_DIR, "physisfera_config.json")

        # Root container
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True)

        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Show splash screen and load in background
        self.show_splash_screen()
        self.after(100, self.initialize_app)

    # ----------------
    # Core helpers
    # ----------------
    def center_window(self):
        ws = self.winfo_screenwidth()
        hs = self.winfo_screenheight()
        x = (ws - self.W) // 2
        y = (hs - self.H) // 2
        self.geometry(f"{self.W}x{self.H}+{x}+{y}")

    def on_closing(self):
        # customtkinter's scheduled after-callbacks (check_dpi_scaling/update, etc.)
        # run after destroy and cause bgerror; cancel them all before closing
        try:
            for after_id in self.tk.call("after", "info"):
                try:
                    self.after_cancel(after_id)
                except Exception:
                    pass
        except Exception:
            pass
        self.quit()
        self.destroy()

    def clear_screen(self):
        for w in self.container.winfo_children():
            w.destroy()

    def show_splash_screen(self):
        """Display stylish loading screen with progress bar."""
        self.clear_screen()

        splash = ctk.CTkFrame(self.container, fg_color=BG_PRIMARY)
        splash.pack(fill="both", expand=True)

        # Main content frame with decorative border
        content = ctk.CTkFrame(splash, fg_color=BG_PRIMARY)
        content.pack(expand=True, padx=40, pady=40)

        # Decorative top line
        top_line = ctk.CTkFrame(content, fg_color=ACCENT_GLOW, height=2)
        top_line.pack(fill="x", pady=(0, 32))

        # Logo/Title with color
        ctk.CTkLabel(
            content,
            text="Physiscore",
            font=FONT_HEADER_BIG,
            text_color=ACCENT_LIGHT
        ).pack(pady=(0, 8))

        ctk.CTkLabel(
            content,
            text="AI-Assisted Analysis Platform",
            font=("Segoe UI", 14),
            text_color=TEXT_TERTIARY
        ).pack(pady=(0, 48))

        # Status text with better contrast
        self.splash_status = ctk.CTkLabel(
            content,
            text="Initializing...",
            font=("Segoe UI", 12),
            text_color=TEXT_SECONDARY
        )
        self.splash_status.pack(pady=(0, 20))

        # Progress bar with glow color
        self.splash_progress = ctk.CTkProgressBar(
            content,
            width=300,
            height=10,
            fg_color=BG_TERTIARY,
            progress_color=ACCENT,
            corner_radius=CORNER_RADIUS_SM
        )
        self.splash_progress.set(0)
        self.splash_progress.pack(pady=(0, 28))

        # Decorative bottom line
        bottom_line = ctk.CTkFrame(content, fg_color=ACCENT_GLOW, height=2)
        bottom_line.pack(fill="x", pady=(0, 16))

        # Version with accent color
        ctk.CTkLabel(
            content,
            text="v1.0.0",
            font=("Segoe UI", 10),
            text_color=ACCENT
        ).pack(pady=(0, 0))
        self.update()

    def update_splash(self, status: str, progress: float):
        """Update splash screen status and progress."""
        self.splash_status.configure(text=status)
        self.splash_progress.set(progress)
        self.update()

    def initialize_app(self):
        """Initialize app in background and transition to main screen."""
        try:
            # Step 1: Load config
            self.update_splash("Loading configuration...", 0.2)
            self.load_config()

            # Step 2: Setup resources
            self.update_splash("Setting up resources...", 0.4)
            if getattr(sys, 'frozen', False):
                # PyInstaller: datas are unpacked under _MEIPASS (the _internal folder in onedir)
                base_path = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
                self.logo_dir = os.path.join(base_path, "logo")
                if not os.path.isdir(self.logo_dir):
                    self.logo_dir = os.path.join(os.path.dirname(sys.executable), "logo")
            else:
                self.logo_dir = os.path.join(BASE_DIR, "logo")

            # Step 3: Prepare UI
            self.update_splash("Preparing interface...", 0.7)
            self.after(200)  # Simulated load time for visual effect

            # Step 4: Complete
            self.update_splash("Ready!", 1.0)
            self.after(400, self.transition_to_main)

        except Exception as e:
            print(f"Initialization error: {e}")
            self.transition_to_main()

    def transition_to_main(self):
        """Transition from splash screen to main app."""
        self.show_setup_page()

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.origin_path = data.get("origin_path", "")
                    self.gemini_api_key = data.get("gemini_api_key", "")

                    # if a key exists, also set it in env so spectra/AI can read it
                    if self.gemini_api_key:
                        os.environ["GEMINI_API_KEY"] = self.gemini_api_key
                        os.environ.setdefault("GOOGLE_API_KEY", self.gemini_api_key)
            except Exception as e:
                print(f"Config load error: {e}")

    def save_config(self):
        # merge-preserve: keep keys managed elsewhere (e.g. cell_area_cm2
        # used by the JV/Dark-JV cores) instead of overwriting the file
        data = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data["origin_path"] = self.origin_path
        data["gemini_api_key"] = self.gemini_api_key
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Config save error: {e}")

    def toast(self, msg: str, ok=True):
        if hasattr(self, "_toast") and self._toast.winfo_exists():
            self._toast.destroy()
        
        toast_color = SUCCESS if ok else DANGER
        self._toast = ctk.CTkLabel(
            self.container,
            text=f"{'✓' if ok else '✗'} {msg}",
            corner_radius=12,
            padx=20,
            pady=12,
            font=("Segoe UI", 12, "bold"),
            fg_color=toast_color,
            text_color="white",
            border_width=0
        )
        self._toast.place(relx=0.5, rely=0.92, anchor="center")
        self.after(2000, lambda: self._toast.destroy() if self._toast.winfo_exists() else None)

    # ========================================================
    # Page 1: Setup
    # ========================================================
    def show_setup_page(self):
        self.clear_screen()

        bg = ctk.CTkFrame(self.container, fg_color=BG_PRIMARY)
        bg.pack(fill="both", expand=True)

        # Enhanced Header with decorative elements
        header = ctk.CTkFrame(bg, fg_color=BG_PRIMARY)
        header.pack(fill="x", padx=40, pady=(40, 30))

        # Decorative accent line
        accent_line = ctk.CTkFrame(header, fg_color=ACCENT_GLOW, height=3)
        accent_line.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            header,
            text="Physiscore",
            font=FONT_HEADER_BIG,
            text_color=ACCENT_LIGHT
        ).pack(anchor="w")

        ctk.CTkLabel(
            header,
            text="AI-Assisted Analysis Platform",
            font=("Segoe UI", 14),
            text_color=TEXT_TERTIARY
        ).pack(anchor="w", pady=(8, 0))

        # Main Content with compact padding
        content = ctk.CTkFrame(bg, fg_color=BG_PRIMARY)
        content.pack(fill="both", expand=True, padx=28, pady=(0, 28))

        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)

        # Left Panel with enhanced styling
        left = Card(content)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        left.grid_rowconfigure(2, weight=1)
        left.grid_columnconfigure(0, weight=1)

        # Top border line inside left card to match right card edge
        ctk.CTkFrame(left, fg_color=BORDER_LIGHT, height=2).grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 0))

        ctk.CTkLabel(
            left,
            text="Setup your analysis environment and API keys.",
            font=("Segoe UI", 12),
            text_color=TEXT_TERTIARY,
            wraplength=260,
            justify="center"
        ).grid(row=1, column=0, padx=18, pady=(0, 6), sticky="ew")

        # Statistics Cards (Scrollable - no scrollbar)
        stats_scroll = ctk.CTkScrollableFrame(
            left,
            fg_color=BG_PRIMARY,
            border_width=0,
            corner_radius=0,
            scrollbar_button_color=BG_PRIMARY,
            scrollbar_button_hover_color=BG_PRIMARY,
        )
        stats_scroll.grid(row=2, column=0, padx=18, pady=(2, 0), sticky="nsew")
        stats_scroll.grid_columnconfigure(0, weight=1)

        # Helper function for stat cards
        def create_stat_card(parent, emoji, title, subtitle, color):
            stat = ctk.CTkFrame(parent, fg_color=BG_TERTIARY, corner_radius=CORNER_RADIUS_MD, border_width=2, border_color=BORDER_LIGHT)
            stat.pack(fill="x", pady=(0, 16))
            stat.bind("<Enter>", lambda e: stat.configure(border_color=color, fg_color=BG_HOVER))
            stat.bind("<Leave>", lambda e: stat.configure(border_color=BORDER_LIGHT, fg_color=BG_TERTIARY))
            
            stat_inner = ctk.CTkFrame(stat, fg_color=BG_TERTIARY)
            stat_inner.pack(fill="x", padx=16, pady=14)
            
            ctk.CTkLabel(stat_inner, text=emoji, font=("Segoe UI", 28)).pack(anchor="w", pady=(0, 6))
            ctk.CTkLabel(stat_inner, text=title, font=("Segoe UI", 14, "bold"), text_color=color).pack(anchor="w", pady=(0, 2))
            ctk.CTkLabel(stat_inner, text=subtitle, font=("Segoe UI", 11), text_color=TEXT_SECONDARY).pack(anchor="w")

        # Create stat cards with enhanced styling
        create_stat_card(stats_scroll, "⚡", "10x Faster", "Automated Analysis", ACCENT)
        create_stat_card(stats_scroll, "🎯", "99% Accuracy", "AI-Powered Analysis", SUCCESS_LIGHT)
        create_stat_card(stats_scroll, "⏱️", "90% Time Saved", "vs Manual Work", WARNING_LIGHT)
        # Checklist at bottom with enhanced styling
        info_text = (
            "✓ Select OriginLab executable\n"
            "✓ Add Gemini API key (optional)\n"
            "✓ Access all analysis modules\n"
            "✓ Manage your configurations"
        )
        checklist_frame = ctk.CTkFrame(left, fg_color=BG_SECONDARY, corner_radius=CORNER_RADIUS_MD, border_width=2, border_color=BORDER_LIGHT)
        checklist_frame.grid(row=3, column=0, padx=18, pady=(6, 12), sticky="ew")
        
        ctk.CTkLabel(
            checklist_frame,
            text=info_text,
            font=("Segoe UI", 11),
            text_color=SUCCESS_LIGHT,
            justify="left"
        ).pack(anchor="w", padx=16, pady=12)

        # Right Panel with enhanced styling
        right = Card(content)
        right.grid(row=0, column=1, sticky="nsew", padx=(14, 0))
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            right,
            text="Configuration",
            font=FONT_H1,
            text_color=ACCENT_LIGHT,
            height=36,
            anchor="w"
        ).grid(row=0, column=0, padx=18, pady=(12, 10), sticky="w")

        # Path selection
        path_label = ctk.CTkLabel(
            right,
            text="OriginLab Executable",
            font=("Segoe UI", 11, "bold"),
            text_color=ACCENT_LIGHT
        )
        path_label.grid(row=1, column=0, padx=18, pady=(12, 6), sticky="w")

        path_frame = ctk.CTkFrame(right, fg_color=BG_TERTIARY, corner_radius=CORNER_RADIUS_MD, border_width=2, border_color=BORDER_LIGHT)
        path_frame.grid(row=2, column=0, padx=18, pady=(0, 12), sticky="ew")
        path_frame.grid_columnconfigure(0, weight=1)

        self.path_btn = ctk.CTkButton(
            path_frame,
            text="Browse...",
            height=44,
            font=FONT_H2,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="white",
            corner_radius=CORNER_RADIUS_SM,
            command=self.select_path
        )
        self.path_btn.grid(row=0, column=0, padx=12, pady=10, sticky="ew")

        self.path_badge = Badge(path_frame, "NOT SET", DANGER)
        self.path_badge.grid(row=0, column=1, padx=(0, 12), pady=10)

        # API Key with enhanced styling
        key_label = ctk.CTkLabel(
            right,
            text="Gemini API Key",
            font=("Segoe UI", 11, "bold"),
            text_color=ACCENT_LIGHT
        )
        key_label.grid(row=3, column=0, padx=18, pady=(6, 6), sticky="w")

        key_frame = ctk.CTkFrame(right, fg_color=BG_TERTIARY, corner_radius=CORNER_RADIUS_MD, border_width=2, border_color=BORDER_LIGHT)
        key_frame.grid(row=4, column=0, padx=18, pady=(0, 18), sticky="ew")
        key_frame.grid_columnconfigure(0, weight=1)

        self.api_entry = CustomEntry(
            key_frame,
            placeholder_text="sk-...",
            height=44,
            font=FONT_BODY,
            fg_color=BG_TERTIARY,
            border_width=1,
            border_color=BORDER
        )
        self.api_entry.grid(row=0, column=0, padx=12, pady=10, sticky="ew")
        self.api_entry.bind("<KeyRelease>", self.check_api_input)

        self.api_badge = Badge(key_frame, "NOT SET", DANGER)
        self.api_badge.grid(row=0, column=1, padx=(0, 12), pady=10)

        # Prefill
        if self.origin_path:
            self.path_btn.configure(text=f"✓ {os.path.basename(self.origin_path)}")
            self.path_badge.configure(text="READY", fg_color=SUCCESS)
        if self.gemini_api_key:
            self.api_entry.insert(0, self.gemini_api_key)
            self.api_badge.configure(text="READY", fg_color=SUCCESS)

        # Action Buttons with enhanced styling
        actions = ctk.CTkFrame(right, fg_color=BG_PRIMARY)
        actions.grid(row=5, column=0, padx=18, pady=16, sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            actions,
            text="Save Settings",
            height=48,
            font=FONT_H2,
            fg_color=BG_TERTIARY,
            hover_color=BG_HOVER,
            border_width=2,
            border_color=BORDER_LIGHT,
            text_color=TEXT_PRIMARY,
            corner_radius=CORNER_RADIUS_MD,
            command=self.on_save_only
        ).grid(row=0, column=0, padx=(0, 8), sticky="ew")

        ctk.CTkButton(
            actions,
            text="Continue →",
            height=48,
            font=FONT_H2,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="white",
            corner_radius=CORNER_RADIUS_MD,
            command=self.go_to_selection
        ).grid(row=0, column=1, padx=(8, 0), sticky="ew")

    def on_save_only(self):
        self.gemini_api_key = self.api_entry.get().strip()
        if self.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = self.gemini_api_key
            os.environ.setdefault("GOOGLE_API_KEY", self.gemini_api_key)
        self.save_config()
        self.toast("Saved settings.", ok=True)

    def select_path(self):
        path = filedialog.askopenfilename(
            title="Select Origin Executable",
            filetypes=[("Executable files", "*.exe"), ("All files", "*.*")]
        )
        if path:
            self.origin_path = path
            self.path_btn.configure(text=f"Origin: .../{os.path.basename(path)}")
            self.path_badge.configure(text="READY", fg_color=ACCENT)
            self.save_config()
            self.toast("Origin path set.", ok=True)

    def check_api_input(self, _event=None):
        v = self.api_entry.get().strip()
        if len(v) > 10:
            self.api_badge.configure(text="READY", fg_color=ACCENT)
        else:
            self.api_badge.configure(text="NOT SET", fg_color=DANGER)

    def go_to_selection(self):
        # allow entering the dashboard even without Origin/key
        self.gemini_api_key = self.api_entry.get().strip()
        if self.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = self.gemini_api_key
            os.environ.setdefault("GOOGLE_API_KEY", self.gemini_api_key)
        self.save_config()
        self.show_selection_page()

    # ========================================================
    # Page 2: Selection (Dashboard)
    # ========================================================
    def show_selection_page(self):
        self.clear_screen()

        root = ctk.CTkFrame(self.container, fg_color=BG_PRIMARY)
        root.pack(fill="both", expand=True)
        root.grid_rowconfigure(1, weight=1)
        root.grid_columnconfigure(0, weight=1)

        # Enhanced Header with decorative elements
        header = ctk.CTkFrame(root, fg_color=BG_PRIMARY)
        header.pack(fill="x", padx=28, pady=(28, 12))
        header.grid_columnconfigure(0, weight=1)

        # Decorative accent line at top
        accent_line = ctk.CTkFrame(header, fg_color=ACCENT_GLOW, height=3)
        accent_line.pack(fill="x", pady=(0, 16))

        title_frame = ctk.CTkFrame(header, fg_color=BG_PRIMARY)
        title_frame.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            title_frame,
            text="Analysis Modules",
            font=FONT_HEADER_BIG,
            text_color=ACCENT_LIGHT
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_frame,
            text="Select an analysis module to get started",
            font=("Segoe UI", 12),
            text_color=TEXT_TERTIARY
        ).pack(anchor="w", pady=(4, 0))

        # Search & Actions with enhanced styling
        controls = ctk.CTkFrame(header, fg_color=BG_PRIMARY)
        controls.pack(fill="x")
        controls.grid_columnconfigure(0, weight=1)
        controls.grid_columnconfigure(1, weight=0)

        self.search_var = ctk.StringVar(value="")
        search = CustomEntry(
            controls,
            textvariable=self.search_var,
            placeholder_text="🔍 Search modules...",
            height=40,
            font=("Segoe UI", 11),
            fg_color=BG_SECONDARY,
            border_width=1,
            border_color=BORDER
        )
        search.grid(row=0, column=0, padx=(0, 12), sticky="ew")
        search.bind("<KeyRelease>", lambda e: self.refresh_cards())

        ctk.CTkButton(
            controls,
            text="⚙ Settings",
            width=140,
            height=40,
            font=FONT_H2,
            fg_color=BG_SECONDARY,
            hover_color=ACCENT_LIGHT,
            border_width=1,
            border_color=BORDER,
            text_color=TEXT_PRIMARY,
            command=self.show_setup_page
        ).grid(row=0, column=1, sticky="ew")

        # Content Area (hidden scrollbar)
        scroll = ctk.CTkScrollableFrame(root, fg_color=BG_PRIMARY, scrollbar_button_color=BG_PRIMARY, scrollbar_button_hover_color=BG_PRIMARY)
        scroll.pack(fill="both", expand=True, padx=28, pady=(12, 28))
        scroll.grid_columnconfigure(0, weight=1)

        self.scroll_parent = scroll

        self.modules = [
            ("Optoelectronic Analysis", [
                ("J-V Curve", "J-V Curve.png", "run_jv", run_jv),
                ("J-V Curve (Dark)", "J-V dark.png", "run_jv_dark", run_jv_dark),
                ("EQE", "EQE.png", "run_eqe", run_eqe),
            ]),
            ("Structural Analysis", [
                ("FE-SEM", "FE-SEM.png", "run_sem", run_sem),
                ("XRD", "XRD.png", "run_xrd", run_xrd),
            ]),
            ("Optical Analysis", [
                ("Abs", "Abs.png", "run_abs", run_abs),
                ("PL", "PL.png", "run_pl", run_pl),
            ]),
            ("Spectroscopic Analysis", [
                ("Raman", "Raman.png", "run_raman", run_raman),
                ("FTIR", "FTIR.png", "run_ftir", run_ftir),
            ]),
            ("Advanced Auto-Fitting (Spectra)", [
                ("XRD Pro", "XRD.png", "spectra_xrd", spectra_app),
                ("PL Pro", "PL.png", "spectra_pl", spectra_app),
            ]),
        ]

        self.refresh_cards()

    def open_spectra_tab(self, tab_name: str):
        """spectra.App is a ctk.CTk (separate root); run it as a separate process
        to avoid nested mainloops. Env vars like GEMINI_API_KEY are inherited."""
        if spectra_app is None:
            messagebox.showerror("Error", "Cannot load the Spectra module.")
            return
        try:
            if getattr(sys, "frozen", False):
                # in exe build: re-launch itself with the --spectra flag
                cmd = [sys.executable, "--spectra", tab_name]
            else:
                cmd = [sys.executable, "-m", "spectra.app", tab_name]
            subprocess.Popen(cmd, cwd=BASE_DIR)
            self.toast(f"Launched Spectra {tab_name} window as a new process.", ok=True)
        except Exception as e:
            messagebox.showerror("Error", f"Spectra launch failed:\n{e}")

    def refresh_cards(self):
        for w in self.scroll_parent.winfo_children():
            w.destroy()

        query = (self.search_var.get().strip().lower() if hasattr(self, "search_var") else "")

        for cat_title, items in self.modules:
            filtered = []
            for (name, icon, key, mod) in items:
                if not query or query in name.lower() or query in key.lower():
                    filtered.append((name, icon, key, mod))

            if not filtered:
                continue

            # Category Title with enhanced styling
            cat_header = ctk.CTkFrame(self.scroll_parent, fg_color=BG_PRIMARY)
            cat_header.pack(fill="x", pady=(24, 16))

            ctk.CTkLabel(
                cat_header,
                text=cat_title,
                font=FONT_H2,
                text_color=ACCENT_LIGHT
            ).pack(anchor="w")

            ctk.CTkLabel(
                cat_header,
                text=f"{len(filtered)} module{'s' if len(filtered) > 1 else ''}",
                font=("Segoe UI", 10),
                text_color=TEXT_TERTIARY
            ).pack(anchor="w", pady=(4, 0))
            
            # Enhanced Divider line with gradient effect
            divider = ctk.CTkFrame(self.scroll_parent, fg_color=BORDER_LIGHT, height=2)
            divider.pack(fill="x", pady=(12, 16))

            # Module Grid
            grid = ctk.CTkFrame(self.scroll_parent, fg_color=BG_PRIMARY)
            grid.pack(fill="x", pady=(0, 0))
            cols = 3
            for i in range(cols):
                grid.grid_columnconfigure(i, weight=1)

            r = 0
            c = 0
            for name, icon_file, module_key, module_obj in filtered:
                tile = self.build_module_tile(grid, name, icon_file, module_key, module_obj)
                tile.grid(row=r, column=c, padx=12, pady=12, sticky="nsew")
                c += 1
                if c >= cols:
                    c = 0
                    r += 1

    def build_module_tile(self, parent, name, icon_file, module_key, module_obj):
        tile = ctk.CTkFrame(
            parent,
            fg_color=BG_SECONDARY,
            corner_radius=CORNER_RADIUS_LG,
            border_width=2,
            border_color=BORDER
        )
        tile.grid_rowconfigure(2, weight=1)
        tile.grid_columnconfigure(0, weight=1)
        original_border = BORDER
        def on_enter(event):
            if module_obj:
                tile.configure(border_color=ACCENT_GLOW, fg_color=BG_HOVER)
            else:
                tile.configure(border_color=BORDER_LIGHT)
        
        def on_leave(event):
            tile.configure(border_color=BORDER, fg_color=BG_SECONDARY)

        # Icon Section with enhanced styling
        img_path = os.path.join(self.logo_dir, icon_file)
        img = safe_load_ctk_image(img_path, size=(64, 64))

        icon_frame = ctk.CTkFrame(tile, fg_color=BG_PRIMARY, corner_radius=CORNER_RADIUS_SM)
        icon_frame.grid(row=0, column=0, padx=14, pady=(14, 10), sticky="w")

        if img:
            ctk.CTkLabel(icon_frame, text="", image=img).pack(padx=6, pady=6)
        else:
            fallback = ctk.CTkFrame(
                icon_frame,
                width=64,
                height=64,
                fg_color=BG_TERTIARY,
                corner_radius=8,
                border_width=1,
                border_color=BG_TERTIARY
            )
            fallback.pack(padx=6, pady=6)
            fallback.pack_propagate(False)
            ctk.CTkLabel(
                fallback,
                text="◯",
                font=("Segoe UI", 20, "bold"),
                text_color=TEXT_SECONDARY
            ).place(relx=0.5, rely=0.5, anchor="center")

        # Title & Status with enhanced styling
        header = ctk.CTkFrame(tile, fg_color=BG_SECONDARY)
        header.grid(row=1, column=0, padx=14, pady=(0, 10), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)

        ctk.CTkLabel(
            header,
            text=name,
            font=FONT_H2,
            text_color=ACCENT_LIGHT
        ).grid(row=0, column=0, sticky="w")

        if module_obj is None:
            Badge(header, "MISSING", DANGER_LIGHT).grid(row=0, column=1, padx=(8, 0))
        else:
            Badge(header, "READY", SUCCESS_LIGHT).grid(row=0, column=1, padx=(8, 0))

        # Action Button with enhanced styling
        btn = ctk.CTkButton(
            tile,
            text="Open →",
            height=40,
            font=FONT_H2,
            fg_color=(ACCENT if module_obj else BG_TERTIARY),
            hover_color=(ACCENT_HOVER if module_obj else BG_TERTIARY),
            text_color=("white" if module_obj else TEXT_SECONDARY),
            border_width=0,
            state=("normal" if module_obj else "disabled"),
            corner_radius=CORNER_RADIUS_MD,
            command=lambda m=module_key: self.open_analysis_window(m)
        )
        btn.grid(row=2, column=0, padx=14, pady=(0, 14), sticky="ew")

        # Bind hover effect to tile
        tile.bind("<Enter>", on_enter)
        tile.bind("<Leave>", on_leave)

        return tile

    # ========================================================
    # Safe module open
    # ========================================================
    def open_analysis_window(self, module_key):
        # export Gemini key to env if present (runs fine without it)
        if self.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = self.gemini_api_key
            os.environ.setdefault("GOOGLE_API_KEY", self.gemini_api_key)

        try:
            target_class = None

            if module_key == "run_jv" and run_jv:
                target_class = run_jv.AnalysisWindow
            elif module_key == "run_jv_dark" and run_jv_dark:
                target_class = run_jv_dark.AnalysisWindow
            elif module_key == "run_eqe" and run_eqe:
                target_class = run_eqe.AnalysisWindow
            elif module_key == "run_sem" and run_sem:
                target_class = run_sem.AnalysisWindow
            elif module_key == "run_abs" and run_abs:
                target_class = run_abs.AnalysisWindow
            elif module_key == "run_raman" and run_raman:
                target_class = run_raman.AnalysisWindow
            elif module_key == "run_ftir" and run_ftir:
                target_class = run_ftir.AnalysisWindow

            elif module_key == "run_xrd" and run_xrd:
                target_class = run_xrd.AnalysisWindow
            elif module_key == "run_pl" and run_pl:
                target_class = run_pl.AnalysisWindow

            elif module_key == "spectra_xrd":
                self.open_spectra_tab("XRD")
                return
            elif module_key == "spectra_pl":
                self.open_spectra_tab("PL")
                return

            if target_class:
                self.iconify()
                window = target_class(self, self.origin_path, self.gemini_api_key)
                self.wait_window(window)
                self.deiconify()
            else:
                messagebox.showerror("Error", f"Module '{module_key}' failed to load or does not exist.")

        except AttributeError:
            self.deiconify()
            messagebox.showerror("Error", f"No 'AnalysisWindow' class in '{module_key}.py'.\n(check the module code)")
        except Exception as e:
            self.deiconify()
            messagebox.showerror("Error", f"Failed to open window:\n{e}")

if __name__ == "__main__":
    # in the frozen exe, re-launching with "--spectra XRD|PL" opens only the spectra window
    if "--spectra" in sys.argv:
        _idx = sys.argv.index("--spectra")
        _tab = sys.argv[_idx + 1] if len(sys.argv) > _idx + 1 else "PL"
        if spectra_app is not None:
            _sp = spectra_app.App(start_tab=_tab)
            _sp.mainloop()
        sys.exit(0)

    app = PhysisferaApp()
    app.mainloop()
