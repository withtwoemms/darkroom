"""Unit tests for the filesystem ticket store."""

import pytest

from darkroom.cli import main
from darkroom.tickets import AlreadyClaimed, TicketError, TicketStore


class TestEnqueueAndQueue:
    def test_round_trip(self, tmp_path):
        store = TicketStore(tmp_path)
        ticket = store.enqueue(
            "builder",
            "fix press notification",
            body="Outbox stays empty after approval.",
            scenario="press_notified",
        )
        assert ticket.id.endswith("fix-press-notification")

        queued = store.queue("builder")
        assert len(queued) == 1
        loaded = queued[0]
        assert loaded.title == "fix press notification"
        assert loaded.body == "Outbox stays empty after approval."
        assert loaded.fields["scenario"] == "press_notified"
        assert loaded.role == "builder"

    def test_file_is_greppable_markdown(self, tmp_path):
        store = TicketStore(tmp_path)
        ticket = store.enqueue("judge", "score run 42")
        text = (tmp_path / "queue" / "judge" / f"{ticket.id}.md").read_text()
        assert text.startswith("---\n")
        assert "title: score run 42" in text

    def test_id_collision_gets_suffix(self, tmp_path):
        store = TicketStore(tmp_path)
        first = store.enqueue("builder", "same title")
        second = store.enqueue("builder", "same title")
        assert first.id != second.id

    def test_roles_and_empty_queue(self, tmp_path):
        store = TicketStore(tmp_path)
        assert store.roles() == []
        assert store.queue("builder") == []
        store.enqueue("builder", "a")
        store.enqueue("judge", "b")
        assert store.roles() == ["builder", "judge"]


class TestClaiming:
    def test_claim_is_exclusive(self, tmp_path):
        store = TicketStore(tmp_path)
        ticket = store.enqueue("builder", "work")
        with store.claim(ticket):
            assert store.is_claimed(ticket.id)
            with pytest.raises(AlreadyClaimed):
                with store.claim(ticket):
                    pass
        assert not store.is_claimed(ticket.id)

    def test_lock_released_on_exception(self, tmp_path):
        store = TicketStore(tmp_path)
        ticket = store.enqueue("builder", "work")
        with pytest.raises(RuntimeError):
            with store.claim(ticket):
                raise RuntimeError("boom")
        assert not store.is_claimed(ticket.id)

    def test_force_steals_stale_lock(self, tmp_path):
        store = TicketStore(tmp_path)
        ticket = store.enqueue("builder", "work")
        (tmp_path / "locks").mkdir(exist_ok=True)
        (tmp_path / "locks" / f"{ticket.id}.lock").write_text("stale")
        assert store.lock_age(ticket.id) is not None
        with store.claim(ticket, force=True):
            assert store.is_claimed(ticket.id)

    def test_lock_age_none_when_unclaimed(self, tmp_path):
        store = TicketStore(tmp_path)
        ticket = store.enqueue("builder", "work")
        assert store.lock_age(ticket.id) is None


class TestResolution:
    def test_resolve_moves_to_history_with_disposition(self, tmp_path):
        store = TicketStore(tmp_path)
        ticket = store.enqueue("builder", "fix it", scenario="s1")
        destination = store.resolve(ticket, "done", note="wired the outbox")

        assert store.queue("builder") == []
        text = destination.read_text()
        assert "disposition: done" in text
        assert "## Disposition" in text
        assert "wired the outbox" in text

        history = store.history("builder")
        assert len(history) == 1
        assert history[0].fields["disposition"] == "done"
        assert history[0].fields["scenario"] == "s1"

    def test_resolve_clears_lock(self, tmp_path):
        store = TicketStore(tmp_path)
        ticket = store.enqueue("builder", "fix it")
        (tmp_path / "locks").mkdir(exist_ok=True)
        (tmp_path / "locks" / f"{ticket.id}.lock").write_text("")
        store.resolve(ticket, "blocked")
        assert not store.is_claimed(ticket.id)

    def test_resolve_missing_ticket(self, tmp_path):
        store = TicketStore(tmp_path)
        ticket = store.enqueue("builder", "fix it")
        store.resolve(ticket, "done")
        with pytest.raises(TicketError):
            store.resolve(ticket, "done")


class TestTicketCLI:
    def test_new_list_resolve(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert main([
            "ticket", "new", "builder", "fix press notification",
            "--field", "scenario=press_notified",
        ]) == 0
        out = capsys.readouterr().out
        assert out.startswith("enqueued: builder/")
        ticket_id = out.strip().split("/", 1)[1]

        assert main(["ticket", "list"]) == 0
        out = capsys.readouterr().out
        assert "fix press notification" in out and "1 open ticket(s)" in out

        assert main([
            "ticket", "resolve", "builder", ticket_id,
            "--disposition", "done", "--note", "shipped",
        ]) == 0
        assert "resolved:" in capsys.readouterr().out

        assert main(["ticket", "list"]) == 0
        assert "0 open ticket(s)" in capsys.readouterr().out

    def test_state_dir_from_adapter_defaults(self, tmp_path, capsys, monkeypatch):
        (tmp_path / "darkroom.toml").write_text(
            '[project]\nname = "p"\n[defaults]\nstate = "custom/state"'
        )
        monkeypatch.chdir(tmp_path)
        assert main(["ticket", "new", "builder", "hello"]) == 0
        capsys.readouterr()
        assert (tmp_path / "custom" / "state" / "queue" / "builder").is_dir()

    def test_resolve_unknown_is_error(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert main([
            "ticket", "resolve", "builder", "nope", "--disposition", "done",
        ]) == 2
        assert "error:" in capsys.readouterr().out
