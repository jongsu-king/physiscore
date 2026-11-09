"""Open every analysis window once (hidden root), pump the event loop, and
close it again. Catches construction-time errors in the GUI layer that the
unit tests (which never import Tk) cannot see. Needs a display.

    python tools/gui_smoke.py            # all tools
    python tools/gui_smoke.py XRD PL     # a subset
"""
import importlib
import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PHYSISCORE_NO_UPDATE", "1")

import customtkinter as ctk  # noqa: E402

TOOLS = {
    "JV": "scripts.JV.run_jv", "Dark": "scripts.Dark_JV.run_jv_dark", "EQE": "scripts.EQE.run_eqe",
    "Abs": "scripts.Abs.run_abs", "XRD": "scripts.XRD.run_xrd", "PL": "scripts.PL.run_pl",
    "Raman": "scripts.Raman.run_raman", "FTIR": "scripts.FTIR.run_ftir", "SEM": "scripts.SEM.run_sem",
}


def main(names):
    root = ctk.CTk()
    root.withdraw()
    failures = 0
    for key in names:
        mod_name = TOOLS[key]
        t0 = time.perf_counter()
        try:
            mod = importlib.import_module(mod_name)
            win = mod.AnalysisWindow(root, "", "")
            for _ in range(20):
                root.update()
            win.destroy()
            root.update()
            print(f"ok    {key:6s} {time.perf_counter() - t0:5.2f}s")
        except Exception:
            failures += 1
            print(f"FAIL  {key}")
            traceback.print_exc()
    try:
        root.destroy()
    except Exception:
        pass
    # launcher window itself (its own Tk root: CTkImage objects belong to one interpreter)
    try:
        import Physiscore_Launcher as L
        app = L.LauncherApp()
        for _ in range(40):
            app.update()
        app.on_closing()
        print("ok    Launcher")
    except Exception:
        failures += 1
        print("FAIL  Launcher")
        traceback.print_exc()
    return failures


if __name__ == "__main__":
    sel = [a for a in sys.argv[1:] if a in TOOLS] or list(TOOLS)
    sys.exit(1 if main(sel) else 0)
