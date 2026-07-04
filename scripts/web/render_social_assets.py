#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFilter, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = REPO_ROOT / "Web"
SCREENSHOT_ROOT = WEB_ROOT / "assets" / "screenshots"
ICON_SOURCE = (
    REPO_ROOT
    / "iphone"
    / "SpeedConsumerApp"
    / "Assets.xcassets"
    / "AppIcon.appiconset"
    / "icon-1024.png"
)
SOCIAL_ROOT = WEB_ROOT / "assets" / "social"
ICON_ROOT = WEB_ROOT / "assets" / "icons"

FONT_REGULAR = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
FONT_BOLD = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")

LOCALES = {
    "de": {
        "title": "YouSpeed",
        "subtitle": "Live-Tempolimit mit Offline-Karten",
        "detail": "iPhone zuerst · Android Alpha · Keine Werbung, kein Tracking",
    },
    "en": {
        "title": "YouSpeed",
        "subtitle": "Live speed-limit assist with offline maps",
        "detail": "iPhone first · Android alpha · No ads, no tracking",
    },
    "fr": {
        "title": "YouSpeed",
        "subtitle": "Assistant de vitesse avec cartes hors ligne",
        "detail": "iPhone d'abord · Android alpha · Sans publicité, sans suivi",
    },
    "nl": {
        "title": "YouSpeed",
        "subtitle": "Live snelheidslimiet met offline kaarten",
        "detail": "iPhone eerst · Android alpha · Geen advertenties, geen tracking",
    },
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else FONT_REGULAR
    if path.exists():
        return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    image = image.convert("RGBA")
    scale = max(size[0] / image.width, size[1] / image.height)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.LANCZOS,
    )
    left = (resized.width - size[0]) // 2
    top = (resized.height - size[1]) // 2
    return resized.crop((left, top, left + size[0], top + size[1]))


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    return mask


def paste_rounded(
    base: Image.Image,
    image: Image.Image,
    xy: tuple[int, int],
    size: tuple[int, int],
    radius: int,
    border: tuple[int, int, int, int] | None = None,
) -> None:
    thumb = cover(image, size)
    mask = rounded_mask(size, radius)

    shadow = Image.new("RGBA", size, (0, 0, 0, 220))
    shadow.putalpha(mask.filter(ImageFilter.GaussianBlur(18)))
    base.alpha_composite(shadow, (xy[0] + 10, xy[1] + 18))

    base.paste(thumb, xy, mask)
    if border:
        draw = ImageDraw.Draw(base)
        draw.rounded_rectangle(
            (xy[0], xy[1], xy[0] + size[0], xy[1] + size[1]),
            radius=radius,
            outline=border,
            width=2,
        )


def draw_wrapped(
    draw: ImageDraw.ImageDraw,
    text: str,
    xy: tuple[int, int],
    max_chars: int,
    text_font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    line_gap: int,
) -> int:
    x, y = xy
    for line in wrap(text, width=max_chars):
        draw.text((x, y), line, font=text_font, fill=fill)
        bbox = draw.textbbox((x, y), line, font=text_font)
        y += bbox[3] - bbox[1] + line_gap
    return y


def render_social(locale: str, strings: dict[str, str]) -> None:
    width, height = 1200, 630
    canvas = Image.new("RGBA", (width, height), "#0b0e10")
    draw = ImageDraw.Draw(canvas)

    # Road plane and lane marks.
    draw.polygon([(610, 0), (1200, 0), (1200, 630), (765, 630)], fill="#11171a")
    draw.line((820, 0, 610, 630), fill=(255, 255, 255, 30), width=4)
    draw.line((1020, 0, 960, 630), fill=(245, 166, 35, 52), width=5)
    for offset in range(-20, 720, 92):
        draw.line((970, offset, 950, offset + 48), fill=(255, 255, 255, 48), width=8)

    # App icon.
    icon = Image.open(ICON_SOURCE).convert("RGBA")
    icon_size = (88, 88)
    icon_thumb = cover(icon, icon_size)
    canvas.paste(icon_thumb, (74, 70), rounded_mask(icon_size, 22))

    draw.text((74, 178), strings["title"], font=font(72, bold=True), fill="#ffffff")
    next_y = draw_wrapped(
        draw,
        strings["subtitle"],
        (76, 276),
        28,
        font(42, bold=True),
        (255, 232, 185),
        10,
    )
    draw_wrapped(
        draw,
        strings["detail"],
        (78, next_y + 26),
        46,
        font(25),
        (190, 198, 201),
        8,
    )

    # Speed sign accent.
    draw.ellipse((80, 492, 190, 602), fill="#ffffff", outline="#e63c2f", width=13)
    draw.text((111, 520), "80", font=font(38, bold=True), fill="#111111")
    draw.line((220, 546, 460, 546), fill=(230, 60, 47, 140), width=4)
    draw.line((220, 570, 390, 570), fill=(245, 166, 35, 120), width=4)

    shots = [
        ("warn-level-1-money.png", (665, 112), (176, 382), 28),
        ("warn-level-2-points.png", (800, 50), (244, 530), 36),
        ("autobahn-unlimited-over-130.png", (1015, 130), (166, 360), 28),
    ]
    for filename, xy, size, radius in shots:
        paste_rounded(
            canvas,
            Image.open(SCREENSHOT_ROOT / filename),
            xy,
            size,
            radius,
            border=(255, 255, 255, 42),
        )

    canvas.convert("RGB").save(SOCIAL_ROOT / f"youspeed-og-{locale}.png", quality=95)


def render_icons() -> None:
    icon = Image.open(ICON_SOURCE).convert("RGBA")
    sizes = {
        "favicon-32.png": 32,
        "apple-touch-icon.png": 180,
        "app-icon-192.png": 192,
        "app-icon-512.png": 512,
    }
    for filename, size in sizes.items():
        icon.resize((size, size), Image.Resampling.LANCZOS).save(ICON_ROOT / filename)

    (ICON_ROOT / "favicon.svg").write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#0b0e10"/>
  <circle cx="32" cy="32" r="24" fill="#fff"/>
  <circle cx="32" cy="32" r="21" fill="none" stroke="#e63c2f" stroke-width="6"/>
  <text x="32" y="39" text-anchor="middle" font-family="Arial, sans-serif" font-size="18" font-weight="700" fill="#111">YS</text>
</svg>
""",
        encoding="utf-8",
    )


def main() -> None:
    SOCIAL_ROOT.mkdir(parents=True, exist_ok=True)
    ICON_ROOT.mkdir(parents=True, exist_ok=True)
    render_icons()
    for locale, strings in LOCALES.items():
        render_social(locale, strings)
    print("Rendered social and icon assets")


if __name__ == "__main__":
    main()
