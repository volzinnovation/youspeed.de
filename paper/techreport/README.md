# Paper Sources (arXiv-style)

This directory contains LaTeX sources for the technical report covering:
- the current end-to-end system architecture and local-first bundle pipeline,
- the current iPhone release-track app and Android internal-alpha feature scope,
- jurisdiction handling across bundled countries and the current warning-rule layering,
- Germany-specific maxspeed provenance plus the Europe-wide explicit-tag analysis across 45 extracts,
- the actual bundle-generation, sharding, publication, and iterative-update pipeline,
- the runtime architecture comparison (S1-S4 scenarios),
- the broader matcher-approach ladder on the retained offline benchmark,
- the current matcher-profile comparison on replay and geometry-stress corpora,
- future work around jurisdiction-aware defaults, iterative updates, and matcher convergence,
- appendix material for bundle contracts, the current v3 runtime database schema, and the full Europe ranking,
- related work positioned around present product constraints rather than future roadmap sections.

Key files:
- `main.tex`: manuscript
- `main.pdf`: latest local build artifact
- `arxiv.sty`: arXiv-style template package
- `../share/references.bib`: bibliography
- `../share/IEEEabrv.bib`: IEEE abbreviation strings
- `data/benchmark_report.json`: archived benchmark source data retained for reference

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
