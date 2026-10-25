"""Pretends to be the Gemini API for the tests: chat answers, writing notes and quizzes, revising,
web research and the PDF upload. Logs every request to gemini.jsonl in the folder it's run from.
What it answers depends on the words in the question (see chat())."""
import base64, io, json, re, sys, wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1])
LOG = open("gemini.jsonl", "a")
uploads = {}
calls = {"overloaded": 0}


def text_of(request):
    return "\n".join(p.get("text", "") for turn in request.get("contents", []) for p in turn.get("parts", []))


def chat(request):
    parts = request["contents"][-1]["parts"]
    last = parts[-1]["text"]
    kinds = [p["inlineData"]["mimeType"] for p in parts if "inlineData" in p]
    words = "what does the second law say" if "audio/wav" in kinds else last.split("The user says:", 1)[-1].strip()
    w = words.lower()
    open_doc = (re.findall(r"Open now: (d\d+)", last) or [""])[0]
    tags = re.findall(r"^\[(d\d+[ps]\d+)\]", last, re.M)
    ids = re.findall(r"\b(d\d+) \"", last)
    reply = {"heard": words, "answer": "Right then: a heat engine turns heat into work.", "cites": tags[:2]}
    if ("look it up" in w or "audio/wav" in kinds) and "Passages from their documents" not in last:
        return {"heard": words, "answer": "", "look_up": "boilers fire tube"}
    if "go to" in w and tags:
        reply.update(answer="Here it is.", go=tags[0])
    elif "make notes" in w:
        reply.update(answer="Right, I'll write those notes.", make={"kind": "notes", "sources": [open_doc]})
    elif "add a note" in w:
        reply.update(answer="Added.", edit={"doc": open_doc, "how": "append", "find": "", "text": "- Boilers make steam from water."})
    elif "rewrite" in w:
        reply.update(answer="Rewriting it now.", edit={"doc": open_doc, "how": "revise", "text": "Make it shorter"})
    elif "research" in w:
        reply.update(answer="Let me look that up.", search={"query": "steam turbines", "save_to": "new"})
    elif "folder" in w:
        reply.update(answer="Done, they're in Thermodynamics.", organize={"folder": "Thermodynamics", "docs": ids})
    elif "answer is b" in w:
        reply.update(answer="That's right.", quiz_choice=2)
    elif "overload" in w and not calls["overloaded"]:
        calls["overloaded"] += 1
        return None
    return reply


def written(request):
    sources = request["contents"][-1]["parts"]
    tag = (re.findall(r"\[(d\d+[ps]\d+)\]", text_of(request)) or ["d1p1"])[0]
    schema = request.get("generationConfig", {}).get("responseSchema", {}).get("properties", {})
    if "questions" in schema:
        return json.dumps({"questions": [
            {"question": "What does a boiler make?", "choices": ["Ice", "Steam", "Coal", "Oil"], "answer": 1, "why": "It boils water.", "ref": tag},
            {"question": "What limits engine efficiency?", "choices": ["Carnot", "Newton", "Ohm", "Pascal"], "answer": 0, "why": "Carnot's limit.", "ref": tag}]})
    if "cards" in schema:
        return json.dumps({"cards": [{"front": "Boiler", "back": "Makes steam. [{}]".format(tag), "ref": "[{}]".format(tag)},
                                     {"front": "Governor", "back": "Keeps the speed steady: $\x0corall t$, **always**.", "ref": tag}]})
    return "# Notes\n\n## Engines\n- **Heat engine**: turns heat into work [{}, d1p2]\n- Efficiency has a limit: $\\eta = 1 - T_c / T_h$\n".format(tag)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, body, headers=None):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/v1beta/models"):
            return self.reply(200, {"models": [{"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                                               {"name": "models/gemini-3.8-flash-lite", "supportedGenerationMethods": ["generateContent"]}]})
        if self.path.startswith("/v1beta/files/"):
            return self.reply(200, dict(uploads[self.path.split("/v1beta/")[1]], state="ACTIVE"))
        self.reply(404, {"error": {"message": "not found"}})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/upload/v1beta/files":
            LOG.write(json.dumps({"upload": "start"}) + "\n"); LOG.flush()
            return self.reply(200, {}, {"X-Goog-Upload-URL": "http://127.0.0.1:{}/upload-session/1".format(PORT)})
        if self.path.startswith("/upload-session/"):
            name = "files/doc{}".format(len(uploads) + 1)
            uploads[name] = {"name": name, "uri": "http://127.0.0.1:{}/v1beta/{}".format(PORT, name), "mimeType": "application/pdf"}
            LOG.write(json.dumps({"upload": "data", "pdf": body[:4] == b"%PDF"}) + "\n"); LOG.flush()
            return self.reply(200, {"file": dict(uploads[name], state="PROCESSING")})
        if ":generateContent" not in self.path:
            return self.reply(404, {"error": {"message": "not found"}})
        request = json.loads(body)
        system = request.get("systemInstruction", {}).get("parts", [{}])[0].get("text", "")
        parts = request["contents"][-1]["parts"]
        entry = {"model": self.path.split("/models/")[1].split(":")[0], "system": system[:60], "rules": "You stop listening after each answer" in system,
                 "kinds": [p["inlineData"]["mimeType"] if "inlineData" in p else "file" if "fileData" in p else "text" for p in parts],
                 "text": parts[-1].get("text", ""), "all": text_of(request)[:4000], "chars": len(text_of(request)), "history": len(request["contents"]) - 1,
                 "thinking": request.get("generationConfig", {}).get("thinkingConfig"), "tools": request.get("tools")}
        for p in parts:
            if p.get("inlineData", {}).get("mimeType") == "audio/wav":
                w = wave.open(io.BytesIO(base64.b64decode(p["inlineData"]["data"])))
                entry["wav"] = [w.getframerate(), round(w.getnframes() / w.getframerate(), 2)]
        if request.get("tools"):
            entry["kind"] = "research"
            LOG.write(json.dumps(entry) + "\n"); LOG.flush()
            return self.reply(200, {"candidates": [{"content": {"parts": [{"text": "SAY: Steam turbines spin blades with steam. NOTES:\n- Parsons built one in 1884"}]},
                                                    "groundingMetadata": {"groundingChunks": [{"web": {"uri": "https://example.com/turbine", "title": "example.com"}}]}}]})
        if system.startswith("You write study material"):
            entry["kind"] = "write"
            text = written(request)
        elif system.startswith("You edit a student's"):
            entry["kind"] = "revise"
            text = "# Notes\n\nShorter now.\n"
        else:
            entry["kind"] = "chat"
            answer = chat(request)
            if answer is None:
                LOG.write(json.dumps(entry) + "\n"); LOG.flush()
                return self.reply(503, {"error": {"message": "overloaded"}})
            text = json.dumps(answer)
        LOG.write(json.dumps(entry) + "\n"); LOG.flush()
        self.reply(200, {"candidates": [{"content": {"parts": [{"text": text}]}}]})


ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
