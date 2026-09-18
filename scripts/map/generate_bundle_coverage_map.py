#!/usr/bin/env python3
"""Generate the README coverage map from the checked-in bundle catalog.

The catalog stores buffered Geofabrik extract polygons for every supported
bundle. This renderer intentionally uses only the Python standard library so
the README asset can be refreshed without adding a plotting dependency.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "shared/RegionalCoverage/catalog-v1.json"
TARGETS = ROOT / "iphone/SpeedConsumerApp/BundleTargets.top10.json"
OUTPUT = ROOT / "docs/bundle-coverage-map.svg"

TSR_COUNTRIES = {"BE", "CH", "DE", "FR", "NL"}
MAIN_VIEW = (-7.0, 17.5, 41.0, 56.5)
WIDTH, HEIGHT = 1600, 1000
MAP = (70, 112, 1100, 850)


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def project(lon: float, lat: float) -> tuple[float, float]:
    lon_min, lon_max, lat_min, lat_max = MAIN_VIEW
    x0, y0, x1, y1 = MAP
    x = x0 + (lon - lon_min) / (lon_max - lon_min) * (x1 - x0)
    y = y1 - (lat - lat_min) / (lat_max - lat_min) * (y1 - y0)
    return x, y


def in_main_view(entry: dict) -> bool:
    if entry["country"] in {"IS", "RO", "SE"} or entry["region"] in {
        "guadeloupe", "martinique", "mayotte", "reunion"
    }:
        return False
    lon_min, lon_max, lat_min, lat_max = MAIN_VIEW
    west, south, east, north = entry["bbox"]
    return east >= lon_min and west <= lon_max and north >= lat_min and south <= lat_max


def simplify_ring(ring: list[list[float]], max_points: int = 170) -> list[list[float]]:
    if len(ring) <= max_points:
        return ring
    step = (len(ring) - 1) / (max_points - 1)
    selected = [ring[round(i * step)] for i in range(max_points - 1)]
    selected.append(ring[-1])
    return selected


def path_for_entry(entry: dict) -> str:
    commands: list[str] = []
    for polygon in entry["polygons"]:
        for ring in polygon:
            points = simplify_ring(ring)
            if len(points) < 4:
                continue
            projected = [project(point[0], point[1]) for point in points]
            commands.append("M " + " ".join(f"{x:.1f},{y:.1f}" for x, y in projected) + " Z")
    return " ".join(commands)


def text(x: float, y: float, value: str, *, size: int = 16, weight: int = 500,
         fill: str = "#12243a", anchor: str = "start", family: str = "Arial") -> str:
    return (f'<text x="{x}" y="{y}" fill="{fill}" font-family="{family}" '
            f'font-size="{size}px" font-weight="{weight}" text-anchor="{anchor}">{esc(value)}</text>')


def rounded_label(x: float, y: float, label: str, *, fill: str, text_fill: str = "#ffffff",
                  width: int | None = None) -> str:
    width = width or max(66, 17 + len(label) * 8)
    return (f'<rect x="{x}" y="{y - 22}" width="{width}" height="30" rx="15" fill="{fill}"/>'
            + text(x + width / 2, y - 1, label, size=13, weight=750, fill=text_fill, anchor="middle"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--targets", type=Path, default=TARGETS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    targets = json.loads(args.targets.read_text(encoding="utf-8"))
    entries = catalog["regions"]
    target_count = sum(len(country["regions"]) for country in targets["countries"])
    if target_count != len(entries):
        raise SystemExit(f"target/catalog bundle count mismatch: {target_count} != {len(entries)}")

    main_entries = [entry for entry in entries if in_main_view(entry)]
    off_map = [entry for entry in entries if entry not in main_entries]
    main_tsr = [entry for entry in main_entries if entry["country"] in TSR_COUNTRIES]

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">',
        '<title id="title">YouSpeed map-bundle coverage in Western Europe</title>',
        '<desc id="desc">All 51 supported map bundles are shown. Coral marks bundles in countries with an embedded on-device traffic-sign-recognition pack.</desc>',
        '<defs>',
        '<filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="7" stdDeviation="10" flood-color="#0b1d32" flood-opacity="0.12"/></filter>',
        '<pattern id="grid" width="80" height="80" patternUnits="userSpaceOnUse"><path d="M 80 0 L 0 0 0 80" fill="none" stroke="#bfd0df" stroke-opacity="0.34" stroke-width="1"/></pattern>',
        '</defs>',
        '<rect width="1600" height="1000" fill="#f7fafc"/>',
        '<rect x="0" y="0" width="1600" height="1000" fill="#eaf2f7"/>',
        '<rect x="0" y="0" width="1600" height="1000" fill="url(#grid)" opacity="0.34"/>',
        '<rect x="42" y="36" width="1516" height="928" rx="28" fill="#ffffff" filter="url(#shadow)"/>',
        text(78, 86, "YouSpeed bundle coverage", size=30, weight=800),
        text(78, 110, "Western Europe · current checked-in release targets", size=15, weight=500, fill="#60758b"),
        f'<rect x="{MAP[0]}" y="{MAP[1]}" width="{MAP[2]-MAP[0]}" height="{MAP[3]-MAP[1]}" rx="22" fill="#dcecf3" stroke="#c3d7e4" stroke-width="2"/>',
    ]

    # Light coordinate guides make the projection legible without competing
    # with the bundle shapes.
    for lon in [-5, 0, 5, 10, 15]:
        x, _ = project(lon, MAIN_VIEW[2])
        svg.append(f'<path d="M {x:.1f} {MAP[1]} V {MAP[3]}" stroke="#aac2d1" stroke-opacity="0.32" stroke-dasharray="3 8"/>')
        svg.append(text(x + 4, MAP[3] - 12, f"{lon}°", size=11, fill="#7590a3"))
    for lat in [42, 46, 50, 54]:
        _, y = project(MAIN_VIEW[0], lat)
        svg.append(f'<path d="M {MAP[0]} {y:.1f} H {MAP[2]}" stroke="#aac2d1" stroke-opacity="0.32" stroke-dasharray="3 8"/>')
        svg.append(text(MAP[0] + 10, y - 5, f"{lat}°N", size=11, fill="#7590a3"))

    for entry in main_entries:
        fill = "#e77657" if entry["country"] in TSR_COUNTRIES else "#2b8cbe"
        stroke = "#ffffff"
        svg.append(f'<path d="{path_for_entry(entry)}" fill="{fill}" fill-opacity="0.88" stroke="{stroke}" stroke-width="1.15" stroke-linejoin="round"/>')

    # Country-level labels keep the map readable even though the boundary
    # geometry is intentionally bundle-level.
    country_labels = [
        ("FR", 1.5, 46.6, "FR · 26 bundles + TSR", "#e77657", 164),
        ("DE", 10.2, 51.2, "DE · 16 bundles + TSR", "#e77657", 164),
        ("BE", 4.4, 50.9, "BE · TSR", "#e77657", 86),
        ("NL", 5.0, 52.7, "NL · TSR", "#e77657", 86),
        ("CH", 8.3, 46.4, "CH · TSR", "#e77657", 86),
    ]
    for _, lon, lat, label, fill, width in country_labels:
        x, y = project(lon, lat)
        svg.append(rounded_label(x, y, label, fill=fill, width=width))

    for lon, lat, label in [(6.1, 49.75, "LU"), (9.55, 47.16, "LI"), (7.50, 43.72, "MC")]:
        x, y = project(lon, lat)
        svg.append(rounded_label(x, y, label, fill="#2b8cbe", width=50))

    svg.extend([
        text(78, 939, "Coral = an embedded on-device TSR pack; blue = map bundle coverage.", size=13, weight=600, fill="#4f667b"),
        text(78, 957, "Boundaries are buffered Geofabrik extract coverage, not authoritative national borders.", size=11, weight=500, fill="#7890a2"),
        '<g transform="translate(1150,112)">',
        '<rect width="365" height="852" rx="22" fill="#f6f9fb" stroke="#dce6ed"/>',
        text(30, 46, "At a glance", size=22, weight=800),
        text(30, 74, f"{len(entries)} supported bundles", size=16, weight=750, fill="#1f5f87"),
        text(30, 96, f"{len(main_entries)} in the main viewport", size=13, weight=500, fill="#60758b"),
        '<line x1="30" y1="122" x2="335" y2="122" stroke="#dce6ed"/>',
        '<circle cx="42" cy="153" r="8" fill="#2b8cbe"/>',
        text(62, 159, "Map bundle coverage", size=14, weight=650),
        '<circle cx="42" cy="184" r="8" fill="#e77657"/>',
        text(62, 190, "Map bundle + on-device TSR", size=14, weight=650),
        text(30, 236, "Bundle groups", size=16, weight=800),
        text(30, 267, "DE", size=14, weight=800, fill="#e77657"),
        text(82, 267, "16 regional bundles", size=14, weight=550),
        text(30, 294, "FR", size=14, weight=800, fill="#e77657"),
        text(82, 294, "26 regional bundles", size=14, weight=550),
        text(30, 321, "BE · NL · CH", size=14, weight=800, fill="#e77657"),
        text(140, 321, "1 bundle each", size=14, weight=550),
        text(30, 348, "LU · LI · MC", size=14, weight=800, fill="#2b8cbe"),
        text(140, 348, "1 bundle each", size=14, weight=550),
        text(30, 399, "Also supported outside the", size=16, weight=800),
        text(30, 421, "main Western Europe viewport", size=16, weight=800),
    ])

    off_map_names = [
        ("IS", "Iceland"), ("SE", "Sweden"), ("RO", "Romania"),
        ("FR", "Guadeloupe · Martinique · Mayotte · Réunion"),
    ]
    y = 461
    for code, label in off_map_names:
        color = "#e77657" if code == "FR" else "#2b8cbe"
        svg.append(f'<rect x="30" y="{y-17}" width="42" height="26" rx="13" fill="{color}"/>')
        svg.append(text(51, y + 1, code, size=11, weight=800, fill="#ffffff", anchor="middle"))
        svg.append(text(86, y + 1, label, size=13, weight=550))
        y += 34

    svg.extend([
        '<line x1="30" y1="625" x2="335" y2="625" stroke="#dce6ed"/>',
        text(30, 660, "TSR status", size=16, weight=800),
        text(30, 689, "Embedded packs are field-test /", size=13, weight=500, fill="#60758b"),
        text(30, 708, "evaluation or shadow artifacts;", size=13, weight=500, fill="#60758b"),
        text(30, 727, "production rollout remains gated", size=13, weight=500, fill="#60758b"),
        text(30, 764, "Generated from:", size=12, weight=800, fill="#7890a2"),
        text(30, 785, "shared/RegionalCoverage/catalog-v1.json", size=11, weight=500, fill="#60758b"),
        text(30, 803, "and BundleTargets.top10.json", size=11, weight=500, fill="#60758b"),
        '</g>',
        '</svg>',
    ])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(svg) + "\n", encoding="utf-8")
    print(f"Wrote {len(entries)} bundles ({len(main_entries)} in viewport, {len(off_map)} in inset list) to {args.output}")


if __name__ == "__main__":
    main()
