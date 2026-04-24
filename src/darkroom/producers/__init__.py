"""Built-in evidence producers."""

from darkroom.producers.log import LogProducer
from darkroom.producers.screenshot import ElementScreenshotProducer, ScreenshotProducer

__all__ = ["ElementScreenshotProducer", "LogProducer", "ScreenshotProducer"]
