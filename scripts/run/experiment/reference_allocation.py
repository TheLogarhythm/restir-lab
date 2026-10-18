"""Requested light-class work for full-target, equally weighted batch means."""
from .config import NEE_SAMPLE_COUNTS

CLASSES = ("local", "environment", "infinite")
ARGUMENT_CLASSES = ("LocalLight", "Environment", "InfiniteLight")
PROGRESS_UNIT = "local_samples_per_stream"


def count_map(value, *, minimum=0, maximum=None):
    if (not isinstance(value, dict) or set(value) != set(CLASSES)
            or any(type(n) is not int or n < minimum or maximum is not None and n > maximum
                   for n in value.values())):
        raise ValueError("Invalid reference light-class counts")
    return dict(value)


def allocation_record(counts, batch, samples, previous_samples, previous_totals):
    counts = count_map(counts, minimum=1, maximum=64)
    if counts["local"] != batch:
        raise ValueError("Reference progress must equal the local-light batch count")
    if previous_samples and previous_totals is None:
        raise ValueError("Unequal-budget resume requires parent light-class counts")
    previous = count_map(previous_totals if previous_totals is not None else dict.fromkeys(CLASSES, 0))
    if previous["local"] != previous_samples or (not previous_samples and any(previous.values())):
        raise ValueError("Reference parent allocation differs from resumed batches")
    batches = (samples - previous_samples) // batch
    return {"progress_unit": PROGRESS_UNIT, "batch_counts": counts, "previous_samples": previous,
            "cumulative_samples": {name: previous[name] + batches * counts[name] for name in CLASSES}}


def allocation_totals(config):
    """Validate requested budgets; absent classes can execute fewer samples.

    Legacy v3 records imply equal counts. Counts describe work, not pooling
    weights: every full-target batch retains equal weight across allocations.
    """
    ref = config["reference"]
    if ref.get("diagnostic_only") or ref.get("estimator") != "conventional_light_sampling":
        raise ValueError("Diagnostic or unsupported estimator cannot be a full reference")
    batch = ref["batch_samples_per_light_class"]
    resumed = ref.get("resume_batches", 0)
    if type(batch) is not int or not 1 <= batch <= 64 or type(resumed) is not int or resumed < 0:
        raise ValueError("Invalid reference batch count")
    samples = ref["checkpoints"][-1]
    if type(samples) is not int or samples <= resumed * batch or samples % batch:
        raise ValueError("Invalid reference allocation endpoint")
    stored = ref.get("allocation")
    if stored is not None and not isinstance(stored, dict):
        raise ValueError("Invalid reference allocation record")
    counts = dict.fromkeys(CLASSES, batch) if stored is None else stored.get("batch_counts")
    expected = allocation_record(counts, batch, samples, resumed * batch,
        dict.fromkeys(CLASSES, resumed * batch) if stored is None else stored.get("previous_samples"))
    if stored is not None and stored != expected:
        raise ValueError("Reference allocation totals or progress unit differ")
    definition, arguments = config["definition"], config["arguments"]
    if (definition.get("initial_brdf_candidates") != 0
            or arguments.get("restirDI.initialSampling.numBrdfSamples") != 0):
        raise ValueError("Reference must use conventional light samples without BRDF reuse")
    for name, argument in zip(CLASSES, ARGUMENT_CLASSES):
        for actual in (definition.get(f"initial_{name}_candidates"),
                       arguments.get(f"restirDI.initialSampling.num{argument}Samples")):
            if type(actual) is not int or actual != expected["batch_counts"][name]:
                raise ValueError("Reference light-class budgets differ from allocation")
    mode = definition.get("initial_local_sampling_mode", "UNIFORM")
    if mode not in NEE_SAMPLE_COUNTS:
        raise ValueError("Invalid reference local-light sampling mode")
    actual = arguments.get("restirDI.neeLocalLightSampling." + NEE_SAMPLE_COUNTS[mode])
    if type(actual) is not int or actual != expected["batch_counts"]["local"]:
        raise ValueError("Reference local-sampling budget differs from allocation")
    return expected["cumulative_samples"]
