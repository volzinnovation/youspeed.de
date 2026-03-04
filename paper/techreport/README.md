# Paper Sources (arXiv-style)

This directory contains LaTeX sources for the technical report covering:
- v1-v4 runtime architecture comparison (S1-S4 scenarios),
- on-device/query and incremental-update evaluation (including polycontainment),
- technical vision and architecture scope aligned with current app behavior (highway-first in-city classification, residential polygon fallback, simple tunnel mode),
- international extension: country bundles and sanction-rule model for the 10 countries with highest maxspeed availability.

Key files:
- `main.tex`: manuscript
- `main.pdf`: latest local build artifact
- `arxiv.sty`: arXiv-style template package
- `../share/references.bib`: bibliography
- `../share/IEEEabrv.bib`: IEEE abbreviation strings
- `data/benchmark_report.json`: benchmark source data used in the manuscript
- `data/europe_maxspeed_ranking_rows.tex`: generated appendix rows for the Europe ranking table

Build locally (if LaTeX is installed):
```bash
cd paper/techreport
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

Alternative single-command build:
```bash
cd paper/techreport
latexmk -pdf main.tex
```
