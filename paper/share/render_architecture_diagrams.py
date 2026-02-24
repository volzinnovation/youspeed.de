#!/usr/bin/env python3
"""Render technical architecture diagrams as PNG files.

Outputs:
- TECHNICAL_ARCHITECTURE.png
- TECHNICAL_ARCHITECTURE_PAPER_SCOPE.png
- TECHNICAL_ARCHITECTURE_PAPER_SCOPE_BLIND.png
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
import math

from PIL import Image, ImageDraw, ImageFont


OUT_DIR = Path(__file__).resolve().parent
FULL_OUT = OUT_DIR / "TECHNICAL_ARCHITECTURE.png"
SCOPE_OUT = OUT_DIR / "TECHNICAL_ARCHITECTURE_PAPER_SCOPE.png"
BLIND_SCOPE_OUT = OUT_DIR / "TECHNICAL_ARCHITECTURE_PAPER_SCOPE_BLIND.png"


CANVAS_W = 2400
CANVAS_H = 960


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates: List[str] = []
    if bold:
        candidates.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/System/Library/Fonts/Supplemental/Helvetica.ttc",
            ]
        )
    candidates.extend(
        [
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Supplemental/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


F_TITLE = load_font(42, bold=True)
F_SECTION = load_font(30, bold=True)
F_NODE = load_font(21)
F_NODE_BOLD = load_font(22, bold=True)
F_SMALL = load_font(18)


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int


def rounded_box(
    draw: ImageDraw.ImageDraw,
    box: Box,
    fill: Tuple[int, int, int],
    outline: Tuple[int, int, int] = (80, 80, 80),
    radius: int = 14,
    width: int = 3,
) -> None:
    draw.rounded_rectangle(
        [box.x, box.y, box.x + box.w, box.y + box.h],
        radius=radius,
        fill=fill,
        outline=outline,
        width=width,
    )


def wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def draw_node(
    draw: ImageDraw.ImageDraw,
    box: Box,
    label: str,
    fill: Tuple[int, int, int],
    *,
    title: bool = False,
    dimmed: bool = False,
) -> None:
    if dimmed:
        fill = tuple(int(c * 0.82 + 255 * 0.18) for c in fill)
        outline = (165, 165, 165)
        text_color = (112, 112, 112)
    else:
        outline = (102, 102, 102)
        text_color = (35, 35, 35)

    rounded_box(draw, box, fill=fill, outline=outline, radius=13, width=3)

    font = F_NODE_BOLD if title else F_NODE
    lines = wrap_text(draw, label, font, box.w - 18)
    line_height = font.getbbox("Ag")[3] - font.getbbox("Ag")[1] + 2
    y = box.y + (box.h - line_height * len(lines)) // 2
    for line in lines:
        w = draw.textlength(line, font=font)
        draw.text((box.x + (box.w - w) / 2, y), line, font=font, fill=text_color)
        y += line_height


def draw_section(
    draw: ImageDraw.ImageDraw, box: Box, title: str, fill: Tuple[int, int, int]
) -> None:
    rounded_box(draw, box, fill=fill, outline=(95, 95, 95), radius=18, width=4)
    draw.text((box.x + 14, box.y + 10), title, font=F_SECTION, fill=(45, 45, 45))


def anchor(box: Box, side: str) -> Tuple[int, int]:
    if side == "left":
        return (box.x, box.y + box.h // 2)
    if side == "right":
        return (box.x + box.w, box.y + box.h // 2)
    if side == "top":
        return (box.x + box.w // 2, box.y)
    if side == "bottom":
        return (box.x + box.w // 2, box.y + box.h)
    raise ValueError(f"invalid side: {side}")


def arrow_head(
    draw: ImageDraw.ImageDraw,
    p0: Tuple[int, int],
    p1: Tuple[int, int],
    color: Tuple[int, int, int],
    size: int = 10,
) -> None:
    x0, y0 = p0
    x1, y1 = p1
    angle = math.atan2(y1 - y0, x1 - x0)
    p2 = (
        x1 - size * math.cos(angle) + size * 0.55 * math.sin(angle),
        y1 - size * math.sin(angle) - size * 0.55 * math.cos(angle),
    )
    p3 = (
        x1 - size * math.cos(angle) - size * 0.55 * math.sin(angle),
        y1 - size * math.sin(angle) + size * 0.55 * math.cos(angle),
    )
    draw.polygon([p1, p2, p3], fill=color)


def draw_path(
    draw: ImageDraw.ImageDraw, points: Iterable[Tuple[int, int]], *, dimmed: bool = False
) -> None:
    points = list(points)
    color = (72, 72, 72) if not dimmed else (170, 170, 170)
    width = 4 if not dimmed else 3
    draw.line(points, fill=color, width=width)
    arrow_head(draw, points[-2], points[-1], color)


def to_manhattan(points: Iterable[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Return a polyline with only horizontal/vertical segments."""
    pts = list(points)
    if not pts:
        return []
    out = [pts[0]]
    for x1, y1 in pts[1:]:
        x0, y0 = out[-1]
        if x0 != x1 and y0 != y1:
            out.append((x1, y0))
        if out[-1] != (x1, y1):
            out.append((x1, y1))
    # Drop accidental duplicates.
    compact: List[Tuple[int, int]] = [out[0]]
    for p in out[1:]:
        if p != compact[-1]:
            compact.append(p)
    return compact


def draw_path_bidirectional(
    draw: ImageDraw.ImageDraw, points: Iterable[Tuple[int, int]], *, dimmed: bool = False
) -> None:
    points = to_manhattan(points)
    color = (72, 72, 72) if not dimmed else (170, 170, 170)
    width = 4 if not dimmed else 3
    draw.line(points, fill=color, width=width)
    arrow_head(draw, points[-2], points[-1], color)
    arrow_head(draw, points[1], points[0], color)


def connect(
    draw: ImageDraw.ImageDraw,
    a: Box,
    a_side: str,
    b: Box,
    b_side: str,
    *,
    via: List[Tuple[int, int]] | None = None,
    dimmed: bool = False,
) -> None:
    points = [anchor(a, a_side)]
    if via:
        points.extend(via)
    points.append(anchor(b, b_side))
    points = to_manhattan(points)
    draw_path(draw, points, dimmed=dimmed)


def connect_bidirectional(
    draw: ImageDraw.ImageDraw,
    a: Box,
    a_side: str,
    b: Box,
    b_side: str,
    *,
    via: List[Tuple[int, int]] | None = None,
    dimmed: bool = False,
) -> None:
    points = [anchor(a, a_side)]
    if via:
        points.extend(via)
    points.append(anchor(b, b_side))
    points = to_manhattan(points)
    draw_path_bidirectional(draw, points, dimmed=dimmed)


def render(scope_mode: bool, out_path: Path, *, blind_review: bool = False) -> None:
    image = Image.new("RGB", (CANVAS_W, CANVAS_H), "white")
    draw = ImageDraw.Draw(image)

    title = "Technical Architecture" if blind_review else "YouSpeed Technical Architecture"
    tw = draw.textlength(title, font=F_TITLE)
    draw.text(((CANVAS_W - tw) / 2, 8), title, font=F_TITLE, fill=(24, 24, 24))

    # Section containers
    ext = Box(20, 56, 340, 470)
    cloud = Box(380, 56, 930, 840)
    device = Box(1330, 56, 1050, 840)

    draw_section(draw, ext, "External Systems", (239, 245, 252))
    draw_section(
        draw,
        cloud,
        "Backend Platform" if blind_review else "YouSpeed Backend Platform",
        (240, 248, 239),
    )
    draw_section(draw, device, "User Device (No Account, Device ID)", (252, 245, 237))

    # Nodes
    n: Dict[str, Box] = {
        "osm_src": Box(45, 112, 290, 76),
        "rules": Box(45, 216, 290, 76),
        "osm_api": Box(45, 320, 290, 76),
        "ingest": Box(430, 112, 230, 76),
        "build": Box(740, 112, 230, 76),
        "release": Box(1050, 112, 230, 76),
        "api": Box(740, 214, 230, 76),
        "obs_in": Box(430, 314, 230, 76),
        "trust": Box(740, 314, 230, 76),
        "validate": Box(1010, 314, 230, 76),
        "merge": Box(740, 434, 230, 76),
        "global": Box(740, 534, 230, 76),
        "export": Box(430, 654, 230, 76),
        "loc": Box(1385, 108, 250, 76),
        "app": Box(1695, 108, 250, 76),
        "base": Box(1385, 210, 250, 76),
        "infer": Box(1695, 210, 250, 76),
        "overlay": Box(2005, 210, 340, 76),
        "cv": Box(1385, 312, 250, 76),
        "norm": Box(1695, 312, 250, 76),
        "voice": Box(2005, 312, 340, 76),
        "local": Box(1695, 414, 250, 76),
        "queue": Box(1695, 514, 250, 76),
        "sync": Box(1695, 654, 250, 84),
    }

    labels: Dict[str, str] = {
        "osm_src": "OpenStreetMap snapshots and diffs",
        "rules": "Regulatory and rule datasets",
        "osm_api": "OSM contribution interface",
        "ingest": "Baseline ingestion pipeline",
        "build": "Bundle and delta builder",
        "release": "Release artifact publisher",
        "api": "Sync and observation API",
        "obs_in": "Observation intake service",
        "trust": "Device-ID trust service",
        "validate": "Spatial and rule validation",
        "merge": "Conflict resolver and merge",
        "global": "Global speed intelligence store",
        "export": "OSM export moderation queue",
        "loc": "Location and heading input",
        "app": "Mobile app shell" if blind_review else "YouSpeed iOS app shell",
        "base": "Baseline runtime database",
        "infer": "Offline inference engine",
        "overlay": "Local confidence overlay",
        "cv": "On-device CV module",
        "norm": "Observation normalization",
        "voice": "Voice and speech module",
        "local": "Local sign observation store",
        "queue": "Offline sync queue",
        "sync": "Sync and update manager",
    }

    paper_scope = {
        "osm_src",
        "rules",
        "ingest",
        "build",
        "release",
        "loc",
        "app",
        "base",
        "infer",
        "overlay",
    }

    title_nodes = {"app", "infer", "sync"}

    def is_dim(k1: str, k2: str) -> bool:
        return scope_mode and not ({k1, k2} <= paper_scope)

    for key, box in n.items():
        if key in {"osm_src", "rules", "osm_api"}:
            fill = (224, 239, 251)
        elif key in {
            "ingest",
            "build",
            "release",
            "api",
            "obs_in",
            "trust",
            "validate",
            "merge",
            "global",
            "export",
        }:
            fill = (222, 240, 218)
        else:
            fill = (250, 232, 214)

        draw_node(
            draw,
            box,
            labels[key],
            fill,
            title=key in title_nodes,
            dimmed=scope_mode and key not in paper_scope,
        )

    if scope_mode:
        for key in paper_scope:
            b = n[key]
            draw.rounded_rectangle(
                [b.x - 3, b.y - 3, b.x + b.w + 3, b.y + b.h + 3],
                radius=14,
                outline=(36, 112, 232),
                width=4,
            )

    # External to baseline
    connect(draw, n["osm_src"], "right", n["ingest"], "left", dimmed=is_dim("osm_src", "ingest"))
    connect(
        draw,
        n["rules"],
        "right",
        n["ingest"],
        "left",
        via=[(400, anchor(n["rules"], "right")[1]), (400, anchor(n["ingest"], "left")[1])],
        dimmed=is_dim("rules", "ingest"),
    )

    # Baseline pipeline
    connect(draw, n["ingest"], "right", n["build"], "left", dimmed=is_dim("ingest", "build"))
    connect(draw, n["build"], "right", n["release"], "left", dimmed=is_dim("build", "release"))
    connect(
        draw,
        n["release"],
        "bottom",
        n["api"],
        "top",
        via=[
            (anchor(n["release"], "bottom")[0], 198),
            (anchor(n["api"], "top")[0], 198),
        ],
        dimmed=scope_mode,
    )

    # API fan-out and observation pipeline
    connect(
        draw,
        n["api"],
        "left",
        n["obs_in"],
        "top",
        via=[(700, 252), (700, 306), (545, 306)],
        dimmed=scope_mode,
    )
    connect(draw, n["api"], "bottom", n["trust"], "top", dimmed=scope_mode)
    connect(
        draw,
        n["api"],
        "right",
        n["validate"],
        "top",
        via=[(1060, 252), (1060, 306), (1125, 306)],
        dimmed=scope_mode,
    )
    connect(draw, n["obs_in"], "right", n["trust"], "left", dimmed=scope_mode)
    connect(draw, n["trust"], "right", n["validate"], "left", dimmed=scope_mode)
    connect(draw, n["trust"], "bottom", n["merge"], "top", dimmed=scope_mode)
    connect(
        draw,
        n["validate"],
        "left",
        n["merge"],
        "right",
        via=[(992, 352), (992, 472)],
        dimmed=scope_mode,
    )
    connect(draw, n["merge"], "bottom", n["global"], "top", dimmed=scope_mode)
    connect(
        draw,
        n["global"],
        "right",
        n["api"],
        "right",
        via=[(1286, 572), (1286, 252)],
        dimmed=scope_mode,
    )

    # Export loop
    connect(
        draw,
        n["global"],
        "left",
        n["export"],
        "right",
        via=[(700, 572), (700, 692)],
        dimmed=scope_mode,
    )
    connect(
        draw,
        n["export"],
        "left",
        n["osm_api"],
        "right",
        via=[(370, 692), (370, 358)],
        dimmed=scope_mode,
    )

    # Device inference path
    connect(
        draw,
        n["loc"],
        "right",
        n["infer"],
        "top",
        via=[(1670, 146), (1670, 198), (1820, 198)],
        dimmed=is_dim("loc", "infer"),
    )
    connect(draw, n["base"], "right", n["infer"], "left", dimmed=is_dim("base", "infer"))
    connect(draw, n["overlay"], "left", n["infer"], "right", dimmed=is_dim("overlay", "infer"))
    connect(draw, n["infer"], "top", n["app"], "bottom", dimmed=is_dim("infer", "app"))

    # Local observation capture path
    connect(draw, n["cv"], "right", n["norm"], "left", dimmed=scope_mode)
    connect(draw, n["voice"], "left", n["norm"], "right", dimmed=scope_mode)
    connect(
        draw,
        n["loc"],
        "left",
        n["norm"],
        "top",
        via=[(1340, 146), (1340, 298), (1820, 298)],
        dimmed=scope_mode,
    )
    connect(draw, n["norm"], "bottom", n["local"], "top", dimmed=scope_mode)
    connect(
        draw,
        n["local"],
        "right",
        n["overlay"],
        "right",
        via=[(2360, 452), (2360, 248)],
        dimmed=scope_mode,
    )
    connect(draw, n["local"], "bottom", n["queue"], "top", dimmed=scope_mode)
    connect(draw, n["queue"], "bottom", n["sync"], "top", dimmed=scope_mode)

    # Sync channels (separate lanes to avoid overlap)
    connect_bidirectional(
        draw,
        n["api"],
        "right",
        n["sync"],
        "left",
        via=[(1286, 252), (1286, 716)],
        dimmed=scope_mode,
    )
    connect(
        draw,
        n["sync"],
        "top",
        n["base"],
        "bottom",
        via=[(1368, 654), (1368, 298), (1510, 298)],
        dimmed=scope_mode,
    )
    connect(
        draw,
        n["sync"],
        "right",
        n["overlay"],
        "right",
        via=[(2368, 696), (2368, 248)],
        dimmed=scope_mode,
    )

    # Footer
    footer = Box(20, 910, 2360, 40)
    rounded_box(draw, footer, fill=(247, 247, 247), outline=(152, 152, 152), radius=8, width=2)
    if scope_mode:
        text = "Paper scope highlighted in blue: top two rows only, excluding Sync and observation API."
        color = (36, 112, 232)
    else:
        text = "Flow semantics: baseline updates, local-first observations, device-ID based sync and validated global merge."
        color = (70, 70, 70)
    draw.text((34, 920), text, font=F_SMALL, fill=color)

    image.save(out_path, "PNG")


def main() -> None:
    render(scope_mode=False, out_path=FULL_OUT)
    render(scope_mode=True, out_path=SCOPE_OUT)
    render(scope_mode=True, out_path=BLIND_SCOPE_OUT, blind_review=True)
    print(FULL_OUT)
    print(SCOPE_OUT)
    print(BLIND_SCOPE_OUT)


if __name__ == "__main__":
    main()
