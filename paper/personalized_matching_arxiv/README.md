# Personalized Matching Paper

This paper targets an ITS audience and uses the `arxiv` template for fast iteration before venue-specific reformatting.

## Primary venue target

Current recommendation: `ICITT 2026` in Oslo, Norway.

Why this fits:
- Full-paper venue with an official paper deadline on `2026-04-05`.
- Topic scope includes intelligent traffic systems, transportation safety, navigation, and AI in transportation.
- Oslo is a strong conference city with clear tourism upside: fjord access, Opera House, MUNCH museum, island ferries, and waterfront sauna culture.

Audience framing for this manuscript:
- emphasize deployable ITS value, not only ML novelty
- keep the story anchored in mobile ISA, offline operation, and resource-constrained real-time inference
- present learning as a conservative adapter around an auditable matcher, not a black-box replacement

Official links:
- Conference: <https://www.icitt.org/>
- Call for papers: <https://www.icitt.org/cfp.html>
- Tourism: <https://www.visitoslo.com/en/>

Backup option:
- `EuroCarto 2026` is a reasonable GIS/cartography backup, but it is a weaker fit for the current ITS-oriented story and is centered on abstracts rather than this paper's full empirical framing.

## Refresh from a new log

1. Generate hindsight labels and datasets.

```bash
python3 /Users/raphaelvolz/Github/youspeed.de/scripts/iphone/analyze_hindsight_match_labels.py \
  /Users/raphaelvolz/Github/youspeed.de/inspector/cw_bh_drive_match_log.ndjson \
  --future-window 5 \
  --min-future-run-length 5 \
  --min-agreement-ratio 0.8 \
  --summary-out /Users/raphaelvolz/Github/youspeed.de/tmp/hindsight_match_summary.json \
  --pseudolabels-out /Users/raphaelvolz/Github/youspeed.de/tmp/hindsight_match_pseudolabels.jsonl
```

```bash
python3 /Users/raphaelvolz/Github/youspeed.de/scripts/iphone/export_hindsight_training_dataset.py \
  /Users/raphaelvolz/Github/youspeed.de/inspector/cw_bh_drive_match_log.ndjson \
  --future-window 5 \
  --min-future-run-length 5 \
  --min-agreement-ratio 0.8 \
  --output-prefix /Users/raphaelvolz/Github/youspeed.de/tmp/hindsight
```

2. Refresh the paper data fragments from the current benchmark artifacts.

```bash
python3 /Users/raphaelvolz/Github/youspeed.de/scripts/iphone/render_hindsight_paper_artifacts.py \
  --match-summary /Users/raphaelvolz/Github/youspeed.de/tmp/hindsight_match_summary.json \
  --training-summary /Users/raphaelvolz/Github/youspeed.de/tmp/hindsight_training_summary.json \
  --benchmark /Users/raphaelvolz/Github/youspeed.de/tmp/hindsight_model_benchmark.json \
  --gate-csv /Users/raphaelvolz/Github/youspeed.de/tmp/hindsight_gate_dataset.csv \
  --output-dir /Users/raphaelvolz/Github/youspeed.de/paper/personalized_matching_arxiv/data
```

3. Compile the paper.

```bash
cd /Users/raphaelvolz/Github/youspeed.de/paper/personalized_matching_arxiv
latexmk -pdf main.tex
```

## Current artifact inputs

- Match summary: `/Users/raphaelvolz/Github/youspeed.de/tmp/hindsight_match_summary.json`
- Training summary: `/Users/raphaelvolz/Github/youspeed.de/tmp/hindsight_training_summary.json`
- Benchmark snapshot: `/Users/raphaelvolz/Github/youspeed.de/tmp/hindsight_model_benchmark.json`
- Gate dataset: `/Users/raphaelvolz/Github/youspeed.de/tmp/hindsight_gate_dataset.csv`

## Notes

- The manuscript intentionally separates narrative from metrics. New logs should usually update only the generated files under `data/`.
- The current benchmark snapshot is a retained multi-log study. Treat cross-driver and route-type conclusions as provisional until the coverage expands further, especially for tunnels and high-speed motorway segments.
