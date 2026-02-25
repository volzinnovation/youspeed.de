#!/usr/bin/env python3
import argparse
import datetime as dt
import html
import json
import re
import subprocess
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

SCHOLAR_USER = "Hc4nZ4MAAAAJ"
DBLP_PID = "59/5046"
OPENALEX_AUTHOR = "A5086573546"
HSPF_PROFILE_DE = "https://www.hs-pforzheim.de/profile/raphaelvolz"
HSPF_PROFILE_EN = "https://www.hs-pforzheim.de/en/profile/raphaelvolz"

OUTPUT_BIB = Path("docs/cv/raphael_volz_publications.bib")
OUTPUT_TEX = Path("docs/cv/raphael_volz_publications_by_type.tex")
OUTPUT_QC = Path("docs/cv/raphael_volz_publications_qc.json")

UA = "Mozilla/5.0 (compatible; CVPublicationBuilder/1.0; +https://pforzheim-university.de)"


def fetch(url: str) -> str:
    proc = subprocess.run(
        [
            "curl",
            "-L",
            "--fail",
            "--max-time",
            "45",
            "-H",
            f"User-Agent: {UA}",
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def read_text_with_fallback(path: str, preferred_encodings: list[str] | None = None) -> str:
    data = Path(path).read_bytes()
    encodings = preferred_encodings or []
    for enc in encodings + ["utf-8", "latin-1"]:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


def clean_text(s: str) -> str:
    s = html.unescape(strip_tags(s))
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_title(s: str) -> str:
    s = html.unescape(s)
    s = s.replace("\\", "")
    s = s.replace("{", "").replace("}", "")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def parse_scholar_rows(profile_html: str):
    rows = re.findall(r'<tr class="gsc_a_tr">(.*?)</tr>', profile_html, flags=re.S)
    out = []
    for row in rows:
        m_title = re.search(r'(<a[^>]*class="gsc_a_at"[^>]*>)(.*?)</a>', row, flags=re.S)
        if not m_title:
            continue
        anchor_open = m_title.group(1)
        m_href = re.search(r'href="([^"]+)"', anchor_open)
        href = html.unescape(m_href.group(1)) if m_href else ""
        title = clean_text(m_title.group(2))

        grays = re.findall(r'<div class="gs_gray">(.*?)</div>', row, flags=re.S)
        authors = clean_text(grays[0]) if len(grays) > 0 else ""
        venue = clean_text(grays[1]) if len(grays) > 1 else ""

        m_year = re.search(r'<td class="gsc_a_y">\s*<span[^>]*>(.*?)</span>', row, flags=re.S)
        year_txt = clean_text(m_year.group(1)) if m_year else ""
        year = int(year_txt) if year_txt.isdigit() else None

        out.append(
            {
                "title": title,
                "authors": authors,
                "venue": venue,
                "year": year,
                "href": "https://scholar.google.com" + href,
                "norm_title": normalize_title(title),
            }
        )
    return out


def parse_bibtex_entries(text: str):
    entries = []
    chunks = re.split(r"(?=@[A-Za-z]+\{)", text)
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.match(r"@([A-Za-z]+)\{([^,]+),", chunk)
        if not m:
            continue
        entry_type = m.group(1).lower()
        key = m.group(2).strip()

        fields = {}
        body = chunk[m.end() :].strip()
        if body.endswith("}"):
            body = body[:-1]

        i = 0
        n = len(body)
        while i < n:
            while i < n and body[i] in " \t\r\n,":
                i += 1
            if i >= n:
                break
            j = i
            while j < n and re.match(r"[A-Za-z0-9_\-]", body[j]):
                j += 1
            if j == i:
                break
            field = body[i:j].lower()
            i = j
            while i < n and body[i] in " \t\r\n":
                i += 1
            if i >= n or body[i] != "=":
                break
            i += 1
            while i < n and body[i] in " \t\r\n":
                i += 1
            if i >= n:
                break

            if body[i] == "{":
                depth = 0
                start = i + 1
                i += 1
                while i < n:
                    if body[i] == "{":
                        depth += 1
                    elif body[i] == "}":
                        if depth == 0:
                            break
                        depth -= 1
                    i += 1
                value = body[start:i]
                i += 1
            elif body[i] == '"':
                i += 1
                start = i
                while i < n:
                    if body[i] == '"' and body[i - 1] != "\\":
                        break
                    i += 1
                value = body[start:i]
                i += 1
            else:
                start = i
                while i < n and body[i] not in ",\n\r":
                    i += 1
                value = body[start:i].strip()

            fields[field] = value.strip()

        entries.append(
            {
                "entry_type": entry_type,
                "key": key,
                "fields": fields,
                "raw": chunk.strip(),
                "title": clean_text(fields.get("title", "")),
                "year": int(fields["year"]) if fields.get("year", "").isdigit() else None,
                "norm_title": normalize_title(fields.get("title", "")),
            }
        )
    return entries


def parse_dblp_xml_metadata(xml_text: str):
    root = ET.fromstring(xml_text)
    items = []
    for r in root.findall("r"):
        if len(r) == 0:
            continue
        e = r[0]
        etype = e.tag.lower()
        title_el = e.find("title")
        title = clean_text("".join(title_el.itertext())) if title_el is not None else ""
        if not title:
            continue
        year_txt = clean_text(e.findtext("year", default=""))
        year = int(year_txt) if year_txt.isdigit() else None
        venue = clean_text(e.findtext("journal", default="")) or clean_text(e.findtext("booktitle", default=""))
        authors = [clean_text("".join(a.itertext())) for a in e.findall("author")]
        authors = [a for a in authors if a]
        if not authors:
            continue
        key = e.attrib.get("key", "")
        items.append(
            {
                "entry_type": etype,
                "key": key,
                "title": title,
                "year": year,
                "authors": " and ".join(authors),
                "venue": venue,
                "norm_title": normalize_title(title),
            }
        )
    return items


def map_hspf_section_type(section: str) -> str:
    s = (section or "").lower()
    if "zeitschrift" in s or "journal article" in s:
        return "article"
    if "tagungsband" in s or "proceedings" in s:
        return "inproceedings"
    if "beitrag in buch" in s or "chapter in book" in s:
        return "incollection"
    if "dissertation" in s:
        return "phdthesis"
    return "misc"


def parse_hspf_authors(author_part: str) -> str:
    author_part = clean_text(author_part).strip().rstrip(".")
    if not author_part:
        return ""
    tokens = [t.strip() for t in author_part.split(",") if t.strip()]
    names = []
    i = 0
    while i + 1 < len(tokens):
        last = tokens[i].strip()
        first = tokens[i + 1].strip()
        if re.fullmatch(r"[A-Za-zÀ-ÿ'` -]+", last) and re.fullmatch(r"[A-Za-zÀ-ÿ. '`\-]+", first):
            names.append(f"{last}, {first}")
            i += 2
            continue
        break
    if names:
        return normalize_authors(" and ".join(names))
    fallback = [p.strip() for p in re.split(r"\band\b|,|;", author_part) if p.strip()]
    return normalize_authors(" and ".join(fallback))


def parse_hspf_profile_publications(profile_html: str, source_url: str):
    block_match = re.search(
        r'<div class="tab-pane"\s+id="tab-academ-\d+-type-contribs">(.*?)</div>\s*<div class="tab-pane"\s+id="tab-academ-\d+-other-activities">',
        profile_html,
        flags=re.S,
    )
    if not block_match:
        return []
    block = block_match.group(1)
    out = []
    current_section = ""
    for para in re.findall(r"<p([^>]*)>(.*?)</p>", block, flags=re.S):
        attrs, body = para
        txt = clean_text(body)
        if not txt:
            continue
        if "wr_hspfo-academ-subheader" in attrs:
            current_section = txt
            continue

        m = re.match(r"^(?P<authors>.+?)\s*\((?P<year>\d{4})\)\.\s*(?P<rest>.+)$", txt)
        if not m:
            continue
        authors_part = m.group("authors").strip()
        year = safe_int(m.group("year"))
        rest = m.group("rest").strip()
        if ". " in rest:
            title, tail = rest.split(". ", 1)
        else:
            title, tail = rest, ""
        title = title.strip().rstrip(".")
        tail = tail.strip()
        if not title:
            continue

        entry_type = map_hspf_section_type(current_section)
        venue_sentence = ""
        if tail:
            # Keep the core citation sentence while avoiding splits on ordinals like "9. ..."
            venue_sentence = re.split(r"(?<!\b\d)\.\s+(?=[A-ZÀ-ÖØ-Þ])", tail, maxsplit=1)[0].strip()
        if entry_type in {"incollection", "inproceedings"} and venue_sentence.lower().startswith("in "):
            venue_sentence = venue_sentence[3:].strip()
        venue_sentence = venue_sentence.strip().rstrip(".")

        pages = ""
        pages_match = re.search(r"(?:pp\.?\s*)?(\d{1,5})\s*[-–]\s*(\d{1,5})", txt, flags=re.I)
        if pages_match:
            pages = f"{pages_match.group(1)}--{pages_match.group(2)}"
        else:
            page_single = re.search(r"\(\s*pp?\.?\s*(\d{1,5})\s*\)", txt, flags=re.I)
            if page_single:
                pages = page_single.group(1)

        venue_sentence = re.sub(r"\(\s*pp?\.?\s*[^)]*\)", "", venue_sentence, flags=re.I).strip(" ,")
        venue_sentence = re.sub(r",\s*\d{1,5}\s*[-–]\s*\d{1,5}\s*$", "", venue_sentence).strip(" ,")
        venue_sentence = re.sub(r"\s+\.", ".", venue_sentence)
        venue_sentence = venue_sentence.strip(" ,.")

        volume = ""
        number = ""
        vm = re.match(r"^(.*?),\s*(\d+)\s*\(([^)]+)\)(?:\s*,\s*pp?\.?\s*[\d–-]+)?\s*$", venue_sentence, flags=re.I)
        if vm:
            venue = vm.group(1).strip()
            volume = vm.group(2).strip()
            number = vm.group(3).strip()
        else:
            venue = venue_sentence

        doi = ""
        doi_match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", txt)
        if doi_match:
            doi = normalize_doi(doi_match.group(0))

        out.append(
            {
                "title": title,
                "norm_title": normalize_title(title),
                "authors": parse_hspf_authors(authors_part),
                "year": year,
                "entry_type": entry_type,
                "venue": venue,
                "volume": volume,
                "number": number,
                "pages": pages,
                "doi": doi,
                "date": str(year or ""),
                "source_url": source_url,
                "section": current_section,
            }
        )
    return out


def dedupe_hspf_rows(rows):
    deduped = []
    for row in rows:
        rn = row.get("norm_title", "")
        ry = row.get("year")
        if not rn:
            continue
        replace_idx = None
        for i, cur in enumerate(deduped):
            cn = cur.get("norm_title", "")
            cy = cur.get("year")
            if rn == cn and (ry is None or cy is None or abs(ry - cy) <= 1):
                replace_idx = i
                break
            if similarity(rn, cn) >= 0.97 and (ry is None or cy is None or abs(ry - cy) <= 1):
                replace_idx = i
                break
        if replace_idx is None:
            deduped.append(row)
            continue
        old = deduped[replace_idx]
        old_score = (40 if old.get("doi") else 0) + len(old.get("authors", "")) + len(old.get("venue", ""))
        new_score = (40 if row.get("doi") else 0) + len(row.get("authors", "")) + len(row.get("venue", ""))
        if new_score > old_score:
            deduped[replace_idx] = row
    return deduped


def dedupe_scholar_rows(rows):
    deduped = []
    for row in rows:
        row_norm = row.get("norm_title", "")
        if not row_norm:
            continue
        row_year = row.get("year")
        match_idx = None
        for i, cur in enumerate(deduped):
            cur_norm = cur.get("norm_title", "")
            cur_year = cur.get("year")
            if row_norm == cur_norm:
                match_idx = i
                break
            if similarity(row_norm, cur_norm) >= 0.97:
                if row_year is None or cur_year is None or abs(row_year - cur_year) <= 1:
                    match_idx = i
                    break
        if match_idx is None:
            deduped.append(row)
            continue

        old = deduped[match_idx]
        old_score = len(old.get("authors", "")) + len(old.get("venue", "")) + (50 if old.get("year") else 0)
        new_score = len(row.get("authors", "")) + len(row.get("venue", "")) + (50 if row.get("year") else 0)
        if new_score > old_score:
            deduped[match_idx] = row
    return deduped


def fetch_openalex_works(author_id: str):
    url = f"https://api.openalex.org/works?filter=author.id:{author_id}&per-page=200"
    payload = json.loads(fetch(url))
    return parse_openalex_works_payload(payload)


def parse_openalex_works_payload(payload: dict):
    results = payload.get("results", [])
    works = []
    for w in results:
        title = w.get("title") or ""
        if not title:
            continue
        venue = ""
        src = (w.get("primary_location") or {}).get("source") or {}
        venue = src.get("display_name") or ""

        authors = []
        for a in w.get("authorships") or []:
            dn = (a.get("author") or {}).get("display_name")
            if dn:
                authors.append(dn)

        primary_loc = w.get("primary_location") or {}
        primary_source = primary_loc.get("source") or {}

        works.append(
            {
                "title": title,
                "norm_title": normalize_title(title),
                "year": w.get("publication_year"),
                "publication_date": w.get("publication_date") or "",
                "type": w.get("type") or "",
                "doi": w.get("doi") or "",
                "url": w.get("id") or "",
                "venue": venue,
                "authors": authors,
                "volume": (w.get("biblio") or {}).get("volume") or "",
                "issue": (w.get("biblio") or {}).get("issue") or "",
                "first_page": (w.get("biblio") or {}).get("first_page") or "",
                "last_page": (w.get("biblio") or {}).get("last_page") or "",
                "publisher": primary_source.get("host_organization_name") or "",
            }
        )
    return works


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def bib_escape(s: str) -> str:
    s = s.replace("\\", "\\\\")
    s = s.replace("{", "\\{").replace("}", "\\}")
    return s


def sanitize_key_fragment(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^A-Za-z0-9]+", "", s)
    return s[:40] or "Work"


def make_unique_key(base: str, used: set[str]) -> str:
    key = base
    idx = 1
    while key in used:
        idx += 1
        key = f"{base}{idx}"
    used.add(key)
    return key


def scholar_authors_to_bib(authors: str) -> str:
    parts = [p.strip() for p in re.split(r",| and ", authors) if p.strip()]
    if not parts:
        return "Raphael Volz"
    return " and ".join(parts)


def _clean_author_text(s: str) -> str:
    s = (s or "").replace("{", "").replace("}", "").replace("\\", "")
    s = re.sub(r"\b(\d{4}|\d{3,})\b", "", s)
    s = re.sub(r"\s+", " ", s).strip(" ,;")
    return s


def _abbrev_given_names(given: str) -> str:
    given = _clean_author_text(given)
    if not given:
        return ""
    pieces = [p for p in re.split(r"\s+", given) if p]
    out = []
    for piece in pieces:
        hy_parts = [h for h in re.split(r"[-–]", piece) if h]
        if len(hy_parts) > 1:
            hy_out = []
            for h in hy_parts:
                m = re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", h)
                if m:
                    hy_out.append(m.group(0).upper() + ".")
            if hy_out:
                out.append("-".join(hy_out))
            continue
        m = re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", piece)
        if m:
            out.append(m.group(0).upper() + ".")
    return " ".join(out)


def _split_author_candidates(authors: str) -> list[str]:
    text = _clean_author_text(authors)
    if not text:
        return []

    and_parts = [p.strip() for p in re.split(r"\band\b", text, flags=re.I) if p.strip()]
    if len(and_parts) > 1:
        return and_parts

    semicolon_parts = [p.strip() for p in text.split(";") if p.strip()]
    if len(semicolon_parts) > 1:
        return semicolon_parts

    comma_tokens = [t.strip() for t in text.split(",") if t.strip()]
    if len(comma_tokens) >= 2 and len(comma_tokens) % 2 == 0:
        even = comma_tokens[0::2]
        odd = comma_tokens[1::2]
        if all(re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", t or "") for t in odd):
            return [f"{even[i]}, {odd[i]}" for i in range(len(even))]

    return comma_tokens if len(comma_tokens) > 1 else [text]


def _format_single_author(name: str) -> str:
    name = _clean_author_text(name)
    if not name:
        return ""

    if "," in name:
        last, first = name.split(",", 1)
    else:
        parts = [p for p in name.split(" ") if p]
        if not parts:
            return ""
        if len(parts) == 1:
            last, first = parts[0], ""
        else:
            last, first = parts[-1], " ".join(parts[:-1])

    last = _clean_author_text(last).upper()
    first_abbrev = _abbrev_given_names(first)
    return f"{last}, {first_abbrev}" if first_abbrev else last


def normalize_authors(authors: str) -> str:
    names = [_format_single_author(x) for x in _split_author_candidates(authors)]
    names = [n for n in names if n]
    return ", ".join(names)


def safe_int(value):
    try:
        return int(value)
    except Exception:
        return None


def normalize_doi(value: str) -> str:
    if not value:
        return ""
    doi = value.strip()
    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("\\_", "_")
    doi = doi.replace("{", "").replace("}", "")
    doi = doi.replace("\\", "")
    return doi.strip()


def latex_escape(text: str) -> str:
    if text is None:
        return ""
    repl = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "^": r"\^{}",
    }
    out = []
    for ch in text:
        out.append(repl.get(ch, ch))
    return "".join(out)


def prepare_tex_text(text: str) -> str:
    if not text:
        return ""
    s = text
    latex_unicode = {
        r"{\"{a}}": "ä",
        r"{\"a}": "ä",
        r"{\"{o}}": "ö",
        r"{\"o}": "ö",
        r"{\"{u}}": "ü",
        r"{\"u}": "ü",
        r"{\"{A}}": "Ä",
        r"{\"A}": "Ä",
        r"{\"{O}}": "Ö",
        r"{\"O}": "Ö",
        r"{\"{U}}": "Ü",
        r"{\"U}": "Ü",
        r"{\ss}": "ß",
        r"{\'{e}}": "é",
        r"{\'e}": "é",
        r"{\~{a}}": "ã",
    }
    for k, v in latex_unicode.items():
        s = s.replace(k, v)
    s = s.replace(r"{\&}", "&").replace(r"\&", "&")
    s = s.replace(r"\_", "_")
    s = s.replace(r"\(", "(").replace(r"\)", ")")
    s = re.sub(r"\\[A-Za-z]+", "", s)
    s = s.replace("\\", "")
    s = s.replace("{", "").replace("}", "")
    return s


def best_openalex_match(title: str, year: int | None, openalex_by_norm: dict, openalex_works: list):
    norm = normalize_title(title or "")
    if not norm:
        return None
    if norm in openalex_by_norm:
        return openalex_by_norm[norm]

    best = (0.0, None)
    for w in openalex_works:
        if year is not None and w.get("year") is not None and abs(int(year) - int(w["year"])) > 2:
            continue
        sim = similarity(norm, w.get("norm_title", ""))
        if sim > best[0]:
            best = (sim, w)
    return best[1] if best[0] >= 0.94 else None




def map_openalex_type(t: str) -> str:
    t = (t or "").lower()
    if t == "article":
        return "article"
    if t in {"proceedings-article", "proceedings"}:
        return "inproceedings"
    if t in {"book-chapter", "reference-entry"}:
        return "incollection"
    if t == "book":
        return "book"
    if t == "dissertation":
        return "phdthesis"
    if t == "report":
        return "techreport"
    return "misc"


def infer_type_from_scholar(venue: str, title: str) -> str:
    v = (venue or "").lower()
    t = (title or "").lower()
    if any(k in v for k in ["journal", "trans.", "transactions", "j. "]):
        return "article"
    if any(
        k in v
        for k in [
            "conference",
            "proceedings",
            "workshop",
            "symposium",
            "hicss",
            "ifip",
            "iswc",
            "www",
            "sac",
            "ekaw",
            "lncs",
        ]
    ):
        return "inproceedings"
    if "handbook" in v or "handbook" in t:
        return "incollection"
    if "corr" in v or "arxiv" in v or "preprint" in v:
        return "misc"
    if any(k in v for k in ["deliverable", "technical report", "report"]):
        return "techreport"
    if "thesis" in v or "thesis" in t:
        return "phdthesis"
    if "book" in v:
        return "book"
    return "misc"


def format_entry(entry_type: str, key: str, fields: dict[str, str]) -> str:
    order = [
        "author",
        "title",
        "journal",
        "booktitle",
        "year",
        "date",
        "volume",
        "number",
        "pages",
        "publisher",
        "doi",
        "url",
        "note",
    ]
    lines = [f"@{entry_type}{{{key},"]
    for f in order:
        v = fields.get(f)
        if v:
            lines.append(f"  {f} = {{{bib_escape(v)}}},")
    if lines[-1].endswith(","):
        lines[-1] = lines[-1][:-1]
    lines.append("}")
    return "\n".join(lines)


def type_bucket(entry_type: str) -> str:
    t = (entry_type or "misc").lower()
    if t == "article":
        return "Journal Articles"
    if t == "inproceedings":
        return "Conference Papers"
    if t == "incollection":
        return "Book Chapters"
    if t == "book":
        return "Books"
    if t in {"phdthesis", "mastersthesis"}:
        return "Theses"
    if t == "techreport":
        return "Technical Reports"
    return "Other Publications"


def entry_quality_score(entry: dict) -> int:
    fields = entry.get("fields", {})
    venue = (fields.get("journal") or fields.get("booktitle") or "").lower()
    score = 0
    if fields.get("doi"):
        score += 50
    if fields.get("pages"):
        score += 10
    if fields.get("venue"):
        score += 5
    if fields.get("journal") or fields.get("booktitle"):
        score += 5
    if "workshop" in venue:
        score -= 10
    if "alternate" in venue or "poster" in venue:
        score -= 8
    return score


def main():
    parser = argparse.ArgumentParser(description="Build Raphael Volz publication bib and CV section")
    parser.add_argument("--scholar-file", help="Path to saved Google Scholar profile HTML")
    parser.add_argument("--dblp-file", help="Path to saved DBLP BibTeX export")
    parser.add_argument("--dblp-xml-file", help="Path to saved DBLP XML export")
    parser.add_argument("--openalex-file", help="Path to saved OpenAlex works JSON")
    parser.add_argument("--hspf-file", help="Path to saved HSPF profile HTML (de)")
    parser.add_argument("--hspf-file-en", help="Path to saved HSPF profile HTML (en)")
    args = parser.parse_args()

    scholar_url = (
        f"https://scholar.google.com/citations?user={SCHOLAR_USER}&hl=en&oe=ASCII&view_op=list_works"
        "&cstart=0&pagesize=100"
    )
    if args.scholar_file:
        scholar_html = read_text_with_fallback(args.scholar_file, preferred_encodings=["latin-1"])
    else:
        scholar_html = fetch(scholar_url)
    scholar_rows = dedupe_scholar_rows(parse_scholar_rows(scholar_html))

    if args.dblp_file:
        dblp_bib = read_text_with_fallback(args.dblp_file, preferred_encodings=["utf-8"])
    else:
        dblp_bib = fetch(f"https://dblp.org/pid/{DBLP_PID}.bib")
    dblp_entries = parse_bibtex_entries(dblp_bib)

    if args.dblp_xml_file:
        dblp_xml = read_text_with_fallback(args.dblp_xml_file, preferred_encodings=["utf-8"])
    else:
        dblp_xml = fetch(f"https://dblp.org/pid/{DBLP_PID}.xml")
    dblp_meta = parse_dblp_xml_metadata(dblp_xml)
    dblp_meta_by_key = {m.get("key", ""): m for m in dblp_meta}

    if args.openalex_file:
        openalex_payload = json.loads(read_text_with_fallback(args.openalex_file, preferred_encodings=["utf-8"]))
        openalex_works = parse_openalex_works_payload(openalex_payload)
    else:
        openalex_works = fetch_openalex_works(OPENALEX_AUTHOR)
    openalex_by_norm = {w["norm_title"]: w for w in openalex_works if w.get("norm_title")}

    if args.hspf_file:
        hspf_de_html = read_text_with_fallback(args.hspf_file, preferred_encodings=["utf-8"])
    else:
        hspf_de_html = fetch(HSPF_PROFILE_DE)
    if args.hspf_file_en:
        hspf_en_html = read_text_with_fallback(args.hspf_file_en, preferred_encodings=["utf-8"])
    else:
        hspf_en_html = fetch(HSPF_PROFILE_EN)

    hspf_rows = dedupe_hspf_rows(
        parse_hspf_profile_publications(hspf_de_html, HSPF_PROFILE_DE)
        + parse_hspf_profile_publications(hspf_en_html, HSPF_PROFILE_EN)
    )
    hspf_by_norm = {}
    for row in hspf_rows:
        norm = row.get("norm_title", "")
        if not norm:
            continue
        current = hspf_by_norm.get(norm)
        if not current:
            hspf_by_norm[norm] = row
            continue
        current_score = (40 if current.get("doi") else 0) + len(current.get("authors", "")) + len(
            current.get("venue", "")
        )
        new_score = (40 if row.get("doi") else 0) + len(row.get("authors", "")) + len(row.get("venue", ""))
        if new_score > current_score:
            hspf_by_norm[norm] = row

    dblp_norms = {e["norm_title"] for e in dblp_meta if e["norm_title"]}

    # Fuzzy duplicate guard against tiny punctuation differences.
    dblp_title_year = [(e["norm_title"], e.get("year")) for e in dblp_meta if e["norm_title"]]

    def is_in_dblp(title_norm: str, year):
        if title_norm in dblp_norms:
            return True
        for dn, dy in dblp_title_year:
            if year is not None and dy is not None and abs(year - dy) > 1:
                continue
            if similarity(title_norm, dn) >= 0.94:
                return True
        return False

    scholar_by_norm = {}
    for row in scholar_rows:
        norm = row.get("norm_title")
        if not norm:
            continue
        current = scholar_by_norm.get(norm)
        if not current:
            scholar_by_norm[norm] = row
            continue
        current_score = len(current.get("authors", "")) + len(current.get("venue", "")) + (50 if current.get("year") else 0)
        new_score = len(row.get("authors", "")) + len(row.get("venue", "")) + (50 if row.get("year") else 0)
        if new_score > current_score:
            scholar_by_norm[norm] = row

    scholar_only = []
    for row in scholar_rows:
        if not row["title"]:
            continue
        if is_in_dblp(row["norm_title"], row.get("year")):
            continue
        # Keep only entries plausibly authored by Raphael Volz.
        has_volz_in_row = "volz" in (row.get("authors") or "").lower()
        if not has_volz_in_row:
            candidate = best_openalex_match(row["title"], row.get("year"), openalex_by_norm, openalex_works)
            has_volz_in_oa = bool(
                candidate and any("volz" in (a or "").lower() for a in (candidate.get("authors") or []))
            )
            if not has_volz_in_oa:
                continue
        scholar_only.append(row)

    used_keys = {e["key"] for e in dblp_entries}

    final_entries = []
    enriched_openalex = 0
    hspf_added = 0

    for e in dblp_entries:
        fields = {k: v for k, v in e.get("fields", {}).items()}
        if fields.get("author"):
            fields["author"] = normalize_authors(fields["author"])
        if fields.get("year") and not fields.get("date"):
            fields["date"] = fields["year"]
        final_entries.append(
            {
                "entry_type": e["entry_type"],
                "key": e["key"],
                "fields": fields,
                "title": clean_text(fields.get("title", "")),
                "norm_title": normalize_title(fields.get("title", "")),
                "year": safe_int(fields.get("year")),
                "source": "dblp",
            }
        )

    for row in scholar_only:
        oaw = best_openalex_match(row["title"], row.get("year"), openalex_by_norm, openalex_works)
        entry_type = infer_type_from_scholar(row.get("venue", ""), row.get("title", ""))
        if entry_type == "misc" and oaw:
            entry_type = map_openalex_type(oaw.get("type", ""))

        if oaw:
            authors = " and ".join(oaw.get("authors") or []) or scholar_authors_to_bib(row.get("authors", ""))
            year = str(oaw.get("year") or row.get("year") or "").strip()
            pages = ""
            if oaw.get("first_page") and oaw.get("last_page"):
                pages = f"{oaw['first_page']}--{oaw['last_page']}"
            elif oaw.get("first_page"):
                pages = str(oaw["first_page"])

            field_venue = "journal" if entry_type == "article" else "booktitle"
            fields = {
                "author": normalize_authors(authors),
                "title": row["title"],
                "year": year,
                "date": (oaw.get("publication_date") or year),
                "doi": normalize_doi(oaw.get("doi") or ""),
                "url": (f"https://doi.org/{normalize_doi(oaw.get('doi') or '')}" if oaw.get("doi") else "")
                or oaw.get("url")
                or row["href"],
                "volume": str(oaw.get("volume") or ""),
                "number": str(oaw.get("issue") or ""),
                "pages": pages,
                "publisher": oaw.get("publisher") or "",
                "note": "Source: Google Scholar profile + OpenAlex metadata",
            }
            venue_value = row.get("venue") or oaw.get("venue") or ""
            if venue_value:
                fields[field_venue] = venue_value
            enriched_openalex += 1
        else:
            field_venue = "journal" if entry_type == "article" else "booktitle"
            fields = {
                "author": normalize_authors(scholar_authors_to_bib(row.get("authors", ""))),
                "title": row["title"],
                "year": str(row["year"] or ""),
                "date": str(row["year"] or ""),
                "url": row["href"],
                "note": "Source: Google Scholar profile entry",
            }
            if row.get("venue"):
                fields[field_venue] = row["venue"]

        base = f"Volz{fields.get('year','ND')}{sanitize_key_fragment(row['title'])[:16]}"
        key = make_unique_key(base, used_keys)
        final_entries.append(
            {
                "entry_type": entry_type,
                "key": key,
                "fields": fields,
                "title": row["title"],
                "norm_title": normalize_title(row["title"]),
                "year": safe_int(fields.get("year")),
                "source": "scholar_openalex" if oaw else "scholar",
            }
        )

    # Add publications found on HSPF profile if not already present from DBLP/Scholar/OpenAlex.
    for row in hspf_rows:
        if not row.get("title"):
            continue
        row_norm = row.get("norm_title", "")
        row_year = row.get("year")
        already_present = False
        for e in final_entries:
            en = e.get("norm_title") or normalize_title(e.get("fields", {}).get("title", ""))
            ey = safe_int(e.get("fields", {}).get("year"))
            if not en:
                continue
            if row_norm and row_norm == en and (row_year is None or ey is None or abs(row_year - ey) <= 1):
                already_present = True
                break
            if row_norm and similarity(row_norm, en) >= 0.96 and (row_year is None or ey is None or abs(row_year - ey) <= 1):
                already_present = True
                break
        if already_present:
            continue

        entry_type = row.get("entry_type") or infer_type_from_scholar(row.get("venue", ""), row.get("title", ""))
        venue_field = "journal" if entry_type == "article" else "booktitle"
        fields = {
            "author": normalize_authors(row.get("authors") or "Raphael Volz"),
            "title": row.get("title", ""),
            "year": str(row.get("year") or ""),
            "date": str(row.get("date") or row.get("year") or ""),
            "pages": row.get("pages") or "",
            "volume": row.get("volume") or "",
            "number": row.get("number") or "",
            "doi": row.get("doi") or "",
            "url": row.get("source_url") or HSPF_PROFILE_DE,
            "note": "Source: Hochschule Pforzheim profile publication list",
        }
        if fields.get("doi"):
            fields["url"] = f"https://doi.org/{normalize_doi(fields['doi'])}"
        if row.get("venue"):
            fields[venue_field] = row["venue"]

        base = f"Volz{fields.get('year','ND')}{sanitize_key_fragment(row['title'])[:16]}"
        key = make_unique_key(base, used_keys)
        final_entries.append(
            {
                "entry_type": entry_type,
                "key": key,
                "fields": fields,
                "title": row.get("title", ""),
                "norm_title": row_norm,
                "year": safe_int(fields.get("year")),
                "source": "hspf",
            }
        )
        hspf_added += 1

    # Second pass: fill missing DOI/date/venue/year from OpenAlex and Scholar fallback.
    for entry in final_entries:
        fields = entry["fields"]
        title = fields.get("title", "")
        year = safe_int(fields.get("year"))
        norm_title = entry.get("norm_title") or normalize_title(title)
        openalex_match = best_openalex_match(title, year, openalex_by_norm, openalex_works)
        scholar_row = scholar_by_norm.get(norm_title)
        hspf_row = hspf_by_norm.get(norm_title)

        if openalex_match:
            doi = normalize_doi(openalex_match.get("doi") or "")
            if doi and not fields.get("doi") and entry.get("source") != "dblp":
                fields["doi"] = doi
            if doi and (
                not fields.get("url")
                or "hs-pforzheim.de/profile/raphaelvolz" in (fields.get("url") or "")
                or "hs-pforzheim.de/en/profile/raphaelvolz" in (fields.get("url") or "")
            ):
                fields["url"] = f"https://doi.org/{doi}"

            if not fields.get("year") and openalex_match.get("year"):
                fields["year"] = str(openalex_match["year"])

            if not fields.get("date"):
                fields["date"] = openalex_match.get("publication_date") or fields.get("year", "")

            venue_field = "journal" if entry["entry_type"] == "article" else "booktitle"
            if not fields.get("journal") and not fields.get("booktitle"):
                venue = openalex_match.get("venue") or ""
                if venue:
                    fields[venue_field] = venue

            if not fields.get("volume") and openalex_match.get("volume"):
                fields["volume"] = str(openalex_match["volume"])
            if not fields.get("number") and openalex_match.get("issue"):
                fields["number"] = str(openalex_match["issue"])
            if not fields.get("pages"):
                fp, lp = openalex_match.get("first_page"), openalex_match.get("last_page")
                if fp and lp:
                    fields["pages"] = f"{fp}--{lp}"
                elif fp:
                    fields["pages"] = str(fp)

        if scholar_row:
            if not fields.get("year") and scholar_row.get("year"):
                fields["year"] = str(scholar_row["year"])
            if not fields.get("date"):
                fields["date"] = str(fields.get("year") or scholar_row.get("year") or "")
            if not fields.get("journal") and not fields.get("booktitle") and scholar_row.get("venue"):
                venue_field = "journal" if entry["entry_type"] == "article" else "booktitle"
                fields[venue_field] = scholar_row["venue"]

        if hspf_row:
            if not fields.get("year") and hspf_row.get("year"):
                fields["year"] = str(hspf_row["year"])
            if not fields.get("date"):
                fields["date"] = str(hspf_row.get("date") or fields.get("year") or "")
            if not fields.get("journal") and not fields.get("booktitle") and hspf_row.get("venue"):
                venue_field = "journal" if entry["entry_type"] == "article" else "booktitle"
                fields[venue_field] = hspf_row["venue"]
            if not fields.get("pages") and hspf_row.get("pages"):
                fields["pages"] = hspf_row["pages"]
            if not fields.get("volume") and hspf_row.get("volume"):
                fields["volume"] = hspf_row["volume"]
            if not fields.get("number") and hspf_row.get("number"):
                fields["number"] = hspf_row["number"]
            if not fields.get("doi") and hspf_row.get("doi"):
                fields["doi"] = normalize_doi(hspf_row["doi"])
            if not fields.get("author") and hspf_row.get("authors"):
                fields["author"] = normalize_authors(hspf_row["authors"])

        if fields.get("year") and not fields.get("date"):
            fields["date"] = fields["year"]
        if fields.get("doi"):
            fields["doi"] = normalize_doi(fields["doi"])
        if entry["entry_type"] == "proceedings" and not fields.get("booktitle") and fields.get("title"):
            fields["booktitle"] = fields["title"]


    dropped_incomplete = 0
    filtered_entries = []
    for entry in final_entries:
        fields = entry["fields"]
        if entry.get("source", "").startswith("scholar"):
            has_year = bool(fields.get("year"))
            has_venue = bool(fields.get("journal") or fields.get("booktitle"))
            has_doi = bool(fields.get("doi"))
            if not has_year or (not has_venue and not has_doi):
                dropped_incomplete += 1
                continue
        filtered_entries.append(entry)
    final_entries = filtered_entries

    # Remove exact publication duplicates (same normalized title and year),
    # keeping the highest-quality record.
    dedup_groups = defaultdict(list)
    dedup_passthrough = []
    for entry in final_entries:
        fields = entry.get("fields", {})
        title_norm = normalize_title(fields.get("title", ""))
        year_value = str(fields.get("year", "")).strip()
        if not title_norm or not year_value:
            dedup_passthrough.append(entry)
            continue
        dedup_groups[(title_norm, year_value)].append(entry)

    dedup_removed = 0
    deduped_entries = []
    for _, group in dedup_groups.items():
        if len(group) == 1:
            deduped_entries.append(group[0])
            continue
        group_sorted = sorted(group, key=entry_quality_score, reverse=True)
        deduped_entries.append(group_sorted[0])
        dedup_removed += len(group_sorted) - 1
    final_entries = dedup_passthrough + deduped_entries

    bib_lines = []
    bib_lines.append("% Auto-generated for Raphael Volz scientific CV")
    bib_lines.append(f"% Generated on {dt.date.today().isoformat()}")
    bib_lines.append("% Sources: Google Scholar profile, DBLP, OpenAlex, Hochschule Pforzheim profile")
    bib_lines.append("\n")

    for e in final_entries:
        bib_lines.append(format_entry(e["entry_type"], e["key"], e["fields"]).strip())
        bib_lines.append("\n")

    OUTPUT_BIB.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_BIB.write_text("\n".join(bib_lines).strip() + "\n", encoding="utf-8")

    all_meta = []
    for e in final_entries:
        fields = e.get("fields", {})
        if e.get("source") == "dblp" and e.get("key") in dblp_meta_by_key:
            dm = dblp_meta_by_key[e["key"]]
            title = dm.get("title", "")
            authors = dm.get("authors", "")
            venue = dm.get("venue", "") or clean_text(fields.get("journal") or fields.get("booktitle") or "")
            year_value = dm.get("year") if dm.get("year") is not None else safe_int(fields.get("year"))
        else:
            title = clean_text(fields.get("title", ""))
            authors = clean_text(normalize_authors(fields.get("author", "")))
            venue = clean_text(fields.get("journal") or fields.get("booktitle") or "")
            year_value = safe_int(fields.get("year"))
        all_meta.append(
            {
                "entry_type": e.get("entry_type", "misc"),
                "key": e.get("key", ""),
                "title": clean_text(title),
                "year": year_value,
                "date": clean_text(fields.get("date", "")),
                "authors": clean_text(normalize_authors(authors)),
                "venue": clean_text(venue),
                "doi": clean_text(fields.get("doi", "")),
            }
        )

    grouped = defaultdict(list)
    for item in all_meta:
        grouped[type_bucket(item["entry_type"])].append(item)

    section_order = [
        "Journal Articles",
        "Conference Papers",
        "Book Chapters",
        "Books",
        "Theses",
        "Technical Reports",
        "Other Publications",
    ]

    tex = []
    tex.append("% Auto-generated by scripts/cv/generate_raphael_volz_publications.py")
    tex.append(f"% Generated on {dt.date.today().isoformat()}")
    tex.append(r"\section*{Literature for Scientific CV}")
    tex.append(
        r"\noindent\textit{Generated automatically from Google Scholar, DBLP, OpenAlex, and Hochschule Pforzheim profile data.}\\"
    )
    tex.append(rf"\noindent\textit{{Generated on: {dt.date.today().isoformat()}}}")
    tex.append("")

    for section in section_order:
        items = grouped.get(section, [])
        if not items:
            continue
        items.sort(key=lambda x: ((x.get("year") or 0), x.get("title") or ""), reverse=True)
        tex.append(rf"\subsection*{{{latex_escape(section)} ({len(items)})}}")
        tex.append(r"\begin{enumerate}")
        for it in items:
            year = str(it["year"]) if it.get("year") else "n.d."
            date = it.get("date") or ""
            authors = it.get("authors") or "Unknown authors"
            title = it.get("title") or "Untitled"
            venue = it.get("venue") or ""
            doi = (it.get("doi") or "").replace("https://doi.org/", "")

            date_fragment = f"; date: {date}" if date and date != year else ""
            line = f"{latex_escape(prepare_tex_text(authors))} ({latex_escape(year)}{latex_escape(date_fragment)}). "
            line += rf"\emph{{{latex_escape(prepare_tex_text(title))}}}."
            if venue:
                line += f" {latex_escape(prepare_tex_text(venue))}."
            if doi:
                line += rf" DOI: \texttt{{{latex_escape(doi)}}}."
            tex.append(r"\item " + line)
        tex.append(r"\end{enumerate}")
        tex.append("")

    OUTPUT_TEX.write_text("\n".join(tex).strip() + "\n", encoding="utf-8")

    qc = {
        "generated_on": dt.date.today().isoformat(),
        "scholar_rows": len(scholar_rows),
        "hspf_rows": len(hspf_rows),
        "dblp_entries": len(dblp_entries),
        "scholar_only_added": len([e for e in final_entries if e.get("source", "").startswith("scholar")]),
        "hspf_only_added": hspf_added,
        "openalex_works_fetched": len(openalex_works),
        "scholar_only_enriched_with_openalex": enriched_openalex,
        "total_entries_in_bib": len(final_entries),
        "scholar_entries_dropped_as_incomplete": dropped_incomplete,
        "entries_removed_as_duplicates": dedup_removed,
        "entries_missing_doi": sum(1 for e in final_entries if not e["fields"].get("doi")),
        "entries_missing_venue": sum(
            1 for e in final_entries if not e["fields"].get("journal") and not e["fields"].get("booktitle")
        ),
        "entries_missing_year": sum(1 for e in final_entries if not e["fields"].get("year")),
        "entries_missing_date": sum(1 for e in final_entries if not e["fields"].get("date")),
    }
    OUTPUT_QC.write_text(json.dumps(qc, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(qc, indent=2))


if __name__ == "__main__":
    main()
