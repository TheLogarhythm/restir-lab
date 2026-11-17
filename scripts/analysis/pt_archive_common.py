"""Shared IO and frozen coverage for the six-view PT archive entrypoints."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from records.archive import child, read, require, verify_inventory
from records.provenance import sha256 as sha

VIEWS = {"bistro-interior", "bistro-exterior", "classroom", "emerald-square", "veach-ajar", "zero-day-measure-seven"}
METHODS = {"temporal-off", "temporal-on", "cgns", "pdf"}
SEEDS = [0, 100000, 200000, 300000]
