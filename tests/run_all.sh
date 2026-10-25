#!/bin/bash
# Runs every test, against a fake Gemini: no key or internet needed.
# The page tests need Google Chrome (they drive it headless); they're skipped without it.
cd "$(dirname "$0")" || exit 1
failed=""
run() { echo "== $1"; bash "$2" || failed="$failed $1"; echo; }
run hub run_hub_tests.sh
run firmware run_firmware_tests.sh
if python3 -c "import cdp, sys; sys.exit(0 if cdp.find_chrome() else 1)"; then
  run page run_page_tests.sh
else
  echo "== page: skipped (needs Google Chrome)"
fi
if [ -n "$failed" ]; then echo "FAILED:$failed"; exit 1; fi
echo "Everything passed"
