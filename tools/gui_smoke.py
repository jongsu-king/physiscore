"""Open every analysis window once and close it again. Catches construction-
time errors in the GUI layer that the unit tests (which never import Tk)
cannot see. Needs a display (CI uses xvfb on Linux).

Each window runs in its own process: creating a second Tk interpreter after
destroying the first is not something the program ever does, and some Tk 9
builds crash on it. A final 'Session' check reproduces real use instead - one
launcher, every tool window opened and closed as its child.

The curve windows (SCLC ... Stability, PLQY, Mismatch) also load their built-in example,
analyse it and write the workbook with its analysis record. 'Workspace' builds
a small project folder, lets the launcher classify it and hands one file to
its tool.

    python tools/gui_smoke.py            # all windows + launcher + workspace + session
    python tools/gui_smoke.py XRD PL     # a subset

The settings file is a temporary one, so a run never touches the user's own.
"""
import importlib
import os
import subprocess
import sys
import tempfile
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
    "SCLC": "scripts.SCLC.run_sclc", "Intensity": "scripts.Intensity.run_intensity",
    "TRPL": "scripts.TRPL.run_trpl", "EIS": "scripts.EIS.run_eis", "CV": "scripts.CV.run_cv",
    "Stability": "scripts.Stability.run_stability", "PLQY": "scripts.PLQY.run_plqy",
    "Mismatch": "scripts.Mismatch.run_mismatch",
}
CURVE_TOOLS = ("SCLC", "Intensity", "TRPL", "EIS", "CV", "Stability", "PLQY", "Mismatch")
EXTRA = ("Launcher", "Workspace", "Session")


def _pump(widget, n=20, dt=0.0):
    for _ in range(n):
        widget.update()
        if dt:
            time.sleep(dt)


def _pump_until(widget, done, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        widget.update()
        if done():
            return True
        time.sleep(0.01)
    return False


def _exercise_curve_tool(win, tmp) -> str:
    """Example -> analysis -> workbook + analysis record. Returns '' or what failed."""
    win.load_example()
    if not _pump_until(win, lambda: not win._busy):
        return "the analysis did not finish"
    if win._item() is None:
        it = win.items.get(win.current) or {}
        return f"the example was not analysed: {it.get('error', 'no result')}"
    out = os.path.join(tmp, f"{win.SLUG}.xlsx")
    win.write_excel(out)
    if not (os.path.isfile(out) and os.path.isfile(out[:-5] + ".analysis.json")):
        return "the workbook or its analysis record was not written"
    for view in win.VIEWS:                      # every graph view draws without an error
        win.var_view.set(view)
        win._redraw()
        win.update()
    return ""


def _make_workspace(folder):
    """One file each for four tools and one that is not data."""
    import numpy as np
    import pandas as pd
    from scripts.EIS import eis_core
    from scripts.SCLC import sclc_core
    from scripts.Stability import stability_core
    from scripts.TRPL import trpl_core
    v, j = sclc_core.simulate()
    pd.DataFrame({"Voltage (V)": v, "J (mA/cm2)": j}).to_csv(os.path.join(folder, "EOD_sclc.csv"), index=False)
    t, y = trpl_core.simulate()
    pd.DataFrame({"Time (ns)": t, "Counts": y}).to_csv(os.path.join(folder, "film_TRPL.csv"), index=False)
    f, zr, zi = eis_core.simulate()
    pd.DataFrame({"Frequency (Hz)": f, "Z' (Ohm)": zr, "Z'' (Ohm)": zi}).to_csv(
        os.path.join(folder, "cell_EIS.csv"), index=False)
    st, sy = stability_core.simulate()
    pd.DataFrame({"Time (h)": st, "PCE (%)": np.asarray(sy)}).to_csv(
        os.path.join(folder, "cell_MPPT.csv"), index=False)
    with open(os.path.join(folder, "notes.txt"), "w", encoding="utf-8") as fh:
        fh.write("spin 4000 rpm 30 s\nanneal 150 C 15 min\n")
    return {"sclc", "trpl", "eis", "stability", ""}


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
    if key == "Workspace":
        import Physiscore_Launcher as L
        with tempfile.TemporaryDirectory() as tmp:
            kinds = _make_workspace(tmp)
            app = L.LauncherApp(workspace=tmp)
            ok = _pump_until(app, lambda: app.ws_panel.folder and not app.ws_panel.scanning
                             and len(app.ws_panel.detections) == len(kinds))
            found = {d.kind for d in app.ws_panel.detections}
            fail = "" if ok and found == kinds else f"detected kinds {sorted(found)}, expected {sorted(kinds)}"
            if not fail:
                d = next(x for x in app.ws_panel.detections if x.kind == "sclc")
                mod = importlib.import_module(TOOLS["SCLC"])
                win = mod.AnalysisWindow(app, "")
                L.hand_over(win, [d.path])
                if not _pump_until(win, lambda: not win._busy and win._item() is not None):
                    fail = "the file handed over from the workspace was not analysed"
                else:
                    win.write_excel(os.path.join(tmp, "sclc_results.xlsx"))
                    app.ws_panel.refresh_results()
                    _pump(app, 10)
                    if len(app.res_panel.entries) != 1:
                        fail = f"the Results tab lists {len(app.res_panel.entries)} exports, expected 1"
                win.destroy()
                _pump(app, 5)
            app.on_closing()
        if fail:
            print("workspace:", fail)
            return 1
        return 0
    if key == "Session":
        import Physiscore_Launcher as L
        app = L.LauncherApp()
        _pump(app, 100, 0.02)
        for name, mod_name in TOOLS.items():
            mod = importlib.import_module(mod_name)
            win = mod.CompareWindow(app, "xrd") if name == "Compare" else mod.AnalysisWindow(app, "")
            _pump(win, 15)
            win.destroy()
            _pump(app, 5)
        alive = bool(app.winfo_exists())
        app.on_closing()
        return 0 if alive else 1
    root = ctk.CTk()
    root.withdraw()
    mod = importlib.import_module(TOOLS[key])
    win = mod.CompareWindow(root, "xrd") if key == "Compare" else mod.AnalysisWindow(root, "")
    _pump(root, 20)
    fail = ""
    if key in CURVE_TOOLS:
        with tempfile.TemporaryDirectory() as tmp:
            fail = _exercise_curve_tool(win, tmp)
    win.destroy()
    _pump(root, 5)
    root.destroy()
    if fail:
        print(f"{key}: {fail}")
        return 1
    return 0


def main(names) -> int:
    failures = 0
    cfg_dir = tempfile.mkdtemp(prefix="physiscore_smoke_")
    env = dict(os.environ, PHYSISCORE_CONFIG=os.path.join(cfg_dir, "config.json"))
    for key in names:
        t0 = time.perf_counter()
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", key],
                           capture_output=True, text=True, timeout=300, env=env)
        dt = time.perf_counter() - t0
        if r.returncode == 0:
            print(f"ok    {key:9s} {dt:5.2f}s")
        else:
            failures += 1
            print(f"FAIL  {key}  (exit {r.returncode})")
            tail = [ln for ln in (r.stdout + r.stderr).splitlines()
                    if ln.strip() and "FutureWarning" not in ln][-25:]
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
    sel = [a for a in sys.argv[1:] if a in TOOLS or a in EXTRA]
    if not sel:
        sel = list(TOOLS) + list(EXTRA)
    sys.exit(1 if main(sel) else 0)
