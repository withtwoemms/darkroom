---
name: darkroom-author
description: Author or repair a scenario's proof in darkroom's 0.20 shape - the exposure in QA's hands and the rubric in product's, posed against backdrops, bound to the builder's published surfaces - and run the same discipline over an existing corpus to extract backdrops and rewrite rubrics in product's words. Use when a user wants to write, review, tidy, or de-duplicate exposures and rubrics, extract shared setup into backdrops, or bring migrated proofs up to the house style.
---

# Authoring a proof

You are writing the two files of a proof, under two hats, and the
discipline is in never letting one hat touch the other's file to make
a run go green:

| hat | file | says |
|-----|------|------|
| product | `proofs/<scenario>/rubric.toml` | what a good record shows, in product's words |
| QA | `proofs/<scenario>/exposure.toml`, `backdrops.toml` | how the subject is driven and what each step expects |

Engineering's file — `scenarios/<scenario>.surfaces` — is read, never
written here. The interview skill owns the spec; the converge skill
owns the run. This skill owns the *shape* of the proof, whether it is
being written fresh or brought up to style.

Vocabulary, so the files read the same way every time: a **scenario**
is named `snake_case`; its **exposure** drives the subject and
captures frames; its **rubric** scores them; a **backdrop** is shared
setup the exposure is posed against; a **witness** is a step whose
record proves a criterion; the **surfaces** are the addresses the
build exposes.

## The rules, in the order they bite

1. **A witness is never in the backdrop.** What a scenario proves is
   in its own steps. Shared setup (saving a note, holding its token) goes in `backdrops.toml`; the moment a rubric cites a
   backdrop step, forty rubrics depend on shared setup and one edit
   silently re-scores them all. If a criterion needs a setup fact
   ("the note exists"), witness it with the scenario's own step
   (an `http` read of the note), not the backdrop's founding click.
2. **A rubric speaks product's language.** A description says what a
   good record *shows*, never which step showed it: no step names, no
   status codes, no selectors, no `(log)`, no "resolved 2". The
   witnesses list carries the binding; the prose carries the standard.
   Test: could the PM have written this sentence before the exposure
   existed? If not, it is QA's sentence in product's file.
   - before: `"the member's unread list held exactly two notes (unread_list; two_unread_not_three resolved 2) … (newest_is_the_retraction, retraction_named)"`
   - after: `"the member is told of exactly the notes that were withdrawn unread — the retraction first, with who sent it, then the expiry — and never of one they had read"`
3. **Every witness leaves a record.** Cite an `assert`, an `http` or
   `command` step, a `screenshot`, or any step with an `expect` table.
   A bare `goto`/`click`/`fill` gates the run but gives the judge
   nothing; `darkroom audit` refuses it.
4. **Witness absence with a positive.** "The handle field is gone" is
   not a selector that fails to appear — it is a state attribute that
   *does* (`#notes li[data-archived="true"]`), or a count that
   resolves to zero (`curl … | grep -c` expecting exit 1), or an
   `http` read whose body an `assert` inspects. A once-shown surface
   (a notice dismissed on view) is witnessed on the render that shows
   it and on the next render that does not — both positively.
5. **Follow a link to prove it leads somewhere.** `selector_visible`
   proves presence; `url_contains` after a `click` proves the door
   opens. The judge docked a point on an identical build for "leads
   where it says" witnessed by visibility alone.
6. **Machine surfaces, never display text.** Expectations match
   `data-*` and ids; typography is the judge's business from
   screenshots and must never be able to break a gate.
7. **Production posture by default.** An exposure runs with every
   exam-only bridge off (every `[serve]` bridge at its production value)
   unless the scenario is *about* that bridge. A defect on the
   first tenant hid for a month because every landing exposure
   registered a member through a bridge production does not have.
8. **Address only what is published.** Read the scenario's
   `.surfaces`; an exposure touches those addresses. On a new feature
   the surfaces do not exist yet — write to the spec's intent and let
   the audit flag `surface-unpublished` until the builder publishes.
9. **Scaled clocks, array paths, reuse.** A TTL scenario sets the
   clock seam (`[serve] day_seconds = 5`), never sleeps a day;
   a list is addressed by index (`$.items[0].id`, `#list li[-1]`);
   the closest proven exposure is the template, never an invented
   shape.
10. **Version is schema.** Bump the rubric's `version` when criteria,
    ids, points, witnesses, trials, or a stated threshold change —
    never for a rewording. Rewrites under this skill keep the version.

## Backdrops: extracting them from a corpus

A backdrop is a named step sequence many exposures open with. To find
them, count repeated steps across the corpus by name + kind + target
(the one-liner below) and read the top of the list as sequences, not
single steps: a founding is three steps that always travel together.

```sh
for f in proofs/*/exposure.toml; do awk 'BEGIN{RS="\\[\\[step\\]\\]"} NR>1 {n=k=u=s=""; split($0,L,"\n"); for(i in L){ if(L[i]~/^name = /)n=L[i]; if(L[i]~/^kind = /)k=L[i]; if(L[i]~/^url = /)u=L[i]; if(L[i]~/^selector = /)s=L[i] } print n"|"k"|"u"|"s}' "$f"; done | sort | uniq -c | sort -rn | head -20
```

Then, per backdrop:

- **Name it for the state it leaves**, not the steps it takes:
  `note_saved`, `note_archived`, `token_in_hand` — the
  exposure reads "posed against a saved note".
- **Lift the steps verbatim** into `[[backdrop]]` / `[[backdrop.step]]`,
  names intact; an exposure that used them replaces those steps with
  `backdrop = ["note_saved"]`. Step names must not collide with the
  exposure's own; the engine refuses a collision at load.
- **Keep variants apart.** A founding with PRF off and one with PRF on
  are two backdrops, not one with a flag. If two exposures' "same"
  setup differs in one field, either both backdrops exist or the
  difference moves into the exposure's own first step.
- **Check no rubric cites a lifted step** (`grep -l '"<step>"'
  proofs/*/rubric.toml`). If one does, the criterion is re-witnessed
  by the scenario's own step before the lift — rule 1.
- **Prove nothing moved**: `darkroom audit` clean, then `darkroom
  expose --scenario <one of each>` green, before the next backdrop.

## Rubric rewrite: bringing a migrated corpus up to style

Migrated rubrics carry 0.19 habits: step names in parentheses,
"resolved", "(log)", codes and selectors. The rewrite is a copy edit
under rule 2, one scenario at a time:

1. Read the spec — product's intent, in product's words.
2. For each criterion, keep `id`, `points`, `witnesses` exactly;
   rewrite `description` as the sentence product would have written
   before the exposure existed. Drop every step name, code, selector,
   and "(log)"; keep every *threshold* ("within ten seconds", "exactly
   two", "never of one they had opened") — thresholds are product's.
3. If a description names a fact no witness proves, that is a missing
   witness, not surplus prose: add the step to the exposure (QA's hat)
   and cite it — this is a schema change, so bump `version`.
4. `version` stays unless step 3 fired.
5. `darkroom vault seal` and `darkroom audit` after each scenario.

Do not batch-rewrite with a script. The whole point is that each
sentence is read against its spec.

## Writing a proof fresh

Order: spec (interview skill) → rubric (this skill, product's hat:
criteria with points and the witness *names* you intend) → exposure
(QA's hat: the steps that produce those witnesses, posed against the
backdrops that exist) → `darkroom audit` → `darkroom expose` dry run
→ hand to the converge skill. Write the rubric first so the exposure
is built to produce named witnesses, not the other way round.

A finished pair, for reference — `notes_page_offers_the_form`, in
the relay example's vocabulary:

```toml
# exposure.toml (QA)
scenario = "notes_page_offers_the_form"
record = true

[[step]]
name = "open_page"
kind = "goto"
url = "{base_url}/"
expect = { status = 200, title_contains = "Relay Notes", selector_visible = "#note-form" }

[[step]]
name = "no_token_on_page"   # absence, witnessed positively
kind = "command"
cmd = "curl -s {base_url}/ | grep -c 'name=\"token\"'"
expect = { exit_code = 1 }

[[step]]
name = "type_a_note"
kind = "fill"
selector = "#note-text"
value = "milk"

[[step]]
name = "saved_note"         # a control is proven by what it does
kind = "click"
selector = "#save"
expect = { selector_visible = "#notes li" }
```

```toml
# rubric.toml (product)
version = "1"

[[criterion]]
id = "the_page_offers_the_form"
points = 15
description = "the page offers one form to save a note, the saved note shows in the list, and the note's token never appears on the page"
witnesses = ["open_page", "no_token_on_page", "saved_note"]
```

## Hand-off

Report what changed and under which hat: backdrops extracted (name,
steps, exposures that now pose against each), rubrics rewritten
(scenario, criteria touched, whether `version` moved and why),
exposures changed, and the audit and dry-run results that prove
nothing moved. Anything that needed a product ruling — a threshold
the spec never stated, a criterion no witness can prove — is listed
as a question, not decided.
