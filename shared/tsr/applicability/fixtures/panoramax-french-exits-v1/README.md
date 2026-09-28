# Public French exit image experiment

`corpus.json` contains eight real public Panoramax images from two geographically
separate areas: A10 Aire d’Orléans-Gidy and A75 Issoire exit 13. This is an
exploratory external evaluation of candidate attribution. It is not a locked
final holdout, a detector benchmark, or evidence of production accuracy.

| Area | Selected images | Visible speed signs | Capture and projection |
| --- | ---: | --- | --- |
| A10 Orléans-Gidy, northbound | 3 | Service-approach 50, then 30 in two views | 2025-06-15; original equirectangular HD; two-second cadence |
| A75 Issoire exit 13, both mainline directions | 4 | Two exit 70 posts, each seen twice | 2024-08-18 / 2024-08-21; perspective SD |
| A75 Issoire exit 13, vehicle on the ramp | 1 | A legitimate 70 for the camera vehicle | 2019-07-01 UTC; perspective SD |

There are seven reviewed non-ego sign observations and one ego positive control.
Repeated views are not additional physical signs. The 2019 and 2024 surveys do
not establish cross-year physical identity. The positive control is on the exit
ramp, so it does not establish mainline-sign recall. No exhaustive empty-image
negative labels are claimed.

## Acquisition and provenance

The OSM France host was unreachable during acquisition on 2026-09-28. Discovery
used the [Panoramax federation search API](https://api.panoramax.xyz/api/search).
The federation returned public assets from MathiasBas's instance and IGN;
`source.origin_host` records the actual host. These are genuine Panoramax images,
not user-drive images or generated examples.

`a10-reviewed.json` and `a75-reviewed.json` retain the per-area annotations.
`items/` preserves each complete source STAC item, including image URLs, capture
timestamps, sequence ID/rank, coordinates, image-center direction, camera
metadata, license, and provider annotations. Every selected image and metadata
file has a SHA-256 recorded in `corpus.json`. Provider machine annotations are
preserved for provenance; they do not supply governing-road truth or predictions.

Attribution: **MathiasBas / Panoramax**, CC-BY-SA-4.0, for the A10 images;
**DIR-MC / Panoramax IGN**, Etalab Open Licence 2.0, for the A75 images. Exact
license URLs and per-image source URLs are recorded in the manifest. Cached
images are unmodified public assets; A75 uses the provider's SD derivative.
Large image bytes remain in the ignored `inspector/logs/` cache.

The source A75 timestamps contain tiny microsecond increments while consecutive
positions span metres. They are retained verbatim, but are not usable cadence
or vehicle-speed observations; temporal carry is explicitly disabled. A10's
two-second still cadence is retained without duplication or interpolation.
Equirectangular image-center azimuth is not vehicle heading, and fixed-x phone
camera rules are not evaluated on A10 panoramas.

## Review and independence

Annotations were made by assistant visual review; there is no independent human
adjudication. Road polygons describe visible pavement/shoulder extent. Ground
anchors indicate visible post bases only when identifiable; guardrail/barrier
occlusion is marked unreliable. Target applicability labels are separate from
these geometry inputs. The two A75 supplementary-arrow relations are retained
for review, but are excluded from geometry-only predictions because they already
contain a manually resolved road relation.

`novelty-audit.json` records the baseline Git revision, exact-ID searches and
reviewed prior corpora. No selected image or sequence UUID occurred in that
baseline or the other available TSR JSON fixtures. These locations differ from
the reviewed A4/A35, PACA, Swiss and Karlsruhe routes. This audit cannot prove
independence from upstream classifier training or every historical ignored log.
`split: held_out` records geographic separation from local development imagery;
inspection has already occurred, so it must not be presented as a final holdout.

Current OSM topology references are explicitly dated counterfactual inputs;
they postdate the photos and do not prove historical bundle contents or sign
applicability. Driver behavior and learned geometry models are disabled. The
frozen uncertainty settings must not be narrowed to make these examples pass.
Abstention is a valid and informative result when a post foot is hidden or a
road boundary is ambiguous.

## Reproduce

From the repository root, fetch missing public images and verify the pinned
bytes, then replay the annotations:

```sh
python3 scripts/tsr/applicability/fetch_public_image_corpus.py shared/tsr/applicability/fixtures/panoramax-french-exits-v1/corpus.json
python3 scripts/tsr/applicability/image_geometry_replay.py shared/tsr/applicability/fixtures/panoramax-french-exits-v1/corpus.json --output inspector/logs/2026-09-28-fr-exit-experiment/public-replay.json
```

Acquisition on this Mac used the system `curl` trust store because Python's local
TLS certificate chain was unavailable. Do not disable certificate verification.
The fetch helper refuses changed bytes instead of silently replacing the
reviewed images. The experiment consumes reviewed candidates and geometry; it
does not rerun the phone detector/classifier or establish live display behavior.
