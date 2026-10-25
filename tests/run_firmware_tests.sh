#!/bin/bash
# The board's finger logic, compiled for this computer with fake pins and fake Bluetooth.
# Needs a C++ compiler (on a Mac: xcode-select --install).
TESTS="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
{ echo '#include "Arduino.h"'; cat "$TESTS/../firmware/board_core/board_core.ino"; } > "$WORK/fw.cpp"
c++ -std=c++17 -I "$TESTS/firmware/stub" -I "$WORK" "$TESTS/firmware/test_fingers.cpp" -o "$WORK/test_fingers" || exit 1
"$WORK/test_fingers"
