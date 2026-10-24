# YouSpeed website

Quellordner fuer die Kunden-Website des Forschungsprojekts.

- Quelle: `Web/`
- Publish-Ziel: `sites/` (fuer GitHub Pages)

Lokaler Publish-Lauf:

```bash
./scripts/web/publish_web_to_sites.sh
```

Statischer Smoke-Test nach dem Publish:

```bash
node ./scripts/web/check_static_site.mjs sites
```

Der Test prueft lokale Links, referenzierte Assets und In-Page-Anker im GitHub-Pages-Artefakt.

## Version 1.4 website

- Localized release copy: `scripts/web/release-1.4.json` (DE/EN/FR/NL).
- Page generator: `node scripts/web/build_localized_site.mjs`.
- Artwork generator: `python3 scripts/web/render_social_assets.py` (Pillow). Reuses the Apple/Android artwork prepared for 1.4 and its retained native demonstration captures; The hero arranges five original shared traffic-sign PNGs in a circle, following the feature graphic’s sign selection. Gallery WebP renditions are scaled without cropping. Social previews reuse the complete localized Android feature graphic.
- Original artwork and provenance: `store/README.md` and `store/artwork/dashcam-preview.json`.
- Downloads: version 1.4 is available on the App Store and Google Play. Both stores are the primary download options. The GitHub link is explicitly an archive of older Android APKs; no unverified 1.4 APK URL is advertised. iOS 17 / Android 14 or later is required.
- Release copy updated on 24 October 2026 following the product owner’s confirmation that both stores released 1.4. OCR reads, displays and optionally speaks supplementary-sign text; it does not automatically evaluate its conditions.
- Existing `assets/release-1.3/` paths are retained for stable asset URLs and do not identify the current app version. The original feature film is retained with a version-neutral title; it is not presented as a new 1.4 recording.

## Country references and film

- `scripts/web/build_reference_pages.mjs` generates 76 static reference pages in DE/EN/FR/NL: two country indexes, five sign catalogues and twelve penalty tables per language. They use the app’s shared renderers and JSON sources, keeping road contexts, spoken names and missing values consistent with the app.
- `scripts/web/reference-copy.json` contains the localized reference headings, store banners and film text. `Web/reference.js` adds catalogue search; catalogue content remains accessible without JavaScript.
- Pictograms are copied unchanged from `shared/tsr/sign-pictograms/`, with per-image attribution. Swiss artwork with pending redistribution review is omitted; codes and spoken names remain available with a link to ASTRA.
- `sitemap.xml` includes all 82 pages. Reference pages have canonical URLs, language alternates and breadcrumb structured data. Every page, including the homepages, has a fixed yellow banner with the app icon and both official store links. The primary navigation and a dedicated section immediately after the hero link prominently to both reference indexes.
- The homepage film uses the video ID in `store/android/metadata/youtube-preview-1.3.json` and a local poster. The YouTube player loads only after a click; the direct YouTube link is always available.
- Validate reference sources with `node tests/penalty-documentation.test.cjs` and `node tests/traffic-sign-documentation.test.cjs`, alongside the static site smoke test above.

The local publish script regenerates pages and assets before copying `Web/` to `sites/`. This prepares the deployment artifact; pushing it to the Pages branch can deploy the public website and requires explicit approval under the repository guidance.
