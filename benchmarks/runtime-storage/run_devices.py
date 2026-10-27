#!/usr/bin/env python3
"""Run already-built/staged isolated benchmarks. Never touches driving app data."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import time
import uuid

BACKENDS = ("sqlite", "geodesk", "packed")
ANDROID_ROOT = "/data/local/tmp/youspeed-storage-prototype"
APP = "de.youspeed.StoragePrototypeBenchmark"


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def require(condition, detail="Device benchmark check failed"):
    if not condition:
        raise ValueError(detail)


def paths(root, backend):
    if backend == "packed":
        return f"{root}/runtime.pack", f"{root}/nodes.yspn"
    if backend == "sqlite":
        return f"{root}/runtime.sqlite", f"{root}/nodes.sqlite"
    return f"{root}/bw-runtime.gol|{root}/runtime.sqlite", f"{root}/bw-runtime.gol|{root}/nodes.sqlite"


def android(args):
    adb = ["adb", "-s", args.device]
    for backend in args.backends:
        road, nodes = paths(ANDROID_ROOT, backend)
        command = [f"{ANDROID_ROOT}/storage_phone_runner", backend, road,
                   f"{ANDROID_ROOT}/stratified.csv", nodes, f"{ANDROID_ROOT}/node-queries.csv",
                   "3", f"{ANDROID_ROOT}/corrections-{backend}.journal"]
        report_path = args.output / f"android-{backend}-final.json"
        with report_path.open("w") as output:
            run(adb + ["shell", shlex.join(command)], stdout=output, timeout=300)
        require(json.loads(report_path.read_text())["overall_success"] is True)
        with (args.output / f"android-{backend}-roads.json").open("w") as output:
            run(adb + ["shell", shlex.join([f"{ANDROID_ROOT}/storage_phone_runner", "--road-parity",
                                           backend, road, f"{ANDROID_ROOT}/stratified.csv"])],
                stdout=output, timeout=120)
        print(f"Android {backend}: passed", flush=True)


def iphone(args):
    base = ["xcrun", "devicectl", "--timeout", "60", "--quiet"]
    for backend in args.backends:
        nonce = str(uuid.uuid4())
        config_dir = args.iphone_config_dir or args.output.parent / "iphone-data"
        config = json.loads((config_dir / f"{backend}.json").read_text())
        config.update(run_id=nonce, write_road_results=True)
        local_config = args.output / f"iphone-config-{backend}.json"
        local_config.write_text(json.dumps(config, indent=2) + "\n")
        run(base + ["device", "copy", "to", "--device", args.device,
                    "--domain-type", "appDataContainer", "--domain-identifier", APP,
                    "--source", str(local_config), "--destination", f"Documents/data/{backend}.json"], timeout=75)
        run(base + ["device", "process", "launch", "--device", args.device,
                    "--terminate-existing", "--json-output", str(args.output / f"iphone-launch-{backend}.json"),
                    APP, "--", "--config", f"data/{backend}.json"], timeout=75)
        report_path = args.output / f"iphone-{backend}-final.json"
        deadline = time.monotonic() + 300
        while True:
            copy = base + ["device", "copy", "from", "--device", args.device,
                           "--domain-type", "appDataContainer", "--domain-identifier", APP,
                           "--source", f"Documents/report-{backend}.json", "--destination", str(report_path)]
            result = subprocess.run(copy, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=75)
            report = json.loads(report_path.read_text()) if result.returncode == 0 else None
            if report and report.get("configuration", {}).get("run_id") == nonce:
                require(report["overall_success"] is True, report)
                require(report["road_results_exported"] is True)
                break
            if time.monotonic() >= deadline:
                progress_path = args.output / f"iphone-{backend}-progress.json"
                subprocess.run(base + ["device", "copy", "from", "--device", args.device,
                                       "--domain-type", "appDataContainer", "--domain-identifier", APP,
                                       "--source", "Documents/benchmark-progress.json",
                                       "--destination", str(progress_path)], timeout=75)
                raise TimeoutError(f"No fresh successful iPhone {backend} report; inspect {progress_path}")
            time.sleep(3)
        run(base + ["device", "copy", "from", "--device", args.device,
                    "--domain-type", "appDataContainer", "--domain-identifier", APP,
                    "--source", f"Documents/road-results-{backend}.json",
                    "--destination", str(args.output / f"iphone-{backend}-roads.json")], timeout=75)
        print(f"iPhone {backend}: passed", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform", choices=("android", "iphone"))
    parser.add_argument("--device", required=True, help="Explicit adb serial or CoreDevice identifier")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backends", nargs="+", choices=BACKENDS, default=BACKENDS)
    parser.add_argument("--iphone-config-dir", type=Path, help="Local staged packed/sqlite/geodesk JSON configurations")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    (android if args.platform == "android" else iphone)(args)


if __name__ == "__main__":
    main()
