# Quickstart

Four stages, about fifteen minutes. Each stage pays off on its own
before asking for more: first you *see evidence*, then you meet the
exam, then you watch the convergence loop run for free, and only then
do you point real agents at a real project. Every block is
copy-paste runnable; stages 1–3 are executed verbatim by darkroom's
own CI, so this guide cannot silently rot.

Prerequisites: Python 3.10+, `git`. Stage 4 additionally wants the
`claude` CLI (or any agent CLI you template in).

```bash
pip install darkroom-ai
```

## Stage 1 — First evidence (2 minutes)

Make a tiny project — a stdlib notes API, nothing to install:

```bash
mkdir quicknotes && cd quicknotes
```

`app.py`:

```python
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
```

`darkroom.toml` — the adapter: run-me facts about your project, and
nothing more:

```toml
[project]
name = "quicknotes"

[commands]
serve = "python3 app.py {port}"
test = "darkroom drive --drives drives"

[evidence]
dir = "evidence"
contract = "evidence-contract.toml"
```

`drives/note_saved.drive.toml` — a drive script: the exam as data.
darkroom boots your app fresh, runs the steps against it as a black
box, and captures every exchange:

```toml
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
```

Run it, then look at what was captured:

```bash
darkroom drive --drives drives
darkroom gallery evidence/runs/*/manifest.json
```

You have a **manifest** — an inventory of typed evidence (here, two
HTTP transcripts), the artifact everything else in darkroom judges,
diffs, and gates on — and a gallery page rendering it.

## Stage 2 — The exam (3 minutes)

Declare what a run *must* capture. `evidence-contract.toml`:

```toml
schema_version = "1.0"
project = "quicknotes"

[[scenario]]
name = "note_saved"

  [[scenario.requires]]
  kind = "http_transcript"
  min_count = 2
```

`darkroom drive` now verifies each run against the contract (you saw
`verify: ok (contract)` already — the adapter points at it). Now
break the app on purpose — in `app.py`, make `do_GET` always miss:

```python
    def do_GET(self):
        self._json(404, {"error": "gone"})
```

```bash
darkroom drive --drives drives ; cat evidence/runs/*/harness.log | tail -3
```

The scenario fails at `read_back` — and the evidence captured before
the failure is kept. **A failing scenario is still judgeable**: that
is the design, because a judge needs to see what *did* happen. The
harness log carries the step-level record. Restore `do_GET` before
moving on.

## Stage 3 — The loop, for free (5 minutes)

The convergence loop — assess, judge, build, checkpoint, repeat — is
usually driven by agents, but the roles are just commands honoring a
file contract. So you can watch the whole state machine converge with
two shell scripts and zero spend.

Seed a bug (in `app.py`, `do_GET` again):

```python
    def do_GET(self):
        note = NOTES.get(self.path.strip("/").split("/")[-1])
        if note is None: return self._json(404, {"error": "gone"})
        self._json(200, {"id": note["id"], "text": note["text"].upper()})
```

`judge.sh` — greps the run's evidence, writes an evaluation and
builder feedback:

```sh
#!/bin/sh
# args: manifest evaluation_out feedback_out
if grep -rq "first light" --include "*-read_back.json" "$(dirname "$1")"; then earned=100; passed=true
else earned=0; passed=false; fi
cat > "$2" <<EOF
{"run_id": "quickstart", "rubric_version": "1",
 "scenarios": [{"scenario": "note_saved", "criteria": [{
   "criterion": "reads_back", "passed": $passed,
   "points_earned": $earned, "points_possible": 100}]}]}
EOF
[ "$passed" = true ] || echo "the saved note does not read back verbatim" > "$3"
```

> Note the `--include` pattern: it names the `read_back` *transcript*
> file exactly. Since drive-scripts 1.4 every step with an `expect` also
> leaves a witness file (`…-read_back.expect.json`) recording what the
> expectation checked and found — including the expected text itself. A
> judge that greps `*read_back*` would match that witness and pass
> vacuously, exactly the hazard this stage is about. Search transcripts,
> or read the witness's `found`/`ok` fields; never grep for the needle
> across everything.

`builder.sh` — "fixes" the app when the feedback says so:

```sh
#!/bin/sh
# args: feedback
grep -q "verbatim" "$1" 2>/dev/null && \
  python3 - <<'EOF'
from pathlib import Path
p = Path("app.py")
p.write_text(p.read_text().replace('note["text"].upper()', 'note["text"]'))
EOF
```

The loop wants a clean git tree (it makes checkpoints):

```bash
chmod +x judge.sh builder.sh
printf 'evidence/\n' > .gitignore
git init -q && git add -A && git commit -qm "quicknotes"

darkroom auto --scenario note_saved \
  --judge-cmd  './judge.sh {manifest} {evaluation_out} {feedback_out}' \
  --build-cmd  './builder.sh {feedback}'
```

Watch it: iteration 1 scores 0.0, the builder gets the feedback and
fixes the bug, iteration 2 scores 100.0, **CONVERGED**, and
`evidence-gates.json` appears — the scenario's peak score, ratcheted:
future runs below it are regressions. `git log` shows the loop's
checkpoints. Everything the agents will do in stage 4 slots into
exactly this machine.

## Stage 4 — The real thing (real agents, real spend)

Now the roles become agents, and the judge's criteria become
something the builder never sees.

```bash
darkroom home init          # ~/.darkroom/projects/<name>/ — operator space, mode 700
```

1. **Author scenarios and rubrics** with the interview skill
   (the `darkroom-interview` skill (`darkroom skills install`, or the plugin) — run it in Claude Code from your
   project). It interrogates your product description into scenarios,
   criteria with thresholds, and preflight-validated artifacts.
2. **Seal the rubrics** out of the tenant and derive the contract
   from them: `darkroom vault seal && darkroom vault derive-contract`.
3. **Move the exam out of the tenant.** Stages 1–3 kept `drives/` in
   the repo because nothing was reading it but you; from here on the
   builder is an agent working in that repo, and a drive script it
   can open is an exam it can read. The home has a place for them,
   and it is where `darkroom drive` looks when `--drives` is absent:

   ```bash
   git rm -rq --cached drives && mv drives ~/.darkroom/projects/quicknotes/drives
   ```

   then drop `--drives drives` from the `test` command in
   `darkroom.toml` (`test = "darkroom drive"`) and commit. Once the
   rubrics are sealed (or an `operator.toml` exists), `darkroom
   preflight` warns about drive scripts still inside the tenant and
   `darkroom auto` refuses to spend against them.
4. **Write the operator config** — `~/.darkroom/projects/<name>/operator.toml`:

```toml
[judge]
model = "claude-opus-5"

[builder]
model = "claude-sonnet-5"
escalated_model = "claude-opus-5"

[loop]
max_iterations = 6
```

5. **Run it**: `darkroom auto --scenario <name> --operator ~/.darkroom/projects/<name>/operator.toml`
   (with `operator.toml` in the home, `--operator` is discovered
   automatically). Iteration budgets are spend caps; the builder
   starts cheap and escalates only on stagnation.
6. **Read the record**: `darkroom dossier` — iterations, score
   trajectories, gates, and the metered cost of every agent call.

A note on spend: each iteration is one judge call and one builder
call. Start with one scenario and a small `max_iterations`.

**Credentials, and which side of the boundary each lives on.** The
sealed-exam design has one boundary: the builder must never read the
exam (rubrics, drives, loop state). Credentials sort by that rule:

- *The agent CLI's own login* (`claude` authenticates through its own
  keychain login or `ANTHROPIC_API_KEY`) belongs to the operator's
  shell, and the judge and builder inherit it — they are the
  operator's agents and authenticate as such. It is not part of the
  exam, so its visibility to the builder is expected. Keep it out of
  the tenant: never in `darkroom.toml`, `.env`, or anything committed.
- *The rubric vault* (the OpenBao backend) is where the boundary is
  enforced by policy, not by hiding. Give each role its own token and
  keep the rubric path out of the builder's policy — with `[vault]
  path = "darkroom/quicknotes"` on the `secret` KV v2 mount:

  ```hcl
  # operator.hcl — darkroom reads rubrics with this and inlines them
  # into the judge's prompt; the judge itself never touches the vault
  path "secret/data/darkroom/quicknotes/*"     { capabilities = ["read", "list"] }
  path "secret/metadata/darkroom/quicknotes/*" { capabilities = ["read", "list"] }

  # builder.hcl — whatever the tenant's work needs, and never the exam
  path "secret/data/darkroom/*"     { capabilities = ["deny"] }
  path "secret/metadata/darkroom/*" { capabilities = ["deny"] }
  path "secret/data/quicknotes/*"   { capabilities = ["read"] }
  ```

  The operator's token is `BAO_TOKEN` in the shell that runs
  `darkroom auto`, nowhere else; the engine strips `BAO_TOKEN` /
  `VAULT_TOKEN` from every agent subprocess so it can never reach a
  role by inheritance. A builder that needs the vault gets its own
  token, handed over explicitly in its invoke template — `invoke =
  "BAO_TOKEN=$BUILDER_BAO_TOKEN claude …"` — which is precisely a
  credential the builder is allowed to hold, because its policy says
  what it can reach.
- *Everything in the darkroom home* (`operator.toml`, the vault, the
  drives, loop state) is mode 700 and outside every tenant path; the
  builder is invoked with the tenant as its working directory and
  `--add-dir` only for what a role needs.

The usual ceiling applies: this protects the exam from a builder that
follows its instructions and from other users on the machine, not from
a same-UID process that escapes its sandbox — for that, the OpenBao
backend's server-side audit is the graduation path.

## Where to go next

- **Browser steps** — drive real pages (`goto`/`click`/`fill`/
  `screenshot`), screencast whole scenarios (`record = true`), set
  phone-width viewports, and run headless passkey ceremonies
  (`[browser] webauthn = true`): `pip install 'darkroom-ai[playwright]'`,
  then see the UI slice in `examples/relay-service/`.
- **Hardened backends** — containers for the system under test
  (`[containers]` extra) and an OpenBao rubric vault (`[vault]`).
- **Pytest users**: the plugin gives any existing suite an `evidence`
  fixture and manifest-backed runs — no drive scripts required.
- **The formats** — `docs/spec/`: every artifact above is a written,
  versioned format any harness can emit.
- **The arc** — `ROADMAP.md`, and `docs/vision.md` for where this is
  headed.
