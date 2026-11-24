#!/usr/bin/env python3
"""Export and verify an immutable OpenSign Core sign-asset snapshot."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess

if __package__:
    from .sign_crosswalk import CROSSWALK, COUNTRIES, TSR, available_artwork, crosswalk, pictogram_path
else:
    from sign_crosswalk import CROSSWALK, COUNTRIES, TSR, available_artwork, crosswalk, pictogram_path

REPOSITORY = "https://github.com/volzinnovation/opensign-core"
LOCK_NAME = "sign-assets.lock.json"
ROOTS = {"inspector": "shared/tsr", "youspeed": "shared/tsr",
         "analytics": "commercial_backend/youspeed/crop_taxonomy"}


def snapshot_files(profile):
    yield CROSSWALK
    yield TSR / "sign_crosswalk.py"
    yield TSR / "sync_sign_crosswalk.py"
    artwork = TSR / "sign-pictograms"
    for country in sorted(COUNTRIES):
        yield TSR / f"prolix-{country.lower()}-class-catalog-v1.json"
    if profile == "analytics":
        yield artwork / "sources/panoramax-country-code-mapping-v1.json"
    elif profile == "inspector":
        yield artwork / "THIRD_PARTY_NOTICES.txt"
        yield from sorted((artwork / "png").glob("*.png"))
        yield from sorted((artwork / "national").glob("*/png/*.png"))
    else:
        yield from sorted(path for path in artwork.rglob("*")
                          if path.is_file() and path != CROSSWALK
                          and not any(part.startswith(".") or part == "__pycache__"
                                      for part in path.relative_to(artwork).parts))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def verify_local(root):
    lock = json.loads((root / LOCK_NAME).read_text(encoding="utf-8"))
    if (lock["repository"] != REPOSITORY or not re.fullmatch(r"[a-f0-9]{40}", lock["revision"])
            or lock["profile"] not in ROOTS):
        raise ValueError("Invalid OpenSign Core asset pin")
    expected = {path.relative_to(TSR).as_posix() for path in snapshot_files(lock["profile"])}
    if set(lock["files"]) != expected:
        raise ValueError("OpenSign Core asset lock and snapshot have different file lists")
    for name, checksum in lock["files"].items():
        path = root / name
        if not path.is_file() or path.is_symlink() or digest(path) != checksum:
            raise ValueError(f"OpenSign Core asset differs: {name}")
    return lock["revision"]


def validate_crosswalk():
    for source in ("display", "mapillary", "mobidata", "openstreetmap"):
        for country, entries in crosswalk()[source].items():
            if country not in COUNTRIES:
                raise ValueError(f"Unknown country: {country}")
            for label, entry in entries.items():
                if "image_path" in entry and not available_artwork(entry["image_path"]):
                    raise ValueError(f"Invalid artwork: {source}/{country}/{label}")
                if "pictogram" in entry and not pictogram_path(country, entry["pictogram"]):
                    raise ValueError(f"Invalid pictogram: {source}/{country}/{label}")
                if "sign_code" in entry and not entry["sign_code"].startswith(country + ":"):
                    raise ValueError(f"Sign code has the wrong country: {source}/{country}/{label}")
    for country, templates in crosswalk()["mapillary_speed_templates"].items():
        for label, code in templates.items():
            if (country not in COUNTRIES or not code.startswith(country + ":")
                    or any(template.count("{speed}") != 1 for template in (label, code))):
                raise ValueError(f"Invalid Mapillary speed template: {country}/{label}")

    data = crosswalk()
    catalog = json.loads((TSR / "prolix-de-class-catalog-v1.json").read_text(encoding="utf-8"))
    labels = catalog["class_labels"]
    model = data["source_metadata"]["panoramax"]["DE"]
    if len(labels) != model["deployed_label_count"] or len(set(labels)) != len(labels):
        raise ValueError("German model catalog and crosswalk have different output vocabularies")
    legacy = set(labels[:model["original_label_count"]])
    for raw, entry in data["mobidata"]["DE"].items():
        if not set(entry["classifier_labels"]) <= legacy:
            raise ValueError(f"MobiData audit refers to an unknown baseline class: {raw}")
        if entry["display_eligible"] and entry["pictogram_png_path"]:
            image = entry["pictogram_png_path"].removeprefix("shared/")
            if not available_artwork(image):
                raise ValueError(f"Missing MobiData pictogram for {raw}")

    for source in ("mapillary", "mobidata", "openstreetmap"):
        for raw, row in data[source]["DE"].items():
            if source == "mapillary" or "target_label" in row:
                target = row.get("target_label")
                status = row.get("mapping_status")
                if status == "reference_only" and source == "mapillary":
                    valid = isinstance(target, str) and bool(target.strip()) and target not in labels
                elif status == "excluded_de" and source == "mapillary":
                    valid = target is None and not row.get("sign_code")
                else:
                    valid = status is None and (target is None or target in labels)
                if "target_label" not in row or not row.get("mapping_basis") or not valid:
                    raise ValueError(f"Invalid reviewed {source} classifier target: {raw}")
            if "review_pictogram" in row and not pictogram_path("DE", row["review_pictogram"]):
                raise ValueError(f"Missing German review pictogram for {raw}")
    if not re.fullmatch(r"[0-9a-f]{40}", data["source_metadata"]["mapillary"]["sprite_revision"]):
        raise ValueError("Mapillary pictogram links require an immutable publisher revision")

    first, last = data["source_metadata"]["synset"]["central_class_ids"]
    entries = data["synset"]["DE"]
    if set(entries) != {str(i) for i in range(first, last + 1)}:
        raise ValueError("Incomplete Synset publisher label inventory")
    for label, row in data["display"]["DE"].items():
        if "synset_id" not in row:
            continue
        raw = row["synset_id"]
        entry = entries.get(raw, {})
        if (entry.get("target_label") != label
                or entry.get("mapping_status") not in {"approved", "reference_only"}
                or row.get("image_path") != f"tsr/sign-pictograms/png/synset-{raw}.png"):
            raise ValueError(f"Invalid Synset display example for {label}: {raw}")
    for key, row in entries.items():
        status, target = row["mapping_status"], row["target_label"]
        valid_targets = {
            "approved": target in labels,
            "reference_only": isinstance(target, str) and bool(target.strip()) and target not in labels,
            "unmapped": target is None,
        }
        if not valid_targets.get(status, False):
            raise ValueError(f"Invalid classifier target or review status for Synset {key}")
        if (not all(row.get(name) for name in ("source_name", "class_name", "mapping_basis"))
                or not re.fullmatch(r"https://synset\.de/[^\s]+", row["source_artwork"])):
            raise ValueError(f"Missing publisher evidence for Synset {key}")
        if (row.get("sign_code") is not None and
                (not re.fullmatch(r"DE:[0-9][0-9.,-]*", row["sign_code"])
                 or row.get("sign_code_scope") not in {"sign", "family"})):
            raise ValueError(f"Invalid national-code relation for Synset {key}")


def previous_helper(root, profile, core_path):
    """Find an obsolete helper only if the previous lock and its Core commit both authenticate its bytes."""
    name = "catalog_labels.py"
    target = root / name
    previous = root / LOCK_NAME
    if not previous.is_file() or (not target.exists() and not target.is_symlink()):
        return None
    lock = json.loads(previous.read_text(encoding="utf-8"))
    revision = lock.get("revision", "")
    if (lock.get("repository") != REPOSITORY or lock.get("profile") != profile
            or not re.fullmatch(r"[a-f0-9]{40}", revision) or name not in lock.get("files", {})):
        return None
    if target.is_symlink() or not target.is_file() or digest(target) != lock["files"][name]:
        raise ValueError(f"Preserve locally changed asset: {target}")
    original = subprocess.run(["git", "-C", str(TSR), "show", f"{revision}:{core_path}/{name}"],
                              capture_output=True)
    if original.returncode or sha256(original.stdout).hexdigest() != lock["files"][name]:
        raise ValueError(f"Could not authenticate previous Core asset: {target}")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="consumer repository root")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--profile", choices=sorted(ROOTS), help="export from the Core checkout")
    mode.add_argument("--verify-local", action="store_true", help="verify an exported snapshot offline")
    args = parser.parse_args()
    if args.verify_local:
        candidates = [args.destination / path for path in set(ROOTS.values()) if (args.destination / path / LOCK_NAME).is_file()]
        if len(candidates) != 1:
            parser.error("Expected one sign-asset lock in the consumer repository")
        root = candidates[0]
        print(f"Verified OpenSign Core sign assets {verify_local(root)}")
        return

    validate_crosswalk()
    root = args.destination / ROOTS[args.profile]
    files = sorted(set(snapshot_files(args.profile)))
    relative = [str(path.relative_to(TSR)) for path in files]
    core_path = TSR.relative_to(TSR.parents[4])
    tracked = set(subprocess.check_output(
        ["git", "-C", str(TSR.parents[4]), "ls-tree", "-r", "--name-only", "HEAD", str(core_path)],
        text=True,
    ).splitlines())
    for name, path in zip(relative, files):
        git_path = (core_path / name).as_posix()
        if git_path not in tracked or path.read_bytes() != subprocess.check_output(
            ["git", "-C", str(TSR.parents[4]), "show", f"HEAD:{git_path}"]
        ):
            raise SystemExit(f"Commit and review the OpenSign Core asset first: {git_path}")
    revision = subprocess.check_output(["git", "-C", str(TSR), "rev-parse", "HEAD"], text=True).strip()
    retired = previous_helper(root, args.profile, core_path)
    for path in files:
        target = root / path.relative_to(TSR)
        if target.is_file() and target.read_bytes() == path.read_bytes():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    if retired is not None:
        retired.unlink()
    lock = {"repository": REPOSITORY, "revision": revision, "profile": args.profile,
            "files": {name: digest(path) for name, path in zip(relative, files)}}
    (root / LOCK_NAME).write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Pinned OpenSign Core sign assets {revision} ({len(files)} files)")


if __name__ == "__main__":
    main()
