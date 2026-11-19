#!/usr/bin/env python3
"""Export and verify an immutable OpenSign Core sign-asset snapshot."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess

from sign_crosswalk import CROSSWALK, COUNTRIES, TSR, available_artwork, crosswalk, pictogram_path

REPOSITORY = "https://github.com/volzinnovation/opensign-core"
LOCK_NAME = "sign-assets.lock.json"


def snapshot_files(profile):
    yield CROSSWALK
    yield TSR / "sign_crosswalk.py"
    yield TSR / "sync_sign_crosswalk.py"
    artwork = TSR / "sign-pictograms"
    for country in sorted(COUNTRIES):
        yield TSR / f"prolix-{country.lower()}-class-catalog-v1.json"
    if profile == "inspector":
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
            or lock["profile"] not in {"inspector", "youspeed"}):
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



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="consumer repository root")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--profile", choices=("inspector", "youspeed"), help="export from the Core checkout")
    mode.add_argument("--verify-local", action="store_true", help="verify an exported snapshot offline")
    args = parser.parse_args()
    root = args.destination / "shared/tsr"
    if args.verify_local:
        print(f"Verified OpenSign Core sign assets {verify_local(root)}")
        return

    validate_crosswalk()
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
    for path in files:
        target = root / path.relative_to(TSR)
        if target.is_file() and target.read_bytes() == path.read_bytes():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    lock = {"repository": REPOSITORY, "revision": revision, "profile": args.profile,
            "files": {name: digest(path) for name, path in zip(relative, files)}}
    (root / LOCK_NAME).write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Pinned OpenSign Core sign assets {revision} ({len(files)} files)")


if __name__ == "__main__":
    main()
