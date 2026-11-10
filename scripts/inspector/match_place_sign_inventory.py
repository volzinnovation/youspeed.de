"""Attach optional nearby MobiData reference candidates to a place review."""

from __future__ import annotations

import math
from pathlib import Path
import sqlite3

from scripts.map.traffic_sign_inventory import SOURCE_ID


MATCH_RADIUS_M = 30
EARTH_RADIUS_M = 6371008.8


def distance_m(first, second):
    lat1, lat2 = map(math.radians, (first[1], second[1]))
    longitude_delta = math.radians(second[0] - first[0])
    value = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(longitude_delta / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1, value)))


def attach_inventory_matches(document, inventory_path):
    """Preserve all groups and poses, adding exact-class candidates within 30 m.

    The reported source orientation is preserved without conversion or use in
    estimating the sign pose. Multiple nearby records remain explicit candidates.
    """
    uri = Path(inventory_path).resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        source = connection.execute(
            "SELECT source_id, publisher, dataset_url, license_id, license_url, "
            "snapshot_timestamp, snapshot_sha256 FROM traffic_sign_source "
            "WHERE source_id=?",
            (SOURCE_ID,),
        ).fetchone()
        if source is None:
            raise ValueError("MobiData source metadata is missing from the inventory")
        for group in document["groups"]:
            group.pop("mobidata_matches", None)
            proposal = group.get("proposal")
            if not proposal or proposal.get("position_status") == "challenged_review":
                continue
            longitude, latitude = proposal["longitude"], proposal["latitude"]
            if not (
                math.isfinite(longitude)
                and math.isfinite(latitude)
                and -180 <= longitude <= 180
                and -85 <= latitude <= 85
            ):
                continue
            latitude_delta = math.degrees(MATCH_RADIUS_M / EARTH_RADIUS_M)
            longitude_delta = latitude_delta / math.cos(
                math.radians(abs(latitude) + latitude_delta)
            )
            rows = connection.execute(
                "SELECT source_id, record_key, group_id AS source_group_id, "
                "location_id, sign_code, longitude, latitude, orientation_deg, updated_at "
                "FROM traffic_sign_inventory WHERE source_id=? AND sign_code=? "
                "AND latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?",
                (
                    SOURCE_ID, group["sign_code"],
                    latitude - latitude_delta, latitude + latitude_delta,
                    longitude - longitude_delta, longitude + longitude_delta,
                ),
            )
            matches = []
            for row in rows:
                distance = distance_m(
                    (longitude, latitude), (row["longitude"], row["latitude"])
                )
                if distance > MATCH_RADIUS_M:
                    continue
                candidate = dict(row)
                candidate["distance_m"] = distance
                # The source allows 360 degrees, which is equivalent to north.
                orientation = candidate["orientation_deg"]
                if orientation is not None and not (
                    math.isfinite(orientation) and 0 <= orientation <= 360
                ):
                    candidate["orientation_deg"] = None
                matches.append(candidate)
            if matches:
                matches.sort(key=lambda row: (row["distance_m"], row["record_key"]))
                group["mobidata_matches"] = matches
    document["mobidata_reference"] = {
        **dict(source),
        "match_radius_m": MATCH_RADIUS_M,
        "match_basis": "exact_sign_code_and_distance_to_proposed_position",
        "orientation_basis": "source_GruppenAusrichtung_unconverted",
    }
    document["summary"]["groups_with_mobidata_matches"] = sum(
        bool(group.get("mobidata_matches")) for group in document["groups"]
    )
    return document
