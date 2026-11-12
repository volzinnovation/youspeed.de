"""Batch the two city reviews into an owner-only MapServer WFS snapshot."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import fiona
from shapely.geometry import Point, shape

from scripts.inspector.build_place_sign_review import (
    MAX_PRIVATE_INPUT_BYTES, METRIC, municipality_boundary, project, read_private,
)

CITIES = {"08235033": "Bad Herrenalb", "08231000": "Pforzheim"}
LAYER = "verkehrszeichen"
FIELDS = {
    "id": "str", "stvo_nr": "str", "text": "str", "ost": "float", "nord": "float",
    "hoehe": "float", "hoehe_ueber_boden": "float", "azimut": "float",
    "url_infra3d": "str", "datum": "str", "img": "str", "stack_id": "str",
    "stack_order": "int", "parent_sign_id": "str", "gemeinde_ags": "str",
    "kreis_ags": "str", "stadtbezirk_id": "str", "sighting_count": "int",
    "source_types": "str", "position_status": "str", "first_discovered_on": "str",
}
MAPFILE = """MAP
  NAME "streetshots_signs"
  STATUS ON
  EXTENT 0 4000000 1100000 6500000
  UNITS METERS
  PROJECTION
    "EPSG:25832"
  END
  OUTPUTFORMAT
    NAME "geojson"
    DRIVER "OGR/GEOJSON"
    MIMETYPE "application/geo+json"
    FORMATOPTION "FORM=SIMPLE"
    FORMATOPTION "STORAGE=memory"
    FORMATOPTION "LCO:RFC7946=YES"
  END
  WEB
    METADATA
      "wfs_enable_request" "GetCapabilities DescribeFeatureType GetFeature"
      "wfs_title" "Streetshots Verkehrszeichen"
      "wfs_abstract" "Privater Arbeitsstand. Position und Azimut sind geschätzt. Quellen: Streetshots und Panoramax."
      "wfs_accessconstraints" "Private"
      "wfs_namespace_prefix" "youspeed"
      "wfs_namespace_uri" "https://youspeed.de/ns/verkehrszeichen/1"
      "wfs_srs" "EPSG:25832 EPSG:4326"
      "wfs_getfeature_formatlist" "geojson"
      "wfs_use_default_extent_for_getfeature" "false"
      "wfs_maxfeatures" "5000"
    END
    VALIDATION
      "immutable" "true"
    END
  END
  LAYER
    NAME "verkehrszeichen"
    TYPE POINT
    STATUS ON
    CONNECTIONTYPE OGR
    CONNECTION "verkehrszeichen.gpkg"
    DATA "verkehrszeichen"
    PROJECTION
      "EPSG:25832"
    END
    METADATA
      "wfs_title" "Verkehrszeichen"
      "gml_featureid" "id"
      "gml_include_items" "{fields}"
      "gml_geometries" "msGeometry"
      "gml_msGeometry_type" "point"
      "gml_types" "auto"
    END
  END
END
"""


def utc_day(value):
    captured = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if captured.tzinfo is None:
        raise ValueError("capture timestamp must include a time zone")
    return captured.astimezone(timezone.utc).date().isoformat()


def features(document, ags, boundary, previous):
    counts = Counter()
    rows = []
    identifiers = set()
    for group in document["groups"]:
        identifier = group["id"]
        if not re.fullmatch(r"[0-9a-f]{32}", identifier) or identifier in identifiers:
            raise ValueError("invalid or duplicate sign group ID")
        identifiers.add(identifier)
        refinement = group.get("mobile_refinement") or {}
        refined = refinement.get("status") == "refined"
        pose = refinement["proposal"] if refined else group.get("proposal")
        if not pose:
            counts["unresolved"] += 1
            continue
        longitude, latitude = pose["longitude"], pose["latitude"]
        if not boundary.covers(Point(longitude, latitude)):
            counts["outside_municipality"] += 1
            continue
        panorama = group["observations"] + group.get("follow_on_observations", [])
        days = [utc_day(row["captured_at"]) for row in panorama]
        mobile_ids = set(refinement["mobile_evidence_ids"]) if refined else set()
        mobile = [row for row in group.get("mobile_observations", [])
                  if row["evidence_id"] in mobile_ids]
        if {row["evidence_id"] for row in mobile} != mobile_ids:
            raise ValueError("missing mobile dependencies for refined sign")
        days.extend(utc_day(row["captured_at"]) for row in mobile)
        # Discovery survives reprocessing as long as the group keeps its ID.
        first = min(days)
        if identifier in previous:
            first = min(first, previous[identifier])
        azimuth = pose.get("azimut_deg")
        if azimuth is not None and not math.isfinite(azimuth):
            raise ValueError("invalid sign azimuth")
        (east, north), _ = project([longitude], [latitude])[0]
        properties = dict.fromkeys(FIELDS)
        properties.update(
            id=identifier, stvo_nr=group["sign_code"], ost=east, nord=north,
            azimut=(azimuth + 180) % 360 if azimuth is not None else None,
            datum=max(days), first_discovered_on=first, gemeinde_ags=ags,
            kreis_ags=ags[:5] if ags else None, position_status=pose["position_status"],
            sighting_count=len({row["image_id"] for row in panorama}) + len(mobile_ids),
            source_types="panoramax,mobile" if mobile else "panoramax",
        )
        rows.append({"geometry": {"type": "Point", "coordinates": (east, north)},
                     "properties": properties})
        counts["features"] += 1
        counts["mobile_refined"] += bool(mobile)
        counts["missing_azimuth"] += azimuth is None
    return rows, dict(counts)


def previous_dates(target):
    if not target.exists():
        return {}
    with fiona.open(target, layer=LAYER) as source:
        return {row["properties"]["id"]: row["properties"]["first_discovered_on"]
                for row in source}


def build(directory, boundary_file, reviews):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_mode & 0o077:
        raise ValueError("WFS output directory must be owner-only")
    target = directory / f"{LAYER}.gpkg"
    previous = previous_dates(target)
    rows, summary = [], {}
    for ags, path in reviews.items():
        document = json.loads(read_private(path, MAX_PRIVATE_INPUT_BYTES))
        boundary = municipality_boundary(boundary_file, ags)
        if document["place"]["name"] != CITIES[ags] or (
            "boundary_wgs84" not in document["place"]
            or not shape(document["place"]["boundary_wgs84"]).equals(shape(boundary))
        ):
            raise ValueError(f"review must cover the requested municipality {ags}")
        city_rows, summary[ags] = features(document, ags, shape(boundary), previous)
        if not city_rows:
            raise ValueError(f"empty snapshot for municipality {ags}")
        rows.extend(city_rows)
    if len({row["properties"]["id"] for row in rows}) != len(rows):
        raise ValueError("sign group is present in both municipalities")

    write_snapshot(directory, rows)
    return summary


def write_snapshot(directory, rows):
    """Write already resolved features; generic scopes need no invented municipality."""
    directory = Path(directory).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_mode & 0o077:
        raise ValueError("WFS output directory must be owner-only")
    if len({row["properties"]["id"] for row in rows}) != len(rows):
        raise ValueError("duplicate sign feature ID")
    target = directory / f"{LAYER}.gpkg"
    with TemporaryDirectory(dir=directory) as working:
        working = Path(working)
        package = working / target.name
        with fiona.open(package, "w", driver="GPKG", layer=LAYER, crs=METRIC,
                        schema={"geometry": "Point", "properties": FIELDS}) as sink:
            sink.writerecords(rows)
        with fiona.open(package, layer=LAYER) as source:
            if len(source) != len(rows) or dict(source.schema["properties"]) != FIELDS:
                raise ValueError("incomplete sign snapshot")
        package.chmod(0o600)

        mapfile = working / f"{LAYER}.map"
        mapfile.write_text(MAPFILE.format(fields=",".join(FIELDS)))
        config = working / "mapserver.conf"
        config.write_text(
            "CONFIG\n  ENV\n"
            f"    MS_MAPFILE {json.dumps(str(directory / mapfile.name), ensure_ascii=False)}\n"
            '    MS_MAP_NO_PATH "1"\n    MS_MODE "WFS"\n'
            '    MS_ERRORFILE "stderr"\n    PROJ_NETWORK "OFF"\n  END\nEND\n'
        )
        for path in (mapfile, config):
            path.chmod(0o600)
            os.replace(path, directory / path.name)
        os.replace(package, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundaries", required=True, type=Path)
    parser.add_argument("--bad-herrenalb", required=True, type=Path)
    parser.add_argument("--pforzheim", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.output_directory.resolve(), args.boundaries, {
        "08235033": args.bad_herrenalb, "08231000": args.pforzheim,
    }), sort_keys=True))


if __name__ == "__main__":
    main()
