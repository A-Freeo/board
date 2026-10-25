"""Starts the hub in the folder it's run from, for the browser tests.
QUIET=1: it never speaks out loud. FAKE_MAC=1: it acts as a Mac (with a fake `say` first in PATH)."""
import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())
import board_hub  # noqa: E402

if os.environ.get("QUIET"):
    board_hub.speech_command = lambda voice: None
if os.environ.get("FAKE_MAC"):
    board_hub.IS_MAC = True
sys.argv = ["board_hub.py"] + sys.argv[1:]
asyncio.run(board_hub.main())
