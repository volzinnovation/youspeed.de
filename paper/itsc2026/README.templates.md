# ITSC 2026 Submission Folder

Prepared on 2026-02-23 and updated for the shortened IEEE conference draft.

## Included locally

- `main.tex` (rewritten IEEE conference paper draft)
- `../share/references.bib`
- `IEEEtran.cls`
- `IEEEtran.bst`
- `../share/IEEEabrv.bib`
- `constraints-and-track-fit.md`

## Build

```bash
cd paper/itsc2026
latexmk -pdf main.tex
```

## Notes

- The manuscript is formatted for IEEE conference submission and currently compiles to 4 pages.
- This is under the ITSC initial submission limit of 6 pages.
- The long-form manuscript remains under `paper/techreport/`.
