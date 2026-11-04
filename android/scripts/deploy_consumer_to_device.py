#!/usr/bin/env python3
"""Update one explicitly selected Android driver app without creating a second app.

APK metadata and the installed-package inventory must both be readable before
installation. This helper never uninstalls an app or clears application data.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess


CONSUMER_ID = "de.youspeed.android"
DRIVER_IDS = frozenset((CONSUMER_ID, CONSUMER_ID + ".debug"))
# These are the repository's non-launchable instrumentation APKs, not driver apps.
INSTRUMENTATION_IDS = frozenset(
    (CONSUMER_ID + ".test", CONSUMER_ID + ".debug.test", CONSUMER_ID + ".testhost.test")
)
PACKAGE_PATTERN = r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*"


def apk_metadata(badging: str) -> dict[str, str]:
    packages = [line for line in badging.splitlines() if line.startswith("package:")]
    if len(packages) != 1:
        raise ValueError("Cannot verify the APK package metadata; installation stopped.")
    fields = dict(re.findall(r"([A-Za-z][A-Za-z0-9_]*)='([^']*)'", packages[0]))
    package = fields.get("name", "")
    if not re.fullmatch(PACKAGE_PATTERN, package) or not re.fullmatch(
        r"[1-9][0-9]*", fields.get("versionCode", "")
    ) or not fields.get("versionName"):
        raise ValueError("Cannot verify the APK package/version metadata; installation stopped.")
    if package not in DRIVER_IDS:
        raise ValueError("Consumer deployment requires the normal release/debug app, not a test host.")
    return {key: fields[key] for key in ("name", "versionCode", "versionName")}


def installed_packages(output: str) -> set[str]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines or any(not re.fullmatch("package:" + PACKAGE_PATTERN, line) for line in lines):
        raise ValueError("Cannot verify the phone's installed-package inventory; installation stopped.")
    return {line.removeprefix("package:") for line in lines}


def validate_identity(packages: set[str], target: str) -> None:
    if target not in DRIVER_IDS:
        raise ValueError("Consumer deployment requires the normal release/debug app, not a test host.")
    consumer_apps = {
        package for package in packages
        if (package == CONSUMER_ID or package.startswith(CONSUMER_ID + "."))
        and package not in INSTRUMENTATION_IDS
    }
    conflicts = consumer_apps - {target}
    if conflicts:
        raise ValueError(
            "Other YouSpeed app identities are installed: " + ", ".join(sorted(conflicts))
            + ". Preserve and consolidate their data first. No apps were removed."
        )


def sdk_tools(sdk: Path) -> tuple[Path, Path]:
    adb = sdk / "platform-tools/adb"
    candidates = [path for path in (sdk / "build-tools").glob("*/aapt2")
                  if path.is_file() and os.access(path, os.X_OK)]
    if not adb.is_file() or not os.access(adb, os.X_OK) or not candidates:
        raise ValueError("Android SDK adb and aapt2 are required; installation stopped.")
    aapt2 = max(candidates, key=lambda path: tuple(int(part) for part in re.findall(r"\d+", path.parent.name)))
    return adb, aapt2


def deploy(apk: Path, serial: str, sdk: Path, *, launch: bool = False, run=subprocess.run) -> dict[str, str]:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", serial):
        raise ValueError("An explicit valid Android device serial is required.")
    if not apk.is_file():
        raise ValueError("The APK file does not exist; installation stopped.")
    adb, aapt2 = sdk_tools(sdk)

    def execute(argv: list[str], *, timeout: int = 120) -> str:
        result = run(argv, check=True, capture_output=True, text=True, timeout=timeout)
        return result.stdout

    metadata = apk_metadata(execute([str(aapt2), "dump", "badging", str(apk.resolve())]))
    device = [str(adb), "-s", serial]
    packages = installed_packages(execute([*device, "shell", "pm", "list", "packages"]))
    validate_identity(packages, metadata["name"])
    output = execute([*device, "install", "-r", str(apk.resolve())], timeout=600)
    if "Success" not in output.splitlines():
        raise ValueError("Android did not confirm a successful update; inspect the device before retrying.")
    if launch:
        execute([*device, "shell", "am", "start", "-n",
                 metadata["name"] + "/de.youspeed.android.alpha.MainActivity"])
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--serial", required=True, help="Explicit adb device serial")
    parser.add_argument("--sdk", type=Path, default=Path(
        os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
        or Path.home() / "Library/Android/sdk"))
    parser.add_argument("--launch", action="store_true", help="Launch after the in-place update")
    args = parser.parse_args()
    try:
        metadata = deploy(args.apk, args.serial, args.sdk, launch=args.launch)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(4, str(error) + "\n")
    print(f"Updated {metadata['name']} to {metadata['versionName']} ({metadata['versionCode']}).")


if __name__ == "__main__":
    main()
