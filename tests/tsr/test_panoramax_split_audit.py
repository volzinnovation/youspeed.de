import hashlib
import json
import stat
import struct
import subprocess
import sys
import warnings
import zipfile
from pathlib import Path

import pytest

from scripts.tsr.audit_panoramax_split import (
    PanoramaxSplitAuditError,
    audit_archives,
    audit_split,
    derive_source_image_id,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "tsr" / "audit_panoramax_split.py"
SOURCE_A = "DE_11111111-1111-4111-8111-111111111111"
SOURCE_B = "DE_22222222-2222-4222-8222-222222222222"
SOURCE_C = "FR_33333333-3333-4333-8333-333333333333"


def jpeg(payload: bytes) -> bytes:
    return b"\xff\xd8\xff\xe0" + payload + b"\xff\xd9"


def write_archive(
    path: Path,
    entries: list[tuple[str, bytes]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> Path:
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for member_path, data in entries:
            archive.writestr(member_path, data)
    return path


def make_happy_archives(tmp_path: Path) -> tuple[Path, Path]:
    shared_bytes = jpeg(b"same-image")
    train = write_archive(
        tmp_path / "train.zip",
        [
            (f"train/speed_30/{SOURCE_A}0.jpg", shared_bytes),
            (f"train/speed_50/{SOURCE_B}0.jpg", jpeg(b"train-only")),
        ],
    )
    validation = write_archive(
        tmp_path / "val.zip",
        [
            (f"val/speed_30/{SOURCE_A}1.jpg", shared_bytes),
            (f"val/give_way/{SOURCE_C}0.jpg", jpeg(b"validation-only")),
        ],
    )
    return train, validation


def set_encrypted_flag(path: Path, flag: int = 0x1) -> None:
    payload = bytearray(path.read_bytes())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        cursor = 0
        while True:
            cursor = payload.find(signature, cursor)
            if cursor < 0:
                break
            flags = struct.unpack_from("<H", payload, cursor + flag_offset)[0]
            struct.pack_into("<H", payload, cursor + flag_offset, flags | flag)
            cursor += len(signature)
    path.write_bytes(payload)


def test_happy_path_reports_counts_coverage_and_overlaps(tmp_path: Path) -> None:
    train, validation = make_happy_archives(tmp_path)

    report = audit_archives(
        train,
        validation,
        include_details=True,
        expectations={
            "train_images": 2,
            "validation_images": 2,
            "source_image_id_overlap": 1,
            "exact_validation_images_in_train": 1,
        },
    )

    assert report["audit_completed"] is True
    assert report["expectations_passed"] is True
    assert report["leakage_free"] is False
    assert report["splits"]["train"]["image_count"] == 2
    assert report["splits"]["validation"]["image_count"] == 2
    assert report["splits"]["train"]["classes"] == {
        "speed_30": 1,
        "speed_50": 1,
    }
    assert report["class_coverage"] == {
        "shared": ["speed_30"],
        "train_only": ["speed_50"],
        "validation_only": ["give_way"],
    }
    assert report["overlap"]["source_image_id_count"] == 1
    assert report["overlap"]["source_image_ids"] == [SOURCE_A.removeprefix("DE_")]
    assert report["overlap"]["exact_validation_image_count"] == 1
    assert report["overlap"]["exact_sha256_count"] == 1


def test_source_id_uses_legacy_de_prefix_and_crop_discriminator_rule() -> None:
    assert derive_source_image_id(f"{SOURCE_A}f.jpg") == SOURCE_A.removeprefix("DE_")
    assert derive_source_image_id(f"{SOURCE_C}f.jpg") == SOURCE_C
    assert (
        derive_source_image_id(
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcde0.jpg"
        )
        == "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcde"
    )


def test_cross_class_exact_duplicate_is_reported(tmp_path: Path) -> None:
    same_bytes = jpeg(b"label-conflict")
    train = write_archive(
        tmp_path / "train.zip",
        [(f"train/speed_30/{SOURCE_A}0.jpg", same_bytes)],
    )
    validation = write_archive(
        tmp_path / "val.zip",
        [(f"val/speed_50/{SOURCE_B}0.jpg", same_bytes)],
    )

    report = audit_archives(train, validation, include_details=True)

    assert report["overlap"]["source_image_id_count"] == 0
    assert report["overlap"]["exact_validation_image_count"] == 1
    assert report["overlap"]["cross_class_exact_sha256_count"] == 1
    assert report["overlap"]["cross_class_exact_validation_image_count"] == 1
    group = report["overlap"]["exact_duplicate_groups"][0]
    assert group["cross_class"] is True
    assert group["train"][0]["class_name"] == "speed_30"
    assert group["validation"][0]["class_name"] == "speed_50"


def test_duplicate_source_ids_are_grouped_not_rejected(tmp_path: Path) -> None:
    archive = write_archive(
        tmp_path / "train.zip",
        [
            (f"train/bad:windows/{SOURCE_A}0.jpg", jpeg(b"first-crop")),
            (f"train/bad:windows/{SOURCE_A}a.jpg", jpeg(b"second-crop")),
        ],
    )

    split = audit_split(archive, "train")

    assert len(split.records) == 2
    assert {record.source_image_id for record in split.records} == {
        SOURCE_A.removeprefix("DE_")
    }


def test_shared_digest_and_validation_member_counts_are_distinct(
    tmp_path: Path,
) -> None:
    same_bytes = jpeg(b"one-digest-three-members")
    train = write_archive(
        tmp_path / "train.zip",
        [(f"train/speed_30/{SOURCE_A}0.jpg", same_bytes)],
    )
    validation = write_archive(
        tmp_path / "val.zip",
        [
            (f"val/speed_30/{SOURCE_B}0.jpg", same_bytes),
            (f"val/speed_30/{SOURCE_C}0.jpg", same_bytes),
        ],
    )

    report = audit_archives(train, validation)

    assert report["overlap"]["exact_sha256_count"] == 1
    assert report["overlap"]["exact_validation_image_count"] == 2


@pytest.mark.parametrize(
    "member_path",
    [
        "../escape.jpg",
        "/train/speed_30/image.jpg",
        "//server/share/image.jpg",
        "C:/train/speed_30/image.jpg",
        "train/../speed_30/image.jpg",
        "train\\speed_30\\image.jpg",
    ],
)
def test_unsafe_member_path_is_rejected(tmp_path: Path, member_path: str) -> None:
    archive = write_archive(tmp_path / "train.zip", [(member_path, jpeg(b"x"))])

    with pytest.raises(PanoramaxSplitAuditError, match="path|rooted"):
        audit_split(archive, "train")


def test_duplicate_member_path_is_rejected(tmp_path: Path) -> None:
    archive_path = tmp_path / "train.zip"
    member_path = f"train/speed_30/{SOURCE_A}0.jpg"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(member_path, jpeg(b"first"))
            archive.writestr(member_path, jpeg(b"second"))

    with pytest.raises(PanoramaxSplitAuditError, match="duplicate ZIP member"):
        audit_split(archive_path, "train")


def test_unicode_canonical_duplicate_member_path_is_rejected(tmp_path: Path) -> None:
    archive_path = tmp_path / "train.zip"
    composed = f"train/caf\N{LATIN SMALL LETTER E WITH ACUTE}/{SOURCE_A}0.jpg"
    decomposed = f"train/cafe\N{COMBINING ACUTE ACCENT}/{SOURCE_A}0.jpg"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(composed, jpeg(b"first"))
        archive.writestr(decomposed, jpeg(b"second"))

    with pytest.raises(PanoramaxSplitAuditError, match="duplicate ZIP member"):
        audit_split(archive_path, "train")


def test_file_directory_path_collision_is_rejected(tmp_path: Path) -> None:
    archive_path = tmp_path / "train.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("train/speed_30/", b"")
        archive.writestr("train/speed_30", b"")

    with pytest.raises(PanoramaxSplitAuditError, match="duplicate ZIP member"):
        audit_split(archive_path, "train")


def test_symlink_member_is_rejected(tmp_path: Path) -> None:
    archive_path = tmp_path / "train.zip"
    info = zipfile.ZipInfo(f"train/speed_30/{SOURCE_A}0.jpg")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(info, b"target.jpg")

    with pytest.raises(PanoramaxSplitAuditError, match="symbolic-link"):
        audit_split(archive_path, "train")


@pytest.mark.parametrize(
    ("member_name", "mode"),
    [
        ("train/speed_30/", stat.S_IFREG | 0o644),
        (f"train/speed_30/{SOURCE_A}0.jpg", stat.S_IFDIR | 0o755),
    ],
)
def test_declared_member_type_must_match_path_shape(
    tmp_path: Path, member_name: str, mode: int
) -> None:
    archive_path = tmp_path / "train.zip"
    info = zipfile.ZipInfo(member_name)
    info.create_system = 3
    info.external_attr = mode << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(info, b"" if member_name.endswith("/") else jpeg(b"x"))

    with pytest.raises(PanoramaxSplitAuditError, match="unsupported ZIP member type"):
        audit_split(archive_path, "train")


@pytest.mark.parametrize("flag", [0x1, 0x40])
def test_encrypted_member_flag_is_rejected_before_read(
    tmp_path: Path, flag: int
) -> None:
    archive_path = write_archive(
        tmp_path / "train.zip",
        [(f"train/speed_30/{SOURCE_A}0.jpg", jpeg(b"encrypted-flag"))],
        compression=zipfile.ZIP_STORED,
    )
    set_encrypted_flag(archive_path, flag)

    with pytest.raises(PanoramaxSplitAuditError, match="encrypted ZIP member"):
        audit_split(archive_path, "train")


def test_member_and_total_uncompressed_limits_are_enforced(tmp_path: Path) -> None:
    archive_path = write_archive(
        tmp_path / "train.zip",
        [
            (f"train/speed_30/{SOURCE_A}0.jpg", jpeg(b"a" * 32)),
            (f"train/speed_30/{SOURCE_B}0.jpg", jpeg(b"b" * 32)),
        ],
    )

    with pytest.raises(PanoramaxSplitAuditError, match="member exceeds limit"):
        audit_split(archive_path, "train", max_member_bytes=16)
    with pytest.raises(PanoramaxSplitAuditError, match="total exceeds limit"):
        audit_split(archive_path, "train", max_total_bytes=64)


def test_archive_and_expansion_limits_are_enforced(tmp_path: Path) -> None:
    archive_path = write_archive(
        tmp_path / "train.zip",
        [(f"train/speed_30/{SOURCE_A}0.jpg", jpeg(b"0" * 4096))],
    )

    with pytest.raises(PanoramaxSplitAuditError, match="archive exceeds byte limit"):
        audit_split(archive_path, "train", max_archive_bytes=32)
    with pytest.raises(PanoramaxSplitAuditError, match="expansion ratio"):
        audit_split(archive_path, "train", max_expansion_ratio=1.0)


def test_unsupported_compression_is_rejected(tmp_path: Path) -> None:
    archive_path = write_archive(
        tmp_path / "train.zip",
        [(f"train/speed_30/{SOURCE_A}0.jpg", jpeg(b"bzip2"))],
        compression=zipfile.ZIP_BZIP2,
    )

    with pytest.raises(PanoramaxSplitAuditError, match="unsupported ZIP compression"):
        audit_split(archive_path, "train")


def test_wrong_expected_hash_stops_before_zip_parsing(tmp_path: Path) -> None:
    not_a_zip = tmp_path / "train.zip"
    not_a_zip.write_bytes(b"not a zip")
    actual = hashlib.sha256(not_a_zip.read_bytes()).hexdigest()
    wrong = "0" * 64 if actual != "0" * 64 else "1" * 64

    with pytest.raises(PanoramaxSplitAuditError, match="SHA-256 expectation mismatch"):
        audit_split(not_a_zip, "train", expected_archive_sha256=wrong)


@pytest.mark.parametrize(
    ("member_path", "message"),
    [
        ("train/speed_30/readme.txt", "unsupported image extension"),
        ("train/speed_30/nested/image0.jpg", "images must use"),
    ],
)
def test_non_image_or_malformed_layout_is_rejected(
    tmp_path: Path, member_path: str, message: str
) -> None:
    archive = write_archive(tmp_path / "train.zip", [(member_path, jpeg(b"x"))])

    with pytest.raises(PanoramaxSplitAuditError, match=message):
        audit_split(archive, "train")


def test_image_extension_must_match_file_signature(tmp_path: Path) -> None:
    archive = write_archive(
        tmp_path / "train.zip",
        [(f"train/speed_30/{SOURCE_A}0.jpg", b"plain text")],
    )

    with pytest.raises(PanoramaxSplitAuditError, match="image bytes"):
        audit_split(archive, "train")


def test_cli_json_is_deterministic_and_assertions_control_exit(
    tmp_path: Path,
) -> None:
    train, validation = make_happy_archives(tmp_path)
    command = [
        sys.executable,
        str(SCRIPT),
        "--train",
        str(train),
        "--val",
        str(validation),
        "--expect-train-images",
        "2",
        "--expect-val-images",
        "2",
        "--expect-train-bytes",
        str(train.stat().st_size),
        "--expect-val-bytes",
        str(validation.stat().st_size),
        "--expect-source-overlap",
        "1",
        "--expect-exact-val-in-train",
        "1",
        "--expect-train-sha256",
        hashlib.sha256(train.read_bytes()).hexdigest(),
        "--expect-val-sha256",
        hashlib.sha256(validation.read_bytes()).hexdigest(),
    ]

    first = subprocess.run(command, check=False, capture_output=True, text=True)
    second = subprocess.run(command, check=False, capture_output=True, text=True)

    assert first.returncode == 0
    assert first.stderr == ""
    assert first.stdout == second.stdout
    parsed = json.loads(first.stdout)
    assert parsed["audit_completed"] is True
    assert parsed["expectations_passed"] is True
    assert parsed["leakage_free"] is False
    assert parsed["overlap"]["details_included"] is False
    assert "source_image_ids" not in parsed["overlap"]
    assert "exact_duplicate_groups" not in parsed["overlap"]
    assert all(assertion["passed"] for assertion in parsed["assertions"])

    detailed = subprocess.run(
        command + ["--include-details"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert detailed.returncode == 0
    detailed_report = json.loads(detailed.stdout)
    assert detailed_report["overlap"]["details_included"] is True
    assert detailed_report["overlap"]["source_image_ids"]
    assert detailed_report["overlap"]["exact_duplicate_groups"]
    repeated_detailed = subprocess.run(
        command + ["--include-details"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert detailed.stdout == repeated_detailed.stdout

    mismatch_command = command.copy()
    mismatch_command[mismatch_command.index("--expect-exact-val-in-train") + 1] = "2"
    mismatch = subprocess.run(
        mismatch_command, check=False, capture_output=True, text=True
    )
    assert mismatch.returncode == 1
    assert json.loads(mismatch.stdout)["expectations_passed"] is False


def test_cli_rejects_malformed_expected_sha256(tmp_path: Path) -> None:
    train, validation = make_happy_archives(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--train",
            str(train),
            "--val",
            str(validation),
            "--expect-train-sha256",
            "A" * 64,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "64 lowercase hexadecimal characters" in result.stderr
