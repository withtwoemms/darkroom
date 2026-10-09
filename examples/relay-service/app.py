#!/usr/bin/env python3
"""relay-service: the darkroom example tenant (stdlib only).

A tiny notes API with token-guarded deletion, archiving, read-once
notes, and a server-rendered notes page that wears its state — enough
surface to demonstrate exposures, backdrops, surfaces, and rubrics end
to end. Every attribute the page carries is a surface a scenario proves.
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

    def do_GET(self):
        if self.path == "/":
            return self._page()
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
