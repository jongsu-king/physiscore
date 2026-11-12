"""Documentation screenshots: every tool window with synthetic example data loaded.

    python tools/screenshots.py [outdir] [name ...]

Each window runs in its own process (several customtkinter windows created and
destroyed in one process can corrupt the Tcl heap on some builds). On macOS the
window alone is captured with `screencapture -l <window id>` (window id from
Quartz, `pip install pyobjc-framework-Quartz`), so other windows or system
dialogs on the screen never end up in the picture; this needs screen-recording
permission for the terminal. Elsewhere the window region is grabbed with Pillow.

All data are synthetic (analytical models with noise) and labelled as such in the
documentation. The windows read a settings file made for the run in a temporary
folder, and the main window keeps its update state in the same temporary folder,
so neither the settings, a folder nor the update history of the person who runs
the script ends up in a picture.
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

NAMES = ("launcher", "workspace", "results", "updates", "jv", "device", "dark", "eqe", "abs", "pl", "xrd", "sem",
         "raman", "ftir", "xps", "sclc", "intensity", "trpl", "trpl_irf", "eis", "eis_drt", "cv", "stability", "compare",
         "interpretation")
LAUNCHER_VIEWS = ("launcher", "workspace", "results", "updates")
PROJECT = "FAPbI3_batch_2026-11"      # the synthetic project folder of the main-window pictures
HC = 1239.84198
TOOL_SIZE = "1440x900+30+40"


# --------------------------------------------------------------------------- helpers
def pump(widget, seconds=0.5, until=None):
    t_end = time.time() + seconds
    while time.time() < t_end:
        widget.update()
        if until is not None and until():
            for _ in range(15):
                widget.update()
                time.sleep(0.02)
            return True
        time.sleep(0.02)
    return until() if until is not None else True


def quiet_dialogs(*modules):
    """Replace message boxes with prints and file dialogs with fixed answers."""
    from tkinter import messagebox
    for fn in ("showwarning", "showerror", "showinfo"):
        setattr(messagebox, fn, lambda title="", message="", **k: print(f"[dialog] {title}: {message}"))
    messagebox.askyesno = lambda *a, **k: False


def answer_file_dialog(module, path):
    module.filedialog.askopenfilename = lambda *a, **k: path


def _window_id(win):
    import Quartz
    title, pid = win.title(), os.getpid()
    best = None
    for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID):
        if int(w.get("kCGWindowOwnerPID", -1)) != pid:
            continue
        if not bool(w.get("kCGWindowIsOnscreen", False)):
            continue
        b = w.get("kCGWindowBounds", {})
        score = (str(w.get("kCGWindowName") or "") == title, float(b["Width"]) * float(b["Height"]))
        if best is None or score > best[0]:
            best = (score, int(w["kCGWindowNumber"]))
    return None if best is None else best[1]


def grab(win, path, width=1600):
    try:
        win.lift()
        win.attributes("-topmost", True)
    except Exception:
        pass
    pump(win, 1.2)
    if sys.platform == "darwin":
        wid = _window_id(win)
        if wid is None:
            import Quartz
            mine = [(w.get("kCGWindowName"), w.get("kCGWindowIsOnscreen"), w.get("kCGWindowLayer"))
                     for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID)
                     if int(w.get("kCGWindowOwnerPID", -1)) == os.getpid()]
            print("FAIL no window id for", win.title(), "| windows of this process:", mine)
            return False
        subprocess.run(["screencapture", "-x", "-o", f"-l{wid}", path], check=False)
        if os.path.exists(path):
            subprocess.run(["sips", "--resampleWidth", str(width), path], capture_output=True)
    else:
        from PIL import ImageGrab
        x, y = win.winfo_rootx(), win.winfo_rooty()
        ImageGrab.grab(bbox=(x, y, x + win.winfo_width(), y + win.winfo_height())).save(path)
    ok = os.path.exists(path) and os.path.getsize(path) > 20000
    print(("ok   " if ok else "FAIL ") + path)
    return ok


# --------------------------------------------------------------------------- synthetic data
def write_jv_folder(folder):
    from conftest import single_diode_jv
    os.makedirs(folder, exist_ok=True)
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
            # the source-meter reads the photocurrent as positive; Physiscore multiplies by -1000/area
            rows = "\n".join(f"{a:.4f}\t{b * 0.04 / 1000:.9f}" for a, b in zip(vv, jj))
            with open(os.path.join(folder, f"{name} {k}.txt"), "w", encoding="utf-8") as fh:
                fh.write("Vmeas\tImeas\n" + rows + "\n")
    return folder


def write_dark_folder(folder):
    from conftest import thermal_voltage
    os.makedirs(folder, exist_ok=True)
    v = np.round(np.arange(-0.3, 1.0001, 0.01), 4)
    rng = np.random.default_rng(3)
    for name, (j0, n, rsh) in {"Reference": (2e-9, 1.85, 4e4), "Passivated": (3e-10, 1.6, 1.5e5)}.items():
        for k in range(1, 4):
            vt = n * thermal_voltage()
            j = j0 * (1 + rng.normal(0, 0.1)) * np.expm1(v / vt) + 1000.0 * v / rsh
            j = j / (1 + 0.002 * np.maximum(j, 0))        # mild series-resistance roll-off
            i = -j * 0.04 / 1000 * (1 + rng.normal(0, 0.01, len(v)))   # instrument sign
            rows = "\n".join(f"{a:.4f}\t{b:.6e}" for a, b in zip(v, i))
            with open(os.path.join(folder, f"{name} {k}.txt"), "w", encoding="utf-8") as fh:
                fh.write("Vmeas\tImeas\n" + rows + "\n")
    return folder


def eqe_curve(wl, eg=1.60, peak=88.0, sigma=0.03):
    from scipy.special import erf
    e = HC / wl
    return peak * 0.5 * (1 + erf((e - eg) / (sigma * np.sqrt(2)))) * (1 - 0.3 * np.exp(-((wl - 350) / 60) ** 2))


def write_eqe(path, eg=1.60):
    wl = np.arange(300.0, 1000.0, 2.0)
    pd.DataFrame({"Wavelength (nm)": wl, "EQE (%)": eqe_curve(wl, eg)}).to_csv(path, index=False)
    return path


def absorbance_curve(wl, eg, eu=0.018, a0=7.0, rng=None):
    """Direct-gap film: (A hv)^2 linear in hv just above Eg and flattening higher
    up, an Urbach tail of width eu below it (soft-plus join), a small offset."""
    e = HC / wl
    de = e - eg
    core = np.sqrt((eu / 2) * np.logaddexp(0.0, 2 * de / eu))     # sqrt(de) above, exp(de/eu) below
    a = a0 * core / e / np.sqrt(1 + np.clip(de, 0, None) / 1.0) + 0.02
    if rng is not None:
        a = a + rng.normal(0, 0.002, len(wl))
    return a


def write_abs_xlsx(path):
    wl = np.arange(300.0, 900.0, 1.0)
    rng = np.random.default_rng(5)
    pd.DataFrame({"Wavelength (nm)": wl,
                  "Film A (as cast)": absorbance_curve(wl, 1.60, rng=rng),
                  "Film B (annealed)": absorbance_curve(wl, 1.58, eu=0.016, rng=rng)}
                 ).to_excel(path, index=False, sheet_name="UV-Vis")
    return path


def pl_band(wl, e0, fwhm_ev, amp):
    e = HC / wl
    s = fwhm_ev / 2.35482
    return amp * np.exp(-((e - e0) ** 2) / (2 * s * s)) * (HC / wl ** 2) * 1000 / 2


def write_pl(path):
    wl = np.arange(650.0, 900.0, 0.5)
    rng = np.random.default_rng(7)
    base = 20 + 0.02 * (wl - 650)
    cols = {"Wavelength (nm)": wl,
            "Perovskite film": base + pl_band(wl, 1.585, 0.085, 1000) + rng.normal(0, 4, len(wl)),
            "Film + passivation": base + pl_band(wl, 1.588, 0.080, 1650) + rng.normal(0, 4, len(wl)),
            "Film + PCBM": base + pl_band(wl, 1.584, 0.090, 170) + rng.normal(0, 4, len(wl))}
    pd.DataFrame(cols).to_csv(path, index=False)
    return path


def xrd_pattern():
    from conftest import pseudo_voigt
    x = np.round(np.arange(10.0, 45.0, 0.02), 4)
    y = (300 * np.exp(-(x - 10) / 25) + 40
         + pseudo_voigt(x, 2000, 14.08, 0.12, 0.5) + pseudo_voigt(x, 260, 19.98, 0.13, 0.5)
         + pseudo_voigt(x, 380, 24.50, 0.14, 0.5) + pseudo_voigt(x, 900, 28.40, 0.15, 0.5)
         + pseudo_voigt(x, 400, 31.86, 0.18, 0.5) + pseudo_voigt(x, 300, 40.60, 0.20, 0.5)
         + pseudo_voigt(x, 520, 12.70, 0.10, 0.4)                        # PbI2 (001), a second phase
         + np.random.default_rng(1).normal(0, 4, len(x)))
    return x, y


def write_xrd_reference(path):
    pd.DataFrame({"2theta": [14.10, 19.97, 24.51, 28.43, 31.86, 40.62],
                  "h": [1, 1, 1, 2, 2, 2], "k": [0, 1, 1, 0, 1, 2], "l": [0, 0, 1, 0, 0, 0],
                  "I": [100, 15, 20, 60, 25, 18]}).to_csv(path, index=False)
    return path


def write_sem_image(path):
    import cv2
    from scipy.spatial import cKDTree
    rng = np.random.default_rng(11)
    h, w, bar = 704, 1024, 64
    pts = rng.uniform([0, 0], [w, h], size=(140, 2))
    yy, xx = np.mgrid[0:h, 0:w]
    _, lab = cKDTree(pts).query(np.c_[xx.ravel(), yy.ravel()])
    lab = lab.reshape(h, w)
    shade = rng.uniform(150, 215, len(pts))
    img = shade[lab]
    edge = np.zeros((h, w), bool)
    edge[:, 1:] |= lab[:, 1:] != lab[:, :-1]
    edge[1:, :] |= lab[1:, :] != lab[:-1, :]
    edge = cv2.dilate(edge.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    img[edge] = 45
    img = cv2.GaussianBlur(img.astype(np.float32), (0, 0), 1.2) + rng.normal(0, 6, (h, w))
    full = np.zeros((h + bar, w), np.float32)
    full[:h] = img
    full = np.clip(full, 0, 255).astype(np.uint8)
    cv2.putText(full, "SYNTHETIC EXAMPLE   5.0 kV   x50,000   WD 4.1 mm", (16, h + 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, 255, 1, cv2.LINE_AA)
    cv2.rectangle(full, (820, h + 26), (920, h + 32), 255, -1)
    cv2.putText(full, "200 nm", (835, h + 54), cv2.FONT_HERSHEY_SIMPLEX, 0.55, 255, 1, cv2.LINE_AA)
    cv2.imwrite(path, full)
    return path


def lorentz(x, c, fwhm, amp):
    return amp * (fwhm / 2) ** 2 / ((x - c) ** 2 + (fwhm / 2) ** 2)


def write_raman(path):
    x = np.arange(100.0, 800.0, 1.0)
    rng = np.random.default_rng(13)
    bands = [(144, 9, 1000), (197, 10, 90), (399, 16, 210), (516, 15, 190), (639, 18, 260)]
    a = sum(lorentz(x, c, f, h) for c, f, h in bands)
    b = sum(lorentz(x, c + 2.5, f * 1.15, h * 0.55) for c, f, h in bands)
    bg = 120 + 0.25 * (x - 100) + 60 * np.exp(-(x - 100) / 300)
    pd.DataFrame({"Raman shift (cm-1)": x,
                  "TiO2 layer": a + bg + rng.normal(0, 5, len(x)),
                  "TiO2 + perovskite": b + bg * 1.3 + rng.normal(0, 5, len(x))}).to_csv(path, index=False)
    return path


def write_ftir(path):
    x = np.arange(4000.0, 600.0, -2.0)
    rng = np.random.default_rng(17)

    def g(c, w, a):
        return a * np.exp(-((x - c) ** 2) / (2 * (w / 2.355) ** 2))
    a1 = g(3170, 120, 0.25) + g(2920, 30, 0.12) + g(2850, 25, 0.08) + g(1710, 30, 0.35) + g(1470, 25, 0.22) \
        + g(1250, 40, 0.18) + g(1090, 50, 0.30) + g(910, 25, 0.12)
    a2 = g(3170, 120, 0.20) + g(2920, 30, 0.10) + g(2850, 25, 0.07) + g(1714, 30, 0.20) + g(1470, 25, 0.20) \
        + g(1250, 40, 0.10) + g(1090, 50, 0.32) + g(910, 25, 0.12)
    t1 = 100 * 10 ** (-(a1 + 0.02)) + rng.normal(0, 0.15, len(x))
    t2 = 100 * 10 ** (-(a2 + 0.03)) + rng.normal(0, 0.15, len(x))
    pd.DataFrame({"Wavenumber (cm-1)": x, "Sample A": t1, "Sample B": t2}).to_csv(path, index=False)
    return path


def write_xps(path):
    be = np.arange(132.0, 150.0, 0.05)
    rng = np.random.default_rng(19)

    def gl(c, fwhm, area, m=0.3):
        s = fwhm / 2.355
        gauss = np.exp(-((be - c) ** 2) / (2 * s * s)) / (s * np.sqrt(2 * np.pi))
        lor = (fwhm / 2) / np.pi / ((be - c) ** 2 + (fwhm / 2) ** 2)
        return area * ((1 - m) * gauss + m * lor)
    peaks = gl(138.60, 0.95, 4000) + gl(143.47, 0.95, 3000) + gl(136.85, 0.8, 380) + gl(141.72, 0.8, 285)
    step = 900 + 0.12 * np.cumsum(peaks[::-1])[::-1] * 0.05     # Shirley-like step towards high BE
    y = rng.poisson(np.clip(peaks + step, 1, None)).astype(float)
    pd.DataFrame({"Binding Energy (eV)": be, "Counts": y}).to_csv(path, index=False)
    return path


def write_device_inputs(tmp):
    from conftest import single_diode_jv
    v = np.round(np.arange(-0.1, 1.2001, 0.01), 4)
    j = single_diode_jv(v, jph=21.9, j0=4e-12, n=1.45, rs=2.2, rsh=3000.0)
    jv = os.path.join(tmp, "device_A_JV.txt")
    with open(jv, "w", encoding="utf-8") as fh:
        fh.write("Vmeas\tImeas\n" + "\n".join(f"{a:.4f}\t{b * 0.04 / 1000:.9f}" for a, b in zip(v, j)) + "\n")
    eqe = write_eqe(os.path.join(tmp, "device_A_EQE.csv"), 1.60)
    ab = write_abs_xlsx(os.path.join(tmp, "film_A_abs.xlsx"))
    pl = write_pl(os.path.join(tmp, "film_A_PL.csv"))
    return {"jv": jv, "eqe": eqe, "abs": ab, "pl": pl}


# --------------------------------------------------------------------------- synthetic project
def _table(path, cols, sep=",", pre=""):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(pre)
        pd.DataFrame(cols).to_csv(fh, index=False, sep=sep)


def _instrument_export(path, v, j, area=0.04, summary=True):
    """Source-meter export: optional summary block, then Vmeas / Imeas (A, photocurrent positive)."""
    lines = []
    if summary:
        lines += ["Voc V\tVoc_mA\tJsc mA/cm2\tx\ty\tz\tFill Factor\tEfficiency", "1.1\t0\t24.9\t0\t0\t0\t80.0\t22.0"]
    lines.append("Vmeas\tImeas")
    lines += [f"{a:.4f}\t{-b * area / 1000.0:.9e}" for a, b in zip(v, j)]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def write_project(folder):
    """A sample batch as it lies on a lab computer: one sub-folder per technique,
    files named by sample, and a few files whose names say nothing."""
    from scipy.special import erf
    from scripts.JV.jv_core import single_diode_current
    from scripts.TRPL import trpl_core
    from scripts.SCLC import sclc_core
    from scripts.Intensity import intensity_core
    from scripts.EIS import eis_core
    from scripts.CV import cv_core
    from scripts.Stability import stability_core
    rng = np.random.default_rng(7)

    def p(*parts):
        path = os.path.join(folder, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    v = np.round(np.arange(-0.2, 1.2501, 0.01), 4)
    for grp, jph, j0, n, rs, rsh in (("Ref", 24.6, 4e-11, 1.55, 2.6, 2500.0), ("PEAI", 25.1, 6e-12, 1.38, 1.9, 6000.0)):
        for i in range(1, 5):
            k = 1 + 0.02 * rng.standard_normal()
            fwd = single_diode_current(v, jph * k, j0 * 1.6, n, rs * 1.3, rsh)
            rev = single_diode_current(v, jph * k, j0, n, rs, rsh)
            _instrument_export(p("JV", f"{grp} {i}.txt"), np.concatenate([v, v[::-1]]), np.concatenate([fwd, rev[::-1]]))
    vd = np.round(np.arange(-1.0, 1.3001, 0.02), 4)
    for grp, j0, n in (("Ref", 4e-11, 1.55), ("PEAI", 6e-12, 1.38)):
        _instrument_export(p("JV_dark", f"{grp}_dark.txt"), vd, single_diode_current(vd, 0.0, j0, n, 2.0, 5e4),
                           summary=False)

    wl = np.arange(300.0, 901.0, 5.0)
    e = HC / wl
    for grp, eg in (("Ref", 1.53), ("PEAI", 1.535)):
        eqe = 88 * 0.5 * (1 + erf((e - eg) / (0.028 * np.sqrt(2)))) * (1 - 0.35 * np.exp(-(wl - 300) / 60))
        _table(p("EQE", f"{grp}_EQE.csv"), {"Wavelength (nm)": wl, "EQE (%)": np.round(eqe, 3)})
    wl = np.arange(400.0, 901.0, 1.0)
    e = HC / wl
    a = 2.8 * 0.5 * (1 + erf((e - 1.53) / 0.03)) * (0.6 + 0.4 * (e - 1.3)) + 0.05
    pd.DataFrame({"Wavelength (nm)": wl, "Ref": a, "PEAI": a * 1.03}).to_excel(p("UV-Vis", "FAPbI3_abs.xlsx"), index=False)
    wl = np.arange(700.0, 901.0, 0.5)
    pl = 4200 * np.exp(-0.5 * ((wl - 805) / 17) ** 2) + 30 + 6 * rng.standard_normal(len(wl))
    _table(p("PL", "Ref_PL.csv"), {"Wavelength (nm)": wl, "Ref": pl, "PEAI": 2.6 * pl})
    head = "# TCSPC export\n# excitation 640 nm, 1 MHz\n"
    t, y = trpl_core.simulate(taus=(8.0, 140.0), amps=(0.6, 0.4))
    _table(p("PL", "Ref_TRPL.csv"), {"Time (ns)": t, "Counts": y}, pre=head)
    t, y = trpl_core.simulate(taus=(15.0, 620.0), amps=(0.35, 0.65))
    _table(p("PL", "PEAI_TRPL.csv"), {"Time (ns)": t, "Counts": y}, pre=head)

    tt = np.arange(10.0, 50.0, 0.02)
    xrd = 40 + 8 * rng.random(len(tt))
    for c, h, w in ((13.95, 5200, 0.09), (19.8, 300, 0.1), (24.3, 900, 0.1), (28.1, 2600, 0.1), (31.5, 1100, 0.11),
                    (40.2, 500, 0.12), (42.8, 420, 0.12), (12.7, 180, 0.1)):
        xrd += h * np.exp(-0.5 * ((tt - c) / w) ** 2)
    _table(p("XRD", "Ref_XRD.xy"), {"2theta": np.round(tt, 3), "counts": np.round(xrd, 1)}, sep="\t")
    shift = np.arange(60.0, 1800.0, 1.0)
    raman = 20 + sum(h * w ** 2 / ((shift - c) ** 2 + w ** 2)
                     for c, h, w in ((110, 900, 12), (135, 500, 14), (521, 3000, 3), (1100, 140, 20)))
    _table(p("Raman", "Ref_Raman.csv"), {"Raman shift (cm-1)": shift, "Intensity": raman})
    wn = np.arange(4000.0, 399.0, -2.0)
    tr = 96 - sum(h * np.exp(-0.5 * ((wn - c) / w) ** 2)
                  for c, h, w in ((3400, 22, 60), (3270, 16, 45), (1712, 30, 12), (1610, 14, 14), (1470, 9, 12),
                                  (1350, 7, 12)))
    _table(p("FTIR", "Ref_FTIR.csv"), {"Wavenumber (cm-1)": wn, "Transmittance (%)": tr})
    be = np.arange(148.0, 133.99, -0.05)
    xps = (900 + 9000 * np.exp(-0.5 * ((be - 138.4) / 0.42) ** 2) + 6800 * np.exp(-0.5 * ((be - 143.26) / 0.42) ** 2)
           + 30 * rng.standard_normal(len(be)))
    _table(p("XPS", "Ref_XPS_Pb4f.csv"), {"Binding Energy (eV)": np.round(be, 2), "Counts / s": np.round(xps, 1)})
    write_sem_image(p("SEM", "Ref_SEM_x50k.tif"))

    for grp, mu, nt in (("Ref", 1.0, 5e16), ("PEAI", 1.6, 2e16)):
        vv, jj = sclc_core.simulate(thickness_nm=500, eps_r=25, mobility_cm2_Vs=mu, n_t_cm3=nt, n0_cm3=1e13)
        jj = jj * (1 + 0.02 * rng.standard_normal(len(jj)))          # 2 % current noise
        _table(p("SCLC", f"EOD_{grp}_sclc.csv"), {"Voltage (V)": vv, "J (mA/cm2)": jj})
    d = intensity_core.simulate()
    d["voc"] = d["voc"] + 0.0015 * rng.standard_normal(len(d["voc"]))         # 1.5 mV and 1 % read-out scatter
    d["jsc"] = d["jsc"] * (1 + 0.01 * rng.standard_normal(len(d["jsc"])))
    _table(p("Suns-Voc", "Ref_intensity.csv"), {"Irradiance (mW/cm2)": d["intensity"], "Voc (V)": d["voc"],
                                                "Jsc (mA/cm2)": d["jsc"], "FF (%)": d["ff"], "PCE (%)": d["pce"]})
    f, zre, zim = eis_core.simulate()
    _table(p("EIS", "Ref_EIS_0V_dark.csv"), {"Frequency (Hz)": f, "Z' (Ohm)": zre, "Z'' (Ohm)": zim})
    bias, cap = cv_core.simulate(n_cm3=1e17, v_bi=0.9, eps_r=25.0, area_cm2=0.1, noise=0.004, seed=3)
    _table(p("CV", "Ref_MottSchottky_10kHz.csv"), {"Bias (V)": bias, "Cp (F)": cap})
    t, y = stability_core.simulate()
    _table(p("Stability", "Ref_MPPT_ISOS-L-1.csv"), {"Time (h)": t, "PCE (%)": y})
    t, y = stability_core.simulate(a1=0.04, tau1=25.0, rate_per_h=4e-5)
    _table(p("Stability", "PEAI_MPPT_ISOS-L-1.csv"), {"Time (h)": t, "PCE (%)": y})

    # files whose names say nothing: the measurement is judged from columns and numbers alone
    f, zre, zim = eis_core.simulate(model="R(RQ)")
    _table(p("unsorted", "sample_07.csv"), {"A": f, "B": zre, "C": zim})
    t, y = trpl_core.simulate()
    np.savetxt(p("unsorted", "run_0012.txt"), np.column_stack([t, y]), fmt="%.6g", delimiter="\t")
    np.savetxt(p("unsorted", "device3.dat"),
               np.column_stack([v, single_diode_current(v, 23.0, 1e-10, 1.5, 2.0, 3000.0)]), fmt="%.6g", delimiter="\t")
    with open(p("unsorted", "notes.txt"), "w", encoding="utf-8") as fh:
        fh.write("spin 4000 rpm 30 s\nanneal 150 C 15 min\n")
    return folder


# the files of the project each new tool reads, and the entries that differ from the defaults
PROJECT_RUNS = {
    "sclc": (("SCLC", "EOD_Ref_sclc.csv"), ("SCLC", "EOD_PEAI_sclc.csv")),
    "intensity": (("Suns-Voc", "Ref_intensity.csv"),),
    "trpl": (("PL", "Ref_TRPL.csv"), ("PL", "PEAI_TRPL.csv")),
    "eis": (("EIS", "Ref_EIS_0V_dark.csv"),),
    "cv": (("CV", "Ref_MottSchottky_10kHz.csv"),),
    "stability": (("Stability", "Ref_MPPT_ISOS-L-1.csv"), ("Stability", "PEAI_MPPT_ISOS-L-1.csv")),
}
PROJECT_PARAMS = {"sclc": {"thickness_nm": 500.0, "eps_r": 25.0}, "cv": {"area_cm2": 0.1, "eps_r": 25.0, "thickness_nm": 500.0},
                  "stability": {"protocol": "ISOS-L-1"}}


def project_files(folder, tool):
    return [os.path.join(folder, *parts) for parts in PROJECT_RUNS[tool]]


def write_project_results(folder):
    """Export the analyses of the project the way the windows do, so that the
    Results tab of the main window has side-cars to list."""
    from scripts.common import curve_batch
    out = os.path.join(folder, "results")
    os.makedirs(out, exist_ok=True)
    for tool in PROJECT_RUNS:
        params = curve_batch.parameters(tool, PROJECT_PARAMS.get(tool))
        items = curve_batch.run_files(tool, project_files(folder, tool), params)
        bad = [it["file"] for it in items if it["result"] is None]
        if bad:
            raise RuntimeError(f"{tool}: no result for {', '.join(bad)}")
        curve_batch.write_excel(tool, items, os.path.join(out, f"{PROJECT.split('_')[0]}_{tool}.xlsx"), params)
    return out


def project(tmp):
    """The synthetic project of this run (written once, shared by the per-window processes)."""
    folder = os.path.join(tmp, PROJECT)
    done = os.path.join(tmp, "project.ok")
    if not os.path.exists(done):
        write_project(folder)
        write_project_results(folder)
        open(done, "w").close()
    return folder


# --------------------------------------------------------------------------- windows
def isolate_update_state(L, tmp):
    """Keep the updater's settings (last check, latest release seen) in the run's
    temporary folder. Without this the Updates tab shows whatever the copy of
    Physiscore on this machine last saw, which is not reproducible."""
    folder = os.path.join(tmp, "update-state")
    os.makedirs(folder, exist_ok=True)
    make = L.make_update_app

    def isolated(selfupdate):
        import dataclasses
        return dataclasses.replace(make(selfupdate), settings_dir=folder)

    L.make_update_app = isolated


def shot_launcher(outdir, tmp, view="launcher"):
    """The main window on the synthetic project: the Workspace tab as it opens
    (launcher), the same tab with a file of unknown name selected (workspace),
    the Results tab (results) and the Updates tab (updates)."""
    import Physiscore_Launcher as L
    quiet_dialogs()
    isolate_update_state(L, tmp)
    app = L.LauncherApp(workspace=project(tmp))
    app.geometry("1280x900+30+40")
    pump(app, 20, until=lambda: all(c["status"].cget("text").startswith("Ready") for c in app.cards.values()))
    scanned = pump(app, 30, until=lambda: not app.ws_panel.scanning and bool(app.ws_panel.detections))
    ok = bool(scanned)
    if view == "workspace":
        app.tabs.set("Workspace")
        app.tree.selection_set(app.cards["scripts.TRPL.run_trpl"]["iid"])
        weak = [iid for iid, d in app.ws_panel._rows.items() if os.path.basename(d.path) == "run_0012.txt"]
        ok = ok and bool(weak)
        if weak:
            app.ws_panel.tree.selection_set(weak[0])
            app.ws_panel.tree.see(weak[0])
    elif view == "results":
        app.tabs.set("Results")
        ok = ok and len(app.ws_panel.entries) == len(PROJECT_RUNS)
    elif view == "updates":
        app.tabs.set("Updates")
    pump(app, 2.5)
    ok = grab(app, os.path.join(outdir, f"{view}.png")) and ok
    app.on_closing()
    return ok


def reset_fields(win):
    """Every parameter at its default: a window restores the values an earlier
    window of the same run remembered, and the picture must not depend on them."""
    for f in win.FIELDS:
        d = f.get("default", "")
        d = d() if callable(d) else d
        win.set_param(f["key"], f"{d:g}" if isinstance(d, float) else d)


def shot_curve_tool(name, win, tmp):
    """One of the six windows built on CurveToolWindow, with its project files analysed."""
    reset_fields(win)
    for key, value in PROJECT_PARAMS.get(name, {}).items():
        win.set_param(key, value)
    files = project_files(project(tmp), name)
    win.load_paths(files, run=False)
    win.run(sync=True)
    if win.file_tree.exists(files[0]):
        win.file_tree.selection_set(files[0])
    return all(win.items.get(f, {}).get("result") is not None for f in files)


def shot_view(name, win, tmp):
    """TRPL with a Gaussian-response reconvolution, impedance on its DRT view."""
    from scripts.EIS import eis_core
    from scripts.TRPL import trpl_core
    if name == "trpl_irf":
        path = os.path.join(tmp, "Film_TRPL_25ps.csv")
        t, y = trpl_core.simulate(taus=(0.35, 3.2), amps=(0.55, 0.45), peak_counts=1e4, background=3.0, n=1000,
                                  t_max=25.0, t0=2.0, irf_fwhm=0.5, seed=3)
        _table(path, {"Time (ns)": t, "Counts": y}, pre="# TCSPC export\n# excitation 640 nm, 40 MHz, 25 ps bins\n")
        params, view = {"irf": "gaussian", "irf_fwhm": 0.0, "model": "auto"}, "Decay (log)"
    else:
        path = os.path.join(tmp, "Cell_EIS_0V_dark.csv")
        f, zr, zi = eis_core.simulate()
        _table(path, {"Frequency (Hz)": f, "Z' (Ohm)": zr, "Z'' (Ohm)": zi})
        params, view = {}, "DRT"
    reset_fields(win)
    for key, value in params.items():
        win.set_param(key, value)
    win.load_paths([path], run=False)
    win.run(sync=True)
    if win.file_tree.exists(path):
        win.file_tree.selection_set(path)
    win.var_view.set(view)
    win._redraw()
    return win.items.get(path, {}).get("result") is not None


def shot_tool(name, outdir, tmp):
    import customtkinter as ctk
    quiet_dialogs()
    root = ctk.CTk()
    root.withdraw()
    out = os.path.join(outdir, f"{name}.png")
    ok = False

    if name == "jv":
        from scripts.JV import run_jv
        win = run_jv.AnalysisWindow(root, "")
        win.geometry(TOOL_SIZE)
        win.directory_path.set(write_jv_folder(os.path.join(tmp, "jv")))
        win.start_processing()
        pump(root, 40, until=lambda: win.processed_data is not None and bool(win.tree.get_children()))
        kids = win.tree.get_children()
        if kids:
            win.tree.selection_set(kids[0])
            win._on_tree_select(None)
        ok = grab(win, out) and bool(kids)

    elif name == "interpretation":
        from scripts.JV import run_jv
        from scripts.common import interpret as _interp
        from scripts.common.interpret_window import InterpretationWindow
        jv = run_jv.AnalysisWindow(root, "")
        jv.geometry(TOOL_SIZE)
        jv.directory_path.set(write_jv_folder(os.path.join(tmp, "jv")))
        jv.start_processing()
        pump(root, 40, until=lambda: jv.processed_data is not None and bool(jv.tree.get_children()))
        win = InterpretationWindow(jv, _interp.interpret_jv_results(jv.processed_data))
        win.transient("")          # a free window, so the capture holds only this one
        jv.withdraw()
        win.geometry("1180x760+60+60")
        pump(root, 2)
        ok = grab(win, out) and bool(win.tree.get_children())

    elif name == "dark":
        from scripts.Dark_JV import run_jv_dark
        win = run_jv_dark.DarkAnalysisWindow(root, "")
        win.geometry(TOOL_SIZE)
        win.directory_path.set(write_dark_folder(os.path.join(tmp, "dark")))
        win.start_processing()
        pump(root, 40, until=lambda: bool(win.tree.get_children()))
        kids = win.tree.get_children()
        if kids:
            win.tree.selection_set(kids[0])
            win._on_tree_select(None)
        ok = grab(win, out) and bool(kids)

    elif name == "eqe":
        from pathlib import Path
        from scripts.EQE import run_eqe
        win = run_eqe.AnalysisWindow(root, "")
        win.geometry(TOOL_SIZE)
        win.target_file = Path(write_eqe(os.path.join(tmp, "device_A_EQE.csv")))
        win.entry_file.insert(0, str(win.target_file))
        win.entry_voc.insert(0, "1.12")
        win._load_and_plot()
        win._auto_fit_all()
        pump(root, 2)
        ok = grab(win, out) and win.eqe_summary is not None

    elif name == "abs":
        from pathlib import Path
        from scripts.Abs import run_abs
        path = write_abs_xlsx(os.path.join(tmp, "films_abs.xlsx"))
        win = run_abs.AnalysisWindow(root, "")
        win.geometry(TOOL_SIZE)
        win.entry_file.insert(0, path)
        win.target_file = Path(path)
        win.sheet_menu.configure(values=["UV-Vis"])
        win.selected_sheet.set("UV-Vis")
        win.load_data_from_ui()
        pump(root, 1)
        win.entry_expected_eg.insert(0, "1.6")
        win.auto_fit_expected()
        pump(root, 2)
        ok = grab(win, out) and bool(win.fit_result)

    elif name == "pl":
        from scripts.PL import run_pl
        win = run_pl.PLAnalysisWindow(root, "")
        win.geometry(TOOL_SIZE)
        win.file_path_var.set(write_pl(os.path.join(tmp, "films_PL.csv")))
        win.load_data()
        pump(root, 1)
        win.var_ref_col.set("Perovskite film")
        win.var_filter_width.set(5)      # Savitzky-Golay window (points)
        win.var_rigidity.set(8)          # ALS log10(lambda); 8 suits 0.5 nm sampling of a broad band
        win.var_protection.set(0.01)     # ALS asymmetry p
        win.run_analysis()
        pump(root, 3)
        ok = grab(win, out)

    elif name == "xrd":
        from scripts.XRD import run_xrd
        win = run_xrd.AnalysisWindow(root, "")
        win.geometry(TOOL_SIZE)
        tab = win.tab
        x, y = xrd_pattern()
        tab.x_data, tab.y_data = x, y
        tab.ax_prev.clear()
        tab.ax_prev.plot(x, y, color="gray", alpha=0.6, label="Raw")
        tab.canvas_prev.draw()
        tab.btn_run.configure(state="normal")
        tab.run_analysis()
        pump(root, 2)
        answer_file_dialog(run_xrd, write_xrd_reference(os.path.join(tmp, "MAPbI3_cubic_reference.csv")))
        tab.load_reference()
        pump(root, 2)
        ok = grab(win, out) and tab.current_peaks_df is not None and len(tab.current_peaks_df) >= 3

    elif name == "sem":
        from scripts.SEM import run_sem
        win = run_sem.AnalysisWindow(root, "")
        win.geometry(TOOL_SIZE)
        answer_file_dialog(run_sem, write_sem_image(os.path.join(tmp, "film_A_SEM.png")))
        win.load_image()
        pump(root, 1)
        win.nm_per_px = 2.0
        win.lbl_scale_info.configure(text="Scale: 2.0000 nm/px (scale bar 200 nm = 100 px)")
        win.run_auto_segment()
        pump(root, 60, until=lambda: len(win.records) >= 20)
        pump(root, 2)
        ok = grab(win, out) and len(win.records) > 0
        print("sem grains:", len(win.records))

    elif name in ("raman", "ftir"):
        mod_name = "scripts.Raman.run_raman" if name == "raman" else "scripts.FTIR.run_ftir"
        import importlib
        mod = importlib.import_module(mod_name)
        path = write_raman(os.path.join(tmp, "raman.csv")) if name == "raman" else write_ftir(os.path.join(tmp, "ftir.csv"))
        win = mod.AnalysisWindow(root, "")
        win.geometry(TOOL_SIZE)
        answer_file_dialog(mod, path)
        win.load_data()
        pump(root, 1)
        if len(win.layers) > 1:
            win.toggle_layer_visibility(1)
        pump(root, 2)
        ok = grab(win, out) and len(win.layers) >= 2

    elif name == "device":
        from scripts.Device import run_device
        win = run_device.AnalysisWindow(root, "")
        win.geometry(TOOL_SIZE)
        for k, p in write_device_inputs(tmp).items():
            win.paths[k].set(p)
        win.compute()
        pump(root, 30, until=lambda: getattr(win, "summary", None) is not None)
        pump(root, 2)
        ok = grab(win, out)

    elif name in PROJECT_RUNS:
        import importlib
        folder = {"sclc": "SCLC", "intensity": "Intensity", "trpl": "TRPL", "eis": "EIS", "cv": "CV",
                  "stability": "Stability"}[name]
        win = importlib.import_module(f"scripts.{folder}.run_{name}").AnalysisWindow(root, "")
        win.geometry(TOOL_SIZE)
        pump(root, 1)
        done = shot_curve_tool(name, win, tmp)
        pump(root, 2)
        ok = grab(win, out) and done

    elif name in ("trpl_irf", "eis_drt"):
        if name == "trpl_irf":
            from scripts.TRPL.run_trpl import AnalysisWindow
        else:
            from scripts.EIS.run_eis import AnalysisWindow
        win = AnalysisWindow(root, "")
        win.geometry(TOOL_SIZE)
        pump(root, 1)
        done = shot_view(name, win, tmp)
        pump(root, 2)
        ok = grab(win, out) and done

    elif name == "compare":
        from scripts.common.compare_window import CompareWindow
        files = [write_eqe(os.path.join(tmp, f"series_Br{int(round((eg - 1.55) * 200)):02d}_EQE.csv"), eg)
                 for eg in (1.55, 1.60, 1.65, 1.70)]
        win = CompareWindow(root, "eqe", files=files)
        win.geometry("1440x860+30+40")
        pump(root, 30, until=lambda: len(win.items) >= len(files))
        pump(root, 2)
        ok = grab(win, out) and len(win.items) >= len(files)

    elif name == "xps":
        from spectra.app import App
        from spectra.gui.tab_dashboard import SpectraDashboardTab
        root.destroy()
        app = App("XPS")
        app.geometry(TOOL_SIZE)

        def find(w):
            if isinstance(w, SpectraDashboardTab):
                return w
            for c in w.winfo_children():
                r = find(c)
                if r is not None:
                    return r
            return None
        pump(app, 1)
        tab = find(app)
        path = write_xps(os.path.join(tmp, "film_A_Pb4f.csv"))
        tab.file_path = path
        tab.ent_path.insert(0, path)
        tab._load_file(path)
        tab._refresh_buttons()
        tab.run_clicked()
        pump(app, 60, until=lambda: tab.fitted is not None)
        ok = grab(app, out) and tab.fitted is not None
        app.destroy()
        return ok

    try:
        win.destroy()
        root.destroy()
    except Exception:
        pass
    return ok


def main(outdir, names):
    os.makedirs(outdir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="physiscore_shots_")
    failed = []
    for name in names:
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--one", name, outdir, tmp])
        if r.returncode != 0:
            failed.append(name)
    print("failed:", failed if failed else "none")
    return not failed


if __name__ == "__main__":
    if "--one" in sys.argv:
        i = sys.argv.index("--one")
        name, outdir, tmp = sys.argv[i + 1], sys.argv[i + 2], sys.argv[i + 3]
        os.environ["PHYSISCORE_CONFIG"] = os.path.join(tmp, "settings.json")
        ok = shot_launcher(outdir, tmp, name) if name in LAUNCHER_VIEWS else shot_tool(name, outdir, tmp)
        sys.exit(0 if ok else 1)
    args = sys.argv[1:]
    out = args[0] if args and args[0] not in NAMES else os.path.join(ROOT, "docs", "images")
    sel = [a for a in args if a in NAMES] or list(NAMES)
    sys.exit(0 if main(out, sel) else 1)
