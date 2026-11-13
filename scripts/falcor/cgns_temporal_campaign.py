"""Compatibility command for the temporal-on spatial/CGNS campaign."""

from . import spatial_campaign as _campaign
from .spatial_campaign import choose_attempt, validate_code_inputs


def validate_artifacts(directory, artifacts, schedule, width, height):
    return _campaign.validate_artifacts(
        directory, artifacts, schedule, width, height, temporal_reuse=True
    )


def validate_pair(a, ma, b, mb):
    return _campaign.validate_pair(a, ma, b, mb, temporal_reuse=True)


def run_campaign(output, *, retry_failed=False, experiment_path=None):
    return _campaign.run_campaign(
        output, retry_failed=retry_failed, experiment_path=experiment_path, temporal_reuse=True
    )


def main():
    _campaign.main(temporal_reuse=True, legacy=True)


if __name__ == "__main__":
    main()
