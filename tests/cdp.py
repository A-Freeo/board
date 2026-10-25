"""Drives Google Chrome for the page tests, with nothing to install: Chrome's DevTools protocol
over a small WebSocket client. Chrome runs headless with its own empty profile."""
import base64, json, os, shutil, socket, subprocess, tempfile, time, urllib.request

CHROME_PATHS = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium", "google-chrome", "chromium"]
KEYS = {"PageDown": 34, "PageUp": 33, "ArrowRight": 39, "ArrowLeft": 37, "F18": 129, "Escape": 27, "Enter": 13}


def find_chrome():
    for path in CHROME_PATHS:
        if os.path.exists(path) or shutil.which(path):
            return path
    return None


class Browser:
    def __init__(self, width=1440, height=900, port=9333):
        self.profile = tempfile.mkdtemp()
        self.process = subprocess.Popen([find_chrome(), "--headless=new", "--remote-debugging-port={}".format(port),
                                         "--user-data-dir=" + self.profile, "--window-size={},{}".format(width, height),
                                         "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                         "--no-first-run", "--no-default-browser-check", "about:blank"],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                pages = json.loads(urllib.request.urlopen("http://127.0.0.1:{}/json/list".format(port)).read())
                url = next(p["webSocketDebuggerUrl"] for p in pages if p["type"] == "page")
                break
            except Exception:
                time.sleep(0.1)
        host, _, path = url[len("ws://"):].partition("/")
        name, _, number = host.partition(":")
        self.sock = socket.create_connection((name, int(number)))
        self.sock.sendall("GET /{} HTTP/1.1\r\nHost: {}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                          "Sec-WebSocket-Key: {}\r\nSec-WebSocket-Version: 13\r\n\r\n".format(
                              path, host, base64.b64encode(os.urandom(16)).decode()).encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.sock.recv(1)
        self.next_id = 0
        self.events = []
        self.errors = []
        self.send("Page.enable")
        self.send("Runtime.enable")
        self.send("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=width < 600)

    def _read(self, count):
        data = b""
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise ConnectionError("Chrome closed the connection")
            data += chunk
        return data

    def _message(self):
        parts = b""
        while True:
            first, second = self._read(2)
            length = second & 127
            if length == 126:
                length = int.from_bytes(self._read(2), "big")
            elif length == 127:
                length = int.from_bytes(self._read(8), "big")
            parts += self._read(length)
            if first & 0x80:
                return json.loads(parts.decode())

    def send(self, method, **params):
        self.next_id += 1
        data = json.dumps({"id": self.next_id, "method": method, "params": params}).encode()
        mask = os.urandom(4)
        header = bytes([0x81]) + (bytes([0x80 | len(data)]) if len(data) < 126 else
                                  bytes([0x80 | 126]) + len(data).to_bytes(2, "big") if len(data) < 65536 else
                                  bytes([0x80 | 127]) + len(data).to_bytes(8, "big"))
        self.sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        while True:
            message = self._message()
            if message.get("id") == self.next_id:
                if "error" in message:
                    raise RuntimeError("{}: {}".format(method, message["error"]))
                return message.get("result", {})
            self.events.append(message)
            if message.get("method") == "Runtime.exceptionThrown":
                details = message["params"]["exceptionDetails"]
                self.errors.append((details.get("exception") or {}).get("description") or details.get("text"))

    def go(self, url):
        self.send("Page.navigate", url=url)
        self.wait("document.readyState === 'complete'")

    def js(self, expression):
        result = self.send("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in result:
            raise RuntimeError("JS: {}".format(result["exceptionDetails"].get("exception", {}).get("description")))
        return result.get("result", {}).get("value")

    def wait(self, expression, seconds=8):
        end = time.time() + seconds
        while time.time() < end:
            try:
                if self.js(expression):
                    return True
            except RuntimeError:
                pass
            time.sleep(0.1)
        return False

    def key(self, name, text=None):
        code = KEYS.get(name, ord(name.upper()) if len(name) == 1 else 0)
        base = {"key": name, "code": name if len(name) > 1 else "Key" + name.upper(), "windowsVirtualKeyCode": code}
        self.send("Input.dispatchKeyEvent", type="keyDown", text=text or "", **base)
        self.send("Input.dispatchKeyEvent", type="keyUp", **base)

    def click(self, selector):
        return self.js("(() => { const n = document.querySelector(" + json.dumps(selector) + "); if (!n) return false; n.click(); return true; })()")

    def upload(self, selector, paths):
        node = self.send("Runtime.evaluate", expression="document.querySelector({})".format(json.dumps(selector)))["result"]
        self.send("DOM.setFileInputFiles", files=paths, objectId=node["objectId"])

    def screenshot(self, path):
        with open(path, "wb") as file:
            file.write(base64.b64decode(self.send("Page.captureScreenshot", format="png")["data"]))

    def close(self):
        self.process.terminate()
        self.process.wait()
        shutil.rmtree(self.profile, ignore_errors=True)
