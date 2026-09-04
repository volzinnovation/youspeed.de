#!/usr/bin/env python3
"""Build leakage-safe TSR v2 train/calibration/holdout group splits.

Every sample that shares either a drive or a reviewed physical-sign identity is
placed in the same connected component before a split is assigned.  This is
stricter than grouping by capture alone: if the same physical sign is observed
on two drives, both drives (and every other sign on those drives) stay on one
side of the evaluation boundary.

The module is intentionally model-framework independent.  It consumes either
compact sample records or a frozen full-scene annotation v2 manifest, emits a
deterministic manifest, and fails closed when a record claims lineage from the
published Panoramax validation split, which is known to overlap its training
archive.  Full-scene conversion never invents near-duplicate clusters; that
audit remains pending until reviewed cluster IDs are supplied explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SPLITS = ("train", "calibration", "holdout")
PUBLISHED_PANORAMAX_VALIDATION_SPLIT = (
    "panoramax-classified-de-road-signs-b485694-validation"
)
PUBLISHED_PANORAMAX_VALIDATION_ALIASES = {
    "panoramax-de-validation-b485694",
}


class GroupSplitError(ValueError):
    """Raised when records cannot safely be partitioned."""


@dataclass(frozen=True)
class SplitSample:
    """Minimum grouping identity needed before augmentation or training."""

    sample_id: str
    drive_id: str
    physical_sign_ids: tuple[str, ...]
    near_duplicate_cluster_ids: tuple[str, ...]
    source_split_id: str | None = None
    source_artifact_ids: tuple[str, ...] = ()


class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def add(self, value: str) -> None:
        self._parent.setdefault(value, value)

    def find(self, value: str) -> str:
        parent = self._parent[value]
        if parent != value:
            self._parent[value] = self.find(parent)
        return self._parent[value]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        # Lexical roots make the graph deterministic regardless of input order.
        first, second = sorted((left_root, right_root))
        self._parent[second] = first


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GroupSplitError(message)


def _safe_id(value: Any, field: str) -> str:
    _require(
        isinstance(value, str) and SAFE_ID.fullmatch(value) is not None,
        f"{field} must be a safe lowercase identifier",
    )
    return value


def _string_tuple(value: Any, field: str, *, allow_empty: bool) -> tuple[str, ...]:
    _require(isinstance(value, list), f"{field} must be an array")
    if not allow_empty:
        _require(bool(value), f"{field} must not be empty")
    result = tuple(_safe_id(item, f"{field}[]") for item in value)
    _require(len(result) == len(set(result)), f"{field} contains duplicates")
    return tuple(sorted(result))


def sample_from_mapping(value: Mapping[str, Any], field: str = "sample") -> SplitSample:
    """Parse the stable grouping projection used by the CLI and tests."""

    _require(isinstance(value, Mapping), f"{field} must be an object")
    required = {
        "sample_id",
        "drive_id",
        "physical_sign_ids",
        "near_duplicate_cluster_ids",
        "source_split_id",
        "source_artifact_ids",
    }
    _require(set(value) == required, f"{field} fields must be exactly {sorted(required)}")
    source_split_id = value["source_split_id"]
    _require(
        source_split_id is None or isinstance(source_split_id, str),
        f"{field}.source_split_id must be a string or null",
    )
    return SplitSample(
        sample_id=_safe_id(value["sample_id"], f"{field}.sample_id"),
        drive_id=_safe_id(value["drive_id"], f"{field}.drive_id"),
        physical_sign_ids=_string_tuple(
            value["physical_sign_ids"],
            f"{field}.physical_sign_ids",
            allow_empty=True,
        ),
        near_duplicate_cluster_ids=_string_tuple(
            value["near_duplicate_cluster_ids"],
            f"{field}.near_duplicate_cluster_ids",
            allow_empty=True,
        ),
        source_split_id=(source_split_id.strip().lower() if source_split_id else None),
        source_artifact_ids=_string_tuple(
            value["source_artifact_ids"],
            f"{field}.source_artifact_ids",
            allow_empty=True,
        ),
    )


def samples_from_full_scene_manifest(value: Mapping[str, Any]) -> list[SplitSample]:
    """Project frozen full-scene annotations into leakage-group identities."""

    _require(isinstance(value, Mapping), "full-scene manifest must be an object")
    _require(value.get("schema_version") == 2, "unsupported full-scene schema")
    _require(value.get("taxonomy_version") == "tsr-semantic-v2", "unsupported taxonomy")
    _require(value.get("frozen") is True, "full-scene annotations must be frozen")
    frames = value.get("frames")
    _require(isinstance(frames, list) and frames, "full-scene frames must be non-empty")

    projected: list[SplitSample] = []
    for index, frame in enumerate(frames):
        prefix = f"frames[{index}]"
        _require(isinstance(frame, Mapping), f"{prefix} must be an object")
        objects = frame.get("objects")
        source = frame.get("source")
        _require(isinstance(objects, list), f"{prefix}.objects must be an array")
        _require(isinstance(source, Mapping), f"{prefix}.source must be an object")
        physical_sign_ids = tuple(
            sorted(
                {
                    _safe_id(item.get("physical_sign_id"), f"{prefix}.objects[].physical_sign_id")
                    for item in objects
                    if isinstance(item, Mapping)
                }
            )
        )
        _require(
            len(physical_sign_ids) > 0,
            f"{prefix} must retain at least one physical-sign identity",
        )
        source_split_id = source.get("source_split_id")
        _require(
            source_split_id is None or isinstance(source_split_id, str),
            f"{prefix}.source.source_split_id must be a string or null",
        )
        source_artifact_ids = tuple(
            sorted(
                {
                    _safe_id(source[field], f"{prefix}.source.{field}")
                    for field in ("source_id", "source_asset_id")
                }
            )
        )
        projected.append(
            SplitSample(
                sample_id=_safe_id(frame.get("frame_id"), f"{prefix}.frame_id"),
                drive_id=_safe_id(frame.get("drive_id"), f"{prefix}.drive_id"),
                physical_sign_ids=physical_sign_ids,
                near_duplicate_cluster_ids=(),
                source_split_id=(source_split_id.strip().lower() if source_split_id else None),
                source_artifact_ids=source_artifact_ids,
            )
        )
    return projected


def _reject_published_panoramax_validation(sample: SplitSample) -> None:
    prohibited_ids = {
        PUBLISHED_PANORAMAX_VALIDATION_SPLIT,
        *PUBLISHED_PANORAMAX_VALIDATION_ALIASES,
    }
    artifact_overlap = set(sample.source_artifact_ids) & prohibited_ids
    published_validation = sample.source_split_id in prohibited_ids
    _require(
        not artifact_overlap and not published_validation,
        "published Panoramax validation lineage cannot enter an M0 split",
    )


def _split_for_component(
    component_members: Sequence[str],
    *,
    seed: str,
    train_fraction: float,
    calibration_fraction: float,
) -> str:
    material = "\0".join((seed, *sorted(component_members))).encode("utf-8")
    bucket = int.from_bytes(hashlib.sha256(material).digest()[:8], "big") / float(2**64)
    if bucket < train_fraction:
        return "train"
    if bucket < train_fraction + calibration_fraction:
        return "calibration"
    return "holdout"


def build_group_split(
    samples: Iterable[SplitSample],
    *,
    seed: str,
    train_fraction: float = 0.7,
    calibration_fraction: float = 0.15,
    near_duplicate_analysis_status: str = "pending",
) -> dict[str, Any]:
    """Return a deterministic connected-component split manifest."""

    _require(isinstance(seed, str) and seed, "seed must be non-empty")
    _require(
        math.isfinite(train_fraction) and 0 < train_fraction < 1,
        "train_fraction must be between zero and one",
    )
    _require(
        math.isfinite(calibration_fraction) and 0 < calibration_fraction < 1,
        "calibration_fraction must be between zero and one",
    )
    _require(
        train_fraction + calibration_fraction < 1,
        "holdout fraction must be positive",
    )
    _require(
        near_duplicate_analysis_status in {"pending", "passed"},
        "near_duplicate_analysis_status must be pending or passed",
    )

    ordered = sorted(samples, key=lambda item: item.sample_id)
    _require(bool(ordered), "at least one sample is required")
    sample_ids = [sample.sample_id for sample in ordered]
    _require(len(sample_ids) == len(set(sample_ids)), "sample_id values must be unique")
    for sample in ordered:
        _reject_published_panoramax_validation(sample)
        if near_duplicate_analysis_status == "passed":
            _require(
                bool(sample.near_duplicate_cluster_ids),
                "a passed near-duplicate analysis requires a cluster ID for every sample",
            )

    graph = _UnionFind()
    for sample in ordered:
        sample_node = f"sample:{sample.sample_id}"
        drive_node = f"drive:{sample.drive_id}"
        graph.add(sample_node)
        graph.add(drive_node)
        graph.union(sample_node, drive_node)
        for physical_sign_id in sample.physical_sign_ids:
            sign_node = f"sign:{physical_sign_id}"
            graph.add(sign_node)
            graph.union(sample_node, sign_node)
        for cluster_id in sample.near_duplicate_cluster_ids:
            duplicate_node = f"near-duplicate:{cluster_id}"
            graph.add(duplicate_node)
            graph.union(sample_node, duplicate_node)

    component_samples: dict[str, list[SplitSample]] = {}
    for sample in ordered:
        root = graph.find(f"sample:{sample.sample_id}")
        component_samples.setdefault(root, []).append(sample)

    groups: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    for component in sorted(
        component_samples.values(), key=lambda items: tuple(item.sample_id for item in items)
    ):
        component_sample_ids = sorted(item.sample_id for item in component)
        drive_ids = sorted({item.drive_id for item in component})
        sign_ids = sorted(
            {sign_id for item in component for sign_id in item.physical_sign_ids}
        )
        near_duplicate_ids = sorted(
            {
                cluster_id
                for item in component
                for cluster_id in item.near_duplicate_cluster_ids
            }
        )
        identity_members = [
            *(f"sample:{value}" for value in component_sample_ids),
            *(f"drive:{value}" for value in drive_ids),
            *(f"sign:{value}" for value in sign_ids),
            *(f"near-duplicate:{value}" for value in near_duplicate_ids),
        ]
        component_sha256 = hashlib.sha256(
            "\0".join(identity_members).encode("utf-8")
        ).hexdigest()
        split = _split_for_component(
            identity_members,
            seed=seed,
            train_fraction=train_fraction,
            calibration_fraction=calibration_fraction,
        )
        component_id = f"group-{component_sha256[:20]}"
        assignment_digest = hashlib.sha256(
            "\0".join((seed, split, *identity_members)).encode("utf-8")
        ).hexdigest()
        groups.append(
            {
                "component_id": component_id,
                "drive_ids": drive_ids,
                "physical_sign_ids": sign_ids,
                "near_duplicate_cluster_ids": near_duplicate_ids,
                "sample_ids": component_sample_ids,
                "partition": split,
                "assignment_digest": assignment_digest,
            }
        )
        assignments.extend(
            {
                "sample_id": item.sample_id,
                "drive_id": item.drive_id,
                "physical_sign_ids": list(item.physical_sign_ids),
                "near_duplicate_cluster_ids": list(item.near_duplicate_cluster_ids),
                "source_split_id": item.source_split_id,
                "component_id": component_id,
                "partition": split,
            }
            for item in component
        )

    manifest_digest = hashlib.sha256(
        "\0".join(group["assignment_digest"] for group in groups).encode("utf-8")
    ).hexdigest()
    manifest = {
        "schema_version": 2,
        "manifest_id": f"youspeed-tsr-group-split-v2-{manifest_digest[:16]}",
        "taxonomy_version": "tsr-semantic-v2",
        "seed": seed,
        "strategy": {
            "algorithm": "connected_components_seeded_sha256_v1",
            "group_keys": [
                "drive_id",
                "physical_sign_id",
                "near_duplicate_cluster_id",
            ],
            "partitions": {
                "train": train_fraction,
                "calibration": calibration_fraction,
                "holdout": 1 - train_fraction - calibration_fraction,
            },
        },
        "prohibited_source_splits": [
            {
                "source_split_id": PUBLISHED_PANORAMAX_VALIDATION_SPLIT,
                "aliases": sorted(PUBLISHED_PANORAMAX_VALIDATION_ALIASES),
                "reason": (
                    "The published crop validation archive overlaps its training "
                    "archive and is benchmark/leakage-audit material only."
                ),
                "permitted_usage": "bootstrap_or_leakage_audit_only",
                "assigned_sample_count": 0,
            }
        ],
        "components": groups,
        "samples": sorted(assignments, key=lambda item: item["sample_id"]),
        "leakage_audit": {
            "drive_overlap_count": 0,
            "physical_sign_overlap_count": 0,
            "near_duplicate_analysis_status": near_duplicate_analysis_status,
            "near_duplicate_overlap_count": (
                0 if near_duplicate_analysis_status == "passed" else None
            ),
            "prohibited_source_split_count": 0,
            "passed": near_duplicate_analysis_status == "passed",
        },
    }
    validate_group_split(manifest)
    return manifest


def validate_group_split(manifest: Mapping[str, Any]) -> None:
    """Validate relational invariants that JSON Schema alone cannot express."""

    _require(manifest.get("schema_version") == 2, "unsupported group-split schema")
    groups = manifest.get("components")
    assignments = manifest.get("samples")
    _require(isinstance(groups, list) and groups, "components must be non-empty")
    _require(isinstance(assignments, list) and assignments, "samples must be non-empty")
    seen: dict[str, dict[str, str]] = {
        "sample": {},
        "drive": {},
        "physical sign": {},
        "near duplicate": {},
    }
    group_ids: set[str] = set()
    groups_by_id: dict[str, Mapping[str, Any]] = {}
    assignment_by_sample: dict[str, tuple[str, str]] = {}
    for index, group in enumerate(groups):
        _require(isinstance(group, Mapping), f"components[{index}] must be an object")
        component_id = _safe_id(group.get("component_id"), f"components[{index}].component_id")
        _require(component_id not in group_ids, f"duplicate component_id {component_id}")
        group_ids.add(component_id)
        groups_by_id[component_id] = group
        split = group.get("partition")
        _require(split in SPLITS, f"components[{index}].partition is invalid")
        for label, field in (
            ("sample", "sample_ids"),
            ("drive", "drive_ids"),
            ("physical sign", "physical_sign_ids"),
            ("near duplicate", "near_duplicate_cluster_ids"),
        ):
            values = group.get(field)
            _require(isinstance(values, list), f"components[{index}].{field} must be an array")
            for value in values:
                _safe_id(value, f"components[{index}].{field}[]")
                prior_split = seen[label].get(value)
                _require(
                    prior_split in {None, split},
                    f"{label} {value} leaks across {prior_split} and {split}",
                )
                seen[label][value] = split
                if label == "sample":
                    _require(value not in assignment_by_sample, f"sample {value} is repeated")
                    assignment_by_sample[value] = (component_id, split)
        identity_members = [
            *(f"sample:{value}" for value in sorted(group["sample_ids"])),
            *(f"drive:{value}" for value in sorted(group["drive_ids"])),
            *(f"sign:{value}" for value in sorted(group["physical_sign_ids"])),
            *(
                f"near-duplicate:{value}"
                for value in sorted(group["near_duplicate_cluster_ids"])
            ),
        ]
        expected_component_sha = hashlib.sha256(
            "\0".join(identity_members).encode("utf-8")
        ).hexdigest()
        _require(
            component_id == f"group-{expected_component_sha[:20]}",
            f"component {component_id} identity digest is wrong",
        )
        expected_assignment_digest = hashlib.sha256(
            "\0".join((manifest["seed"], split, *identity_members)).encode("utf-8")
        ).hexdigest()
        _require(
            group.get("assignment_digest") == expected_assignment_digest,
            f"component {component_id} assignment digest is wrong",
        )

    prohibited_ids: set[str] = set()
    for item in manifest.get("prohibited_source_splits", []):
        prohibited_ids.add(item["source_split_id"])
        prohibited_ids.update(item["aliases"])
    for index, assignment in enumerate(assignments):
        _require(isinstance(assignment, Mapping), f"samples[{index}] must be an object")
        _require(
            set(assignment)
            == {
                "sample_id",
                "drive_id",
                "physical_sign_ids",
                "near_duplicate_cluster_ids",
                "source_split_id",
                "component_id",
                "partition",
            },
            f"samples[{index}] has unexpected fields",
        )
        sample_id = _safe_id(assignment["sample_id"], f"samples[{index}].sample_id")
        expected = assignment_by_sample.get(sample_id)
        _require(expected is not None, f"assignment references unknown sample {sample_id}")
        _require(
            expected == (assignment["component_id"], assignment["partition"]),
            f"assignment for {sample_id} disagrees with its component",
        )
        group = groups_by_id[assignment["component_id"]]
        _require(
            assignment["drive_id"] in group["drive_ids"],
            f"sample {sample_id} drive is absent from its component",
        )
        _require(
            set(assignment["physical_sign_ids"]).issubset(
                group["physical_sign_ids"]
            ),
            f"sample {sample_id} physical signs are absent from its component",
        )
        _require(
            set(assignment["near_duplicate_cluster_ids"]).issubset(
                group["near_duplicate_cluster_ids"]
            ),
            f"sample {sample_id} near-duplicate clusters are absent from its component",
        )
        _require(
            assignment["source_split_id"] not in prohibited_ids,
            f"sample {sample_id} uses a prohibited source split",
        )
    _require(
        len(assignments) == len(assignment_by_sample),
        "samples must cover every component sample exactly once",
    )
    partitions = manifest.get("strategy", {}).get("partitions", {})
    _require(
        set(partitions) == set(SPLITS)
        and math.isclose(sum(partitions.values()), 1.0, abs_tol=1e-12),
        "strategy partition weights must sum to one",
    )
    audit = manifest.get("leakage_audit")
    _require(isinstance(audit, Mapping), "leakage_audit must be an object")
    for field in (
        "drive_overlap_count",
        "physical_sign_overlap_count",
        "prohibited_source_split_count",
    ):
        _require(audit.get(field) == 0, f"leakage_audit.{field} must be zero")
    near_status = audit.get("near_duplicate_analysis_status")
    _require(near_status in {"pending", "passed"}, "near-duplicate status is invalid")
    if near_status == "passed":
        _require(
            all(item["near_duplicate_cluster_ids"] for item in assignments),
            "a passed near-duplicate analysis requires a cluster ID for every sample",
        )
        _require(audit.get("near_duplicate_overlap_count") == 0, "near-duplicate overlap must be zero")
        _require(audit.get("passed") is True, "completed zero-overlap audit must pass")
    else:
        _require(audit.get("near_duplicate_overlap_count") is None, "pending near-duplicate audit cannot claim a count")
        _require(audit.get("passed") is False, "pending near-duplicate audit cannot pass")


def _load_samples(path: Path) -> list[SplitSample]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GroupSplitError(f"cannot read {path}: {error}") from error
    _require(isinstance(payload, Mapping), "input must be an object")
    if "frames" in payload:
        return samples_from_full_scene_manifest(payload)
    values = payload.get("samples")
    _require(isinstance(values, list), "input.samples must be an array")
    return [sample_from_mapping(value, f"samples[{index}]") for index, value in enumerate(values)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="build a deterministic split manifest")
    build.add_argument("input", type=Path, help="JSON object containing sample grouping records")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--seed", required=True)
    build.add_argument("--train-fraction", type=float, default=0.7)
    build.add_argument("--calibration-fraction", type=float, default=0.15)
    build.add_argument(
        "--near-duplicate-analysis-status",
        choices=("pending", "passed"),
        default="pending",
        help="claim passed only after every sample has reviewed near-duplicate clustering",
    )

    validate = subparsers.add_parser("validate", help="validate relational split invariants")
    validate.add_argument("manifest", type=Path)

    args = parser.parse_args(argv)
    if args.command == "validate":
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
        validate_group_split(payload)
        print(json.dumps({"valid": True}, sort_keys=True))
        return 0

    samples = _load_samples(args.input)
    manifest = build_group_split(
        samples,
        seed=args.seed,
        train_fraction=args.train_fraction,
        calibration_fraction=args.calibration_fraction,
        near_duplicate_analysis_status=args.near_duplicate_analysis_status,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "built": True,
                "sample_count": len(manifest["samples"]),
                "component_count": len(manifest["components"]),
                "leakage_audit_passed": manifest["leakage_audit"]["passed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
