"""Typed saved-result views and offline readers for supported backends."""

from .models import CapturedFrame, RunRecord
from .readers import load_frame, read_run

__all__ = ["CapturedFrame", "RunRecord", "load_frame", "read_run"]
