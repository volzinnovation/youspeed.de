#!/usr/bin/env python3
"""Build a local HTML gallery from original native country-review PNGs and JSON.

No screenshots are generated, altered, copied, uploaded, or replaced. Run after
both native capture scripts, optionally with --require-complete for all 66 scenes.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from html import escape
import json
from pathlib import Path
import struct
from urllib.parse import quote


GROUPS = {
    "FR-fr": ("France", "French", "FRA", [0, 2, 10, 25, 35, 45, 55]),
    "NL-nl": ("Netherlands", "Dutch", "NLD", [0, 2, 10, 35, 45, 55]),
    "BE-nl": ("Belgium", "Dutch", "BEL", [0, 5, 15, 25, 35, 45]),
    "BE-fr": ("Belgium", "French", "BEL", [0, 5, 15, 25, 35, 45]),
    "BE-de": ("Belgium", "German", "BEL", [0, 5, 15, 25, 35, 45]),
}
PLATFORMS = {"android": "Android", "iphone": "iPhone"}


def link(path: Path, root: Path) -> str:
    return quote(path.relative_to(root).as_posix(), safe="/")


def collect(root: Path) -> tuple[list[dict], list[str]]:
    captures, warnings = [], []
    for platform in PLATFORMS:
        for group, (country, language, code, deltas) in GROUPS.items():
            expected = {(delta, 50) for delta in deltas}
            if group == "FR-fr":
                expected |= {(2, 70), (10, 70)}
            seen = Counter()
            for metadata in sorted((root / platform / group).glob("*.json")):
                picture = metadata.with_suffix(".png")
                if not picture.is_file():
                    warnings.append(f"Missing PNG: {link(metadata, root)}")
                    continue
                try:
                    report = json.loads(metadata.read_text())
                    delta = int(report["delta_kmh"])
                    limit = int(report.get("posted_limit_kmh", report.get("limit_kmh")))
                    if report["country"] != code:
                        raise ValueError(f"reported country {report['country']} does not match {code}")
                    if str(report["locale"]).replace("_", "-").split("-")[0] != group.split("-")[1]:
                        raise ValueError("reported language does not match folder")
                    png = picture.read_bytes()
                    if png[:8] != b"\x89PNG\r\n\x1a\n":
                        raise ValueError("not a PNG")
                    width, height = struct.unpack(">II", png[16:24])
                    digest = hashlib.sha256(png).hexdigest()
                    if report.get("screenshot_sha256", digest) != digest:
                        raise ValueError("PNG checksum differs from capture report")
                except (ValueError, KeyError, TypeError, struct.error) as error:
                    warnings.append(f"Invalid capture {link(metadata, root)}: {error}")
                    continue
                displayed = report.get("displayed", {})
                captures.append(dict(
                    platform=platform, group=group, country=country, language=language,
                    delta=delta, limit=limit, speed=limit + delta, width=width, height=height,
                    image=link(picture, root), metadata=link(metadata, root), sha256=digest,
                    title=report.get("title", displayed.get("penalty-notice-title", "")) or "No penalty warning",
                    details=report.get("details", displayed.get("penalty-notice-details", "")) or "",
                    inside_city=report.get("inside_city"),
                ))
                seen[(delta, limit)] += 1
            for delta, limit in sorted(expected - set(seen)):
                warnings.append(f"Awaiting {platform}/{group}: +{delta} km/h at limit {limit}")
            for case, count in seen.items():
                if count > 1:
                    warnings.append(f"Duplicate scenario {platform}/{group}: {case} ({count} captures)")
                if case not in expected:
                    warnings.append(f"Additional scenario {platform}/{group}: {case}")
    return captures, warnings


CSS = """
:root{color-scheme:light;font:15px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#202421;background:#f4f3ef}
*{box-sizing:border-box}body{margin:0}a{color:#285b47;text-underline-offset:3px}header,main,footer{max-width:1320px;margin:auto;padding:32px}
header{padding-top:52px;padding-bottom:20px}.eyebrow{text-transform:uppercase;font-size:12px;letter-spacing:.12em;color:#626b63}
h1{font-size:clamp(30px,5vw,52px);line-height:1.1;letter-spacing:-.035em;margin:14px 0 18px}h2{font-size:26px;margin:0}h3{font-size:17px;margin:0}
p{margin:10px 0}.lede{max-width:850px;font-size:18px;color:#515952}.summary{display:flex;gap:24px;flex-wrap:wrap;margin-top:24px}.summary strong{font-size:24px;margin-right:7px}
.status{padding:12px 16px;background:#e4eee7;border-left:4px solid #417652;border-radius:3px}.status.pending{background:#fff0d3;border-color:#ab7020}
details{max-width:1000px;margin-top:18px}summary{cursor:pointer;font-weight:600}details p{color:#515952}.filters{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0 40px;padding-bottom:20px;border-bottom:1px solid #d9dcd6}
label{font-size:12px;color:#566056;display:grid;gap:4px}select{font:inherit;font-size:14px;border:1px solid #bcc5bd;border-radius:7px;background:white;padding:9px 30px 9px 10px;min-width:140px}
.group{margin-bottom:48px}.grouphead{display:flex;align-items:baseline;gap:14px;margin-bottom:16px;flex-wrap:wrap}.grouphead span{color:#667068;font-size:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:20px}.capture{min-width:0;background:#fff;border:1px solid #dfe3dc;border-radius:12px;overflow:hidden}
.image{display:flex;justify-content:center;align-items:center;background:#e8eae4;padding:14px;min-height:380px}.image img{display:block;height:auto;max-height:440px;max-width:100%;object-fit:contain;box-shadow:0 5px 20px #0002}
.caption{padding:16px}.tag{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#657065}.inputs{font-variant-numeric:tabular-nums;font-size:13px;color:#4c574f;margin:9px 0}.caption h3{margin:6px 0}.detail{font-size:13px;color:#4c574f}.links{display:flex;gap:16px;font-size:12px;margin-top:14px}
.empty{color:#626b63;padding:25px;border:1px dashed #bdc6be;border-radius:8px}.count{color:#5f695f;font-size:13px;align-self:end;margin-bottom:10px}footer{border-top:1px solid #d7ded5;color:#5e685f;font-size:12px}
[hidden]{display:none!important}@media(max-width:600px){header,main,footer{padding:22px}.grid{grid-template-columns:1fr}.image img{max-height:560px}.image{min-height:0}}@media print{.filters{display:none}.capture{break-inside:avoid}.grid{grid-template-columns:repeat(3,1fr)}.image img{max-height:280px}.group{break-before:page}}
"""


def render(root: Path, captures: list[dict], warnings: list[str]) -> str:
    groups = []
    for platform, platform_name in PLATFORMS.items():
        for group, (country, language, _code, _deltas) in GROUPS.items():
            scenes = sorted((c for c in captures if c["platform"] == platform and c["group"] == group),
                            key=lambda c: (c["limit"], c["delta"], c["image"]))
            cards = []
            for c in scenes:
                context = ""
                if isinstance(c["inside_city"], bool):
                    context = " · built-up context" if c["inside_city"] else " · outside built-up context"
                alt = f"{platform_name}, {country} in {language}: simulated speed {c['speed']} km/h, posted limit {c['limit']} km/h"
                cards.append(f'''<article class="capture" data-platform="{platform}" data-country="{country}" data-language="{language}" data-kind="{'safe' if c['delta'] == 0 else 'warning'}" data-limit="{c['limit']}">
<a class="image" href="{c['image']}" target="_blank" rel="noopener"><img loading="lazy" src="{c['image']}" width="{c['width']}" height="{c['height']}" alt="{escape(alt, quote=True)}"></a>
<div class="caption"><div class="tag">{'No excess' if c['delta'] == 0 else f'+{c["delta"]} km/h excess'}</div>
<div class="inputs">Speed {c['speed']} · limit {c['limit']} km/h{context}</div><h3>{escape(c['title'])}</h3>
{f'<p class="detail">{escape(c["details"])}</p>' if c['details'] else ''}
<div class="links"><a href="{c['image']}" target="_blank" rel="noopener">Original PNG</a><a href="{c['metadata']}" target="_blank" rel="noopener">Capture JSON</a></div></div></article>''')
            groups.append(f'''<section class="group"><div class="grouphead"><h2>{platform_name} · {country}</h2><span>{language} · {group} · {len(scenes)} captures</span></div>
<div class="grid">{''.join(cards)}</div>{'<p class="empty">Native captures are not available yet.</p>' if not scenes else ''}</section>''')
    status = f"{len(captures)} of 66 planned native scenes available."
    if warnings:
        status += " Capture set incomplete or requires review."
    else:
        status += " Every planned country, language and penalty-band scene is present."
    warning_html = ""
    if warnings:
        warning_html = '<details><summary>Capture completeness notes</summary><ul>' + ''.join(f'<li>{escape(w)}</li>' for w in warnings) + '</ul></details>'
    manifests = ' · '.join(f'<a href="{platform}/manifest.json">{label} manifest</a>' for platform, label in PLATFORMS.items() if (root / platform / 'manifest.json').is_file())
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>YouSpeed — country UI review</title><style>{CSS}</style></head><body>
<header><div class="eyebrow">YouSpeed · Native UI review · 9 September 2026</div><h1>Country rules, in the app.</h1><p class="lede">Original Android emulator and iPhone simulator captures for France, the Netherlands and Belgium, across each warning band and the no-excess state.</p>
<div class="summary"><span><strong>{len(captures)}</strong> original captures</span><span><strong>3</strong> countries</span><span><strong>5</strong> country/language pairs</span><span><strong>2</strong> platforms</span></div>
<p class="status {'pending' if warnings else ''}">{escape(status)}</p>{warning_html}
<details><summary>What these screenshots verify — and what is simulated</summary>
<p>The native apps receive simulated city GPS fixes, posted road limits and driving speeds. Their production country selector, bundled rule parser and UI render the result. Speed equals posted limit plus the scenario’s excess. These are repeatable UI scenarios, not recordings of a road drive, real enforcement measurements or a live border crossing. France’s extra +2 and +10 scenes use a 70 km/h posted limit to check the limit-dependent amount. A safe scene means no excess in this scenario.</p>
<p>The offline catalog describes buffered map-extract coverage, not authoritative national borders. Overlapping coverage or an invalid, stale or unresolved fix makes country-specific penalties unavailable. A country transition requires three valid fixes spanning at least 15 seconds; accepted fixes are at most 30 seconds old with reported accuracy at most 100 metres. The selected country must not silently revert to Germany during uncertainty.</p>
<p>Penalty values are indicative. The displayed excess is simulated GPS speed minus a detected limit; no universal enforcement tolerance has been deducted. A missing scalar fine, point count or ban duration is not zero and must not become an invented number. Original capture JSON provides the recorded evidence for each scene.</p>
<p>Main and runtime translation work covers English, German, French and Dutch. This gallery visually covers French, Dutch and German main-screen scenes, not every language or settings screen. Android’s static UI resources also cover Spanish, Italian, Polish, Brazilian Portuguese and Swedish; its runtime messages still fall back to English in those languages. Complete end-to-end translation coverage in those other locales is not claimed.</p>
<p>Images are linked directly to their original PNG files. The gallery performs no image editing or recomposition and sends no data to any server.</p></details></header>
<main><div class="filters" aria-label="Gallery filters">
<label>Platform<select id="platform"><option value="">Both platforms</option><option>Android</option><option>iPhone</option></select></label>
<label>Country<select id="country"><option value="">All countries</option><option>France</option><option>Netherlands</option><option>Belgium</option></select></label>
<label>Language<select id="language"><option value="">All languages</option><option>French</option><option>Dutch</option><option>German</option></select></label>
<label>Scenario<select id="kind"><option value="">All scenarios</option><option value="safe">No excess</option><option value="warning">Warning bands</option><option value="limit70">France · limit 70</option></select></label><span class="count" id="visible-count" aria-live="polite">{len(captures)} captures shown</span></div>
{''.join(groups)}<p id="no-results" class="empty" hidden>No captured scenarios match these filters.</p></main>
<footer>Generated {generated}. <a href="gallery-manifest.json">Gallery manifest and PNG checksums</a>{' · ' + manifests if manifests else ''}. Open any image to inspect its full native resolution.</footer>
<script>const controls=['platform','country','language','kind'].map(id=>document.getElementById(id));
function filter(){{const [platform,country,language,kind]=controls.map(el=>el.value.toLowerCase());let visible=0;
document.querySelectorAll('.capture').forEach(card=>{{const d=card.dataset;const show=(!platform||d.platform===platform)&&(!country||d.country.toLowerCase()===country)&&(!language||d.language.toLowerCase()===language)&&(!kind||(kind==='limit70'?d.limit==='70':d.kind===kind));card.hidden=!show;visible+=show?1:0;}});
document.querySelectorAll('.group').forEach(group=>{{group.hidden=!group.querySelector('.capture:not([hidden])');}});document.getElementById('visible-count').textContent=visible+' captures shown';document.getElementById('no-results').hidden=visible>0;}}
controls.forEach(el=>el.addEventListener('change',filter));</script></body></html>'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="Folder containing android/ and iphone/ captures")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    captures, warnings = collect(root)
    (root / "index.html").write_text(render(root, captures, warnings), encoding="utf-8")
    (root / "gallery-manifest.json").write_text(json.dumps(dict(
        expected_count=66, capture_count=len(captures), complete=not warnings,
        notes=warnings, captures=captures,
    ), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Gallery: {root / 'index.html'} ({len(captures)}/66 captures, {len(warnings)} completeness notes)")
    return 1 if args.require_complete and warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
