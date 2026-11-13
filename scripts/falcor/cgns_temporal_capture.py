"""Compatibility entry point for temporal-on fixed-view ReSTIR PT captures."""
from functools import partial
from . import spatial_capture as capture

ROOT = capture.ROOT
capture_schedule = capture.capture_schedule
validate_budget = capture.validate_budget
validate_runtime = capture.validate_runtime
seed_record = partial(capture.seed_record, temporal_reuse=True)
graph_options = partial(capture.graph_options, temporal_reuse=True)
render_script = partial(capture.render_script, temporal_reuse=True)
launch = partial(capture.launch, temporal_reuse=True)


def _portable_paths(experiment_path, runtime, command):
    return capture.portable_paths(experiment_path, runtime, command, ROOT)


def main():
    capture.main(temporal_reuse=True)


if __name__ == '__main__':
    main()
