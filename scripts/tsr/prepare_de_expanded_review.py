#!/usr/bin/env python3
"""Clone frozen field crops into a prediction-blind expanded-taxonomy review.

Only an explicit allowlist of review inputs is read. No training images, model
predictions or source-model labels enter this package. Prior human decisions,
if present, are archived unchanged and never promoted into a new approval.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.tsr.de_label_review import load_review


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def visual_updates() -> dict:
    changes = {}
    for key in ("A006", "A010", "A022", "A028"):
        changes[key] = dict(proposed_class_id="bus:stop", confidence="probable" if key == "A006" else "clear",
            visual_reason="Yellow/green H bus-stop sign (DE:224), now represented by bus:stop. It is distinct from bus:start (DE:245 bus lane)." +
            (" The small crop warrants particular human attention." if key == "A006" else ""))
    for key in ("I026", "I038"):
        changes[key] = dict(proposed_class_id="supplementary:plate", confidence="clear",
            visual_reason="White supplementary time plate showing 22–6 h. The new class identifies only the plate family; it does not establish the associated restriction or automatically apply these hours.")
    for key in ("P002", "P007", "P020"):
        direction = "straight" if key == "P007" else "right"
        changes[key] = dict(proposed_class_id="exit", confidence="clear",
            visual_reason=f"Blue numbered U-diversion panel with an arrow pointing {direction}. The original HF class-definition audit establishes exit as this numbered motorway-diversion family; route number and arrow subtype are not separate class outputs.")
    changes["A037"] = dict(proposed_class_id=None, confidence="needs_context",
        visual_reason="Brown tourist direction panel. The clarified exit family covers numbered U-diversion panels, so this crop must not be forced into exit; its residual wayfinding mapping still requires review.")
    changes["I032"] = dict(proposed_class_id=None, confidence="needs_context",
        visual_reason="Blue motorway direction board with destinations, route numbers and arrows. The clarified exit family covers numbered U-diversion panels, not every motorway direction board; the class mapping remains for human review.")
    return changes


def prepare_one(source: Path, target: Path, classes_path: Path, catalog: Path,
                expected_count: int, updates: dict, context: dict) -> dict:
    intake = source / "intake"
    manifest_path = intake / "benchmark-all120.json"
    manifest = json.loads(manifest_path.read_text())
    images = manifest["images"]
    ids = [r["id"] for r in images]
    if len(ids) != expected_count or len(ids) != len(set(ids)) or not all(re.fullmatch(r"[A-Z][0-9]{3}", k) for k in ids):
        raise ValueError("Unexpected frozen image count or duplicate/invalid IDs")
    classes = json.loads(classes_path.read_text())["classes"]
    old_classes = json.loads((source / "class-index.json").read_text())["classes"]
    if len(old_classes) != 136 or classes[:136] != old_classes:
        raise ValueError("Expanded review must preserve all 136 predecessor class indices")
    if not set(updates) <= set(ids):
        raise ValueError("Visual update refers to an image outside the frozen intake")
    blind = json.loads((intake / "evaluation-blind.json").read_text())
    if ({r["blind_id"] for r in blind["samples"]} != set(ids)
            or any(r.get("truth_label") is not None for r in blind["samples"])):
        raise ValueError("Require exactly the original unadjudicated blind samples")
    source_files = {}
    image_files = []
    changes = []
    manual_reviews = []
    target.mkdir(parents=True)

    def preserve(path: Path, destination: Path) -> None:
        relative = str(path.relative_to(source))
        before = sha(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        if sha(destination) != before:
            raise ValueError("Source changed while copying " + relative)
        source_files[relative] = before

    preserve(manifest_path, target / "intake/benchmark-all120.json")
    preserve(source / "class-index.json", target / "provenance/source-class-index.json")
    preserve(intake / "evaluation-blind.json", target / "provenance/source-evaluation-blind.json")
    for relative in ("review-context.json", "package-provenance.json", "intake/blind/review-manifest.json", "intake/blind/review-package.json",
                     "intake/blind/review-progress.json", "intake/blind/review-approved.json"):
        path = source / relative
        if path.is_file():
            preserve(path, target / "provenance" / relative)
            if path.name in ("review-progress.json", "review-approved.json"):
                manual_reviews.append({"path": relative, "sha256": source_files[relative],
                                       "treatment": "Archived byte-for-byte; expanded taxonomy requires new explicit review."})
    for item in images:
        for key, expected in (("path", item["sha256"]), ("canonicalPath", item["canonicalSha256"]),
                              ("blind", None)):
            relative = item[key] if key != "blind" else f"blind/{item['id']}.png"
            path = intake / relative
            if not path.resolve().is_relative_to(intake.resolve()) or path.suffix != ".png":
                raise ValueError("Unsafe crop path")
            if expected is not None and sha(path) != expected:
                raise ValueError("Frozen crop digest mismatch: " + item["id"])
            preserve(path, target / "intake" / relative)
            image_files.append({"id": item["id"], "path": relative, "sha256": sha(path)})
    proposal_ids = []
    proposal_digests = {}
    for name in ("phone", "panoramax"):
        relative = f"intake/blind/proposed-{name}-labels.json"
        path = source / relative
        preserve(path, target / "provenance" / relative)
        proposal = json.loads(path.read_text())
        for row in proposal["labels"]:
            proposal_ids.append(row["id"])
            before = deepcopy(row)
            if row["id"] in updates:
                row.update(updates[row["id"]])
            row["visual_reason"] = row["visual_reason"].replace("136-class catalog", f"{len(classes)}-class catalog")
            row.update(human_reviewed=False, approved=False)
            if row != before:
                changes.append({"id": row["id"], "before": before, "after": deepcopy(row),
                                "class_decision_changed": before["proposed_class_id"] != row["proposed_class_id"],
                                "basis": "Assistant visual inspection of original frozen pixels and audited class definitions; no model predictions. Class-count wording refreshed where necessary."})
        proposal["expanded_taxonomy_review"] = {
            "class_index_sha256": sha(classes_path), "class_count": len(classes),
            "source_proposal_sha256": sha(path), "requires_new_human_review": True,
            "predictions_used": False,
        }
        write(target / relative, proposal)
        proposal_digests[name] = {"source_sha256": sha(path), "expanded_sha256": sha(target / relative)}
    if len(proposal_ids) != len(set(proposal_ids)) or set(proposal_ids) != set(ids):
        raise ValueError("Source proposals do not cover the exact frozen intake")
    shutil.copyfile(classes_path, target / "class-index.json")
    blind["classes"] = classes
    blind["label_status"] = "unadjudicated_expanded_taxonomy_diagnostic"
    blind["expanded_review_provenance"] = {
        "source_evaluation_blind_sha256": source_files["intake/evaluation-blind.json"],
        "source_manifest_sha256": source_files["intake/benchmark-all120.json"],
        "class_index_sha256": sha(classes_path), "previously_taxonomy_inspected": True,
        "untouched_test_set": False, "truth_labels_approved": False,
    }
    write(target / "intake/evaluation-blind.json", blind)
    write(target / "intake/blind/review-manifest.json", {
        "schemaVersion": 1, "images": [{"id": i["id"], "path": i["id"] + ".png", "source": i["source"],
                                        "native_path": "../" + i["path"]} for i in images],
        "labels": classes, "annotation_policy": "Assistant visual proposals only. Every decision requires explicit human review. Previously taxonomy-inspected diagnostic comparison; not an untouched test set.",
    })
    write(target / "review-context.json", context)
    package = load_review(target, catalog)
    if any(r["reviewed"] for r in package["records"]):
        raise ValueError("Expanded review must start unapproved")
    write(target / "intake/blind/review-package.json", package)
    # If a person saved a review while we prepared the clone, do not publish a
    # package claiming that the old state was frozen throughout the copy.
    for name in ("review-progress.json", "review-approved.json"):
        relative = "intake/blind/" + name
        if (source / relative).exists() != (relative in source_files):
            raise ValueError("Human review changed during package creation; rerun to preserve it")
    if any(sha(source / relative) != digest for relative, digest in source_files.items()):
        raise ValueError("Source files changed during package creation")
    report = {
        "schema_version": 1, "status": "draft_for_explicit_user_review", "source_directory": str(source),
        "records": len(ids), "source_files_sha256": source_files, "image_files": image_files,
        "source_manifest_sha256": sha(manifest_path), "manifest_preserved_byte_for_byte": True,
        "source_proposal_digests": proposal_digests, "proposal_changes": changes,
        "manual_reviews_preserved": manual_reviews, "class_count": len(classes),
        "class_index_sha256": sha(classes_path), "catalog_reference_sha256": sha(catalog),
        "diagnostic_comparison_only": True, "previously_taxonomy_inspected": True,
        "untouched_test_set": False, "model_predictions_read": False, "training_images_added": False,
        "labels_approved": False, "final_f1_allowed": False,
    }
    write(target / "package-provenance.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=Path, required=True)
    parser.add_argument("--supplement", type=Path, required=True)
    parser.add_argument("--classes", type=Path, required=True)
    parser.add_argument("--class-index-sha256", required=True)
    parser.add_argument("--class-definition", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    classes = json.loads(args.classes.read_text())["classes"]
    if (sha(args.classes) != args.class_index_sha256 or len(classes) != 142
            or classes[136:] != ["bus:stop", "supplementary:plate", "maxspeed:90", "DE:156-10", "DE:325.1", "DE:325.2"]):
        raise ValueError("Require the frozen final 142-class index")
    if args.output.exists():
        raise ValueError("Output directory must be new; never overwrite human review")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".expanded-review-", dir=args.output.parent) as temporary:
        stage = Path(temporary) / "field-review"
        stage.mkdir()
        for source, name in ((args.classes, "class-index.json"), (args.catalog, "catalog-reference.json"),
                             (args.class_definition, "class-definition-change.json")):
            shutil.copyfile(source, stage / name)
        common = "Previously taxonomy-inspected diagnostic comparison using the same frozen crops and routes, not a new untouched test set. The class vocabulary is now 142. All proposals require new explicit human approval; no F1 has been calculated. Repeated views remain correlated, and unsupported classes remain unmeasured."
        reports = {}
        reports["main120"] = prepare_one(args.main, stage / "main120", stage / "class-index.json", stage / "catalog-reference.json", 120, visual_updates(), {
            "description": "Expanded-taxonomy review of the original 120 crops: 40 Android, 40 iPhone and 40 Panoramax. Images and IDs are unchanged.",
            "scope": common,
        })
        reports["supplement36"] = prepare_one(args.supplement, stage / "supplement36", stage / "class-index.json", stage / "catalog-reference.json", 36, {}, {
            "description": "Separate expanded-taxonomy review of the original 36 Panoramax supplement crops: 24 unresolved random selections and 12 yellow-rectangle screen selections. Images and IDs are unchanged.",
            "scope": common + " This targeted supplement cannot estimate population prevalence. All 36 pixels were re-inspected for newly represented plate and traffic-calmed classes; no additional justified proposal was found. Two original screening downloads were unavailable and were not replaced.",
        })
        write(stage / "package-provenance.json", {
            "schema_version": 1, "status": "draft_for_explicit_user_review", "records": 156,
            "class_count": len(classes), "class_index_sha256": sha(args.classes),
            "class_definition_sha256": sha(args.class_definition), "catalog_reference_sha256": sha(args.catalog),
            "script_sha256": sha(Path(__file__)),
            "packages": {key: {"records": r["records"], "source_manifest_sha256": r["source_manifest_sha256"],
                               "package_provenance_sha256": sha(stage / key / "package-provenance.json"),
                               "proposal_changes": len(r["proposal_changes"])} for key, r in reports.items()},
            "model_predictions_read": False, "training_images_added": False, "labels_approved": False,
            "final_f1_allowed": False, "untouched_test_set": False,
            "server_started": False, "suggested_ports": {"main120": 8768, "supplement36": 8769},
        })
        stage.rename(args.output)
    print(json.dumps({"output": str(args.output), "records": 156, "classes": 142, "approved": False}))


if __name__ == "__main__":
    main()
