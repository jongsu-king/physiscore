# PyInstaller spec for the installers (Windows, macOS, Linux): one-folder build,
# plus a .app bundle on macOS.   pyinstaller --noconfirm packaging/physiscore.spec
# (Physiscore_v2.spec / build_exe_v2.bat remain for the older Windows-only build.)
import os
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve().parent
VERSION = re.search(r'APP_VERSION = "([^"]+)"', (ROOT / "Physiscore_Launcher.py").read_text(encoding="utf-8")).group(1)
ICONS = ROOT / "packaging" / "icons"
icon = str(ICONS / ("app.ico" if sys.platform == "win32" else "app.icns")) if ICONS.exists() else None

datas = [(str(ROOT / "logo"), "logo")]
for src, dst in [
    ("scripts/EQE/astm_g173_global.csv", "scripts/EQE"),
    ("scripts/JV/jv_config.json", "scripts/JV"),
    ("scripts/Dark_JV/dark_jv_config.json", "scripts/Dark_JV"),
    ("scripts/SEM/sem_config.json", "scripts/SEM"),
]:
    if (ROOT / src).exists():
        datas.append((str(ROOT / src), dst))
datas += collect_data_files("customtkinter")

def package_modules(*packages):
    """Every module of the analysis packages, found on disk: the launcher imports
    the tools by name at run time, so PyInstaller cannot see them by itself."""
    names = []
    for pkg in packages:
        for path in sorted((ROOT / pkg).rglob("*.py")):
            rel = path.relative_to(ROOT).with_suffix("")
            parts = list(rel.parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if "__pycache__" not in parts:
                names.append(".".join(parts))
    return names


hiddenimports = (
    package_modules("scripts", "spectra")
    + ["selfupdate", "PIL._tkinter_finder", "matplotlib.backends.backend_tkagg",
       "pybaselines", "lmfit", "pydantic", "openpyxl", "xlrd"]
)
if sys.platform == "win32":
    hiddenimports += ["win32com", "win32com.client"]

a = Analysis(
    [str(ROOT / "Physiscore_Launcher.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "IPython", "PyQt5", "PyQt6", "PySide6", "_legacy"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Physiscore", console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="Physiscore")
if sys.platform == "darwin":
    app = BUNDLE(
        coll, name="Physiscore.app", icon=icon, bundle_identifier="io.github.jongsu-king.physiscore",
        version=VERSION,
        info_plist={"CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
                    "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "11.0",
                    "NSHumanReadableCopyright": "© 2026 H-MOL, Incheon National University. MIT License"},
    )
