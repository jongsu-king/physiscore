"""Open every analysis window once and close it again. Catches construction-
time errors in the GUI layer that the unit tests (which never import Tk)
cannot see. Needs a display (CI uses xvfb on Linux).

Each window runs in its own process: creating a second Tk interpreter after
destroying the first is not something the program ever does, and some Tk 9
builds crash on it. A final 'Session' check reproduces real use instead - one
launcher, every tool window opened and closed as its child.

    python tools/gui_smoke.py            # all windows + session
    python tools/gui_smoke.py XRD PL     # a subset
"""
import importlib
import os
import subprocess
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PHYSISCORE_NO_UPDATE", "1")

TOOLS = {
    "JV": "scripts.JV.run_jv", "Dark": "scripts.Dark_JV.run_jv_dark", "EQE": "scripts.EQE.run_eqe",
    "Abs": "scripts.Abs.run_abs", "XRD": "scripts.XRD.run_xrd", "PL": "scripts.PL.run_pl",
    "Raman": "scripts.Raman.run_raman", "FTIR": "scripts.FTIR.run_ftir", "SEM": "scripts.SEM.run_sem",
    "Device": "scripts.Device.run_device", "Compare": "scripts.common.compare_window",
}


def _pump(widget, n=20, dt=0.0):
    for _ in range(n):
        widget.update()
        if dt:
            time.sleep(dt)


def run_one(key) -> int:
    """Child process: open one window (or the launcher, or the session)."""
    import customtkinter as ctk
    if key == "Launcher":
        import Physiscore_Launcher as L
        app = L.LauncherApp()
        _pump(app, 60, 0.02)
        states = {c["status"].cget("text") for c in app.cards.values()}
        app.on_closing()
        if any(s.startswith("Unavailable") for s in states):
            print("launcher reports unavailable tools:", states)
            return 1
        return 0
    if key == "Session":
        import Physiscore_Launcher as L
        app = L.LauncherApp()
        _pump(app, 100, 0.02)
        for name, mod_name in TOOLS.items():
            mod = importlib.import_module(mod_name)
            win = mod.CompareWindow(app, "xrd") if name == "Compare" else mod.AnalysisWindow(app, "", "")
            _pump(win, 15)
            win.destroy()
            _pump(app, 5)
        alive = bool(app.winfo_exists())
        app.on_closing()
        return 0 if alive else 1
    root = ctk.CTk()
    root.withdraw()
    mod = importlib.import_module(TOOLS[key])
    win = mod.CompareWindow(root, "xrd") if key == "Compare" else mod.AnalysisWindow(root, "", "")
    _pump(root, 20)
    win.destroy()
    _pump(root, 5)
    root.destroy()
    return 0


def main(names) -> int:
    failures = 0
    for key in names:
        t0 = time.perf_counter()
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", key],
                           capture_output=True, text=True, timeout=300)
        dt = time.perf_counter() - t0
        if r.returncode == 0:
            print(f"ok    {key:8s} {dt:5.2f}s")
        else:
            failures += 1
            print(f"FAIL  {key}  (exit {r.returncode})")
            tail = [ln for ln in (r.stdout + r.stderr).splitlines()
                    if ln.strip() and "FutureWarning" not in ln and "generativeai" not in ln][-25:]
            print("\n".join("      " + ln for ln in tail))
    return failures


if __name__ == "__main__":
    if "--child" in sys.argv:
        key = sys.argv[sys.argv.index("--child") + 1]
        try:
            sys.exit(run_one(key))
        except Exception:
            traceback.print_exc()
            sys.exit(1)
    sel = [a for a in sys.argv[1:] if a in TOOLS or a in ("Launcher", "Session")]
    if not sel:
        sel = list(TOOLS) + ["Launcher", "Session"]
    sys.exit(1 if main(sel) else 0)
