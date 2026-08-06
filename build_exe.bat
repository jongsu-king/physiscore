@echo off
REM ============================================
REM  Physiscore unified exe build script
REM  Output: dist\Physiscore\Physiscore.exe
REM  (ASCII only - do not add Korean text here,
REM   cmd reads .bat files in OEM codepage)
REM ============================================
cd /d "%~dp0"
set PY=C:\Users\DESKTOP\AppData\Local\Programs\Python\Python313\python.exe

echo [1/3] Installing dependencies...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [2/3] Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] Running PyInstaller...
"%PY%" -m PyInstaller Physiscore.spec --noconfirm
if errorlevel 1 goto :fail

echo.
echo BUILD OK: dist\Physiscore\Physiscore.exe
echo Distribute the whole dist\Physiscore folder (onedir mode).
pause
exit /b 0

:fail
echo.
echo BUILD FAILED. Check the error message above.
pause
exit /b 1
