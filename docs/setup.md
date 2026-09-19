# Setup

## Scaffold

Requirements: Git and Python 3.11 or newer. The scaffold validator uses only the Python standard library. Run from the repository root:

```text
python scripts/check_scaffold.py
```

No renderer binaries, scenes, submodules, or measured results are installed. Local `assets/`, `runs/`, and `build/` are ignored; recreate them as needed after cloning.

## Renderers

Follow [the integration procedure](../renderers/README.md). Record OS, GPU/VRAM, driver, compiler, graphics SDK, shader compiler, and upstream commit. Follow the selected implementation's own build instructions; a current Falcor release may not match an older paper implementation.

## Course documents

Edit `writing/course/proposal/main.tex` and `writing/course/report/main.tex`. The proposal is a draft with shared references; the report still contains instructional template text. Friday will add his proposal background in a separate commit. Complete the report placeholders when drafting it; see the [roadmap](roadmap.md) for submission dates. Preserve originals in `writing/course/templates/`.

With TeX Live installed, create `build/latex/proposal` and `build/latex/report`. Run the proposal commands below from the repository root so BibTeX finds the shared bibliography:

```text
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/latex/proposal writing/course/proposal/main.tex
bibtex build/latex/proposal/main
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/latex/proposal writing/course/proposal/main.tex
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/latex/proposal writing/course/proposal/main.tex
```

These commands were verified for the current draft with TeX Live 2024. The output is `build/latex/proposal/main.pdf`. The report template can be compiled separately:

```text
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/latex/report writing/course/report/main.tex
```

The report does not yet invoke the shared bibliography. Add citations and bibliography commands when drafting it.
