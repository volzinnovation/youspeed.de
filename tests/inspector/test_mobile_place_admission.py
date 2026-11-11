from contextlib import contextmanager
import copy
import hashlib
import json
from types import SimpleNamespace

from inspector.server import CropStore


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def source_document():
    event = {"event_id": "event-a"}
    manifest = {"observation_id": "event-a"}
    binding = {
        "installation": "installation-a", "epoch": 1, "event_id": "event-a",
        "crop_id": "crop-a", "crop_digest": "content-a",
        "event_sha256": digest(event), "manifest_sha256": digest(manifest),
        "review_sha256": digest({key: None for key in (
            "review_revision", "verdict", "corrected_classification", "crop_digest",
            "observation_sha256", "manifest_sha256"
        )}),
    }
    row = {"evidence_id": "mobile-a", "source_binding": binding}
    document = {"mobile_reference": {}, "groups": [
        {"id": "matched", "proposal": {"azimut_deg": 10}, "mobile_observations": [row]},
        {"id": "unmatched", "proposal": None},
    ]}
    current = {"evidence_id": "mobile-a", "observation": event, "manifest": manifest, "digest": "content-a"}
    return document, current


def admit(document, current, freshness=(True, True)):
    freshness = iter(freshness)

    class Database:
        def execute(self, sql, params=None):
            if "control_state" in sql:
                return SimpleNamespace(fetchone=lambda: {"fresh": next(freshness)})
            return SimpleNamespace(fetchall=lambda: current)

    @contextmanager
    def connection():
        yield Database()

    source = SimpleNamespace(connection=connection, require_live_controls=CropStore.require_live_controls)
    CropStore.admit_place_mobile(source, document)


def test_admits_bound_current_crop_without_exposing_source_bindings():
    document, current = source_document()
    admit(document, [current])
    row = document["groups"][0]["mobile_observations"][0]
    assert "source_binding" not in row
    assert row["crop_url"] == "/inspector/api/crops/installation-a/1/crop-a/image"
    assert document["mobile_reference"]["visible_observations"] == 1
    assert document["groups"][0]["proposal"] == {"azimut_deg": 10}


def test_withholds_revoked_changed_and_stale_sources_while_preserving_groups():
    for change in ("revoked", "event", "image", "manifest", "review", "stale", "became_stale"):
        document, current = source_document()
        original = copy.deepcopy(document["groups"])
        freshness = (True, True)
        rows = [current]
        if change == "revoked":
            rows = []
        elif change == "event":
            current["observation"]["changed"] = True
        elif change == "image":
            current["digest"] = "replaced"
        elif change == "manifest":
            current["manifest"]["changed"] = True
        elif change == "review":
            current["review_revision"] = 2
        elif change == "stale":
            freshness = (False,)
        else:
            freshness = (True, False)
        admit(document, rows, freshness)
        assert [g["id"] for g in document["groups"]] == [g["id"] for g in original]
        assert all(not g.get("mobile_observations") for g in document["groups"])
        assert document["mobile_reference"]["visible_observations"] == 0


def test_removes_refined_pose_when_a_contributing_source_is_missing():
    document, current = source_document()
    group = document["groups"][0]
    group["mobile_refinement"] = {"mobile_evidence_ids": ["mobile-a", "mobile-b"]}
    admit(document, [current])
    assert "mobile_refinement" not in group
    assert group["proposal"] == {"azimut_deg": 10}
