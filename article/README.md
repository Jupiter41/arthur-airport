# Compiling the article

`main.tex` uses the Springer LLNCS class (`llncs.cls`) and bibliography style
(`splncs04.bst`). Both are copied from `LaTeX2e+Proceedings+Template+ZIP/`
into this directory so the build is self-contained.

## Option A — local LaTeX distribution (MiKTeX / TeX Live)

Requires `pdflatex` on your PATH (install MiKTeX: https://miktex.org).

```powershell
cd article
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

The result is `main.pdf`. Run `pdflatex` twice after `bibtex` so citations and
the table of contents resolve.

## Option B — Docker (no local install)

```powershell
cd article
docker run --rm -v "${PWD}:/work" -w /work texlive/texlive `
  sh -c "pdflatex -interaction=nonstopmode main.tex && bibtex main && pdflatex -interaction=nonstopmode main.tex && pdflatex -interaction=nonstopmode main.tex"
```

## Clean up temporary build files

```powershell
cd article
Remove-Item main.aux, main.log, main.bbl, main.blg, main.out -ErrorAction SilentlyContinue
```

## Files

| File | Purpose |
|---|---|
| `main.tex` | The article source |
| `refs.bib` | BibTeX references |
| `llncs.cls` | Springer LNCS document class |
| `splncs04.bst` | LNCS bibliography style |
| `screenshots/`, `references/` | Assets for figures |
