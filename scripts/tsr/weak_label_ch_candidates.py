#!/usr/bin/env python3
"""Create non-authoritative cross-country weak labels for CH candidate crops."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any


AVAILABLE_COUNTRIES = ("DE", "FR", "BE", "NL")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, default=None)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, default=Path("/mnt/nvme/prolix/models"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--countries", nargs="+", choices=AVAILABLE_COUNTRIES, default=["DE", "FR"])
    parser.add_argument("--min-confidence", type=float, default=0.90)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--device", default="0")
    parser.add_argument("--imgsz", type=int, default=224)
    args = parser.parse_args()
    output = args.output or args.run / "weak-labels.jsonl"
    records = read_jsonl(args.candidates or args.run / "candidates.jsonl")
    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    ch_codes = {
        entry["model_class_label"]: entry["country_codes"]["CH"]["raw"]
        for entry in mapping["entries"]
        if entry.get("country_codes", {}).get("CH", {}).get("raw")
    }
    country_label_aliases: dict[str, dict[str, str]] = {country: {} for country in AVAILABLE_COUNTRIES}
    for entry in mapping["entries"]:
        label = entry["model_class_label"]
        for country in AVAILABLE_COUNTRIES:
            code = entry.get("country_codes", {}).get(country)
            if not code:
                continue
            for value in (code.get("raw"), code.get("normalized")):
                if not value:
                    continue
                value = str(value)
                country_label_aliases[country][value] = label
                country_label_aliases[country][value.removeprefix(country + ":")] = label
                country_label_aliases[country][value.replace("[", "-").replace("]", "")] = label

    def model_label(country: str, raw_label: str) -> str | None:
        if raw_label in ch_codes:
            return raw_label
        aliases = country_label_aliases[country]
        if raw_label in aliases:
            return aliases[raw_label]
        # Some published classifier inventories omit a national variant
        # suffix (for example FR AB3 vs mapped AB3a). Only accept a prefix
        # match when it resolves to exactly one reviewed semantic label.
        matches = {label for key, label in aliases.items() if key and (key.startswith(raw_label) or raw_label.startswith(key))}
        return next(iter(matches)) if len(matches) == 1 else None

    from ultralytics import YOLO

    models = {}
    for country in args.countries:
        filename = {
            "DE": "classify_de_road_signs.pt",
            "FR": "best.pt",
            "BE": "classify_be_road_signs.pt",
            "NL": "classify_nl_road_signs.pt",
        }[country]
        models[country] = YOLO(str(args.model_root / country / "classifier" / filename))

    paths = [args.run / row["crop_path"] for row in records]
    predictions: dict[str, list[dict[str, Any]]] = {country: [] for country in args.countries}
    for country, model in models.items():
        results = model([str(path) for path in paths], device=args.device, imgsz=args.imgsz, batch=args.batch, verbose=False)
        for result in results:
            probabilities = getattr(result, "probs", None)
            if probabilities is None:
                predictions[country].append({"raw_label": None, "confidence": None, "ch_code": None})
                continue
            top = int(probabilities.top1)
            confidence = float(probabilities.top1conf)
            names = getattr(result, "names", {})
            raw_label = str(names.get(top, top) if isinstance(names, dict) else top)
            predictions[country].append({
                "raw_label": raw_label,
                "confidence": confidence,
                "model_class_label": model_label(country, raw_label),
                "ch_code": ch_codes.get(model_label(country, raw_label)),
            })

    output.parent.mkdir(parents=True, exist_ok=True)
    summary = Counter()
    with output.open("w", encoding="utf-8") as handle:
        for index, row in enumerate(records):
            country_predictions = {country: predictions[country][index] for country in args.countries}
            codes = [value["ch_code"] for value in country_predictions.values() if value["ch_code"]]
            counts = Counter(codes)
            consensus_code, consensus_count = (counts.most_common(1)[0] if counts else (None, 0))
            high_confidence = [value["ch_code"] for value in country_predictions.values() if value["ch_code"] and (value["confidence"] or 0) >= args.min_confidence]
            dual_agreement = len(args.countries) == 2 and consensus_count == 2 and len(codes) == 2 and len(high_confidence) == 2
            output_row = {
                "candidate_id": row["candidate_id"],
                "picture_id": row["picture_id"],
                "collection": row.get("collection"),
                "crop_path": row["crop_path"],
                "image_path": row.get("image_path"),
                "detector": row.get("detector", {}),
                "coordinates": row.get("coordinates"),
                "datetime": row.get("datetime"),
                "providers": row.get("providers", []),
                "license": row.get("license"),
                "source_item_url": row.get("source_item_url"),
                "source_instance_url": row.get("source_instance_url"),
                "country_model_predictions": country_predictions,
                "weak_label": {
                    "ch_code": consensus_code if dual_agreement else None,
                    "agreement_count": consensus_count,
                    "high_confidence_agreement_count": Counter(high_confidence).get(consensus_code, 0) if consensus_code else 0,
                    "status": "dual_classifier_consensus_pseudo_label" if dual_agreement else "excluded_disagreement_or_low_confidence",
                    "ground_truth_substitute": dual_agreement,
                },
            }
            handle.write(json.dumps(output_row, ensure_ascii=False) + "\n")
            summary["candidates"] += 1
            summary["weak_consensus"] += int(dual_agreement)
            summary["mapped_top1_any_model"] += int(bool(codes))
    summary_path = args.summary or output.with_name("weak-label-summary.json")
    summary_path.write_text(json.dumps({
        "status": "weak_labels_only",
        "models": {country: str(models[country].ckpt_path) for country in args.countries},
        "mapping": str(args.mapping),
        "countries": args.countries,
        "minimum_confidence": args.min_confidence,
        "counts": summary,
        "policy": "Per user instruction, only agreement between the selected classifiers at or above the confidence threshold is accepted as a CH training pseudo-label substitute; it is not runtime evidence or an independent evaluation holdout.",
    }, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
