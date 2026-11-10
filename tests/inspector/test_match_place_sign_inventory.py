import copy
import sqlite3

import pytest

from scripts.inspector.match_place_sign_inventory import attach_inventory_matches


@pytest.fixture
def inventory(tmp_path):
    path = tmp_path / "inventory.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE traffic_sign_source (
                source_id, publisher, dataset_url, license_id, license_url,
                snapshot_timestamp, snapshot_sha256
            );
            INSERT INTO traffic_sign_source VALUES (
                'mobidata-bw-vzk', 'MobiData BW', 'https://mobidata-bw.de/',
                'dl-de/by-2-0', 'https://www.govdata.de/dl-de/by-2-0', '2026-10-17', 'hash'
            );
            CREATE TABLE traffic_sign_inventory (
                source_id, record_key, group_id, location_id, sign_code,
                longitude, latitude, orientation_deg, updated_at
            );
        """)
        connection.executemany(
            "INSERT INTO traffic_sign_inventory VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("mobidata-bw-vzk", key, key, "location", code, lon, 48.8, heading, None)
                for key, code, lon, heading in [
                    ("near", "DE:222", 8.4401, 360),
                    ("far", "DE:222", 8.441, 90),
                    ("different-type", "DE:222-10", 8.44, 180),
                    ("ambiguous", "DE:222", 8.4402, None),
                ]
            ],
        )
    return path


def test_matches_exact_class_within_radius_and_preserves_unmatched_groups(inventory):
    proposal = {"longitude": 8.44, "latitude": 48.8, "azimut_deg": 150}
    document = {
        "groups": [
            {"id": "matched", "sign_code": "DE:222", "proposal": proposal},
            {"id": "unmatched", "sign_code": "DE:205", "proposal": proposal},
            {"id": "unresolved", "sign_code": "DE:222", "proposal": None},
            {"id": "challenged", "sign_code": "DE:222", "proposal": {
                **proposal, "position_status": "challenged_review",
            }},
        ],
        "summary": {},
    }
    original = copy.deepcopy(document)
    attach_inventory_matches(document, inventory)
    assert [group["id"] for group in document["groups"]] == [
        group["id"] for group in original["groups"]
    ]
    matches = document["groups"][0]["mobidata_matches"]
    assert [row["record_key"] for row in matches] == ["near", "ambiguous"]
    assert all(0 < row["distance_m"] < 30 for row in matches)
    assert matches[0]["orientation_deg"] == 360
    assert matches[1]["orientation_deg"] is None
    assert document["groups"][0]["proposal"] == original["groups"][0]["proposal"]
    assert all("mobidata_matches" not in group for group in document["groups"][1:])
    assert document["summary"]["groups_with_mobidata_matches"] == 1
    assert document["mobidata_reference"]["snapshot_timestamp"] == "2026-10-17"
    with sqlite3.connect(inventory) as connection:
        connection.execute("DELETE FROM traffic_sign_inventory")
        connection.commit()
    attach_inventory_matches(document, inventory)
    assert document["groups"] == original["groups"]
    assert document["summary"]["groups_with_mobidata_matches"] == 0


def test_inventory_path_must_exist(inventory):
    missing = inventory.with_name("missing.sqlite")
    with pytest.raises(sqlite3.OperationalError):
        attach_inventory_matches({"groups": [], "summary": {}}, missing)
    assert not missing.exists()
