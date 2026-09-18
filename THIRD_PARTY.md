# Third-party materials

## Included course materials

| Material | Supplied source | Repository copy |
| --- | --- | --- |
| Proposal template | [COMP5411 course webpage](https://course.cse.ust.hk/comp5411/) (`proposal.tex`) | `writing/course/templates/proposal.tex` |
| Report template | [COMP5411 course webpage](https://course.cse.ust.hk/comp5411/) (`report.tex`) | `writing/course/templates/report.tex` |
| Course guidelines | [COMP5411 course webpage](https://course.cse.ust.hk/comp5411/) (`projguidelines.pdf`) | `writing/course/guidelines/projguidelines.pdf` |

All three materials are from the [HKUST COMP5411 course webpage](https://course.cse.ust.hk/comp5411/).

Working copies retain the template structure, use ReSTIR Lab and Fall 2026, and leave author/group fields unfilled. The report working copy defines the missing `DocTitle` macro used in its header. Original templates are unchanged.

## Planned dependencies (not included)

- RTXDI: https://github.com/NVIDIA-RTX/RTXDI
- A selected Falcor paper implementation; candidate: https://github.com/DQLin/ReSTIR_PT
- Assets listed in [the scene documentation](scenes/README.md).

When adding a dependency, record its URL, exact commit, license, local modifications, and included notices. Check licenses per asset rather than assuming a code license covers all content.

## Implementation provenance

The initial documentation, examples, validation script, and workflow were prepared with Codex assistance. Course templates and guidelines were copied from supplied originals. No renderer implementation is included. Maintain file-level human, AI-assisted, and upstream provenance in subsequent work and in the report's Implemented files appendix.
