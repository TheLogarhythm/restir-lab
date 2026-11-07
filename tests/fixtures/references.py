"""Small fixed-reference policies for offline artifact fixtures."""


def small_policy():
    return {
        "kind": "fixed_budget",
        "seed": 1001,
        "local_samples": 256,
        "max_local_samples": 256,
        "batch_counts": {"local": 64, "environment": 8, "infinite": 4},
        "checkpoints": [128, 256],
        "local_sampling": "POWER_RIS",
    }
