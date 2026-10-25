#!/bin/bash
# Double-click to start Board on a Mac. The first time: right-click this file, then Open.
cd "$(dirname "$0")/hub" || exit 1

if ! command -v python3 >/dev/null; then
  echo "Python 3 isn't installed. Get it from python.org, then double-click this again."
  read -r -p "Press Enter to close." _
  exit 1
fi

install() {
  python3 -c "import $1" 2>/dev/null && return
  echo "Setting up $1 (once)..."
  python3 -m pip install --quiet --user "$1" 2>/dev/null ||
    python3 -m pip install --quiet --break-system-packages "$1" ||
    echo "Couldn't install $1. Board still works, with a bit less (see the README)."
}
install sounddevice     # Oswald hears you through the laptop mic
install pynput          # asking Oswald from the board works in every app, not just the reader

python3 board_hub.py
