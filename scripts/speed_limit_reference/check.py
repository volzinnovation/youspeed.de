#!/usr/bin/env python3
"""Verify frozen artifacts, packaged pins, transition vocabulary and scenarios."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from model import Machine

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "shared/speed-limit-reference"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", help="Print the normalized reference sequence for one scenario")
    args = parser.parse_args()
    lock_path = PACK / "approval-lock.json"
    lock = json.loads(lock_path.read_text())
    assert lock["schema_version"] == 1
    assert lock["runtime_active"] is True
    for item in lock["artifacts"]:
        assert Path(item["file"]).name == item["file"]
        assert digest(PACK / item["file"]) == item["sha256"], f"Changed frozen artifact: {item['file']}"
    pin = digest(lock_path)
    for path in ["iphone/SpeedConsumerApp/SpeedLimitReferenceModel.swift",
                 "android/app/src/main/java/de/youspeed/android/alpha/SpeedLimitReferenceModel.kt"]:
        assert pin in (ROOT / path).read_text(), f"Approval-lock pin mismatch: {path}"
    policy = json.loads((PACK / "policy-v1.1.0.json").read_text())
    assert policy["schema_version"] == 1 and policy["version"] == lock["target_version"]
    assert policy["priority"] == ["voice", "camera", "bundle"]
    assert policy["limits"]["ordinary_max_age_s"] == 300
    assert policy["limits"]["ordinary_max_distance_m"] == 5000
    assert policy["initial_state"] == "UNKNOWN"
    assert policy["states"] == ["VOICE", "CAMERA", "BUNDLE", "LAST_KNOWN", "UNKNOWN"]
    assert [r["register"] for r in policy["selection"]] == ["voice", "camera", "camera_context", "bundle", "last_known", None]
    assert [r["current"] for r in policy["selection"]] == [True, True, True, True, False, False]
    rules = policy["transitions"]
    assert len({r["id"] for r in rules}) == len(rules)
    assert all(re.fullmatch(r"T\d+", r["id"]) for r in rules)
    assert rules[-1]["on"] == "*" and rules[-1]["guard"] == "always"
    assert set(policy["events"]) == {r["on"] for r in rules if r["on"] != "*"}
    corpus = json.loads((PACK / "scenarios-v1.1.0.json").read_text())
    assert corpus["policy_version"] == policy["version"]
    seen_transitions, seen_states, count = set(), set(), 0
    assert len({s["id"] for s in corpus["scenarios"]}) == len(corpus["scenarios"])
    if args.trace:
        assert args.trace in {s["id"] for s in corpus["scenarios"]}, "Unknown scenario"
    for scenario in corpus["scenarios"]:
        machine = Machine(policy)
        for i, row in enumerate(scenario["steps"]):
            result = machine.step(row["event"])
            for key, expected in row["expect"].items():
                assert result[key] == expected, f"{scenario['id']} step {i} {key}: {result[key]!r} != {expected!r}"
            assert result["violation_reference_kmh"] == result["penalty_reference_kmh"]
            if result["state"] in ("LAST_KNOWN", "UNKNOWN"):
                assert result["current"] is False and result["penalty_reference_kmh"] is None
            if machine.state["voice"] is not None:
                assert result["state"] == "VOICE"
            for source in ("voice", "camera"):
                claim = machine.state[source]
                if claim:
                    assert machine.state["elapsed_s"] - claim["accepted_elapsed_s"] < 300
                    assert machine.state["distance_m"] - claim["accepted_distance_m"] < 5000
            seen_transitions.add(result["transition_id"])
            seen_states.add(result["state"])
            count += 1
            if scenario["id"] == args.trace:
                print(json.dumps(dict(event=row["event"]["kind"], elapsed_s=row["event"]["elapsed_s"], reference=result)))
    assert {r["id"] for r in rules} <= seen_transitions, f"Untested transitions: {set(r['id'] for r in rules) - seen_transitions}"
    assert set(policy["states"]) == seen_states
    print(f"PASS: {len(corpus['scenarios'])} scenarios, {count} steps, all {len(rules)} transitions and {len(seen_states)} states; artifact hashes and both app pins match.")


if __name__ == "__main__":
    check()
