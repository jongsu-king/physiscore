# -*- mode: python ; coding: utf-8 -*-
# Physiscore 통합 exe 빌드 스펙 (PyInstaller)
# 빌드: pyinstaller Physiscore.spec --noconfirm
import os

block_cipher = None

datas = [
    ("logo", "logo"),                                   # 아이콘 이미지
    ("rawdata/am1.5g.xlsx", "rawdata"),                 # EQE Jsc 계산용 표준 스펙트럼
    ("scripts/EQE/astm_g173_global.csv", "scripts/EQE"),  # ASTM G173-03 full-resolution AM1.5G
    ("scripts/JV/jv_config.json", "scripts/JV"),
    ("scripts/Dark_JV/dark_jv_config.json", "scripts/Dark_JV"),
    ("scripts/SEM/sem_config.json", "scripts/SEM"),
    ("physisfera_config.json", "."),
]
# 존재하는 파일만 포함
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
    "pybaselines", "lmfit", "pydantic",   # spectra (XRD Pro / PL Pro) 의존성
]

a = Analysis(
    ["main gui_test3.py"],
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
    console=False,          # 콘솔창 숨김. 디버깅 시 True로
    icon=None,              # .ico 파일 있으면 경로 지정
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
