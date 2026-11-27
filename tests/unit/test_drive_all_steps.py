"""Running every step, and skipping only what a failure made meaningless.

A drive stops at the first failure, which is right for a gate and wrong for a
campaign: the builder learns one fact per iteration, and a scenario with five
unbuilt steps cannot converge in six iterations at that rate. Worse, the
trajectory it produces -- flat zero -- is indistinguishable from a builder
that is genuinely stuck, so the operator escalates and spends more to obtain
the same single bit.

These cover the three things that make continuing safe rather than noisy:
what still runs, what is skipped and why, and that none of it loosens the
gate.
"""

from darkroom.drive import (
    Context,
    ScenarioResult,
    StepResult,
    _placeholders_in,
    _why_this_cannot_run,
)


# --- what a step needs ------------------------------------------------------


def test_placeholders_are_found_wherever_they_are_written():
    """A step's dependencies are not only in its url -- they hide in headers,
    json bodies, form bodies and command lines."""
    step = {
        "name": "x",
        "url": "{base_url}/invoices/{invoice_id}",
        "headers": {"X-Trace": "{trace}"},
        "json": {"lines": [{"ref": "{quote_id}"}]},
    }
    assert _placeholders_in(step) == {"base_url", "invoice_id", "trace", "quote_id"}


def test_escaped_braces_are_not_placeholders():
    """`%{{http_code}}` is curl's syntax surviving interpolation, not a
    dependency on a value called http_code."""
    assert _placeholders_in({"cmd": "curl -w '%{{http_code}}' {base_url}"}) == {"base_url"}


# --- why a step would be skipped --------------------------------------------


def test_a_step_needing_a_value_nobody_produced_runs_anyway():
    """An unknown placeholder that no step was ever going to save is an
    authoring defect, and must still surface as one. Skipping it would hide
    the author's mistake behind a plausible excuse."""
    ctx = Context({"base_url": "http://x"})
    step = {"name": "b", "url": "{base_url}/{typo_nobody_saves}"}

    assert _why_this_cannot_run(step, ctx, False, produced_by={}) == ""


def test_a_step_needing_a_value_a_failed_step_owed_is_skipped():
    """The common cascade: a POST that was meant to save an id failed, so
    everything addressing that id has nothing to act on. Reporting those as
    failures hands a builder four symptoms of one cause."""
    ctx = Context({"base_url": "http://x"})
    step = {"name": "read_it_back", "url": "{base_url}/quotes/{quote_id}"}

    reason = _why_this_cannot_run(
        step, ctx, False, produced_by={"quote_id": "create_the_quote"}
    )

    assert "{quote_id}" in reason
    assert "create_the_quote" in reason


def test_a_value_that_was_saved_does_not_cause_a_skip():
    ctx = Context({"base_url": "http://x", "quote_id": "q-1"})
    step = {"name": "read_it_back", "url": "{base_url}/quotes/{quote_id}"}

    assert _why_this_cannot_run(
        step, ctx, False, produced_by={"quote_id": "create_the_quote"}
    ) == ""


def test_browser_steps_after_a_failed_navigation_are_skipped():
    """They would act on whatever page happened to be loaded, so their
    expectations fail for the wrong reason -- 'selector not visible' when the
    truth is 'you are on the wrong page'."""
    ctx = Context()

    assert _why_this_cannot_run(
        {"name": "click_it", "kind": "click"}, ctx, True, produced_by={}
    )
    assert _why_this_cannot_run(
        {"name": "look", "kind": "screenshot"}, ctx, True, produced_by={}
    )


def test_a_navigation_is_never_skipped_for_a_lost_page():
    """A goto is how the browser gets somewhere again. Skipping it would mean
    one failed navigation ends every browser step for the rest of the run,
    which is the halt this change exists to remove."""
    assert _why_this_cannot_run(
        {"name": "go", "kind": "goto", "url": "http://x"}, Context(), True, produced_by={}
    ) == ""


def test_non_browser_steps_are_unaffected_by_a_lost_page():
    """An http call does not care where the browser is."""
    ctx = Context({"base_url": "http://x"})
    assert _why_this_cannot_run(
        {"name": "ask", "kind": "http", "url": "{base_url}/health"}, ctx, True, produced_by={}
    ) == ""


def test_an_author_can_declare_a_dependency_the_engine_cannot_infer():
    """Semantic dependencies -- 'this assertion only means anything if that
    POST succeeded' -- are invisible to placeholder and page analysis."""
    ctx = Context()
    step = {"name": "assert_it", "kind": "http", "requires": ["the_post"]}

    assert "the_post" in _why_this_cannot_run(step, ctx, False, produced_by={})

    ctx.passed_steps.add("the_post")
    assert _why_this_cannot_run(step, ctx, False, produced_by={}) == ""


# --- the gate does not move -------------------------------------------------


def test_a_skipped_step_is_not_a_pass():
    """This is the line that must not be crossed. Continuing past a failure
    changes what is reported, never what gates -- otherwise it buys builder
    throughput by weakening the thing the engine exists to be."""
    result = ScenarioResult(
        scenario="s",
        steps=[
            StepResult("a", "http", ok=True),
            StepResult("b", "http", ok=False, detail="expected 201, got 404"),
            StepResult("c", "http", ok=False, status="skipped", skipped_because="needs {id}"),
        ],
    )

    assert result.ok is False
    assert [s.name for s in result.failed] == ["b"]
    assert [s.name for s in result.skipped] == ["c"]


def test_a_run_with_only_skips_is_still_not_green():
    result = ScenarioResult(
        scenario="s",
        steps=[
            StepResult("a", "http", ok=True),
            StepResult("b", "http", ok=False, status="skipped", skipped_because="why"),
        ],
    )
    assert result.ok is False


def test_status_defaults_from_ok_so_existing_callers_are_unchanged():
    """Every StepResult built elsewhere in the engine passes ok= and no
    status; they must keep meaning what they meant."""
    assert StepResult("a", "http", ok=True).status == "passed"
    assert StepResult("a", "http", ok=False, detail="x").status == "failed"
