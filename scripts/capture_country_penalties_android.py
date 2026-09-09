#!/usr/bin/env python3
"""Capture actual Android debug UI country/penalty scenarios; never builds mock screenshots.

Install app-debug.apk on an emulator first, then pass --adb, --serial and --output.
The synthetic road/speed/GPS inputs use the production selector, parser and renderer.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    package = "de.youspeed.android.debug"
    adb = [args.adb, "-s", args.serial]

    def run(*parts):
        return subprocess.check_output(adb + list(parts))

    matrix = [("FRA", "FR-fr", "fr-FR", [0, 2, 10, 25, 35, 45, 55]),
              ("NLD", "NL-nl", "nl-NL", [0, 2, 10, 35, 45, 55]),
              ("BEL", "BE-nl", "nl-BE", [0, 5, 15, 25, 35, 45]),
              ("BEL", "BE-fr", "fr-BE", [0, 5, 15, 25, 35, 45]),
              ("BEL", "BE-de", "de-BE", [0, 5, 15, 25, 35, 45])]
    manifest = []
    for code, folder, locale, deltas in matrix:
        destination = args.output / "android" / folder
        destination.mkdir(parents=True, exist_ok=True)
        rules = json.loads((repo / f"android/app/src/main/assets/Rules/{code}-rules.json").read_text())
        run("shell", "cmd", "locale", "set-app-locales", package, "--locales", locale)
        scenarios = [(delta, 50) for delta in deltas]
        if code == "FRA":
            scenarios += [(2, 70), (10, 70)]
        for index, (delta, limit) in enumerate(scenarios):
            name = f"{index:02d}-delta-{delta:02d}-limit-{limit}.png"
            run("shell", "am", "force-stop", package)
            run("shell", "am", "start", "-W", "-n", f"{package}/de.youspeed.android.alpha.MainActivity",
                "--es", "screenshot_state", "warn-level-0", "--es", "screenshot_country", code,
                "--ei", "screenshot_delta", str(delta), "--ei", "screenshot_limit", str(limit))
            for attempt in range(5):
                time.sleep(0.5)
                run("shell", "uiautomator", "dump", "/sdcard/youspeed-country-window.xml")
                xml = run("exec-out", "cat", "/sdcard/youspeed-country-window.xml")
                nodes = {n.get("resource-id"): n for n in ET.fromstring(xml).iter("node") if n.get("resource-id")}
                if "active-rule-country" in nodes:
                    break
            assert "active-rule-country" in nodes, f"Country UI missing: {code} {locale} +{delta}"
            band = next((b for b in rules["bands"] if b["min_delta_kmh"] <= delta <= (b["max_delta_kmh"] or 1000)), None)
            if band:
                expected = band["localized_templates"][locale[:2]]["title_template"].replace("{delta}", str(delta)).replace("{currency}", rules["currency_code"])
                assert nodes["penalty-notice-title"].get("text") == expected, (locale, nodes)
                assert "penalty-estimate-note" in nodes
                expected_detail = band["localized_templates"][locale[:2]]["detail_template"].replace("{delta}", str(delta)).replace("{currency}", rules["currency_code"])
                assert nodes["penalty-notice-details"].get("text") == expected_detail, (nodes["penalty-notice-details"].get("text"), expected_detail)
            else:
                assert "penalty-notice-title" not in nodes
            (destination / name).write_bytes(run("exec-out", "screencap", "-p"))
            (destination / name.replace(".png", ".xml")).write_bytes(xml)
            entry = dict(platform="android", country=code, locale=locale, delta_kmh=delta, limit_kmh=limit,
                         simulated=True, image=str((destination / name).resolve()),
                         displayed={key: node.get("text") for key, node in nodes.items() if key in
                                    ["active-rule-country", "penalty-notice-title", "penalty-notice-details", "primary-metric", "secondary-metric"]})
            (destination / name.replace(".png", ".json")).write_text(json.dumps(entry, ensure_ascii=False, indent=2))
            manifest.append(entry)
            print(f"Captured {folder}/{name}", flush=True)
    (args.output / "android" / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
