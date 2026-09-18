# Project guidance

Reproduce and evaluate ReSTIR using RTXDI and selected Falcor implementations.

- Do not commit to `main` without the user's explicit request or approval.
- Keep renderer integrations separate, preserve upstream layouts, and pin dependency versions.
- Keep unrelated projects out of this repository; store large assets and generated output in ignored directories.
- Preserve original course templates and guidelines; edit working copies only.
- Follow `experiments/protocol.md` for reproducibility and comparisons; maintain provenance in `THIRD_PARTY.md`.
- Distinguish author-code runs, reproduced results, and independent implementations; separate observations from hypotheses.
- Run `python scripts/check_scaffold.py` after structural changes and relevant checks after renderer changes. Report only verified outcomes and state limitations.
