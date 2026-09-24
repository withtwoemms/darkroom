# Drive Scripts

**Format:** TOML · **Schema version:** 1.3 · **File:** one script per
scenario, named `<anything>.drive.toml`, conventionally in the
operator home's `drives/` directory.

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
| `[browser]` *(1.3)* | table | no | browser-session options: `viewport = { width, height }` sizes the page (phone-width criteria); `webauthn = true` attaches a virtual authenticator (platform, user-verifying, presence auto-simulated) so passkey flows run headlessly — the scenario's `{base_url}` then addresses the server as `localhost`, since WebAuthn rejects IP origins |
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
| `save` | table var → path | extract values from the JSON response body: paths use `$.field.sub` form |
| `expect` | table (interpolated) | expectations (below) |

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
  digests precedes the step evidence.
- The engine writes the harness log (step names, ok/FAIL, failure
  details) beside the manifest — the builder-visible diagnostics
  channel specified in [role-hooks.md](role-hooks.md).

## Versioning

`1.0` named the document shape, the six original step kinds,
interpolation forms, and expectation keys; `1.1` added the four
browser step kinds and three browser expectation keys; `1.2` added
the `record` flag; `1.3` added the `[browser]` session table
(viewport, webauthn), literal-brace escapes, and bounded waiting
(~5s) on browser expectations — each additive, per the shared
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
