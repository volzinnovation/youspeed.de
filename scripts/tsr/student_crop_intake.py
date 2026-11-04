"""Read the pinned student learning crops without approving their proposed labels.

Only the five learning packages are admitted. Teacher test packages, the demo,
and the separate multiclass review supplement never enter this intake. Crop
bytes are read directly from ZIP members without extracting full road images.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile


DATASET_ID = "loffenauer/ws26_hspf_imo"
COLLECTION_SCHEMA = "ws26-hspf-imo-learning-collection-v1"
PACKAGE_SCHEMAS = {
    "panoramax-studenten-2026-10-19.zip": "panoramax-course-collection-v1",
    "panoramax-mobidata-bw-review-2026-10-20-v2.zip": "youspeed-mobidata-town-sign-review-v2",
    "panoramax-mobidata-bw-review-2026-10-20-additions.zip": "youspeed-mobidata-town-sign-review-additions-v1",
    "mapillary-mobidata-bw-review-2026-10-21.zip": "youspeed-mapillary-mobidata-review-input-v1",
    "mapillary-mobidata-bw-review-2026-10-21-additions.zip": "youspeed-mapillary-mobidata-review-input-v1",
}
TOWN_LABELS = {"DE:310": "city:start", "DE:311": "city:end"}
MAX_ARCHIVE_BYTES = 2 * 1024**3
MAX_MANIFEST_BYTES = 32 * 1024**2
MAX_CROP_BYTES = 16 * 1024**2
MAX_MEMBERS = 20_000
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_VERIFIED_ARCHIVES: dict[tuple, str] = {}


class StudentIntakeError(ValueError):
    """A package identity, source record or crop failed intake validation."""


def _require(condition, message):
    if not condition:
        raise StudentIntakeError(message)


def _safe_member(value: str) -> str:
    _require(isinstance(value, str) and bool(value), "Missing ZIP member path")
    plain = value[:-1] if value.endswith("/") else value
    path = PurePosixPath(plain)
    _require(bool(plain) and not path.is_absolute() and "\\" not in plain
             and all(part not in {"", ".", ".."} for part in plain.split("/"))
             and ":" not in path.parts[0]
             and all(ord(char) >= 32 for char in plain), "Unsafe ZIP member path")
    return plain


def _digest(value, field):
    _require(isinstance(value, str) and SHA256.fullmatch(value), f"Invalid {field}")
    return value


def _archive_identity(path: Path, expected: str, expected_bytes=None):
    expected = _digest(expected, "archive SHA-256")
    _require(path.is_file() and not path.is_symlink(), "Learning archive is not a regular file")
    info = path.stat()
    _require(0 < info.st_size <= MAX_ARCHIVE_BYTES, "Learning archive exceeds byte limit")
    if expected_bytes is not None:
        _require(type(expected_bytes) is int and info.st_size == expected_bytes,
                 "Learning archive byte count differs from collection manifest")
    identity = (str(path.resolve()), info.st_dev, info.st_ino, info.st_size,
                info.st_mtime_ns, info.st_ctime_ns)
    if _VERIFIED_ARCHIVES.get(identity) != expected:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        _require(digest.hexdigest() == expected, "Learning archive SHA-256 mismatch")
        after = path.stat()
        _require((after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                 == (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns),
                 "Learning archive changed while hashing")
        _VERIFIED_ARCHIVES[identity] = expected


def _members(archive):
    infos = archive.infolist()
    _require(len(infos) <= MAX_MEMBERS, "Learning archive has too many members")
    result = {}
    for member in infos:
        _safe_member(member.filename)
        mode = member.external_attr >> 16
        _require(not stat.S_ISLNK(mode) and stat.S_IFMT(mode) in {0, stat.S_IFREG, stat.S_IFDIR}
                 and not member.flag_bits & 1, "Unsupported ZIP member type")
        _require(member.filename not in result, "Duplicate ZIP member path")
        result[member.filename] = member
    return result


def _read_member(archive, members, member_path, limit):
    _safe_member(member_path)
    member = members.get(member_path)
    _require(member is not None and not member.is_dir(), "Referenced ZIP member is missing")
    _require(0 < member.file_size <= limit, "ZIP member exceeds byte limit")
    with archive.open(member) as stream:
        data = stream.read(limit + 1)
    _require(len(data) == member.file_size and len(data) <= limit, "ZIP member byte count mismatch")
    return data


def _json_bytes(data):
    try:
        return json.loads(data)
    except (UnicodeError, ValueError) as error:
        raise StudentIntakeError("Learning manifest is not valid JSON") from error


def _source_labels(tags):
    return sorted({tag["value"] for tag in tags if isinstance(tag, dict)
                   and tag.get("key") == "osm|traffic_sign"
                   and isinstance(tag.get("value"), str) and tag["value"].strip()})


def _town_proposal(codes, fallback=None):
    # Generic yes and accompanying non-class tags do not erase a specific code.
    specific = {value for value in codes if value not in {"yes", "sign", "traffic_sign"}}
    if len(specific) == 1 and next(iter(specific)) in TOWN_LABELS:
        return TOWN_LABELS[next(iter(specific))]
    if specific:
        return None
    return fallback if fallback in TOWN_LABELS.values() else None


def _record_tags(row):
    target = row.get("source_target_annotation_id")
    for annotation in row.get("live_annotations") or []:
        if target and str(annotation.get("id")) == str(target):
            return annotation.get("semantics") or []
    return [{"key": "osm|traffic_sign", "value": code}
            for code in row.get("source_target_original_codes") or [] if isinstance(code, str)]


def read_student_archives(collection_manifest: Path, archive_dir: Path, *,
                          dataset_revision: str) -> list[dict]:
    """Return source candidates from checksummed learning archives, with no approval.

    Stock package flags and suggested classes are not human review evidence.
    Actual reviewed course exports must enter through their separate verified
    importer; this API never upgrades a source candidate to a reviewed sample.
    """
    _require(isinstance(dataset_revision, str) and re.fullmatch("[a-f0-9]{40}", dataset_revision),
             "An immutable Hugging Face dataset revision is required")
    collection_manifest, archive_dir = Path(collection_manifest), Path(archive_dir).resolve()
    _require(collection_manifest.stat().st_size <= MAX_MANIFEST_BYTES, "Collection manifest exceeds byte limit")
    collection = _json_bytes(collection_manifest.read_bytes())
    _require(isinstance(collection, dict) and collection.get("schema_version") == COLLECTION_SCHEMA
             and collection.get("repository_id") == DATASET_ID, "Unexpected student collection identity")
    packages = collection.get("packages")
    _require(isinstance(packages, list), "Collection learning packages are missing")
    excluded = set(collection.get("excluded_from_learning", []))
    excluded.update(entry["path"] for entry in collection.get("review_supplements", []))
    records, seen_packages, seen_samples = [], set(), set()
    for package in packages:
        package_path = _safe_member(package["path"])
        name = PurePosixPath(package_path).name
        if package_path in excluded or name not in PACKAGE_SCHEMAS:
            continue
        _require(name not in seen_packages, "Learning package is listed twice")
        seen_packages.add(name)
        path = archive_dir / name
        if not path.exists():
            path = archive_dir / package_path
        _require(path.resolve().is_relative_to(archive_dir), "Archive path escapes its directory")
        expected = package["sha256"]
        _archive_identity(path, expected, package.get("bytes"))
        root = _safe_member(package["archive_root"])
        with zipfile.ZipFile(path) as archive:
            members = _members(archive)
            payload = _json_bytes(_read_member(archive, members, root + "/manifest.json", MAX_MANIFEST_BYTES))
            _require(payload.get("schema_version") == PACKAGE_SCHEMAS[name], "Unexpected learning package schema")
            base = name == "panoramax-studenten-2026-10-19.zip"
            rows = payload.get("crops" if base else "records")
            _require(isinstance(rows, list) and len(rows) == package.get("crops"),
                     "Learning crop count differs from collection manifest")
            items = {item["picture_id"]: item for item in payload.get("items", [])}
            metadata_cache = {}
            for row in rows:
                sample = row.get("sample_id") or row.get("candidate_id")
                _require(isinstance(sample, str) and bool(sample) and len(sample) <= 512
                         and not any(char in sample for char in "/\\\0\r\n"), "Invalid student crop identity")
                _require(sample not in seen_samples, "Duplicate student sample identity")
                seen_samples.add(sample)
                crop_path = _safe_member(row["crop_path"])
                _require(crop_path.startswith("inbox/classifier/") and crop_path.endswith(".png"),
                         "Student crop is outside the candidate classifier tree")
                member_path = root + "/" + crop_path
                _require(member_path in members and 0 < members[member_path].file_size <= MAX_CROP_BYTES,
                         "Student crop member is missing or exceeds byte limit")
                crop_sha = _digest(row.get("crop_sha256"), "crop SHA-256")
                picture = row.get("picture_id") or row.get("image_id")
                item = items.get(picture, {})
                tags = row.get("osm_tags", []) if base else _record_tags(row)
                if base and item.get("metadata_sha256") and item.get("bundle_path"):
                    if picture not in metadata_cache:
                        data = _read_member(archive, members, root + "/" + _safe_member(item["bundle_path"])
                                            + "/metadata.json", MAX_MANIFEST_BYTES)
                        _require(hashlib.sha256(data).hexdigest() == item["metadata_sha256"],
                                 "Source annotation metadata SHA-256 mismatch")
                        metadata_cache[picture] = _json_bytes(data)
                    annotations = metadata_cache[picture].get("original_item", {}).get("properties", {}).get("annotations", [])
                    original = next((a for a in annotations if str(a.get("id")) == str(row.get("annotation_id"))), None)
                    if original is not None:
                        tags = original.get("semantics", [])
                _require(isinstance(tags, list), "Source annotation tags must be a list")
                codes = _source_labels(tags)
                proposal_codes = [row["visible_class_proposal"]] if row.get("visible_class_proposal") else []
                proposed = _town_proposal(codes, row.get("suggested_label")) if base else _town_proposal(
                    proposal_codes, row.get("proposed_model_label"))
                sequence = row.get("sequence_id") or item.get("sequence_id")
                records.append({
                    "sample_id": sample, "source_kind": "hf_student", "dataset_id": DATASET_ID,
                    "dataset_revision": dataset_revision, "revision": dataset_revision,
                    "archive_name": name, "archive_path": str(path.resolve()),
                    "archive_sha256": expected, "archive_bytes": path.stat().st_size,
                    "member_path": member_path, "crop_sha256": crop_sha,
                    "picture_id": picture,
                    "annotation_id": row.get("annotation_id") or row.get("source_target_annotation_id"),
                    "sequence_id": sequence,
                    "group_id": row.get("conservative_split_group_id") or row.get("group_id")
                                or ("sequence-" + sequence if sequence else None),
                    "source_url": row.get("source_item_url") or row.get("source_url") or item.get("source_url"),
                    "license": row.get("license") or item.get("license"),
                    "author": row.get("author") or item.get("author"),
                    "raw_tags": tags, "source_annotation_labels": codes, "proposed_label": proposed,
                    "label_origin": "source_annotation" if base else "student_visual_proposal",
                    "review_status": "unreviewed", "human_approved": False, "eligible_for_training": False,
                    "candidate_record": row,
                })
    expected_total = collection.get("totals", {}).get("crops")
    if expected_total is not None:
        _require(len(records) == expected_total, "Learning collection crop total does not reconcile")
    return records


def read_crop_bytes(record: dict) -> bytes:
    """Read one native PNG unchanged and verify both package and crop identity."""
    path = Path(record["archive_path"])
    _archive_identity(path, record["archive_sha256"], record.get("archive_bytes"))
    member = _safe_member(record["member_path"])
    _require(member.endswith(".png") and "/inbox/classifier/" in member,
             "Student crop is outside the candidate classifier tree")
    with zipfile.ZipFile(path) as archive:
        data = _read_member(archive, _members(archive), member, MAX_CROP_BYTES)
    _require(data.startswith(b"\x89PNG\r\n\x1a\n"), "Student crop is not a PNG")
    _require(hashlib.sha256(data).hexdigest() == _digest(record["crop_sha256"], "crop SHA-256"),
             "Student crop SHA-256 mismatch")
    return data
