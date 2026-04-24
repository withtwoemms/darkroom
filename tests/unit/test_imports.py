"""Smoke tests that the public API imports cleanly."""


def test_import_top_level():
    from darkroom import (
        CaptureContext,
        EvidenceCapture,
        EvidenceItem,
        EvidenceProducer,
        EvidenceRun,
        RunManifest,
        ScenarioBundle,
        dump_manifest,
        load_manifest,
    )

    assert EvidenceItem is not None
    assert ScenarioBundle is not None
    assert RunManifest is not None
    assert EvidenceProducer is not None
    assert CaptureContext is not None
    assert EvidenceCapture is not None
    assert EvidenceRun is not None
    assert load_manifest is not None
    assert dump_manifest is not None


def test_import_producers():
    from darkroom.producers import LogProducer, ScreenshotProducer

    assert LogProducer is not None
    assert ScreenshotProducer is not None


def test_import_compat():
    from darkroom.compat import (
        EVIDENCE_DIR,
        ensure_dirs,
        screenshot,
        timestamp,
    )

    assert EVIDENCE_DIR is not None
    assert ensure_dirs is not None
    assert timestamp is not None
    assert screenshot is not None


def test_version():
    from darkroom import __version__

    assert isinstance(__version__, str)
    assert len(__version__) > 0
