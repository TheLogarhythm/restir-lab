"""A persistent, fail-closed total wall-clock budget for one controlled suite."""
from datetime import datetime, timedelta, timezone
import json
import hashlib
import math
from pathlib import Path


class BudgetExceeded(RuntimeError):
    """The suite's total allowance has been consumed."""


def _utc(value, label):
    try:
        instant = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(instant, datetime) or instant.utcoffset() is None:
            raise ValueError("timezone is required")
        return instant.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"Invalid {label}: an aware timestamp is required") from error


def _positive_finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"Invalid {label}: a positive finite number is required")
    return float(value)


class ExperimentBudget:
    """Charge elapsed wall time since the earliest suite render, including restarts.

    ``directory`` is the controlled suite root: only manifests recursively below
    that root belong to its accounting. Archived runs and diagnostics count.
    A saved policy is never reset or extended automatically.
    """

    def __init__(self, directory, hours=30, now=None, *, authorization=None):
        hours = _positive_finite(hours, "budget hours")
        if hours > 30:
            raise ValueError("The controlled experiment total budget cannot exceed 30 hours")
        self.directory = Path(directory)
        self.path = self.directory / "execution-budget.json"
        self._now = now if now is not None else lambda: datetime.now(timezone.utc)
        current = _utc(self._now(), "current time")
        starts = []
        for path in self.directory.rglob("manifest.json"):
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(manifest, dict):
                    raise ValueError("manifest must be an object")
                if "started_utc" in manifest:
                    starts.append(_utc(manifest["started_utc"], f"manifest start in {path}"))
            except (OSError, ValueError) as error:
                raise ValueError(f"Cannot establish prior experiment time from {path}: {error}") from error
        earliest = min(starts, default=current)
        if earliest > current:
            raise ValueError("Prior experiment start cannot be in the future")
        if not self.path.exists():
            self.directory.mkdir(parents=True, exist_ok=True)
            policy = {"version": 1, "accounting": "wall_clock", "limit_hours": hours,
                      "started_utc": earliest.isoformat(),
                      "deadline_utc": (earliest + timedelta(hours=hours)).isoformat()}
            # Exclusive creation prevents a competing process from resetting it.
            try:
                with self.path.open("x", encoding="utf-8") as stream:
                    stream.write(json.dumps(policy, indent=2) + "\n")
            except FileExistsError:
                pass
        try:
            policy = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(policy, dict) or policy.get("version") != 1 or policy.get("accounting") != "wall_clock":
                raise ValueError("Unsupported execution-budget policy")
            limit = _positive_finite(policy.get("limit_hours"), "saved budget hours")
            self._started = _utc(policy.get("started_utc"), "saved budget start")
            self._deadline = _utc(policy.get("deadline_utc"), "saved budget deadline")
            if limit != hours or self._deadline != self._started + timedelta(hours=limit):
                raise ValueError("Saved budget duration/deadline differs from its fixed allowance")
            if self._started > earliest:
                raise ValueError("Saved budget start would omit prior elapsed experiment time")
        except (OSError, ValueError, OverflowError) as error:
            raise ValueError(f"Invalid execution-budget policy {self.path}: {error}") from error
        self._record = policy
        if authorization is not None:
            try:
                window = json.loads(Path(authorization).read_text(encoding="utf-8"))
                if (window.get("version") != 1 or window.get("approved_by") != "user"
                        or window.get("scope") != "sparse_references_and_analysis"
                        or window.get("original_budget_sha256") != hashlib.sha256(self.path.read_bytes()).hexdigest()):
                    raise ValueError("A matching explicit user authorization is required")
                start = _utc(window.get("not_before_utc"), "approved window start")
                end = _utc(window.get("deadline_utc"), "approved window deadline")
                approved = _utc(window.get("approved_utc"), "approval time")
                if not approved <= start < end:
                    raise ValueError("Invalid approved reference window")
                self._started, self._deadline = start, end
                self._record = {"version": 2, "accounting": "approved_reference_window",
                    "original_budget": policy, "authorization": window,
                    "started_utc": start.isoformat(), "deadline_utc": end.isoformat()}
            except (OSError, ValueError, TypeError, AttributeError) as error:
                raise ValueError(f"Invalid reference-window authorization: {error}") from error

    @property
    def record(self):
        """Return policy metadata suitable for suite state/provenance records."""
        return dict(self._record)

    def remaining_seconds(self):
        current = max(self._started, _utc(self._now(), "current time"))
        return max(0.0, (self._deadline - current).total_seconds())

    def check(self):
        if _utc(self._now(), "current time") < self._started:
            raise BudgetExceeded(f"Approved reference window opens at {self._started.isoformat()}")
        if self.remaining_seconds() <= 0:
            raise BudgetExceeded(f"Controlled experiment total budget exhausted at {self._deadline.isoformat()}")

    def timeout(self, max_seconds):
        """Cap a subprocess timeout by the suite's remaining total allowance."""
        maximum = _positive_finite(max_seconds, "timeout")
        self.check()
        remaining = self.remaining_seconds()
        if remaining <= 0:
            raise BudgetExceeded(f"Controlled experiment total budget exhausted at {self._deadline.isoformat()}")
        return min(maximum, remaining)
