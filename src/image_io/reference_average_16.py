"""Compatibility entry point for sixteen independent FLOAT32 seed images."""
from .reference_average import _average_seed_exrs


def average_sixteen_seed_exrs(inputs, output):
    """Write the equal-weight linear RGB mean without overwriting inputs."""
    return _average_seed_exrs(inputs, output, seed_count=16)
