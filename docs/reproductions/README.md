# Reproductions

Each guide states its estimator, implementation differences, supported settings
and evidence limits. Running adapted author code does not reproduce a paper
figure or prove transport equivalence.

| Guide | Scope |
| --- | --- |
| [PDF Similarity: RTXDI DI](pdf-similarity.md) | DI implementation, usage and evaluation status |
| [CGNS: RTXDI DI](cgns.md) | Direct-light neighbor selection and diagnostics |
| [Spatial-reuse comparison](spatial-reuse.md) | Corrected RTXDI DI/GI/PT targets, protocol and retained-result limits |
| [CGNS: Falcor PT](falcor-cgns-pt.md) | PT selector, cached implementation and historical validation |
| [PDF Similarity: Falcor PT](falcor-pdf-pt.md) | First-hop adaptation, effective M, diagnostics and historical validation |
| [Six-view PT stage](pt-6-views-spatial-compare.md) | Completed archive, new batches, timing/metrics and runtime maintenance |

The [DI baseline](../../results/summaries/di-baseline/README.md) records adapted
RTXDI author-code results. [Decision history](../superpowers/README.md) records
implementation choices and dated checks.

[Controlled CGNS target contract](cgns-di-gi-pt.md) is frozen evidence whose
original path and bytes are required by historical comparison validation.
It is retained unchanged; use the spatial-reuse guide for maintained instructions.
