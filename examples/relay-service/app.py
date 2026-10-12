#!/usr/bin/env python3
"""relay-service: the darkroom example tenant (stdlib only).

A tiny notes API with token-guarded deletion, archiving, read-once
notes, a server-rendered notes page that wears its state, and a
telling page that asks to be allowed to reach this device — enough
surface to demonstrate exposures, backdrops, surfaces, and rubrics end
to end. Every attribute the pages carry is a surface a scenario proves.

The telling page is where the `[browser] push` option earns itself:
the page talks to the Push API as any page would, and the exam
supplies the push service a headless browser has none of. Nothing
here knows it is being examined — there is no flag, no bridge, and no
exam-only route behind the control.
"""

import json
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

NOTES = {}

# An exam-only bridge: when set, deletion needs no token. Off in
# production and in every exposure that is not about the bridge
# itself — darkroom.toml's [serve.defaults] keeps it at 0.
OPEN_DELETE = os.environ.get("RELAY_OPEN_DELETE", "0") == "1"


# In life this is the tenant's VAPID public key, served to the page so
# the subscription it asks for is bound to this sender alone. The
# relay never sends, so it is a constant here.
SERVER_KEY = (
    "BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJ"
    "uRSoYvGmQgIiDUcJjBuMUDrKs"
)

WORKER_JS = """\
// The page's own service worker. The exam fetches it like a browser
// does — it is simply not what answers for push under examination.
self.addEventListener('push', (event) => {
  const said = event.data ? event.data.text() : '';
  event.waitUntil(self.registration.showNotification('Relay', {body: said}));
});
"""

TELLING_PAGE = """\
<!doctype html><title>Relay Telling</title>
<main data-telling-state="unknown">
<h1>Relay Telling</h1>
<button id="ask" data-state="ready">Tell me when a note arrives</button>
<button id="stop" hidden>Stop telling me</button>
<p id="endpoint" hidden></p>
<p id="why" hidden></p>
</main>
<script>
const SERVER_KEY = "__SERVER_KEY__";
const main = document.querySelector("main");
const ask = document.getElementById("ask");
const stop = document.getElementById("stop");
const endpoint = document.getElementById("endpoint");
const why = document.getElementById("why");

function show(state, sub, reason) {
  main.dataset.tellingState = state;
  const on = state === "on";
  ask.hidden = on;
  stop.hidden = !on;
  endpoint.hidden = !on;
  if (on) endpoint.textContent = sub.endpoint;
  why.hidden = !reason;
  if (reason) why.textContent = reason;
}

const worker = () => navigator.serviceWorker.register("/relay-worker.js");

async function paint() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    return show("unsupported", null, "this browser cannot be told");
  }
  const reg = await worker();
  const sub = await reg.pushManager.getSubscription();
  if (sub) return show("on", sub);
  if (Notification.permission === "denied") {
    return show("refused", null, "this device has refused");
  }
  show("unasked");
}

ask.onclick = async () => {
  ask.dataset.state = "asking";
  const answer = await Notification.requestPermission();
  try {
    const reg = await worker();
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true, applicationServerKey: SERVER_KEY});
    show("on", sub);
  } catch (err) {
    show(answer === "denied" ? "refused" : "unanswered", null, err.name);
  } finally {
    ask.dataset.state = "ready";
  }
};

stop.onclick = async () => {
  const reg = await worker();
  const sub = await reg.pushManager.getSubscription();
  if (sub) await sub.unsubscribe();
  show("off");
};

paint();
</script>
"""


def _new_note(text, read_once=False):
    note_id = uuid.uuid4().hex[:8]
    NOTES[note_id] = {
        "id": note_id,
        "text": text,
        "token": uuid.uuid4().hex,
        "archived": False,
        "read_once": bool(read_once),
        "gone_reason": None,
    }
    return NOTES[note_id]


def _public(note):
    return {k: v for k, v in note.items() if k not in ("token", "gone_reason")}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def _note(self):
        return NOTES.get(self.path.strip("/").split("/")[-1])

    def do_POST(self):
        parts = self.path.strip("/").split("/")
        if self.path == "/notes/form":
            from urllib.parse import parse_qs

            length = int(self.headers.get("Content-Length", 0))
            data = parse_qs(self.rfile.read(length).decode())
            for text in data.get("text", []):
                _new_note(text)
            return self._page()
        if self.path == "/notes":
            body = self._body()
            note = _new_note(body.get("text", ""), body.get("read_once", False))
            return self._json(201, {**_public(note), "token": note["token"]})
        if len(parts) == 3 and parts[0] == "notes" and parts[2] == "archive":
            note = NOTES.get(parts[1])
            if note is None:
                return self._json(404, {"error": "no such note"})
            if note["gone_reason"]:
                return self._json(410, {"error": "gone", "reason": note["gone_reason"]})
            note["archived"] = True  # idempotent by construction
            return self._json(200, _public(note))
        self._json(404, {"error": "unknown route"})

    def _page(self):
        import html

        def state(n):
            if n["gone_reason"]:
                return "gone"
            return "archived" if n["archived"] else "draft"

        notes = list(NOTES.values())
        page_state = state(notes[-1]) if notes else "empty"
        items = "".join(
            f'<li data-note-id="{n["id"]}" data-archived="{str(n["archived"]).lower()}"'
            + (f' data-gone-reason="{n["gone_reason"]}"' if n["gone_reason"] else "")
            + f">{html.escape(n['text'])}</li>"
            for n in notes
        )
        body = (
            "<!doctype html><title>Relay Notes</title>"
            f'<main data-note-state="{page_state}"><h1>Relay Notes</h1>'
            '<form id="note-form" method="post" action="/notes/form">'
            '<input type="text" name="text" id="note-text">'
            '<button type="submit" id="save" data-state="ready">Save</button></form>'
            f'<ul id="notes">{items}</ul></main>'
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, content_type, text):
        body = text.encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            return self._page()
        if self.path == "/telling":
            page = TELLING_PAGE.replace("__SERVER_KEY__", SERVER_KEY)
            return self._static("text/html", page)
        if self.path == "/relay-worker.js":
            return self._static("text/javascript", WORKER_JS)
        note = self._note()
        if note is None:
            return self._json(404, {"error": "no such note"})
        if note["gone_reason"]:
            return self._json(410, {"error": "gone", "reason": note["gone_reason"]})
        public = _public(note)
        if note["read_once"]:
            note["gone_reason"] = "read"  # this read was the one
        self._json(200, public)

    def do_DELETE(self):
        note = self._note()
        if note is None:
            return self._json(404, {"error": "no such note"})
        if note["gone_reason"]:
            return self._json(410, {"error": "gone", "reason": note["gone_reason"]})
        if not OPEN_DELETE and self.headers.get("X-Note-Token") != note["token"]:
            return self._json(403, {"error": "bad token"})
        del NOTES[note["id"]]
        self._json(204, {})


HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
