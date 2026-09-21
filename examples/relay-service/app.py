#!/usr/bin/env python3
"""relay-service: the darkroom example tenant (stdlib only).

A tiny notes API with token-guarded deletion — enough surface to
demonstrate drive scripts, evidence contracts, and rubrics end to end.
"""

import json
import sys
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

NOTES = {}


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

    def do_POST(self):
        parts = self.path.strip("/").split("/")
        if self.path == "/notes":
            note_id = uuid.uuid4().hex[:8]
            NOTES[note_id] = {
                "id": note_id,
                "text": self._body().get("text", ""),
                "token": uuid.uuid4().hex,
                "archived": False,
            }
            return self._json(201, NOTES[note_id])
        if len(parts) == 3 and parts[0] == "notes" and parts[2] == "archive":
            note = NOTES.get(parts[1])
            if note is None:
                return self._json(404, {"error": "no such note"})
            note["archived"] = True  # idempotent by construction
            return self._json(200, note)
        self._json(404, {"error": "unknown route"})

    def do_GET(self):
        note = NOTES.get(self.path.strip("/").split("/")[-1])
        if note is None:
            return self._json(404, {"error": "no such note"})
        public = {k: v for k, v in note.items() if k != "token"}
        self._json(200, public)

    def do_DELETE(self):
        note = NOTES.get(self.path.strip("/").split("/")[-1])
        if note is None:
            return self._json(404, {"error": "no such note"})
        if self.headers.get("X-Note-Token") != note["token"]:
            return self._json(403, {"error": "bad token"})
        del NOTES[note["id"]]
        self._json(204, {})


HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
