#!/usr/bin/env python3
"""Replay the six backend/device checks from retained compressed evidence."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    directory = Path(__file__).resolve().parent
    evidence = directory / "results"
    summary = json.loads((evidence / "phone-summary.json").read_text())
    require(summary["complete_requested_phones"] is True, "Phone comparison is incomplete")
    require(summary["parity"]["cross_phone_parity_verified"] is True, "Missing cross-phone parity")
    with tempfile.TemporaryDirectory(prefix="youspeed-evidence-") as scratch:
        scratch = Path(scratch)
        for platform in ("android", "iphone"):
            raw = gzip.decompress((evidence / f"{platform}-road-results.json.gz").read_bytes())
            digest = hashlib.sha256(raw).hexdigest()
            for backend in ("packed", "sqlite", "geodesk"):
                recorded = summary["devices"][platform][backend]
                require(digest == recorded["road_results_sha256"], "Raw archive differs from saved backend export")
                report = evidence / f"{platform}-{backend}-final.json"
                require(hashlib.sha256(report.read_bytes()).hexdigest() == recorded["report_sha256"],
                        f"Report changed: {report.name}")
                shutil.copyfile(report, scratch / report.name)
                # Each platform archive represents three verified byte-identical exports.
                (scratch / f"{platform}-{backend}-roads.json").write_bytes(raw)
        size_receipt = directory.parents[1] / "shared/runtime-storage-prototype/results/complete-sizes.json"
        output = scratch / "summary.json"
        subprocess.run([sys.executable, str(directory / "compare_reports.py"), str(scratch),
                        str(size_receipt), str(output)], check=True)
        replayed = json.loads(output.read_text())
        require(replayed == summary, "Replayed summary differs from retained measurements")
    print("Retained reports and compressed exports reproduce the complete two-phone comparison.")


if __name__ == "__main__":
    main()
