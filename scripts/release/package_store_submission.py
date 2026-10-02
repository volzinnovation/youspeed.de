#!/usr/bin/env python3
"""Package reviewed listing sources and evidence; never upload or submit."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tmp/store-submission-1.3/YouSpeed-1.3-store-assets.zip")
    args = parser.parse_args()
    validation = ROOT / "docs/release/STORE_PACKAGE_VALIDATION_2026-10-02.json"
    subprocess.run([sys.executable, str(ROOT / "scripts/release/validate_store_package.py"),
                    "--report", str(validation)], check=True)

    # Explicit source roots prevent inclusion of credentials, device recordings,
    # debug logs, model training data or unrelated concurrent working-tree files.
    roots = ("store/apple", "store/android", "store/artwork", "fastlane/metadata/android")
    files = {p for directory in roots for p in (ROOT / directory).rglob("*")
             if p.is_file() and p.name != ".DS_Store"}
    reports = ("STORE_SUBMISSION_1.3_2026-10-02.md", "STORE_PACKAGE_VALIDATION_2026-10-02.json",
               "IPHONE_READINESS_2026-10-02.md", "ANDROID_READINESS_2026-10-02.md",
               "STORE_METADATA_READINESS_2026-10-02.md", "STORE_SCREENSHOT_REVIEW_2026-10-02.md",
               "COUNTRY_STORE_EXAMPLES_2026-10-02.md", "COUNTRY_STORE_EXAMPLES_2026-10-02.json",
               "PUBLIC_MAP_READINESS_2026-10-02.json", "SCREENSHOT_ENCODING_VALIDATION_2026-10-02.json",
               "PANORAMAX_PRIVACY_READINESS_2026-10-02.md", "PANORAMAX_PRIVACY_READINESS_2026-10-02.json")
    files.update(ROOT / "docs/release" / name for name in reports)
    files.update(ROOT / name for name in ("store/country-availability-1.3.json", "store/README.md",
                  "Web/datenschutz.html", "Web/support/index.html",
                  "scripts/release/validate_store_package.py", "scripts/release/generate_store_graphics.mjs",
                  "scripts/release/package_store_submission.py", "scripts/release/generate_store_screenshot_layouts.mjs",
                  "scripts/iphone/recreate_store_screenshots.sh",
                  "scripts/iphone/normalize_store_screenshot.py", "scripts/iphone/requirements-screenshots.txt",
                  "android/scripts/recreate_store_screenshots.sh", "android/scripts/prepare-play-release.sh",
                  "android/scripts/audit-release-artifact.py"))
    files.update(ROOT / name for name in ("docs/DUTCH_PENALTY_REVIEW_2026-10-02.md",
                  "docs/PENALTY_DOCUMENTATION.md"))
    missing = [str(p.relative_to(ROOT)) for p in files if not p.is_file()]
    if missing:
        raise SystemExit("Required handoff files missing: " + ", ".join(sorted(missing)))
    ordered = sorted(files, key=lambda p: p.relative_to(ROOT).as_posix())
    payloads = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in ordered}
    validation_report = json.loads(payloads[validation.relative_to(ROOT).as_posix()])
    if validation_report["android_version_code"] != "10031":
        raise SystemExit("This handoff is prepared for 1.3 (10031); review the version before packaging another build")
    for checked in validation_report["files"]:
        if hashlib.sha256(payloads[checked["path"]]).hexdigest() != checked["sha256"]:
            raise SystemExit("Source changed after validation: " + checked["path"])
    manifest = {"format": "youspeed.store-assets.v1", "version": "1.3", "build": 10031,
                "console_changes_applied": False, "submission_performed": False,
                "contains_app_binaries": False,
                "files": [{"path": name, "bytes": len(raw),
                           "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in payloads.items()]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        payloads["PACKAGE_MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
        for name, raw in payloads.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 2, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            executable = name != "PACKAGE_MANIFEST.json" and (ROOT / name).stat().st_mode & 0o111
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            archive.writestr(info, raw)
    checksum = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(".zip.sha256").write_text(f"{checksum}  {args.output.name}\n")
    print(f"Prepared {args.output}: {len(ordered)} files, {args.output.stat().st_size:,} bytes")
    print(f"SHA-256 {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
