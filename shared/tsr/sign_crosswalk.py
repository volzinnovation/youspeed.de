"""Portable, display-only join between source labels and national sign artwork."""

from __future__ import annotations

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


@cache
def crosswalk():
    data = json.loads(CROSSWALK.read_text(encoding="utf-8"))
    if data["schema_version"] != 1:
        raise ValueError("Unsupported sign crosswalk version")
    return data


def source_aliases(source, country):
    return crosswalk().get(source, {}).get(country, {})


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
    for source, code in source_aliases("mapillary_speed_templates", country).items():
        if match := speed_template_pattern(source).fullmatch(label):
            return code.format(speed=match[1])
    return source_aliases("mapillary", country).get(label, {}).get("sign_code")


def mapillary_classes(code):
    country = code[:2]
    for source, template in source_aliases("mapillary_speed_templates", country).items():
        if match := speed_template_pattern(template).fullmatch(code):
            return [source.format(speed=match[1])]
    return [label for label, entry in source_aliases("mapillary", country).items() if entry.get("sign_code") == code]


def code_artwork(label, country):
    code = label if label.startswith(country + ":") else f"{country}:{label}"
    override = display_artwork(country).get(code, {})
    codes, _ = catalog_index(country)
    return available_artwork(override.get("image_path")) or codes.get(code.upper())


def resolve_sign(source, label, country):
    """Return an explicit identity and independent artwork. Missing mappings stay unresolved."""
    if country not in COUNTRIES:
        return SourceSign(label, None, None)
    value = label.strip()
    if source == "mapillary":
        entry = source_aliases(source, country).get(value, {})
        code = mapillary_code(value, country)
        image = pictogram_path(country, entry.get("pictogram")) or (code_artwork(code, country) if code else None)
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


def resolve_osm_tag(value, country):
    """Resolve individual traffic_sign codes and keep decimal commas inside a code."""
    return [resolve_sign("openstreetmap", token.strip(), country)
            for token in re.split(r";|,(?=\s*[A-Z]{2}:)", value) if token.strip()]
