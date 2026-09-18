# Renderer integrations

| Location | Intended role | Current state |
| --- | --- | --- |
| `rtxdi/` | RTXDI sample-based baseline | Documentation only |
| `falcor/` | Selected paper's Falcor implementation | Documentation only |

RTXDI: https://github.com/NVIDIA-RTX/RTXDI

Falcor framework: https://github.com/NVIDIAGameWorks/Falcor

Candidate author implementation: https://github.com/DQLin/ReSTIR_PT

## Integration procedure

1. Select the upstream repository and exact commit, matching the paper when appropriate.
2. Create a team fork if code changes are needed; preserve notices and upstream history.
3. Move the slot's onboarding README to `docs/decisions/` so the target directory is empty before adding the submodule.
4. Add the chosen repository at that location, check out the selected commit, and commit `.gitmodules` and the gitlink together.
5. Record license, build instructions, tested environment, and local changes.
6. Have both teammates initialize recursive submodules and run the same small scene.

Select the actual compatible author branch rather than adding the latest Falcor automatically. Add more paper-specific checkouts only when needed. No submodules are registered by the scaffold.
