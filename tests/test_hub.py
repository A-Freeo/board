"""The hub without a browser: the board's key, one question per tap, look-ups, what's sent to Gemini,
bringing documents in, and voices. Run tests/run_hub_tests.sh."""
import asyncio, io, json, math, os, random, sys, threading, time
from array import array
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
os.environ["GEMINI_URL"] = "http://127.0.0.1:9922"
os.environ["GEMINI_API_KEY"] = "test-key-1234567890abcdef"
sys.path.insert(0, sys.argv[1])
SAMPLES = Path(sys.argv[2])
import board_hub as bh

fails = 0
def check(ok, what):
    global fails
    print(("PASS " if ok else "FAIL ") + what); fails += not ok

def tone(seconds, loud=True, rate=16000):
    return array("h", (int((6000 if loud else 40) * math.sin(2 * math.pi * 220 * i / rate)) for i in range(int(seconds * rate))))

async def feed(samples, step=320):
    for i in range(0, len(samples) - step + 1, step):
        bh.hub.heard_packet(samples[i:i + step])
    await asyncio.sleep(0)

def noise(seconds, level, spikes=0, rate=16000, seed=1):
    """Room sound: random noise around a level, with a louder packet now and then (spikes a second)."""
    rnd = random.Random(seed)
    out = array("h")
    for packet in range(int(seconds * 50)):
        loud = spikes and rnd.random() < spikes / 50
        out.extend(int(max(-32000, min(32000, rnd.gauss(0, level * (3 if loud else 1))))) for _ in range(320))
    return out

def chatter(seconds, level, seed=2):
    """People talking behind you: bursts of voice-like sound with gaps."""
    rnd, out = random.Random(seed), array("h")
    while len(out) < seconds * 16000:
        out.extend(tone(rnd.uniform(0.1, 0.5), loud=False) if rnd.random() < 0.3 else
                   array("h", (int(level * 1.4 * math.sin(2 * math.pi * rnd.choice((150, 190, 240)) * i / 16000)) for i in range(int(rnd.uniform(0.2, 0.6) * 16000)))))
    return out[:int(seconds * 16000)]

def mix(*parts):
    out = array("h", [0] * max(len(p) for p in parts))
    for p in parts:
        for i, v in enumerate(p):
            out[i] = max(-32000, min(32000, out[i] + v))
    return out

def cut(samples):
    """Feeds a Listener; returns (seconds in when it finished, seconds of sound) for each thing said."""
    listener, out = bh.Listener(), []
    for i in range(0, len(samples) - 319, 320):
        said = listener.add(samples[i:i + 320])
        if said:
            out.append((round((i + 320) / 16000, 2), round(len(said) / 16000, 2)))
    return out

def requests(kind=None):
    rows = [json.loads(l) for l in open("gemini.jsonl")]
    return [r for r in rows if kind is None or r.get("kind") == kind]

async def wait_for(test, seconds=5):
    for _ in range(int(seconds * 10)):
        if test(): return True
        await asyncio.sleep(0.1)
    return False

async def settle():
    await wait_for(lambda: hub.state == "off" and not hub.busy and not [t for t in hub.tasks if not t.done()], 8)

FAKE_KEYS = r"""
import time
print("trusted", flush=True)
time.sleep(0.3); print("F18 down", flush=True)
time.sleep(1.0); print("F18 down", flush=True)
time.sleep(5)
"""

class Site(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        if self.path == "/paper.pdf":
            body, kind = (SAMPLES / "lecture.pdf").read_bytes(), "application/pdf"
        else:
            body, kind = (SAMPLES / "reading.html").read_bytes(), "text/html; charset=utf-8"
        self.send_response(200); self.send_header("Content-Type", kind); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

hub = bh.hub

async def main():
    # 0. when you've stopped talking
    quiet = cut(tone(1.0, loud=False) + tone(1.5) + tone(3.0, loud=False))
    check(len(quiet) == 1 and 2.5 + 0.7 <= quiet[0][0] <= 2.5 + 1.0, "quiet room: he stops recording 0.8 s after you stop  " + str(quiet))
    fan = cut(mix(noise(6.0, 400, spikes=8), tone(1.0, loud=False) + tone(1.5)))
    check(len(fan) == 1 and fan[0][0] <= 2.5 + 1.3, "a noisy fan with bumps: he still stops soon after you do  " + str(fan))
    talkers = cut(mix(chatter(7.0, 900), tone(1.0, loud=False) + tone(1.5)))
    check(len(talkers) == 1 and talkers[0][0] <= 2.5 + 1.3, "people talking behind you: he still stops soon after you do  " + str(talkers))
    breath = cut(tone(0.5, loud=False) + tone(1.0) + tone(0.4, loud=False) + tone(1.0) + tone(2.0, loud=False))
    check(len(breath) == 1 and breath[0][1] >= 2.4, "a breath mid-sentence doesn't cut you off  " + str(breath))
    check(cut(tone(0.5, loud=False) + tone(0.1) + tone(2.0, loud=False)) == [], "a cough alone isn't a question")
    longest = cut(tone(0.5, loud=False) + tone(14.0))
    check(longest and longest[0][0] <= 0.5 + 12.5, "he never records for more than 12 s  " + str(longest))

    hub.mic.stream = object()
    real_speech = bh.speech_command
    bh.speech_command = lambda voice: None          # nothing is said out loud until the voice tests
    library = hub.library
    # 1. the key listener process: F18 turns Oswald on, the next F18 turns him off
    real_exec = asyncio.create_subprocess_exec
    async def fake_exec(program, flag, code, **kw):
        return await real_exec(sys.executable, "-c", FAKE_KEYS, **kw)
    asyncio.create_subprocess_exec = fake_exec
    hub.later(hub.listen_for_keys())
    ok = await wait_for(lambda: hub.talking, 3)
    check(ok and hub.keys == "everywhere" and hub.state == "listening", "F18 from the key listener turns Oswald on")
    await bh.api("/api/talk", {})
    check(hub.talking, "the page's F18 for the same press is ignored (no double toggle)")
    ok = await wait_for(lambda: not hub.talking, 3)
    check(ok and hub.state == "off", "the next F18 turns him off")
    asyncio.create_subprocess_exec = real_exec
    await wait_for(lambda: hub.keys == "page", 10)

    # 2. documents: files, a web page and a linked PDF
    for name in ("lecture.pdf", "reading.html", "notes.txt") + (("essay.docx",) if (SAMPLES / "essay.docx").exists() else ()):
        reply = await bh.upload(name, "", "", (SAMPLES / name).read_bytes())
        check(reply["ok"], "adds " + name)
    lecture = library.docs()[0]
    check(lecture["kind"] == "pdf" and library.path(lecture).read_bytes().startswith(b"%PDF"), "a PDF is kept as it is")
    reading = library.docs()[1]
    check(reading["title"] == "The Steam Age" and "alert" not in library.read(reading) and "<h2>" in library.read(reading),
          "a web page keeps its headings and title, and loses its scripts")
    if (SAMPLES / "essay.docx").exists():
        check("James Watt" in library.read(library.docs()[3]), "a Word file becomes a readable page")
    reply = await bh.upload("virus.exe", "", "", b"MZ....")
    check(not reply["ok"] and "PDF" in reply["answer"], "a file Board can't read is refused with a clear message")
    site = ThreadingHTTPServer(("127.0.0.1", 9944), Site)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    reply = await bh.api("/api/link", {"url": "http://127.0.0.1:9944/article"})
    check(reply["ok"] and reply["doc"]["kind"] == "page" and reply["doc"]["url"].endswith("/article"), "a link to a web page is added as a page")
    reply = await bh.api("/api/link", {"url": "http://127.0.0.1:9944/paper.pdf"})
    check(reply["ok"] and reply["doc"]["kind"] == "pdf", "a link to a PDF is added as a PDF")
    site.shutdown()
    texts = [t + ". " + "Every lecture page has a paragraph of words like this one, about engines and heat. " * 3 for t in [
             "Lecture 4 heat engines", "A heat engine turns heat into work", "The first law", "The second law: no engine turns all its heat into work",
             "Carnot efficiency", "Worked example", "Fire-tube boilers pass hot gas through tubes", "The governor", "Entropy", "Summary"]]
    await bh.api("/api/texts", {"doc": lecture["id"], "texts": texts})
    check(lecture["pages"] == 10 and library.texts(lecture)[3].startswith("The second law"), "the reader's page text is kept for each PDF page")

    # 3. tap, ask, he looks it up in the library, answers and turns off by himself
    await bh.api("/api/view", {"doc": lecture["id"], "page": 2, "pages": 10, "text": texts[1], "selection": "turns heat into work"})
    n = len(requests())
    hub.last_toggle = -1e9
    hub.key_toggle()
    await asyncio.sleep(0.2)
    await feed(tone(1.0, loud=False)); await feed(tone(1.2)); await feed(tone(1.0, loud=False))
    ok = await wait_for(lambda: len(requests()) >= n + 2 and hub.state == "off", 6)
    first, second = (requests()[n:] + [{}, {}])[:2]
    check(ok and first.get("kinds", [""])[0] == "audio/wav", "tap and ask: the recording goes to Gemini")
    check("On screen [{}p2]:\nA heat engine".format(lecture["id"]) in first.get("text", "") and 'Selected: "turns heat into work"' in first.get("text", ""),
          "with the page on screen and what's highlighted")
    check("Passages from their documents" not in first.get("text", ""), "a spoken question first goes without passages (none to search for yet)")
    check(second.get("kinds") == ["text"] and "[{}p4]".format(lecture["id"]) in second.get("text", ""),
          "Oswald asked to look it up: the hub finds the second-law page and asks again, as text")
    check(ok and not hub.talking, "after answering he turns off by himself")
    check(first.get("rules"), "Oswald is told he stops listening after each answer")
    check(all(r["chars"] < 6000 for r in requests("chat")) and first.get("kinds") == ["audio/wav", "text"], "every question stays small: no whole documents, under 6000 characters")
    check(first.get("thinking") == {"thinkingLevel": "minimal"}, "questions use minimal thinking")

    # 4. typed question while he's off, and Gemini being busy
    n = len(requests())
    result = hub.typed("overload test")
    ok = await wait_for(lambda: len(requests()) >= n + 2, 5)
    check(result["ok"] and ok and requests()[-1]["model"] != requests()[-2]["model"], "Gemini busy: the hub tries the next model")
    await settle()

    # 5. tap and say nothing: he gives up after WAIT_FOR_QUESTION; mid-sentence he waits
    bh.WAIT_FOR_QUESTION = 1.0
    hub.last_toggle = -1e9
    hub.key_toggle()
    await asyncio.sleep(0.3)
    check(hub.state == "listening", "a tap turns him on")
    await feed(tone(0.5, loud=False))
    ok = await wait_for(lambda: hub.state == "off", 3)
    check(ok and not hub.talking, "nothing asked: he turns off by himself")
    n = len(requests())
    hub.last_toggle = -1e9
    hub.key_toggle()
    await asyncio.sleep(0.2)
    await feed(tone(0.6, loud=False)); await feed(tone(1.5))
    await asyncio.sleep(1.6)
    check(hub.state == "listening", "still listening while you're mid-sentence, past the wait")
    await feed(tone(1.0, loud=False))
    ok = await wait_for(lambda: len(requests()) > n and hub.state == "off", 6)
    check(ok, "the late question still gets answered, then he's off")
    hub.last_toggle = -1e9
    hub.key_toggle()
    await asyncio.sleep(0.2)
    hub.last_toggle = -1e9
    hub.key_toggle()
    await asyncio.sleep(0.2)
    check(hub.state == "off" and not hub.talking, "tap again turns him off")

    # 6. KEEP_LISTENING = True: he keeps listening after he answers
    bh.KEEP_LISTENING = True
    n = len(requests())
    hub.last_toggle = -1e9
    hub.key_toggle()
    await asyncio.sleep(0.2)
    await feed(tone(1.0, loud=False)); await feed(tone(1.2)); await feed(tone(1.0, loud=False))
    ok = await wait_for(lambda: len(requests()) > n and hub.state == "listening" and not hub.busy, 8)
    check(ok and hub.talking, "KEEP_LISTENING: he keeps listening after he answers")
    check(not requests("chat")[-1]["rules"], "and isn't told he stops listening")
    hub.last_toggle = -1e9
    hub.key_toggle()
    await asyncio.sleep(0.2)
    bh.KEEP_LISTENING = False
    await settle()

    # 7. writing: notes from the lecture, attached to it, with the whole text sent once
    await hub.make("notes")
    notes = library.docs()[-1]
    writing = requests("write")[-1]
    check(notes["kind"] == "notes" and notes["parent"] == lecture["id"] and notes["sources"] == [lecture["id"]], "notes are written from the open lecture and attached to it")
    check("[{}p7]".format(lecture["id"]) in writing["all"] and writing["thinking"] == {"thinkingLevel": "low"}, "the writer gets every page, tagged, and thinks a little")
    await hub.make("guide", sources=[lecture["id"], reading["id"]])
    guide = library.docs()[-1]
    check(guide["kind"] == "guide" and guide["parent"] == "" and guide["sources"] == [lecture["id"], reading["id"]], "a study guide from two documents isn't attached to either")
    await hub.make("quiz")
    quiz = library.docs()[-1]
    check(quiz["kind"] == "quiz" and library.content(quiz)["answers"] == [None, None], "a quiz starts with nothing answered")
    cards = bh.tidy_cards({"cards": [{"front": "Quantifiers", "back": "($\x0corall x$) and ($\neg$) [d7s3, d2p3]\u8bde\u751f", "ref": "[d7s3]"}]})["cards"][0]
    check(cards["back"] == "($\\forall x$) and ($\\neg$)" and cards["ref"] == "d7s3",
          "flashcards: LaTeX that lost its backslash in the JSON is mended, tags and stray characters come out")
    check(hub.quiz_answer(quiz["id"], 0, 1) and library.content(quiz)["answers"][0] == 1, "an answer is kept")

    # 8. Oswald edits a note: append under a heading, replace words, revise
    library.write(notes, "# Notes\n\n## Engines\n- Heat to work\n\n## Boilers\n- Fire-tube\n")
    await hub.edit(notes["id"], "append", "Engines", "- Carnot limits efficiency")
    text = library.read(notes)
    check(text.index("Carnot") < text.index("## Boilers"), "append under a heading puts it at the end of that section")
    await hub.edit(notes["id"], "replace", "Fire-tube", "Fire-tube and water-tube")
    check("Fire-tube and water-tube" in library.read(notes), "replace swaps the exact words")
    await hub.edit(notes["id"], "revise", "", "Make it shorter")
    check(library.read(notes).startswith("# Notes\n\nShorter now."), "revise rewrites the note with Gemini")
    await hub.edit(lecture["id"], "append", "", "x")
    check(library.read(lecture) != "x" and library.path(lecture).read_bytes().startswith(b"%PDF"), "he can't edit a PDF")

    # 9. folders and the library
    hub.organize("Thermodynamics", [lecture["id"], reading["id"], reading["id"]])
    folder = library.folder(lecture["folder"])
    check(folder and folder["name"] == "Thermodynamics" and reading["folder"] == folder["id"], "organize makes a folder and moves documents in")
    check(notes["folder"] == folder["id"], "attached notes go with their document")
    listing = library.listing()
    check('Folder {} "Thermodynamics"'.format(folder["id"]) in listing and "attached to {}".format(lecture["id"]) in listing, "Oswald sees folders and attachments")
    check(library.place("{}p5".format(lecture["id"])) == {"doc": lecture["id"], "page": 5, "find": ""}, "a page tag points at the page")
    check(library.place("{}s2".format(reading["id"]))["find"].startswith("Part"), "a section tag points at the words that start it")
    check(library.place("d999") is None and library.place("nonsense") is None, "a made-up tag points nowhere")
    library.delete(folder["id"])
    check(lecture["folder"] == "" and library.doc(lecture["id"]), "deleting a folder keeps its documents")

    # 10. research, saved in a new note
    await hub.research("what about steam turbines", "steam turbines", "new")
    research = library.docs()[-1]
    check(research["title"].startswith("Research") and "https://example.com/turbine" in library.read(research), "research goes in a note with its sources")
    check(requests("research")[-1]["tools"] == [{"google_search": {}}], "research uses Google Search")

    # 11. a scanned PDF (no text): questions only send a picture of the page, notes get the whole file once
    scan = library.add("pdf", "Scan", (SAMPLES / "lecture.pdf").read_bytes())
    library.set_texts(scan, [""] * 10)
    await bh.api("/api/view", {"doc": scan["id"], "page": 1, "pages": 10, "text": ""})
    hub.clients.add(asyncio.Queue())
    real_snap = hub.take_snap
    async def snap():
        hub.snaps[99] = b"\xff\xd8fakejpeg"
        return hub.snaps.pop(99)
    hub.take_snap = snap
    hub.typed("what is this")
    await settle()
    check(requests("chat")[-1]["kinds"] == ["image/jpeg", "text"], "a question about a scanned page sends a picture of that page only")
    hub.take_snap = real_snap
    n = len(requests())
    await hub.make("notes")
    check(any(r.get("upload") == "data" and r.get("pdf") for r in requests()[n:]) and "file" in requests("write")[-1]["kinds"],
          "writing notes from it uploads the PDF once and sends it by reference")

    # 12. voices: the Mac's list, British first, and picking one
    listing = """Albert              en_US    # Hello! My name is Albert.
Daniel              en_GB    # Hello! My name is Daniel.
Eddy (English (UK)) en_GB    # Hello! My name is Eddy.
Jamie (Premium)     en_GB    # Hello! My name is Jamie.
Karen               en_AU    # Hello! My name is Karen.
Fiona               en-scotland # Hello! My name is Fiona.
Thomas              fr_FR    # Bonjour, je m'appelle Thomas.
"""
    bh.IS_MAC = True
    bh.speech_command = real_speech
    real_run, real_popen = bh.subprocess.run, bh.subprocess.Popen
    bh.subprocess.run = lambda *a, **k: type("Result", (), {"stdout": listing})()
    spoken = []
    class FakeSay:
        def __init__(self, command, **kw):
            spoken.append(command); self.stdin = io.BytesIO()
        def poll(self): return 0
        def terminate(self): pass
    bh.subprocess.Popen = FakeSay
    bh.find_voices()
    names = [name for name, _ in bh.mac_voices]
    check(names[:3] == ["Jamie (Premium)", "Daniel", "Eddy (English (UK))"], "British voices first, the best first")
    check("Albert" not in names and "Thomas" not in names and ("Fiona", "Scottish") in bh.mac_voices, "joke voices and other languages left out")
    check(hub.voice_name() == "Jamie (Premium)", "the best British voice is the default")
    ok = hub.pick_voice("Karen")
    await asyncio.sleep(0.5)
    check(ok and hub.voice_name() == "Karen" and bh.read_json(bh.SETTINGS_FILE, {}).get("voice") == "Karen", "picking a voice saves it")
    check(spoken and spoken[-1][-2:] == ["-v", "Karen"], "and he says something in it")
    check(not hub.pick_voice("Zarvox") and hub.voice_name() == "Karen", "a voice that isn't there can't be picked")
    check(bh.Hub().voice_name() == "Karen", "the pick is still there next time")
    bh.subprocess.run, bh.subprocess.Popen = real_run, real_popen
    check(bh.Library().doc(notes["id"])["title"] == notes["title"], "the library is still there next time")
    print("ALL PASSED" if not fails else "{} FAILED".format(fails))
    sys.exit(1 if fails else 0)

asyncio.run(main())
