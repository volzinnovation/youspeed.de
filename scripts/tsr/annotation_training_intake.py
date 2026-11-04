#!/usr/bin/env python3
"""Build an offline, annotation-preserving native-crop training intake.

Every admitted input record remains in the manifest, including duplicates and
unreviewed visual proposals. Source-labelled training is an explicit opt-in;
it is never described as human review, a validation set, or a quality result.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.tsr.source_annotation_labels import resolve_crop_labels
from scripts.tsr import student_crop_intake


SCHEMA = "youspeed-annotation-training-intake-v1"
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
BASE_ARCHIVE = "panoramax-studenten-2026-10-19.zip"
DE_CATALOG = ROOT / "shared/tsr/prolix-de-class-catalog-v1.json"
OWNED_PANORAMAX_HOSTS = {"panoramax.woladen.de", "panoramax.youspeed.de"}
LICENSES = {
    "CC-BY-SA-4.0": "CC-BY-SA-4.0",
    "CC-BY-4.0": "CC-BY-4.0",
    "CC0-1.0": "CC0-1.0",
    "CC0": "CC0-1.0",
    "https://creativecommons.org/licenses/by-sa/4.0/": "CC-BY-SA-4.0",
    "https://creativecommons.org/licenses/by/4.0/": "CC-BY-4.0",
    "https://creativecommons.org/publicdomain/zero/1.0/": "CC0-1.0",
}
CSV_COLUMNS = ["sample_id", "path", "label", "class_index", "country", "split",
               "label_origin", "human_approved", "reviewer", "group_id", "license",
               "author", "source_url", "crop_sha256", "width", "height"]


class IntakeError(ValueError):
    """An intake contract or an explicit review record is invalid."""


def _load_json(value):
    return copy.deepcopy(value) if isinstance(value, (dict, list)) else json.loads(Path(value).read_text())


def _classes(value):
    payload = _load_json(value)
    classes = payload.get("classes") if isinstance(payload, dict) else payload
    if not isinstance(classes, list) or not classes or any(not isinstance(c, str) or not c for c in classes):
        raise IntakeError("Class index must contain nonempty exact class IDs")
    if len(classes) != len(set(classes)):
        raise IntakeError("Class index contains duplicate class IDs")
    payload = payload if isinstance(payload, dict) else {"classes": classes}
    baseline = payload.get("baseline_class_count", len(classes))
    if type(baseline) is not int or not 0 <= baseline <= len(classes):
        raise IntakeError("Invalid baseline class count")
    try:
        catalog_raw = DE_CATALOG.read_bytes()
        catalog = json.loads(catalog_raw)
    except (OSError, ValueError) as error:
        raise IntakeError("Cannot read the shared German source-code catalog") from error
    if catalog.get("country") != "DE" or not isinstance(catalog.get("signs"), list):
        raise IntakeError("Invalid shared German source-code catalog")
    codes = {}
    selected_classes = set(classes)
    for sign in catalog["signs"]:
        code, class_id = sign.get("sign_code"), sign.get("class_id")
        if isinstance(code, str) and code.startswith("DE:") and class_id in selected_classes:
            codes.setdefault(code, set()).add(class_id)
    for field in ("new_class_mapping", "canonical_source_codes"):
        for key, values in payload.get(field, {}).items():
            values = [values] if isinstance(values, str) else values
            if not isinstance(values, list):
                continue
            if key in classes:
                for code in values:
                    if isinstance(code, str):
                        codes.setdefault(code, set()).add(key)
            else:
                for class_id in values:
                    if class_id in classes:
                        codes.setdefault(key, set()).add(class_id)
    mapping_provenance = {
        "policy": "exact_shared_de_catalog_intersection_v1",
        "definition": "Exact source sign_code to catalog class_id mappings intersected with the selected class index. "
                      "Class-index declarations add candidates; multiple candidates remain ambiguous.",
        "catalog": {"path": DE_CATALOG.relative_to(ROOT).as_posix(),
                    "sha256": hashlib.sha256(catalog_raw).hexdigest(),
                    "schema_version": catalog.get("schema_version"), "country": "DE"},
        "class_index_mapping_fields": ["new_class_mapping", "canonical_source_codes"],
        "candidate_classes_by_source_code": {code: sorted(values) for code, values in sorted(codes.items())},
    }
    return payload, {"DE": selected_classes}, {"DE": set(classes[:baseline])}, codes, mapping_provenance


def _source_labels(codes, code_classes):
    labels = []
    for raw in codes:
        if not isinstance(raw, str):
            continue
        raw = raw.strip()
        if raw == "yes":
            labels.append({"raw_tag": raw, "parsed": {"raw": raw, "code": "yes"}})
            continue
        candidates = sorted(code_classes.get(raw, set()))
        labels.append({
            "raw_tag": raw, "target_classifier_country": raw.split(":", 1)[0] if ":" in raw else "unknown",
            "semantic_mapping_status": "unique" if len(candidates) == 1 else "ambiguous" if candidates else "unmapped",
            "semantic_candidates": [{"label": candidate} for candidate in candidates],
            "yolo_mapping_status": "unmapped",
        })
    return labels


def _resolve(record, source_kind, catalogs, models, code_classes):
    if source_kind == "panoramax":
        labels = record.get("labels", [])
    elif record.get("archive_name") == BASE_ARCHIVE:
        labels = _source_labels(record.get("source_annotation_labels", []), code_classes)
    else:
        # These four learning archives contain visual suggestions, not accepted
        # source labels, even when a stock manifest carries approval-like flags.
        return {"country": "DE", "class_id": None, "status": "unresolved",
                "label_origin": "student_visual_proposal", "classifier_supported": False,
                "review_required": True, "reasons": ["student_visual_proposal_requires_review"],
                "source_class_ids": [], "model_class_ids": [], "source_classes": [], "model_classes": [],
                "raw_tags": list(record.get("source_annotation_labels", [])), "ignored_detection_tags": []}
    return resolve_crop_labels(labels, catalogs, model_labels=models)


def _author(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return next((value[k].strip() for k in ("name", "display_name", "username")
                     if isinstance(value.get(k), str) and value[k].strip()), "")
    return ""


def _rights(record):
    evidence = record.get("rights") if isinstance(record.get("rights"), dict) else {}
    license_name = evidence.get("license") or record.get("license") or record.get("licence")
    author = _author(evidence.get("author") or record.get("author") or record.get("contributor"))
    source_url = evidence.get("source_url") or record.get("source_url")
    normalized = LICENSES.get(license_name) if isinstance(license_name, str) else None
    reasons = []
    if normalized is None:
        reasons.append("missing_or_unknown_image_license")
    if normalized != "CC0-1.0" and not author:
        reasons.append("missing_image_author")
    if not isinstance(source_url, str) or urlsplit(source_url).scheme not in {"https", "http"} or not urlsplit(source_url).netloc:
        reasons.append("missing_source_attribution_url")
    return {"license": license_name, "normalized_license": normalized, "author": author or None,
            "source_url": source_url, "license_evidence_url": evidence.get("license_evidence_url") or source_url,
            "valid": not reasons, "reasons": reasons}


def _namespace(record, source_kind):
    host = record.get("source_id") if source_kind == "panoramax" else None
    url = record.get("source_url") or record.get("source_base_url")
    if not host and isinstance(url, str):
        host = urlsplit(url).hostname
    if host in OWNED_PANORAMAX_HOSTS:
        return "owned-panoramax"
    return host or "hf-student"


def _png(data, expected, record):
    if not isinstance(expected, str) or not SHA256.fullmatch(expected):
        raise IntakeError("invalid_crop_sha256")
    if len(data) > student_crop_intake.MAX_CROP_BYTES:
        raise IntakeError("crop_exceeds_byte_limit")
    if hashlib.sha256(data).hexdigest() != expected:
        raise IntakeError("crop_sha256_mismatch")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "PNG":
                raise IntakeError("crop_is_not_png")
            dimensions = image.size
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as error:
        raise IntakeError("invalid_png_bytes") from error
    for key, value in zip(("width", "height"), dimensions):
        if record.get(key) is not None and record[key] != value:
            raise IntakeError("crop_dimensions_mismatch")
    return dimensions


class _Components:
    def __init__(self, count):
        self.parent = list(range(count))

    def find(self, item):
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left, right):
        self.parent[self.find(right)] = self.find(left)


def _connect(components, tokens):
    seen = {}
    for index, values in enumerate(tokens):
        for token in values:
            if token in seen:
                components.union(index, seen[token])
            else:
                seen[token] = index


def _reviews(path, sample_ids, classes):
    if path is None:
        return {}
    result = {}
    with Path(path).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not {"sample_id", "label", "reviewer"}.issubset(reader.fieldnames or []):
            raise IntakeError("Reviewed CSV requires sample_id,label,reviewer")
        for row in reader:
            sample_id, label, reviewer = (row.get(key, "").strip() for key in ("sample_id", "label", "reviewer"))
            if sample_id not in sample_ids or label not in classes or not reviewer:
                raise IntakeError("Reviewed CSV has an unknown sample, class or missing reviewer")
            if sample_id in result:
                raise IntakeError("Reviewed CSV lists a sample twice")
            result[sample_id] = {"label": label, "reviewer": reviewer}
    return result


def _csv(path, rows, columns):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_from_records(panoramax_records, student_records, *, panoramax_images, classes,
                       output, include_source_labels=False, reviewed_csv=None, as_of=None):
    """Retain all records/valid PNGs and create a deduplicated train-only CSV.

    Student records must come from ``read_student_archives``; crop bytes are
    always reverified through that adapter. Invalid/missing crops stay explicit
    in the manifest and never enter training. The CLI returns failure when any
    such record exists so an incomplete image copy cannot be mistaken for success.
    """
    class_index, catalogs, models, code_classes, mapping_provenance = _classes(classes)
    output, panoramax_images = Path(output), Path(panoramax_images)
    if output.exists() and any(output.iterdir()):
        raise IntakeError("Output directory must be empty; preserve previous intake builds")
    output.mkdir(parents=True, exist_ok=True)
    (output / "images").mkdir()
    entries, identities, duplicate_tokens, connection_tokens = [], [], [], []
    objects = {}
    seen_ids = set()
    for source_kind, records in (("panoramax", panoramax_records), ("hf_student", student_records)):
        for original in records:
            record = copy.deepcopy(original)
            if source_kind == "hf_student" and record.get("archive_name") not in student_crop_intake.PACKAGE_SCHEMAS:
                raise IntakeError("Student record is outside the five admitted learning archives")
            identifier = record.get("crop_id") if source_kind == "panoramax" else record.get("sample_id")
            if not isinstance(identifier, str) or not identifier or any(c in identifier for c in "/\\\0\r\n"):
                raise IntakeError("Invalid crop/sample identity")
            sample_id = "panoramax-" + identifier if source_kind == "panoramax" else identifier
            if sample_id in seen_ids:
                raise IntakeError("Input sample identity is repeated")
            seen_ids.add(sample_id)
            namespace = _namespace(record, source_kind)
            picture, annotation = record.get("picture_id"), record.get("annotation_id")
            identity = f"annotation:{namespace}:{picture}:{annotation}" if picture and annotation else None
            identities.append(identity)
            resolution = _resolve(record, source_kind, catalogs, models, code_classes)
            rights = _rights(record)
            digest = record.get("crop_sha256")
            image = {"valid": False, "path": None, "sha256": digest, "width": None, "height": None, "error": None}
            try:
                if source_kind == "panoramax":
                    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
                        raise IntakeError("invalid_crop_sha256")
                    path = panoramax_images / (digest + ".png")
                    if not path.is_file() or path.is_symlink():
                        raise IntakeError("missing_native_crop:" + str(path))
                    if path.stat().st_size > student_crop_intake.MAX_CROP_BYTES:
                        raise IntakeError("crop_exceeds_byte_limit")
                    data = path.read_bytes()
                else:
                    data = student_crop_intake.read_crop_bytes(record)
                width, height = _png(data, digest, record)
                relative = "images/" + digest + ".png"
                if digest not in objects:
                    (output / relative).write_bytes(data)
                    objects[digest] = {"path": relative, "sha256": digest, "bytes": len(data), "width": width, "height": height}
                image.update(valid=True, path=relative, width=width, height=height)
            except (IntakeError, student_crop_intake.StudentIntakeError, OSError) as error:
                image["error"] = str(error)
            sequences = record.get("sequence_ids") or ([record["sequence_id"]] if record.get("sequence_id") else [])
            groups = [f"sequence:{namespace}:{sequence}" for sequence in sequences if isinstance(sequence, str) and sequence]
            if picture:
                groups.append(f"picture:{namespace}:{picture}")
            if record.get("group_id"):
                groups.append(f"declared-group:{namespace}:{record['group_id']}")
            if image["valid"]:
                groups.append("crop-sha256:" + digest)
            duplicate_tokens.append(([identity] if identity else []) + (["crop-sha256:" + digest] if image["valid"] else []))
            connection_tokens.append(groups)
            entries.append({"sample_id": sample_id, "source_kind": source_kind,
                            "annotation_identity": identity, "resolution": resolution,
                            "proposed_label": record.get("proposed_label"), "image": image,
                            "rights": rights, "group_identities": sorted(set(groups)),
                            "review_status": "unreviewed", "human_approved": False,
                            "provenance": record})

    reviews = _reviews(reviewed_csv, seen_ids, catalogs["DE"])
    duplicates = _Components(len(entries))
    connected = _Components(len(entries))
    _connect(duplicates, duplicate_tokens)
    _connect(connected, connection_tokens)
    # Annotation revisions remain connected even if their crop hashes changed.
    _connect(connected, [[identity] if identity else [] for identity in identities])
    buckets = {}
    for index in range(len(entries)):
        buckets.setdefault(duplicates.find(index), []).append(index)
    connected_tokens = {}
    for index, tokens in enumerate(connection_tokens):
        connected_tokens.setdefault(connected.find(index), set()).update(tokens)
    samples, train_rows = [], []
    for indexes in buckets.values():
        indexes.sort(key=lambda i: (entries[i]["source_kind"] != "panoramax",
                                   entries[i]["provenance"].get("archive_name") != BASE_ARCHIVE,
                                   entries[i]["sample_id"]))
        chosen = entries[indexes[0]]
        canonical_id = chosen["sample_id"]
        for index in indexes:
            entries[index]["canonical_sample_id"] = canonical_id
            entries[index]["duplicate_of"] = None if index == indexes[0] else canonical_id
        approved = {reviews[entries[index]["sample_id"]]["label"] for index in indexes if entries[index]["sample_id"] in reviews}
        if len(approved) > 1:
            raise IntakeError("Duplicate crop has conflicting explicit review labels")
        review = next((reviews[entries[index]["sample_id"]] for index in indexes if entries[index]["sample_id"] in reviews), None)
        label = review["label"] if review else chosen["resolution"]["class_id"]
        origin = "human_review" if review else chosen["resolution"]["label_origin"]
        reasons = [] if review else list(chosen["resolution"]["reasons"])
        requires_review = False if review else chosen["resolution"]["review_required"]
        for index in indexes:
            other = entries[index]
            # Current source annotation revisions supersede the older HF copy;
            # conflicting labels on distinct annotations sharing bytes do not.
            same_annotation = bool(chosen["annotation_identity"] and other["annotation_identity"] == chosen["annotation_identity"])
            if (not review and not same_annotation
                    and other["resolution"]["class_id"] not in {None, label}):
                reasons.append("identical_crop_bytes_have_conflicting_source_labels")
                requires_review = True
        if not chosen["image"]["valid"]:
            requires_review = True
            reasons.append(chosen["image"]["error"] or "invalid_native_crop")
        if not chosen["rights"]["valid"]:
            requires_review = True
            reasons.extend(chosen["rights"]["reasons"])
        admitted = bool(label in catalogs["DE"] and not requires_review
                        and (review is not None or (include_source_labels and origin == "source_annotation")))
        if label and not review and not include_source_labels:
            reasons.append("source_label_training_not_enabled")
        group_tokens = sorted(connected_tokens[connected.find(indexes[0])])
        group_id = "connected-" + hashlib.sha256("\n".join(group_tokens or [canonical_id]).encode()).hexdigest()[:24]
        sample = {"sample_id": canonical_id, "record_sample_ids": [entries[index]["sample_id"] for index in indexes],
                  "source_record_count": len(indexes), "image": chosen["image"], "rights": chosen["rights"],
                  "country": "DE" if review else chosen["resolution"]["country"], "label": label,
                  "proposed_labels": sorted({entries[index]["proposed_label"] for index in indexes
                                             if isinstance(entries[index]["proposed_label"], str)}),
                  "label_origin": origin, "classifier_supported": label in models.get("DE", set()),
                  "human_approved": review is not None, "reviewer": review["reviewer"] if review else None,
                  "review_status": "approved" if review else "unreviewed", "review_required": requires_review,
                  "training_ready": admitted, "split": "train" if admitted else None,
                  "reasons": sorted(set(reasons)), "group_id": group_id,
                  "group_identities": group_tokens}
        samples.append(sample)
        for index in indexes:
            entries[index]["group_id"] = group_id
        if admitted:
            train_rows.append({"sample_id": canonical_id, "path": chosen["image"]["path"], "label": label,
                               "class_index": class_index["classes"].index(label), "country": sample["country"],
                               "split": "train", "label_origin": origin, "human_approved": review is not None,
                               "reviewer": sample["reviewer"], "group_id": group_id,
                               "license": chosen["rights"]["normalized_license"], "author": chosen["rights"]["author"],
                               "source_url": chosen["rights"]["source_url"], "crop_sha256": chosen["image"]["sha256"],
                               "width": chosen["image"]["width"], "height": chosen["image"]["height"]})

    samples.sort(key=lambda item: item["sample_id"])
    train_rows.sort(key=lambda item: (item["class_index"], item["sample_id"]))
    manifest = {"schema": SCHEMA, "generated_at": datetime.now(timezone.utc).isoformat(), "source_snapshot": as_of,
                "policy": {"include_source_labels": bool(include_source_labels), "all_records_retained": True,
                           "source_labels_are_human_review": False, "training_only": True,
                           "physical_sign_independence_established": False, "native_bytes_resized": False,
                           "reserved_teacher_demo_and_review_supplements_admitted": False},
                "class_index": class_index, "source_label_mapping": mapping_provenance,
                "record_count": len(entries), "unique_sample_count": len(samples),
                "records_by_source": dict(Counter(entry["source_kind"] for entry in entries)),
                "native_image_object_count": len(objects), "invalid_image_record_count": sum(not entry["image"]["valid"] for entry in entries),
                "training_sample_count": len(train_rows), "training_by_class": dict(Counter(row["label"] for row in train_rows)),
                "review_queue_sample_count": sum(not sample["training_ready"] for sample in samples),
                "records": entries, "samples": samples, "native_image_objects": sorted(objects.values(), key=lambda item: item["sha256"]),
                "validation": {"input_record_count": len(panoramax_records) + len(student_records),
                               "all_input_records_retained": len(entries) == len(panoramax_records) + len(student_records),
                               "deduplicated_record_sum": sum(sample["source_record_count"] for sample in samples),
                               "all_training_images_valid": all(row["crop_sha256"] in objects for row in train_rows),
                               "all_training_rights_valid": all(sample["rights"]["valid"] for sample in samples if sample["training_ready"]),
                               "all_training_splits_are_train": all(row["split"] == "train" for row in train_rows)}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    (output / "class-index.json").write_text(json.dumps(class_index, indent=2, ensure_ascii=False) + "\n")
    _csv(output / "train.csv", train_rows, CSV_COLUMNS)
    _csv(output / "review-queue.csv", [{"sample_id": sample["sample_id"], "source_label": sample["label"],
                                      "proposed_label": ";".join(sample["proposed_labels"]),
                                      "review_required": sample["review_required"], "reasons": ";".join(sample["reasons"]),
                                      "path": sample["image"]["path"], "group_id": sample["group_id"]}
                                     for sample in samples if not sample["training_ready"]],
         ["sample_id", "source_label", "proposed_label", "review_required", "reasons", "path", "group_id"])
    return manifest


def build_intake(*, panoramax_export, panoramax_images, student_collection, student_archives,
                 student_revision, classes, output, include_source_labels=False, reviewed_csv=None):
    """Load the pinned five-archive collection and a current Panoramax export."""
    payload = _load_json(panoramax_export)
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise IntakeError("Panoramax export must contain a records list")
    students = student_crop_intake.read_student_archives(Path(student_collection), Path(student_archives),
                                                        dataset_revision=student_revision)
    return build_from_records(records, students, panoramax_images=panoramax_images, classes=classes,
                              output=output, include_source_labels=include_source_labels, reviewed_csv=reviewed_csv,
                              as_of=payload.get("as_of") if isinstance(payload, dict) else None)


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("panoramax-export", "panoramax-images", "student-collection", "student-archives", "classes", "output"):
        parser.add_argument("--" + option, required=True, type=Path)
    parser.add_argument("--student-revision", required=True)
    parser.add_argument("--include-source-labels", action="store_true",
                        help="Admit unique source annotations without claiming human review; visual proposals remain withheld")
    parser.add_argument("--reviewed-csv", type=Path, help="Explicit approvals with sample_id,label,reviewer columns")
    return parser.parse_args(argv)


def main(argv=None):
    try:
        result = build_intake(**vars(arguments(argv)))
    except (IntakeError, student_crop_intake.StudentIntakeError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps({key: result[key] for key in ("record_count", "unique_sample_count", "native_image_object_count",
                                                 "invalid_image_record_count", "training_sample_count", "review_queue_sample_count")}))
    return 2 if result["invalid_image_record_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
