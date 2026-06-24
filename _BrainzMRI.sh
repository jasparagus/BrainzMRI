#!/bin/bash

# Set terminal title (works in most standard terminal emulators)
echo -ne "\033]0;BrainzMRI Launcher\007"

echo "============================================"
echo "   BrainzMRI Launcher"
echo "============================================"
echo ""

# FORCE SYSTEM PYTHON ON LINUX
# Standalone Python builds often lack Xft/Fontconfig support for Tkinter.
# By forcing the system Python, we ensure fonts scale and render correctly.
export UV_PYTHON_PREFERENCE="system"

# Create a fresh environment with system Python and install all dependencies from pyproject.toml
uv sync --python system

uv run python gui_main.py

# Equivalent to 'pause'
read -n 1 -s -r -p "Press any key to continue..."
echo ""
