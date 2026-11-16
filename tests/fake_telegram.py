"""A stand-in for api.telegram.org: records sent messages, serves queued updates."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "123456:TEST-TOKEN"


class Fake:
    def __init__(self):
        self.sent, self.updates, self.fail_next, self.n = [], [], None, 0
        self.edits, self.answers, self.commands = [], [], []
        self.lock = threading.Lock()

    def push(self, chat_id, text, username="tester"):
        with self.lock:
            self.n += 1
            self.updates.append({"update_id": self.n, "message": {"chat": {"id": chat_id, "type": "private"}, "from": {"username": username}, "text": text}})

    def push_callback(self, chat_id, data, message_id=42):
        with self.lock:
            self.n += 1
            self.updates.append({"update_id": self.n, "callback_query": {"id": f"cb{self.n}", "data": data, "message": {"message_id": message_id, "chat": {"id": chat_id, "type": "private"}}}})

    def last_markup(self, chat_id):
        for m in reversed(self.sent):
            if str(m["chat_id"]) == str(chat_id) and m.get("reply_markup"):
                return m["reply_markup"]

    def texts(self, chat_id):
        return [m["text"] for m in self.sent if str(m["chat_id"]) == str(chat_id)]


FAKE = Fake()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # test control: /__sent
        data = json.dumps(FAKE.sent).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        method = self.path.rsplit("/", 1)[-1]
        if self.path == "/__push":
            FAKE.push(body["chat_id"], body["text"], body.get("username", "tester"))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        out, code = {"ok": True, "result": True}, 200
        if f"/bot{TOKEN}/" not in self.path:
            out, code = {"ok": False, "error_code": 401, "description": "Unauthorized"}, 401
        elif method == "getMe":
            out = {"ok": True, "result": {"username": "zadachi_test_bot"}}
        elif method == "getUpdates":
            if body.get("timeout") and not [u for u in FAKE.updates if u["update_id"] >= body.get("offset", 0)]:
                time.sleep(1)  # a real long poll waits; this keeps a running app from spinning
            with FAKE.lock:
                out = {"ok": True, "result": [u for u in FAKE.updates if u["update_id"] >= body.get("offset", 0)]}
        elif method == "editMessageText":
            FAKE.edits.append(body)
        elif method == "answerCallbackQuery":
            FAKE.answers.append(body)
        elif method == "setMyCommands":
            FAKE.commands = body.get("commands", [])
        elif method == "sendMessage":
            if FAKE.fail_next:
                (code, desc), FAKE.fail_next = FAKE.fail_next, None
                out = {"ok": False, "error_code": code, "description": desc}
            else:
                FAKE.sent.append(body)
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start() -> str:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


if __name__ == "__main__":  # standalone for manual and browser tests: python3 tests/fake_telegram.py
    srv = ThreadingHTTPServer(("127.0.0.1", 9911), H)
    print("fake telegram on :9911", flush=True)
    srv.serve_forever()
