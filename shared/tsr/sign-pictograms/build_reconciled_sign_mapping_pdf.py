#!/usr/bin/env python3
"""Build the reconciled Panoramax traffic-sign mapping PDF.

Example:
    python3 shared/tsr/sign-pictograms/build_reconciled_sign_mapping_pdf.py \
      --mapping-csv /path/to/panoramax-road_signs_mapping.csv

The mapping CSV remains an external source. This builder verifies the checked-in
German and national FR/NL/BE manifest assets and their PNG/SVG hashes, checks the
model-linked selection mappings, and renders every CSV row with country columns.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


SIGN_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SIGN_ROOT.parents[2]
COUNTRIES = ("DE", "FR", "NL", "CH", "BE")
ARTWORK_COUNTRIES = ("DE", "FR", "NL", "BE")
COUNTRY_NAMES = {"DE": "Germany", "FR": "France", "NL": "Netherlands", "CH": "Switzerland", "BE": "Belgium"}
COUNTRY_COLORS = {
    "DE": colors.HexColor("#e7eef8"),
    "FR": colors.HexColor("#f7e9ef"),
    "NL": colors.HexColor("#fff0dc"),
    "CH": colors.HexColor("#f0f0f0"),
    "BE": colors.HexColor("#fff8d9"),
}


def text(value: object) -> str:
    return (
        str(value or "")
        .replace("\u2010", "-")
        .replace("\u2011", "-")
        .replace("\u2012", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
    )


def para(value: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text(value)).replace("\n", "<br/>"), style)


def normalize_code(raw: str, country: str) -> str:
    prefix = country + ":"
    return raw[len(prefix) :] if raw.startswith(prefix) else raw


def load_sources(mapping_csv: Path):
    with mapping_csv.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        expected = ["YOLO", "DE", "FR", "NL", "CH", "BE"]
        if reader.fieldnames != expected:
            raise ValueError(f"Expected CSV columns {expected}, got {reader.fieldnames}")
        rows = list(reader)

    manifests = {}
    selections = {}
    assets = {}
    for country in ARTWORK_COUNTRIES:
        manifest_path = SIGN_ROOT / "manifest.json" if country == "DE" else SIGN_ROOT / "national" / country / "manifest.json"
        selection_path = None if country == "DE" else SIGN_ROOT / "national" / country / "selection.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        selection = json.loads(selection_path.read_text(encoding="utf-8")) if selection_path else None
        manifests[country] = manifest
        selections[country] = selection
        by_code = {}
        for artwork in manifest["artworks"]:
            code = normalize_code(artwork["sign_code"], country)
            png = SIGN_ROOT / artwork["png_path"]
            original = SIGN_ROOT / artwork["original_path"]
            if not png.is_file() or not original.is_file():
                raise FileNotFoundError(f"Missing artwork for {country}:{code}")
            if hashlib.sha256(png.read_bytes()).hexdigest() != artwork["png_sha256"]:
                raise ValueError(f"PNG hash mismatch for {country}:{code}")
            if hashlib.sha256(original.read_bytes()).hexdigest() != artwork["original_sha256"]:
                raise ValueError(f"SVG hash mismatch for {country}:{code}")
            if code in by_code:
                raise ValueError(f"Duplicate manifest code for {country}:{code}")
            by_code[code] = {**artwork, "_png": png}
        assets[country] = by_code

    # Selection files must agree with every corresponding CSV code. Catalog-only
    # preserved extras have no source_model_class and are intentionally skipped.
    for country in ("FR", "NL", "BE"):
        csv_codes = defaultdict(list)
        for row in rows:
            if row[country]:
                csv_codes[row["YOLO"]].append(normalize_code(row[country], country))
        selected_codes = defaultdict(list)
        for entry in selections[country]["entries"]:
            if entry.get("source_model_class"):
                selected_codes[entry["source_model_class"]].append(entry["sign_code"])
        for model_class, codes in selected_codes.items():
            if sorted(codes) != sorted(csv_codes.get(model_class, [])):
                raise ValueError(f"{country} selection does not reconcile for {model_class}")
    return rows, manifests, selections, assets


def sized_image(artwork: dict) -> Image:
    image = Image(str(artwork["_png"]))
    scale = min(52 / image.imageWidth, 52 / image.imageHeight)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    return image


def missing_cell(raw: str, country: str, styles: dict) -> Table:
    label = "Not mapped" if not raw else ("No CH artwork set" if country == "CH" else "No checked-in artwork")
    reason = "No CSV mapping" if not raw else ("No CH manifest in repository" if country == "CH" else "Not in reviewed manifest")
    box = Table([[para(label, styles["missing"])]], colWidths=[171])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f6f7f9")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#b7bec8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    items = [box]
    if raw:
        items += [Spacer(1, 2), para(raw, styles["code"])]
    items += [Spacer(1, 2), para(reason, styles["tiny"])]
    return Table([[items]], colWidths=[181])


def country_cell(country: str, raw: str, assets: dict, styles: dict) -> Table:
    if not raw:
        return missing_cell(raw, country, styles)
    code = normalize_code(raw, country)
    artwork = assets.get(country, {}).get(code)
    if artwork is None:
        return missing_cell(raw, country, styles)
    content = [
        sized_image(artwork), Spacer(1, 2), para(raw, styles["code"]),
        para(artwork["license"], styles["license"]),
        para(artwork.get("mapping_status", ""), styles["tiny"]),
    ]
    cell = Table([[content]], colWidths=[181])
    cell.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COUNTRY_COLORS[country]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return cell


def source_link(url: str, styles: dict) -> Paragraph:
    safe_url = escape(text(url), {'"': "&quot;"})
    return Paragraph(f'<link href="{safe_url}" color="#225ea8">Commons permanent page</link>', styles["appendix"])


def footer(canvas, doc):
    canvas.saveState()
    width, _ = landscape(A3)
    canvas.setStrokeColor(colors.HexColor("#c7ced8"))
    canvas.setLineWidth(0.4)
    canvas.line(18 * mm, 12 * mm, width - 18 * mm, 12 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#5c6673"))
    canvas.drawString(18 * mm, 8 * mm, "Panoramax traffic-sign mapping reconciliation")
    canvas.drawRightString(width - 18 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build(mapping_csv: Path, output: Path):
    rows, manifests, selections, assets = load_sources(mapping_csv)
    stylesheet = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle("title", parent=stylesheet["Title"], fontName="Helvetica-Bold", fontSize=24, leading=29, textColor=colors.HexColor("#17324d"), spaceAfter=7),
        "subtitle": ParagraphStyle("subtitle", parent=stylesheet["Normal"], fontName="Helvetica", fontSize=12, leading=16, textColor=colors.HexColor("#4a5563"), spaceAfter=18),
        "h1": ParagraphStyle("h1", parent=stylesheet["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=colors.HexColor("#17324d"), spaceBefore=8, spaceAfter=7),
        "body": ParagraphStyle("body", parent=stylesheet["BodyText"], fontName="Helvetica", fontSize=9.2, leading=12.5, textColor=colors.HexColor("#202a35"), spaceAfter=4),
        "small": ParagraphStyle("small", parent=stylesheet["BodyText"], fontName="Helvetica", fontSize=8, leading=10.5, textColor=colors.HexColor("#394553"), spaceAfter=2),
        "tiny": ParagraphStyle("tiny", parent=stylesheet["BodyText"], fontName="Helvetica", fontSize=6.3, leading=7.6, textColor=colors.HexColor("#53606d"), wordWrap="CJK"),
        "code": ParagraphStyle("code", parent=stylesheet["BodyText"], fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=colors.HexColor("#17212b"), alignment=TA_CENTER),
        "license": ParagraphStyle("license", parent=stylesheet["BodyText"], fontName="Helvetica", fontSize=6.6, leading=8, textColor=colors.HexColor("#273746"), alignment=TA_CENTER),
        "missing": ParagraphStyle("missing", parent=stylesheet["BodyText"], fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=colors.HexColor("#687481"), alignment=TA_CENTER),
        "table_header": ParagraphStyle("table_header", parent=stylesheet["BodyText"], fontName="Helvetica-Bold", fontSize=8.5, leading=10, textColor=colors.white, alignment=TA_CENTER),
        "yolo": ParagraphStyle("yolo", parent=stylesheet["BodyText"], fontName="Helvetica-Bold", fontSize=7.4, leading=9, textColor=colors.HexColor("#263442"), wordWrap="CJK"),
        "appendix": ParagraphStyle("appendix", parent=stylesheet["BodyText"], fontName="Helvetica", fontSize=6.7, leading=8.3, textColor=colors.HexColor("#263442"), wordWrap="CJK"),
        "appendix_header": ParagraphStyle("appendix_header", parent=stylesheet["BodyText"], fontName="Helvetica-Bold", fontSize=7.2, leading=8.5, textColor=colors.white, alignment=TA_CENTER),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output), pagesize=landscape(A3), rightMargin=18 * mm, leftMargin=18 * mm, topMargin=15 * mm, bottomMargin=17 * mm, title="Panoramax traffic-sign country mapping reconciliation", author="YouSpeed.de")
    story = [Spacer(1, 18 * mm), Paragraph("Panoramax traffic-sign country mapping", styles["title"]), Paragraph("Reconciled visual catalogue for the German, French, Dutch, Swiss and Belgian columns in the supplied mapping CSV.", styles["subtitle"])]
    summary = Table([
        [para("Source rows", styles["small"]), para(len(rows), styles["body"]), para("CSV columns", styles["small"]), para("YOLO, DE, FR, NL, CH, BE", styles["body"])],
        [para("Reconciliation", styles["small"]), para("FR, NL and BE model-linked selection entries match the corresponding CSV codes. Country prefixes are normalized to uppercase.", styles["body"]), para("Generated", styles["small"]), para("2026-09-16", styles["body"])],
        [para("Artwork sets", styles["small"]), para("DE 111, FR 114, NL 111, BE 115. Manifest extras remain catalog-only when they have no source model class.", styles["body"]), para("CH artwork", styles["small"]), para("No CH manifest or artwork directory is present in this repository; CH codes remain text-only.", styles["body"])],
    ], colWidths=[78, 370, 82, 380])
    summary.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e7eef8")), ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#e7eef8")), ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#aeb9c6")), ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d4dbe3")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [summary, Spacer(1, 12 * mm), Paragraph("Source and interpretation", styles["h1"]), Paragraph("Each mapping row is retained in source order. A country cell shows the real transparent PNG when the CSV code resolves to a checked-in manifest asset. Missing cells preserve the CSV code and state why no image is shown. License and provenance details for every rendered asset appear in the appendix.", styles["body"]), Paragraph("German artwork is indexed by shared/tsr/sign-pictograms/manifest.json. France, the Netherlands and Belgium use their national manifest.json and selection.json files. The German set has no separate top-level selection.json.", styles["body"]), PageBreak()]

    header = [para("YOLO class", styles["table_header"])] + [para(f"{cc} - {COUNTRY_NAMES[cc]}", styles["table_header"]) for cc in COUNTRIES]
    table_rows = [header]
    for row in rows:
        table_rows.append([para(row["YOLO"], styles["yolo"])] + [country_cell(cc, row[cc], assets, styles) for cc in COUNTRIES])
    mapping_table = LongTable(table_rows, colWidths=[115, 190, 190, 190, 190, 190], repeatRows=1, splitByRow=1)
    mapping_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324d")), ("GRID", (0, 0), (-1, 0), 0.45, colors.HexColor("#dce3eb")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 1), (-1, -1), 3), ("BOTTOMPADDING", (0, 1), (-1, -1), 3), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafbfd")]), ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#d6dde5"))]))
    story += [Paragraph("CSV rows and country artwork", styles["h1"]), mapping_table, PageBreak(), Paragraph("Artwork provenance and license", styles["h1"]), Paragraph("This appendix lists every unique manifest artwork referenced by a CSV row with its country, code, model classes, declared license, attribution requirement, artist, Commons source and checked-in PNG hash.", styles["body"])]

    referenced = defaultdict(list)
    for row in rows:
        for country in ARTWORK_COUNTRIES:
            if row[country]:
                code = normalize_code(row[country], country)
                if code in assets[country]:
                    referenced[(country, code)].append(row["YOLO"])
    appendix_rows = [[para(v, styles["appendix_header"]) for v in ("Country", "Code", "CSV model class(es)", "License / attribution", "Artist", "Commons source", "PNG SHA-256")]]
    for country, code in sorted(referenced):
        artwork = assets[country][code]
        attribution = artwork["license"] + ("; attribution required" if artwork.get("attribution_required") else "; attribution not required")
        url = artwork.get("source_page_permanent_url") or artwork.get("license_source_permanent_url") or artwork.get("source_page_url")
        appendix_rows.append([para(f"{country} - {COUNTRY_NAMES[country]}", styles["appendix"]), para(artwork["sign_code"], styles["appendix"]), para("; ".join(sorted(set(referenced[(country, code)]))), styles["appendix"]), para(attribution, styles["appendix"]), para(artwork.get("artist", ""), styles["appendix"]), source_link(url, styles), para(artwork["png_sha256"], styles["appendix"])])
    appendix_table = LongTable(appendix_rows, colWidths=[72, 52, 220, 125, 155, 175, 270], repeatRows=1, splitByRow=1)
    appendix_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324d")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafbfd")]), ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#d6dde5"))]))
    story.append(appendix_table)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(json.dumps({"rows": len(rows), "referenced_assets": len(referenced), "output": str(output), "bytes": output.stat().st_size}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping-csv", type=Path, required=True, help="Path to the Panoramax road_signs_mapping.csv file")
    parser.add_argument("--output", type=Path, default=SIGN_ROOT / "panoramax-road-signs-mapping-reconciled.pdf")
    args = parser.parse_args()
    build(args.mapping_csv.expanduser().resolve(), args.output.expanduser().resolve())


if __name__ == "__main__":
    main()
