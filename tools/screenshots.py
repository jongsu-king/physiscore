"""Capture documentation screenshots of the main window and a few tools with
synthetic data loaded (macOS: uses `screencapture`, which needs screen-recording
permission for the terminal; elsewhere it tries Pillow's ImageGrab).

    python tools/screenshots.py [outdir]
"""
import os
import subprocess
import sys
import tempfile
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("PHYSISCORE_NO_UPDATE", "1")

import customtkinter as ctk  # noqa: E402


def grab(win, path):
    win.update_idletasks()
    win.update()
    time.sleep(0.6)
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    if sys.platform == "darwin":
        # include the title bar (about 28 px) above the client area
        subprocess.run(["screencapture", "-x", "-R", f"{x},{y - 28},{w},{h + 28}", path], check=False)
    else:
        from PIL import ImageGrab
        ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(path)
    ok = os.path.exists(path) and os.path.getsize(path) > 10000
    print(("ok   " if ok else "FAIL ") + path)
    return ok


def synthetic_jv_folder(tmp):
    from conftest import single_diode_jv
    v = np.round(np.arange(-0.2, 1.1001, 0.01), 4)
    sets = {"Reference": dict(jph=22.0, j0=1e-9, n=1.5, rs=2.0, rsh=2000.0),
            "Passivated": dict(jph=22.4, j0=2e-10, n=1.4, rs=1.6, rsh=5000.0)}
    rng = np.random.default_rng(0)
    for name, prm in sets.items():
        for k in range(1, 5):
            p = dict(prm)
            p["jph"] *= 1 + rng.normal(0, 0.01)
            p["rs"] *= 1 + rng.normal(0, 0.1)
            j = single_diode_jv(v, **p)
            j_r = single_diode_jv(v, **{**p, "j0": p["j0"] / 2})
            vv = np.concatenate([v, v[::-1]])
            jj = np.concatenate([j, j_r[::-1]])
            rows = "\n".join(f"{a:.4f}\t{-b * 0.04 / 1000:.9f}" for a, b in zip(vv, jj))
            with open(os.path.join(tmp, f"{name} {k}.txt"), "w", encoding="utf-8") as fh:
                fh.write("Voc V\tx\tJsc mA/cm2\tx\tx\tx\tFill Factor\tEfficiency\n0.9\t0\t22\t0\t0\t0\t77\t15\n")
                fh.write("Vmeas\tImeas\n" + rows + "\n")


def main_launcher(outdir):
    import Physiscore_Launcher as L
    app = L.LauncherApp()
    app.geometry("1180x740+40+60")
    for _ in range(40):
        app.update()
    time.sleep(1.0)
    ok = grab(app, os.path.join(outdir, "launcher.png"))
    app.on_closing()
    return ok


def capture_tool(name, outdir, tmp):
    """One tool per process (destroying customtkinter windows in a loop can
    corrupt the Tcl heap on some builds)."""
    root = ctk.CTk()
    root.withdraw()
    ok = False
    if name == "jv":
        synthetic_jv_folder(tmp)
        from scripts.JV import run_jv
        win = run_jv.AnalysisWindow(root, "", "")
        win.geometry("1500x920+40+60")
        win.directory_path.set(tmp)
        win.start_processing()
        for _ in range(400):
            root.update()
            time.sleep(0.02)
            if win.processed_data is not None and win.lbl_status.cget("text").startswith("Complete"):
                break
        for _ in range(10):
            root.update()
        kids = win.tree.get_children()
        if kids:
            win.tree.selection_set(kids[0])
            win._on_tree_select(None)
            for _ in range(10):
                root.update()
        ok = win.processed_data is not None and bool(kids)
        print("jv processed:", ok, "| rows:", len(kids))
        ok = grab(win, os.path.join(outdir, "jv.png")) and ok
        win.destroy()
    elif name == "eqe":
        from scipy.special import erf
        from pathlib import Path
        wl = np.arange(300.0, 1100.0, 1.0)
        e = 1239.84198 / wl
        eqe = 88 * 0.5 * (1 + erf((e - 1.60) / (0.03 * np.sqrt(2)))) * (1 - 0.3 * np.exp(-((wl - 350) / 60) ** 2))
        eqe_path = os.path.join(tmp, "device_A_EQE.csv")
        pd.DataFrame({"Wavelength (nm)": wl, "EQE (%)": eqe}).to_csv(eqe_path, index=False)
        from scripts.EQE import run_eqe
        win = run_eqe.AnalysisWindow(root, "", "")
        win.geometry("1500x920+40+60")
        win.target_file = Path(eqe_path)
        win.entry_voc.insert(0, "1.12")
        win._load_and_plot()
        win._auto_fit_all()
        for _ in range(10):
            root.update()
        ok = grab(win, os.path.join(outdir, "eqe.png")) and win.eqe_summary is not None
        win.destroy()
    elif name == "xrd":
        from conftest import pseudo_voigt
        x = np.round(np.arange(10.0, 45.0, 0.02), 4)
        y = (300 * np.exp(-(x - 10) / 25) + 40 + pseudo_voigt(x, 2000, 14.1, 0.12, 0.5)
             + pseudo_voigt(x, 900, 28.4, 0.15, 0.5) + pseudo_voigt(x, 400, 31.9, 0.18, 0.5)
             + pseudo_voigt(x, 300, 40.6, 0.2, 0.5) + np.random.default_rng(1).normal(0, 4, len(x)))
        from scripts.XRD import run_xrd
        win = run_xrd.AnalysisWindow(root, "", "")
        win.geometry("1500x920+40+60")
        tab = win.tab
        tab.x_data, tab.y_data = x, y
        tab.ax_prev.clear()
        tab.ax_prev.plot(x, y, color="gray", alpha=0.6, label="Raw")
        tab.canvas_prev.draw()
        tab.btn_run.configure(state="normal")
        tab.run_analysis()
        for _ in range(10):
            root.update()
        ok = grab(win, os.path.join(outdir, "xrd.png")) and len(tab.current_peaks_df) >= 3
        win.destroy()
    try:
        root.destroy()
    except Exception:
        pass
    return ok


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    results = []
    tmp = tempfile.mkdtemp(prefix="physiscore_shots_")
    for name in ("launcher", "jv", "eqe", "xrd"):
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--one", name, outdir, tmp])
        results.append(r.returncode == 0)
    return all(results)


if __name__ == "__main__":
    if "--one" in sys.argv:
        i = sys.argv.index("--one")
        name, outdir, tmp = sys.argv[i + 1], sys.argv[i + 2], sys.argv[i + 3]
        ok = main_launcher(outdir) if name == "launcher" else capture_tool(name, outdir, tmp)
        sys.exit(0 if ok else 1)
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "images")
    sys.exit(0 if main(out) else 1)
