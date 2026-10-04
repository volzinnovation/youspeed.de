#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from shutil import copyfile

from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = REPO_ROOT / "Web"
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


def circle_mask(size: int, radius_ratio: float = 0.388) -> Image.Image:
    scale = 4
    mask = Image.new("L", (size * scale, size * scale), 0)
    draw = ImageDraw.Draw(mask)
    center = size * scale / 2
    radius = size * scale * radius_ratio
    draw.ellipse(
        (
            round(center - radius),
            round(center - radius),
            round(center + radius),
            round(center + radius),
        ),
        fill=255,
    )
    return mask.resize((size, size), Image.Resampling.LANCZOS)


def render_release_artwork() -> None:
    """Reuse approved 1.3 store artwork; scale for the web without cropping."""
    release_root = WEB_ROOT / "assets" / "release-1.3"
    release_root.mkdir(parents=True, exist_ok=True)
    copyfile(REPO_ROOT / "store/videos/feature-film/en-US/youspeed-feature-film-poster.jpg", release_root / "feature-film-poster.jpg")
    signs_root = release_root / "signs"
    signs_root.mkdir(parents=True, exist_ok=True)
    for sign in ["de-274-50", "de-206", "de-283", "de-102", "de-205"]:
        copyfile(REPO_ROOT / f"shared/tsr/sign-pictograms/png/{sign}.png", signs_root / f"{sign}.png")
    road = Image.open(REPO_ROOT / "store/artwork/source/european-road-backdrop.png")
    road.convert("RGB").save(release_root / "road.webp", quality=88)
    for locale, store_locale in {"de": "de-DE", "en": "en-US", "fr": "fr-FR", "nl": "nl-NL"}.items():
        target = release_root / locale
        target.mkdir(parents=True, exist_ok=True)
        sources = {
            "recognition": REPO_ROOT / f"store/apple/screenshots/{store_locale}/iphone-6.9/02-camera-speed-limit.png",
            "signs": REPO_ROOT / f"store/apple/screenshots/{store_locale}/iphone-6.9/03-secondary-sign.png",
            "dashcam": REPO_ROOT / f"store/apple/screenshots/{store_locale}/iphone-6.9/04-dashcam.png",
            "android-dashcam": REPO_ROOT / f"store/android/listing/{store_locale}/phone-screenshots/02-dashcam.png",
        }
        for name, source in sources.items():
            image = Image.open(source).convert("RGB")
            image.thumbnail((960, 540) if name == "android-dashcam" else (660, 1434), Image.Resampling.LANCZOS)
            image.save(target / f"{name}.webp", quality=90, method=6)
        # Keep the localized feature graphic complete in the social preview.
        graphic = Image.open(REPO_ROOT / f"store/android/listing/{store_locale}/feature-graphic-1024x500.png").convert("RGB")
        graphic.thumbnail((1200, 630), Image.Resampling.LANCZOS)
        scale = 1200 / graphic.width
        graphic = graphic.resize((1200, round(graphic.height * scale)), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (1200, 630), "#0b0e10")
        canvas.paste(graphic, (0, (630 - graphic.height) // 2))
        canvas.save(SOCIAL_ROOT / f"youspeed-og-{locale}.png")


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

    mark = icon.resize((192, 192), Image.Resampling.LANCZOS)
    mark.putalpha(circle_mask(192))
    mark.save(ICON_ROOT / "app-icon-mark-192.png")

    (ICON_ROOT / "favicon.svg").write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#0b0e10"/>
  <circle cx="32" cy="32" r="24" fill="#fff"/>
  <circle cx="32" cy="32" r="21" fill="none" stroke="#e63c2f" stroke-width="6"/>
  <text x="32" y="39" text-anchor="middle" font-family="Arial, sans-serif" font-size="18" font-weight="700" fill="#111">30</text>
</svg>
""",
        encoding="utf-8",
    )


def main() -> None:
    SOCIAL_ROOT.mkdir(parents=True, exist_ok=True)
    ICON_ROOT.mkdir(parents=True, exist_ok=True)
    render_icons()
    render_release_artwork()
    print("Rendered 1.3 release, social and icon assets")


if __name__ == "__main__":
    main()
