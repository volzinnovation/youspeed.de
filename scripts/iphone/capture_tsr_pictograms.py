#!/usr/bin/env python3
"""Capture native UI from explicitly synthetic classifier-output replay.

This verifies display/state behavior, not recognition accuracy. Use
probe_city_entry.swift for actual bundled Core ML inference on a real image.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = 'de.youspeed.SpeedConsumer'
CASES = [
    ('01-give-way', 'give_way', 'give_way'),
    ('02-stop-replaces', 'give_way,stop', 'stop'),
    ('03-speed-clears', 'give_way,stop,maxspeed:30', None),
    ('04-rejected-retains', 'give_way,bad', 'give_way'),
    ('05-unmapped-clears', 'give_way,other', None),
    ('06-zone-clears', 'give_way,zone:30', None),
]


def simctl(*args, **kwargs):
    return subprocess.run(['xcrun', 'simctl', *args], text=True, capture_output=True, check=True, **kwargs).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    app = ROOT / 'iphone/.derived/SpeedConsumerBuild/Build/Products/Debug-iphonesimulator/SpeedConsumer.app'
    simctl('install', args.device, str(app))
    simctl('privacy', args.device, 'grant', 'location', BUNDLE)
    simctl('status_bar', args.device, 'override', '--time', '9:41', '--dataNetwork', 'wifi', '--wifiMode', 'active', '--wifiBars', '3', '--batteryState', 'charged', '--batteryLevel', '100')
    container = Path(simctl('get_app_container', args.device, BUNDLE, 'data'))
    report_path = container / 'Documents/sign-review.json'
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        for name, classes, expected in CASES:
            subprocess.run(['xcrun', 'simctl', 'terminate', args.device, BUNDLE], capture_output=True)
            report_path.unlink(missing_ok=True)
            env = dict(os.environ, SIMCTL_CHILD_YOUSPEED_SCREENSHOT_STATE='traffic-sign-pictogram', SIMCTL_CHILD_YOUSPEED_SCREENSHOT_SIGNS=classes)
            simctl('launch', args.device, BUNDLE, '-AppleLanguages', '(de)', '-AppleLocale', 'de_DE', env=env)
            deadline = time.monotonic() + 20
            while not report_path.exists() and time.monotonic() < deadline:
                time.sleep(0.2)
            row = json.loads(report_path.read_text())
            assert row['displayed_class'] == expected, row
            assert row['posted_limit_kmh'] == 50, row
            assert row['city_entry_model_available'] is False, row
            time.sleep(5)
            screenshot = args.output / f'{name}.png'
            simctl('io', args.device, 'screenshot', str(screenshot))
            row.update(screenshot=str(screenshot), screenshot_sha256=hashlib.sha256(screenshot.read_bytes()).hexdigest(), expected_displayed_class=expected, capture='original simulator pixels')
            screenshot.with_suffix('.json').write_text(json.dumps(row, indent=2, ensure_ascii=False) + '\n')
            rows.append(row)
            print(f'Captured {name}: {expected}', flush=True)
        (args.output / 'pictogram-manifest.json').write_text(json.dumps(rows, indent=2, ensure_ascii=False) + '\n')
    finally:
        subprocess.run(['xcrun', 'simctl', 'terminate', args.device, BUNDLE], capture_output=True)
        subprocess.run(['xcrun', 'simctl', 'status_bar', args.device, 'clear'], capture_output=True)


if __name__ == '__main__':
    main()
