#!/usr/bin/env python3
"""
Board hub: the study reader and Oswald, on the laptop. The board is just a Bluetooth keyboard:
the index tip and the pad lower down the index type Page Down and Page Up (they turn the
reader's pages), and the ring finger types F18, which asks Oswald a question. This listens for F18.

    python3 board_hub.py          start (the reader opens at http://localhost:8000)

The library holds PDFs, Word and Pages files, slides, web pages and the notes, study guides,
quizzes and flashcards Oswald writes, in folders. Oswald hears you through the laptop mic,
answers out loud, and only sends Gemini the bits of your documents a question needs.
You can also type a question in this window.
"""

import argparse
import asyncio
import base64
import getpass
import hashlib
import html
import io
import json
import math
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
import webbrowser
import zipfile
from array import array
from collections import Counter, deque
from html.parser import HTMLParser
from pathlib import Path

VERSION = "3.0"
HERE = Path(__file__).resolve().parent
LIBRARY = HERE / "library"
FILES = LIBRARY / "files"
TEXTS = LIBRARY / "text"
LIBRARY_FILE = LIBRARY / "library.json"
UPLOADS_FILE = LIBRARY / "uploaded.json"
SETTINGS_FILE = HERE / "settings.json"
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")

GEMINI_URL = os.environ.get("GEMINI_URL", "https://generativelanguage.googleapis.com")


# =====================================================================
# Settings. Change these freely.
# =====================================================================

ASSISTANT_NAME = "Oswald"
VOICES = ["Jamie (Premium)", "Jamie (Enhanced)", "Daniel (Enhanced)", "Oliver (Enhanced)", "Daniel"]   # British, best first. Or pick one on the page
SPEAKING_RATE = 185             # words a minute
KEEP_LISTENING = False          # False: one question per tap, then he turns off. True: he listens until you tap him off
WAIT_FOR_QUESTION = 8           # seconds he waits after a tap for you to start talking
QUICK_ANSWERS = True            # Oswald answers without thinking it over first. Much faster
OPEN_PAGE = True                # open the reader in the browser when the hub starts

# How much of your documents goes with each question. Less is cheaper and faster.
PAGE_CHARS = 3000               # the page on screen
NOTE_CHARS = 8000               # the whole note on screen, when it's one Oswald can edit
PASSAGES = 4                    # passages from your other pages that match the question
PASSAGE_CHARS = 700
SOURCE_CHARS = 150_000          # everything sent when he writes notes, a guide or a quiz
HISTORY_TURNS = 6


# =====================================================================
# Oswald's rules. His personality is in oswald.txt.
# =====================================================================

AI_RULES = (
    "The user is studying with Board: a reader on their laptop that holds their documents (PDFs, slides, "
    "web pages, Word files, and the notes and quizzes you write) in folders, and a controller on their "
    "hand that turns the pages. They talk to you and the laptop reads your answer out loud.\n"
    "answer is one to three short spoken sentences, with no lists, symbols, emoji or markdown. When a "
    "longer explanation would really help (steps, a formula, a worked example), put it in detail as short "
    "markdown: it's shown, not read out. Write maths in detail as LaTeX between $ signs.\n"
    "Answer from their documents. Every passage has a tag like [d1p5] (document d1, page 5) or [d4s2] "
    "(document d4, section 2). Put the tags you used in cites. When they ask to see or go to something, "
    "set go to its tag, or to a document id. If their documents don't cover it, say so, then answer from "
    "what you know and say that's what it is.\n"
    "Selected is text they highlighted: \"this\" usually means it.\n"
    "You can work in their library. make writes a new document of a kind (notes, guide, summary, quiz, "
    "cards) from sources (document ids, the open one if they don't say), attached to a document and in a "
    "folder (an id or a new name) when that fits. edit changes a notes, guide or summary document: how is "
    "append (text goes at the end, or under the heading named in find), replace (the exact words in find "
    "become text) or revise (text says what to change). organize puts documents in a folder (an id, or a "
    "name for a new one). For make and revise just say briefly what you're doing: it appears when written.\n"
    "search looks something up on the web. Use it only when they ask for research, recent facts or "
    "something their documents can't cover. save_to is a note id, or \"new\", when they want it kept.\n"
    "look_up: if the answer may be in their other documents but isn't in what you were sent, leave answer "
    "empty and set look_up to a few search words.\n"
    "When a quiz is open, quiz_choice is the option they pick for the question on screen (1 for A to 4 "
    "for D): tell them whether it's right and why. Never give an answer away before they choose."
)

REPLY_RULES = ("Reply in JSON. heard is exactly what the user said (empty if the recording is only noise or "
               "isn't meant for you). Leave out every other field you don't need.")

ONE_QUESTION_RULE = ("You stop listening after each answer, so don't end with an offer or a question like "
                     "\"anything else?\". If you need to know something before you can answer, ask it.")

STRING = {"type": "STRING"}
STRINGS = {"type": "ARRAY", "items": STRING}
KINDS = ["notes", "guide", "summary", "quiz", "cards"]

REPLY_SCHEMA = {
    "type": "OBJECT",
    "required": ["heard", "answer"],
    "properties": {
        "heard": STRING,
        "answer": STRING,
        "detail": STRING,
        "cites": STRINGS,
        "go": STRING,
        "look_up": STRING,
        "make": {"type": "OBJECT", "required": ["kind"], "properties": {
            "kind": {"type": "STRING", "enum": KINDS}, "title": STRING, "sources": STRINGS,
            "about": STRING, "attach_to": STRING, "folder": STRING}},
        "edit": {"type": "OBJECT", "required": ["doc", "how", "text"], "properties": {
            "doc": STRING, "how": {"type": "STRING", "enum": ["append", "replace", "revise"]},
            "find": STRING, "text": STRING}},
        "search": {"type": "OBJECT", "required": ["query"], "properties": {"query": STRING, "save_to": STRING}},
        "organize": {"type": "OBJECT", "required": ["folder", "docs"], "properties": {"folder": STRING, "docs": STRINGS}},
        "quiz_choice": {"type": "INTEGER"},
    },
}

WRITE_RULES = (
    "You write study material for a student from their sources. Use only the sources unless the request "
    "says otherwise. Every passage of the sources starts with a tag like [d1p5]: after a fact, cite where "
    "it's from with that tag in square brackets. Write maths as LaTeX between $ signs ($$ for a formula on its own "
    "line). Plain, clear British English. No introduction or sign-off."
)

CARD_FORMAT = (" Put a tag only in ref, written like d1p5 with no brackets, never in the other fields. Wrap all "
               "maths in $ signs. The reply is JSON, so write every LaTeX backslash twice, like \\\\forall.")

WRITE_KINDS = {
    "notes": "Write study notes in markdown that follow the order of the sources: a ## heading for each topic, "
             "short bullet points, key terms in bold with their meaning, and the worked examples the sources have.",
    "guide": "Write a study guide in markdown with these sections: ## Overview (two or three sentences), "
             "## Key terms (**term**: meaning), ## Main ideas (grouped by topic), ## Easy to mix up, "
             "## Practice questions (five), and ## Answers.",
    "summary": "Write a one-page summary in markdown: a short overview paragraph, then the main points as bullets.",
    "quiz": "Write a multiple-choice quiz of 8 questions that test understanding, not just recall. Each has four "
            "choices, answer is the index of the right one (0 to 3), why is one sentence on why it's right, "
            "and ref is the tag of the passage it's from." + CARD_FORMAT,
    "cards": "Write 15 flashcards for the most important ideas: front is a short question or term, back is the "
             "answer in at most two sentences, and ref is the tag of the passage it's from." + CARD_FORMAT,
}

QUIZ_SCHEMA = {"type": "OBJECT", "required": ["questions"], "properties": {"questions": {"type": "ARRAY", "items": {
    "type": "OBJECT", "required": ["question", "choices", "answer", "why"],
    "properties": {"question": STRING, "choices": STRINGS, "answer": {"type": "INTEGER"}, "why": STRING, "ref": STRING}}}}}

CARDS_SCHEMA = {"type": "OBJECT", "required": ["cards"], "properties": {"cards": {"type": "ARRAY", "items": {
    "type": "OBJECT", "required": ["front", "back"], "properties": {"front": STRING, "back": STRING, "ref": STRING}}}}}

REVISE_RULES = ("You edit a student's study note. Make the change asked for and keep everything else as it is. "
                "Reply with the whole note in markdown and nothing else.")

RESEARCH_RULES = ("Search the web to answer a student's question. Reply in two parts. First a line starting SAY: "
                  "with one to three short spoken sentences, no markdown. Then a line NOTES: followed by the key "
                  "facts as a short markdown list. Plain British English.")

NOT_SEARCHED = (" Google Search isn't available right now, so start the spoken part by saying you couldn't search "
                "the web and this is from what you know.")

DEFAULT_PERSONALITY = "You are Oswald, a calm and practical British engineer who helps students study."
SORRY = "Sorry, I couldn't get an answer just then. Have a look at the hub."
NO_KEY = "No Gemini key. Paste one on the page, or run the hub again and paste it there"


# =====================================================================
# Files
# =====================================================================

def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1), encoding="utf-8")


def number(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


# =====================================================================
# Bringing documents in: everything becomes a PDF (pages) or clean HTML (paged by the reader)
# =====================================================================

class ConvertError(Exception):
    pass


KEEP_TAGS = {"p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "b", "strong", "i", "em",
             "u", "s", "sub", "sup", "blockquote", "pre", "code", "table", "thead", "tbody", "tfoot", "tr", "th",
             "td", "caption", "a", "img", "figure", "figcaption", "dl", "dt", "dd", "mark", "small", "div", "span"}
SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe", "object", "nav", "header", "footer",
             "aside", "form", "button", "select", "textarea", "head", "title"}
EMPTY_TAGS = {"br", "hr", "img", "meta", "link", "input", "source", "wbr"}
BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote", "pre", "dt", "dd",
              "figcaption", "caption", "br", "hr", "table", "ul", "ol"}


class Cleaner(HTMLParser):
    """Keeps the words and the simple tags of a page (no scripts, styles, menus or attributes),
    and notes where the <article> or <main> is, which is usually the part worth reading."""

    def __init__(self, base=""):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.out = []
        self.skipping = 0
        self.title = ""
        self.in_title = False
        self.parts = {}
        self.open_parts = {}

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag in SKIP_TAGS and tag not in EMPTY_TAGS:
            self.skipping += 1
            return
        if self.skipping:
            return
        if tag in ("article", "main") and tag not in self.parts and tag not in self.open_parts:
            self.open_parts[tag] = [len(self.out), 1]
        elif tag in self.open_parts:
            self.open_parts[tag][1] += 1
        if tag not in KEEP_TAGS:
            return
        attrs = dict(attrs)
        keep = ""
        if tag == "a" and attrs.get("href"):
            href = urllib.parse.urljoin(self.base, attrs["href"])
            if href.startswith(("http://", "https://")):
                keep = ' href="{}"'.format(html.escape(href))
        if tag == "img":
            src = urllib.parse.urljoin(self.base, attrs.get("src") or "")
            if not src.startswith(("http://", "https://", "data:image/")):
                return
            keep = ' src="{}" alt="{}"'.format(html.escape(src), html.escape(attrs.get("alt") or ""))
        for name in ("colspan", "rowspan"):
            if tag in ("td", "th") and str(attrs.get(name, "")).isdigit():
                keep += ' {}="{}"'.format(name, attrs[name])
        self.out.append("<{}{}>".format(tag, keep))

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in SKIP_TAGS and tag not in EMPTY_TAGS:
            self.skipping = max(0, self.skipping - 1)
            return
        if self.skipping:
            return
        if tag in self.open_parts:
            self.open_parts[tag][1] -= 1
            if not self.open_parts[tag][1]:
                self.parts[tag] = (self.open_parts.pop(tag)[0], len(self.out))
        if tag in KEEP_TAGS and tag not in EMPTY_TAGS:
            self.out.append("</{}>".format(tag))

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skipping:
            self.out.append(html.escape(data, quote=False))

    def result(self):
        for tag in ("article", "main"):
            if tag in self.parts:
                start, end = self.parts[tag]
                part = "".join(self.out[start:end])
                if len(re.sub(r"<[^>]+>", "", part)) > 500:
                    return part
        return "".join(self.out)


def clean_html(text, base=""):
    cleaner = Cleaner(base)
    cleaner.feed(text)
    cleaner.close()
    return cleaner.result(), " ".join(cleaner.title.split())


class TextBlocks(HTMLParser):
    """The text of clean HTML as blocks: (is it a heading, its words)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.words = []
        self.heading = False

    def flush(self):
        text = " ".join("".join(self.words).split())
        if text:
            self.blocks.append((self.heading, text))
        self.words, self.heading = [], False

    def handle_starttag(self, tag, attrs):
        if tag in BLOCK_TAGS:
            self.flush()
        self.heading = self.heading or tag in ("h1", "h2", "h3")

    def handle_endtag(self, tag):
        if tag in BLOCK_TAGS or tag in ("h1", "h2", "h3"):
            self.flush()

    def handle_data(self, data):
        self.words.append(data)


def html_blocks(text):
    parser = TextBlocks()
    parser.feed(text)
    parser.close()
    parser.flush()
    return parser.blocks


def markdown_blocks(text):
    blocks = []
    for part in re.split(r"\n\s*\n|\n(?=#)", text):
        heading = part.lstrip().startswith("#")
        part = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", part)
        part = re.sub(r"\[(d\d+(?:[ps]\d+)?)\]", "", part)
        part = re.sub(r"^\s*(#+|[-*+>]|\d+[.)]|\|)\s*|[*_`|]", " ", part, flags=re.M)
        part = " ".join(part.split())
        if part:
            blocks.append((heading, part))
    return blocks


def sections(blocks, size=1200):
    """Groups blocks into passages of about `size` characters, starting a new one at each heading."""
    pieces = []
    for heading, text in blocks:
        while len(text) > size:
            cut = text.rfind(". ", 0, size) + 1 or size
            pieces.append((heading, text[:cut].strip()))
            heading, text = False, text[cut:].strip()
        pieces.append((heading, text))
    chunks, current = [], ""
    for heading, text in pieces:
        if current and (heading or len(current) + len(text) > size):
            chunks.append(current)
            current = ""
        current = (current + "\n" + text).strip()
    if current:
        chunks.append(current)
    return chunks


def text_to_html(text):
    return "".join("<p>{}</p>".format(html.escape(part).replace("\n", "<br>"))
                   for part in re.split(r"\n\s*\n", text) if part.strip())


def export_pdf(app, path):
    """Opens a file in Pages or Keynote and saves it as a PDF (Mac only)."""
    if not IS_MAC:
        raise ConvertError("{} files can only be opened on a Mac. Save it as a PDF and add that.".format(app))
    out = Path(tempfile.mkdtemp()) / "out.pdf"
    script = ('tell application "{0}"\n set d to open (POSIX file "{1}")\n'
              ' export d to (POSIX file "{2}") as PDF\n close d saving no\nend tell').format(app, path, out)
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=180, check=True)
        return out.read_bytes()
    except (subprocess.SubprocessError, OSError):
        raise ConvertError("{} couldn't turn it into a PDF. Open it in {} and use File > Export To > PDF.".format(app, app))
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)


def convert(name, data):
    """A file someone added, as ("pdf", bytes, title), ("page", clean HTML, title) or ("notes", markdown, title).
    The title is empty when the file doesn't have one."""
    ending = Path(name).suffix.lower()
    if data.startswith(b"%PDF"):
        return "pdf", data, ""
    if ending in (".txt", ".text"):
        return "page", text_to_html(data.decode("utf-8", "replace")), ""
    if ending in (".md", ".markdown"):
        return "notes", data.decode("utf-8", "replace"), ""
    if ending in (".html", ".htm"):
        return ("page",) + clean_html(data.decode("utf-8", "replace"))
    if ending == ".pages":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as box:
                return "pdf", box.read("QuickLook/Preview.pdf"), ""
        except (zipfile.BadZipFile, KeyError):
            pass
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / ("file" + ending)
        path.write_bytes(data)
        if ending == ".pages":
            return "pdf", export_pdf("Pages", path), ""
        if ending in (".key", ".pptx", ".ppt"):
            return "pdf", export_pdf("Keynote", path), ""
        if ending in (".docx", ".doc", ".rtf", ".odt", ".wordml", ".webarchive"):
            if not shutil.which("textutil"):
                raise ConvertError("Word files can only be opened on a Mac. Save it as a PDF and add that.")
            result = subprocess.run(["textutil", "-convert", "html", "-stdout", str(path)], capture_output=True, timeout=60)
            if result.returncode:
                raise ConvertError("Couldn't read that file. Save it as a PDF and add that.")
            return "page", clean_html(result.stdout.decode("utf-8", "replace"))[0], ""
    raise ConvertError("Board reads PDF, Word, Pages, Keynote, PowerPoint, web pages, text and markdown files.")


def fetch_page(url):
    """A web page as ("page", clean HTML, title), or a linked PDF as ("pdf", bytes, name)."""
    if not re.match(r"https?://", url):
        url = "https://" + url
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Board study reader)"})
    try:
        with urllib.request.urlopen(request, timeout=20, context=ssl_context()) as response:
            data = response.read(30_000_000)
            kind = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            url = response.geturl()
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise ConvertError("Couldn't open that link ({}).".format(getattr(error, "reason", error)))
    name = urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name) or "Web page"
    if data.startswith(b"%PDF") or kind == "application/pdf":
        return "pdf", data, name
    if "html" not in kind and "text" not in kind:
        raise ConvertError("That link isn't a web page or a PDF.")
    body, title = clean_html(data.decode(charset, "replace"), url)
    if len(re.sub(r"<[^>]+>", "", body).strip()) < 50:
        raise ConvertError("That page has no text Board can read (it may need a login).")
    return "page", body, title or name


# =====================================================================
# The library: folders, documents and the text of every page
# =====================================================================

EDITABLE = ("notes", "guide", "summary")
ENDINGS = {"pdf": ".pdf", "page": ".html", "notes": ".md", "guide": ".md", "summary": ".md", "quiz": ".json", "cards": ".json"}
STOP_WORDS = set("""the and for are but not you all any can had her was one our out his has have how its may new now
see two who did get let say she too use that with this from they will would there their what about which when
make like into than them then some could these other more very your also just what does where why page pages
oswald please tell show explain""".split())


def stem(word):
    """engines and engine, studies and study: the same word for searching."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


def words(text):
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOP_WORDS]


class Library:
    def __init__(self):
        self.data = read_json(LIBRARY_FILE, {})
        for key, value in (("next", 1), ("folders", []), ("docs", []), ("open", "")):
            self.data.setdefault(key, value)
        self.word_cache = {}

    def save(self):
        write_json(LIBRARY_FILE, self.data)

    def docs(self):
        return self.data["docs"]

    def doc(self, doc_id):
        return next((d for d in self.data["docs"] if d["id"] == str(doc_id).strip()), None)

    def folder(self, folder_id):
        return next((f for f in self.data["folders"] if f["id"] == str(folder_id).strip()), None)

    def new_id(self, letter):
        self.data["next"] += 1
        return "{}{}".format(letter, self.data["next"] - 1)

    def path(self, doc):
        return FILES / doc["file"]

    def read(self, doc):
        try:
            return self.path(doc).read_text(encoding="utf-8")
        except OSError:
            return ""

    def add(self, kind, title, content, folder="", parent="", sources=(), url=""):
        doc_id = self.new_id("d")
        doc = {"id": doc_id, "title": title.strip()[:120] or "Untitled", "kind": kind, "file": doc_id + ENDINGS[kind],
               "folder": folder if self.folder(folder) else "", "parent": parent if self.doc(parent) else "",
               "sources": [s for s in sources if self.doc(s)], "url": url, "at": time.time(), "updated": time.time(),
               "pages": 0, "page": 1}
        if doc["parent"]:
            doc["parent"] = self.doc(parent)["parent"] or doc["parent"]       # one level of attachments
            doc["folder"] = self.doc(doc["parent"])["folder"]
        FILES.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            self.path(doc).write_bytes(content)
        else:
            self.path(doc).write_text(content if isinstance(content, str) else json.dumps(content, indent=1), encoding="utf-8")
        self.data["docs"].append(doc)
        self.index(doc)
        self.save()
        return doc

    def write(self, doc, content):
        self.path(doc).write_text(content if isinstance(content, str) else json.dumps(content, indent=1), encoding="utf-8")
        doc["updated"] = time.time()
        self.index(doc)
        self.save()

    def content(self, doc):
        text = self.read(doc)
        return read_json(self.path(doc), {}) if doc["kind"] in ("quiz", "cards") else text

    def index(self, doc):
        """Splits a document's text into passages for Oswald. A PDF's pages come from the reader."""
        kind = doc["kind"]
        if kind == "pdf":
            return
        if kind == "page":
            texts = sections(html_blocks(self.read(doc)))
        elif kind in EDITABLE:
            texts = sections(markdown_blocks(self.read(doc)))
        elif kind == "quiz":
            texts = ["{} Choices: {}".format(q.get("question", ""), "; ".join(q.get("choices", [])))
                     for q in self.content(doc).get("questions", [])]
        else:
            texts = ["{}: {}".format(c.get("front", ""), c.get("back", "")) for c in self.content(doc).get("cards", [])]
        self.set_texts(doc, texts)

    def texts(self, doc):
        return read_json(TEXTS / (doc["id"] + ".json"), [])

    def set_texts(self, doc, texts):
        write_json(TEXTS / (doc["id"] + ".json"), texts)
        doc["chars"] = sum(len(t) for t in texts)
        doc["indexed"] = time.time()
        if doc["kind"] == "pdf":
            doc["pages"] = len(texts)
        self.word_cache.pop(doc["id"], None)

    def full_text(self, doc, limit):
        """A document's passages, each with its tag, up to `limit` characters."""
        out, used = [], 0
        for i, text in enumerate(self.texts(doc)):
            part = "[{}] {}".format(self.tag(doc, i + 1), text)
            if used + len(part) > limit:
                break
            out.append(part)
            used += len(part)
        return "\n".join(out)

    def tag(self, doc, place):
        return "{}{}{}".format(doc["id"], "p" if doc["kind"] == "pdf" else "s", place)

    def place(self, ref):
        """Where a tag like d3p5, d4s2 or d3 points: {doc, page, find}."""
        match = re.fullmatch(r"\[?(d\d+)(?:([ps])(\d+))?\]?", str(ref).strip())
        doc = self.doc(match.group(1)) if match else None
        if not doc:
            return None
        spot = number(match.group(3))
        place = {"doc": doc["id"], "page": 0, "find": ""}
        if not spot:
            return place
        if doc["kind"] in ("pdf", "quiz", "cards"):
            place["page"] = spot
        else:
            texts = self.texts(doc)
            if spot <= len(texts):
                place["find"] = " ".join(texts[spot - 1].split()[:8])
        return place

    def search(self, query, skip=(), count=PASSAGES):
        """The passages in the library that best match the question (BM25)."""
        wanted = set(words(query))
        if not wanted:
            return []
        items = []
        for doc in self.data["docs"]:
            cached = self.word_cache.get(doc["id"])
            if not cached:
                cached = [(Counter(words(t)), t) for t in self.texts(doc)]
                self.word_cache[doc["id"]] = cached
            items += [(self.tag(doc, i + 1), counts, text) for i, (counts, text) in enumerate(cached)]
        if not items:
            return []
        average = sum(sum(c.values()) for _, c, _ in items) / len(items) or 1
        seen = Counter(w for _, counts, _ in items for w in wanted if w in counts)
        scored = []
        for tag, counts, text in items:
            if tag in skip:
                continue
            length = sum(counts.values())
            score = sum(math.log(1 + (len(items) - seen[w] + 0.5) / (seen[w] + 0.5)) * counts[w] * 2.2 /
                        (counts[w] + 1.2 * (0.25 + 0.75 * length / average)) for w in wanted if counts[w])
            if score > 0:
                scored.append((score, tag, text))
        scored.sort(reverse=True)
        return [(tag, text[:PASSAGE_CHARS]) for _, tag, text in scored[:count]]

    def find_folder(self, name, create=True):
        name = str(name).strip()
        if not name:
            return ""
        found = self.folder(name) or next((f for f in self.data["folders"] if f["name"].lower() == name.lower()), None)
        if found:
            return found["id"]
        if not create:
            return ""
        folder = {"id": self.new_id("f"), "name": name[:60]}
        self.data["folders"].append(folder)
        self.save()
        return folder["id"]

    def move(self, doc_id, folder=None, parent=None):
        doc = self.doc(doc_id)
        if not doc:
            return False
        if parent is not None:
            parent_doc = self.doc(parent)
            doc["parent"] = parent_doc["id"] if parent_doc and parent_doc["id"] != doc["id"] and not parent_doc["parent"] else ""
            if doc["parent"]:
                doc["folder"] = parent_doc["folder"]
        if folder is not None:
            doc["folder"] = folder if self.folder(folder) else ""
            if doc["parent"] and self.doc(doc["parent"])["folder"] != doc["folder"]:
                doc["parent"] = ""
        for child in self.data["docs"]:
            if child["parent"] == doc["id"]:
                child["folder"] = doc["folder"]
        self.save()
        return True

    def rename(self, item_id, title):
        title = str(title).strip()[:120]
        item = self.doc(item_id) or self.folder(item_id)
        if not item or not title:
            return False
        item["title" if "kind" in item else "name"] = title
        self.save()
        return True

    def delete(self, item_id):
        folder = self.folder(item_id)
        if folder:
            self.data["folders"].remove(folder)
            for doc in self.data["docs"]:
                if doc["folder"] == folder["id"]:
                    doc["folder"] = ""
        doc = self.doc(item_id)
        if doc:
            self.data["docs"].remove(doc)
            for child in self.data["docs"]:
                if child["parent"] == doc["id"]:
                    child["parent"] = ""
            for path in (self.path(doc), TEXTS / (doc["id"] + ".json")):
                try:
                    path.unlink()
                except OSError:
                    pass
            if self.data["open"] == doc["id"]:
                self.data["open"] = ""
        self.save()
        return bool(folder or doc)

    def listing(self):
        """The library as a few short lines for Oswald."""
        def describe(doc):
            size = "{} pages".format(doc["pages"]) if doc["kind"] == "pdf" and doc["pages"] else doc["kind"]
            on = ", attached to {}".format(doc["parent"]) if doc["parent"] else ""
            return '{} "{}" ({}{})'.format(doc["id"], doc["title"][:60], size, on)
        lines = []
        for folder in self.data["folders"]:
            inside = [describe(d) for d in self.data["docs"] if d["folder"] == folder["id"]]
            lines.append('Folder {} "{}": {}'.format(folder["id"], folder["name"], "; ".join(inside) or "empty"))
        loose = [describe(d) for d in self.data["docs"] if not d["folder"]]
        if loose:
            lines.append("Not in a folder: " + "; ".join(loose))
        return "\n".join(lines[:60]) or "The library is empty."

    def public(self):
        return {"folders": self.data["folders"], "docs": self.data["docs"], "open": self.data["open"]}


# =====================================================================
# AI: Gemini, with the key from hub/.env
# =====================================================================

gemini_model = ""
gemini_models = []


def load_env():
    path = HERE / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split(" #", 1)[0].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip().strip('"').strip("'") for part in line.split("=", 1))
        if key and value and key not in os.environ:
            os.environ[key] = value


def save_key(key):
    global gemini_model, gemini_models
    path = HERE / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [line for line in lines if not line.strip().startswith("GEMINI_API_KEY=")] + ["GEMINI_API_KEY=" + key]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ["GEMINI_API_KEY"] = key
    gemini_model, gemini_models = "", []


def personality():
    try:
        return (HERE / "oswald.txt").read_text(encoding="utf-8").strip() or DEFAULT_PERSONALITY
    except OSError:
        return DEFAULT_PERSONALITY


def ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class AIError(Exception):
    pass


def web_request(url, data=None, headers=None, timeout=25):
    """One request to Gemini. Returns the body and the response headers."""
    request = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
            return response.read(), response.headers
    except urllib.error.HTTPError as error:
        text = error.read().decode(errors="ignore")
        try:
            text = json.loads(text)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            text = text[:200]
        raise AIError("AI error {}: {}".format(error.code, text))
    except urllib.error.URLError as error:
        if isinstance(error.reason, ssl.SSLCertVerificationError):
            raise AIError("Python can't verify secure connections. Run: python3 -m pip install certifi")
        raise AIError("Can't reach Gemini. Check the internet connection.")
    except OSError:
        raise AIError("Gemini took too long to answer.")


def web_json(url, body=None, headers=None, timeout=25):
    data = json.dumps(body).encode() if body is not None else None
    reply, _ = web_request(url, data, dict({"Content-Type": "application/json"}, **(headers or {})), timeout)
    return json.loads(reply.decode())


def gemini_choices(key):
    """Flash models to try, best first. The one that last worked goes first."""
    global gemini_models
    if os.environ.get("AI_MODEL"):
        return [os.environ["AI_MODEL"]]
    if not gemini_models:
        names = []
        listing = web_json(GEMINI_URL + "/v1beta/models?pageSize=200", headers={"x-goog-api-key": key})
        for model in listing.get("models", []):
            name = model.get("name", "").split("/")[-1]
            skip = any(word in name for word in ("image", "tts", "live", "audio", "embedding", "preview", "exp"))
            if "flash" in name and not skip and "generateContent" in model.get("supportedGenerationMethods", []):
                names.append(name)

        def rank(name):
            numbers = re.findall(r"\d+(?:\.\d+)?", name)
            return ("lite" not in name, float(numbers[0]) if numbers else 0.0)

        names.sort(key=rank, reverse=True)
        gemini_models = list(dict.fromkeys(names + ["gemini-flash-latest", "gemini-flash-lite-latest"]))
    if gemini_model in gemini_models:
        return [gemini_model] + [name for name in gemini_models if name != gemini_model]
    return gemini_models


no_minimal = set()     # models that won't think less than "low"


def thinking(model, effort):
    """Gemini 3 and newer take a thinking level; 2.5 takes a budget, where 0 means none."""
    numbers = re.findall(r"gemini-(\d+)", model)
    if numbers and int(numbers[0]) >= 3:
        return {"thinkingLevel": "minimal" if effort == "quick" and model not in no_minimal else "low"}
    return {"thinkingBudget": 0 if effort == "quick" else 1024}


BUSY_ERRORS = ("AI error 503", "AI error 429", "AI error 500", "AI error 404", "took too long")


def ask_gemini(body, effort="quick", timeout=25, whole=False, tries=4):
    """Sends a request to the best Flash model, moving to the next one when Google is busy.
    Returns the reply's text (or the whole reply, with whole=True)."""
    global gemini_model
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise AIError(NO_KEY)
    problem = None
    for model in gemini_choices(key)[:tries]:
        url = "{}/v1beta/models/{}:generateContent".format(GEMINI_URL, model)
        config = body.setdefault("generationConfig", {})
        config.pop("thinkingConfig", None)
        if QUICK_ANSWERS or effort != "quick":
            config["thinkingConfig"] = thinking(model, effort)
        try:
            try:
                reply = web_json(url, body, {"x-goog-api-key": key}, timeout)
            except AIError as error:
                if "thinking" not in str(error).lower():
                    raise
                if config.get("thinkingConfig", {}).get("thinkingLevel") == "minimal":
                    no_minimal.add(model)
                    config["thinkingConfig"] = thinking(model, effort)
                else:
                    config.pop("thinkingConfig", None)
                reply = web_json(url, body, {"x-goog-api-key": key}, timeout)
            gemini_model = model
            if whole:
                return reply
            parts = ((reply.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            return " ".join(p.get("text", "") for p in parts if not p.get("thought"))
        except AIError as error:
            if not any(busy in str(error) for busy in BUSY_ERRORS):
                raise
            problem = error
    raise AIError("Gemini is overloaded right now. Try again in a minute. ({})".format(problem))


def gemini_file(path):
    """Uploads a PDF to Gemini once (Google keeps it for 48 hours) and returns its address.
    Only used for scanned PDFs, which have no text to send."""
    key = os.environ["GEMINI_API_KEY"]
    data = path.read_bytes()
    digest = hashlib.sha1(data).hexdigest()
    uploads = read_json(UPLOADS_FILE, {})
    known = uploads.get(digest)
    if known and time.time() - known.get("at", 0) < 46 * 3600:
        return known["uri"]
    _, headers = web_request(GEMINI_URL + "/upload/v1beta/files",
                             json.dumps({"file": {"display_name": path.stem[:100]}}).encode(),
                             {"x-goog-api-key": key, "Content-Type": "application/json",
                              "X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
                              "X-Goog-Upload-Header-Content-Length": str(len(data)),
                              "X-Goog-Upload-Header-Content-Type": "application/pdf"})
    upload_url = headers.get("x-goog-upload-url")
    if not upload_url:
        raise AIError("Gemini didn't take the PDF upload.")
    body, _ = web_request(upload_url, data, {"x-goog-api-key": key, "Content-Type": "application/pdf",
                                             "X-Goog-Upload-Offset": "0",
                                             "X-Goog-Upload-Command": "upload, finalize"}, timeout=240)
    file = json.loads(body.decode()).get("file", {})
    for _ in range(60):
        if file.get("state", "ACTIVE") == "ACTIVE":
            break
        if file.get("state") == "FAILED":
            raise AIError("Gemini couldn't read the PDF.")
        time.sleep(1)
        file = web_json(GEMINI_URL + "/v1beta/" + file["name"], headers={"x-goog-api-key": key})
    if not file.get("uri"):
        raise AIError("Gemini didn't take the PDF upload.")
    uploads[digest] = {"uri": file["uri"], "at": time.time(), "name": path.name}
    write_json(UPLOADS_FILE, uploads)
    return file["uri"]


def pdf_part(path):
    """A scanned PDF for the writer: its address at Gemini, or the file itself."""
    try:
        return {"fileData": {"mimeType": "application/pdf", "fileUri": gemini_file(path)}}
    except AIError:
        if path.stat().st_size > 15_000_000:
            raise
        return {"inlineData": {"mimeType": "application/pdf", "data": base64.b64encode(path.read_bytes()).decode()}}


def read_json_reply(text):
    match = re.search(r"\{.*\}", text, re.S)
    try:
        value = json.loads(match.group(0) if match else text)
    except (ValueError, AttributeError):
        raise AIError("Gemini sent back something odd: " + text[:80])
    if not isinstance(value, dict):
        raise AIError("Gemini sent back something odd: " + text[:80])
    return value


def clean_reply(value):
    def text(item, limit=4000):
        return str(item or "").strip()[:limit]

    def strings(items):
        return [text(i, 200) for i in (items if isinstance(items, list) else []) if text(i)]

    def part(name, keys):
        item = value.get(name)
        if not isinstance(item, dict):
            return None
        return {k: strings(item.get(k)) if k in ("sources", "docs") else text(item.get(k), 20000) for k in keys}

    reply = {"heard": text(value.get("heard")), "answer": text(value.get("answer")), "detail": text(value.get("detail")),
             "cites": strings(value.get("cites"))[:8], "go": text(value.get("go"), 40), "look_up": text(value.get("look_up"), 200),
             "make": part("make", ("kind", "title", "sources", "about", "attach_to", "folder")),
             "edit": part("edit", ("doc", "how", "find", "text")),
             "search": part("search", ("query", "save_to")),
             "organize": part("organize", ("folder", "docs")),
             "quiz_choice": number(value.get("quiz_choice"))}
    if reply["make"] and reply["make"]["kind"] not in KINDS:
        reply["make"] = None
    if reply["edit"] and (reply["edit"]["how"] not in ("append", "replace", "revise") or not reply["edit"]["text"]):
        reply["edit"] = None
    if reply["search"] and not reply["search"]["query"]:
        reply["search"] = None
    if reply["organize"] and not (reply["organize"]["folder"] and reply["organize"]["docs"]):
        reply["organize"] = None
    return reply


def ai_reply(words, sound, picture, context, history):
    """Asks Oswald about what was said (typed words, or a recording), with what's on screen."""
    parts = []
    if sound:
        parts.append({"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(sound).decode()}})
    if picture:
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(picture).decode()}})
    notes = (["The recording is the user talking to you."] if sound else []) + \
            (["The picture is the page on their screen."] if picture else [])
    question = context + "\n\n" + "\n".join(notes + ([] if sound else ["The user says: " + words]))
    turns = [{"role": "user" if who == "user" else "model", "parts": [{"text": text}]} for who, text in history[-HISTORY_TURNS:]]
    turns.append({"role": "user", "parts": parts + [{"text": question}]})
    rules = AI_RULES if KEEP_LISTENING else AI_RULES + "\n" + ONE_QUESTION_RULE
    body = {"systemInstruction": {"parts": [{"text": "{}\n\n{}\n\n{}".format(personality(), rules, REPLY_RULES)}]},
            "contents": turns,
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": REPLY_SCHEMA}}
    reply = clean_reply(read_json_reply(ask_gemini(body)))
    if not sound:
        reply["heard"] = words
    return reply


LOST_ESCAPES = {"\x0c": "\\f", "\x08": "\\b", "\t": "\\t", "\r": "\\r", "\n": "\\n"}
TAG_GROUP = re.compile(r"\s*\[\s*d\d+(?:[ps]\d+)?(?:\s*[,;]\s*d\d+(?:[ps]\d+)?)*\s*\]")
CJK = re.compile(r"[\u3000-\u9fff\uac00-\ud7af\uff00-\uffef]+")


def tidy(text, keep_cjk=False):
    """A quiz or flashcard field as Gemini wrote it: LaTeX backslashes lost to JSON escapes put back
    (\\forall arrives as a form feed and "orall"), page tags taken out, stray characters dropped."""
    def fix(math):
        return re.sub(r"[\x08-\x0d](?=\\)|[\x08-\x0d]", lambda c: "" if c.end() < len(math.group(0)) and
                      math.group(0)[c.end()] == "\\" else LOST_ESCAPES.get(c.group(0), ""), math.group(0))
    text = re.sub(r"\$[^$]*\$", fix, str(text or ""))
    text = TAG_GROUP.sub("", re.sub(r"[\x00-\x1f]", " ", text))
    if not keep_cjk:
        text = CJK.sub("", text)
    return " ".join(text.split())


def first_tag(*texts):
    for text in texts:
        match = re.search(r"d\d+(?:[ps]\d+)?", str(text or ""))
        if match:
            return match.group(0)
    return ""


def tidy_cards(content, keep_cjk=False):
    """Cleans every field of a quiz or a set of flashcards."""
    for q in content.get("questions", []):
        q["ref"] = first_tag(q.get("ref"), q.get("why"), q.get("question"))
        q["question"], q["why"] = tidy(q["question"], keep_cjk), tidy(q.get("why"), keep_cjk)
        q["choices"] = [tidy(c, keep_cjk) for c in q["choices"]]
    for c in content.get("cards", []):
        c["ref"] = first_tag(c.get("ref"), c.get("back"), c.get("front"))
        c["front"], c["back"] = tidy(c["front"], keep_cjk), tidy(c.get("back"), keep_cjk)
    return content


def ai_write(kind, title, sources, about):
    """Writes notes, a guide or a summary (markdown), or a quiz or flashcards (JSON), from the sources.
    sources is the tagged text, plus any scanned PDFs as parts."""
    text, pdfs = sources
    ask = "{}\nTitle: {}\n{}".format(WRITE_KINDS[kind], title, "What they asked for: " + about if about else "")
    body = {"systemInstruction": {"parts": [{"text": WRITE_RULES}]},
            "contents": [{"role": "user", "parts": pdfs + [{"text": "Sources:\n" + text}, {"text": ask}]}],
            "generationConfig": {}}
    if kind in ("quiz", "cards"):
        body["generationConfig"] = {"responseMimeType": "application/json",
                                    "responseSchema": QUIZ_SCHEMA if kind == "quiz" else CARDS_SCHEMA}
    reply = ask_gemini(body, effort="write", timeout=120)
    if kind == "quiz":
        questions = []
        for q in read_json_reply(reply).get("questions") or []:
            choices = [str(c).strip() for c in q.get("choices") or [] if str(c).strip()][:4]
            if q.get("question") and len(choices) >= 2:
                questions.append({"question": str(q["question"]).strip(), "choices": choices,
                                  "answer": min(number(q.get("answer")), len(choices) - 1),
                                  "why": str(q.get("why") or "").strip(), "ref": str(q.get("ref") or "").strip()})
        if not questions:
            raise AIError("Gemini didn't write any questions.")
        return tidy_cards({"questions": questions, "answers": [None] * len(questions)}, bool(CJK.search(text)))
    if kind == "cards":
        cards = [{"front": str(c["front"]).strip(), "back": str(c.get("back") or "").strip(), "ref": str(c.get("ref") or "").strip()}
                 for c in read_json_reply(reply).get("cards") or [] if isinstance(c, dict) and c.get("front")]
        if not cards:
            raise AIError("Gemini didn't write any flashcards.")
        return tidy_cards({"cards": cards}, bool(CJK.search(text)))
    reply = re.sub(r"^```(?:markdown|md)?\s*|\s*```\s*$", "", reply.strip())
    if not reply:
        raise AIError("Gemini sent back an empty document.")
    return reply


def ai_revise(note, instruction, passages):
    body = {"systemInstruction": {"parts": [{"text": REVISE_RULES}]},
            "contents": [{"role": "user", "parts": [{"text": "The note:\n" + note},
                                                    {"text": "Passages from their documents that may help:\n" + passages if passages else "No passages."},
                                                    {"text": "The change: " + instruction}]}]}
    reply = re.sub(r"^```(?:markdown|md)?\s*|\s*```\s*$", "", ask_gemini(body, effort="write", timeout=120).strip())
    if len(reply) < 20:
        raise AIError("Gemini sent back an empty note.")
    return reply


search_works = True     # False once the key turns out not to have Google Search


def ai_research(question, query):
    """Looks something up with Google Search. Returns what to say, notes and the sources.
    If the key can't use Google Search, Oswald answers from what he knows and says so."""
    body = {"systemInstruction": {"parts": [{"text": RESEARCH_RULES}]},
            "contents": [{"role": "user", "parts": [{"text": "Question: {}\nSearch for: {}".format(question, query)}]}],
            "tools": [{"google_search": {}}]}
    global search_works
    try:
        if not search_works:
            raise AIError("Google Search is off for this key")
        reply = ask_gemini(body, effort="quick", timeout=30, whole=True, tries=1)
    except AIError as error:
        search_works = search_works and "429" not in str(error) and "quota" not in str(error).lower()
        body.pop("tools")
        body["systemInstruction"]["parts"][0]["text"] = RESEARCH_RULES.replace("Search the web to answer", "Answer from what you know") + NOT_SEARCHED
        reply = ask_gemini(body, effort="quick", timeout=60, whole=True)
    candidate = (reply.get("candidates") or [{}])[0]
    text = " ".join(p.get("text", "") for p in (candidate.get("content") or {}).get("parts") or [] if not p.get("thought"))
    say, _, notes = text.partition("NOTES:")
    say = say.replace("SAY:", "").strip()
    sources = []
    for chunk in (candidate.get("groundingMetadata") or {}).get("groundingChunks") or []:
        web = chunk.get("web") or {}
        if web.get("uri") and web.get("uri") not in [s["uri"] for s in sources]:
            sources.append({"title": web.get("title") or web["uri"], "uri": web["uri"]})
    if not say:
        raise AIError("The web search came back empty.")
    return {"say": say, "notes": notes.strip(), "sources": sources[:6]}


def ai_label():
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    return "Gemini ({})".format(os.environ.get("AI_MODEL") or gemini_model or "newest Flash model")


# =====================================================================
# The laptop: mic and voice
# =====================================================================

RATE = 16000
PACKET = 320                # samples in 20 ms


def wav_bytes(samples, rate=RATE):
    out = io.BytesIO()
    with wave.open(out, "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(samples.tobytes())
    return out.getvalue()


def loudness(samples):
    return math.sqrt(sum(s * s for s in samples) / max(len(samples), 1))


class Listener:
    """Cuts the mic's sound into things you said, by waiting for a pause. Quiet is measured against the
    room before you spoke and against your own voice, so a fan or people talking behind you don't count."""
    PAUSE = 45              # packets (0.9 s) that are mostly quiet end what you said
    STRAY = 6               # loud packets a pause may still have: a cough, a door, a voice behind you
    LONGEST = 600           # packets (12 s)
    SHORTEST = 15           # loud packets (0.3 s). Less is a click or a cough

    def __init__(self):
        self.reset()

    def reset(self):
        self.room = deque(maxlen=100)       # the last 2 s before you spoke. The quietest moment is its noise
        self.before = deque(maxlen=15)      # the last 0.3 s, so the first word isn't cut off
        self.recent = deque(maxlen=self.PAUSE)
        self.sound = None
        self.voice = []
        self.loud = 0

    def add(self, samples):
        """Takes one packet. Returns everything you said once you pause."""
        level = loudness(samples)
        noise = 3 * min(self.room) if self.room else 0
        if self.sound is None:
            self.room.append(level)
            self.before.append(samples)
            self.loud = self.loud + 1 if level > max(noise, 300) else 0
            if self.loud >= 3:
                self.sound, self.voice = list(self.before), [level] * 3
                self.recent.clear()
            return None
        self.sound.append(samples)
        voice = sorted(self.voice)[len(self.voice) // 2]
        loud = level > max(noise, 300, voice / 4)
        if loud:
            self.voice.append(level)
        self.recent.append(loud)
        paused = len(self.recent) == self.PAUSE and sum(self.recent) <= self.STRAY
        if not paused and len(self.sound) < self.LONGEST:
            return None
        said = array("h")
        for part in self.sound:
            said.extend(part)
        long_enough = len(self.voice) >= self.SHORTEST
        self.sound, self.loud = None, 0
        self.before.clear()
        return said if long_enough else None


class Mic:
    """The laptop's mic, in 20 ms packets at 16 kHz (needs: python3 -m pip install sounddevice)."""

    def __init__(self):
        self.stream = None
        self.name = ""
        self.problem = "off"
        self.rate = RATE
        self.loud_seen = 0.0

    def start(self, loop, on_packet):
        try:
            import sounddevice
        except Exception:
            self.problem = ("Chrome's, for now. For the laptop mic, run python3 -m pip install sounddevice "
                            "in Terminal, then restart the hub")
            return False
        try:
            device = sounddevice.query_devices(kind="input")
            self.name = device["name"]
            rate = RATE
            try:
                sounddevice.check_input_settings(samplerate=RATE, channels=1, dtype="int16")
            except Exception:
                rate = int(device["default_samplerate"])
            step = max(1, round(rate / RATE))
            self.rate = rate // step

            def callback(data, frames, when, status):
                samples = array("h", bytes(data))
                if step > 1:
                    samples = array("h", (sum(samples[i:i + step]) // step for i in range(0, len(samples) - step + 1, step)))
                loop.call_soon_threadsafe(on_packet, samples)

            self.stream = sounddevice.RawInputStream(samplerate=rate, channels=1, dtype="int16",
                                                     blocksize=PACKET * step, callback=callback)
            self.stream.start()
            return True
        except Exception as error:
            self.problem = "couldn't open it ({}). Oswald listens through Chrome instead".format(error)
            return False


NOVELTY_VOICES = {"Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Good News", "Jester",
                  "Organ", "Superstar", "Trinoids", "Whisper", "Wobble", "Zarvox"}
ACCENTS = {"en_GB": "British", "en_US": "American", "en_AU": "Australian", "en_IE": "Irish", "en_IN": "Indian",
           "en_ZA": "South African", "en-scotland": "Scottish"}
mac_voices = []       # [(name, accent)]: British first, and the best of each first


def voice_quality(name):
    return 0 if "(Premium)" in name else 1 if "(Enhanced)" in name else 2


def find_voices():
    """The Mac's English voices, from the list `say -v ?` prints."""
    global mac_voices
    if not IS_MAC:
        return mac_voices
    try:
        listing = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return mac_voices
    found = {(name, ACCENTS.get(locale, locale))
             for name, locale in re.findall(r"^(.+?)\s+([a-z]{2,3}[_-][\w-]+)\s+#", listing, re.M)
             if locale.startswith("en") and name not in NOVELTY_VOICES}
    mac_voices = sorted(found, key=lambda v: (v[1] != "British", voice_quality(v[0]), v[0]))
    return mac_voices


WINDOWS_SPEECH = ("Add-Type -AssemblyName System.Speech;"
                  "$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                  "$voice.SelectVoiceByHints('Male');"
                  "$voice.Speak([Console]::In.ReadToEnd())")


def speech_command(voice):
    if IS_MAC:
        return ["say", "-r", str(SPEAKING_RATE)] + (["-v", voice] if voice else [])
    if IS_WINDOWS:
        return ["powershell", "-NoProfile", "-Command", WINDOWS_SPEECH]
    return None


# =====================================================================
# The hub: Oswald, the library and the reader
# =====================================================================

# The board's Oswald key, heard in every app. This runs in its own process, so a problem
# with the key library (or a missing permission) can never stop Oswald: the page still hears it.
KEY_LISTENER = r"""
import os, sys, threading
threading.Thread(target=lambda: (sys.stdin.read(), os._exit(0)), daemon=True).start()   # stops when the hub does
from pynput import keyboard
F18 = getattr(keyboard.Key, "f18", None)

def press(key):
    if key == F18 or getattr(key, "vk", None) in (79, 0x81):
        print("F18 down", flush=True)

with keyboard.Listener(on_press=press) as listener:
    print("trusted" if getattr(listener, "IS_TRUSTED", True) else "not trusted", flush=True)
    listener.join()
"""

LOOKS_VISUAL = re.compile(r"\b(diagram|figure|picture|image|graph|chart|table|drawing|photo|map|equation|formula|slide|look)", re.I)
KIND_NAMES = {"notes": "notes", "guide": "study guide", "summary": "summary", "quiz": "quiz", "cards": "flashcards"}


class Hub:
    def __init__(self):
        self.keys = "page"          # where the board's Oswald key is heard: "page" or "everywhere"
        self.last_toggle = -1e9
        self.clients = set()
        self.tasks = set()
        self.history = []
        self.talking = False        # Oswald is on
        self.state = "off"          # off, listening, thinking, speaking
        self.talk_id = 0            # changes every time Oswald turns on or off
        self.turned_on = 0.0
        self.browser_heard = 0.0    # when Chrome last heard words (when it's the mic)
        self.voice = read_json(SETTINGS_FILE, {}).get("voice", "")
        self.busy = False
        self.listener = Listener()
        self.mic = Mic()
        self.speech = None
        self.library = Library()
        self.view = {"doc": self.library.data["open"], "page": 1, "pages": 0, "text": "", "selection": ""}
        self.snaps = {}
        self.snap_id = 0

    # ---------- the terminal and the page ----------
    def log(self, text):
        print("  " + text, flush=True)
        self.broadcast({"kind": "log", "time": time.strftime("%H:%M:%S"), "text": text})

    def broadcast(self, message):
        for queue in list(self.clients):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(message)

    def mic_route(self):
        return "laptop" if self.mic.stream else "browser"

    def status(self):
        return {"kind": "status", "ai": ai_label(), "talk": self.talk_message(),
                "mic": self.mic.name if self.mic.stream else self.mic.problem, "keys": self.keys,
                "library": self.library.public(), "voice": self.voice_name(),
                "voices": [{"name": name, "accent": accent} for name, accent in mac_voices]}

    def update_library(self):
        self.broadcast({"kind": "library", "library": self.library.public()})

    def chat(self, who, text, **extra):
        print("{:>8}: {}".format(who, text), flush=True)
        self.broadcast(dict({"kind": "chat", "who": who, "text": text}, **extra))

    def problem(self, text):
        self.log(text)
        self.broadcast({"kind": "note", "text": text})

    def working(self, text):
        self.broadcast({"kind": "working", "text": text})

    def later(self, job):
        task = asyncio.ensure_future(job)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    # ---------- the board's Oswald key ----------
    def key_toggle(self):
        """F18 (or the button): Oswald on or off. The page and the key listener can both hear one
        press, so a second toggle straight after the first is ignored."""
        if time.monotonic() - self.last_toggle < 0.5:
            return
        self.last_toggle = time.monotonic()
        self.later(self.toggle())

    async def listen_for_keys(self):
        try:
            process = await asyncio.create_subprocess_exec(sys.executable, "-c", KEY_LISTENER,
                                                           stdin=asyncio.subprocess.PIPE,
                                                           stdout=asyncio.subprocess.PIPE,
                                                           stderr=asyncio.subprocess.DEVNULL)
        except OSError:
            return
        while True:
            line = (await process.stdout.readline()).decode().strip()
            if not line:
                break
            if line == "not trusted":
                self.log("Oswald's fingers work while the reader is in front. For every app, allow Terminal under "
                         "Privacy & Security > Accessibility and Input Monitoring, then reopen Terminal")
            if line != "F18 down":
                continue
            if self.keys != "everywhere":       # it hears the board, so the page leaves the key to it
                self.keys = "everywhere"
                self.broadcast(self.status())
            self.key_toggle()
        self.keys = "page"
        self.broadcast(self.status())

    # ---------- what's on screen ----------
    def open_doc(self):
        return self.library.doc(self.view["doc"])

    def set_view(self, data):
        doc = self.library.doc(data.get("doc"))
        self.view = {"doc": doc["id"] if doc else "", "page": max(1, number(data.get("page"))),
                     "pages": number(data.get("pages")), "text": str(data.get("text") or "")[:PAGE_CHARS],
                     "selection": str(data.get("selection") or "")[:1500]}
        if doc:
            doc["page"] = self.view["page"]
        if self.library.data["open"] != self.view["doc"]:
            self.library.data["open"] = self.view["doc"]
            self.library.save()

    def scanned(self, doc):
        return doc and doc["kind"] == "pdf" and doc.get("pages") and doc.get("chars", 0) < 40 * doc["pages"]

    async def take_snap(self):
        """A picture of the PDF page on screen, from the reader. None if it doesn't answer."""
        if not self.clients:
            return None
        self.snap_id += 1
        snap_id = self.snap_id
        self.broadcast({"kind": "snap", "id": snap_id})
        give_up = time.monotonic() + 3
        while snap_id not in self.snaps and time.monotonic() < give_up:
            await asyncio.sleep(0.05)
        return self.snaps.pop(snap_id, None)

    def context(self, question="", look_up=""):
        """What Oswald is told with each question: the library, the page on screen, what's highlighted,
        and (for typed questions or a look-up) the best matching passages from everything else."""
        view, doc = self.view, self.open_doc()
        lines = ["Library:", self.library.listing()]
        skip = set()
        if doc:
            here = self.library.tag(doc, view["page"]) if doc["kind"] in ("pdf", "quiz", "cards") else doc["id"]
            skip.add(here)
            lines.append('Open now: {} "{}" ({}), page {} of {}.'.format(doc["id"], doc["title"], doc["kind"],
                                                                          view["page"], view["pages"] or "?"))
            if doc["kind"] in EDITABLE:
                lines.append("The whole of {} (markdown, you can edit it):\n{}".format(doc["id"], self.library.read(doc)[:NOTE_CHARS]))
            elif doc["kind"] == "quiz":
                quiz = self.library.content(doc)
                questions = quiz.get("questions", [])
                if 1 <= view["page"] <= len(questions):
                    q = questions[view["page"] - 1]
                    given = (quiz.get("answers") or [None] * len(questions))[view["page"] - 1]
                    lines.append("Quiz question {} on screen: {} Choices: {}. Right answer: {} ({}). {}".format(
                        view["page"], q["question"], "; ".join("{}) {}".format("ABCD"[i], c) for i, c in enumerate(q["choices"])),
                        "ABCD"[q["answer"]], q["why"], "They picked {}.".format("ABCD"[given]) if given is not None else "They haven't picked yet."))
                else:
                    right = sum(1 for q, a in zip(questions, quiz.get("answers") or []) if a == q["answer"])
                    lines.append("The quiz's score page is on screen: {} of {} right.".format(right, len(questions)))
            elif view["text"]:
                lines.append("On screen [{}]:\n{}".format(here, view["text"]))
        else:
            lines.append("No document is open.")
        if view["selection"]:
            lines.append('Selected: "{}"'.format(view["selection"]))
        query = look_up or question
        if query:
            passages = self.library.search(query + " " + view["selection"], skip)
            if doc and doc["kind"] in EDITABLE:
                passages = [p for p in passages if not p[0].startswith(doc["id"] + "s")]
            if passages:
                lines.append("Passages from their documents that match:")
                lines += ["[{}] {}".format(tag, text) for tag, text in passages]
            elif look_up:
                lines.append("Nothing in their documents matches that.")
        return "\n".join(lines)

    # ---------- Oswald: tap and ask, tap again to stop him ----------
    def talk_message(self):
        return {"kind": "talk", "state": self.state, "name": ASSISTANT_NAME, "mic": self.mic_route(), "keep": KEEP_LISTENING}

    def set_state(self, state):
        self.state = state
        self.broadcast(self.talk_message())

    async def toggle(self):
        if self.talking or self.state == "speaking":
            await self.stop()
        else:
            await self.start()

    async def start(self):
        if not os.environ.get("GEMINI_API_KEY"):
            self.problem(NO_KEY)
            return
        self.talking = True
        self.talk_id += 1
        self.turned_on = time.monotonic()
        self.stop_speaking()
        self.log("{} is listening{}".format(ASSISTANT_NAME, "" if self.mic.stream else " through Chrome (keep the page open)"))
        self.listen()
        if not KEEP_LISTENING:
            self.later(self.stop_if_nothing_asked())

    async def stop(self, why=""):
        self.talking = False
        self.talk_id += 1
        self.stop_speaking()
        self.set_state("off")
        self.log(why or "{} is off".format(ASSISTANT_NAME))

    async def stop_if_nothing_asked(self):
        """One question per tap: if you don't start talking soon after the tap, he turns off."""
        while self.talking:
            await asyncio.sleep(0.25)
            if (self.talking and self.state == "listening" and not self.someone_talking()
                    and time.monotonic() - self.turned_on > WAIT_FOR_QUESTION):
                await self.stop("Nothing was asked, so {} is off".format(ASSISTANT_NAME))

    def someone_talking(self):
        return self.listener.sound is not None or time.monotonic() - self.browser_heard < 1.5

    def listen(self):
        self.listener.reset()
        self.set_state("listening")

    def ask(self, words="", sound=None):
        self.set_state("thinking")        # straight away, so nothing turns him off mid-question
        self.later(self.answer(words=words, sound=sound))

    def heard_packet(self, samples):
        if any(abs(s) > 200 for s in samples[::8]):
            self.mic.loud_seen = time.monotonic()
        if self.state != "listening":
            return
        said = self.listener.add(samples)
        if said:
            self.log("Heard {:.1f} s of you".format(len(said) / self.mic.rate))
            self.ask(sound=wav_bytes(said, self.mic.rate))

    def heard_in_browser(self, words):
        """What Chrome heard, when the laptop mic isn't set up in Python."""
        if self.talking and self.state == "listening" and words:
            self.ask(words=words)

    def typed(self, words):
        words = words.strip()
        if not words:
            return {"ok": False, "answer": "Ask a question first."}
        if self.state in ("thinking", "speaking") or self.busy:
            return {"ok": False, "answer": "{} is busy. Ask again in a moment.".format(ASSISTANT_NAME)}
        self.ask(words=words[:1000])
        return {"ok": True, "answer": ""}

    async def answer(self, words="", sound=None):
        talk_id = self.talk_id
        self.busy = True
        self.later(self.refresh_voices())     # a voice downloaded a minute ago is used straight away
        if words:
            self.chat("You", words)
        self.set_state("thinking")
        started = time.monotonic()
        doc = self.open_doc()
        picture = None
        if doc and doc["kind"] == "pdf" and (len(self.view["text"]) < 200 or LOOKS_VISUAL.search(words)):
            picture = await self.take_snap()          # a slide that's mostly a picture, or a question about one
        try:
            reply = await asyncio.to_thread(ai_reply, words, sound, picture, self.context(words), self.history)
            if reply["look_up"] and reply["heard"]:
                reply = await asyncio.to_thread(ai_reply, reply["heard"], None, picture,
                                                self.context(reply["heard"], reply["look_up"]), self.history)
            ok = True
        except AIError as error:
            reply, ok = {"heard": words, "answer": str(error)}, False
        except Exception as error:
            reply, ok = {"heard": words, "answer": "Something went wrong: {}".format(error)}, False
        self.busy = False
        if talk_id != self.talk_id:
            return
        if ok and not reply["heard"]:
            self.after_answer(talk_id, asked=False)
            return
        if sound:
            self.chat("You", reply["heard"])
        if ok:
            if not reply["answer"]:
                reply["answer"] = "I couldn't find that in your documents."
            self.act(reply)
            cites = [place for place in (self.library.place(c) for c in reply["cites"]) if place]
            self.chat(ASSISTANT_NAME, reply["answer"], detail=reply["detail"], cites=cites)
            self.log("(answered in {:.1f} s)".format(time.monotonic() - started))
            self.history = (self.history + [("user", reply["heard"]), ("assistant", reply["answer"])])[-2 * HISTORY_TURNS:]
        else:
            self.problem(reply["answer"])
        self.set_state("speaking")
        await self.speak(reply["answer"] if ok else SORRY, talk_id)
        self.after_answer(talk_id)

    def act(self, reply):
        """Does what Oswald decided: show a page, write or change a document, research, sort the library."""
        if reply["go"]:
            self.go(reply["go"])
        if reply["quiz_choice"]:
            doc = self.open_doc()
            if doc and doc["kind"] == "quiz":
                self.quiz_answer(doc["id"], self.view["page"] - 1, reply["quiz_choice"] - 1)
        if reply["organize"]:
            self.organize(reply["organize"]["folder"], reply["organize"]["docs"])
        if reply["make"]:
            m = reply["make"]
            self.later(self.make(m["kind"], m["title"], m["sources"], m["about"], m["attach_to"], m["folder"]))
        if reply["edit"]:
            e = reply["edit"]
            self.later(self.edit(e["doc"], e["how"], e["find"], e["text"]))
        if reply["search"]:
            self.later(self.research(reply["heard"], reply["search"]["query"], reply["search"]["save_to"]))

    def go(self, ref):
        place = self.library.place(ref)
        if place:
            self.broadcast(dict({"kind": "go"}, **place))

    def after_answer(self, talk_id, asked=True):
        """Back to listening, or off: unless KEEP_LISTENING is on, he turns off once he's answered."""
        if talk_id != self.talk_id:
            return
        waiting = not asked and time.monotonic() - self.turned_on < WAIT_FOR_QUESTION
        if self.talking and (KEEP_LISTENING or waiting):
            self.listen()
        else:
            self.talking = False
            self.set_state("off")

    async def say_now(self, text):
        """Says something between questions, without Oswald hearing himself."""
        if self.state not in ("off", "listening"):
            return
        was_listening = self.state == "listening"
        if was_listening:
            self.set_state("speaking")
        talk_id = self.talk_id
        await self.speak(text, talk_id)
        if was_listening and talk_id == self.talk_id:
            self.listen()

    # ---------- writing, editing and sorting documents ----------
    def source_text(self, docs):
        """The tagged text of the sources, and scanned PDFs as parts (they have no text)."""
        text, pdfs, room = [], [], SOURCE_CHARS
        for doc in docs:
            if self.scanned(doc):
                pdfs.append(pdf_part(self.library.path(doc)))
                text.append("{} \"{}\" is the attached PDF.".format(doc["id"], doc["title"]))
                continue
            part = '{} "{}":\n{}'.format(doc["id"], doc["title"], self.library.full_text(doc, room))
            room -= len(part)
            text.append(part)
        return "\n\n".join(text), pdfs

    async def make(self, kind, title="", sources=(), about="", attach_to="", folder=""):
        docs = [d for d in (self.library.doc(s) for s in sources) if d] or [d for d in [self.open_doc()] if d]
        docs = [d for d in docs if d["kind"] not in ("quiz", "cards")] or docs
        if not docs:
            self.problem("Open a document first, so {} has something to work from.".format(ASSISTANT_NAME))
            return
        name = KIND_NAMES[kind]
        title = title or "{}: {}".format(docs[0]["title"] if len(docs) == 1 else "Study", name[0].upper() + name[1:])
        parent = attach_to if self.library.doc(attach_to) else docs[0]["id"] if len(docs) == 1 else ""
        folders = {d["folder"] for d in docs}
        folder = self.library.find_folder(folder) if folder else (folders.pop() if len(folders) == 1 else "")
        self.working("{} is writing the {}…".format(ASSISTANT_NAME, name))
        self.log("Writing {} from {}".format(name, ", ".join(d["title"] for d in docs)))
        try:
            content = await asyncio.to_thread(ai_write, kind, title, self.source_text(docs), about)
        except AIError as error:
            self.working("")
            self.problem("Couldn't write the {}: {}".format(name, error))
            return
        doc = self.library.add(kind, title, content, folder, parent, [d["id"] for d in docs])
        self.working("")
        self.update_library()
        self.broadcast({"kind": "go", "doc": doc["id"], "page": 1, "find": ""})
        self.log("{} ready: {}".format(name.capitalize(), doc["title"]))
        self.later(self.say_now("Your {} is ready.".format(name)))

    async def edit(self, doc_id, how, find, text):
        doc = self.library.doc(doc_id)
        if not doc or doc["kind"] not in EDITABLE:
            self.problem("{} can only change notes, guides and summaries.".format(ASSISTANT_NAME))
            return
        note = self.library.read(doc)
        changed = text
        if how == "replace" and find and find in note:
            note = note.replace(find, text, 1)
        elif how == "append":
            note = add_under(note, find, text)
        else:
            self.working("{} is changing {}…".format(ASSISTANT_NAME, doc["title"]))
            passages = "\n".join("[{}] {}".format(tag, t) for tag, t in self.library.search(text, {doc["id"]}))
            try:
                note = await asyncio.to_thread(ai_revise, note, text if how == "revise" else
                                               "Change \"{}\" to: {}".format(find, text), passages)
            except AIError as error:
                self.working("")
                self.problem("Couldn't change the note: {}".format(error))
                return
            self.working("")
            changed = ""
        self.library.write(doc, note)
        self.update_library()
        self.broadcast({"kind": "changed", "doc": doc["id"], "text": " ".join(changed.split()[:8])})
        self.log("Changed " + doc["title"])

    def organize(self, folder, doc_ids):
        folder_id = self.library.find_folder(folder)
        moved = [d for d in dict.fromkeys(doc_ids) if self.library.move(d, folder=folder_id)]
        if moved:
            self.update_library()
            self.log("Put {} in {}".format(", ".join(moved), self.library.folder(folder_id)["name"]))

    async def research(self, question, query, save_to=""):
        self.working("{} is looking it up…".format(ASSISTANT_NAME))
        try:
            found = await asyncio.to_thread(ai_research, question, query)
        except AIError as error:
            self.working("")
            self.problem("Couldn't search the web: {}".format(error))
            return
        self.working("")
        self.chat(ASSISTANT_NAME, found["say"], detail=found["notes"], sources=found["sources"])
        if save_to:
            note = self.library.doc(save_to)
            if not note or note["kind"] not in EDITABLE:
                here = self.open_doc() or {"id": "", "folder": ""}
                note = self.library.add("notes", "Research: " + query[:60], "# Research: {}\n".format(query),
                                        here["folder"], here["id"])
            links = "\n".join("- [{}]({})".format(s["title"], s["uri"]) for s in found["sources"])
            self.library.write(note, add_under(self.library.read(note), "", "## {}\n\n{}\n\nSources:\n{}".format(
                query, found["notes"] or found["say"], links)))
            self.update_library()
            self.broadcast({"kind": "changed", "doc": note["id"], "text": query})
        await self.say_now(found["say"])

    def quiz_answer(self, doc_id, question, choice):
        doc = self.library.doc(doc_id)
        if not doc or doc["kind"] != "quiz":
            return False
        quiz = self.library.content(doc)
        questions = quiz.get("questions", [])
        if not (0 <= question < len(questions)) or not (0 <= choice < len(questions[question]["choices"])):
            return False
        answers = (quiz.get("answers") or []) + [None] * len(questions)
        answers = answers[:len(questions)]
        answers[question] = choice
        quiz["answers"] = answers
        self.library.write(doc, quiz)
        self.broadcast({"kind": "changed", "doc": doc["id"], "text": ""})
        return True

    # ---------- Oswald's voice ----------
    def voice_name(self):
        """The voice he speaks in: the one picked on the page, or the best British one this Mac has."""
        names = [name for name, _ in mac_voices]
        return next((name for name in [self.voice] + VOICES if name in names), None)

    def pick_voice(self, name):
        if name not in [n for n, _ in mac_voices]:
            return False
        self.voice = name
        write_json(SETTINGS_FILE, {"voice": name})
        self.broadcast(self.status())
        self.later(self.say_now("Right then. This is how I sound now."))
        return True

    async def refresh_voices(self):
        """Looks again, for voices downloaded since the hub started."""
        before, voice = list(mac_voices), self.voice_name()
        await asyncio.to_thread(find_voices)
        if mac_voices != before:
            self.broadcast(self.status())
            if self.voice_name() != voice:
                self.log("{} speaks as {} now".format(ASSISTANT_NAME, self.voice_name()))

    async def speak(self, text, talk_id):
        command = speech_command(self.voice_name())
        if not command:
            return
        self.stop_speaking()
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return
        self.speech = process
        process.stdin.write(text.encode("utf-8"))
        process.stdin.close()
        while process.poll() is None:
            if talk_id != self.talk_id:
                process.terminate()
                return
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.3)      # lets the room go quiet so he doesn't hear himself

    def stop_speaking(self):
        if self.speech and self.speech.poll() is None:
            self.speech.terminate()

    async def watch_mic(self):
        """Warns once if the mic only ever gives silence (usually a missing Mac permission)."""
        await asyncio.sleep(8)
        if self.mic.stream and not self.mic.loud_seen:
            self.log("The mic hears only silence. On the Mac: System Settings > Privacy & Security > "
                     "Microphone > turn on Terminal, then reopen Terminal.")


def add_under(note, heading, text):
    """Adds text at the end of a note, or at the end of the section under a heading."""
    lines = note.rstrip().split("\n")
    if heading:
        for i, line in enumerate(lines):
            if line.startswith("#") and heading.strip("# ").lower() in line.lower():
                level = len(line) - len(line.lstrip("#"))
                end = next((j for j in range(i + 1, len(lines))
                            if lines[j].startswith("#") and len(lines[j]) - len(lines[j].lstrip("#")) <= level), len(lines))
                return "\n".join(lines[:end]).rstrip() + "\n\n" + text.strip() + "\n\n" + "\n".join(lines[end:]).lstrip()
    return "\n".join(lines).rstrip() + "\n\n" + text.strip() + "\n"


# =====================================================================
# The page (http://localhost:8000)
# =====================================================================

FILE_TYPES = {".html": "text/html; charset=utf-8", ".mjs": "text/javascript", ".js": "text/javascript",
              ".pdf": "application/pdf", ".md": "text/markdown; charset=utf-8", ".json": "application/json"}
MAX_UPLOAD = 100_000_000
MAX_REQUEST = 12_000_000


async def respond(writer, code, body, content_type="application/json"):
    if isinstance(body, dict):
        body = json.dumps(body)
    if isinstance(body, str):
        body = body.encode()
    writer.write("HTTP/1.1 {} OK\r\nContent-Type: {}\r\nContent-Length: {}\r\nCache-Control: no-store\r\n"
                 "Connection: close\r\n\r\n".format(code, content_type, len(body)).encode() + body)
    await writer.drain()
    writer.close()


async def send_file(writer, path):
    if not path.is_file():
        return await respond(writer, 404, {"error": "Not found"})
    await respond(writer, 200, path.read_bytes(), FILE_TYPES.get(path.suffix.lower(), "application/octet-stream"))


async def stream_events(writer):
    writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nCache-Control: no-store\r\n\r\n")
    queue = asyncio.Queue(maxsize=300)
    hub.clients.add(queue)
    queue.put_nowait(hub.status())
    hub.later(hub.refresh_voices())
    try:
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), 15)
                writer.write(("data: " + json.dumps(message) + "\n\n").encode())
            except asyncio.TimeoutError:
                writer.write(b": ping\n\n")
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        hub.clients.discard(queue)
        writer.close()


def added(doc):
    hub.update_library()
    hub.log("Added " + doc["title"])
    return {"ok": True, "doc": doc}


async def upload(name, folder, parent, data):
    try:
        kind, content, title = await asyncio.to_thread(convert, name, data)
    except ConvertError as error:
        return {"ok": False, "answer": str(error)}
    return added(hub.library.add(kind, title or Path(name).stem or "Document", content, folder, parent))


async def api(path, data):
    library = hub.library
    if path == "/api/ask":
        return hub.typed(str(data.get("question", "")))
    if path == "/api/talk":
        hub.key_toggle()
    elif path == "/api/heard":
        hub.heard_in_browser(str(data.get("text", "")).strip()[:1000])
    elif path == "/api/hearing":
        hub.browser_heard = time.monotonic()
    elif path == "/api/voice":
        if not hub.pick_voice(str(data.get("name", ""))):
            return {"ok": False, "answer": "That voice isn't on this Mac."}
    elif path == "/api/key":
        key = str(data.get("key", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9_\-.]{20,200}", key):
            return {"ok": False, "answer": "That doesn't look like an API key."}
        save_key(key)
        hub.log("Gemini key saved. {} is ready".format(ASSISTANT_NAME))
        hub.broadcast(hub.status())
    elif path == "/api/view":
        hub.set_view(data)
    elif path == "/api/texts":
        doc = library.doc(data.get("doc"))
        if doc and doc["kind"] == "pdf":
            library.set_texts(doc, [str(t)[:20000] for t in (data.get("texts") or [])][:3000])
            library.save()
    elif path == "/api/place":
        return {"ok": True, "place": library.place(str(data.get("ref", "")))}
    elif path == "/api/snap":
        hub.snaps[number(data.get("id"))] = base64.b64decode(str(data.get("data", "")).split(",")[-1])
    elif path == "/api/link":
        try:
            kind, content, title = await asyncio.to_thread(fetch_page, str(data.get("url", "")).strip())
        except ConvertError as error:
            return {"ok": False, "answer": str(error)}
        return added(library.add(kind, title, content, str(data.get("folder", "")), str(data.get("parent", "")),
                                 url=str(data.get("url", ""))))
    elif path == "/api/new":
        kind = "notes"
        title = str(data.get("title") or "New note").strip()
        text = str(data.get("text") or "")
        return added(library.add(kind, title, text or "# {}\n\n".format(title), str(data.get("folder", "")), str(data.get("parent", ""))))
    elif path == "/api/save":
        doc = library.doc(data.get("doc"))
        if not doc or doc["kind"] not in EDITABLE:
            return {"ok": False, "answer": "Only notes can be edited."}
        library.write(doc, str(data.get("text", ""))[:500_000])
        hub.update_library()
        return {"ok": True, "doc": doc}
    elif path == "/api/folder":
        folder = library.find_folder(str(data.get("name", "")).strip() or "New folder")
        hub.update_library()
        return {"ok": True, "folder": folder}
    elif path == "/api/move":
        folder, parent = data.get("folder"), data.get("parent")
        if not library.move(str(data.get("doc", "")), None if folder is None else str(folder), None if parent is None else str(parent)):
            return {"ok": False, "answer": "That document isn't in the library."}
        hub.update_library()
    elif path == "/api/rename":
        if not library.rename(str(data.get("id", "")), str(data.get("title", ""))):
            return {"ok": False, "answer": "Couldn't rename that."}
        hub.update_library()
    elif path == "/api/delete":
        if not library.delete(str(data.get("id", ""))):
            return {"ok": False, "answer": "That isn't in the library."}
        hub.update_library()
    elif path == "/api/make":
        kind = str(data.get("kind", ""))
        if kind not in KINDS:
            return {"ok": False, "answer": "Oswald can write notes, guides, summaries, quizzes and flashcards."}
        hub.later(hub.make(kind, sources=[str(d) for d in data.get("sources") or []]))
    elif path == "/api/quiz":
        if not hub.quiz_answer(str(data.get("doc", "")), number(data.get("question")), number(data.get("choice"))):
            return {"ok": False, "answer": "That isn't a quiz question."}
    elif path == "/api/quiz-reset":
        doc = library.doc(data.get("doc"))
        if doc and doc["kind"] == "quiz":
            quiz = library.content(doc)
            quiz["answers"] = [None] * len(quiz.get("questions", []))
            library.write(doc, quiz)
            hub.broadcast({"kind": "changed", "doc": doc["id"], "text": ""})
    else:
        return None
    return {"ok": True}


async def handle_request(reader, writer):
    try:
        request_line = (await reader.readline()).decode("latin-1").split()
        headers = {}
        while True:
            header = (await reader.readline()).decode("latin-1")
            if header in ("\r\n", "\n", ""):
                break
            name, _, value = header.partition(":")
            headers[name.strip().lower()] = value.strip()
        if len(request_line) < 2:
            return writer.close()
        method, target = request_line[0], request_line[1]
        path, _, query = target.partition("?")
        path = urllib.parse.unquote(path)
        length = int(headers.get("content-length") or 0)
        if length > (MAX_UPLOAD if path == "/api/upload" else MAX_REQUEST):
            return await respond(writer, 413, {"ok": False, "answer": "That file is too big."})
        body = await reader.readexactly(length) if length else b""

        if headers.get("host", "").rsplit(":", 1)[0] not in ("localhost", "127.0.0.1", "[::1]"):
            return await respond(writer, 403, {"error": "Open http://localhost instead"})
        if method == "GET":
            if path == "/":
                return await send_file(writer, HERE / "dashboard.html")
            if path == "/events":
                return await stream_events(writer)
            folder, _, name = path.strip("/").partition("/")
            if folder == "library" and re.fullmatch(r"d\d+\.(pdf|html|md|json)", name):
                return await send_file(writer, FILES / name)
            if folder == "pdfjs" and name == Path(name).name and name.endswith((".mjs", ".js")):
                return await send_file(writer, HERE / "pdfjs" / name)
        elif method == "POST" and headers.get("x-board") == "1":
            if path == "/api/upload":
                fields = urllib.parse.parse_qs(query)
                field = lambda key: fields.get(key, [""])[0]
                return await respond(writer, 200, await upload(field("name") or "Document", field("folder"), field("parent"), body))
            result = await api(path, json.loads(body or b"{}"))
            if result is not None:
                return await respond(writer, 200, result)
        await respond(writer, 404, {"error": "Not found"})
    except (ConnectionError, ValueError, asyncio.IncompleteReadError):
        writer.close()


# =====================================================================
# Start
# =====================================================================

hub = Hub()


def read_typing(loop):
    """Questions typed in this window go to Oswald."""
    for line in sys.stdin:
        loop.call_soon_threadsafe(hub.typed, line)


def ask_for_key():
    if os.environ.get("GEMINI_API_KEY") or not sys.stdin.isatty():
        return
    print("Oswald needs a Gemini API key (free at aistudio.google.com/apikey).")
    key = getpass.getpass("Paste it here and press Enter, or just press Enter to paste it on the page later: ").strip()
    if re.fullmatch(r"[A-Za-z0-9_\-.]{20,200}", key):
        save_key(key)
        print("Saved in hub/.env (it stays on this laptop).")
    elif key:
        print("That doesn't look like a key. You can paste it on the page.")


def open_page(url):
    if IS_MAC and Path("/Applications/Google Chrome.app").exists():
        subprocess.run(["open", "-a", "Google Chrome", url])
    else:
        webbrowser.open(url)


async def main():
    parser = argparse.ArgumentParser(description="Board hub")
    parser.add_argument("--port", type=int, default=8000, help="the page's port (default 8000)")
    parser.add_argument("--no-mic", action="store_true", help="don't use the laptop mic in Python (Chrome listens instead)")
    parser.add_argument("--no-browser", action="store_true", help="don't open the page")
    args = parser.parse_args()

    load_env()
    ask_for_key()
    find_voices()
    loop = asyncio.get_running_loop()
    if not args.no_mic:
        hub.mic.start(loop, hub.heard_packet)

    server = None
    for port in range(args.port, args.port + 10):
        try:
            server = await asyncio.start_server(handle_request, "localhost", port)
            break
        except OSError:
            continue
    if not server:
        sys.exit("Couldn't start the page: ports {}-{} are busy".format(args.port, args.port + 9))
    url = "http://localhost:{}".format(port)

    print("")
    print("Board hub {}".format(VERSION))
    print("  Reader:      " + url)
    print("  {:<12} {}, voice {}".format(ASSISTANT_NAME + ":", ai_label() or "needs a Gemini key (paste it on the page)",
                                        hub.voice_name() or "the computer's default"))
    print("  Mic:         " + (hub.mic.name if hub.mic.stream else hub.mic.problem))
    print("  Board:       pair \"Board\" in Bluetooth. Touch your ring finger to your thumb and ask {}".format(ASSISTANT_NAME))
    print("  Type:        a question here and press Enter")
    print("  Stop:        Ctrl+C")
    print("")

    if sys.stdin.isatty():
        threading.Thread(target=read_typing, args=(loop,), daemon=True).start()
    hub.later(hub.watch_mic())
    hub.later(hub.listen_for_keys())
    if OPEN_PAGE and not args.no_browser:
        open_page(url)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
