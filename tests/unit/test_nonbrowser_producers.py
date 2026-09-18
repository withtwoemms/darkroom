"""Unit tests for the command, file-snapshot, and diff producers."""

import hashlib
import json
import sys
from pathlib import Path

from darkroom.producer import CaptureContext
from darkroom.producers.command import CommandTranscriptProducer
from darkroom.producers.files import DiffProducer, FileSnapshotProducer


def _ctx(tmp_path, step="step", step_count=1):
    return CaptureContext(
        scenario="scenario_a",
        step=step,
        run_dir=tmp_path,
        step_count=step_count,
    )


class TestCommandTranscriptProducer:
    def test_captures_successful_command(self, tmp_path):
        item = CommandTranscriptProducer().capture(
            _ctx(tmp_path, step="greet"),
            argv=[sys.executable, "-c", "print('hello')"],
        )
        assert item.kind == "command_transcript"
        assert item.metadata["exit_code"] == 0
        assert "duration_ms" in item.metadata
        transcript = json.loads((tmp_path / item.path).read_text())
        assert transcript["stdout"].strip() == "hello"
        assert transcript["exit_code"] == 0
        assert transcript["timed_out"] is False

    def test_captures_failure_exit_code_and_stderr(self, tmp_path):
        item = CommandTranscriptProducer().capture(
            _ctx(tmp_path),
            argv=[sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
        )
        assert item.metadata["exit_code"] == 3
        transcript = json.loads((tmp_path / item.path).read_text())
        assert transcript["stderr"] == "boom"

    def test_string_argv_is_split(self, tmp_path):
        item = CommandTranscriptProducer().capture(
            _ctx(tmp_path), argv=f"{sys.executable} -c 'print(42)'"
        )
        transcript = json.loads((tmp_path / item.path).read_text())
        assert transcript["stdout"].strip() == "42"
        assert transcript["argv"][0] == sys.executable

    def test_timeout_recorded(self, tmp_path):
        item = CommandTranscriptProducer().capture(
            _ctx(tmp_path),
            argv=[sys.executable, "-c", "import time; time.sleep(5)"],
            timeout=0.2,
        )
        assert item.metadata["timed_out"] is True
        assert item.metadata["exit_code"] is None

    def test_output_truncation(self, tmp_path):
        item = CommandTranscriptProducer().capture(
            _ctx(tmp_path),
            argv=[sys.executable, "-c", "print('x' * 100)"],
            max_output_bytes=10,
        )
        transcript = json.loads((tmp_path / item.path).read_text())
        assert transcript["stdout"] == "x" * 10
        assert transcript["stdout_truncated"] is True


class TestFileSnapshotProducer:
    def test_copies_content_with_checksum(self, tmp_path):
        source = tmp_path / "seed.yaml"
        source.write_bytes(b"crew: [ada, lin]\n")
        item = FileSnapshotProducer().capture(_ctx(tmp_path, step="seed"), source=source)
        assert item.kind == "file_snapshot"
        assert item.path == Path("scenario_a/01-seed.yaml")
        assert (tmp_path / item.path).read_bytes() == b"crew: [ada, lin]\n"
        assert item.metadata["size_bytes"] == 17
        assert item.metadata["sha256"] == hashlib.sha256(b"crew: [ada, lin]\n").hexdigest()
        assert item.metadata["source"] == str(source)

    def test_mime_guessed_from_extension(self, tmp_path):
        source = tmp_path / "report.json"
        source.write_text("{}")
        item = FileSnapshotProducer().capture(_ctx(tmp_path), source=source)
        assert item.mime == "application/json"

    def test_unknown_extension_falls_back(self, tmp_path):
        source = tmp_path / "blob.xyzq"
        source.write_bytes(b"\x00")
        item = FileSnapshotProducer().capture(_ctx(tmp_path), source=source)
        assert item.mime == "application/octet-stream"


class TestDiffProducer:
    def test_unified_diff_with_counts(self, tmp_path):
        before = tmp_path / "before.txt"
        after = tmp_path / "after.txt"
        before.write_text("one\ntwo\nthree\n")
        after.write_text("one\n2\nthree\nfour\n")
        item = DiffProducer().capture(
            _ctx(tmp_path, step="config_change"), before=before, after=after
        )
        assert item.kind == "diff"
        text = (tmp_path / item.path).read_text()
        assert text.startswith(f"--- {before}")
        assert "+2" in text and "-two" in text and "+four" in text
        assert item.metadata["lines_added"] == 2
        assert item.metadata["lines_removed"] == 1

    def test_identical_files_produce_empty_diff(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("same\n")
        f2.write_text("same\n")
        item = DiffProducer().capture(_ctx(tmp_path), before=f1, after=f2)
        assert (tmp_path / item.path).read_text() == ""
        assert item.metadata["lines_added"] == 0
        assert item.metadata["lines_removed"] == 0
