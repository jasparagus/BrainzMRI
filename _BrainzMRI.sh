#!/bin/bash

# Set terminal title (works in most standard terminal emulators)
echo -ne "\033]0;BrainzMRI Launcher\007"

echo "============================================"
echo "   BrainzMRI Launcher"
echo "============================================"
echo ""

# ------------------------------------------------------------------
# 1. Verify pyproject.toml exists (required by uv)
# ------------------------------------------------------------------
if [ ! -f "pyproject.toml" ]; then
    echo "[ERROR] pyproject.toml not found in $(pwd)."
    echo "        This file is required to build the virtual environment."
    echo "        Please restore it from version control (e.g., git checkout pyproject.toml)."
    echo ""
    read -n 1 -s -r -p "Press any key to exit..."
    echo ""
    exit 1
fi

# ------------------------------------------------------------------
# 2. Check for system Tk package (required for scalable fonts)
# ------------------------------------------------------------------
# Try to import tkinter with the system Python. If it fails, the
# system Tk bindings are missing and fonts will not scale.
SYSTEM_PYTHON=$(command -v python3 || command -v python)

if [ -z "$SYSTEM_PYTHON" ]; then
    echo "[ERROR] No system Python found on PATH."
    echo "        BrainzMRI requires Python 3.13+ with Tkinter support."
    echo ""
    read -n 1 -s -r -p "Press any key to exit..."
    echo ""
    exit 1
fi

# Test that tkinter is importable
if ! "$SYSTEM_PYTHON" -c "import tkinter" 2>/dev/null; then
    echo "[ERROR] Tkinter is not available in your system Python ($SYSTEM_PYTHON)."
    echo ""
    echo "        Install the Tk package for your distribution:"
    echo "          Arch/Manjaro:    sudo pacman -S tk"
    echo "          Debian/Ubuntu:   sudo apt install python3-tk"
    echo "          Fedora:          sudo dnf install python3-tkinter"
    echo "          openSUSE:        sudo zypper install python3-tk"
    echo ""
    read -n 1 -s -r -p "Press any key to exit..."
    echo ""
    exit 1
fi

# Test that scalable fonts are available (not just the bitmap 'fixed' font)
FONT_COUNT=$("$SYSTEM_PYTHON" -c "
import tkinter as tk
import tkinter.font as tkfont
r = tk.Tk()
r.withdraw()
print(len(tkfont.families()))
r.destroy()
" 2>/dev/null)

if [ "$FONT_COUNT" = "1" ] || [ -z "$FONT_COUNT" ]; then
    echo "[WARNING] Tkinter can only see 1 font family (the bitmap 'fixed' font)."
    echo "          Font scaling will not work. This usually means the Tk library"
    echo "          was compiled without Xft/Freetype support."
    echo ""
    echo "          To fix, install the system Tk package:"
    echo "            Arch/Manjaro:    sudo pacman -S tk"
    echo "            Debian/Ubuntu:   sudo apt install python3-tk tk-dev"
    echo "            Fedora:          sudo dnf install tk"
    echo ""
    read -p "          Continue anyway? [y/N] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# ------------------------------------------------------------------
# 3. Sync the virtual environment using system Python
# ------------------------------------------------------------------
# Force uv to prefer the system Python over its own managed builds.
# Managed/standalone Python builds often lack Xft/Fontconfig linkage,
# which breaks Tkinter font rendering on Linux.
export UV_PYTHON_PREFERENCE="system"

echo "Syncing virtual environment..."
if ! uv sync --python-preference only-system; then
    echo ""
    echo "[ERROR] uv sync failed. Check the output above for details."
    echo ""
    read -n 1 -s -r -p "Press any key to exit..."
    echo ""
    exit 1
fi

# ------------------------------------------------------------------
# 4. Launch the application
# ------------------------------------------------------------------
uv run python gui_main.py

# Equivalent to 'pause'
read -n 1 -s -r -p "Press any key to continue..."
echo ""
