# MobiData BW inventory and lecture review, 20 October 2026

The local Baden-Württemberg bundle contains all **163,504** source records
across **53 exact source codes**, including **13,788 DE:310** and **9,312 DE:311**.
The Web Inspector displays them independently of speed lookup. The existing
speed/settlement tables, metadata and runtime policy are unchanged.

## Source and data contract

- Publisher: Verkehrsministerium Baden-Württemberg / MobiData BW.
- [Dataset catalogue](https://mobidata-bw.de/dataset/verkehrszeichen-baden-wurttemberg),
  [GeoJSON](https://mobidata-bw.de/daten/portal/VZ-Daten/signs.geojson).
- License: [Datenlizenz Deutschland – Namensnennung – Version 2.0](https://www.govdata.de/dl-de/by-2-0).
- FeatureCollection timestamp: `2026-10-17T22:00:00.013Z`.
- Original download: 87,275,340 bytes; SHA-256
  `cb4c89d3d2b18a06a1d5956b94865310929ff455d7a33005053bccaac66b79c3`.
- Modification: transform GeoJSON points/properties to SQLite; preserve exact
  codes and original properties; add spatial indexes and provenance.

`traffic_sign_source` stores publisher, source/catalogue/license URLs, source
hash/timestamp, bounds, count, modification notice and `usage_role=inventory_only`.
`traffic_sign_inventory` stores coordinates, orientation, group/location IDs,
group order, exact sign code, OpenLR reference/confidence, municipality/ARS,
source dates and `raw_properties_json`. Its `record_key` is a canonical feature
SHA-256. Group order is not a sign ordinal: multiple signs may share group/order.
`traffic_sign_inventory_rtree` indexes positions; ordinary latitude/longitude
and code indexes support fallback and filtering. `row_id` is a local database
key, not a persistent sign identity. Feature fingerprints are snapshot-specific.

Imports validate the snapshot before replacement and replace a source atomically.
Reimports remove stale rows. Codes such as `DE:331.2[]` and
`DE:274-50[WVZ Rombachtunnel]` remain literal. Records are **not** copied into
`settlement_sign`, OSM `ways` or matcher/runtime tables. Installation/update dates
have import-batch patterns; treat them as source attributes. Coordinates,
orientation and existence are inventory evidence requiring review.

## Build integration and local artifact

The country generator and rebuild command automatically download/include the
inventory for Baden-Württemberg targets. The Germany release workflow imports
it only for the BW region. Other regions retain their previous build commands.
Direct builder calls can pass `--traffic-sign-geojson FILE`. The bundle packager
copies inventory provenance into `manifest.source`; v3 manifest/schema versions
and app requirements remain unchanged.

```sh
python3 scripts/map/traffic_sign_inventory.py download --output mapdata/raw/mobidata-bw-signs.geojson
python3 scripts/map/traffic_sign_inventory.py import \
  --db mapdata/dist-v3/baden-wuerttemberg-inventory/speeds_v3.sqlite \
  --geojson mapdata/raw/mobidata-bw-signs.geojson
```

The import expects an existing database. The actual local build used an APFS
clone of `dist-v3/baden-wuerttemberg-settlement-pilot/speeds_v3.sqlite` and the
pinned snapshot above. OSM data were not refreshed. Local artifacts:

- DB: `mapdata/dist-v3/baden-wuerttemberg-inventory/speeds_v3.sqlite`.
- Bundle: `mapdata/bundles/v3/baden-wuerttemberg/2026-10-20-mobidata-inventory/`.
- DB size: 1,449,623,552 bytes; gzip: 470,446,667 bytes.
- DB SHA-256: `33e635306bb8515f994857628f019bfcc34b71b320556e9195905b2c0e6b2ee5`.
- Gzip SHA-256: `26d28a2d17274f1697d13dd4d871e802545b88dced6ae9a5eb3b8812866f0195`.

This is a local review build. No release, deployment or upload was performed.
The independent source is refreshed on full BW rebuilds; OSM deltas do not
refresh it. Consult its own timestamp when comparing data.

## Viewer

Serve the repository with `python3 -m http.server 8768 --bind 127.0.0.1` and open
`http://127.0.0.1:8768/inspector/?db=../mapdata/dist-v3/baden-wuerttemberg-inventory/speeds_v3.sqlite`.
The SQLite file is loaded into browser memory. No backend DB connection is needed.
Map tiles and JavaScript dependencies retain their existing network requirements;
the inventory is read entirely from the local bundle.

“Verkehrszeichen im Offline-Bestand” shows counts and source attribution.
Select an exact class and search municipality, location UUID or group UUID.
Click a result to center the map and inspect source attributes and license.
Markers appear from zoom 13, capped at 400 per viewport; refine the view/filter
when capped. Shared official pictograms are used where available, otherwise the
exact source code appears. Town-sign pictograms illustrate the class; place
names printed in the reference artwork are not source labels. Older databases
keep inventory controls disabled. The overlay has no calls into speed
interpretation, map matching or either mobile runtime.

## Lecture collection

`lectures/tsr-sgblur-de-2026-10-26/.build/mobidata-bw-review-2026-10-20/collection-v2/`
contains **57 original JPEG full images, 57 PNG crops and 57 target-box proposals**
from 53 public Panoramax sequences: 37 visual DE:310 and 20 DE:311 proposals.
The archive is `output/panoramax-mobidata-bw-review-2026-10-20-v2.zip` in that lecture
folder; `SICHTUNG.html` is its offline review index. The initial 13-image version
is preserved. The [delivery report](../lectures/tsr-sgblur-de-2026-10-26/source/mobidata-bw-review-2026-10-20-v2/delivery-report.json)
records archive hash/size and counts. The tracked manifest preserves image URLs,
authors, CC BY-SA 4.0 licenses, metadata hashes, proposed boxes, registry
associations and the bounded novelty audit.

The follow-up used all 2,730 records with a public camera position within 10m:
9,014 sign/photo pairs and 5,972 distinct photos. A balanced selection of 180
new native views from 95 municipalities was screened; 53 HD images were replayed.
It adds **44 useful target views (30 DE:310, 14 DE:311)** from 40 new sequences,
with no exact ID/hash overlap against the initial review or scoped prior inventory.
This is a bounded search, not an exhaustive visual census of the cohort.

For the 44 additions, 41 targets have no stored target box, two are `yes` without
a precise class, and one DE:310 proposal matches a box labelled `FR:C50` at 0.92
classification confidence. The latter label is from `classify_fr_road_signs/0.13`;
its source detector is `SGBlur-yolo11s/0.1.0`. Neighbouring annotation labels are
never assigned to the target without box overlap. The fixed local **YOLO11n**
replay finds seven and misses 37 of the new targets (one match is borderline at
IoU 0.512). Across both batches it matches nine and misses 48 of 57 proposals
at IoU ≥ 0.5 (imgsz 1280, conf 0.25, NMS IoU 0.7). Stored source annotations and
this local replay are separate evidence. No new classifier ran, and these
selected cases do not establish population recall or model precision.

The full 10m match subset, original predictions, source metadata and search scope
are frozen inside the archive. [Search report](../lectures/tsr-sgblur-de-2026-10-26/source/mobidata-bw-review-2026-10-20-v2/search-summary.json).
Two initial frames retain the registry/opposite-visible-face discrepancy;
registry codes remain independent of proposed image labels. Conservative site/
sequence groups are proposals for later review; no split is assigned.

Approvals remain false and all 136 classifier approval folders are empty.
Full images have partial target annotation, not complete sign/face/plate ground
truth. The normal course importer is explicitly incompatible until review and
a suitable reviewed export. These examples have already been viewed with the
baseline and remain outside reserved blind-test candidates. No model was trained
and no original Panoramax annotations were changed.

## Coverage answer

In the same public federation catalogue snapshot (HTTP Last-Modified
`2026-10-11T12:14:12Z`), **2,730 of 23,100 town-sign records have a public photo
within 10 metres**: **1,605 DE:310** and **1,125 DE:311** (11.8%). The 50-metre
count is 4,225. These are distinct registry records with a nearby camera
position, not verified visible signs, distinct physical signs or usable crops.

## Verification and limits

- Streamed row hashes match for every original table; original schema SQL
  matches for every original table/index/trigger. `PRAGMA quick_check` is `ok`.
- Both clients query named runtime tables and tolerate additive tables/source
  metadata. Their runtime code and shared state-machine policy were not edited.
- Import/replacement/rollback, literal codes, BW-only build selection and
  manifest provenance have automated tests. Existing builder, bundle/delta and
  publication-gate tests were also run.
- Browser verification used the complete 1.45 GB DB, municipality/class search,
  markers, shared art and details. An older no-inventory DB was also checked.
  Archive CRCs and every packaged asset SHA-256 were checked.
- The September pilot fails the current, stricter field-readiness gate: missing
  detailed way links, motorway-exit/corridor tables and source geometry capability
  metadata. The inventory build has the **same ten errors**, with no additions.
  Review both structural reports beside the materialized DB before considering
  a later release. This change does not establish current app field-test
  readiness, driving accuracy or source freshness.
