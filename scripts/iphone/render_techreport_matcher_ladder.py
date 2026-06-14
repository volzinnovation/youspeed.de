#!/usr/bin/env python3
"""Render the technical-report matcher ladder table from cached replay artifacts."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "paper" / "techreport" / "data"

MODEL_ORDER = [
    "M1",
    "M2",
    "M3",
    "M4",
    "M5",
    "M6",
    "M7",
    "M8",
    "M9",
    "M10",
    "M11",
    "M12",
    "Valhalla",
]

MODEL_ROWS = {
    "connectedBaseline": ("M1", "Connected baseline"),
    "simpleSpeedRef": ("M2", "Nearest + street-ref continuity"),
    "simpleSpeedRefConnected": ("M3", "M2 + connected-candidate gate"),
    "corridorRawMiniHMM": ("M4", "Corridor raw mini-HMM"),
    "corridor": ("M5", "Corridor-aware final"),
    "simpleSpeedRefUrbanRelease": ("M6", "M2 + urban consecutive distance-gap release"),
    "simpleSpeedRefUrbanRelease10m": ("M7", "M6 + 10m search window"),
    "simpleSpeedRefStreetNameFallback": ("M8", "M6 + no-ref street-name continuity"),
    "simpleSpeedRefStreetNameGuard": ("M9", "M8 + guarded stale-ref suppression"),
    "simpleSpeedRefStreetNameGuardNodeAware": ("M10", "M9 + node-direction-aware junction release"),
    "simpleSequenceParticle": ("M11", "M10 + topology-free particle sequence"),
    "simpleSequenceViterbi": ("M12", "M11 + 10-fix Viterbi sequence"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expanded-replay",
        type=Path,
        default=REPO_ROOT / "tmp" / "all_logs_11_model_replay.json",
    )
    parser.add_argument(
        "--particle-replay",
        type=Path,
        default=REPO_ROOT / "tmp" / "m11_only_native_benchmark.json",
    )
    parser.add_argument(
        "--viterbi-replay",
        type=Path,
        default=REPO_ROOT / "tmp" / "m12_continuity_native_benchmark.json",
    )
    parser.add_argument(
        "--valhalla-replay",
        type=Path,
        default=REPO_ROOT / "tmp" / "valhalla_oracle_benchmark.json",
    )
    parser.add_argument(
        "--light-bundle",
        type=Path,
        default=REPO_ROOT / "tmp" / "karlsruhe-regbez_speeds.no_way_links.sqlite",
    )
    parser.add_argument(
        "--topology-bundle",
        type=Path,
        default=Path("/tmp/karlsruhe-regbez_m11.sqlite"),
    )
    parser.add_argument(
        "--full-bundle",
        type=Path,
        default=REPO_ROOT / "iphone" / "SpeedConsumerApp" / "karlsruhe-regbez_speeds.sqlite",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def percentile(values: list[float], p: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * p
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def format_int(value: int) -> str:
    return f"{value:,}"


def command(name: str, value: str) -> str:
    return f"\\newcommand{{\\{name}}}{{{value}}}"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def bundle_size_map(args: argparse.Namespace) -> dict[str, Path]:
    return {
        "M1": args.topology_bundle,
        "M2": args.light_bundle,
        "M3": args.topology_bundle,
        "M4": args.topology_bundle,
        "M5": args.topology_bundle,
        "M6": args.light_bundle,
        "M7": args.light_bundle,
        "M8": args.light_bundle,
        "M9": args.light_bundle,
        "M10": args.light_bundle,
        "M11": args.topology_bundle,
        "M12": args.full_bundle,
    }


def collect_model_rows(
    replay_payload: dict,
    rows: dict[str, dict],
) -> None:
    summaries_by_label = {
        entry["label"]: entry
        for entry in replay_payload.get("modelSummaries", [])
        if entry.get("label") in MODEL_ROWS
    }
    if not summaries_by_label:
        return

    for label, summary in summaries_by_label.items():
        model_id, display_name = MODEL_ROWS[label]
        query_time_summary = summary.get("queryTimeSummary") or {}
        query_p95_ms = query_time_summary.get("p95Ms")
        if query_p95_ms is None:
            query_times: list[float] = []
            for row in replay_payload.get("fixRows", []):
                for prediction in row.get("predictions", []):
                    if prediction.get("label") != label:
                        continue
                    query_time = prediction.get("queryTimeMs")
                    if query_time is not None:
                        query_times.append(float(query_time))
            query_p95_ms = percentile(query_times, 0.95)
        rows[model_id] = {
            "exp": model_id,
            "profile": display_name,
            "accuracy_pct": summary["accuracy"] * 100.0,
            "changed_recall_pct": summary["changedRecall"] * 100.0,
            "query_p95_ms": float(query_p95_ms),
            "logged_agreement_pct": summary["loggedAgreement"] * 100.0,
            "unchanged_accuracy_pct": summary["unchangedAccuracy"] * 100.0,
        }


def infer_valhalla_tiles_size_bytes(valhalla_payload: dict) -> tuple[int, str]:
    config_path = Path(valhalla_payload["configPath"])
    config = read_json(config_path)
    tile_dir = (
        config.get("tile_dir")
        or config.get("tile_extract")
        or config.get("mjolnir", {}).get("tile_extract")
        or config.get("mjolnir", {}).get("tile_dir")
    )
    if not tile_dir:
        raise SystemExit("Could not infer Valhalla tile path from config")
    tile_path = Path(tile_dir)
    if not tile_path.exists():
        raise SystemExit(f"Valhalla tile path does not exist: {tile_path}")
    if tile_path.is_file():
        return tile_path.stat().st_size, str(tile_path)
    total = sum(path.stat().st_size for path in tile_path.rglob("*") if path.is_file())
    return total, str(tile_path)


def render_tex(rows: dict[str, dict], replay_fix_count: int, pseudo_label_count: int) -> str:
    lines = [
        command("MatcherLadderCorpusFixes", format_int(replay_fix_count)),
        command("MatcherLadderPseudoExamples", format_int(pseudo_label_count)),
    ]
    row_lines: list[str] = []
    for key in MODEL_ORDER:
        row = rows[key]
        row_lines.append(
            (
                f"{row['exp']} & {row['profile']} & "
                f"{row['accuracy_pct']:.2f}\\% & "
                f"{row['changed_recall_pct']:.2f}\\% & "
                f"{row['bundle_mib']:.1f} & "
                f"{row['query_p95_ms']:.3f} \\\\"
            )
        )
    lines.append("\\newcommand{\\MatcherLadderRows}{%")
    lines.append("%\n".join(row_lines))
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    rows: dict[str, dict] = {}
    size_paths = bundle_size_map(args)

    expanded_replay = read_json(args.expanded_replay)
    collect_model_rows(expanded_replay, rows)
    collect_model_rows(read_json(args.particle_replay), rows)
    collect_model_rows(read_json(args.viterbi_replay), rows)

    for model_id, bundle_path in size_paths.items():
        if model_id not in rows:
            continue
        rows[model_id]["bundle_bytes"] = bundle_path.stat().st_size
        rows[model_id]["bundle_mib"] = bundle_path.stat().st_size / (1024.0 * 1024.0)
        rows[model_id]["bundle_path"] = str(bundle_path)

    valhalla_payload = read_json(args.valhalla_replay)
    valhalla_summary = valhalla_payload["summary"]
    valhalla_bundle_bytes, valhalla_bundle_path = infer_valhalla_tiles_size_bytes(valhalla_payload)
    rows["Valhalla"] = {
        "exp": "Valhalla",
        "profile": "Valhalla oracle",
        "accuracy_pct": valhalla_summary["accuracy"] * 100.0,
        "changed_recall_pct": valhalla_summary["changedRecall"] * 100.0,
        "query_p95_ms": valhalla_summary["windowP95Ms"],
        "bundle_bytes": valhalla_bundle_bytes,
        "bundle_mib": valhalla_bundle_bytes / (1024.0 * 1024.0),
        "bundle_path": valhalla_bundle_path,
        "logged_agreement_pct": valhalla_summary["loggedAgreement"] * 100.0,
        "unchanged_accuracy_pct": valhalla_summary["unchangedAccuracy"] * 100.0,
    }

    missing = [model_id for model_id in MODEL_ORDER if model_id not in rows]
    if missing:
        raise SystemExit(f"Missing matcher ladder rows: {', '.join(missing)}")

    replay_fix_count = int(valhalla_summary["replayed_fix_count"])
    pseudo_label_count = int(valhalla_summary["pseudo_label_example_count"])

    tex = render_tex(rows, replay_fix_count, pseudo_label_count)
    output_dir = args.output_dir
    write_text(output_dir / "matcher_ladder_rows.tex", tex)
    write_text(
        output_dir / "matcher_ladder_summary.json",
        json.dumps(
            {
                "replayFixCount": replay_fix_count,
                "pseudoLabelExampleCount": pseudo_label_count,
                "rows": [rows[key] for key in MODEL_ORDER],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )


if __name__ == "__main__":
    main()
