#!/usr/bin/env python3
"""Profile downloaded BEMaS feeds for the live-service design; no network or writes.

Inputs are roadworks.geojson, roadworks.cifs.json, roadworks.datex2.xml,
catalogue.json and curl -D headers named geojson.headers/datex.headers/cifs.headers.
This is a research tool, not the production ingestion adapter.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import gzip
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory
    ns = {"d": "http://datex2.eu/schema/2/2_0"}
    urls = {
        "geojson": "https://api.mobidata-bw.de/datasets/traffic/roadworks/roadworks_geojson.json",
        "cifs": "https://api.mobidata-bw.de/datasets/traffic/roadworks/roadworks_cifs.json",
        "datex": "https://api.mobidata-bw.de/datasets/traffic/roadworks/roadworks_svzbw.datex2.xml",
    }
    names = {"geojson": "roadworks.geojson", "cifs": "roadworks.cifs.json", "datex": "roadworks.datex2.xml"}
    headers = {}
    files = {}
    for key, name in names.items():
        lines = (root / (key + ".headers")).read_text().splitlines()
        headers[key] = {k.lower(): v.strip() for line in lines if ":" in line for k, v in [line.split(":", 1)]}
        raw = (root / name).read_bytes()
        files[key] = {"url": urls[key], "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "headers": headers[key]}
    raw_geo = (root / names["geojson"]).read_bytes()
    features = json.loads(raw_geo)["features"]
    cifs = json.loads((root / names["cifs"]).read_bytes())
    cifs_map = {r["id"]: r for r in cifs["incidents"]}
    xml = ET.fromstring((root / names["datex"]).read_bytes())
    records = xml.findall(".//d:situationRecord", ns)
    record_map = {r.get("id"): r for r in records}
    as_of = parsedate_to_datetime(headers["geojson"]["date"]).astimezone(timezone.utc)
    times = Counter()
    geometry_issues = []
    coordinates = []
    good_coordinates = []
    joined = Counter()
    missing_joins = []
    keys = Counter()
    signatures = Counter()
    line_comparisons = Counter()
    for feature in features:
        props = feature["properties"]
        keys.update(props.keys())
        start, end = (datetime.fromisoformat(props[k]) for k in ("starttime", "endtime"))
        times["invalid" if end <= start else "within_outer_window" if start <= as_of < end else "future" if as_of < start else "expired"] += 1
        geo = feature["geometry"]
        points = geo["coordinates"] if geo["type"] == "LineString" else [geo["coordinates"]]
        coordinates.extend(points)
        # Broad regional sanity envelope, deliberately not a state boundary.
        outside = [p for p in points if not (7 <= p[0] <= 11 and 47 <= p[1] <= 50)]
        if outside:
            issue = {"id": props["id"], "type": geo["type"], "outside_coordinates": outside}
            record = record_map.get(props["id"].rsplit(".", 1)[0])
            if geo["type"] == "Point" and record is not None:
                display = record.find(".//d:locationForDisplay", ns)
                if display is not None:
                    named = [float(display.findtext("d:longitude", namespaces=ns)), float(display.findtext("d:latitude", namespaces=ns))]
                    issue.update({"datex_record_id": record.get("id"), "datex_named_lon_lat": named, "equals_reversed_published_point": named == list(reversed(points[0]))})
            geometry_issues.append(issue)
        else:
            good_coordinates.extend(points)
        if geo["type"] == "LineString" and props["id"] in cifs_map:
            values = [float(v) for v in cifs_map[props["id"]]["location"]["polyline"].split()]
            pairs = [[values[i + 1], values[i]] for i in range(0, len(values), 2)]
            line_comparisons["matched" if pairs == points else "mismatched"] += 1
        # Hypothesis checked against this snapshot, not an upstream identity contract.
        record = record_map.get(props["id"].rsplit(".", 1)[0])
        if record is None:
            missing_joins.append(props["id"])
        else:
            joined["matched"] += 1
            joined["operator_status_" + str(record.findtext("d:operatorActionStatus", namespaces=ns))] += 1
            for label, tags in {
                "with_valid_periods": ["validPeriod"],
                "with_recurrence": ["recurringTimePeriodOfDay", "recurringDayWeekMonthPeriod"],
                "with_exceptions": ["exceptionPeriod"],
            }.items():
                joined[label] += any(record.find(".//d:" + tag, ns) is not None for tag in tags)
        signature = {**feature, "properties": {k: v for k, v in props.items() if k != "id"}}
        signatures[json.dumps(signature, sort_keys=True)] += 1
    catalogue = json.loads((root / "catalogue.json").read_bytes())["result"]
    bbox = lambda points: [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]
    report = {
        "as_of_utc": as_of.isoformat(),
        "method": "One public snapshot per format; temporal counts use outer intervals only. No longitudinal freshness measurement or production ingestion acceptance.",
        "files": files,
        "catalogue": {k: catalogue.get(k) for k in ["title", "author", "license_id", "license_url", "metadata_modified"]},
        "geojson": {
            "features": len(features),
            "unique_ids": len({f["properties"]["id"] for f in features}),
            "geometry_types": dict(Counter(f["geometry"]["type"] for f in features)),
            "property_presence": dict(keys),
            "empty_properties": {k: sum(f["properties"].get(k) in (None, "") for f in features) for k in keys},
            "types": dict(Counter(f["properties"]["type"] for f in features)),
            "directions": dict(Counter(f["properties"]["direction"] for f in features)),
            "outer_interval_counts": dict(times),
            "vertices": len(coordinates),
            "bbox_as_published": bbox(coordinates),
            "bbox_without_suspect_features": bbox(good_coordinates),
            "regional_geometry_issues": geometry_issues,
            "duplicate_features_excluding_id": sum(n - 1 for n in signatures.values()),
            "generic_bauphase_descriptions": sum(f["properties"]["description"] == "Bauphase" for f in features),
            "generic_gemeindestrasse_labels": sum(f["properties"]["street"] == "Gemeindestraße" for f in features),
            "gzip_bytes_mtime_zero": len(gzip.compress(raw_geo, mtime=0)),
        },
        "cifs": {"incidents": len(cifs["incidents"]), "timestamp_raw": cifs.get("timestamp"), "id_set_equal_to_geojson": {r["id"] for r in cifs["incidents"]} == {f["properties"]["id"] for f in features}, "line_geometry_comparison": dict(line_comparisons)},
        "datex": {
            "root_namespace": xml.tag,
            "publication_time": xml.findtext(".//d:publicationTime", namespaces=ns),
            "situations": len(xml.findall(".//d:situation", ns)),
            "records": len(records),
            "record_types": dict(Counter(r.get("{http://www.w3.org/2001/XMLSchema-instance}type") for r in records)),
            "joined_geojson": dict(joined),
            "missing_candidate_joins": missing_joins,
            "main_speed_limits": dict(Counter(e.text for e in xml.findall(".//d:mainSpeedLimit", ns))),
        },
    }
    conditional = root / "conditional.headers"
    if conditional.exists():
        report["conditional_geojson_response"] = conditional.read_text().splitlines()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
