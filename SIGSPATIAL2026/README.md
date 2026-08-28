# SIGSPATIAL 2026 Paper Draft

Working title:

> Offline Speed-Limit Inference on Smartphones: A Geospatial Systems Benchmark and Deployment Experience [Experiment]

This folder contains a fresh ACM SIGSPATIAL 2026 draft derived from:
- `../../youspeed.de-paper/itsc2026/main.tex`
- `../../youspeed.de-paper/techreport/main.tex`
- `../../youspeed.de-paper/techreport/data/matcher_ladder_rows.tex`
- ITSC 2026 reviews in `../../youspeed.de-paper/itsc2026/reviews/`

Build:

```sh
make
```

Evidence workflows:

```sh
# Stratified latency benchmark. S2/S4 are skipped unless their configured artifacts exist.
python3 scripts/run_stratified_latency_benchmark.py --architectures S1,S2,S3,S4

# Fast local validation run against the available Karlsruhe S3 artifact.
python3 scripts/run_stratified_latency_benchmark.py --architectures S3 --distance-modes bbox,hybrid,polyline --repeats 3 --warmups 1

# Normalize daily update impact metrics.
python3 scripts/normalize_update_metrics.py

# Validate and summarize hard-case audit corpus.
python3 scripts/build_hard_case_audit_pack.py --strict

# Add S3 top-candidate context for the seeded hard cases.
python3 scripts/build_hard_case_context.py

# Render paper figures from generated CSV/JSONL evidence.
python3 scripts/plot_evidence_figures.py
```

Generated outputs:
- `results/latency/latency_raw.csv`
- `results/latency/latency_summary_by_stratum.csv`
- `results/latency/latency_mode_summary.csv`
- `results/update_metrics/update_metrics_summary.csv`
- `results/update_metrics/update_metrics_table.tex`
- `results/hard_cases/hard_case_audit_summary.json`
- `results/hard_cases/hard_case_candidate_context.md`
- `figures/stratified_latency_p95.pdf`
- `figures/update_metrics_summary.pdf`
- `figures/hardcase_top_candidate_agreement.pdf`

Current pre-submission gaps:
- Run the stratified latency benchmark on the final Germany/Baden-Wuerttemberg S1-S4 artifacts and on the target iPhone hardware. The current committed sample run is S3-only because S2/S4 artifacts are not present locally.
- Add payload byte and validation/decompression timings to the daily update workflow; the existing daily CSV normalizes touched units and S3/S4 apply time but does not capture S1/S2 replacement bytes.
- Manually audit the seeded hard-case rows. They are intentionally marked `needs_manual_review` until a reviewer records a correct way ID and evidence note.
- Verify ACM page count under the final SIGSPATIAL template after figures, tables, and author metadata are final.
