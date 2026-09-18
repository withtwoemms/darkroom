"""Built-in evidence producers."""

from darkroom.producers.command import CommandTranscriptProducer
from darkroom.producers.files import DiffProducer, FileSnapshotProducer
from darkroom.producers.log import LogProducer
from darkroom.producers.screenshot import ElementScreenshotProducer, ScreenshotProducer
from darkroom.producers.video import VideoProducer

__all__ = [
    "CommandTranscriptProducer",
    "DiffProducer",
    "ElementScreenshotProducer",
    "FileSnapshotProducer",
    "LogProducer",
    "ScreenshotProducer",
    "VideoProducer",
]
