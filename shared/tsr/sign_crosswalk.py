"""Resolve source-native sign labels, reviewed classifier targets and optional local artwork."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import cache
import json
from pathlib import Path
import re

TSR = Path(__file__).resolve().parent
CROSSWALK = TSR / "sign-pictograms/source-crosswalk-v1.json"
COUNTRIES = frozenset({"BE", "CH", "DE", "FR", "NL"})
ASSET = re.compile(r"tsr/sign-pictograms/(?:png|national/(?:BE|CH|FR|NL)/png)/[a-z0-9][a-z0-9.,_-]*\.png")


@dataclass(frozen=True)
class SourceSign:
    source_label: str
    sign_code: str | None
    image_path: str | None


@dataclass(frozen=True)
class ReviewedSourceSign(SourceSign):
    target_label: str | None = None
    sign_code_scope: str | None = None


@cache
def crosswalk():
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate key in sign crosswalk: {key}")
            result[key] = value
        return result
    data = json.loads(CROSSWALK.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    if data["schema_version"] != 1:
        raise ValueError("Unsupported sign crosswalk version")
    return data


def source_aliases(source, country):
    return crosswalk().get(source, {}).get(country, {})


@cache
def synset_name_ids(country):
    names = {}
    for key, row in source_aliases("synset", country).items():
        name = row["class_name"]
        names[name] = None if name in names else key
    return names


def synset_entry(label, country="DE"):
    """Look up the publisher's integer label or a unique, exact Parquet class_name."""
    value = str(label).strip()
    entries = source_aliases("synset", country)
    return entries.get(value) or entries.get(synset_name_ids(country).get(value))


def exact_audit_target(entry):
    targets = entry.get("classifier_labels", [])
    if (len(targets) == 1 and entry.get("classifier_capability") == "exact_label"
            and entry.get("classifier_exact_variant_supported")):
        return targets[0]
    return None


def display_artwork(country):
    return source_aliases("display", country)


def available_artwork(path):
    if isinstance(path, str) and ASSET.fullmatch(path) and (TSR.parent / path).is_file():
        return path
    return None


def pictogram_path(country, stem):
    if country not in COUNTRIES or not stem:
        return None
    directory = "png" if country == "DE" else f"national/{country}/png"
    return available_artwork(f"tsr/sign-pictograms/{directory}/{stem}.png")


@cache
def catalog_index(country):
    if country not in COUNTRIES:
        return {}, {}
    catalog = json.loads((TSR / f"prolix-{country.lower()}-class-catalog-v1.json").read_text(encoding="utf-8"))
    codes, models = {}, {}
    for row in catalog["signs"]:
        raw_code = row.get("sign_code")
        code = raw_code if not raw_code or ":" in raw_code else f"{country}:{raw_code}"
        image = available_artwork(row.get("image_path")) if row.get("display_eligible") else None
        if code and image:
            codes[code.upper()] = image
        models[row["class_id"].upper()] = (code, image)
    return codes, models


@cache
def speed_template_pattern(template):
    return re.compile(re.escape(template).replace(re.escape("{speed}"), r"([1-9][0-9]{0,2})"))


def mapillary_code(label, country):
    entry = source_aliases("mapillary", country).get(label, {})
    if entry.get("mapping_status") == "excluded_de":
        return None
    for source, code in source_aliases("mapillary_speed_templates", country).items():
        if match := speed_template_pattern(source).fullmatch(label):
            return code.format(speed=match[1])
    return entry.get("sign_code")


def mapillary_classes(code):
    country = code[:2]
    for source, template in source_aliases("mapillary_speed_templates", country).items():
        if match := speed_template_pattern(template).fullmatch(code):
            label = source.format(speed=match[1])
            return [label] if mapillary_code(label, country) == code else []
    return [label for label, entry in source_aliases("mapillary", country).items() if entry.get("sign_code") == code]


def code_artwork(label, country):
    code = label if label.startswith(country + ":") else f"{country}:{label}"
    override = display_artwork(country).get(code, {})
    codes, _ = catalog_index(country)
    return available_artwork(override.get("image_path")) or codes.get(code.upper())


def resolve_sign(source, label, country):
    """Return an explicit identity and independent artwork. Missing mappings stay unresolved."""
    if source == "synset":
        entry = synset_entry(label, country) or {}
        code = entry.get("sign_code")
        image = code_artwork(code, country) if code and entry.get("sign_code_scope") == "sign" else None
        return SourceSign(str(label), code, image)
    if country not in COUNTRIES:
        return SourceSign(label, None, None)
    value = label.strip()
    if source == "mapillary":
        entry = source_aliases(source, country).get(value, {})
        code = mapillary_code(value, country)
        stem = entry.get("pictogram") if entry.get("display_scope") != "survey" else None
        image = pictogram_path(country, stem) or (code_artwork(code, country) if code else None)
    elif source == "panoramax":
        _, models = catalog_index(country)
        code, exact = models.get(value.upper(), (None, None))
        image = available_artwork(display_artwork(country).get(value, {}).get("image_path")) or exact
    elif source in {"mobidata", "openstreetmap"}:
        allow_unlisted_code = True
        if source == "openstreetmap":
            allow_unlisted_code = value.startswith(country + ":")
            speed = re.fullmatch(r"(?:DE:)?(274|278)\[([1-9][0-9]{0,2})(?:\s*km/h)?\]", value) if country == "DE" else None
            if speed:
                value = f"DE:{speed[1]}-{speed[2]}"
                allow_unlisted_code = True
        alias = source_aliases(source, country).get(value, {})
        if source == "openstreetmap" and not alias and ":" not in value:
            value = f"{country}:{value}"
        code = alias.get("sign_code")
        if (not alias and re.fullmatch(rf"{country}:[A-Za-z0-9][A-Za-z0-9.,-]*(?:\[[0-9.,]+\])?", value)
                and (allow_unlisted_code or code_artwork(value, country))):
            code = value
        image = available_artwork(alias.get("image_path")) or (code_artwork(code, country) if code else None)
    else:
        raise ValueError(f"Unknown sign source: {source}")
    return SourceSign(label, code, image)


@cache
def _classifier_targets(country):
    catalog = json.loads((TSR / f"prolix-{country.lower()}-class-catalog-v1.json").read_text(encoding="utf-8"))
    return {raw.upper(): raw for raw in catalog["class_labels"]}


def german_osm_targets(data, catalog):
    """German traffic_sign literals and their reviewed classifier targets. None means unresolved."""
    # Only concrete identifiers are source literals. 'DE:101-x1' is a classifier-family pattern.
    def concrete(code):
        return bool(code and re.fullmatch(r"DE:[0-9]+(?:[.,-][0-9]+)*", code))

    deployed = set(catalog["class_labels"])
    known = set()
    catalog_targets = defaultdict(set)
    eligible_targets = defaultdict(set)
    evidence = defaultdict(set)
    rejected = set()
    for row in catalog["signs"]:
        code = row.get("sign_code")
        if not concrete(code):
            continue
        known.add(code)
        target = row["class_id"]
        if target in deployed:
            catalog_targets[code].add(target)
            speed = re.fullmatch(r"DE:274-([1-9][0-9]{0,2})", code)
            # A deployed numbered speed is exact even when its local artwork is unavailable.
            if row["display_eligible"] or (speed and target == "maxspeed:" + speed[1]):
                eligible_targets[code].add(target)

    for row in data["synset"]["DE"].values():
        code = row.get("sign_code")
        if row.get("sign_code_scope") == "sign" and concrete(code):
            known.add(code)
            if row["mapping_status"] == "approved":
                evidence[code].add(row["target_label"])
            else:
                rejected.add(code)

    for source in ("mapillary", "mobidata"):
        for native, row in data[source]["DE"].items():
            code = row.get("sign_code")
            if row.get("mapping_status") in {"reference_only", "excluded_de"}:
                continue
            if not concrete(code) or (source == "mobidata" and native != code):
                continue
            known.add(code)
            target = row.get("target_label")
            if target is not None:
                evidence[code].add(target)

    # Synset crops can establish a specific rendered face while an OSM code alone remains
    # ambiguous (e.g. DE:151). Resolve such codes only through an explicit OSM review below.
    resolved = {}
    for code in sorted(known):
        reviewed = evidence[code]
        candidates = reviewed or eligible_targets[code]
        if (code in rejected or len(catalog_targets[code]) > 1 or len(candidates) != 1
                or (reviewed and eligible_targets[code] and not reviewed <= eligible_targets[code])):
            resolved[code] = None
        else:
            resolved[code] = next(iter(candidates))

    aliases = data["openstreetmap"]["DE"]
    # Install explicit code decisions first, so all aliases inherit the same reviewed target.
    for raw, row in aliases.items():
        if concrete(raw) and "target_label" in row:
            resolved[raw] = row["target_label"]
    for raw, row in aliases.items():
        if "target_label" in row:
            resolved[raw] = row["target_label"]
        elif raw not in resolved:
            resolved[raw] = resolved.get(row.get("sign_code"))
    for raw, target in list(resolved.items()):
        match = re.fullmatch(r"DE:(274|278)-([1-9][0-9]{0,2})", raw)
        if match:
            alias = f"DE:{match[1]}[{match[2]}]"
            if alias in resolved and resolved[alias] != target:
                raise ValueError(f"Conflicting OpenStreetMap speed alias: {alias}")
            resolved[alias] = target
    if not {target for target in resolved.values() if target is not None} <= deployed:
        raise ValueError("OpenStreetMap review references a label outside the German classifier")
    return resolved


@cache
def _german_osm_index():
    catalog = json.loads((TSR / "prolix-de-class-catalog-v1.json").read_text(encoding="utf-8"))
    return german_osm_targets(crosswalk(), catalog)


def review_source_sign(source, label, country):
    """Join the native source observation with separately reviewed model targets and Survey artwork hints."""
    sign = resolve_sign(source, label, country)
    target = scope = None
    image = sign.image_path
    native = str(label).strip()
    if source == "synset":
        entry = synset_entry(label, country) or {}
        target, scope = entry.get("target_label"), entry.get("sign_code_scope")
    elif source == "panoramax" and country in COUNTRIES:
        target = _classifier_targets(country).get(native.upper())
    elif source == "mapillary":
        entry = source_aliases(source, country).get(native, {})
        if entry.get("display_scope") == "survey":
            image = pictogram_path(country, entry.get("pictogram"))
        if "target_label" in entry:
            target = entry["target_label"]
        elif sign.sign_code:
            target = exact_audit_target(source_aliases("mobidata", country).get(sign.sign_code, {}))
    elif source == "mobidata":
        entry = source_aliases(source, country).get(native, {})
        target = entry["target_label"] if "target_label" in entry else exact_audit_target(entry)
    elif source == "openstreetmap" and country == "DE":
        index = _german_osm_index()
        target = index[native] if native in index else index.get(sign.sign_code)
    return ReviewedSourceSign(sign.source_label, sign.sign_code, image, target, scope)


def resolve_osm_tag(value, country):
    """Resolve individual traffic_sign codes and keep decimal commas inside a code."""
    return [resolve_sign("openstreetmap", token.strip(), country)
            for token in re.split(r";|,(?=\s*[A-Z]{2}:)", value) if token.strip()]
