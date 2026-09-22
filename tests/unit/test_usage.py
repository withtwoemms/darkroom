"""Usage metering: parsing agent output, the jsonl ledger, degradation."""

import json

from darkroom.usage import (
    UsageRecord,
    build_record,
    parse_agent_output,
    read_usage,
    record_usage,
)

CLAUDE_RESULT = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "total_cost_usd": 0.0834,
        "duration_ms": 41210,
        "usage": {
            "input_tokens": 1200,
            "cache_read_input_tokens": 9000,
            "cache_creation_input_tokens": 300,
            "output_tokens": 450,
        },
        "result": "done",
    }
)


class TestParseAgentOutput:
    def test_claude_json_result(self):
        parsed = parse_agent_output(CLAUDE_RESULT)
        assert parsed == {
            "input_tokens": 1200 + 9000 + 300,
            "output_tokens": 450,
            "cost_usd": 0.0834,
        }

    def test_json_after_leading_noise(self):
        parsed = parse_agent_output("warning: something\n" + CLAUDE_RESULT + "\n")
        assert parsed is not None
        assert parsed["cost_usd"] == 0.0834

    def test_plain_text_yields_none(self):
        assert parse_agent_output("I made the change you asked for.") is None

    def test_json_without_usage_yields_none(self):
        assert parse_agent_output('{"result": "ok"}') is None

    def test_cost_only(self):
        parsed = parse_agent_output('{"total_cost_usd": 0.5}')
        assert parsed == {
            "input_tokens": None, "output_tokens": None, "cost_usd": 0.5,
        }

    def test_garbage_yields_none(self):
        assert parse_agent_output("{not json") is None
        assert parse_agent_output("") is None


class TestBuildRecord:
    def test_full_record(self):
        record = build_record("judge", 2, "claude-opus-5", CLAUDE_RESULT, 41.2101)
        assert record.role == "judge"
        assert record.iteration == 2
        assert record.model == "claude-opus-5"
        assert record.duration_seconds == 41.21
        assert record.input_tokens == 10500
        assert record.output_tokens == 450
        assert record.cost_usd == 0.0834
        assert record.partial is False

    def test_partial_record_from_unparseable_output(self):
        record = build_record("builder", 1, "claude-sonnet-5", "did the thing", 3.0)
        assert record.partial is True
        assert record.input_tokens is None
        assert record.cost_usd is None
        assert record.model == "claude-sonnet-5"  # model+duration always kept


class TestLedger:
    def test_append_and_read_round_trip(self, tmp_path):
        first = build_record("judge", 1, "m", CLAUDE_RESULT, 1.0)
        second = build_record("builder", 1, "m", "text", 2.0)
        record_usage(tmp_path, first)
        record_usage(tmp_path, second)
        records = read_usage(tmp_path)
        assert records == [first, second]

    def test_read_skips_corrupt_lines(self, tmp_path):
        record_usage(tmp_path, build_record("judge", 1, "m", CLAUDE_RESULT, 1.0))
        with open(tmp_path / "usage.jsonl", "a") as f:
            f.write("{corrupt\n")
        record_usage(tmp_path, build_record("builder", 2, "m", "x", 2.0))
        records = read_usage(tmp_path)
        assert [r.role for r in records] == ["judge", "builder"]

    def test_missing_ledger_reads_empty(self, tmp_path):
        assert read_usage(tmp_path / "nowhere") == []

    def test_record_usage_never_raises(self, tmp_path):
        blocked = tmp_path / "file-not-dir"
        blocked.write_text("x")
        record_usage(  # work dir path is a file: swallowed, not raised
            blocked, UsageRecord("judge", 1, "m", 1.0, "now")
        )
