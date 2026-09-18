"""Built-in evidence producers."""

from darkroom.producers.log import LogProducer
from darkroom.producers.screenshot import ElementScreenshotProducer, ScreenshotProducer
from darkroom.producers.video import VideoProducer

__all__ = [
    "ElementScreenshotProducer",
    "LogProducer",
    "ScreenshotProducer",
    "VideoProducer",
]
