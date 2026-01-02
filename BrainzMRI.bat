@echo off
title BrainzMRI Launcher

echo ============================================
echo   BrainzMRI Launcher
echo ============================================
echo.
echo   1. Run BrainzMRI GUI
echo   2. Run ParseListens (CLI mode)
echo.
echo   (Default = GUI in 3 seconds...)
echo.

choice /C 12 /N /T 3 /D 1 >nul

if errorlevel 2 goto CLI
if errorlevel 1 goto GUI

:CLI
echo Starting ParseListens CLI...
python ParseListens.py
goto end

:GUI
echo Starting BrainzMRI GUI...
python BrainzMRI_GUI.py
goto end


:end
pause
