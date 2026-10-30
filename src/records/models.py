"""Backend-neutral views of saved data, with missing evidence kept explicit."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CapturedFrame:
    index: int
    image: Path
    sha256: str
    reset: bool | None
    sampling_frame: int | None
    target: dict | None = None


@dataclass(frozen=True)
class RunRecord:
    backend: str
    directory: Path
    manifest_sha256: str
    width: int
    height: int
    frames: tuple[CapturedFrame, ...]
    seed: int | None
    controls: tuple[dict, ...]
    config: dict
    provenance: dict
    limitations: tuple[str, ...]
    capabilities: frozenset[str]

    def frame(self, index):
        if type(index) is not int:
            raise ValueError("Frame index must be an integer")
        for frame in self.frames:
            if frame.index == index:
                return frame
        raise ValueError(f"Missing captured frame {index}")
