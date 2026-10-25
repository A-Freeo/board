"""The reader in a real Chrome, with a fake Gemini and made-up study documents. Run tests/run_page_tests.sh.
python3 test_page.py <work folder with hub/, samples/ and gemini.jsonl>"""
import json, sys, time
from pathlib import Path
from cdp import Browser

WORK = Path(sys.argv[1])
URL = "http://localhost:8123/"
fails = 0


def check(ok, what):
    global fails
    print(("PASS " if ok else "FAIL ") + what)
    fails += not ok


def requests(kind=None):
    lines = [json.loads(l) for l in (WORK / "gemini.jsonl").read_text().splitlines() if l.startswith("{")]
    return [r for r in lines if kind is None or r.get("kind") == kind]


def library():
    return json.loads((WORK / "hub/library/library.json").read_text())


def until(test, seconds=8):
    for _ in range(int(seconds * 10)):
        try:
            if test():
                return True
        except (OSError, ValueError, KeyError, TypeError, StopIteration):
            pass
        time.sleep(0.1)
    return False


def doc_named(words):
    return next((d for d in library()["docs"] if words in d["title"]), None)


b = Browser()
js, wait = b.js, b.wait
counter = lambda: js("document.getElementById('counter').textContent")
title = lambda: js("document.getElementById('docTitle').textContent")


def ask(question):
    n = len(requests("chat"))
    js("document.getElementById('question').value = " + json.dumps(question))
    b.click("#ask button")
    for _ in range(80):
        if len(requests("chat")) > n and js("!document.getElementById('talk').classList.contains('thinking')"):
            break
        time.sleep(0.1)
    time.sleep(0.4)
    return requests("chat")[-1]


try:
    # 1. the reader opens, empty
    b.go(URL)
    check(wait("document.getElementById('aiLamp').textContent.includes('Oswald')"), "the reader loads and finds the hub")
    check(js("!document.getElementById('welcome').hidden") and counter() == "— / —", "an empty library shows the welcome")

    # 2. a PDF: pages, text you can select, Page Down and Page Up
    b.upload("#fileInput", [str(WORK / "samples/lecture.pdf")])
    check(wait("!!document.querySelector('#pdfSheet canvas') && document.getElementById('counter').textContent === 'Page 1 / 10'", 10), "a PDF opens on page 1 of 10")
    check(wait("document.querySelectorAll('.textLayer span').length > 1"), "the PDF has a text layer, so you can highlight words")
    b.key("PageDown"); b.key("PageDown")
    check(wait("document.getElementById('counter').textContent === 'Page 3 / 10'"), "Page Down (index finger) turns two pages")
    b.key("PageUp")
    check(wait("document.getElementById('counter').textContent === 'Page 2 / 10'"), "Page Up (lower index pad) turns back")
    check(until(lambda: doc_named("lecture")["pages"] == 10 and doc_named("lecture")["chars"] > 300), "the PDF's text reached the hub, all 10 pages")
    lecture = doc_named("lecture")["id"]

    # 3. what's on screen goes with the question, but not the whole library
    question = ask("how do engines work")
    check("On screen [{}p2]".format(lecture) in question["text"] and "What a heat engine does" in question["text"], "Oswald gets the page on screen")
    check("Carnot efficiency" not in question["text"] or "[{}p5]".format(lecture) in question["text"], "other pages only come as matching passages")
    check(wait("document.querySelectorAll('.slip.oswald').length === 1"), "his answer shows in the chat")

    # 4. a long web page is laid out as pages too
    b.upload("#fileInput", [str(WORK / "samples/reading.html")])
    check(wait("!document.getElementById('flowSheet').hidden && /^Page 1 \\/ \\d+$/.test(document.getElementById('counter').textContent)", 10), "a web page file opens as pages")
    pages = int(counter().split("/")[1])
    check(pages >= 3 and title() == "The Steam Age", "a long page is cut into {} pages, titled from the page".format(pages))
    check(js("!document.getElementById('flow').innerHTML.includes('alert') && !document.getElementById('flow').innerHTML.includes('Home | About')"), "scripts and menus are stripped out")
    b.key("PageDown")
    check(wait("document.getElementById('counter').textContent.startsWith('Page 2 /') && document.getElementById('flow').scrollLeft > 100"), "Page Down turns its page")
    full = sum(len(t) for t in json.loads((WORK / "hub/library/text/{}.json".format(doc_named("Steam Age")["id"])).read_text()))
    question = ask("what were mill boilers like")
    check(question["chars"] < 6000 and full > 9000, "a question sends {} characters, not the whole {}-character library".format(question["chars"], full))
    check("Mill boilers were fire-tube boilers" in question["text"] or "Boilers in mills" in question["text"], "the passage that answers it is found and sent")

    # 5. Word and text files
    b.upload("#fileInput", [str(WORK / "samples/essay.docx"), str(WORK / "samples/notes.txt")])
    check(wait("document.getElementById('docTitle').textContent === 'notes'", 10) and doc_named("essay"), "a Word file and a text file are added")
    check(wait("document.getElementById('flow').textContent.includes('James Watt')"), "the text file reads as pages")

    # 6. notes written by Oswald, attached to the lecture, with page links
    b.click(".docLink")
    wait("document.getElementById('docTitle').textContent === 'lecture'")
    b.click("[data-make=notes]")
    check(wait("document.getElementById('docTitle').textContent === 'lecture: Notes'", 10), "Notes: Oswald writes notes and opens them")
    notes = doc_named("lecture: Notes")
    check(notes and notes["parent"] == lecture and notes["kind"] == "notes", "the notes are attached to the lecture")
    check(js("document.querySelector('#tree .item.active').closest('ul').closest('li').querySelector('.title').textContent") == "lecture", "they sit under the lecture in the library")
    writing = requests("write")[-1]
    check(writing["chars"] > 500 and "[{}p1]".format(lecture) in writing["all"], "writing the notes sends the lecture's text, with page tags")
    check(js("document.querySelector('#flow .cite').textContent") == "p. 1", "a page tag in the notes shows as a page link")
    check(js("document.querySelectorAll('#flow .cite').length === 2 && !/\\[d\\d/.test(document.getElementById('flow').innerText)"), "a group of tags like [d1p1, d1p2] shows as two links")
    check(js("document.getElementById('stage').scrollWidth <= document.getElementById('stage').clientWidth + 1"), "nothing on later pages sticks out sideways")
    check(js("!document.querySelector('#flow em') && (!window.katex || !!document.querySelector('#flow .katex'))"), "maths in the notes is drawn as maths")
    b.click("#flow .cite")
    check(wait("document.getElementById('docTitle').textContent === 'lecture' && document.getElementById('counter').textContent === 'Page 1 / 10'"), "the page link opens the lecture at that page")

    # 7. Oswald changes the notes while you watch
    js("[...document.querySelectorAll('.docLink')].find(n => n.textContent.includes('lecture: Notes')).click()")
    wait("document.getElementById('docTitle').textContent === 'lecture: Notes'")
    ask("add a note about boilers")
    check(wait("document.getElementById('flow').textContent.includes('Boilers make steam')", 6), "Oswald adds to the open note and it updates live")
    check(js("!!document.querySelector('#flow .fresh')"), "the new line is lit up")
    ask("rewrite it shorter")
    check(wait("document.getElementById('flow').textContent.includes('Shorter now')", 6), "he can rewrite a note")

    # 8. editing a note yourself
    b.click("#editNote")
    check(wait("!document.getElementById('editSheet').hidden"), "Edit opens the note as markdown")
    js("document.getElementById('editText').value = '# Mine\\n\\n- **Bold** point'")
    b.click("#saveEdit")
    check(wait("document.querySelector('#flow strong')?.textContent === 'Bold'"), "Save shows your version")
    check("**Bold**" in (WORK / "hub/library/files" / notes["file"]).read_text(), "and keeps it on the laptop")

    # 9. a quiz: click or say the answer, page through the questions
    b.click(".docLink")
    wait("document.getElementById('docTitle').textContent === 'lecture'")
    b.click("[data-make=quiz]")
    check(wait("document.getElementById('docTitle').textContent === 'lecture: Quiz' && document.getElementById('counter').textContent === 'Q 1 / 2'", 10), "Quiz me: a quiz opens on question 1")
    js("document.querySelectorAll('.choices button')[1].click()")
    check(wait("!!(document.querySelector('.choices .right') && document.querySelector('.why'))") and not js("document.getElementById('quizSheet').textContent.includes('null')"), "picking an answer shows if it's right, and why")
    b.key("PageDown")
    check(wait("document.getElementById('counter').textContent === 'Q 2 / 2'"), "Page Down goes to the next question")
    ask("the answer is b")
    check(wait("!!document.querySelector('.choices .wrong')"), "saying the letter answers it (B was wrong here)")
    b.key("PageDown")
    check(wait("document.querySelector('.score')?.textContent === '1 / 2'"), "the last page is the score")

    # 10. flashcards: Page Down turns the card over, then the next card
    b.click(".docLink")
    wait("document.getElementById('docTitle').textContent === 'lecture'")
    b.click("[data-make=cards]")
    check(wait("document.getElementById('counter').textContent === 'Card 1 / 2'", 10), "Flashcards open on card 1")
    b.key("PageDown")
    check(wait("document.querySelector('#cardSheet .face').textContent === 'Makes steam.'"), "Page Down turns the card over")
    b.key("PageDown")
    check(wait("document.getElementById('counter').textContent === 'Card 2 / 2' && document.querySelector('#cardSheet .face').textContent === 'Governor'"), "then goes to the next card")
    b.key("PageDown")
    check(wait("!!document.querySelector('#cardSheet .face strong')") and js("!window.katex || !!document.querySelector('#cardSheet .face .katex')") and
          not js("document.querySelector('#cardSheet .face .katex-error')"), "a card's bold and maths are drawn, even maths whose backslash Gemini lost")

    # 11. folders
    ask("put the lecture and the reading in a folder")
    check(wait("[...document.querySelectorAll('.folder summary .name')].some(n => n.textContent === 'Thermodynamics')", 6), "Oswald makes a folder and files documents in it")
    lib = library()
    folder = next(f for f in lib["folders"] if f["name"] == "Thermodynamics")
    check(doc_named("lecture: Notes")["folder"] == folder["id"], "attached notes move with their document")
    b.click("#newFolder")
    js("document.getElementById('nameInput').value = 'Lecture 5'")
    js("document.querySelector('#nameForm button.brass').click()")
    check(wait("[...document.querySelectorAll('.folder summary .name')].some(n => n.textContent === 'Lecture 5')"), "New folder makes a folder")
    b.click("#arrangeDoc")
    js("const s = document.getElementById('arrangeFolder'); s.value = [...s.options].find(o => o.text === 'Lecture 5').value; s.onchange()")
    js("document.querySelector('#arrangeForm button.brass').click()")
    folder5 = lambda: next(f["id"] for f in library()["folders"] if f["name"] == "Lecture 5")
    check(until(lambda: doc_named("lecture: Flashcards")["folder"] == folder5()), "Arrange moves a document to another folder")

    # 12. web research, kept in a note with its sources
    ask("research steam turbines for me")
    check(wait("[...document.querySelectorAll('.slip.oswald')].some(s => s.textContent.includes('Steam turbines spin'))", 6), "research answers in the chat")
    check(js("!!document.querySelector('.slip .sources a[href=\"https://example.com/turbine\"]')"), "with its sources as links")
    check(wait("document.getElementById('docTitle').textContent.startsWith('Research')", 6) and "example.com/turbine" in
          (WORK / "hub/library/files" / doc_named("Research")["file"]).read_text(), "and saved in a research note")
    check(requests("research")[-1]["tools"] == [{"google_search": {}}], "research uses Google Search")

    # 13. the board's Oswald key works on the page
    b.key("F18")
    check(wait("document.getElementById('talk').classList.contains('listening')"), "F18 (ring finger) turns Oswald on")
    b.key("Escape")
    time.sleep(0.6)
    b.key("F18")
    check(wait("!document.getElementById('talk').classList.contains('listening')"), "F18 again turns him off")

    # 14. deleting
    b.click("#arrangeDoc")
    b.click("#deleteDoc"); b.click("#deleteDoc")
    check(wait("document.getElementById('docTitle').textContent === 'No document open'"), "Delete (pressed twice) removes the open document")

    b.screenshot(str(WORK / "reader.png"))
    check(not b.errors, "no errors on the page" + (": " + "; ".join(b.errors) if b.errors else ""))
finally:
    b.close()

phone = Browser(390, 844, port=9334)
try:
    phone.go(URL)
    phone.wait("document.querySelectorAll('.docLink').length > 2")
    check(phone.js("document.documentElement.scrollWidth <= window.innerWidth + 1"), "on a phone-sized screen nothing runs off the side")
    phone.screenshot(str(WORK / "phone.png"))
finally:
    phone.close()

# with the laptop mic the hub records the question, and Chrome only shows the words live
LAPTOP_MIC = """
window.heardPosts = 0;
window.SpeechRecognition = window.webkitSpeechRecognition = class { start() { window.fakeRec = this; } abort() { this.aborted = true; } };
navigator.mediaDevices.getUserMedia = async () => ({ getTracks: () => [] });
const realFetch = window.fetch;
window.fetch = (url, options) => { if (String(url).includes('/api/heard')) heardPosts++; return realFetch(url, options); };
const RealSource = window.EventSource;
window.EventSource = class extends RealSource {
  set onmessage(handler) {
    super.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.talk) m.talk.mic = 'laptop';
      if (m.kind === 'talk') m.mic = 'laptop';
      handler({ data: JSON.stringify(m) });
    };
  }
};
"""
mic = Browser(port=9335)
try:
    mic.send("Page.addScriptToEvaluateOnNewDocument", source=LAPTOP_MIC)
    mic.go(URL)
    mic.wait("document.querySelectorAll('.docLink').length > 2")
    mic.key("F18")
    note = lambda: mic.js("document.getElementById('note').textContent")
    said = lambda results: mic.js("fakeRec.onresult({ resultIndex: 0, results: %s.map(([t, f]) => Object.assign([{ transcript: t }], { isFinal: f })) })"
                                  % json.dumps(results))
    check(mic.wait("!!window.fakeRec"), "laptop mic: Chrome listens along to show the words")
    said([["what is", False]])
    check(note() == "Hearing: what is", "the words show while you talk")
    said([["what is entropy", True], ["in a turbine", False]])
    check(note() == "Hearing: what is entropy in a turbine", "and keep showing after Chrome settles part of the sentence")
    time.sleep(1)
    check(mic.js("heardPosts === 0 && !fakeRec.aborted"), "the hub's recording asks the question, not Chrome")
    mic.key("Escape")
    time.sleep(0.6)
    mic.key("F18")
    check(mic.wait("!document.getElementById('talk').classList.contains('listening')") and note() == "",
          "the words clear when he stops listening")
    check(not mic.errors, "no errors on the page" + (": " + "; ".join(mic.errors) if mic.errors else ""))
finally:
    mic.close()
print("ALL PASSED" if not fails else "{} FAILED".format(fails))
sys.exit(1 if fails else 0)
