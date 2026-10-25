#!/bin/bash
# The reader in Google Chrome (headless, its own empty profile), with a fake Gemini and made-up documents.
# Needs only Chrome: nothing to install.
TESTS="$(cd "$(dirname "$0")" && pwd)"
python3 -c "import sys; sys.path.insert(0, '$TESTS'); import cdp; sys.exit(0 if cdp.find_chrome() else 1)" ||
  { echo "Needs Google Chrome"; exit 1; }
WORK="$(mktemp -d)"
trap 'kill $FAKE $HUB 2>/dev/null; [ -z "$KEEP_WORK" ] && rm -rf "$WORK"' EXIT
cp -R "$TESTS/../hub" "$WORK/hub"
rm -rf "$WORK/hub/.env" "$WORK/hub/settings.json" "$WORK/hub/library" "$WORK/hub/__pycache__"
python3 "$TESTS/make_samples.py" "$WORK/samples"
command -v textutil >/dev/null && textutil -convert docx -output "$WORK/samples/essay.docx" "$WORK/samples/notes.txt"
cd "$WORK" || exit 1
python3 "$TESTS/fake_gemini.py" 9911 > fake_gemini.log 2>&1 &
FAKE=$!
cd "$WORK/hub" || exit 1
QUIET=1 GEMINI_URL=http://127.0.0.1:9911 GEMINI_API_KEY=test-key-1234567890abcdef \
  python3 "$TESTS/start_hub.py" --port 8123 --no-mic --no-browser > "$WORK/hub.log" 2>&1 &
HUB=$!
for i in $(seq 1 50); do curl -s -o /dev/null http://localhost:8123/ && break; sleep 0.2; done
echo "work: $WORK"; python3 "$TESTS/test_page.py" "$WORK"
result=$?
[ -n "$KEEP_SHOTS" ] && cp "$WORK/reader.png" "$WORK/phone.png" "$KEEP_SHOTS"/ 2>/dev/null
exit $result
