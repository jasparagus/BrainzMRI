#!/bin/bash

# Set terminal title (works in most standard terminal emulators)
echo -ne "\033]0;BrainzMRI Launcher\007"

echo "============================================"
echo "   BrainzMRI Launcher"
echo "============================================"
echo ""

source venv/bin/activate.fish

# Prompt to install requirements with a 2-second timeout
# -t 2 sets the timeout to 2 seconds
# -n 1 accepts exactly 1 character of input
read -t 2 -n 1 -p "Run uv install for requirements.txt? [y/N]: " do_install
echo "" # Move to a new line after the prompt or timeout

# Check if the user pressed 'y' or 'Y'
if [[ "$do_install" =~ ^[Yy]$ ]]; then
    echo "Installing requirements..."
    uv pip install -r requirements.txt
    echo ""
else
    echo "Skipping requirements installation."
    echo ""
fi

python gui_main.py

# Equivalent to 'pause'
read -n 1 -s -r -p "Press any key to continue..."
echo ""
