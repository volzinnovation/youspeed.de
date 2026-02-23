# Paper Sources (arXiv-style)

This directory contains LaTeX sources for a scientific summary of the v1-v4 map runtime architectures.

Files:
- `main.tex`: manuscript
- `arxiv.sty`: arXiv-style template package
- `references.bib`: bibliography
- `data/benchmark_report.json`: benchmark source data used in the manuscript (v1-v4)

Build locally (if LaTeX is installed):
```bash
cd techreport
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

Alternative single-command build:
```bash
cd techreport
latexmk -pdf main.tex
```
