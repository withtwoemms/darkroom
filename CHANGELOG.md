# Changelog

All notable changes to this project are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [semantic versioning](https://semver.org/) (pre-1.0: minor
releases may break API, patch releases never do). The manifest schema is
versioned independently of the package — see `ROADMAP.md`.

## [0.20.4] - 2026-10-07

### Fixed

The converge skill now says what a first campaign on a new feature is
for: a publication to align to, not a gate — read exhaustion at zero
for the `.surfaces` it produced, realign, relaunch.

Four audit-precision defects, all surfaced by the first scenario posed
against a backdrop:

- **A backdrop's surfaces belong to the scenario that owns it.** Steps
  a backdrop contributes are marked on expansion and left out of the
  posing scenario's cross-check; the founding's `/setup` no longer
  shows as unpublished on every scenario founded by Dad.
- **A run-time path is not addressable.** A `goto`/`http` whose whole
  path is a saved value (`{base_url}{request_link}`) names nothing the
  audit can check and is skipped; the route that minted the value was
  already touched.
- **Attribute values never decide a selector match.** The publication
  names the attribute (`#admit-agent[data-institution]`); the exposure
  narrows to its value; they are one surface.
- **A published command's placeholders match the words run.** `ID=…`
  matches `ID=acme`, `…`/`*` match any word, and quoted words
  (`NAME='Acme Bank'`) are one word.

## [0.20.3] - 2026-10-06

### Added

- **The `darkroom-author` skill**: authoring or repairing a proof in
  the 0.20 shape — the rubric under product's hat, the exposure under
  QA's, posed against backdrops, bound to the published surfaces — and
  the discipline for bringing a migrated corpus up to style: backdrop
  extraction (name for the state left, lift verbatim, no witness in a
  backdrop, prove nothing moved) and rubric rewrites in product's
  words (keep thresholds, drop step names and codes, `version` stays
  unless the schema moved). Five skills ship with the engine.

### Fixed

- **A shell-script command step is not a command surface.** A `command`
  whose `cmd` carries pipes, heredocs, `;`, `&&`, `nohup`, `pkill`, or
  a newline is QA's harness (a stub server, a restart), not something
  the build exposes; `darkroom surfaces --merge` had published one
  tenant's 40-line Stripe stub as a command.
- **Preflight knows the proofs derive the contract.** `no-contract`
  fired on every tenant that had retired its declared file; it now
  fires only when there are no proofs in the home either.

## [0.20.2] - 2026-10-06

### Added

- **`darkroom surfaces [--merge] [--check] [--scenario]`**: a baseline
  publication for scenarios the builder has not touched — a
  `.surfaces` drafted from the addresses the scenario's exposure
  reaches on the current build (descriptions blank, the notes saying
  it is a draft), or with `--merge` the unpublished addresses added to
  an existing file, its lines kept verbatim. The audit then holds every
  exposure to something real instead of warning about the whole corpus;
  engineering describes and prunes as it goes.
- **`[evidence] keep_runs = N`**: after each drive the evidence run
  directories are pruned to the newest N, keeping any run a gate cites.
  Unset keeps everything, as before.
- **`darkroom status` names how the agents are billed.** The bundle
  carries `metering` (auth method, subscription, whether an API key is
  in the environment) and the report's last section is now *metered
  equivalent*: the CLI's `cost_usd` is the API list price of the tokens
  used, which is a charge only when the CLI runs on an API key; under a
  claude.ai login it is a reference figure drawn against the plan.
- **Preflight `container-runtime`** (info): names the colima docker
  host and the Ryuk socket override the engine will set.

### Changed

- **`darkroom audit` output has a shape**: findings grouped by scenario,
  each with its code, and a per-code tally after the totals.
- **`darkroom vault move`** is the name for moving a filesystem vault's
  rubrics to the configured backend; `vault migrate` still works.
- A rubric's `version` bumps for a change to its schema — criteria,
  ids, points, witnesses, trials, stated thresholds — never for a
  rewording (docs/spec/proofs.md).

### Fixed

- **Servers an exposure restarts itself no longer outlive the run.**
  After the process-group stop, whatever still listens on the
  scenario's port is swept — a `nohup uvicorn …` from a restart step
  lives outside the group the engine signals and left one pair behind
  every full run.
- **colima needs no incantation.** When the docker host is a colima
  socket and nothing has set `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE`,
  the engine sets it to `/var/run/docker.sock` before the first
  container; without it Ryuk fails in seconds (`mkdir …/docker.sock:
  operation not supported`) and every service boot with it.

## [0.20.1] - 2026-10-06

### Fixed

- **The builder was never told to publish its surfaces.** The judge
  read them and the audit checked them, but the builder's prompt said
  nothing — so the first 0.20 slice converged with no `.surfaces`
  written. The builder's ground rules now say what the file is, its
  five sections and columns, when to create and amend it, and that
  its prose is for the people writing and judging the exam, never an
  argument for a score.
- **A selector narrowed to a state is the same surface.** The audit
  matched selectors by exact string, so `#circle-door` published and
  `#circle-door[data-starts-from="circle"]` touched read as two
  surfaces. One extending the other at a selector boundary (`[`, `:`,
  a space, `>`) now matches in either direction; `#a` never matches
  `#ab`.
- **A command that probes the served app is not a command surface.**
  A `command` step whose `cmd` interpolates `{base_url}` (a `curl` of
  the landing, say) is QA reaching a route with a host tool; it is no
  longer cross-checked against `[commands]`.

## [0.20.0] - 2026-10-06

### Fixed

- The release build stamped itself `0.20.1.dev0`: a unit test wrote
  evidence under the repo root, those files had been committed, and
  CI's test run dirtied the tree before `uv build`. Unit tests now
  capture evidence under a temporary directory, `evidence/` is
  ignored, and the release workflow refuses to build a dirty tree.

### Added

- **Proofs** (`docs/spec/proofs.md`, format 1.0): the sealed exam as
  one folder per scenario — `~/.darkroom/projects/<name>/proofs/
  <scenario>/` holds `exposure.toml` (QA's steps, drive-scripts 1.7
  vocabulary unchanged) beside `rubric.toml` (product's criteria): one
  lifecycle, two authors, two files. A criterion's `witnesses` resolve
  against the exposure beside it and its evidence kinds derive from
  the steps it cites; `kind = "http"` and `feature_id` are defaults.
  The vault hands the judge the rubric half only (`list` by scenario,
  `read` renders criteria, never steps), on the filesystem and OpenBao
  backends alike, so judging code is untouched. The rubric's
  `description` is product's words; status codes, selectors, and
  step names belong to the exposure.
- **The `.surfaces` file**: engineering publishes the interface it
  chose for a scenario beside the spec — `scenarios/<name>.surfaces`,
  five columnar sections (`[routes]`, `[commands]`, `[pages]`,
  `[files]`, `[notes]`) — and `darkroom audit` binds every exposure to
  it both ways: `surface-unpublished` (warning: a step probes what the
  build never declared) and `surface-untouched` (info: published, not
  proven); a malformed file is `surfaces-malformed`. The judge's prompt
  carries the publication's addresses only — descriptions and notes
  are builder prose and never reach the judge. Audit
  findings now carry a `code`, and the audit reads the tenant's
  `spec_glob`. Specs stay plain Gherkin: no routes, no selectors, no
  `Build:` notes.
- **Manifest 2.1**: each scenario bundle may carry `provenance` — the
  exposure's `sha256` as run and the rubric's `version` — so a verdict
  names the exam it answered. 2.0 readers ignore it.
- **Screenshots as witnesses**: a criterion may cite a `screenshot`
  step; the picture is the record.
- **A proof folder may hold the exposure alone** while the exam is
  being written (the quickstart's stage 1): it runs and is verified
  structurally; sealing, auditing (`no-rubric`), judging, and contract
  derivation refuse it by name until `rubric.toml` arrives.
- **Derived contract and home-side gates.** With no `[evidence]
  contract` declared, the contract a run is verified against is
  derived from the proofs at run time (`drive`/`expose`, `auto`'s
  assessor); with no `[evidence] gates`, the ratchet lives at
  `~/.darkroom/projects/<name>/state/gates.json`. A tenant on proofs
  commits neither file. Declared paths still win.
- **Backdrops**: `~/.darkroom/projects/<name>/backdrops.toml` names
  step sequences an exposure is posed against (`backdrop = [...]`) —
  set before the sitting, reused across many, never the subject —
  expanded ahead of its own steps, names intact; collisions and
  unknown backdrops are load errors. Drive scripts may carry
  `backdrop` too. The rule that follows: a witness is never in the
  backdrop.
- **`[serve.defaults]`, `[serve.env]`, `[browser.defaults]`** in
  `darkroom.toml`: every exam's `[serve]`/`[browser]` starts from the
  project's defaults, and the engine sets the served process's
  environment from `[serve.env]` templates (`{port}`, serve vars,
  `{service.host}`/`{service.port}`) — a missing value fails boot by
  name.
- **`darkroom migrate [--check] [--force]`**: turns each drive +
  rubric pair in the home into a proof folder, dropping the
  restatements, renaming `include` to `backdrop`, carrying
  `version`/`trials`, reporting unpaired files, and printing the
  `[serve.defaults]` block for serve keys identical across ≥ 90% of
  the corpus (dropped from each exposure once darkroom.toml declares
  them). For every spec with a `Build:` note and no `.surfaces`, a
  draft `.surfaces` is written beside it — routes and selectors
  lifted, the prose kept under `[notes]`, descriptions left to
  engineering; the spec itself is never edited.
- **`darkroom expose`**: `darkroom drive` under the proof vocabulary.
  `darkroom preflight` pairs each spec with its proof folder in the
  home (`unpaired-spec`) before falling back to a tenant `rubric_glob`;
  `darkroom home init` lays down `proofs/` and names `backdrops.toml`.
- The example tenant (`examples/relay-service`) ships in the new
  shape: plain specs, a `.surfaces` beside each, proof folders in
  `proofs/` and `proofs-ui/`, no committed contract.

### Deprecated

- Drive scripts and vault rubrics as two files. Both keep working
  unchanged (a home without proofs is read exactly as before), and a
  home holding proofs ignores `drives/` and vault rubrics — the
  layouts never mix. `darkroom migrate` converts.
- Tenant-side `evidence-contract.toml` / `[evidence] contract` and
  `evidence-gates.json` / `[evidence] gates`: honored when declared,
  needed no longer.
- `feature_id` in rubrics and `kind = "http"` on steps: now defaults.
- `Build:` notes in specs: engineering's half in product's file;
  `darkroom migrate` drafts the `.surfaces` that replaces each.

## [0.19.7] - 2026-10-02

### Fixed

- 0.19.6's process-group stop raised `PermissionError` and took the
  whole drive down when the leader shell had already exited — a
  restart scenario kills its own server tree from a command step, and
  on macOS the vacated pgid can be recycled by a process the engine
  may not signal. The group is now signalled only while the leader
  lives, and both "no such group" and "not permitted" are tolerated.

## [0.19.6] - 2026-10-01

### Fixed

- **Every process-mode scenario leaked its app server.** `_Server`
  ran the serve command through `/bin/sh -c` and stopped it with
  `terminate()` — which reached the shell and nothing below it, so a
  `make serve` → `uv run` → server tree lived on as orphans. One
  operator's machine accumulated 252 exam servers in a day (4.8 GB
  resident, swap exhausted), which then showed up as boot failures,
  slow service readiness, and timing races in the suite. The server now
  starts in its own session and `stop()` signals the whole process
  group, SIGTERM then SIGKILL; a unit test spawns a three-generation
  tree and asserts the grandchild dies.

### Changed

- A declared service's `ready_path` wait allows 90s rather than 30s.
  The bound only ever costs time on failure, and a JVM object store on
  a loaded machine has taken a minute to serve its first request.

## [0.19.5] - 2026-09-30

### Added

- `[[environment.services]]` entries take a `ready_path`: after the
  declared port accepts a connection the engine also waits for an HTTP
  response at that path before booting the app. A JVM object store
  accepts TCP seconds before it serves; handed to the app on TCP alone,
  every bucket call in the app's boot window died with "connection
  closed", and seven converged scenarios went red in the same
  full-suite run — a race the single-scenario loops had been winning.

## [0.19.4] - 2026-09-30

### Fixed

- A browser expectation polled `page.content()` / `page.title()`
  unguarded; landing a poll between a navigation's start and commit —
  exactly what a click that redirects does — raised out of the probe
  and failed the step as "click failed: Page.content: Unable to
  retrieve content…". A raising probe now counts as not-yet within the
  bounded wait, and the witness reads the settled page. Found by a
  builder whose scenario failed the same step six runs running while
  the identical click, asserted with `selector_visible` alone, passed.

## [0.19.3] - 2026-09-30

### Added

- Save and expectation paths can index arrays: `$.items[0].id`,
  `$.receipts[-1].who` (drive-scripts 1.7). A list endpoint's newest
  entry was unreachable from a drive before — a builder proved it with
  the engine's own evaluator after a scenario stalled on it.

### Changed

- The server health window after boot is 30s, not 15s: an app that
  runs migrations at import against a service the engine only
  TCP-probed can take longer than that to answer on a loaded machine.

### Fixed

- **The exam could be left where the builder reads it.** The quickstart
  keeps `drives/` in the tenant through stage 3 and never said to move
  it; an adopter following it verbatim committed the exam beside the
  code. Stage 4 now has the move as its own step, `darkroom preflight`
  warns (`drives-in-tenant`) about drive scripts inside a tenant whose
  exam has moved operator-side — an `operator.toml` or sealed rubrics
  in the project's home — and `darkroom auto` refuses to start against
  one. Stages 1–3 are untouched: the free loop makes a home for its
  state, but seals nothing.
- **Vault tokens reached the agents.** Judge and builder subprocesses
  inherited the operator's whole environment, `BAO_TOKEN` /
  `VAULT_TOKEN` included — contrary to what the OpenBao backend
  promised. Agent invocations now run with those scrubbed
  (`agents.SCRUBBED_ENV`), so a role can only hold a vault token it
  was handed on purpose — and OpenBao's policies are the boundary: the
  quickstart now shows an operator policy that reads the rubric path
  and a builder policy that denies it, with the builder's own token
  passed in its invoke template. The agent CLI's own credential is
  passed through by design: the roles are the operator's agents and
  authenticate as such; the boundary is the exam, not the model.

## [0.19.2] - 2026-09-30

### Added

- The browser session's virtual authenticator now carries the WebAuthn
  **PRF extension** (CTAP 2.1 hmac-secret), so a passkey ceremony in a
  drive can yield per-salt secrets the way a real platform passkey
  does — the mechanism a tenant needs to derive encryption keys from
  the thumb rather than store them. On by default; `[browser] prf =
  false` models an authenticator without it, so the fallback road is
  examinable too (drive-scripts 1.6). Every existing passkey drive is
  unaffected: the extension only answers when a ceremony asks for it.
- `[[environment.services]]` entries take a `command` (array of
  strings) for images whose entrypoint wants arguments — an object
  store's `["server", "/data"]` beside the database. Applied in both
  process mode and container mode; absent, the image's own command
  runs as before.

## [0.19.1] - 2026-09-29

### Fixed

- Declared services' mapped addresses now reach the drive's steps as
  `{name.host}` / `{name.port}`, not only the serve command. A
  restart scenario re-boots the app in place from a command step and
  must hand it the same database the engine started; without the
  values it could not.

## [0.19.0] - 2026-09-29

### Added

- **Services in process mode**: an adapter's `[[environment.services]]`
  now apply when the app is process-booted, not only in container
  mode. Each scenario gets a fresh container per service (a Postgres
  per exam), its mapped address substituted into the serve command as
  `{name.host}` / `{name.port}`, a TCP probe on the declared port
  before the app boots, teardown with the server, and the image
  digests logged as the `environment` item. Needed by a tenant moving
  to Postgres whose exam must run on the same engine as production;
  the alternative — the Makefile launching its own container — has
  no teardown and is the bridge pattern again.

### Changed

- The converge skill's deploy stage gains the migration-safety rule
  (test a schema change against a copy of production's database
  before deploying; columns arrive by ALTER TABLE), reads the
  trajectory through `darkroom status`, and says where a service
  belongs (the adapter, never the Makefile).
- The roadmap records two deferred decisions under Beyond 1.0: a
  darkroom container image (built when hosted judging or an
  evaluator-provenance audit asks for it) and the native second
  implementation as `darkrm` (after the freeze, as the spec's
  conformance proof).

## [0.18.0] - 2026-09-28

### Added

- **`darkroom status`**: the present-tense read of loop state — the
  latest campaign per scenario (iteration numbering restarts at 1)
  with a conservative state (`converged`, `running`, `blocked`,
  `exhausted`, `stopped`), trajectory, best, escalation dials,
  failing criteria from the latest evaluation, the ratcheted gate,
  and campaign spend; plus the blocker brief attributed to the
  campaign it interrupted, the ticket queue in priority order, and
  project spend. `--format json` for consumers; `--stale-after` sets
  how long a quiet run still counts as running. The dossier is the
  record; this is the report.
- **`darkroom-status` skill**: the fourth packaged skill — a fixed
  report shape (headline, convergence, shipped state, queue, spend)
  whose numbers come only from `darkroom status`, with the two
  judgments the engine cannot make (blocker triage; shipped state as
  separate merged/released/deployed/live-verified claims) spelled out.
  Written after an operator report quoted a stale commit count from
  memory; the skill forbids exactly that.

### Fixed

- The plugin manifest said MIT; the project is Apache-2.0.

## [0.17.0] - 2026-09-28

### Added

- **Skills ship with the engine.** The three skills move into the
  package (`darkroom/skills/`, package data), so every wheel carries
  the skills that match its engine. `darkroom skills path` prints
  them; `darkroom skills install` links (or `--copy`) them into
  `~/.claude/skills`; **`darkroom skills check`** compares every
  installed copy — hand-installed or plugin-installed — against the
  packaged one by content hash and exits nonzero on drift. A stale
  copy of a skill was found steering an operator in the field; this
  makes that impossible to miss.
- **A Claude Code plugin and marketplace.** `src/darkroom` is a plugin
  (`.claude-plugin/plugin.json`) and the repo is a one-entry
  marketplace pinned to the release tag: `claude plugin marketplace
  add withtwoemms/darkroom`, then install `darkroom@darkroom` for
  `darkroom:interview`, `darkroom:converge`, `darkroom:chronicle`.
  Skills are version-locked to the engine by construction.
- **Release guards.** The release workflow refuses a tag whose
  plugin version or marketplace pin disagree with it, or whose
  SKILL.md names disagree with their folders, and refuses a wheel
  that does not carry the skills.
- **Redirects as evidence** (drive-scripts 1.5): `http` steps accept
  `follow_redirects = false`, so a 3xx is the response the transcript
  records — status and `Location` — and the new `location_contains`
  expectation witnesses where it pointed. Before, `urlopen` followed
  every redirect silently, so "a refused action routes to sign-in"
  could only be gated through the browser.
- **http steps as the browser's member** (drive-scripts 1.5): `session
  = "browser"` sends the scenario's browser-session cookies with the
  request, so an http step acts as whoever the browser signed in. A
  tenant in the field carried a test-only auth bridge in production
  code so exams could mint invites as a member; that bridge can now be
  retired.

### Changed

- The skills' canonical location is `src/darkroom/skills/` (was
  `skills/` at the repo root).
- The drive-scripts spec index said 1.3 while the spec was at 1.4; it
  now tracks the spec (1.5).

## [0.16.0] - 2026-09-27

### Added

- **Expectation witnesses** (drive-scripts 1.4): every step carrying
  an `expect` table now records what it checked and what it found as
  a `log` item named `<step>.expect` — `{expect, found, ok}`. An
  enforced check the judge could not see was not evidence: three
  field blockers in one tenant (a `data-state` checked but never
  logged, a landing exit asserted by a bare `goto`, a join flow's
  beats gated but invisible) were all this class, each costing an
  operator round-trip. A `goto` whose `expect` requires a selector is
  now a witness, not merely a gate. (A witness carries the expected
  value; a judge that greps evidence for expected text must scope to
  transcripts or read `found`/`ok` — the quickstart's judge now does,
  and the spec says why.)
- **Raw request bodies**: `http` steps accept `body` (a string, sent
  verbatim, no content type implied) beside `json`, so exact-bytes
  scenarios — a webhook's HMAC over the raw payload plus a signature
  header — can be exam-gated instead of verified out-of-band.
- **Witness citations in `darkroom audit`**: rubric criteria may name
  their witnesses (`witnesses = ["step_a", "step_b"]`); the audit
  verifies each cited step exists in the drive and can produce a
  resolved value (an `assert`, an `http`/`command` step, or any step
  with an `expect` table). Citing a bare `goto` fails at authoring
  time instead of at run three.

### Changed

- Rubric criteria gain the optional `witnesses` list (additive); the
  interview skill's example carries it, and `producible_kinds`
  counts a step's `expect` as `log` evidence.

## [0.15.0] - 2026-09-25

### Added

- `darkroom audit` — the witnessability lint: an operator-side static
  cross-check of every sealed rubric criterion's declared evidence
  kinds against what its scenario's drive script can actually produce
  (the step-kind → evidence-kind map, plus `record` → video). The
  costliest observed authoring defect — a criterion demanding
  evidence no step captures, discovered at run six instead of at
  writing time — becomes an authoring-time error; a rubric with no
  drive script is a warning. Exits nonzero on errors, for operator
  pre-campaign hygiene (#58)
- The blocker protocol: a builder that concludes the exam itself is
  defective raises `HARNESS-BLOCKER.md` at the project root — the
  loop detects it in the iteration's changed files, records it
  (`IterationRecord.blocker_raised`, a builder-log line, a console
  marker), and by default **pauses model escalation while it
  stands** (`[loop] pause_escalation_on_blocker`), since frontier
  spend cannot fix an operator-side defect. The builder template
  names the channel; role-hooks spec 1.0 → 1.1 specifies it; the
  dossier (schema 1.1) carries a `blocker` field per iteration.
  Field precedent: builders invented this channel unprompted, and
  were right each time (#59)

## [0.14.1] - 2026-09-24

### Fixed

- Bounded waiting (~5s) now covers `url_contains` and
  `title_contains` browser expectations, matching
  `body_contains`/`selector_visible` — a click whose page script
  navigates asynchronously (a passkey ceremony completing, a
  redirect after a fetch) no longer races the check. Found by the
  first tenant's founding ceremony, which exhausted a run on the
  race (#56)

## [0.14.0] - 2026-09-23

### Added

- Browser-session options (`[browser]` in drive scripts, spec 1.3):
  `viewport = { width, height }` for phone-width criteria, and
  `webauthn = true` attaching a CDP virtual authenticator (platform,
  user-verifying, presence auto-simulated) so passkey enrollment and
  assertion run headlessly — with `{base_url}` addressing the server
  as `localhost` in webauthn scenarios, since WebAuthn rejects IP
  origins. Browser expectations now wait (bounded, ~5s) for
  `body_contains`/`selector_visible`, so asynchronously-settling
  pages are assertable (#53)
- Literal-brace escapes in drive interpolation: `{{` and `}}`
  resolve to `{` and `}` after substitution, so shell fragments like
  curl's `%{http_code}` no longer collide with placeholders — found
  the hard way by a tenant exam that exhausted a run on the
  collision (#53)

## [0.13.0] - 2026-09-23

### Added

- Screencast recording for browser scenarios: `record = true` in a
  drive script records the whole scenario through Playwright's
  context recorder and registers the webm as one `video` evidence
  item (step `screencast`) at teardown — continuity evidence of the
  manipulation itself, opt-in because video fattens evidence dirs.
  Drive-script spec 1.1 → 1.2 (additive). The example UI slice now
  records, its contract requires the video, and CI uploads the
  example screencast as an actions artifact on every run (#51)

## [0.12.0] - 2026-09-22

### Added

- Browser steps in the drive vocabulary (`goto`, `click`, `fill`,
  `screenshot` — the `playwright` extra plus an installed chromium):
  one fresh browser session per scenario alongside the served app;
  actions captured as log evidence, screenshots through the existing
  producer (no new evidence kind); `expect` gains `title_contains`,
  `url_contains`, `body_contains`, and `selector_visible` over the
  live page; a browser failure is a judgeable step failure, never a
  crashed drive. CI runs the browser tests against real chromium.
  The exam engine reaches visual tenants (#47)
- Drive-script spec 1.0 → 1.1 (`docs/spec/drive-scripts.md`): the four
  browser step kinds and three browser expectation keys, additive per
  the shared versioning policy — the policy's first exercise. The
  example tenant grows a UI slice: a rendered notes page, a
  `notes_page` scenario (feature + rubric + browser drive script +
  its own contract), run against real chromium in CI (#48)
- `docs/quickstart.md`: the marked trail — four stages in ~15 minutes
  (first evidence, the exam, the convergence loop with shell hooks
  and zero spend, then real agents), each stage copy-paste runnable;
  stages 1–3 are executed verbatim by a CI integration test so the
  guide cannot silently rot. README links it up top (#49)

## [0.11.0] - 2026-09-22

### Added

- `docs/spec/`: format specifications independent of the Python
  implementation — scaffolding (conformance language, shared
  versioning policy, the trust-boundary map) plus the evidence-side
  pages: manifest (2.0, with the v1→v2 migration as the major-bump
  precedent), evidence contract (1.0, with the no-scoring-information
  invariant and scoping rules), and evaluation (1.0, with the
  strict/lenient loading disciplines and citation requirements) (#39)
- `docs/spec/`: the judgment-side pages — gates (1.0: peak records,
  the four check findings with the regression/stale-peak distinction
  as a conformance rule, ratchet-and-re-baseline update semantics) and
  tickets (1.0: the queue/locks/history layout, flat-frontmatter
  documents, exclusive-create claiming, disposition-append
  resolution) (#40)
- `docs/spec/`: the exam-side pages — drive scripts (1.0: the full
  step vocabulary with field tables, interpolation forms incl.
  `sign()`, expectation keys, fresh-environment-per-scenario and
  failure-stops-the-scenario semantics, the refuse-unknown-step-kinds
  rule) and the role hook contract (1.0: judge/builder placeholder
  sets, the missing-score-is-not-a-zero rule, the two harness
  diagnostics channels, boundary conformance rules) (#41)
- Usage metering for agent invocations (`darkroom.usage`): every
  judge/builder call appends one record — role, iteration, model,
  tokens, cost, duration — to `usage.jsonl` in operator-side loop
  state. The default invoke template gains `--output-format json` so
  the `claude` CLI reports usage structurally; custom templates that
  emit no parseable usage degrade to partial records (model +
  duration), and metering never fails a run. The raw material for the
  dossier's cost ledger (#42)
- `darkroom dossier` (`darkroom.dossier`): deterministic assembly of
  the cross-run record — iteration memory, per-criterion score
  trajectories, `auto:` checkpoint subjects, gate peaks, and the usage
  ledger with per-role totals — as one JSON bundle (schema 1.0, specced
  in `docs/spec/dossier.md`) or its Markdown rendering; `--scenario`
  scopes every section. Operator-facing only: the CLI refuses an
  output path inside the tenant. Usage records and builder-log entries
  now carry scenario attribution (additive fields) so cross-run spend
  and iterations attribute per scenario (#43)
- The chronicle skill (`skills/darkroom-chronicle/`): narrates a
  project's delivery from its dossier — progression as a story,
  collation of what the judge witnessed (sticking points with the
  check-the-exam recommendation, novelty callouts, the rubric-drift
  incomparability rule), spend accounting, and at most three
  actionable surfacings; every claim traceable to a dossier field,
  operator-facing only (#44)

### Fixed

- Dossier evaluation entries order chronologically under mixed
  UTC-offset timestamps (a string sort misordered them) — found by
  assembling the first tenant's real record (#44)
- Loop work files survive across invocations: each `auto` run now
  writes evaluations, feedback, prompts, and usage into its own
  `state/loop/<invocation>/` subdirectory instead of overwriting the
  previous run's files — evaluation history accrues instead of being
  a palimpsest of the last run. The dossier aggregates across
  invocation subdirectories and still reads the flat legacy layout
  (#45)

## [0.10.0] - 2026-09-22

### Added

- OpenBao / HashiCorp Vault backend for the rubric vault
  (`darkroom.vault_openbao`, behind the `vault` extra): KV v2 storage
  with token-gated reads (`BAO_TOKEN`/`VAULT_TOKEN` in the operator
  process only — agents never hold credentials) and rubric-version
  resolution by bounded newest-first walk of KV history; configured via
  `[vault] backend/url/mount/path` in operator config, with
  `build_vault` selecting the backend everywhere. `vault seal` writes to
  the configured backend; new `vault migrate` moves a filesystem vault
  into it, archiving local copies. CI runs the backend tests against a
  real `bao server -dev` (#36)
- Container environments (behind the `containers` extra, testcontainers):
  the adapter's `[environment]` declares run-me facts — `app_image`,
  `app_port`, a `build` command, `app_env` templates with `{serve-var}`
  and `{service.host}`/`{service.port}` substitution, and
  `[[environment.services]]` — while containment *policy* is operator
  authority: `[containers] mode = off | auto | required` (`required`
  makes containment a control a builder cannot disable by editing the
  adapter), flowing to the drive via `--containers`/`DARKROOM_CONTAINERS`.
  Container mode runs each scenario in fresh containers on a private
  network, records **image digests as evidence** (an `environment` log
  item per scenario), and closes the assess-time vector: builder-authored
  code no longer executes with the operator's UID and environment (#37)
- The `container` drive step kind (`action = stop|start|pause|unpause`
  on a declared service or the app) — failure-injection scenarios,
  captured as log evidence (#37)

## [0.9.2] - 2026-09-22

### Fixed

- `darkroom auto` checkpoints its own gate write on convergence, leaving
  a clean tree — previously the post-checkpoint `evidence-gates.json`
  update left the tenant dirty, so a following per-scenario run was
  refused by the clean-tree guard. Found by the first tenant's
  multi-scenario live slate (#34)

## [0.9.1] - 2026-09-22

### Fixed

- Scenario-scoped runs verify against a scenario-scoped contract:
  `darkroom drive --scenario X` and the loop's assessor no longer fail
  verification for scenarios the run deliberately did not attempt —
  previously making per-scenario `darkroom auto` convergence impossible
  under a multi-scenario contract. Found by the first tenant dry run (#32)

## [0.9.0] - 2026-09-21

### Added

- The intent interview as a Claude Code skill
  (`skills/darkroom-interview/`): charter elicitation, scenario
  enumeration with negative space, threshold interviews (declined
  answers become low-confidence criteria, never silent guesses), rubric
  drafting under the capturable-evidence rule, a gaming self-audit
  before presentation, full artifact writing, and mechanical validation
  via `darkroom preflight`; README documents installation (#25)
- The darkroom home (`darkroom.homedir`): `~/.darkroom` (override:
  `DARKROOM_HOME`), mode 700, partitioned per project by the adapter's
  name — operator config, vault, drives, and loop state consolidated
  outside every builder-addressable path. `darkroom home init/path`;
  `vault seal`/`derive-contract` default their `--vault` to the home;
  agent mode auto-discovers `operator.toml` from the home and its
  missing `[vault]` path falls back to the home vault (#27)

- The drive engine (`darkroom.drive`): the exam as data — declarative
  per-scenario `.drive.toml` scripts executed against the system as a
  black box, a fresh server per scenario via the adapter's `serve`
  command with health-wait, every exchange captured through the existing
  producers into an ordinary evidence manifest. Step vocabulary: `http`
  (expect/save with dot-path extraction), `command`, `keygen` (Ed25519,
  via the new `crypto` extra), `sign(...)` interpolation, `assert`
  (captured as log evidence), `wait`. A failed expectation stops its
  scenario but keeps the evidence captured before it — a failing
  scenario is still judgeable (#28)

- `darkroom drive [--scenario] [--drives]` — the exam as a CLI: runs the
  drive scripts (defaulting to the project home's `drives/`), prints
  per-step results, and verifies the produced manifest against the
  contract in the same invocation; the adapter's `test` command can now
  simply be `darkroom drive`, wiring the loop to the external exam (#29)
- The harness diagnostics pipeline, restoring the source framework's
  builder-visible test log: drive writes `harness.log` beside the
  manifest (boot outcomes and per-step results — spec-level information,
  never criteria or scores); a scenario that cannot boot is a failed
  scenario, not a failed drive (later scenarios still run); the assessor
  captures the failing test command's output tail into its notes; the
  judge prompt gains `Harness notes:` and the builder prompt gains a
  `Harness diagnostics` section read from the latest run — so an empty
  repo bootstraps from feedback alone, no seeded skeleton required (#29)
- `examples/relay-service/` — a stdlib-only example tenant with specs,
  rubrics, a derived contract, and drive scripts; exercised green by CI (#29)

### Changed

- Loop state relocated from the tenant's `.darkroom/state` to the
  project's home, closing a leak where agent-mode judge evaluations
  (scores) were readable by the builder between iterations. Agent mode
  now ignores the tenant's advisory `[defaults] state`; explicit
  `--state` still wins everywhere (#27)

## [0.8.0] - 2026-09-20

### Added

- The rubric vault (`darkroom.vault`): `RubricVault` protocol (with a
  `version` read parameter reserved for secret-manager backends) and
  `FilesystemVault` — mode-700 storage outside builder-visible paths
  with every read appended to `audit.log`. `darkroom vault seal` moves
  rubrics out of the tenant tree (move, not copy: one authority);
  `darkroom vault derive-contract [--check]` regenerates the evidence
  contract from the rubrics' evidence declarations (rubric-as-root),
  demoting the tenant contract to a drift-checked cache (#21)
- Operator configuration (`darkroom.operator`): the authority-side file —
  judge/builder models, tool allowlists, invocation command templates,
  vault location, loop policy; no default location, explicitly never in
  the tenant repo (#22)
- Agent roles (`darkroom.agents`): `AgentJudge` (vaulted rubric +
  rendered evidence + escalating feedback instructions assembled into a
  prompt; honors the hook file contract) and `AgentBuilder` (feedback +
  iteration-memory tail; diagnostic instructions, model and tool
  escalation per the dials). Access asymmetry enforced in the
  constructed command: judge add-dirs never include tenant source,
  builder add-dirs never include the vault. Invocation is a swappable
  command template defaulting to the `claude` CLI;
  `darkroom auto --operator operator.toml` runs the loop fully
  agent-driven (#22)
- End-to-end agent-mode integration test: seal → derive-contract →
  `auto --operator` convergence with fake agents honoring the real
  prompt/file contract — vault reads audited, opacity structurally
  verified (no rubric anywhere in the tenant), gates ratcheted; README
  documents the loop in both modes (#23)

## [0.7.0] - 2026-09-20

### Added

- Convergence loop (`darkroom.loop`): the source framework's `make auto`
  as a testable state machine — stagnation accounting, the three
  escalation dials (diagnostic access, model escalation, judge feedback
  specificity), rollback-to-best-checkpoint, iteration memory in
  `builder-log.md`, clean-tree precondition, typed
  `ConvergenceResult`. Roles (assess/judge/build/checkpoint) are
  injected protocols; opacity is preserved by construction (the judge
  authors builder feedback; the loop never derives it from scores) (#18)
- Loop roles darkroom owns (`darkroom.roles`): `AdapterAssessor` (runs
  the adapter's test command, locates the newest run, verifies against
  the contract) and `GitCheckpointer` (checkpoints with
  `--allow-empty`, best-ref rollback without history rewrites, change
  listing) (#18)
- Shell-hook roles (`darkroom.hooks`): `CommandJudge` and
  `CommandBuilder` invoke operator-supplied commands under a documented
  file contract (`{manifest}`/`{evaluation_out}`/`{feedback_out}`;
  `{feedback}`/`{diagnostic}`/`{escalate_model}`) — the loop is runnable
  before built-in agent roles exist, and the contract is a public
  interface those roles will honor. A judge hook that writes no
  evaluation aborts the loop: a missing score is not a zero (#19)
- `darkroom auto --judge-cmd ... --build-cmd ...`: the convergence loop
  as a CLI — live per-iteration reporting, policy via flags (operator
  authority, never the tenant file), gates ratcheted automatically on
  convergence with the winning checkpoint as the retreat point (#19)

## [0.6.0] - 2026-09-20

### Added

- Project adapter (`darkroom.adapter`): `darkroom.toml` at the tenant
  root declaring run-me facts — commands with `{placeholder}`
  substitution, evidence/contract/gates paths, spec and rubric globs,
  advisory `[defaults]`. Carries the trust rule: the file is
  builder-writable, so judging/gating/loop authority never reads from it (#15)
- Preflight (`darkroom.preflight` + `darkroom preflight [--json]`): is
  the project wired for evidence-based delivery — adapter loads, a test
  command exists, spec glob resolves, specs pair with rubrics
  (normalized-stem matching), declared contract loads (#15)
- `darkroom run <command> [--scenario] [--seed] [--capture]`: execute an
  adapter command with substitution; `--capture` records the execution
  as command-transcript evidence (#15)
- Filesystem ticketing (`darkroom.tickets`), porting the source
  framework's `state/queue|locks|history` conventions: markdown tickets
  with flat frontmatter (yaml-compatible subset, no dependency),
  `O_CREAT|O_EXCL` claim locks with stale-age detection and `force`,
  dispositions appended on resolve; CLI `darkroom ticket
  new/list/resolve` with the state dir taken from the adapter's
  `[defaults]` (#16)

## [0.5.0] - 2026-09-19

### Added

- Evaluation score model (`darkroom.evaluation`): typed
  `Evaluation`/`ScenarioEvaluation`/`CriterionResult` with derived
  totals and 0-100 percentage, evidence citations as manifest item
  paths, and `rubric_version` provenance; strict JSON round-trip plus
  lenient `coerce_evaluation`/`normalize_percentage` absorbing observed
  LLM-judge drift (0-1 scales, `overall_score`/`pass_rate` synonyms,
  mapping-or-list criteria, string numbers) (#11)
- Judge renderers (`darkroom.render`): the consuming mirror of the
  producer protocol — `RenderedEvidence` (text + attachments),
  `JudgeRenderer` protocol dispatched on item kind via a registry, and
  built-ins covering all eight kinds; unknown kinds fall back to a
  descriptive line and broken evidence files render as stated defects
  rather than raising (#12)
- The contact sheet: `darkroom gallery <manifest> [--evaluation] [--embed]
  [-o]` renders a run as a single static HTML page — image strips with
  FAILURE flagging, playable videos, collapsible text evidence, and an
  optional score overlay (per-scenario badges, criterion verdicts linked
  to cited evidence, rubric-version chip). Relative media refs by
  default; `--embed` inlines data URIs for a shareable single file (#13)
- Peak gates (`darkroom.gates`): per-scenario high-water marks carrying
  run id (evidence), commit (retreat point), and rubric version — a
  version mismatch reports `stale-peak` (re-baseline), never
  `regression`. CLI: `darkroom gate check` (exit 1 on regression) and
  `darkroom gate update [--commit]` over a committed
  `evidence-gates.json` (#14)
- Run diffing (`darkroom.rundiff` and `darkroom diff <old> <new>`):
  scenario- and item-level changes between two manifests (#14)

## [0.4.0] - 2026-09-18

### Added

- Evidence contracts (`darkroom.contract`): TOML-declared per-scenario
  capture requirements — kinds, counts, named steps, and a `trials`
  dimension for run-series checking. Deliberately a pure projection of
  what a rubric's evidence declarations could generate (#9)
- Manifest verification (`darkroom.verify`): structural checks (paths
  resolve, files non-empty, manifests parse) plus contract satisfaction
  with typed findings; multi-manifest series supported (#9)
- `tomli` as a conditional dependency on Python 3.10 only (stdlib
  `tomllib` thereafter) (#9)
- First CLI, installed as `darkroom` and the terse alias `darkrm`:
  `verify <manifest…> [--contract] [--json]` (exit 1 on errors, 2 on
  usage problems; auto-discovers `evidence-contract.toml`) and
  `show <manifest>` for a human-readable run summary (#10)

## [0.3.0] - 2026-09-18

### Added

- `HTTPTranscriptProducer` (kind `http_transcript`): performs the request
  via stdlib urllib and captures the full exchange — status, headers,
  bodies (truncation-capped), duration, connection errors — with
  sensitive headers redacted by default; plus `EvidenceCapture.http()` (#8)

- First non-browser producers: `CommandTranscriptProducer` (runs the
  command itself — exit code, stdout/stderr with truncation caps,
  duration, timeout capture), `FileSnapshotProducer` (content copy with
  sha256 and guessed mime), and `DiffProducer` (unified diff with
  added/removed line counts) (#7)
- `EvidenceCapture.command()`, `.snapshot()`, and `.diff()` convenience
  methods; new kinds use the scenario-directory layout in both modes (#7)

- `VideoProducer` (kind `video`) filing finalized recordings into the run,
  plus `EvidenceCapture.video()` with a flat screencasts-directory
  fallback — the screencast directories finally have a producer (#6)
- Producers now populate `EvidenceItem.metadata`: screenshots record
  `full_page` and the viewport, element screenshots record the `selector`,
  videos record `size_bytes` (#6)

## [0.2.0] - 2026-09-18

### Added

- Pytest plugin, auto-loaded via the `pytest11` entry point: evidence-mode
  session hooks (`start_run`/`end_run` with manifest write), the
  `evidence` fixture named from the test node, full-page screenshot on
  failure for tests using a `page` fixture, and the `darkroom_project`
  ini option (#5)
- First integration tests, driving real pytest sessions via pytester (#5)

### Changed

- `darkroom.compat` documented as legacy-only; new projects use the
  plugin (#5)

## [0.1.0] - 2026-09-18

### Added

- Apache-2.0 `LICENSE` file (#1)
- Ruff configuration and lint fixes (#1)
- GitHub Actions CI: ruff lint + test matrix over Python 3.10–3.13 (#2)
- `ROADMAP.md` and design docs: vision, rubric lifecycle, generalization
  plan (#3)
- Tag-triggered release workflow publishing to PyPI via trusted
  publishing (#4)

### Changed

- Distribution renamed to `darkroom-ai` (the bare `darkroom` name is
  squatted on PyPI); the import name remains `darkroom` (#4)

### Fixed

- `test_v1_drops_scenario_file` asserted a tautology; it now verifies the
  v1 `scenario_file` field is dropped on load and never serialized (#1)
