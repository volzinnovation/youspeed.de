# Paper Sources (arXiv-style)

This directory contains LaTeX sources for a scientific summary of the v1-v4 map runtime architectures.

Files:
- `main.tex`: manuscript
- `arxiv.sty`: arXiv-style template package
- `../share/references.bib`: bibliography
- `../share/IEEEabrv.bib`: IEEE abbreviation strings
- `data/benchmark_report.json`: benchmark source data used in the manuscript (v1-v4)

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
