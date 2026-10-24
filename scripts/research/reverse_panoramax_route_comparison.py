#!/usr/bin/env python3
"""Reverse the frozen comparison: Panoramax annotation observations → bundle.

All top-level categories are exclusive. Photo annotations and source records are
not physical sign counts. In particular, camera GPS cannot locate each annotated
sign or reliably deduplicate different views into physical objects.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sqlite3

from profile_panoramax_route_signs import family

LABELS = {
    "photo_and_bundle_agree": "Photo and bundle agree",
    "possible_match": "Possible match",
    "same_kind_variant_unclear": "Same kind, variant unclear",
    "possible_wrong_number": "Possible wrong number",
    "same_kind_unknown_number": "Same kind, number unknown",
    "unknown_label": "Sign label unknown",
    "low_confidence": "Sign label uncertain",
    "no_corresponding_type_in_dataset": "That sign type is absent from the dataset",
    "type_present_no_spatial_counterpart_or_ambiguous": "Type exists, but no clear nearby counterpart",
}


def category(observation, dataset_families):
    """Resolve unknown/type absence first; never double-count cone exclusions."""
    if observation["canonical_code"] is None:
        return "unknown_label"
    if family(observation["canonical_code"]) not in dataset_families:
        return "no_corresponding_type_in_dataset"
    status = observation["status"]
    return {
        "unique_exact_code_value_compatible": "photo_and_bundle_agree",
        "exact_code_compatible_candidate": "possible_match",
        "family_class_consistent_variant_unresolved": "same_kind_variant_unclear",
        "unique_numeric_value_conflict_candidate": "possible_wrong_number",
        "numeric_value_conflict_unresolved_identity": "possible_wrong_number",
        "same_family_missing_numeric_value": "same_kind_unknown_number",
        "low_confidence_annotation": "low_confidence",
    }.get(status, "type_present_no_spatial_counterpart_or_ambiguous")


def reverse_comparison(comparison, source_codes):
    dataset_families = {family(code) for code in source_codes}
    counts, details, missing, observations = Counter(), defaultdict(Counter), Counter(), []
    for observation in comparison["observations"]:
        status = category(observation, dataset_families)
        counts[status] += 1
        details[status][observation["status"]] += 1
        if status == "no_corresponding_type_in_dataset":
            missing[observation["canonical_code"]] += 1
        observations.append(dict(photo_id=observation["photo_id"], annotation_id=observation["annotation_id"],
                                 code=observation["observed_code"], category=status, label=LABELS[status],
                                 previous_status=observation["status"], candidate_sign_ids=observation["candidate_sign_ids"],
                                 camera_lat=observation["camera_lat"], camera_lon=observation["camera_lon"],
                                 camera_heading=observation["camera_heading"],
                                 route_heading_error_deg=observation["route_heading_error_deg"],
                                 captured_at=observation["captured_at"], item_url=observation["item_url"],
                                 image_url=observation["image_url"], classification_model=observation["classification_model"],
                                 classification_confidence=observation["classification_confidence"]))
    cone = [o for o in observations if o["previous_status"] == "no_inventory_candidate_in_camera_cone"]
    cone_partition = Counter(o["category"] for o in cone)
    return dict(format="youspeed.panoramax.reverse-route-comparison.v1", unit="photo sign annotation observations",
                question="For each forward-facing photo annotation, is there a corresponding sign in the bundle?",
                cohort=dict(photos_in_origin_bbox=comparison["summary"]["input_photos"],
                            forward_route_photos=comparison["summary"]["photo_direction_filters"]["aligned_route_camera"],
                            annotation_observations=len(observations),
                            unique_annotation_ids=len({o["annotation_id"] for o in observations}),
                            unique_photo_ids=len({o["photo_id"] for o in observations})),
                exclusive_counts={key: counts[key] for key in LABELS if counts[key]},
                readable_counts=[dict(category=key, label=LABELS[key], count=counts[key],
                                      original_statuses=dict(details[key])) for key in LABELS if counts[key]],
                total_check=dict(category_sum=sum(counts.values()), cohort=len(observations), matches=sum(counts.values()) == len(observations)),
                missing_types=dict(type_families=len({family(code) for code in missing}),
                                   annotation_observations=sum(missing.values()),
                                   code_observation_counts=dict(missing.most_common())),
                non_additive_cone_diagnostic=dict(total=len(cone), already_in_exclusive_categories=dict(cone_partition),
                                                add_to_top_level_counts=False),
                different_count_units=dict(exact_code_matching_photo_annotations=counts["photo_and_bundle_agree"] + counts["possible_match"],
                                           exact_code_compatible_inventory_records=comparison["summary"]["distinct_inventory_ids_exact_code_compatible"],
                                           inferred_secondary_slot_inventory_ids=comparison["summary"]["inferred_secondary_slot_ids"],
                                           actual_painted_ui_count=None, confirmed_physical_mismatches=None),
                physical_sign_count=dict(value=None, reliable_estimate_available=False,
                                         reason="Annotations have camera positions, not individual sign positions or shared physical-object IDs. Camera-distance clustering cannot distinguish repeated views from separate adjacent signs with a defensible error bound."),
                interpretation=["40/55-style counts refer to annotation observations and may include repeated photos of one sign",
                                "Photo and bundle agree means one candidate has the same code/value and verified direction under the stated spatial gates; it does not prove physical identity",
                                "Possible matches have the same code/value but uncertain identity or source direction",
                                "Absent sign type means its family is missing from the full53-code MobiData snapshot, not that every photo observation is a different missing physical sign",
                                "No nearby counterpart can reflect source coverage, camera/sign offset, field of view or ambiguous association",
                                "A possible wrong number needs physical-object review before calling the source wrong",
                                "Historical logs do not record what was painted on screen or seen by the driver"],
                thresholds=comparison["thresholds"], observations=observations)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-summary", type=Path)
    parser.add_argument("--out-marker-status", type=Path)
    args = parser.parse_args()
    comparison = json.loads(args.comparison.read_text())
    with sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        codes = [r[0] for r in db.execute("SELECT DISTINCT sign_code FROM traffic_sign_inventory WHERE source_id='mobidata-bw-vzk' ORDER BY sign_code")]
    report = reverse_comparison(comparison, codes)
    report["inputs"] = dict(comparison=str(args.comparison.resolve()), comparison_sha256=hashlib.sha256(args.comparison.read_bytes()).hexdigest(),
                            db=str(args.db.resolve()), source_exact_codes=codes)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    compact = {key: value for key, value in report.items() if key not in ("observations", "inputs")}
    if args.out_summary:
        args.out_summary.write_text(json.dumps(compact, ensure_ascii=False, indent=2) + "\n")
    if args.out_marker_status:
        marker = {o["annotation_id"] + "|" + o["code"]: dict(category=o["category"], label=o["label"]) for o in report["observations"]}
        args.out_marker_status.write_text(json.dumps(marker, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
