#!/usr/bin/env python3
"""Build the reconciled Panoramax traffic-sign mapping PDF.

Example:
    python3 shared/tsr/sign-pictograms/build_reconciled_sign_mapping_pdf.py \
      --mapping-csv /path/to/panoramax-road_signs_mapping.csv

The mapping CSV remains an external source. This builder verifies the checked-in
German and national FR/NL/CH/BE manifest assets and their PNG/SVG hashes, checks
the model-linked selection mappings, and renders every CSV row with country columns.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


SIGN_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SIGN_ROOT.parents[2]
COUNTRIES = ("DE", "FR", "NL", "CH", "BE")
ARTWORK_COUNTRIES = ("DE", "FR", "NL", "CH", "BE")
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


def license_label(artwork: dict, country: str) -> str:
    if country == "CH":
        return "ASTRA source-preparation only; redistribution clearance pending"
    return artwork.get("license", "License status not recorded")


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
    for country in ("FR", "NL", "CH", "BE"):
        csv_codes = defaultdict(list)
        for row in rows:
            if row[country]:
                csv_codes[row["YOLO"]].append(normalize_code(row[country], country))
        selected_codes = defaultdict(list)
        for entry in selections[country]["entries"]:
            if entry.get("source_model_class"):
                selected_codes[entry["source_model_class"]].append(normalize_code(entry["sign_code"], country))
        for model_class, codes in selected_codes.items():
            if sorted(codes) != sorted(csv_codes.get(model_class, [])):
                raise ValueError(f"{country} selection does not reconcile for {model_class}")
    return rows, manifests, selections, assets


def sized_image(artwork: dict, country: str) -> Image:
    image_source: object = str(artwork["_png"])
    if country == "CH":
        with PILImage.open(artwork["_png"]) as source:
            rgba = source.convert("RGBA")
            alpha = rgba.getchannel("A")
            visible = alpha.point(lambda value: 255 if value >= 64 else 0)
            bbox = visible.getbbox()
            if bbox:
                left, top, right, bottom = bbox
                margin = 2
                bbox = (
                    max(0, left - margin),
                    max(0, top - margin),
                    min(rgba.width, right + margin),
                    min(rgba.height, bottom + margin),
                )
                rgba = rgba.crop(bbox)
            buffer = io.BytesIO()
            rgba.save(buffer, format="PNG")
            buffer.seek(0)
            image_source = buffer
    image = Image(image_source)
    scale = min(52 / image.imageWidth, 52 / image.imageHeight)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    return image


def missing_cell(raw: str, country: str, styles: dict) -> Table:
    label = "Not mapped" if not raw else ("No CH artwork in current scope" if country == "CH" else "No checked-in artwork")
    reason = "No CSV mapping" if not raw else ("Excluded or not in source-preparation manifest" if country == "CH" else "Not in reviewed manifest")
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
        sized_image(artwork, country), Spacer(1, 2), para(raw, styles["code"]),
        para(license_label(artwork, country), styles["license"]),
        para(artwork.get("mapping_status", ""), styles["tiny"]),
    ]
    if country == "CH":
        content += [Spacer(1, 2), para(f"ASTRA: {artwork.get('source_archive', '')} / {artwork.get('source_member', '')}", styles["tiny"])]
    cell = Table([[content]], colWidths=[181])
    cell.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COUNTRY_COLORS[country]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return cell


def source_link(url: str, styles: dict, label: str) -> Paragraph:
    safe_url = escape(text(url), {'"': "&quot;"})
    return Paragraph(f'<link href="{safe_url}" color="#225ea8">{escape(text(label))}</link>', styles["appendix"])


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
    ch_codes = {normalize_code(row["CH"], "CH") for row in rows if row["CH"]}
    ch_missing = sorted(ch_codes - set(assets["CH"]))
    artwork_summary = ", ".join(f"{country} {len(assets[country])}" for country in ("DE", "FR", "NL", "CH", "BE"))
    story = [Spacer(1, 18 * mm), Paragraph("Panoramax traffic-sign country mapping", styles["title"]), Paragraph("Reconciled visual catalogue for the German, French, Dutch, Swiss and Belgian columns in the supplied mapping CSV, including ASTRA provenance for Swiss artwork.", styles["subtitle"])]
    summary = Table([
        [para("Source rows", styles["small"]), para(len(rows), styles["body"]), para("CSV columns", styles["small"]), para("YOLO, DE, FR, NL, CH, BE", styles["body"])],
        [para("Reconciliation", styles["small"]), para("FR, NL, CH and BE model-linked selection entries match the corresponding CSV codes. Country prefixes are normalized to uppercase.", styles["body"]), para("Generated", styles["small"]), para("2026-09-17", styles["body"])],
        [para("Artwork sets", styles["small"]), para(f"{artwork_summary}. Manifest extras remain catalog-only when they have no source model class.", styles["body"]), para("CH artwork", styles["small"]), para(f"116 ASTRA source-preparation assets. {len(ch_missing)} mapped CH code(s) have no checked-in artwork in the current scope. 4.88 and 4.90 remain excluded by owner decision.", styles["body"])],
    ], colWidths=[78, 370, 82, 380])
    summary.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e7eef8")), ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#e7eef8")), ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#aeb9c6")), ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d4dbe3")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [summary, Spacer(1, 12 * mm), Paragraph("Source and interpretation", styles["h1"]), Paragraph("Each mapping row is retained in source order. A country cell shows the real transparent PNG when the CSV code resolves to a checked-in manifest asset. Missing cells preserve the CSV code and state why no image is shown. License and provenance details for every rendered asset appear in the appendix.", styles["body"]), Paragraph("German artwork is indexed by shared/tsr/sign-pictograms/manifest.json. France, the Netherlands, Switzerland and Belgium use their national manifest.json and selection.json files. The German set has no separate top-level selection.json.", styles["body"]), Paragraph("Swiss CH artwork is derived from ASTRA's official <link href=\"https://www.astra.admin.ch/de/signale\" color=\"#225ea8\">traffic-sign archive</link>. The appendix records each source archive, source member and SHA-256 hash, along with the local conversion step. ASTRA's public site confirms that the files are available for download, but its copyright notice states that downloading or copying transfers no rights and that reproduction requires prior written permission. The PDF therefore records CH as source-preparation-only pending explicit redistribution clearance. This status does not prevent internal evaluation or provenance documentation.", styles["body"]), PageBreak()]

    header = [para("YOLO class", styles["table_header"])] + [para(f"{cc} - {COUNTRY_NAMES[cc]}", styles["table_header"]) for cc in COUNTRIES]
    table_rows = [header]
    for row in rows:
        table_rows.append([para(row["YOLO"], styles["yolo"])] + [country_cell(cc, row[cc], assets, styles) for cc in COUNTRIES])
    mapping_table = LongTable(table_rows, colWidths=[115, 190, 190, 190, 190, 190], repeatRows=1, splitByRow=1)
    mapping_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324d")), ("GRID", (0, 0), (-1, 0), 0.45, colors.HexColor("#dce3eb")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 1), (-1, -1), 3), ("BOTTOMPADDING", (0, 1), (-1, -1), 3), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafbfd")]), ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#d6dde5"))]))
    story += [Paragraph("CSV rows and country artwork", styles["h1"]), mapping_table, PageBreak(), Paragraph("Artwork provenance and license", styles["h1"]), Paragraph("This appendix lists every unique manifest artwork referenced by a CSV row with its country, code, model classes, declared license or provenance status, attribution requirement, artist or source archive, source member, source page and checked-in PNG hash. For CH, source availability is not treated as redistribution permission.", styles["body"])]

    referenced = defaultdict(list)
    for row in rows:
        for country in ARTWORK_COUNTRIES:
            if row[country]:
                code = normalize_code(row[country], country)
                if code in assets[country]:
                    referenced[(country, code)].append(row["YOLO"])
    appendix_rows = [[para(v, styles["appendix_header"]) for v in ("Country", "Code", "CSV model class(es)", "License / provenance", "Attribution / artist", "Source archive / member", "Source page", "PNG SHA-256")]]
    for country, code in sorted(referenced):
        artwork = assets[country][code]
        license_or_status = license_label(artwork, country)
        attribution = license_or_status if country == "CH" else license_or_status + ("; attribution required" if artwork.get("attribution_required") else "; attribution not required")
        url = artwork.get("source_page_permanent_url") or artwork.get("license_source_permanent_url") or artwork.get("source_page_url") or "https://www.astra.admin.ch/de/signale"
        source_ref = f"{artwork.get('source_archive', '')} / {artwork.get('source_member', '')}\nconversion: {artwork.get('conversion', '')}\nmember SHA-256: {artwork.get('source_member_sha256', '')}" if country == "CH" else artwork.get("commons_title", "")
        source_label = "ASTRA source archive" if country == "CH" else "Commons permanent page"
        appendix_rows.append([para(f"{country} - {COUNTRY_NAMES[country]}", styles["appendix"]), para(artwork["sign_code"], styles["appendix"]), para("; ".join(sorted(set(referenced[(country, code)]))), styles["appendix"]), para(attribution, styles["appendix"]), para(artwork.get("artist", "") or ("ASTRA" if country == "CH" else ""), styles["appendix"]), para(source_ref, styles["appendix"]), source_link(url, styles, source_label), para(artwork["png_sha256"], styles["appendix"])])
    appendix_table = LongTable(appendix_rows, colWidths=[72, 52, 200, 145, 100, 190, 130, 180], repeatRows=1, splitByRow=1)
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
