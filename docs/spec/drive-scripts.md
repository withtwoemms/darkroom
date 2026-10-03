# Drive Scripts

**Format:** TOML · **Schema version:** 1.7 · **File:** one script per
scenario, named `<anything>.drive.toml`, conventionally in the
operator home's `drives/` directory.

> **Deprecated as a standalone file since darkroom 0.20.** The drive
> script's step vocabulary lives on unchanged as the exposure half of a
> [proof](proofs.md), which holds the steps and the criteria that score
> them in one sealed file. Existing drive scripts and vault rubrics keep
> working; `darkroom migrate` merges each pair into a proof, and a home
> holding proofs is read as proofs. Everything below — step kinds,
> fields, interpolation, expectations — continues to version here and
> applies to proofs verbatim.

## Purpose

A drive script is the exam as data: a declarative step sequence that
drives the system under test as a black box over its real interfaces
(HTTP, CLI), capturing every exchange as ordinary evidence. The
engine executing it is a distributed package, the script is
operator-side data, and the tenant contains no harness — the examinee
cannot edit the exam.

## Trust position

Authored and held **operator-side**; the builder never reads drive
scripts. What the builder learns of the exam comes from two sanitized
channels: the scenario specs (which state the behaviors) and the
harness log (step names and failure details — see
[role-hooks.md](role-hooks.md)). Step names and failure details are
spec-level information; a script whose step names or details would
reveal criteria or scoring is misauthored.

## Document shape

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `scenario` | string | yes | the scenario this script exercises |
| `[serve]` | table | no | variables substituted into the adapter's serve command / container env |
| `record` *(1.2)* | boolean (default false) | no | browser scenarios only: record a screencast of the whole scenario, registered as one `video` evidence item (step `screencast`) at teardown |
| `[browser]` *(1.3)* | table | no | browser-session options: `viewport = { width, height }` sizes the page (phone-width criteria); `webauthn = true` attaches a virtual authenticator (platform, user-verifying, presence auto-simulated) so passkey flows run headlessly — the scenario's `{base_url}` then addresses the server as `localhost`, since WebAuthn rejects IP origins; `prf` *(1.6, default true)* gives that authenticator the WebAuthn PRF extension so a ceremony can return per-salt secrets, and `prf = false` models an authenticator without it |
| `[[step]]` | array of tables | yes | the steps, executed in order |

Every step carries:

| Field | Type | Required | Meaning |
|-------|------|----------|---------|
| `name` | string | no (default: the kind) | step name; becomes the evidence item's `step` |
| `kind` | string | no (default `"http"`) | one of the step kinds below |

## Step kinds

### `http`

Performs a request against the system under test; the full exchange
is captured as `http_transcript` evidence.

| Field | Type | Meaning |
|-------|------|---------|
| `url` | string (interpolated) | request URL; `{base_url}` is the booted server |
| `method` | string (default `GET`) | HTTP method |
| `headers` | table (interpolated) | request headers |
| `json` | any (interpolated) | JSON request body; sets `Content-Type: application/json` unless given |
| `body` *(1.4)* | string (interpolated) | raw request body, sent verbatim with no content type implied — for exact-bytes scenarios (a webhook's HMAC over the payload); mutually exclusive with `json` |
| `follow_redirects` *(1.5)* | bool (default `true`) | when `false`, a 3xx is the response the step records — its status and `Location` header — rather than what following it led to; the transcript's `request.follow_redirects` records the choice |
| `session` *(1.5)* | `"browser"` | send the scenario's browser-session cookies for this URL (an explicit `Cookie` header wins), so the request acts as whoever the browser signed in; the scenario then gets a browser session even without browser steps |
| `save` | table var → path | extract values from the JSON response body: paths use `$.field.sub` form; a segment may index an array, `$.items[0].id` or `$.receipts[-1].who` *(1.7)* |
| `expect` | table (interpolated) | expectations (below) |

`session = "browser"` is one-way: the browser's cookies reach the
request, but the response's `Set-Cookie` does not reach the browser.
Before 1.5 an exam that needed to act as a signed-in member from an
http step needed a tenant-side bridge (a header the app honored only
under a test flag) — auth machinery in production code for the exam's
benefit. Now the exam signs in through the browser like a person
does, and the http step borrows that identity.

### `command`

Runs a command via the command-transcript producer.

| Field | Type | Meaning |
|-------|------|---------|
| `argv` | array of strings (interpolated) | exec form |
| `cmd` | string (interpolated) | shell form (`sh -c`); one of `argv`/`cmd` is required |
| `expect` | table | expectations (below) |

### `keygen`

Generates Ed25519 key pairs (requires the `crypto` extra). No
evidence item; populates the interpolation context.

| Field | Type | Meaning |
|-------|------|---------|
| `names` | array of strings | for each `n`: `{keys.n.public}` (base64 raw public key) becomes available, and `sign(keys.n, ...)` can sign with the private key, which never leaves the engine |

### `assert`

Evaluates a simple comparison over interpolated values; captured as
`log` evidence recording the expression, its resolution, and the
outcome.

| Field | Type | Meaning |
|-------|------|---------|
| `that` | string (interpolated) | exactly one `==` or `!=` between two values; surrounding whitespace is trimmed |

### `wait`

| Field | Type | Meaning |
|-------|------|---------|
| `seconds` | number (default 1) | sleep |

### `container`

Container mode only: failure injection against a running scenario
environment; captured as `log` evidence.

| Field | Type | Meaning |
|-------|------|---------|
| `action` | string | `stop`, `start`, `pause`, or `unpause` |
| `service` | string | a declared service name, or `app` |

### Browser steps *(since 1.1)*

`goto`, `click`, `fill`, and `screenshot` drive a real browser
(engines need the Playwright extra and an installed chromium). A
scenario containing any browser step gets **one fresh browser
session** for its duration, booted alongside the served system —
the visual counterpart of the fresh-environment rule. Actions are
captured as `log` evidence; screenshots as `screenshot` evidence via
the ordinary producer, so browser steps introduce **no new evidence
kind**.

`goto`:

| Field | Type | Meaning |
|-------|------|---------|
| `url` | string (interpolated) | page to navigate to |

`click`:

| Field | Type | Meaning |
|-------|------|---------|
| `selector` | string (interpolated) | element to click |

`fill`:

| Field | Type | Meaning |
|-------|------|---------|
| `fields` | table selector → value (both interpolated) | form fields to fill, in order |

`screenshot`:

| Field | Type | Meaning |
|-------|------|---------|
| `full_page` | boolean (default false) | capture the full page rather than the viewport |

A browser-level failure (timeout, missing selector, navigation
error) is an ordinary step failure — the scenario stops, its
evidence is kept.

## Interpolation

String values marked *interpolated* substitute, at execution time:

- `{base_url}` — the booted server's origin;
- `{name}` — any value placed by a `save` extraction or the serve
  table's substitutions;
- `{keys.<n>.public}` — a generated public key;
- `{sign(keys.<n>, <var>)}` — the base64 Ed25519 signature of
  variable `<var>`'s value under key `<n>`.

An unknown placeholder is an error, not empty text. *(1.3)* `{{`
and `}}` are literal-brace escapes — shell fragments like curl's
`%{http_code}` are written `%{{http_code}}` and resolve to literal
braces after substitution. `expect` tables
are interpolated like any other value, so expectations can reference
saved values.

## Expectations

An `expect` table may check:

| Key | Applies to | Meaning |
|-----|-----------|---------|
| `status` | http, goto | exact response status |
| `status_in` | http | status is one of the listed values |
| `exit_code` | command | exact exit code |
| `body_contains` | http, command, browser steps | substring of the response body, stdout, or live page content |
| `title_contains` *(1.1)* | browser steps | substring of the page title |
| `url_contains` *(1.1)* | browser steps | substring of the current page URL |
| `selector_visible` *(1.1)* | browser steps | the selector resolves to a visible element |
| `location_contains` *(1.5)* | http | substring of the response's `Location` header — the witness for a redirect's target (pair with `follow_redirects = false`; a followed redirect has no `Location` left to check) |

### Expectation witnesses *(since 1.4)*

Every step carrying an `expect` table also records what it checked
and what it found, as a `log` item named `<step>.expect`:

```json
{"expect": {"status": 200, "selector_visible": "#join"},
 "found": {"status": 200, "selector_visible": true}, "ok": true}
```

`status` and `exit_code` record the actual value; `title`, `url`, and
`location` the actual string; `body_contains` and `selector_visible`
a boolean.
An enforced check the judge cannot see is not evidence — before 1.4,
a `goto` whose `expect` required a selector gated the run but left
nothing in the record, so a rubric could not cite it. Since 1.4 such
a step is a witness in its own right.

A witness records the expected value as well as the found one. A
judge that searches evidence for expected text must therefore scope
to transcripts (or read `found`/`ok`) — matching the needle inside a
witness is a vacuous pass, not proof.

## Execution semantics

- **Fresh environment per scenario**: the engine boots the system
  under test (a process, or containers in container mode) per
  script, waits for health, runs the steps, and tears down —
  hermetic state, no cross-scenario contamination.
- **Failure stops the scenario, not the drive**: a step whose
  expectation fails (or that errors) ends its scenario; later steps
  are skipped, later scenarios still run. Evidence captured before
  the failure is kept — **a failing scenario is still judgeable,
  which is the point**.
- A scenario that cannot even boot is recorded as a failed scenario
  (a single failed `serve` step), never as a failed drive.
- In container mode, an `environment` log item recording image
  digests precedes the step evidence. In process mode, an adapter
  that declares `[[environment.services]]` gets each service as a
  fresh container per scenario beside the process-booted app (since
  engine 0.19): the service's mapped address reaches the serve
  command as `{name.host}` / `{name.port}` — and to the drive's own
  steps as the same placeholders (0.19.1), so a scenario that re-boots
  the app in place can address the services the engine started — a
  TCP probe waits for a declared port before the app boots, the
  containers stop with the server, and the same `environment` log
  item records their digests.
  A scenario's database is therefore as hermetic as its process.
- The engine writes the harness log (step names, ok/FAIL, failure
  details) beside the manifest — the builder-visible diagnostics
  channel specified in [role-hooks.md](role-hooks.md).

## Versioning

`1.0` named the document shape, the six original step kinds,
interpolation forms, and expectation keys; `1.1` added the four
browser step kinds and three browser expectation keys; `1.2` added
the `record` flag; `1.3` added the `[browser]` session table
(viewport, webauthn), literal-brace escapes, and bounded waiting
(~5s) on all page-settling browser expectations (`title_contains`,
`url_contains`, `body_contains`, `selector_visible`); `1.4` added the raw `body` field on `http` steps and expectation witnesses (every step with an `expect` logs a `<step>.expect` record of what it checked and found); `1.5` added `follow_redirects` and `session` on `http` steps and the `location_contains` expectation; `1.6` added `prf` on the `[browser]` table; `1.7` added array indexes in `save`/expectation paths — each additive, per the shared
policy, so every earlier script remains valid. New step
kinds, fields, or expectation keys arrive as minor bumps; consumers
(engines) MUST refuse unknown step kinds loudly rather than skip
them — a silently skipped step would make an exam pass vacuously.

## Example

```toml
scenario = "note_created"

[serve]
ttl = "60"

[[step]]
name = "create"
kind = "http"
method = "POST"
url = "{base_url}/notes"
json = { text = "first" }
save = { note_id = "$.id" }
expect = { status = 201 }

[[step]]
name = "fetch"
url = "{base_url}/notes/{note_id}"
expect = { status = 200, body_contains = "first" }
```

## Conformance

- Engines MUST execute steps in order, stop a scenario at its first
  failure, keep already-captured evidence, and continue with later
  scenarios.
- Engines MUST boot a fresh environment per scenario and MUST error
  on unknown placeholders and unknown step kinds.
- Engines MUST capture each step through the corresponding evidence
  producer so a drive run yields a conforming manifest.
- Private keys generated by `keygen` MUST NOT be written to evidence,
  logs, or the context's exported values.
- Scripts MUST NOT contain criteria, points, or scoring information;
  they live operator-side and are never shown to the builder.
