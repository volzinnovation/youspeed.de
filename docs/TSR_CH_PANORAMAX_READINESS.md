# Swiss (CH) TSR: Panoramax starting point

Reviewed 2026-09-17. This document records the first reproducible inventory
for a Swiss on-device traffic-sign-recognition pack. It is a readiness and
acquisition plan, not a model release or runtime activation.

## Current finding

The supplied Panoramax mapping has 225 model rows. 139 rows contain a CH
mapping and 86 do not. The CH column contains 139 distinct raw mappings, but
they reduce to 120 base sign codes after separating numeric speed values and
variant suffixes. Sixteen rows are numeric `2.30[value]` speed-limit variants;
those remain the existing schematic speed UI exception and do not need a
country pictogram asset.

The official ASTRA sign downloads cover 117 of the 120 base-code candidates
when the downloaded EPS/WMF/SVG members are treated as source availability.
The reviewed Wikimedia Commons Swiss-sign categories provide declared
public-domain SVG renditions for 91 of the 116 in-scope artwork codes. The
remaining 25 codes have official ASTRA vector source material but still need
a reviewed SVG rendition and per-file provenance before bundling. The detailed
source inventory is `shared/tsr/ch-artwork-source-inventory-v1.json`.
The remaining cases are:

| Code | Status | Action |
| --- | --- | --- |
| `1.17` | Retired/abolished in the official reference | Keep as historical-data provenance only; do not make it an active CH display class. |
| `4.88` | Current official information sign, absent from the current ASTRA ZIP | Owner-excluded; retain as a separately tracked artwork and field-image task. |
| `4.90` | Current official radio-information sign, absent from the current ASTRA ZIP | Owner-excluded; retain as a separately tracked artwork and tunnel/night-image task. |

The ASTRA archives are especially useful for code coverage, but most of the
mapped signs are legacy EPS/WMF rather than ready-to-package SVG. The Swiss
government copyright notice says that downloading or copying does not transfer
rights and that reproduction requires prior written permission unless another
rightsholder or licence applies. The Commons candidates reviewed so far declare
public-domain status per file, with ASTRA as the credited source; those files
still need exact code/revision/checksum capture in the CH manifest. Runtime
artwork must use only that reviewed per-file set.

## Panoramax availability

The current Panoramax Hub inventory has country datasets for Germany, France,
the Netherlands and Belgium, but no Swiss classified dataset or Swiss
classifier. The pinned German validation archive has 6,504 `DE_` members and
575 unprefixed members and contains no Swiss-prefixed members. It can bootstrap
the detector/classifier recipe, but it is not evidence of Swiss recognition.

Raw Swiss imagery is nevertheless available through the federated Panoramax
catalog. A metadata-only search of the Swiss bounding box returned 500 sample
features from 115 collections and eight providers, all declaring
`CC-BY-SA-4.0`; the first page clustered around central Switzerland, so this
is an availability signal rather than a complete national coverage estimate.
The next concrete work item is to crawl the catalog by spatial tiles, retain
only Swiss coordinates, group by sequence, and run the existing sign detector
for candidate crops.

The KI-server crawl completed on `2026-09-17` at
`/mnt/nvme/youspeed-tsr-ch-panoramax-20260917/run/`. It indexed 1,275,880
unique items and 867,859 eligible items. The deterministic queue contains
10,000 sequence-deduplicated `sd` derivatives; all downloaded successfully and
the existing sign detector produced 236 candidate crops. Five failed parent
tiles were recovered by subdivision after three 502 responses. 544 child tiles
still hit the maximum response density at the configured recursion depth, so
this is a large research inventory, not proof of exhaustive national coverage.

An expansion pass reran the German detector on the same 10,000 downloaded
images at confidence `0.05`, producing 515 valid lower-threshold candidate
crops. The DE and FR classifiers then agreed at confidence `>= 0.90` on 98
samples spanning 22 raw CH mappings, 17 of which are artwork base codes; the
remaining mapping is a numeric speed family and is intentionally excluded from
pictogram coverage. This improves discovery recall, but the lower detector
threshold also increases false-positive risk; these remain dual-classifier
pseudo-labels and require route-grouped review before training.

A second, non-overlapping tranche selected the next 1,200 route-deduplicated
images from the same catalog. It downloaded all 1,200 successfully, produced
113 lower-threshold candidates, and added 30 accepted DE+FR agreements. Across
both expansion tranches there are now 628 candidates and 128 accepted samples
covering 24 artwork base codes (30 raw CH mappings, including speed variants).

A third, non-overlapping tranche selected another 1,200 images, downloaded all
of them successfully, produced 542 lower-threshold candidates, and added 149
accepted DE+FR agreements. Across all three expansion tranches there are now
1,170 candidates and 277 accepted samples covering 29 artwork base codes
(37 raw CH mappings, including speed variants).

A fourth, non-overlapping tranche selected another 1,200 images, downloaded
all of them successfully, produced 219 lower-threshold candidates, and added
51 accepted DE+FR agreements. Across all four expansion tranches there are now
1,389 candidates and 328 accepted samples covering 31 artwork base codes
(41 raw CH mappings, including speed variants).

Passes 5 through 10 added 7,200 more non-overlapping images, all downloaded
without failure. They produced 2,239 candidates and 821 accepted agreements;
the cumulative expansion ledger now contains 3,628 candidates and 1,149
accepted samples spanning 47 artwork base codes (58 raw CH mappings, including
speed variants).

Passes 11 through 16 added another 7,200 non-overlapping images, also with no
download failures. They produced 3,309 candidates and 946 accepted agreements;
the cumulative expansion ledger now contains 6,937 candidates and 2,095
accepted samples spanning 52 artwork base codes (63 raw CH mappings, including
speed variants).

For the requested no-human-label bootstrap, the DE and FR classifiers were
run independently over all 236 candidates. National output labels were
normalized through the reviewed cross-country mapping, and only identical CH
codes with both confidences at least 0.90 were accepted. This produced 69
pseudo-labelled samples spanning 21 CH codes. These labels are accepted as
the training substitute requested by the owner, but are not an independent
holdout, human ground truth, or runtime-release evidence. The resulting
`weak-labels.jsonl` and `weak-label-summary.json` remain on the KI server.

The expanded outputs are `candidates-lowconf.jsonl`,
`weak-labels-lowconf.jsonl`, and `weak-label-summary-lowconf.json` in the same
KI-server run directory, with pass-2 through pass-16 outputs under the
corresponding `passN/` directories. The repaired first-pass candidate file
contains 515 records;
the malformed trailing record from the interrupted detector write was retained
as `candidates-lowconf.jsonl.before-tail-repair` and excluded from analysis.

The prioritized missing-class inventory is
`shared/tsr/ch-panoramax-acquisition-targets-v1.json`. It reports 64 total
in-scope artwork base codes without an accepted pseudo-label. Per owner decision,
`4.88` and `4.90` are excluded from the current scope; the active acquisition
target is now 64 in-scope base codes requiring Swiss field imagery and review.
The numeric speed family is not included in this pictogram target count.

The current high-confidence bootstrap corpus uses detector confidence >= 0.70
as an additional noise filter. It remains pseudo-labelled and evaluation-only;
the latest filtered adapter contains 1,119 crops across 59 labels and reaches
20.4% top-1 and 30.8% top-5 on the route split, with 43 of 57 model labels
represented in validation. This is a challenger result, not release evidence.

The full-coverage evaluation pass adds deterministic ASTRA artwork renders for
the 116 in-scope artwork base codes and retains the 1,119 real pseudo-labelled
crops. The resulting v9 classifier has 127 output classes. On the 250-image
route-separated real validation folder it scores 97.6% top-1 and 99.6% top-5;
the comparison v8 checkpoint scores 98.4% and 99.2%. These are agreement-label
benchmarks, not human ground truth. The v9 export passed Core ML and LiteRT
parity (top class preserved; max absolute differences approximately 0.00124
and 0.000021). It is staged in both app trees as
`CH.panoramax-bootstrap.tsrmodelpack`, with CH runtime selection marked
evaluation/shadow only and production registry rollout still blocked.

The CH corpus should be built from Swiss Panoramax routes and grouped by source
route/sequence before splitting. The archive filename convention must not be
used as the sole leakage boundary. Each accepted sample should retain the
Panoramax source identity, country/sign code, route group, capture context,
annotation status, privacy review status, and licence/attribution record.

## Model path for both mobile clients

Owner decisions for this pass are: accept the DE+FR agreement rule as
explicitly marked non-human pseudo-ground truth; cover the full CH artwork
scope except `4.88` and `4.90`; and retain the existing Android/iPhone model
constraints.

The existing shared target is the right starting architecture:

1. a YOLOX-Nano-derived primary-sign proposal detector;
2. a MobileNetV3-Large `224x224` crop classifier, with MobileNetV3-Small as a
   latency challenger; and
3. the existing temporal primary-sign passage reducer.

The CH classifier should begin as a country adapter over the reviewed semantic
labels, not as a blind copy of the DE model. The dual-classifier pseudo-label
subset is suitable for a bootstrap experiment only: the strict
detector pass covers 16 of 118 artwork base codes; all sixteen lower-threshold
expansion tranches together cover 52. Neither supports an all-pictogram CH
runtime pack. The generated acquisition list identifies the remaining 64
in-scope artwork base codes. Train with Swiss
imagery first,
then add only explicitly reviewed adjacent-country examples for visual hard
negatives or genuinely equivalent sign shapes. Keep speed values semantic and
separate from pictogram artwork.

The same frozen training result must produce Core ML for iPhone and LiteRT for
Android. Before production activation, require route-grouped evaluation, export parity,
legal/action mapping review, licensing review, and on-device latency/thermal
measurements on both platforms. Until then, CH remains an evaluation/shadow
pack and must not enter the production country registry.

## Reproduction

The machine-readable result is
`shared/tsr/panoramax-ch-readiness-v1.json`. Recreate it with the downloaded
ASTRA archives and the external mapping CSV:

After downloading the KI-server weak-label output, recreate the acquisition
targets with:

```sh
python3 scripts/tsr/build_ch_acquisition_targets.py \
  --readiness shared/tsr/panoramax-ch-readiness-v1.json \
  --weak-labels tmp/ch-panoramax/weak-labels-lowconf.jsonl \
  --output shared/tsr/ch-panoramax-acquisition-targets-v1.json
```

```sh
python3 scripts/tsr/audit_ch_panoramax.py \
  --mapping-csv /Users/raphaelvolz/Github/my-phd-thesis-gpt-6-astra/examples/traffic_signs/source/panoramax-road_signs_mapping.csv \
  --astra-archive danger=tmp/ch-astra/01-danger.zip \
  --astra-archive other-hazards=tmp/ch-astra/01-other-hazards.zip \
  --astra-archive prohibitions=tmp/ch-astra/02-prohibitions.zip \
  --astra-archive regulations=tmp/ch-astra/02-regulations.zip \
  --astra-archive special-paths=tmp/ch-astra/02-paths.zip \
  --astra-archive priority=tmp/ch-astra/03-priority.zip \
  --astra-archive behavior=tmp/ch-astra/04-behavior.zip \
  --astra-archive direction=tmp/ch-astra/04-direction.zip \
  --astra-archive motorway=tmp/ch-astra/04-motorway.zip \
  --astra-archive information=tmp/ch-astra/04-information.zip \
  --panoramax-catalog-sample tmp/ch-panoramax/swiss-bbox-search-500.json \
  --output shared/tsr/panoramax-ch-readiness-v1.json
```

The metadata sample above was obtained with:

```sh
curl -fsSL --get 'https://api.panoramax.xyz/api/search' \
  --data-urlencode 'bbox=5.9,45.8,10.6,47.9' \
  --data-urlencode 'limit=500' \
  -o tmp/ch-panoramax/swiss-bbox-search-500.json
```

The official sign source is ASTRA's [Swiss sign download page](https://www.astra.admin.ch/de/signale).
The legal reference is the [Swiss Signalisationsverordnung (SSV)](https://www.fedlex.admin.ch/eli/cc/1979/1961_1961_1961/de).
The available bootstrap corpus is [Panoramax classified German road signs](https://huggingface.co/datasets/Panoramax/classified_de_road_signs).
The federated imagery search follows the [Panoramax STAC/API contract](https://docs.panoramax.fr/backend/dev/STAC_compatibility/).
The Panoramax model/data licensing and split-leakage restrictions remain those
documented in `shared/tsr/training-sources-v1.json` and
`docs/TSR_TRAINING_ROUND_TRIP.md`.
