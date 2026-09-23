"""Executes docs/quickstart.md stages 1-3 so the guide cannot rot.

The file contents here are the guide's, verbatim in substance: the
quicknotes tenant, the drive script, the contract, the seeded bug,
and the shell-hook judge/builder. If a darkroom change breaks any
stage, this fails before a reader does.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

from darkroom.cli import main

APP_OK = """
import json, sys, uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

NOTES = {}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        text = json.loads(self.rfile.read(length) or b"{}").get("text", "")
        note_id = uuid.uuid4().hex[:8]
        NOTES[note_id] = {"id": note_id, "text": text}
        self._json(201, NOTES[note_id])
    def do_GET(self):
        note = NOTES.get(self.path.strip("/").split("/")[-1])
        self._json(200, note) if note else self._json(404, {"error": "gone"})

HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
"""

SEEDED_BUG = (
    'self._json(200, {"id": note["id"], "text": note["text"].upper()})'
)

DRIVE = """
scenario = "note_saved"

[[step]]
name = "save"
kind = "http"
method = "POST"
url = "{base_url}/notes"
json = { text = "first light" }
expect = { status = 201 }
save = { note_id = "$.id" }

[[step]]
name = "read_back"
url = "{base_url}/notes/{note_id}"
expect = { status = 200, body_contains = "first light" }
"""

CONTRACT = """
schema_version = "1.0"
project = "quicknotes"

[[scenario]]
name = "note_saved"

  [[scenario.requires]]
  kind = "http_transcript"
  min_count = 2
"""

JUDGE_SH = """\
#!/bin/sh
if grep -rq "first light" --include "*read_back*" "$(dirname "$1")"; then earned=100; passed=true
else earned=0; passed=false; fi
cat > "$2" <<EOF
{"run_id": "quickstart", "rubric_version": "1",
 "scenarios": [{"scenario": "note_saved", "criteria": [{
   "criterion": "reads_back", "passed": $passed,
   "points_earned": $earned, "points_possible": 100}]}]}
EOF
[ "$passed" = true ] || echo "the saved note does not read back verbatim" > "$3"
"""

BUILDER_SH = f"""\
#!/bin/sh
grep -q "verbatim" "$1" 2>/dev/null && \\
  {sys.executable} - <<'EOF'
from pathlib import Path
p = Path("app.py")
p.write_text(p.read_text().replace('note["text"].upper()', 'note["text"]'))
EOF
"""


def _make_quicknotes(root: Path) -> None:
    root.mkdir()
    (root / "app.py").write_text(
        textwrap.dedent(APP_OK).replace("python3", sys.executable)
    )
    (root / "darkroom.toml").write_text(
        textwrap.dedent(f"""
        [project]
        name = "quicknotes"

        [commands]
        serve = "{sys.executable} app.py {{port}}"
        # the guide says `darkroom drive` — the module form is the same
        # entry point without needing the console script on PATH
        test = "{sys.executable} -m darkroom.cli drive --drives drives"

        [evidence]
        dir = "evidence"
        contract = "evidence-contract.toml"
        """)
    )
    (root / "drives").mkdir()
    (root / "drives" / "note_saved.drive.toml").write_text(textwrap.dedent(DRIVE))
    (root / "evidence-contract.toml").write_text(textwrap.dedent(CONTRACT))


def test_quickstart_stages_one_through_three(tmp_path, capsys, monkeypatch):
    root = tmp_path / "quicknotes"
    _make_quicknotes(root)
    monkeypatch.chdir(root)
    monkeypatch.delenv("EVIDENCE_MODE", raising=False)
    monkeypatch.delenv("EVIDENCE_DIR", raising=False)

    # --- stage 1+2: drive is green and the contract verifies
    assert main(["drive", "--drives", "drives"]) == 0
    out = capsys.readouterr().out
    assert "note_saved:" in out and "verify: ok (contract)" in out

    # --- stage 2: the deliberate break fails at read_back, keeps evidence
    app = root / "app.py"
    working = app.read_text()
    app.write_text(
        working.replace(
            'self._json(200, note) if note else self._json(404, {"error": "gone"})',
            'self._json(404, {"error": "gone"})',
        )
    )
    assert main(["drive", "--drives", "drives"]) != 0
    logs = sorted(root.glob("evidence/runs/*/harness.log"))
    assert "FAIL" in logs[-1].read_text()
    app.write_text(working)
    capsys.readouterr()

    # --- stage 3: seed the bug, converge with shell hooks, gates appear
    app.write_text(
        working.replace(
            'self._json(200, note) if note else self._json(404, {"error": "gone"})',
            'self._json(200, {"id": note["id"], "text": note["text"].upper()}) '
            'if note else self._json(404, {"error": "gone"})',
        )
    )
    (root / "judge.sh").write_text(JUDGE_SH)
    (root / "builder.sh").write_text(BUILDER_SH)
    for script in ("judge.sh", "builder.sh"):
        (root / script).chmod(0o755)
    (root / ".gitignore").write_text("evidence/\n")
    subprocess.run(["git", "init", "-q"], check=True)
    for key, value in (
        ("user.email", "quick@example.com"),
        ("user.name", "quick"),
        ("commit.gpgsign", "false"),
    ):
        subprocess.run(["git", "config", key, value], check=True)
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(["git", "commit", "-qm", "quicknotes"], check=True)

    code = main([
        "auto", "--scenario", "note_saved",
        "--judge-cmd", "./judge.sh {manifest} {evaluation_out} {feedback_out}",
        "--build-cmd", "./builder.sh {feedback}",
    ])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "iteration 1: 0.0" in out
    assert "CONVERGED" in out
    assert (root / "evidence-gates.json").exists()
    assert 'note["text"].upper()' not in app.read_text()  # builder fixed it
