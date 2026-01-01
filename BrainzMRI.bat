@echo off
title BrainzMRI Launcher

echo ============================================
echo   BrainzMRI Launcher
echo ============================================
echo.
echo   1. Run ParseListens (CLI mode)
echo   2. Run BrainzMRI GUI
echo.
echo   (Default = GUI in 5 seconds)
echo.

choice /C 12 /N /T 3 /D 2 >nul

if errorlevel 2 goto GUI
if errorlevel 1 goto CLI

:CLI
echo Starting ParseListens CLI...
python ParseListens.py
goto end

:GUI
echo Starting BrainzMRI GUI...
python BrainzMRI_GUI.py
goto end

:end