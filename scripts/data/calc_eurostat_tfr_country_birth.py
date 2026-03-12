#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path
from typing import Iterable

import requests


EUROSTAT_API_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
BIRTHS_DATASET = "demo_facbc"
POPULATION_DATASET = "migr_pop3ctb"
AGE_GROUPS = ["Y15-19", "Y20-24", "Y25-29", "Y30-34", "Y35-39", "Y40-44", "Y45-49"]
AGGREGATE_GEO_LABEL_PREFIXES = (
    "European ",
    "Euro area",
    "European Economic Area",
    "European Free Trade Association",
)
EXCLUDED_GEO_CODES = {"DE_TOT"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute a TFR-style indicator by reporting country and country-of-birth category "
            "from Eurostat demo_facbc (births) and migr_pop3ctb (female population)."
        )
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Reference year for births and 1 January population. Defaults to the latest common year.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tmp/eurostat"),
        help="Directory for generated CSV files.",
    )
    return parser.parse_args()


def fetch(dataset: str, params: Iterable[tuple[str, str]]) -> dict:
    response = requests.get(
        f"{EUROSTAT_API_BASE}/{dataset}",
        params=list(params),
        timeout=180,
    )
    response.raise_for_status()
    return response.json()


def ordered_codes(dataset: dict, dimension: str) -> list[str]:
    category_index = dataset["dimension"][dimension]["category"]["index"]
    return [code for code, _ in sorted(category_index.items(), key=lambda item: item[1])]


def category_labels(dataset: dict, dimension: str) -> dict[str, str]:
    return dataset["dimension"][dimension]["category"].get("label", {})


def strides(sizes: list[int]) -> list[int]:
    result: list[int] = []
    product = 1
    for size in reversed(sizes[1:]):
        product *= size
        result.append(product)
    return list(reversed(result)) + [1]


def decode_observations(dataset: dict) -> list[dict[str, object]]:
    ids = dataset["id"]
    sizes = dataset["size"]
    dimension_codes = {dimension: ordered_codes(dataset, dimension) for dimension in ids}
    out: list[dict[str, object]] = []
    for flat_key, value in dataset.get("value", {}).items():
        remainder = int(flat_key)
        row: dict[str, object] = {}
        for dimension, step in zip(ids, strides(sizes)):
            category_index = remainder // step
            remainder %= step
            row[dimension] = dimension_codes[dimension][category_index]
        row["value"] = value
        out.append(row)
    return out


def latest_common_year() -> int:
    births_probe = fetch(BIRTHS_DATASET, [("geo", "BE"), ("c_birth", "TOTAL"), ("age", AGE_GROUPS[0])])
    population_probe = fetch(
        POPULATION_DATASET,
        [("geo", "BE"), ("c_birth", "TOTAL"), ("age", AGE_GROUPS[0]), ("sex", "F")],
    )
    years = sorted(
        set(ordered_codes(births_probe, "time")) & set(ordered_codes(population_probe, "time")),
        key=int,
    )
    if not years:
        raise RuntimeError("No common year found between Eurostat births and population datasets.")
    return int(years[-1])


def is_country_geo(geo_code: str, geo_label: str) -> bool:
    if geo_code in EXCLUDED_GEO_CODES:
        return False
    return not geo_label.startswith(AGGREGATE_GEO_LABEL_PREFIXES)


def age_slug(age_code: str) -> str:
    return age_code.lower().replace("-", "_")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_matrix_rows(
    summary_rows: list[dict[str, object]],
    c_birth_codes: list[str],
) -> list[dict[str, object]]:
    grouped: dict[tuple[object, object, object], dict[str, object]] = {}
    for row in summary_rows:
        key = (row["year"], row["geo_code"], row["geo_label"])
        if key not in grouped:
            grouped[key] = {
                "year": row["year"],
                "geo_code": row["geo_code"],
                "geo_label": row["geo_label"],
            }
        grouped[key][f"tfr_{row['c_birth_code']}"] = row["tfr_jan1_population"]
    matrix_rows = list(grouped.values())
    matrix_rows.sort(key=lambda row: (str(row["geo_label"]), str(row["geo_code"])))
    return matrix_rows


def main() -> None:
    args = parse_args()
    year = args.year or latest_common_year()
    year_str = str(year)

    births_probe = fetch(BIRTHS_DATASET, [("time", year_str), ("age", AGE_GROUPS[0])])
    c_birth_codes = ordered_codes(births_probe, "c_birth")
    c_birth_labels = category_labels(births_probe, "c_birth")
    geo_labels = category_labels(births_probe, "geo")
    country_geos = [
        geo_code
        for geo_code in ordered_codes(births_probe, "geo")
        if is_country_geo(geo_code, geo_labels.get(geo_code, geo_code))
    ]

    births_dataset = fetch(
        BIRTHS_DATASET,
        [("time", year_str)] + [("age", age) for age in AGE_GROUPS],
    )
    population_dataset = fetch(
        POPULATION_DATASET,
        [("sex", "F"), ("time", year_str)]
        + [("age", age) for age in AGE_GROUPS]
        + [("c_birth", code) for code in c_birth_codes],
    )

    births_map = {
        (row["geo"], row["c_birth"], row["age"]): row["value"]
        for row in decode_observations(births_dataset)
    }
    population_map = {
        (row["geo"], row["c_birth"], row["age"]): row["value"]
        for row in decode_observations(population_dataset)
    }

    summary_rows: list[dict[str, object]] = []
    detail_rows: list[dict[str, object]] = []
    coverage = Counter()

    for geo_code in country_geos:
        geo_label = geo_labels.get(geo_code, geo_code)
        for c_birth_code in c_birth_codes:
            c_birth_label = c_birth_labels.get(c_birth_code, c_birth_code)
            age_births: dict[str, float] = {}
            age_populations: dict[str, float] = {}
            age_rates: dict[str, float] = {}
            missing_ages: list[str] = []

            for age in AGE_GROUPS:
                births_value = births_map.get((geo_code, c_birth_code, age))
                population_value = population_map.get((geo_code, c_birth_code, age))
                if births_value is None or population_value is None or population_value <= 0:
                    missing_ages.append(age)
                    continue
                age_births[age] = float(births_value)
                age_populations[age] = float(population_value)
                age_rates[age] = float(births_value) / float(population_value)

            if missing_ages:
                continue

            tfr = 5.0 * sum(age_rates.values())
            total_births = int(round(sum(age_births.values())))
            total_population = int(round(sum(age_populations.values())))

            base_row = {
                "year": year,
                "geo_code": geo_code,
                "geo_label": geo_label,
                "c_birth_code": c_birth_code,
                "c_birth_label": c_birth_label,
                "tfr_jan1_population": round(tfr, 6),
                "births_15_49": total_births,
                "female_population_15_49_jan1": total_population,
                "age_groups": ",".join(AGE_GROUPS),
                "births_dataset": BIRTHS_DATASET,
                "population_dataset": POPULATION_DATASET,
                "method": "5 * sum(live_births_age / female_population_age_on_1_January)",
                "note": "Uses 1 January female population, so this is a TFR-style approximation rather than the official Eurostat TFR.",
            }
            summary_rows.append(base_row)

            detail_row = dict(base_row)
            for age in AGE_GROUPS:
                slug = age_slug(age)
                detail_row[f"births_{slug}"] = int(round(age_births[age]))
                detail_row[f"female_population_{slug}_jan1"] = int(round(age_populations[age]))
                detail_row[f"asfr_{slug}"] = round(age_rates[age], 10)
            detail_rows.append(detail_row)
            coverage[c_birth_code] += 1

    summary_rows.sort(key=lambda row: (str(row["geo_label"]), str(row["c_birth_label"])))
    detail_rows.sort(key=lambda row: (str(row["geo_label"]), str(row["c_birth_label"])))

    output_dir = args.output_dir
    summary_path = output_dir / f"eurostat_tfr_country_birth_{year}_summary.csv"
    detail_path = output_dir / f"eurostat_tfr_country_birth_{year}_detail.csv"
    matrix_path = output_dir / f"eurostat_tfr_country_birth_{year}_matrix.csv"

    summary_fields = [
        "year",
        "geo_code",
        "geo_label",
        "c_birth_code",
        "c_birth_label",
        "tfr_jan1_population",
        "births_15_49",
        "female_population_15_49_jan1",
        "age_groups",
        "births_dataset",
        "population_dataset",
        "method",
        "note",
    ]
    detail_fields = list(summary_fields)
    for age in AGE_GROUPS:
        slug = age_slug(age)
        detail_fields.extend(
            [
                f"births_{slug}",
                f"female_population_{slug}_jan1",
                f"asfr_{slug}",
            ]
        )
    covered_c_birth_codes = [code for code in c_birth_codes if coverage[code] > 0]
    matrix_fields = ["year", "geo_code", "geo_label"] + [f"tfr_{code}" for code in covered_c_birth_codes]

    write_csv(summary_path, summary_fields, summary_rows)
    write_csv(detail_path, detail_fields, detail_rows)
    write_csv(matrix_path, matrix_fields, build_matrix_rows(summary_rows, covered_c_birth_codes))

    coverage_parts = ", ".join(
        f"{code}={coverage[code]}" for code in c_birth_codes if coverage[code] > 0
    )
    print(f"Computed {len(summary_rows)} rows for {year}.")
    print(f"Summary CSV: {summary_path}")
    print(f"Detail CSV:  {detail_path}")
    print(f"Matrix CSV:  {matrix_path}")
    print(f"Coverage by c_birth: {coverage_parts}")


if __name__ == "__main__":
    main()
