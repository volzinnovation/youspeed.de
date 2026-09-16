# Foreign TSR completion checklist

This checklist is the handoff boundary for activating France (`FR`), the
Netherlands (`NL`) and Belgium (`BE`). Speech, legal warning rules, bundle rule
linkage and core artwork are already implemented. The foreign traffic-sign
recognition packs remain disabled until the evidence below exists for each
country.

## Owner decision recorded

On 16 September 2026 the owner approved the current Wikimedia Commons
renditions for commercial use in the France, Netherlands and Belgium core sets.
The policy is to exclude only a file whose declared source licence does not
permit commercial use. Each manifest records the file-page provenance, licence,
commercial-use decision, attribution/share-alike obligations and asset hashes.
The new Belgian Code de la voie publique catalogue is the target catalogue;
its new-sign effective date is pinned to 1 June 2027 with the documented
transition for current signs.

No further artwork approval is needed for the checked-in entries. The artwork
expansion now reaches the German baseline: FR has 111 model-linked
entries plus three preserved core signs (114 total), NL has 111 entries, and BE
has 111 model-linked entries plus four preserved core/transition signs (115 total).
The manifests still remain runtime-blocked because artwork coverage is not model
calibration or legal-action approval.

## Remaining owner-independent work

### 1. Artwork inventory completion

The expanded sets are recorded in:

- `shared/tsr/sign-pictograms/national/FR/manifest.json`
- `shared/tsr/sign-pictograms/national/NL/manifest.json`
- `shared/tsr/sign-pictograms/national/BE/manifest.json`

Numeric speed-limit signs remain the existing schematic UI exception.

The expanded coverage reaches or exceeds the German 111-entry baseline. The
complete published Panoramax model-class-to-country-code table is materialized
at `shared/tsr/sign-pictograms/sources/panoramax-country-code-mapping-v1.json`;
its legal action/semantic review remains a separate gate.

### 2. Country-labeled image data

The pinned Panoramax model revisions and their dataset-card lineage are now
authorized under their published commercial-use-permitting terms in
`shared/tsr/training-sources-v1.json`. The dataset archives are not app inputs
and are not required for runtime bundles. If retraining is undertaken, the
selected data must contain representative road-sign frames with:

- country and sign code;
- the reviewed semantic ID from `selection.json`;
- source sequence/scene ID and capture timestamp;
- bounding box or crop coordinates;
- negative/background examples;
- enough examples for train, calibration and untouched holdout groups.

The same physical sign or capture sequence must not cross those groups. A
country label alone is not enough to calibrate a model.

### 3. Model transformation and release gates

The blocked handoff is captured in `shared/tsr/foreign-runtime-readiness-v1.json`
and validated by `foreign-runtime-readiness-v1.schema.json`. It records the
pinned classifier checkpoint, shared German detector reference artifacts,
required Core ML/LiteRT shapes, and every missing evidence hash. It is a
readiness manifest, not a runtime release manifest; the country registry stays
unlinked until all gates pass.

The observed export and server provenance is recorded in
[`docs/TSR_EXPORT_AND_SOURCE_PROVENANCE.md`](TSR_EXPORT_AND_SOURCE_PROVENANCE.md)
and `shared/tsr/export-environment-evidence-v1.json`. The KI server's Prolix
image is an inference environment, not the German-compatible mobile export
environment; its Blackwell GPU can still be used for isolated foreign model
work once the export lock and calibration inputs are available.

The foreign packs must use the existing two-stage production architecture:

1. the shared Panoramax detector proposes candidate sign boxes;
2. the country-specific Panoramax classifier scores the proposal crop;
3. iPhone uses a Core ML detector and classifier, while Android uses LiteRT
   models through CameraX;
4. preprocessing and output parity are checked across reference, Core ML and
   LiteRT artifacts;
5. candidate bursts are associated over time and only a validated physical-sign
   passage may affect the active speed context.

The pinned `.pt` files are therefore conversion inputs, not runtime assets.
No pack will be marked calibrated from a synthetic score, a German checkpoint,
or a copied threshold. The existing minimum app/runtime compatibility in the
country registry remains the target.

## What can continue automatically after those inputs arrive

1. Normalize country mappings and complete `selection.json` entries.
2. Build leakage-safe train/calibration/holdout splits with
   `scripts/tsr/group_splits_v2.py`.
3. Train or fine-tune the approved detector/classifier and export matching
   Core ML and LiteRT artifacts.
4. Run independent evaluation, export parity and calibration checks.
5. Fill `runtime_model_class` and generate a schema-valid country-pack release
   manifest with checksum-pinned artifacts.
6. Update `shared/tsr/country-pack-registry-v1.json` only after the acceptance
   gates pass.
7. Package the manifest and model artifacts for both iPhone and Android, then
   exercise country discovery, bundle download, rollback and sign display on
   both clients.

## Current state

| Country | Core artwork | Reviewed mapping | Calibrated model | Runtime manifest | Release state |
| --- | --- | --- | --- | --- | --- |
| FR | 114 SVG/PNG pairs (111 Panoramax-linked + 3 preserved core) | code-level reviewed | missing | missing | blocked |
| NL | 111 SVG/PNG pairs | code-level reviewed | missing | missing | blocked |
| BE | 115 SVG/PNG pairs (111 Panoramax-linked + 4 preserved core/transition) | code-level reviewed (B7 legacy/transition-only) | missing | missing | blocked |

The country registry intentionally keeps all three foreign manifests null and
`calibrated: false` until the technical evidence and automated acceptance
reports are available. The readiness manifest does not change that production
decision.

## Research candidates checked on 16 September 2026

The source search found a viable training-data/model path, but it does not
change the release gate above. Panoramax provides photographic crops and
classification checkpoints, not reusable national SVG/PNG artwork:

| Country | Panoramax training data | Panoramax classifier | Licence shown by source | Immediate caveat |
| --- | --- | --- | --- | --- |
| FR | `classified_fr_road_signs`: 66,000+ detected signs, 250+ official-type classes, plus false-positive classes | `classify_fr_road_signs`: YOLOv8 classification; source reports 0.987 accuracy | Dataset Etalab 2.0; model Etalab 2.0 | Dataset viewer currently fails on an invalid class-label revision; no mobile export or calibration report is supplied |
| NL | `classified_nl_road_signs`: 24,000+ crops, 150+ classes; some additional European examples are filename-prefixed | `classify_nl_road_signs`: fine-tuned from the France classifier; source reports 0.993 accuracy | Dataset CC BY-SA 4.0; model Etalab 2.0 | Dataset viewer currently fails on an invalid class-label revision; foreign-prefixed examples must be filtered before country calibration |
| BE | `classified_be_road_signs`: 24,000+ crops, 140+ classes; some additional European examples are filename-prefixed | `classify_be_road_signs`: pinned revision and checkpoint | Dataset CC BY-SA 4.0; model Etalab 2.0 | Dataset viewer currently fails on an invalid class-label revision; no mobile export or calibration report is supplied |

Useful Panoramax references:

- [Panoramax model and dataset catalogue](https://huggingface.co/Panoramax)
- [France dataset](https://huggingface.co/datasets/Panoramax/classified_fr_road_signs)
- [Netherlands dataset](https://huggingface.co/datasets/Panoramax/classified_nl_road_signs)
- [Belgium dataset](https://huggingface.co/datasets/Panoramax/classified_be_road_signs)
- [France classifier](https://huggingface.co/Panoramax/classify_fr_road_signs)
- [Netherlands classifier](https://huggingface.co/Panoramax/classify_nl_road_signs)
- [Panoramax cross-country mapping CSV](https://huggingface.co/Panoramax/classify_nl_road_signs/blob/main/road_signs_mapping.csv)
- [Prolix traffic-sign analyzer notes](https://gitlab.com/panoramax/clients/prolix/-/blob/main/docs/Analyzer_trafficsign.md)

The Panoramax mapping CSV is a good starting point for reviewed semantic
mapping: it contains country-code columns such as `FR`, `NL` and `BE` beside
shared concepts. It is not accepted as the final YouSpeed mapping until every
selected class is checked against the applicable national regulation and the
country-only examples are isolated.

Panoramax's own documentation describes the Prolix traffic-sign workflow as
currently working for France and invites expansion, so the existence of NL/BE
datasets and classifiers should not be read as a Panoramax production guarantee
for those two countries.

### Artwork inventory

Wikimedia Commons has broad SVG inventories for all three countries:

- [France SVG road signs](https://commons.wikimedia.org/wiki/Category:SVG_road_signs_in_France)
- [Netherlands SVG road signs](https://commons.wikimedia.org/wiki/Category:SVG_road_signs_in_the_Netherlands)
- [Belgium SVG road signs](https://commons.wikimedia.org/wiki/Category:SVG_road_signs_in_Belgium)

The Netherlands category alone lists 180 SVG files across warning, priority,
prohibitory, mandatory, additional and historic groups. Commons is therefore a
practical source of licensed vector renditions, but each file has its own
licence and provenance. Commons category membership is not proof that a file
is an official government-issued artwork byte. The checked-in national sets
continue to record the regulation as the authority for code/meaning and the
Commons file as the separately licensed rendition.

The government sources checked are authoritative for the national sign
catalogues, codes and meanings, rather than a ready-to-import SVG/PNG asset
bundle:

- [France: Legifrance consolidated sign order](https://www.legifrance.gouv.fr/loda/id/LEGISCTA000006112308)
- [France: Sécurité routière sign reference PDF](https://www.securite-routiere.gouv.fr/sites/default/files/2021-05/apr_panneaux2017.pdf)
- [Netherlands: Rijksoverheid sign overview](https://www.rijksoverheid.nl/vraag-en-antwoord/verkeersveiligheid/welke-verkeersborden-en-verkeersregels-gelden-in-nederland)
- [Netherlands: RVV 1990, Annex 1](https://wetten.overheid.nl/BWBR0004825/2021-07-01)
- [Belgium: FOD Mobility road-code programme and sign modernization](https://mobilit.belgium.be/nl/file/12525/download?token=WfU_uvhA)
- [Belgium: official publication of the new public-road code](https://news.belgium.be/fr/publication-du-nouveau-code-de-la-voie-publique)

Belgium needs an explicit versioned rule/sign decision before activation. The
official material now contains both the original 1 September 2026 target and a
later FOD Mobility report recording postponement to 1 June 2027. The current
signs remain in transition, so the Belgian pack must pin the legal effective
date and the applicable sign catalogue instead of silently mixing old and new
codes.

These findings reduce the data-acquisition risk: the owner does not need to
supply a new image corpus for the current classifier-baseline path, and the
Panoramax archives are not required by the apps. The remaining work is
technical: produce the two mobile exports per country, calibrate them against
country-grouped evidence, verify detector/classifier parity and temporal
validated-passage behavior, then generate and sign runtime manifests.
