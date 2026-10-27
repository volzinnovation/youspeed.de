#!/usr/bin/env python3
"""Fetch hash-pinned GeoDesk sources and build the isolated host prototype.

No source, bundle, policy or installed app is changed. Downloads/build artifacts
stay in --scratch. Mobile builds use shared/runtime-storage-geodesk/CMakeLists.txt
directly and never download dependencies at configure time.
"""
from __future__ import annotations
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
PINS = [
    ("libgeodesk", "c59eba63575f94bd484177fe4220b464e4339ffc",
     "https://codeload.github.com/clarisma/libgeodesk/tar.gz/c59eba63575f94bd484177fe4220b464e4339ffc",
     "9eae22bc680b129a99e75fa2a30964406f92f4db6e28352e3f63b54b62a9eb64"),
    ("gol-source", "258dde35949e05185fb7615e79ab1a0a6268142a",
     "https://codeload.github.com/clarisma/geodesk-gol/tar.gz/258dde35949e05185fb7615e79ab1a0a6268142a",
     "2d68e973197b6dbc00012b19c14cef0938fb38aa872ed0a1f7ad713ff93b757a"),
    ("gtl", "v1.2.0",
     "https://codeload.github.com/greg7mdp/gtl/tar.gz/refs/tags/v1.2.0",
     "1547ab78f62725c380f50972f7a49ffd3671ded17a3cb34305da5c953c6ba8e7"),
]
HTTPLIB = ("https://raw.githubusercontent.com/yhirose/cpp-httplib/v0.18.3/httplib.h",
           "a0a0c13dc086663863dbe6730a19716f7d3744904b6205496e8301750814dbd5")


def fetch(path: Path, url: str, sha: str) -> None:
    if not path.exists():
        tmp = path.with_suffix(path.suffix + ".part")
        with urllib.request.urlopen(url) as inp, tmp.open("wb") as out:
            shutil.copyfileobj(inp, out)
        tmp.rename(path)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != sha:
        raise RuntimeError(f"Hash mismatch for {path}: {actual} != {sha}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scratch", type=Path, required=True)
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--openssl-root", type=Path)
    ap.add_argument("--pbf", type=Path)
    ap.add_argument("--gol", type=Path)
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--disk-indexes", action="store_true",
                    help="Use upstream disk-backed temporary ID indexes (can exceed 10 GiB)")
    args = ap.parse_args()
    scratch = args.scratch.resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    for name, _ref, url, sha in PINS:
        archive = scratch / (name + ".tar.gz")
        fetch(archive, url, sha)
        if not (scratch / name).exists():
            with tarfile.open(archive, "r:gz") as tf:
                top = tf.getmembers()[0].name.split("/")[0]
                # Python's data filter rejects absolute/parent/symlink escapes.
                tf.extractall(scratch, filter="data")
            (scratch / top).rename(scratch / name)
    fetch(scratch / "httplib.h", *HTTPLIB)
    # Build-only change: private temporary ID-index pages avoid APFS allocating
    # almost the full sparse OSM ID domain. GOL bytes and native phone reader are
    # unchanged. The patch rejects persisting RAM indexes for updatable builds.
    index_cpp = scratch / "gol-source/src/build/util/MappedIndex.cpp"
    if "YOUSPEED_GOL_RAM_INDEXES" not in index_cpp.read_text():
        subprocess.run(["patch", "--directory", str(scratch / "gol-source"),
                        "--strip=1", "--input", str(Path(__file__).with_name(
                            "temporary-index-ram.patch"))], check=True)
    build = scratch / "build-host"
    cmd = ["cmake", "-S", str(ROOT / "shared/runtime-storage-geodesk"),
           "-B", str(build), "-DCMAKE_BUILD_TYPE=Release",
           f"-DGEODESK_SOURCE_DIR={scratch / 'libgeodesk'}",
           f"-DGTL_SOURCE_DIR={scratch / 'gtl'}",
           "-DSTORAGE_GEODESK_BUILD_TOOL=ON",
           f"-DGOL_SOURCE_DIR={scratch / 'gol-source'}",
           f"-DHTTPLIB_INCLUDE_DIR={scratch}"]
    if args.openssl_root:
        cmd.append(f"-DOPENSSL_ROOT_DIR={args.openssl_root.resolve()}")
    subprocess.run(cmd, check=True)
    subprocess.run(["cmake", "--build", str(build), "--parallel", str(args.parallel)], check=True)
    if bool(args.pbf) != bool(args.gol):
        ap.error("--pbf and --gol must be supplied together")
    if args.pbf:
        env = os.environ.copy()
        if not args.disk_indexes and os.name != "nt":
            env["YOUSPEED_GOL_RAM_INDEXES"] = "1"
        subprocess.run([str(build / "storage_gol"), "build", str(args.gol.resolve()),
                        str(args.pbf.resolve()), "--threads", str(args.threads), "--no-color"],
                       env=env, check=True)


if __name__ == "__main__":
    main()
