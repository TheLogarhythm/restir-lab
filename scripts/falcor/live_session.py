"""Compatibility entry point for the Falcor live demo."""

from .live_demo.acceptance import acceptance_steps, step, validate_sequence, verify
from .live_demo.launcher import main, run_session
from .live_demo.scenes import ROOT

if __name__ == "__main__":
    raise SystemExit(main())
