"""Shared #15 vectors must execute unchanged production Swift fusion."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/tsr/applicability/run_shadow_selection_swift.py"


def test_host_model_support_extraction_fails_on_ambiguous_source():
    spec = importlib.util.spec_from_file_location("shadow_selection_runner", RUNNER)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    source = (ROOT / "iphone/SpeedConsumerApp/ConsumerModels.swift").read_text()
    extracted = runner.model_enums(source)
    assert all("enum " + name in extracted for name in runner.ENUMS)
    with pytest.raises(ValueError, match="expected one production enum"):
        runner.model_enums(source + "\n" + extracted)


@pytest.mark.skipif(
    sys.platform != "darwin" or not shutil.which("swiftc"),
    reason="macOS production Swift host dependencies required",
)
def test_actual_swift_fusion_reselects_from_shared_survivors(tmp_path):
    output = tmp_path / "native"
    subprocess.run(
        [sys.executable, str(RUNNER), "--output", str(output)],
        check=True,
        capture_output=True,
        timeout=150,
    )
    receipt = json.loads((output / "receipt.json").read_text())
    actual = json.loads((output / "swift.json").read_text())
    fixtures = json.loads(
        (ROOT / "shared/tsr/applicability/shadow-selection-fixtures.json").read_text()
    )
    assert receipt["passed"] and receipt["cases"] == len(fixtures["cases"])
    assert len(receipt["shipping_mapping_bindings"]) == 2
    assert all(
        entry["tuple"] == ["no_overtaking:end", "unknown", None, 0.7]
        for entry in receipt["shipping_mapping_bindings"]
    )
    assert [r["candidate_id"] for r in actual["cases"]] == [
        r["expected_candidate_id"] for r in fixtures["cases"]
    ]
    rows = {r["id"]: r for r in actual["cases"]}
    assert (
        rows["blocked_exit_preserves_lower_mainline"]["baseline_candidate_id"]
        == "blocked-exit"
    )
    assert rows["blocked_exit_preserves_lower_mainline"]["candidate_id"] == "mainline"
    assert (
        rows["shipping_unknown_ancillary_alias_cannot_hide_mainline"]["candidate_id"]
        == "mainline"
    )
    assert (
        rows["explicit_non_speed_end_semantic_keeps_swift_ranking"]["candidate_id"]
        == "280"
    )
    assert (
        rows["out_of_frame_survivor_cannot_hide_valid_sign"]["candidate_id"]
        == "mainline"
    )
    assert all(
        r["state"] != "confirmed" and r["evidence_frames"] in (None, 1)
        for r in actual["cases"]
    )
