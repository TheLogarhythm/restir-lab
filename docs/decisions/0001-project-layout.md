# Decision 0001: project layout

Status: accepted for the scaffold.

Use one main repository with separate RTXDI/Falcor integration slots, shared experiment and scene records, and course writing sources. Start with public assets. Geometry work is basic preprocessing. Blender is optional for authoring, with no rendering plugin planned.

Selected renderer repositories will be pinned submodules, pointing to team forks when modified. Until selected, integration slots contain onboarding documentation only. No version pin or submodule registration is fabricated.

Keep bulk assets and raw outputs outside normal Git history. Preserve the two original course templates and guideline PDF separately from editable copies. Leave license selection to the authors.
