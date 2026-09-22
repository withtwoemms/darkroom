# The darkroom Format Specifications

These pages specify darkroom's interchange formats independently of the
Python implementation. The goal is the standard play: any harness, in
any language, can produce a manifest a darkroom judge consumes — and
any judge infrastructure can consume evidence a darkroom harness
produced — by conforming to these documents rather than importing the
package.

## Documents

| Spec | Format | Schema version |
|------|--------|----------------|
| [manifest.md](manifest.md) | run manifest (JSON) | 2.0 |
| [contract.md](contract.md) | evidence contract (TOML) | 1.0 |
| [evaluation.md](evaluation.md) | evaluation (JSON) | 1.0 |
| gates.md | regression gates (JSON) | 1.0 |
| tickets.md | tickets (Markdown + frontmatter) | 1.0 |
| drive-scripts.md | drive scripts (TOML) | 1.0 |
| role-hooks.md | judge/builder hook contract | 1.0 |
| dossier.md | cross-run dossier bundle (JSON) | 1.0 |

## Conformance language

The key words MUST, MUST NOT, SHOULD, and MAY are used per RFC 2119,
and appear only in each page's **Conformance** section. Everything
else is description.

Two conformance roles recur:

- a **producer** emits a document of the format;
- a **consumer** reads one.

## Versioning policy

Each format carries its own `schema_version` (`major.minor` as a
string), versioned independently of the `darkroom-ai` package and
moving more conservatively. The rules:

- A **minor** bump adds fields or relaxes constraints; documents of
  the same major version remain mutually readable.
- A **major** bump changes meaning or removes fields, and ships with
  a documented migration path in the same spec page (the manifest's
  transparent v1→v2 loader is the precedent).
- Consumers MUST ignore fields they do not recognize — this is what
  makes minor bumps safe.

## The trust boundary

darkroom's formats cross a boundary between two sides that must not
share authority. Each spec page carries a **Trust position** section;
the map:

| Format | Written by | Read by | Builder may read? |
|--------|-----------|---------|-------------------|
| manifest | the harness (non-LLM machinery only) | judge side, verification, gates | yes |
| contract | operator side (projection of rubric declarations) | verification, both roles | yes — deliberately sanitized |
| evaluation | the judge | operator side, loop, gates | **no** — carries scores |
| gates | operator side (loop, on convergence) | loop, CI | yes (the floor is public; the scores behind it are not) |
| tickets | operator side | loop, both roles | yes |
| drive scripts | operator side (the exam) | the drive engine | no — operator home |
| role hooks | operator config | the loop | no — operator home |
| dossier | operator side (assembled from state) | operator, narration tooling | **no** — carries score trajectories |

The load-bearing rule behind the map: anything builder-writable may
carry only information whose manipulation is futile or caught;
anything score-bearing stays operator-side. A conforming
implementation preserves these positions, not just the field shapes.

## Out of scope

`darkroom.toml` (the project adapter) and `operator.toml` (operator
config) are darkroom *configuration*, not interchange formats. They
are documented in the main docs, may change with the package, and are
deliberately not frozen by these specifications.
