#!/usr/bin/env python3
"""Build the checked-in official geometry subset used by the coverage map.

The bundle catalog deliberately retains Geofabrik extract coverage for mobile
bundle routing. The documentation map has a different concern: showing the
actual administrative/statistical regions. Eurostat/GISCO NUTS 2013 is used
because it still contains the former French regions represented by the
current release targets.

Download the three source files from the URLs recorded in the output metadata
and pass them with --countries, --nuts-level1, and --nuts-level2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "shared/RegionalCoverage/catalog-v1.json"
OUTPUT = ROOT / "shared/RegionalCoverage/official-regions-v1.json"

COUNTRIES_URL = (
    "https://gisco-services.ec.europa.eu/distribution/v2/countries/geojson/"
    "CNTR_RG_10M_2013_4326.geojson"
)
NUTS_LEVEL1_URL = (
    "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/"
    "NUTS_RG_10M_2013_4326_LEVL_1.geojson"
)
NUTS_LEVEL2_URL = (
    "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/"
    "NUTS_RG_10M_2013_4326_LEVL_2.geojson"
)

FRANCE_NUTS2 = {
    "alsace": "FR42",
    "aquitaine": "FR61",
    "auvergne": "FR72",
    "basse-normandie": "FR25",
    "bourgogne": "FR26",
    "bretagne": "FR52",
    "centre": "FR24",
    "champagne-ardenne": "FR21",
    "corse": "FR83",
    "franche-comte": "FR43",
    "guadeloupe": "FRA1",
    "haute-normandie": "FR23",
    "ile-de-france": "FR10",
    "languedoc-roussillon": "FR81",
    "limousin": "FR63",
    "lorraine": "FR41",
    "martinique": "FRA2",
    "mayotte": "FRA5",
    "midi-pyrenees": "FR62",
    "nord-pas-de-calais": "FR30",
    "pays-de-la-loire": "FR51",
    "picardie": "FR22",
    "poitou-charentes": "FR53",
    "provence-alpes-cote-d-azur": "FR82",
    "reunion": "FRA4",
    "rhone-alpes": "FR71",
}

GERMANY_NUTS1 = {
    "baden-wuerttemberg": "DE1",
    "bayern": "DE2",
    "berlin": "DE3",
    "brandenburg": "DE4",
    "bremen": "DE5",
    "hamburg": "DE6",
    "hessen": "DE7",
    "mecklenburg-vorpommern": "DE8",
    "niedersachsen": "DE9",
    "nordrhein-westfalen": "DEA",
    "rheinland-pfalz": "DEB",
    "saarland": "DEC",
    "sachsen": "DED",
    "sachsen-anhalt": "DEE",
    "schleswig-holstein": "DEF",
    "thueringen": "DEG",
}


def geometry_coordinates(geometry: dict) -> list[list[list[float]]]:
    if geometry["type"] == "Polygon":
        polygons = [geometry["coordinates"]]
    elif geometry["type"] == "MultiPolygon":
        polygons = geometry["coordinates"]
    else:
        raise ValueError(f"Unsupported geometry type: {geometry['type']}")
    if not polygons:
        raise ValueError("Empty geometry")
    for polygon in polygons:
        for ring in polygon:
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("Rings must be closed and contain at least three vertices")
            for point in ring:
                if len(point) != 2 or not all(math.isfinite(value) for value in point):
                    raise ValueError("Invalid coordinate")
    return polygons


def load_features(path: Path, key: str) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    features = {}
    for feature in data["features"]:
        value = feature["properties"].get(key)
        if value:
            features[value] = feature
    return features


def bbox(polygons: list[list[list[float]]]) -> list[float]:
    points = [point for polygon in polygons for ring in polygon for point in ring]
    return [
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--countries", type=Path, required=True)
    parser.add_argument("--nuts-level1", type=Path, required=True)
    parser.add_argument("--nuts-level2", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    countries = load_features(args.countries, "CNTR_ID")
    nuts1 = load_features(args.nuts_level1, "NUTS_ID")
    nuts2 = load_features(args.nuts_level2, "NUTS_ID")
    regions = []

    for catalog_entry in catalog["regions"]:
        country = catalog_entry["country"]
        region = catalog_entry["region"]
        if country == "FR":
            source_id = FRANCE_NUTS2[region]
            source = nuts2
            level = 2
        elif country == "DE":
            source_id = GERMANY_NUTS1[region]
            source = nuts1
            level = 1
        else:
            source_id = country
            source = countries
            level = 0
        feature = source.get(source_id)
        if feature is None:
            raise SystemExit(f"Missing official geometry {source_id} for {catalog_entry['id']}")
        polygons = geometry_coordinates(feature["geometry"])
        properties = feature["properties"]
        regions.append({
            "id": catalog_entry["id"],
            "source_id": source_id,
            "level": level,
            "name": properties.get("NAME_LATN") or properties.get("NAME_ENGL"),
            "bbox": bbox(polygons),
            "polygons": polygons,
        })

    result = {
        "schema_version": 1,
        "source": "Eurostat/GISCO",
        "source_files": [
            {"url": COUNTRIES_URL, "sha256": hashlib.sha256(args.countries.read_bytes()).hexdigest()},
            {"url": NUTS_LEVEL1_URL, "sha256": hashlib.sha256(args.nuts_level1.read_bytes()).hexdigest()},
            {"url": NUTS_LEVEL2_URL, "sha256": hashlib.sha256(args.nuts_level2.read_bytes()).hexdigest()},
        ],
        "source_dataset": "NUTS 2013 / country boundaries, 1:10 million, EPSG:4326",
        "attribution": "© EuroGeographics for the administrative boundaries",
        "boundary_kind": "official_administrative_and_statistical_boundaries",
        "regions": regions,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(regions)} official region geometries to {args.output}")


if __name__ == "__main__":
    main()
