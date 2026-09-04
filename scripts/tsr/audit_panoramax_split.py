#!/usr/bin/env python3
"""Audit leakage in Panoramax classified-road-sign ZIP splits safely.

The published German split audit uses the filename stem with an optional
leading ``DE_`` removed and the final crop discriminator removed.  This tool
reproduces that legacy source-image-ID convention exactly so its result can be
checked against the pinned counts.

This tool treats ZIPs as untrusted containers.  It never extracts members and
never decodes images.  Archive and member bytes are SHA-256 hashed in chunks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import struct
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Mapping, Sequence


SCHEMA_VERSION = "youspeed-panoramax-split-audit-v1"
DEFAULT_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_CENTRAL_DIRECTORY_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_MEMBER_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_MEMBERS = 100_000
DEFAULT_MAX_MEMBER_NAME_BYTES = 4096
DEFAULT_MAX_EXPANSION_RATIO = 200.0
READ_CHUNK_BYTES = 1024 * 1024
MAX_EOCD_SEARCH_BYTES = 22 + 65_535
IMAGE_EXTENSIONS = frozenset({".jpeg", ".jpg", ".png", ".webp"})
SOURCE_STEM = re.compile(r"^(?:[A-Z]{2}_)?[A-Za-z0-9][A-Za-z0-9-]+[0-9a-f]$")
WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
EOCD = struct.Struct("<4s4H2LH")
EOCD_SIGNATURE = b"PK\x05\x06"
ALLOWED_COMPRESSION_METHODS = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})


class PanoramaxSplitAuditError(ValueError):
    """Raised when an archive is unsafe or does not match the dataset layout."""


@dataclass(frozen=True)
class ImageRecord:
    member_path: str
    class_name: str
    source_image_id: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class SplitAudit:
    split: str
    input_path: str
    archive_sha256: str
    archive_size_bytes: int
    records: tuple[ImageRecord, ...]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PanoramaxSplitAuditError(message)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if not 0 < parsed < float("inf"):
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return parsed


def _expected_sha256(value: str) -> str:
    if SHA256.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("must be 64 lowercase hexadecimal characters")
    return value


def _sha256_stream(stream: BinaryIO, *, max_bytes: int) -> tuple[str, int, bytes]:
    digest = hashlib.sha256()
    size = 0
    prefix = bytearray()
    while True:
        read_size = min(READ_CHUNK_BYTES, max_bytes - size + 1)
        chunk = stream.read(read_size)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
        _require(size <= max_bytes, f"stream exceeds byte limit {max_bytes}")
        if len(prefix) < 16:
            prefix.extend(chunk[: 16 - len(prefix)])
    return digest.hexdigest(), size, bytes(prefix)


def _archive_sha256(stream: BinaryIO, *, max_bytes: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while True:
        read_size = min(READ_CHUNK_BYTES, max_bytes - size + 1)
        chunk = stream.read(read_size)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
        _require(size <= max_bytes, f"ZIP archive exceeds byte limit {max_bytes}")
    return digest.hexdigest(), size


def _preflight_central_directory(
    stream: BinaryIO,
    *,
    archive_size: int,
    max_members: int,
    max_central_directory_bytes: int,
) -> int:
    """Bound central-directory allocation before ``ZipFile`` parses it."""

    _require(archive_size >= EOCD.size, "ZIP archive is too small")
    tail_size = min(archive_size, MAX_EOCD_SEARCH_BYTES)
    stream.seek(archive_size - tail_size)
    tail = stream.read(tail_size)
    search_end = len(tail)
    eocd_offset = -1
    eocd_values: tuple[Any, ...] | None = None
    while search_end > 0:
        candidate = tail.rfind(EOCD_SIGNATURE, 0, search_end)
        if candidate < 0:
            break
        if candidate + EOCD.size <= len(tail):
            values = EOCD.unpack_from(tail, candidate)
            comment_length = values[-1]
            if candidate + EOCD.size + comment_length == len(tail):
                eocd_offset = archive_size - tail_size + candidate
                eocd_values = values
                break
        search_end = candidate
    _require(eocd_values is not None, "missing or malformed ZIP end record")
    (
        _,
        disk_number,
        central_disk,
        disk_entries,
        total_entries,
        central_size,
        central_offset,
        _,
    ) = eocd_values
    _require(disk_number == 0 and central_disk == 0, "multi-disk ZIP is not allowed")
    _require(disk_entries == total_entries, "multi-disk ZIP entry counts differ")
    _require(
        total_entries != 0xFFFF
        and central_size != 0xFFFFFFFF
        and central_offset != 0xFFFFFFFF,
        "ZIP64 archives are not supported by this audit",
    )
    _require(
        total_entries <= max_members,
        f"ZIP member count exceeds limit {max_members}: {total_entries}",
    )
    _require(
        central_size <= max_central_directory_bytes,
        "ZIP central directory exceeds byte limit "
        f"{max_central_directory_bytes}: {central_size}",
    )
    _require(
        central_offset + central_size == eocd_offset,
        "ZIP central-directory bounds are inconsistent",
    )
    stream.seek(0)
    return total_entries


def derive_source_image_id(filename: str) -> str:
    """Return the legacy published source-image ID for one crop filename."""

    suffix = Path(filename).suffix.lower()
    _require(suffix in IMAGE_EXTENSIONS, f"unsupported image extension: {filename}")
    stem = filename[: -len(Path(filename).suffix)]
    _require(
        SOURCE_STEM.fullmatch(stem) is not None,
        f"image filename does not follow the Panoramax crop convention: {filename}",
    )
    # Preserve the published audit convention: the German-origin marker is not
    # part of the source ID and the final character is the crop discriminator.
    source_image_id = stem.removeprefix("DE_")[:-1]
    _require(source_image_id, f"missing source-image ID: {filename}")
    return source_image_id


def _safe_member_name(
    name: str, *, max_member_name_bytes: int
) -> tuple[str, tuple[str, ...], bool]:
    _require(name != "", "ZIP member has an empty path")
    _require(
        len(name.encode("utf-8")) <= max_member_name_bytes,
        f"ZIP member path exceeds byte limit {max_member_name_bytes}",
    )
    _require("\x00" not in name, f"ZIP member path contains NUL: {name!r}")
    _require("\\" not in name, f"ZIP member path uses a backslash: {name!r}")
    _require(not name.startswith("/"), f"ZIP member path is absolute: {name!r}")
    _require(
        WINDOWS_DRIVE.match(name) is None,
        f"ZIP member path has a Windows drive prefix: {name!r}",
    )
    normalized = unicodedata.normalize("NFC", name)
    is_directory = normalized.endswith("/")
    components = normalized[:-1].split("/") if is_directory else normalized.split("/")
    _require(
        components and all(part not in {"", ".", ".."} for part in components),
        f"ZIP member path is not normalized: {name!r}",
    )
    _require(
        all(
            not any(ord(character) < 32 or ord(character) == 127 for character in part)
            for part in components
        ),
        f"ZIP member path contains a control character: {name!r}",
    )
    canonical = "/".join(components) + ("/" if is_directory else "")
    return canonical, tuple(components), is_directory


def _reject_unsafe_type(info: zipfile.ZipInfo, is_directory: bool) -> None:
    _require(
        info.flag_bits & (0x1 | 0x40) == 0,
        f"encrypted ZIP member is not allowed: {info.filename!r}",
    )
    _require(
        info.compress_type in ALLOWED_COMPRESSION_METHODS,
        f"unsupported ZIP compression method for {info.filename!r}: "
        f"{info.compress_type}",
    )
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(unix_mode)
    _require(
        not stat.S_ISLNK(unix_mode),
        f"symbolic-link ZIP member is not allowed: {info.filename!r}",
    )
    if file_type:
        allowed_type = stat.S_IFDIR if is_directory else stat.S_IFREG
        _require(
            file_type == allowed_type,
            f"unsupported ZIP member type: {info.filename!r}",
        )


def _validate_image_magic(extension: str, prefix: bytes, member_path: str) -> None:
    if extension in {".jpg", ".jpeg"}:
        valid = prefix.startswith(b"\xff\xd8\xff")
    elif extension == ".png":
        valid = prefix.startswith(b"\x89PNG\r\n\x1a\n")
    else:
        valid = len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP"
    _require(valid, f"image bytes do not match the extension: {member_path!r}")


def _validate_layout(
    split: str,
    components: tuple[str, ...],
    is_directory: bool,
    member_path: str,
) -> tuple[str, str] | None:
    _require(
        components[0] == split,
        f"ZIP member must be rooted at {split!r}: {member_path!r}",
    )
    if is_directory:
        _require(
            len(components) in {1, 2},
            f"unexpected directory layout: {member_path!r}",
        )
        return None
    _require(
        len(components) == 3,
        f"images must use {split}/<class>/<filename>: {member_path!r}",
    )
    class_name, filename = components[1], components[2]
    _require(class_name.strip() == class_name, f"invalid class name: {class_name!r}")
    _require(class_name != "", f"missing class name: {member_path!r}")
    derive_source_image_id(filename)
    return class_name, filename


def audit_split(
    path: Path | str,
    split: str,
    *,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_central_directory_bytes: int = DEFAULT_MAX_CENTRAL_DIRECTORY_BYTES,
    max_member_name_bytes: int = DEFAULT_MAX_MEMBER_NAME_BYTES,
    max_expansion_ratio: float = DEFAULT_MAX_EXPANSION_RATIO,
    expected_archive_bytes: int | None = None,
    expected_archive_sha256: str | None = None,
) -> SplitAudit:
    """Validate and audit one ZIP without extracting any member."""

    _require(split in {"train", "val"}, f"unsupported split: {split!r}")
    _require(max_member_bytes > 0, "max_member_bytes must be positive")
    _require(max_total_bytes > 0, "max_total_bytes must be positive")
    _require(max_members > 0, "max_members must be positive")
    _require(max_archive_bytes > 0, "max_archive_bytes must be positive")
    _require(
        max_central_directory_bytes > 0,
        "max_central_directory_bytes must be positive",
    )
    _require(max_member_name_bytes > 0, "max_member_name_bytes must be positive")
    _require(max_expansion_ratio > 0, "max_expansion_ratio must be positive")
    if expected_archive_bytes is not None:
        _require(
            isinstance(expected_archive_bytes, int)
            and not isinstance(expected_archive_bytes, bool)
            and expected_archive_bytes >= 0,
            "expected_archive_bytes must be a non-negative integer",
        )
    if expected_archive_sha256 is not None:
        _require(
            isinstance(expected_archive_sha256, str)
            and SHA256.fullmatch(expected_archive_sha256) is not None,
            "expected_archive_sha256 must be 64 lowercase hexadecimal characters",
        )
    input_path = Path(path).expanduser()
    _require(input_path.is_file(), f"missing ZIP archive: {input_path}")

    try:
        stat_size = input_path.stat().st_size
        _require(
            stat_size <= max_archive_bytes,
            f"ZIP archive exceeds byte limit {max_archive_bytes}: {stat_size}",
        )
        if expected_archive_bytes is not None:
            _require(
                stat_size == expected_archive_bytes,
                f"{split} archive byte-size expectation mismatch: "
                f"expected {expected_archive_bytes}, got {stat_size}",
            )
        with input_path.open("rb") as archive_stream:
            archive_digest, archive_size = _archive_sha256(
                archive_stream, max_bytes=max_archive_bytes
            )
            _require(
                archive_size == stat_size,
                "ZIP archive size changed while it was being audited",
            )
            if expected_archive_sha256 is not None:
                _require(
                    archive_digest == expected_archive_sha256,
                    f"{split} archive SHA-256 expectation mismatch: "
                    f"expected {expected_archive_sha256}, got {archive_digest}",
                )
            declared_member_count = _preflight_central_directory(
                archive_stream,
                archive_size=archive_size,
                max_members=max_members,
                max_central_directory_bytes=max_central_directory_bytes,
            )
            archive_stream.seek(0)
            with zipfile.ZipFile(archive_stream) as archive:
                infos = archive.infolist()
                _require(infos, f"empty ZIP archive: {input_path}")
                _require(
                    len(infos) == declared_member_count,
                    "ZIP member count differs from the end record",
                )

                seen_paths: set[str] = set()
                image_members: list[tuple[str, str, str, zipfile.ZipInfo]] = []
                declared_total = 0
                for info in infos:
                    member_path, components, is_directory = _safe_member_name(
                        info.filename,
                        max_member_name_bytes=max_member_name_bytes,
                    )
                    duplicate_key = member_path.rstrip("/")
                    _require(
                        duplicate_key not in seen_paths,
                        f"duplicate ZIP member path: {member_path!r}",
                    )
                    seen_paths.add(duplicate_key)
                    _reject_unsafe_type(info, is_directory)
                    _require(
                        info.compress_size >= 0 and info.file_size >= 0,
                        f"ZIP member has a negative size: {member_path!r}",
                    )
                    if info.file_size:
                        expansion_ratio = info.file_size / max(info.compress_size, 1)
                        _require(
                            expansion_ratio <= max_expansion_ratio,
                            f"ZIP member expansion ratio exceeds limit "
                            f"{max_expansion_ratio:g}: {member_path!r}",
                        )
                    _require(
                        info.file_size <= max_member_bytes,
                        f"ZIP member exceeds limit {max_member_bytes}: {member_path!r}",
                    )
                    declared_total += info.file_size
                    _require(
                        declared_total <= max_total_bytes,
                        f"ZIP uncompressed total exceeds limit {max_total_bytes}",
                    )
                    layout = _validate_layout(
                        split, components, is_directory, member_path
                    )
                    if is_directory:
                        _require(
                            info.file_size == 0,
                            f"directory ZIP member has data: {member_path!r}",
                        )
                    elif layout is not None:
                        class_name, filename = layout
                        image_members.append((member_path, class_name, filename, info))

                _require(image_members, f"ZIP contains no images: {input_path}")
                records: list[ImageRecord] = []
                streamed_total = 0
                for member_path, class_name, filename, info in sorted(
                    image_members, key=lambda item: item[0]
                ):
                    with archive.open(info, "r") as member_stream:
                        member_digest, actual_size, prefix = _sha256_stream(
                            member_stream,
                            max_bytes=min(
                                max_member_bytes,
                                max_total_bytes - streamed_total,
                                info.file_size,
                            ),
                        )
                    _require(
                        actual_size == info.file_size,
                        f"ZIP member size mismatch: {member_path!r}",
                    )
                    _require(
                        actual_size <= max_member_bytes,
                        f"ZIP member exceeds limit while reading: {member_path!r}",
                    )
                    streamed_total += actual_size
                    _require(
                        streamed_total <= max_total_bytes,
                        f"ZIP data exceeds total limit while reading {member_path!r}",
                    )
                    _validate_image_magic(
                        Path(filename).suffix.lower(), prefix, member_path
                    )
                    records.append(
                        ImageRecord(
                            member_path=member_path,
                            class_name=class_name,
                            source_image_id=derive_source_image_id(filename),
                            sha256=member_digest,
                            size_bytes=actual_size,
                        )
                    )
    except PanoramaxSplitAuditError:
        raise
    except (
        EOFError,
        OSError,
        OverflowError,
        RuntimeError,
        NotImplementedError,
        ValueError,
        zipfile.BadZipFile,
    ) as error:
        raise PanoramaxSplitAuditError(
            f"cannot audit ZIP archive {input_path}: {error}"
        ) from error

    return SplitAudit(
        split=split,
        input_path=str(input_path),
        archive_sha256=archive_digest,
        archive_size_bytes=archive_size,
        records=tuple(records),
    )


def _split_report(audit: SplitAudit) -> dict[str, Any]:
    class_counts = Counter(record.class_name for record in audit.records)
    source_ids = {record.source_image_id for record in audit.records}
    image_hashes = {record.sha256 for record in audit.records}
    return {
        "archive_sha256": audit.archive_sha256,
        "archive_size_bytes": audit.archive_size_bytes,
        "class_count": len(class_counts),
        "classes": dict(sorted(class_counts.items())),
        "image_count": len(audit.records),
        "source_image_id_count": len(source_ids),
        "unique_image_sha256_count": len(image_hashes),
    }


def _hash_index(
    records: Iterable[ImageRecord],
) -> Mapping[str, tuple[ImageRecord, ...]]:
    mutable: dict[str, list[ImageRecord]] = defaultdict(list)
    for record in records:
        mutable[record.sha256].append(record)
    return {
        digest: tuple(sorted(items, key=lambda item: item.member_path))
        for digest, items in sorted(mutable.items())
    }


def _record_reference(record: ImageRecord) -> dict[str, Any]:
    return {
        "class_name": record.class_name,
        "member_path": record.member_path,
        "size_bytes": record.size_bytes,
        "source_image_id": record.source_image_id,
    }


def build_report(
    train: SplitAudit,
    validation: SplitAudit,
    *,
    expectations: Mapping[str, int | str | None] | None = None,
    limits: Mapping[str, int | float] | None = None,
    include_details: bool = False,
) -> dict[str, Any]:
    """Build the deterministic machine-readable cross-split report."""

    _require(train.split == "train", "train audit has the wrong split label")
    _require(validation.split == "val", "validation audit has the wrong split label")

    train_classes = {record.class_name for record in train.records}
    validation_classes = {record.class_name for record in validation.records}
    train_sources = {record.source_image_id for record in train.records}
    validation_sources = {record.source_image_id for record in validation.records}
    source_overlap = sorted(train_sources & validation_sources)

    train_hashes = _hash_index(train.records)
    validation_hashes = _hash_index(validation.records)
    shared_hashes = sorted(set(train_hashes) & set(validation_hashes))
    duplicate_groups: list[dict[str, Any]] = []
    exact_validation_image_count = 0
    cross_class_hash_count = 0
    cross_class_validation_image_count = 0
    for digest in shared_hashes:
        train_items = train_hashes[digest]
        validation_items = validation_hashes[digest]
        exact_validation_image_count += len(validation_items)
        train_item_classes = {item.class_name for item in train_items}
        validation_item_classes = {item.class_name for item in validation_items}
        cross_class = len(train_item_classes | validation_item_classes) > 1
        if cross_class:
            cross_class_hash_count += 1
            cross_class_validation_image_count += len(validation_items)
        if include_details:
            duplicate_groups.append(
                {
                    "cross_class": cross_class,
                    "sha256": digest,
                    "train": [_record_reference(item) for item in train_items],
                    "validation": [
                        _record_reference(item) for item in validation_items
                    ],
                }
            )

    actuals = {
        "exact_validation_images_in_train": exact_validation_image_count,
        "source_image_id_overlap": len(source_overlap),
        "train_archive_bytes": train.archive_size_bytes,
        "train_archive_sha256": train.archive_sha256,
        "train_images": len(train.records),
        "validation_archive_bytes": validation.archive_size_bytes,
        "validation_archive_sha256": validation.archive_sha256,
        "validation_images": len(validation.records),
    }
    assertion_results: list[dict[str, Any]] = []
    for name, expected in sorted((expectations or {}).items()):
        if expected is None:
            continue
        _require(name in actuals, f"unknown expectation: {name}")
        if name.endswith("_sha256"):
            _require(
                isinstance(expected, str) and SHA256.fullmatch(expected) is not None,
                f"{name} expectation must be 64 lowercase hexadecimal characters",
            )
        else:
            _require(
                isinstance(expected, int) and not isinstance(expected, bool),
                f"{name} expectation must be an integer",
            )
        assertion_results.append(
            {
                "actual": actuals[name],
                "expected": expected,
                "name": name,
                "passed": actuals[name] == expected,
            }
        )

    overlap_report: dict[str, Any] = {
        "cross_class_exact_sha256_count": cross_class_hash_count,
        "cross_class_exact_validation_image_count": cross_class_validation_image_count,
        "details_included": include_details,
        "exact_sha256_count": len(shared_hashes),
        "exact_validation_image_count": exact_validation_image_count,
        "source_image_id_count": len(source_overlap),
    }
    if include_details:
        overlap_report["exact_duplicate_groups"] = duplicate_groups
        overlap_report["source_image_ids"] = source_overlap

    expectations_passed = all(item["passed"] for item in assertion_results)
    leakage_free = len(source_overlap) == 0 and exact_validation_image_count == 0
    return {
        "assertions": assertion_results,
        "audit_completed": True,
        "class_coverage": {
            "shared": sorted(train_classes & validation_classes),
            "train_only": sorted(train_classes - validation_classes),
            "validation_only": sorted(validation_classes - train_classes),
        },
        "expectations_passed": expectations_passed,
        "leakage_free": leakage_free,
        "limits": dict(sorted((limits or {}).items())),
        "overlap": overlap_report,
        "schema": SCHEMA_VERSION,
        "splits": {
            "train": _split_report(train),
            "validation": _split_report(validation),
        },
    }


def audit_archives(
    train_path: Path | str,
    validation_path: Path | str,
    *,
    max_member_bytes: int = DEFAULT_MAX_MEMBER_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_members: int = DEFAULT_MAX_MEMBERS,
    max_archive_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    max_central_directory_bytes: int = DEFAULT_MAX_CENTRAL_DIRECTORY_BYTES,
    max_member_name_bytes: int = DEFAULT_MAX_MEMBER_NAME_BYTES,
    max_expansion_ratio: float = DEFAULT_MAX_EXPANSION_RATIO,
    expectations: Mapping[str, int | str | None] | None = None,
    include_details: bool = False,
) -> dict[str, Any]:
    expectation_values = expectations or {}
    limits = {
        "max_archive_bytes": max_archive_bytes,
        "max_central_directory_bytes": max_central_directory_bytes,
        "max_expansion_ratio": max_expansion_ratio,
        "max_member_bytes": max_member_bytes,
        "max_member_name_bytes": max_member_name_bytes,
        "max_members": max_members,
        "max_total_bytes_per_archive": max_total_bytes,
    }
    train = audit_split(
        train_path,
        "train",
        max_member_bytes=max_member_bytes,
        max_total_bytes=max_total_bytes,
        max_members=max_members,
        max_archive_bytes=max_archive_bytes,
        max_central_directory_bytes=max_central_directory_bytes,
        max_member_name_bytes=max_member_name_bytes,
        max_expansion_ratio=max_expansion_ratio,
        expected_archive_bytes=expectation_values.get("train_archive_bytes"),
        expected_archive_sha256=expectation_values.get("train_archive_sha256"),
    )
    validation = audit_split(
        validation_path,
        "val",
        max_member_bytes=max_member_bytes,
        max_total_bytes=max_total_bytes,
        max_members=max_members,
        max_archive_bytes=max_archive_bytes,
        max_central_directory_bytes=max_central_directory_bytes,
        max_member_name_bytes=max_member_name_bytes,
        max_expansion_ratio=max_expansion_ratio,
        expected_archive_bytes=expectation_values.get("validation_archive_bytes"),
        expected_archive_sha256=expectation_values.get("validation_archive_sha256"),
    )
    return build_report(
        train,
        validation,
        expectations=expectations,
        limits=limits,
        include_details=include_details,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Safely audit source-ID and exact-byte leakage between explicit "
            "Panoramax train.zip and val.zip archives."
        )
    )
    parser.add_argument("--train", required=True, type=Path, help="explicit train.zip")
    parser.add_argument("--val", required=True, type=Path, help="explicit val.zip")
    parser.add_argument(
        "--max-archive-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_ARCHIVE_BYTES,
    )
    parser.add_argument(
        "--max-central-directory-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_CENTRAL_DIRECTORY_BYTES,
    )
    parser.add_argument(
        "--max-member-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_MEMBER_BYTES,
    )
    parser.add_argument(
        "--max-total-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_TOTAL_BYTES,
        help="maximum uncompressed bytes in each archive",
    )
    parser.add_argument(
        "--max-members", type=_positive_int, default=DEFAULT_MAX_MEMBERS
    )
    parser.add_argument(
        "--max-member-name-bytes",
        type=_positive_int,
        default=DEFAULT_MAX_MEMBER_NAME_BYTES,
    )
    parser.add_argument(
        "--max-expansion-ratio",
        type=_positive_float,
        default=DEFAULT_MAX_EXPANSION_RATIO,
    )
    parser.add_argument("--expect-train-images", type=_non_negative_int)
    parser.add_argument("--expect-val-images", type=_non_negative_int)
    parser.add_argument("--expect-source-overlap", type=_non_negative_int)
    parser.add_argument("--expect-exact-val-in-train", type=_non_negative_int)
    parser.add_argument("--expect-train-bytes", type=_non_negative_int)
    parser.add_argument("--expect-val-bytes", type=_non_negative_int)
    parser.add_argument("--expect-train-sha256", type=_expected_sha256)
    parser.add_argument("--expect-val-sha256", type=_expected_sha256)
    parser.add_argument(
        "--include-details",
        action="store_true",
        help="include sorted source IDs and exact-duplicate member groups",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    expectations = {
        "exact_validation_images_in_train": args.expect_exact_val_in_train,
        "source_image_id_overlap": args.expect_source_overlap,
        "train_archive_bytes": args.expect_train_bytes,
        "train_archive_sha256": args.expect_train_sha256,
        "train_images": args.expect_train_images,
        "validation_archive_bytes": args.expect_val_bytes,
        "validation_archive_sha256": args.expect_val_sha256,
        "validation_images": args.expect_val_images,
    }
    try:
        report = audit_archives(
            args.train,
            args.val,
            max_member_bytes=args.max_member_bytes,
            max_total_bytes=args.max_total_bytes,
            max_members=args.max_members,
            max_archive_bytes=args.max_archive_bytes,
            max_central_directory_bytes=args.max_central_directory_bytes,
            max_member_name_bytes=args.max_member_name_bytes,
            max_expansion_ratio=args.max_expansion_ratio,
            expectations=expectations,
            include_details=args.include_details,
        )
    except PanoramaxSplitAuditError as error:
        print(
            json.dumps(
                {
                    "audit_completed": False,
                    "error": {"message": str(error), "type": "audit_error"},
                    "schema": SCHEMA_VERSION,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["expectations_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
