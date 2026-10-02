#!/usr/bin/env python3
"""Review every *actual* national classifier output, independently of artwork.

Run with --write to reconcile bundled manifests/catalogs and regenerate the
review ledger. Without it, fail on drift. No classifier weights are modified.
The original upstream/ASTRA inventories are evidence, not semantic authority.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COUNTRIES = ("DE", "BE", "FR", "NL", "CH")
SOURCES = {
    "DE": "https://www.gesetze-im-internet.de/stvo_2013/anlage_2.html",
    "BE": "https://www.codedelaroute.be/fr/reglementation/1975120109~hra8v386pu",
    "FR": "https://www.legifrance.gouv.fr/loda/id/JORFTEXT000000829916/2024-04-22",
    "NL": "https://wetten.overheid.nl/BWBR0004825/#Bijlage1",
    "CH": "https://www.astra.admin.ch/fr/signaux",
}


def semantic(label: str, country: str = "") -> dict:
    """Allowlisted speed actions. A generic ':end' suffix never ends speed."""
    token = label.strip().lower()
    if country == "FR" or re.fullmatch(r"b(?:14|33)-\d+", token):
        french = re.fullmatch(r"b(14|33)-(\d+)", token)
        if french:
            token = f"maxspeed:{french[2]}" + (":end" if french[1] == "33" else "")
        token = {"b30": "zone:30", "b51": "zone:30:end", "b31": "no:end",
                 "b52": "zone:20", "b53": "zone:20:end",
                 "b54": "zone:pedestrian", "b55": "zone:pedestrian:end",
                 "eb10": "city:start", "eb20": "city:end",
                 "c208": "motorway:end", "c108": "trunk:end"}.get(token, token)
    if country == "CH":
        token = {"zone:calm": "zone:20", "zone:calm:end": "zone:20:end"}.get(token, token)
    numeric = re.fullmatch(r"(maxspeed|zone):(\d+)(:end)?", token)
    if numeric and 5 <= int(numeric[2]) <= 200:
        if numeric[3]:
            return {"kind": "zone_end" if numeric[1] == "zone" else "restriction_end", "value": int(numeric[2])}
        return {"kind": "zone_start" if numeric[1] == "zone" else "maximum_speed", "value": int(numeric[2]), "unit": "km/h"}
    kinds = {
        "maxspeed:end": "restriction_end", "no:end": "restriction_end",
        "motorway:end": "restriction_end", "trunk:end": "restriction_end",
        "zone:end": "zone_end", "city:start": "city_entry", "city:end": "city_exit",
        "city_limit:start": "city_entry", "city_limit:end": "city_exit",
        "built_up_area_start": "city_entry", "built_up_area_end": "city_exit",
        "zone:pedestrian": "pedestrian_zone_start", "zone:pedestrian:end": "pedestrian_zone_end",
        "pedestrian_zone:start": "pedestrian_zone_start", "pedestrian_zone:end": "pedestrian_zone_end",
    }
    return {"kind": kinds.get(token, "unknown")}


def mappings(labels: list[str], country: str, previous: list[dict]) -> list[dict]:
    old = {entry["class_id"]: entry for entry in previous}
    return [{**old.get(label, {"class_id": label, "label": label, "threshold": 0.70}),
             "semantic": semantic(label, country)} for label in labels]


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def encoded(value: dict) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def reconcile_catalog(catalog: dict) -> dict:
    result = copy.deepcopy(catalog)
    country = result["country"]
    signs = {entry["class_id"]: entry for entry in result["signs"]}
    # Upstream spelling differences must not discard an exact reviewed artwork.
    aliases = {
        "BE": {"hazard:left_turn": "hazard:turn_left", "hazard:right_turn": "hazard:turn_right"},
        "NL": {"hazard:left_turn": "hazard:turn_left", "hazard:right_turn": "hazard:turn_right",
               "hazard:intersection_left": "hazard:intersection:left", "hazard:intersection_right": "hazard:intersection:right",
               "hazard:zigzag_left": "hazard:zigzag:left", "noexit": "no_exit",
               "no_overtaking:hgv:end": "no_overtaking:end:hgv", "bus:end": "bus:stop",
               "priority:start": "priority:start"},
    }.get(country, {})
    if country in {"BE", "NL"}:
        root = ROOT / f"shared/tsr/sign-pictograms/national/{country}"
        selections = load(root / "selection.json")["entries"]
        artworks = {a["asset_id"]: a for a in load(root / "manifest.json")["artworks"]}
        for label, source in aliases.items():
            if label not in result["class_labels"]:
                continue
            entry = next((e for e in selections if e["semantic_id"] == source), None)
            if country == "NL" and label == "priority:start":
                entry = next(e for e in selections if e["sign_code"] == "B01")
            if entry is None:
                continue
            art = artworks[entry["artwork_id"]]
            signs[label] = {"class_id": label, "sign_code": entry["sign_code"],
                "image_path": "tsr/sign-pictograms/" + art["png_path"], "display_eligible": True,
                "artwork_id": art["asset_id"], "label": {lang: f"{entry['sign_code']} — {label}" for lang in ("en", "de", "fr", "nl")},
                "notes": "Exact label spelling/country-code reconciliation; mapping-review-v1.json.",
                "source_provenance": {key: art[key] for key in ("commons_title", "license", "license_source_url", "original_sha256", "png_sha256")}}
    generic_values = {"maxheight", "maxwidth", "maxlength", "maxweight", "maxaxleweight", "min_distance", "min_speed", "min_speed:end", "speed", "speed:end", "maxspeed:end", "hazard:incline", "hazard:incline:up", "hazard:include:down"}
    french_values = {"B11", "B12", "B13", "B13a", "B17", "C4a", "C4b", "B25", "B43", "A2a", "A2b"}
    for label in result["class_labels"]:
        sign = signs.setdefault(label, {"class_id": label, "sign_code": None, "image_path": None,
            "display_eligible": False, "label": {lang: label for lang in ("en", "de", "fr", "nl")},
            "notes": "No reviewed artwork for this actual model label; speed actions do not depend on artwork."})
        if label in generic_values or (country == "FR" and label in french_values):
            sign.update(image_path=None, display_eligible=False,
                notes="Model identifies the sign family, not its printed value. Do not display a fabricated number; maximum-speed ends use the national unnumbered end pictogram.")
        if country == "CH" and label == "zone:no_parking:end":
            sign.update(image_path=None, display_eligible=False,
                notes="ASTRA source 2.59.2 (D+F).eps depicts end of a 30 zone, not end of parking restrictions. No faithful parking-zone-end asset is available. No speed action.")
        if country == "CH" and label in {"hazard:horse", "no_exit:car"}:
            sign.update(image_path=None, display_eligible=False,
                notes={"hazard:horse": "ASTRA 1.24.eps shows wild animals (deer), not horses. No faithful horse-warning asset is available.",
                       "no_exit:car": "ASTRA 4.10 is water protection, not a dead end with exceptions (4.09.1). No faithful model-linked asset is available."}[label])
        if country == "BE" and label == "maxheight":
            sign["sign_code"] = "C29"
            sign["notes"] = "Current Belgian C29 is height; C27 is width. Generic classifier does not identify metres; no numeric pictogram displayed."
        if country == "FR" and label in {"C107", "C207", "B41"}:
            meaning = {"C107": "motorroad entry", "C207": "motorway entry", "B41": "end of mandatory footpath"}[label]
            sign["label"] = {lang: f"{label} — {meaning}" for lang in ("en", "de", "fr", "nl")}
            sign["notes"] = "Corrected against the French sign regulation; this is not a speed-end action."
    result["signs"] = list(signs.values())
    return result


def run(write: bool) -> list[str]:
    pending: dict[Path, bytes] = {}
    ledger = {"schema_version": 1, "reviewed_at": "2026-09-23", "scope": "All 820 ordered classifier outputs in DE/BE/FR/NL/CH; semantic and artwork contract audit, not a visual model accuracy evaluation.", "countries": []}
    for country in COUNTRIES:
        cat_path = ROOT / f"shared/tsr/prolix-{country.lower()}-class-catalog-v1.json"
        catalog = reconcile_catalog(load(cat_path))
        labels = catalog["class_labels"]
        pending[cat_path] = encoded(catalog)
        platform_mappings = []
        for parent in ("iphone/SpeedConsumerApp/TSRModelPacks", "android/app/src/main/assets/tsr"):
            path = ROOT / parent / f"{country}.panoramax-bootstrap.tsrmodelpack/manifest.json"
            pack = load(path)
            pack["class_mapping"] = mappings(labels, country, pack["class_mapping"])
            if country == "CH":
                # The reused proposal detector keeps its original DE inventory;
                # CH classifier data is separate. Neither stage is calibrated.
                pack["lineage"]["dataset_inventory_sha256s"] = list(dict.fromkeys([
                    pack["calibration"]["dataset_sha256"],
                    *[a["calibration_dataset_sha256"] for a in pack["detector"]["artifacts"]],
                ]))
            platform_mappings.append(pack["class_mapping"])
            pending[path] = encoded(pack)
        assert platform_mappings[0] == platform_mappings[1], country
        rows = []
        signs_by_label = {sign["class_id"]: sign for sign in catalog["signs"]}
        for sign in [signs_by_label[label] for label in labels]:
            label = sign["class_id"]
            meaning = semantic(label, country)
            rows.append({"class_id": label, "semantic": meaning, "sign_code": sign.get("sign_code"),
                "presentation": "national_pictogram" if sign["display_eligible"] else "numeric_speed" if meaning["kind"] in {"maximum_speed", "zone_start"} else "national_end_pictogram" if label == "maxspeed:end" or label.startswith("B33-") else "unavailable",
                "image_path": sign.get("image_path"),
                "limitation": sign.get("notes") if not sign["display_eligible"] else None})
        ledger["countries"].append({"country": country, "official_reference": SOURCES[country],
            "classifier_checkpoint_sha256": catalog["classifier_checkpoint_sha256"],
            "classifier_output_count": len(labels), "speed_action_count": sum(semantic(l, country)["kind"] != "unknown" for l in labels),
            "runtime_scope": "evaluation_only_existing_rollout_gates_unchanged" if country == "CH" else "bundled_evaluation_pack",
            "entries": rows})
    readiness_path = ROOT / "shared/tsr/foreign-runtime-readiness-v1.json"
    readiness = load(readiness_path)
    for item in readiness["countries"]:
        manifest = ROOT / item["runtime_manifest"]["path"]
        item["runtime_manifest"]["manifest_sha256"] = hashlib.sha256(pending[manifest]).hexdigest()
    pending[readiness_path] = encoded(readiness)
    pending[ROOT / "shared/tsr/mapping-review-v1.json"] = encoded(ledger)
    changed = [str(path.relative_to(ROOT)) for path, raw in pending.items() if not path.exists() or path.read_bytes() != raw]
    if write:
        for path, raw in pending.items():
            if str(path.relative_to(ROOT)) in changed:
                path.write_bytes(raw)
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    changed = run(args.write)
    print(json.dumps({"changed" if args.write else "drift": changed}, indent=2))
    raise SystemExit(0 if args.write or not changed else 1)
