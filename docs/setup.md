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

Edit `writing/course/proposal/main.tex` and `writing/course/report/main.tex`. Preserve the originals in `writing/course/templates/`. Group/author fields and instructional content still need to be filled in. Verify dates rather than assuming embedded template deadlines are current.

With TeX Live installed, create `build/latex/proposal` and `build/latex/report`, then run from the repository root:

```text
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/latex/proposal writing/course/proposal/main.tex
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/latex/report writing/course/report/main.tex
```

Repeat when cross-references need another pass. Use shared `writing/references.bib` when adding citations; bibliography commands are not yet added to the working templates.
