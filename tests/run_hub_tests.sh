#!/bin/bash
# The hub's tests (Python only): the board's key, one question per tap, look-ups, what goes to Gemini,
# documents, notes, quizzes, folders, research and voices.
# Uses a copy of hub/ and a fake Gemini, so your key, library and voice pick aren't touched.
TESTS="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
trap 'kill $FAKE 2>/dev/null; rm -rf "$WORK"' EXIT
cp -R "$TESTS/../hub" "$WORK/hub"
rm -rf "$WORK/hub/.env" "$WORK/hub/settings.json" "$WORK/hub/library" "$WORK/hub/__pycache__"
python3 "$TESTS/make_samples.py" "$WORK/samples"
command -v textutil >/dev/null && textutil -convert docx -output "$WORK/samples/essay.docx" "$WORK/samples/notes.txt"
cd "$WORK" || exit 1
python3 "$TESTS/fake_gemini.py" 9922 > fake_gemini.log 2>&1 &
FAKE=$!
sleep 1
python3 "$TESTS/test_hub.py" "$WORK/hub" "$WORK/samples"
