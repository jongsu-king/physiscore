# app.py
# ------------------------------------------------------------
# Auto-fit - unified App (XRD Dashboard + PL)
# - Supports start_tab argument: "XRD" | "PL"
# ------------------------------------------------------------

from __future__ import annotations

import customtkinter as ctk

from spectra.core.config import PipelineConfig
from spectra.gui.tab_dashboard import SpectraDashboardTab
from spectra.gui.tab_pl import PLAnalysisTab
from scripts.common import palette as _pal
from scripts.common import theme as _theme  # noqa: F401  palette theme for customtkinter (3.2)


def build_default_configs():
    # ===== XRD =====
    xrd_cfg = PipelineConfig(
        technique="XRD",
        sg_window=31, sg_poly=3,
        als_lam=1e6, als_p=0.01,
        use_noise_based_prominence=True, noise_k=8.0,
        min_peak_separation_x=0.15,
        overlap_merge_dx=0.8, region_half_width=2.0, fit_pad=3.5,
    )

    # ===== PL =====
    pl_cfg = PipelineConfig(
        technique="PL",
        pl_enable_aic=True,
        pl_max_peaks=3,
        pl_defect_fwhm_threshold=0.25,
    )

    # ===== XPS =====
    xps_cfg = PipelineConfig(
        technique="XPS",
        sg_window=7, sg_poly=2,
        use_noise_based_prominence=True, noise_k=6.0,
        min_peak_separation_x=0.6,
        overlap_merge_dx=1.5, region_half_width=3.0, fit_pad=3.0,
        xps_background="shirley",
    )

    return xrd_cfg, pl_cfg, xps_cfg


class App(ctk.CTk):
    def __init__(self, start_tab: str = "PL"):
        super().__init__()

        # ---- Global UI theme ----
        ctk.set_appearance_mode("Dark" if _pal.IS_DARK else "Light")       # "Dark" | "Light" | "System"
        ctk.set_default_color_theme("blue")   # built-in theme

        st = (start_tab or "PL").upper()
        
        # Set window title based on selected tab
        self.title(f"Auto-fit - {st} Analysis")
        
        self.geometry("1500x900")
        self.minsize(1250, 780)

        xrd_cfg, pl_cfg, xps_cfg = build_default_configs()

        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, padx=14, pady=14)

        # ---- Only create selected tab ----
        if st == "XRD":
            t_xrd = tabs.add("XRD")
            SpectraDashboardTab(t_xrd, "XRD", xrd_cfg).pack(fill="both", expand=True)
            tabs.set("XRD")
        elif st == "XPS":
            t_xps = tabs.add("XPS")
            SpectraDashboardTab(t_xps, "XPS", xps_cfg).pack(fill="both", expand=True)
            tabs.set("XPS")
        else:  # PL
            t_pl = tabs.add("PL")
            PLAnalysisTab(t_pl, pl_cfg).pack(fill="both", expand=True)
            tabs.set("PL")

        # group boxes -> square boxes with header strips, as in the tool windows (3.2)
        try:
            _theme.instrumentize(self)
        except Exception:
            pass


if __name__ == "__main__":
    import sys

    # DPI fix (Windows)
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    # start tab can be set via CLI arg: python -m spectra.app XRD
    start_tab = sys.argv[1] if len(sys.argv) > 1 else "PL"
    app = App(start_tab=start_tab)
    app.mainloop()
