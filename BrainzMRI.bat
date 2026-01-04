@echo off
title BrainzMRI Launcher

echo ============================================
echo   BrainzMRI Launcher
echo ============================================
echo.
echo   1. Run BrainzMRI GUI
echo   2. Debug
echo.
echo   (Default = GUI, opening in 1 second...)
echo.

choice /C 12 /N /T 1 /D 1 >nul

if errorlevel 2 goto DEBUG
if errorlevel 1 goto GUI

:DEBUG
echo Starting ParseListens DEBUG...
python parsing.py
goto end

:GUI
echo Starting BrainzMRI GUI...
python gui.py
goto end


:end
pause
