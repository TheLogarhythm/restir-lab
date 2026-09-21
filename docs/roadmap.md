# Roadmap

**Draft, updated 2026-09-21.** Relative weeks are planning assumptions, not confirmed course deadlines. The target is three methods from the [scope](scope.md), with one primary backend.

## Current progress

| Area | Status | Next step |
| --- | --- | --- |
| Pitch | Submitted to Canvas A1 on 2026-09-21; final video duration **3:28** ([completion record](https://github.com/TheLogarhythm/restir-lab/issues/1#issuecomment-5762409423)) | Complete |
| Literature | [Review](literature/README.md) and [reading matrix](literature/reading-matrix.csv): 31 papers and 2 supporting resources | Closely study DI, PDF Similarity, and CGNS |
| Proposal | [Working draft](../writing/course/proposal/main.tex) and [references](../writing/references.bib) prepared | Friday adds his background separately; jointly refine the draft using feedback and confirm schedule and hardware |
| Scaffold | Repository structure, templates, and checks available | Refine only as implementation requires |
| Renderer | RTXDI preferred; author Falcor code available as reference | Build a small scene and choose/pin one backend |
| Scenes | [Cornell Box, Bistro, and Arcade shortlisted](../scenes/README.md); not downloaded | Validate import, lighting, and GPU memory use |
| Algorithms and experiments | Not implemented or run | Establish the baseline before comparisons |

## Near-term tasks

Use the [Project board](https://github.com/users/TheLogarhythm/projects/1/views/1) for task status and the [Timeline](https://github.com/users/TheLogarhythm/projects/1/views/2) for dates. Keep detailed checklists in Issues, refine only the next one or two weeks, and add or remove tasks as work progresses.

| Task | Deadline (Hong Kong time) | Responsibility |
| --- | --- | --- |
| [Draft, refine, and submit proposal (#2)](https://github.com/TheLogarhythm/restir-lab/issues/2) | 2026-09-29, 23:59 | Logarhythm and Friday refine the draft using feedback and review together |

## Provisional ten-week plan

| Week | Milestone | Evidence of completion |
| --- | --- | --- |
| 1 | Proposal and scope | Three methods, implementation boundaries, team roles, hardware, and candidate scenes agreed |
| 2 | Feasibility | One backend builds and renders a small scene; extension integration points inspected; revision pinned |
| 3-4 | ReSTIR DI | Baseline and reuse controls work; direct-lighting reference and initial correctness checks available |
| 5 | Progress review and PDF Similarity | Baseline demonstrated; distribution estimation and rejection behavior tested in controlled cases |
| 6-7 | CGNS and integration | Three methods selectable; both extensions checked; diagnostic outputs and timing available |
| 8 | Demo and experiment freeze | Demo runs reliably; scene versions, metrics, and principal configurations fixed |
| 9-10 | Evaluation and final delivery | Comparisons, ablations, report, and teammate setup/reproduction check completed |

## Responsibilities and checkpoints

Proposed division: one member leads the renderer/baseline; the other leads scenes, references, and evaluation scripts. Split the two extensions and review each other's work. Logarhythm and Friday will agree on implementation roles after discussing availability.

At the end of week 2, confirm backend feasibility and DI transfer assumptions before committing to a port. If blocked, revise the backend or method plan explicitly. At the progress review, reduce optional sweeps or scene variants if needed. Preserve the final quarter of the schedule for integration, experiments, and writing; do not silently redefine partial implementations as completed papers.

Use GitHub Issues for individual tasks. Record confirmed choices in [decisions](decisions/), measured results in [the results index](../results/index.csv), and setup steps only after validation.
