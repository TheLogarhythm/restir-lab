"""Historical RTXDI APIs backed by the shared library where applicable."""
from pathlib import Path
import sys

# Existing script commands keep working without an editable installation.
_source = str(Path(__file__).resolve().parents[3] / "src")
if _source not in sys.path:
    sys.path.insert(0, _source)
