# -*- mode: python ; coding: utf-8 -*-
# Physiscore v2 (JV-style unified launcher) build spec
# Build: pyinstaller Physiscore_v2.spec --noconfirm
import os

block_cipher = None

datas = [
    ("logo", "logo"),
    ("rawdata/am1.5g.xlsx", "rawdata"),
    ("scripts/EQE/astm_g173_global.csv", "scripts/EQE"),  # ASTM G173-03 full-resolution AM1.5G
    ("scripts/JV/jv_config.json", "scripts/JV"),
    ("scripts/Dark_JV/dark_jv_config.json", "scripts/Dark_JV"),
    ("scripts/SEM/sem_config.json", "scripts/SEM"),
    ("physisfera_config.json", "."),
]
datas = [(s, d) for (s, d) in datas if os.path.exists(s)]

hiddenimports = [
    "scripts", "scripts.JV.run_jv", "scripts.Dark_JV.run_jv_dark",
    "scripts.EQE.run_eqe", "scripts.SEM.run_sem", "scripts.Abs.run_abs",
    "scripts.Raman.run_raman", "scripts.FTIR.run_ftir",
    "scripts.XRD.run_xrd", "scripts.PL.run_pl",
    "scripts.common.analysis_shell", "scripts.common.plot_interactions",
    "scripts.common.sample_naming",
    "scripts.common.theme",
    "spectra.app",
    "win32com", "win32com.client",
    "google.generativeai",
    "PIL._tkinter_finder",
    "matplotlib.backends.backend_tkagg",
    "pybaselines", "lmfit", "pydantic",
]

a = Analysis(
    ["Physiscore_Launcher.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Physiscore",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Physiscore",
)
