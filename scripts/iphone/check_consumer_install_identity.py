#!/usr/bin/env python3
"""Refuse a consumer install that could create or perpetuate a second sandbox."""

import argparse
import json
from pathlib import Path


CONSUMER_ID = "de.youspeed.SpeedConsumer"
SEPARATE_CONSUMER_TEST_HOSTS = {"de.youspeed.PackedRuntimeIntegrationTestHost"}


def validate_identity(inventory: dict, bundle_id: str) -> None:
    if bundle_id not in (CONSUMER_ID, CONSUMER_ID + ".TestHost"):
        raise ValueError("Consumer deployment requires a driver app, not an isolated test host.")
    apps = inventory.get("result", {}).get("apps")
    if not isinstance(apps, list) or any(
        not isinstance(app, dict) or not isinstance(app.get("bundleIdentifier"), str)
        for app in apps
    ):
        raise ValueError("Cannot verify the phone's installed-app inventory; installation stopped.")
    identities = {
        app["bundleIdentifier"]
        for app in apps
        if app["bundleIdentifier"] == CONSUMER_ID
        or app["bundleIdentifier"].startswith(CONSUMER_ID + ".")
        or app["bundleIdentifier"] in SEPARATE_CONSUMER_TEST_HOSTS
    }
    conflicts = identities - {bundle_id}
    if conflicts:
        raise ValueError(
            "Other YouSpeed app identities are installed: "
            + ", ".join(sorted(conflicts))
            + ". Preserve and consolidate their data before installing. No apps were removed."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--bundle-id", required=True)
    args = parser.parse_args()
    try:
        validate_identity(json.loads(args.inventory.read_text()), args.bundle_id)
    except (OSError, ValueError, TypeError, AttributeError) as error:
        parser.exit(4, str(error) + "\n")


if __name__ == "__main__":
    main()
