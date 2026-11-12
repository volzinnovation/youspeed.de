import json
import subprocess
import sys
from pathlib import Path

import pytest

from shapely.geometry import Point, box, mapping
from scripts.inspector.batch_survey_inventory import NORMALIZER_WRAPPER, assign_jurisdictions, refresh_scope_summary, scoped_sql, verify_source_pack
from scripts.inspector.survey_scope import make_scope, project_geometry


KNOWN = """    AND (
      ((i.metadata#>>'{picture,geometry,coordinates,0}')::double precision BETWEEN 8.36 AND 8.51
      AND (i.metadata#>>'{picture,geometry,coordinates,1}')::double precision BETWEEN 48.74 AND 48.88)
      OR
      ((i.metadata#>>'{picture,geometry,coordinates,0}')::double precision BETWEEN 8.58 AND 8.82
      AND (i.metadata#>>'{picture,geometry,coordinates,1}')::double precision BETWEEN 48.81 AND 49.00)
    )"""


def test_scoped_sql_only_replaces_exact_known_geographic_clause():
    before = "WITH candidates AS (SELECT * WHERE i.active AND NOT EXISTS (suppression)\n"
    after = "\n) SELECT * FROM candidates WHERE feature.active AND crop.current;"
    sql = scoped_sql(before + KNOWN + after, (8.4, 48.7, 8.5, 48.9))
    assert sql.startswith(before) and sql.endswith(after)
    assert "BETWEEN 8.4 AND 8.5" in sql
    assert "BETWEEN 48.7 AND 48.9" in sql
    for changed in (KNOWN.replace("8.36", "8.35"), KNOWN + KNOWN):
        with pytest.raises(ValueError, match="geographic clause changed"):
            scoped_sql(changed, (8.4, 48.7, 8.5, 48.9))


@pytest.mark.parametrize("document", [{"groups": []}, {"schema_version": 1, "source_kind": "inventory_snapshot"},
    {"schema_version": 1, "source_kind": "fresh_management_corpus", "no_previous_inventory_input": True,
     "files": {"groups": {"path": "old.json", "sha256": "old"}}}])
def test_old_inventory_inputs_are_rejected_before_loading_dependencies(tmp_path, document):
    path = tmp_path / "source-pack.json"
    path.write_text(json.dumps(document))
    path.chmod(0o600)
    with pytest.raises(ValueError, match="inventory/group snapshots are forbidden"):
        verify_source_pack(path, make_scope(bbox=(8.4, 48.7, 8.5, 48.9)))


def test_jurisdictions_use_actual_boundaries_and_leave_outside_points_unassigned(tmp_path):
    path = tmp_path / "boundaries.json"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"kind": "gemeinde_ags", "id": "08235033"},
         "geometry": mapping(box(8.4, 48.7, 8.45, 48.9))}]}))
    rows = [{"geometry": mapping(project_geometry(Point(lon, 48.8))), "properties": {}}
            for lon in (8.42, 8.47)]
    assign_jurisdictions(rows, path)
    assert rows[0]["properties"] == {"gemeinde_ags": "08235033", "kreis_ags": "08235"}
    assert rows[1]["properties"] == {"gemeinde_ags": None, "kreis_ags": None}


def test_scoped_normalizer_retains_helper_and_limits_admission_to_requested_camera_area(tmp_path):
    helper = tmp_path / "normalizer.py"
    output = tmp_path / "output.json"
    helper.write_text('''import json,sys
TARGET_BOXES=((8.36,48.74,8.51,48.88),(8.58,48.81,8.82,49.00))
def main():
    assert '--allow-forward-phone' in sys.argv and '--private-panoramax-review' in sys.argv
    with open(sys.argv[sys.argv.index('--output')+1],'w') as stream:
        json.dump(TARGET_BOXES,stream)
''')
    subprocess.run([sys.executable, "-c", NORMALIZER_WRAPPER, str(helper), "report", str(output),
                    "[10.1,49.0,10.2,49.1]"], check=True)
    assert json.loads(output.read_text()) == [[10.1, 49.0, 10.2, 49.1]]
    assert "10.1" not in helper.read_text()


def test_scoped_summary_counts_selected_evidence_and_preserves_canonical_context():
    def observation(annotation, image, longitude=8.42):
        return {"annotation_id": annotation, "image_id": image, "longitude": longitude, "latitude": 48.8}

    canonical = {"groups": 243, "groups_with_proposal": 48, "position_status_counts": {"unresolved": 195},
                 "groups_with_follow_ons": 97, "follow_on_observations": 220, "camera_rule_pairs": 1845,
                 "camera_views_in_window": 1101, "camera_images_in_window": 561, "source_snapshot_at": "current"}
    document = {"summary": canonical, "groups": [
        {"proposal": {"position_status": "nominal_review"},
         "mobile_refinement": {"status": "refined", "proposal": {"position_status": "mobile_refinement"}},
         "observations": [observation("one", "first")],
         "follow_on_observations": [observation("two", "second"), observation("outside", "third", 8.5)]},
        {"proposal": None, "observations": [observation("one", "first")]},
    ]}
    scope = make_scope(bbox=(8.4, 48.7, 8.45, 48.9))
    refresh_scope_summary(document, scope.export, 1)
    summary = document["summary"]
    assert summary["groups"] == 2 and summary["groups_with_proposal"] == 1
    assert summary["position_status_counts"] == {"mobile_refinement": 1, "unresolved": 1}
    assert summary["groups_with_follow_ons"] == 1 and summary["follow_on_observations"] == 2
    assert summary["camera_views_in_window"] == summary["camera_images_in_window"] == 2
    assert summary["located_wfs_features"] == 1 and summary["source_snapshot_at"] == "current"
    assert "camera_rule_pairs" not in summary
    assert document["canonical_summary"] == canonical
    assert canonical["groups"] == 243
