@echo off
:: ============================================================
::  build.bat  -  Build MovieCutDetector.exe for Windows
::  Run this once from the folder that contains both:
::    movie_cut_detector.py
::    movie_cut_detector_gui.py
:: ============================================================

echo.
echo  ===================================================
echo   Movie Cut Detector - Windows EXE Builder
echo  ===================================================
echo.

:: Check Python is on PATH
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found on PATH.
    echo  Install Python 3.10+ from https://python.org and ensure
    echo  "Add Python to PATH" is checked during install.
    pause & exit /b 1
)

echo  [1/4] Installing / upgrading required packages...
python -m pip install --upgrade plexapi requests python-dotenv colorama pyinstaller ^
    >pip_install.log 2>&1
if errorlevel 1 (
    echo  ERROR: pip install failed. See pip_install.log for details.
    pause & exit /b 1
)
echo        Done.
echo.

echo  [2/4] Cleaning previous build artefacts...
if exist build   rmdir /s /q build
if exist dist    rmdir /s /q dist
if exist __pycache__ rmdir /s /q __pycache__
echo        Done.
echo.

echo  [3/4] Compiling to EXE with PyInstaller...
echo        (this takes 30-90 seconds - please wait)
echo.

python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "MovieCutDetector" ^
    --add-data "movie_cut_detector.py;." ^
    --hidden-import plexapi ^
    --hidden-import plexapi.server ^
    --hidden-import plexapi.library ^
    --hidden-import requests ^
    --hidden-import dotenv ^
    --hidden-import colorama ^
    movie_cut_detector_gui.py ^
    >pyinstaller.log 2>&1

if errorlevel 1 (
    echo  ERROR: PyInstaller failed. See pyinstaller.log for details.
    pause & exit /b 1
)

echo.
echo  [4/4] Done!
echo.
echo  ===================================================
echo   Output:  dist\MovieCutDetector.exe
echo.
echo   Copy the .exe to any folder you like.
echo   On first run it will create a .env file next to
echo   itself to store your Plex and TMDb credentials.
echo  ===================================================
echo.

:: Open the dist folder automatically
explorer dist

pause
