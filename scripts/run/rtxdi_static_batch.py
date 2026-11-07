"""Deprecated worker/status entry point; use rtxdi_comparison.py.

Retained for command paths recorded in historical process.json files. Historical
rendering still requires its archived sources; the canonical gate rejects resume
with changed code. Remove after those external worker/status callers migrate.
"""
import sys
from rtxdi_comparison import main

if __name__ == "__main__":
    print("Deprecated: use rtxdi_comparison.py; groups are selected by configuration.", file=sys.stderr)
    main()
