"""Reference precision checks for the controlled PDF comparison."""
import numpy as np

from .artifacts import save_json
from .error_metrics import smape
from .images import write_pfm
from .reference import convergence, regions, rmae
from .reference_runner import PoseAssessment

QUALITY_METRICS = {"rmae": rmae, "smape": smape}


class ControlledAssessment(PoseAssessment):
    """Require two consecutive RMAE and SMAPE passes, including declared ROIs."""

    def __init__(self, captures, ratio, load_image, rois=(), min_samples=0):
        super().__init__(captures, ratio, load_image)
        self.rois = tuple(rois)
        self.min_samples = min_samples
        self.previous_checkpoint = None

    def add(self, samples, images):
        a, b = (np.asarray(image, dtype=np.float64) for image in images)
        reference = (a + b) * .5
        masks = {"full": regions(*reference.shape[:2])["full"]}
        for roi in self.rois:
            x, y, width, height = (roi[k] for k in ("x", "y", "width", "height"))
            if (not roi["name"] or roi["name"] in masks or min(x, y) < 0
                    or min(width, height) <= 0 or x + width > reference.shape[1]
                    or y + height > reference.shape[0]):
                raise ValueError("Invalid reference diagnostic region")
            masks[roi["name"]] = (slice(y, y + height), slice(x, x + width))
        # Stream held-pose captures instead of retaining hundreds of HDR images.
        best_errors = {name: dict.fromkeys(QUALITY_METRICS, float("inf")) for name in masks}
        for capture in self.captures:
            image = self.load_image(capture["image"])
            for name, mask in masks.items():
                for metric, function in QUALITY_METRICS.items():
                    best_errors[name][metric] = min(best_errors[name][metric],
                                                   function(image[mask], reference[mask]))
        checks = {}
        for name, mask in masks.items():
            values = convergence(a[mask], b[mask],
                None if self.previous is None else self.previous[mask])
            for metric, function in QUALITY_METRICS.items():
                best = best_errors[name][metric]
                noise = max(function(image[mask], reference[mask]) for image in (a, b))
                change = None if self.previous is None else function(self.previous[mask], reference[mask])
                threshold = self.ratio * best
                values[metric] = {"half_stream_error": noise, "checkpoint_change": change,
                    "best_method_error": best, "threshold": threshold,
                    "passed": change is not None and noise <= threshold and change <= threshold}
            values["passed"] = all(values[metric]["passed"] for metric in QUALITY_METRICS)
            checks[name] = values
        passed = samples >= self.min_samples and all(values["passed"] for values in checks.values())
        self.streak = self.streak + 1 if passed else 0
        self.rows.append({"samples_per_class_per_stream": samples, "regions": checks, "passed": passed})
        self.previous_checkpoint, self.previous = self.previous, reference
        return self.streak >= 2

    def save(self, directory):
        result = super().save(directory)
        if self.previous_checkpoint is not None:
            write_pfm(directory / "previous-reference.pfm.gz", self.previous_checkpoint)
        result.update(quality_version=1, quality_metrics=list(QUALITY_METRICS),
            convergence_regions=list(self.rows[-1]["regions"]),
            assumptions="Empirical independent half-stream and checkpoint checks in RMAE and SMAPE; "
                        "temporal gradients require the additional sequence check.")
        save_json(directory / "convergence.json", result)
        return result
