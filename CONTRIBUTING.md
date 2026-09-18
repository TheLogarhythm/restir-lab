# Contributing

## Workflow

1. **Define the task.** Create an Issue with an owner, a goal, and a clear completion condition. Before GitHub is set up, agree on these in your shared notes.
2. **Work on a branch.** Use a short name such as `setup/rtxdi`. Keep each change focused. Do not commit to `main` without explicit user approval.
3. **Check the result.** Run checks relevant to the change. For repository structure changes, run `python scripts/check_scaffold.py`; for renderer changes, also verify building and rendering.
4. **Request review.** Open a Pull Request (PR) explaining what changed and how it was checked. Have your teammate review it and rerun important experiments before merging into `main`.

Example: Issue to run Cornell Box → `setup/rtxdi` branch → working demo and setup notes → PR → teammate verifies → merge.

## Research records

- Record code and scene versions, settings, and seeds so your teammate can repeat an experiment. Follow [the experiment protocol](experiments/protocol.md).
- Keep large assets and raw outputs in ignored directories; share their locations and keep small summaries in the repository.
- Separate observations from hypotheses, and record external code and AI assistance in [THIRD_PARTY.md](THIRD_PARTY.md).

Use Issues for tasks and [the roadmap](docs/roadmap.md) for milestones. Keep the process lightweight for small changes.
