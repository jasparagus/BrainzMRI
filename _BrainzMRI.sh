#!/bin/bash

# Set terminal title (works in most standard terminal emulators)
echo -ne "\033]0;BrainzMRI Launcher\007"

echo "============================================"
echo "   BrainzMRI Launcher"
echo "============================================"
echo ""

uv sync
uv run python gui_main.py

# Equivalent to 'pause'
read -n 1 -s -r -p "Press any key to continue..."
echo ""
