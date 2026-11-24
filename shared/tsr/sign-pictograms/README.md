# National sign pictograms

`national-set-index-v1.json` is the country-set contract. Germany (`DE`) is the
active runtime set. France (`FR`), the Netherlands (`NL`) and Belgium (`BE`)
now have expanded reviewed artwork, transparent PNG renditions and explicit
model-code selections under `national/<country>/`; Switzerland (`CH`) is
explicitly tracked as not ready. The foreign sets remain runtime-blocked
until country legal-action review, calibrated TSR models, device evidence and
runtime manifests are accepted. Do not reuse the German sign artwork for those
countries.

The index is validated by `national-set-schema-v1.json`. The existing German
assets remain in `originals/` and `png/` for compatibility with the shared
catalog and both mobile clients. Foreign sets are physically separated so a
country-specific source cannot be mistaken for a German equivalent.

Reviewed on 2026-09-16 against the user-supplied [German sign plate since
2017](https://de.wikipedia.org/wiki/Bildtafel_der_Verkehrszeichen_in_der_Bundesrepublik_Deutschland_seit_2017)
and the German StVO. The plate identifies artwork; the law determines the
meaning. These are offline UI assets, not training samples or proof of model
recognition capability.

`national/<country>/manifest.json` records the official regulation reference,
Commons source page, pinned SVG bytes, transparent PNG bytes, license,
commercial-use decision, per-file provenance and hashes for each reviewed
entry. The regulation is the authority for the sign code and meaning; the
checked-in vector is the separately licensed Commons rendition. The approved
policy is to exclude only a source whose declared licence does not permit
commercial use; attribution and share-alike conditions remain binding.
`national/<country>/selection.json` is the reviewed Panoramax-model-code to
national-sign-code mapping. Its `source_model_class` records the published
classifier label, while `runtime_model_class` stays null until legal action
semantics, an evaluated/calibrated model and runtime evidence are available.
`fetch_national.py` recreates
these manifests only from the checked-in source selection and never turns a
core artwork subset into a runtime pack.

`../prolix-de-class-catalog-v1.json` preserves the 142 ordered labels in the
bundled Core ML and TensorFlow Lite classifiers. Both exports bind to checkpoint
`e10f4a7f8a2d2c3554dc0ef2d0e1f96e98948c7648432ed13098ef05ff6c3299`.
Its first 134 indices retain the original Panoramax `classify_de_road_signs`
vocabulary from revision `5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790`.
Reference catalogs and pictogram aliases do not define additional model outputs.

## Files and verification

- `originals/`: original Commons SVG bytes, without artwork edits.
- `png/`: 8-bit PNG renditions fitted inside 256 × 256 pixels, preserving aspect
  ratio and transparency. Both mobile apps use these same bytes.
- `contours/`: separate white source contours with a dark backing edge for the
  MobiData cue. These contain no sign artwork. Both apps draw the same bytes
  behind an unchanged German pictogram, at 1.125 times its square image frame.
  A 16 px transparent margin surrounds the 256 px reference square. The contour
  leaves a gap outside the sign and ignores interior lettering/cutouts.
  Regenerate with `python3 scripts/tsr/generate_mobidata_contours.py` (Pillow and
  NumPy); `--check` verifies every pinned input and deterministic output.
  `contours/manifest.json` records both hashes. This decoration does not change
  artwork eligibility, recognition, map authority or the speed-reference policy.
  The cue requires the exact source ID `mobidata-bw-vzk`. Primary limits also
  require current bundle authority and an inventory sign/town/reset origin;
  pending camera limits, camera end-sign overlays, stale/unknown values and
  speed capture suppress it. OSM inventory fallbacks never acquire this cue.
- `national/CH/originals/` is the source-preparation exception: the ASTRA
  converted vectors are normalized to their artwork bounds and carry the
  `data-normalized="artwork-bounds"` marker. Their pre-normalization hashes are
  retained as `source_original_sha256` in the Swiss manifests.
- `manifest.json`: original URLs and upload timestamps, Commons page revisions,
  authors, public-domain basis, original SHA-1/SHA-256, PNG SHA-256, dimensions,
  sizes, commercial-use decision, licence-source URL, per-file provenance, and
  the conversion command. German manifest paths are relative to this
  directory; national manifests use paths rooted at `shared/tsr/sign-pictograms`.
  Catalog image paths instead are relative to `shared/`.
- `selection.json`: explicit sign-code-to-Commons-title selection, derived from
  the plate. It is not a fuzzy filename search or automatic semantic mapping.
- `national/<country>/`: country-specific expanded artwork manifests, source indexes,
  selections, SVGs and transparent PNGs. The foreign SVGs are licensed Commons
  renditions tied to official national regulation sources; the selections are
  artwork evidence only until runtime model evaluation and calibration are
  complete.
- `sources/`: the reviewed deployed DE mapping and its snapshot provenance.
- `sources/panoramax-country-code-mapping-v1.json`: complete FR/NL/BE/CH model
  class-to-country-code snapshot with source hash and artwork coverage status.
- `../foreign-runtime-readiness-v1.json`: blocked foreign-pack handoff with
  the shared detector/export contract and missing-evidence gates; it is not a
  downloadable runtime manifest.
- `THIRD_PARTY_NOTICES.txt`: offline credit and licensing notice for packaging
  with the PNG assets.

From the OpenSign Core checkout, verify the artwork bytes and image dimensions.
The acquisition scripts, report builder and historical reconciled PDF are
maintained in [the Core pictogram directory](https://github.com/volzinnovation/opensign-core/tree/codex/opensignmap-mvp/core/src/main/assets/tsr/sign-pictograms).

```sh
python3 core/src/main/assets/tsr/sign-pictograms/fetch.py

# Recreate one foreign core set (network + ImageMagick required)
python3 core/src/main/assets/tsr/sign-pictograms/fetch_national.py FR --fetch
```

To restore missing assets, use `fetch.py --fetch`. This requires `curl`, network
access and the pinned ImageMagick version for each missing PNG (7.1.2-3 by
default; newer additions and DE:1044-10 use 7.1.2-31). It fetches pinned originals sequentially, verifies
their hashes, and recreates PNGs locally. Two renderer exceptions, signs 206
and 250, use separately pinned Commons PNG renditions: ImageMagick's SVG reader
loses their lettering or red ring. `png_source_kind`, source URL and source
hash record this distinction. Different bytes fail verification;
the script never updates the manifest or overwrites an existing mismatched
file. Review an intentional source/renderer update separately. PNGs were
produced on aarch64 with ImageMagick 7.1.2-3 Q16-HDRI, except DE:1044-10,
regenerated with 7.1.2-31 on 2026-10-21 to restore its opaque white face and
complete outline. Its original SVG is unchanged. The manifest records this
exception in `png_renderer` and `png_renderer_version`; `fetch.py` checks the
exact version before rendering a missing PNG. Another platform may
render different bytes and correctly fail that reproducibility check.

## Review the German source labels

Edit [source-crosswalk-v1.json](source-crosswalk-v1.json) in OpenSign Core.
The `mobidata.DE` keys preserve all 53 literal `Verkehrszeichennummer` values
in the pinned MobiData BW review, including qualifiers. `normalized_code`
records the parsed value. `sign_code` records the national identity the
resolver may report. `classifier_labels`, `classifier_capability` and
`classifier_exact_variant_supported` describe the 134-output classifier
named in `source_metadata.mobidata`. The file retains pictogram eligibility
and references from that review. Additional qualified German sign codes can
be resolved on input. The source metadata records the audited inventory date.

The `mapillary.DE` keys are native traffic-sign labels. Printable speed limits
and their end signs use `mapillary_speed_templates.DE`. Panoramax's 134
classifier IDs, followed by eight Streetshots outputs, come from the ordered
`class_labels` in [the German model catalog](../prolix-de-class-catalog-v1.json).
The catalog's other sign entries supply presentation aliases. Model vocabulary
and artwork are maintained separately so a display change preserves output indices.

Every central Synset label (0–210) has a `synset.DE` entry. Its numeric key
is the publisher's Parquet `label`. `class_name` is the raw Parquet name,
`source_name` is the German publisher caption and `source_artwork` links the
reference diagram. The two crossing-sign families share Parquet names, so
use the numeric ID for them. `sign_code` follows the federal VzKat designation
and printed values on the source sign. `sign_code_scope: family` identifies
chevron boards whose physical dimensions prevent assigning a specific variant.
`target_label` is the reviewed label. The status `approved` identifies a deployed
classifier target. The status `reference_only` identifies a label without a model
output index. A JSON null and `mapping_status: unmapped` record an unresolved ID.
`mapping_basis` explains the review decision. The metadata pins the dataset
revision, federal designation reference, attribution and license. The entries
cover the main sign in each Synset image. Training counts belong to the dataset
that samples from this mapping. [Publisher sign table](https://synset.de/datasets/synset-signset-ger/) · [Federal sign designations](https://www.verwaltungsvorschriften-im-internet.de/BMVBW-S32-0001-KF10-BS-A008.htm)

Open the [classifier-by-provider CSV](https://github.com/volzinnovation/opensign-core/blob/HEAD/docs/source-labels-de.csv) to
review the 142 German outputs in model order, followed by approved reference targets
that have no deployed output index. The Mapillary review marks German-scope exclusions
as `excluded_de` and reference targets as `reference_only`. Each assignment has its own row.
The first column repeats the target, and the provider's column contains its native ID.
Filter by target to see all its assignments. A target with no assignment gets a single row
with empty provider columns. Synset uses numeric publisher IDs. The Panoramax column
covers its original 134 outputs. Use `--grouped` for the previous layout with all IDs on one row per target. The final column links a public pictogram. It uses the catalog artwork when it
represents the target, followed by a reviewed MobiData, Synset or Mapillary
example. A representative example can show one variant of a broader family.
A blank means there is no verified pictogram for that output. The [unresolved IDs](https://github.com/volzinnovation/opensign-core/blob/HEAD/docs/source-labels-de-unresolved.csv)
retain sources with ambiguous or unsupported targets and the reason for each decision.
The OpenStreetMap column contains accepted German `traffic_sign` notation.
The [German OSM traffic sign catalogue](https://trafficsigns.osm-verkehrswende.org/DE)
shows pictograms for the IDs its selector supports. Some accepted IDs have no picture in the selector.
The MobiData column contains literal IDs observed in the pinned BW inventory.

The [Mapillary pictogram review](https://github.com/volzinnovation/opensign-core/blob/HEAD/docs/mapillary-de.md) places each
publisher sprite beside its German reference. The scope comprises the 60 labels
in the Baden-Württemberg inventory dated 2026-11-20, existing German aliases,
and publisher-supported numbered variants of the two German speed templates.
The Mapillary section of the JSON records the pinned sprite revision and the
visual evidence for each source ID. For example, the pitched roof over the P
distinguishes `information--parking--g2` from the plain P in `information--parking--g1`.
The MobiData rows retain the historical 134-class capability fields alongside
the current `target_label` and its review basis.

Regenerate the review files from the Core repository root.

```sh
python3 scripts/review_sign_crosswalk.py --code DE:206
python3 scripts/review_sign_crosswalk.py --code DE:274-50
python3 scripts/review_sign_crosswalk.py --target maxspeed:end
python3 scripts/review_sign_crosswalk.py > docs/source-labels-de.csv
python3 scripts/review_sign_crosswalk.py --unresolved > docs/source-labels-de-unresolved.csv
python3 scripts/review_sign_crosswalk.py --mapillary-markdown > docs/mapillary-de.md
```

For source-native application lookups, `resolve_sign(source, label, country)`
returns `SourceSign(source_label, sign_code, image_path)`. For a cross-source
comparison, `review_source_sign` also returns the reviewed classifier target
and national-code scope. It can return a Survey-specific artwork hint for
Mapillary labels that lack a reviewed national code.

| German sign | MobiData BW | Panoramax | Mapillary | Synset |
|---|---|---|---|---|
| Stop, `DE:206` | `DE:206` | `stop` | `regulatory--stop--g1` | 14 · `Stop` |
| 50 km/h, `DE:274-50` | `DE:274-50` | `maxspeed:50` | `regulatory--maximum-speed-limit-50--g1` | 2 · `Geschwindigkeit50` |

Synset 93 is `DE:244.1`, the start of a cycle street. Its classifier target
is unresolved because inspected `bicycle:priority` training photos show a
RESPEKT campaign sign. Synset 6 is `DE:278-80`; it belongs to the broader
classifier class `maxspeed:end`. National identities and model targets can
therefore be reviewed independently.

## Display contract

[Source crosswalk v1](source-crosswalk-v1.json) defines reviewed Mapillary
class mappings, MobiData aliases, and country-specific display fallbacks. It
also maps supported [OpenStreetMap `traffic_sign` values](https://wiki.openstreetmap.org/wiki/Key:traffic_sign)
such as `stop` and `give_way` to national signs with catalog artwork.
[`sign_crosswalk.py`](../sign_crosswalk.py) joins these with the existing
national catalogs for Panoramax class IDs and OpenStreetMap `traffic_sign`
codes. It retains the original label and exposes the sign code and image
path separately. A representative image supplies no additional evidence
about the sign's printed value, variant, or direction.

OpenSign Core owns this data, including the reviewed German catalog and its
reference examples. Edit the catalog and artwork here before updating the
consumer pins. The examples illustrate sign families with unknown printed
values or variants. Keep `display_eligible` and `sign_code` independent of
those examples.

Survey uses the files directly from its pinned Core checkout. Inspector and
YouSpeed preserve their existing offline build paths using generated snapshots.
From a committed Core checkout, regenerate them with:

```
python3 core/src/main/assets/tsr/sync_sign_crosswalk.py --profile inspector ../streetshots-inspector
python3 core/src/main/assets/tsr/sync_sign_crosswalk.py --profile youspeed ../youspeed.de
python3 core/src/main/assets/tsr/sync_sign_crosswalk.py --profile analytics ../Woladen.de-analytics
```

Each snapshot records the Core revision and SHA-256 hashes. Consumers can
verify their checked-in copy offline with
`python3 shared/tsr/sync_sign_crosswalk.py --verify-local .`. Analytics
uses the same command with the script in `commercial_backend/youspeed/crop_taxonomy`.

Render the PNG alpha directly, without a white card or background outside the
physical sign outline. White sign faces, lettering and borders remain opaque.
The shared PNGs have transparent exteriors. Do not turn white pixels
globally transparent, which would also erase required parts of the signs.

`display_eligible` means that a faithful pictogram exists for the entry. It does
not authorize a speed override or decide which signs belong in the secondary
sign card. Numeric speed signs may have artwork while the UI uses its main
speed display for them. Speed actions remain governed by the reviewed model
manifest and passage/state logic.

The first 142 `signs` entries correspond exactly to `class_labels`, preserving
the original 134 indices and appending eight outputs. Additional exact
`DE:278-x`, `DE:281`, `DE:282`, `DE:310`, `DE:311` and semantic aliases are
inventory/reference entries, not model outputs. The model recognizes town
boundaries as `city:start` and `city:end`; exact source-code aliases do not add
outputs or establish recognition performance.

The exact reference entries for DE:315 variants, numeric DE:262–266 and
DE:273 variants, DE:220, DE:241 and DE:357 variants use the official
Verkehrszeichenkatalog designations and the individually pinned Commons SVGs.
Decimal codes retain the VzKat comma. Filenames use a dot for the decimal
separator. The optional `reference_example_sign_code` points from a family
entry to an example for the Inspector WFS map. The map marks the example
with a question mark and identifies its example code on selection. Exact
reference assets and family examples leave the classifier vocabulary and
driving presentation rules unchanged.

The numeric `DE:278-x` aliases are also available to the OSM/MobiData inventory
display independently of the camera vocabulary. Use the exact source sign code
or its explicitly parsed printed speed to select the shared asset. A generic
`DE:278` without a printed value cannot acquire a number from the vehicle speed,
the current speed reference, or an adjacent sign. The owner-confirmed fallback
is the shared unnumbered end-sign pictogram (`de-282.png`) when the printed value
is missing. The `DE:278` inventory alias uses this existing artwork with the
maximum-speed-end label; it retains the source's `DE:278` semantics. This affects presentation
only; the speed-reference state-machine policy is unchanged.

The DE:278 source review on 2026-11-03 confirmed 14 existing variants: 5, 10,
20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120 and 130 km/h. They match the
[BASt list of official designations, page 7, published in the ministry's VwV-StVO amendment material](https://www.bmv.de/SharedDocs/DE/Anlage/Gesetze/Gesetze-20/zwoelfte-allgemeine-vwv-zur-aenderung-vwv-stvo.pdf?__blob=publicationFile#page=58).
No official-source `DE:278-25` artwork was identified. The classifier's
`maxspeed:25` label is not evidence of such an official artwork; adding it
requires a verifiable source SVG and provenance, rather than editing another
sign's digits.

The [integrated BW source audit](../../../docs/DE278_BW_SOURCE_COVERAGE_2026-11-03.json)
records 9,769 generic MobiData `DE:278` entries without a printed value and 621
numeric OSM sign tokens on 618 nodes. Of those OSM tokens, 620 have reviewed
artwork; the remaining `DE:278-57` has no reviewed mapping. Neither snapshot
contains a 25 km/h end sign. Packed OSM records retain their original tags and
verified way memberships. Driving presentation admits only an exact reviewed
variant with an explicit directional source tag and a matching current road;
these observations do not create cancellation boundaries or speed offers.

Blocked entries have `display_eligible: false` and `image_path: null`. They cover
invalid/background/unknown classes, missing reviewed mappings, wildcard or
left/right variants, and numeric restrictions whose values are not model
outputs. For example, generic `maxheight` must not display a made-up 3 m limit;
generic `maxspeed:end` must not display a made-up crossed-out 30. The explicit
`maxspeed:25` model class is retained but currently has no matching asset from
the supplied plate. Generic `zone:end` does not identify a zone's number;
`zone:30:end` has a specific 30-zone-end pictogram.

## Representative Synset pictograms

The German display crosswalk names a reviewed Synset example for selected
classifier classes without dedicated artwork. Each `synset_id` links to the
publisher face under `synset.DE`. The local PNG is and remains an example of the
class. A pictured placement, direction, gradient or zone type is specific to
that face. Synset 199 illustrates the generic `hazard:incline` output with an
uphill warning. Synset 198 depicts a downhill warning and maps to the
`hazard:decline` reference label, which has no classifier output index.
Synset examples are listed separately from exact German inventory artwork and
carry their own credit. [Artwork attribution](THIRD_PARTY_NOTICES.txt)

## Reviewed mapping corrections

The catalog retains source-map provenance and documents its changes per entry:

- `arrow_turn_left` maps to DE:209-10; `arrow_turn_right` maps to DE:209. The
  deployed DE map interchanges these two pictograms.
- Model labels `hazard:left_turn` and `hazard:right_turn` map to DE:103-10 and
  DE:103-20. The deployed map uses different label spellings and maps its
  `hazard:turn_right` to DE:101-20, which depicts aircraft rather than a bend.
- The actual `zone:30:end` label maps to DE:274.2. It is absent from the deployed
  cross-country table.
- `exit` remains blocked: the deployed DE:460 is a numbered motorway detour,
  which does not establish an unambiguous exit pictogram.
- The deployed incline mappings also interchange ascent/descent. The actual
  classifier only emits generic `hazard:incline`; DE:108 is retained as a
  family-level reference, but no direction or percentage is fabricated.
- `bicycle:priority` uses DE:244.1 as the closest German equivalent
  (Fahrradstraße), while `parking:disabled` uses the precise German wheelchair
  supplementary sign 1044-10 used with DE:314.

These are display mappings; they do not change the deployed Prolix service or
the classifier weights. Existing model labels can themselves remain imperfect
predictions and must pass the app's recognition confidence/temporal gates.

## Speed-related legal distinctions

[StVO Anlage 2, items 55–60](https://www.gesetze-im-internet.de/stvo_2013/anlage_2.html)
distinguishes the following signs:

- 278 ends the indicated maximum-speed restriction.
- 279 ends a prescribed minimum speed.
- 280 ends the general overtaking ban.
- 281 ends the overtaking ban for vehicles over 3.5 t. It does not end a speed
  restriction.
- 282 ends route-specific speed restrictions and overtaking bans. It does not
  cancel every traffic rule or universally establish unlimited speed.

An end sign integrated into a lane panel applies to the indicated lane.
General vehicle/road rules and any separately applicable enclosing zone must
still be resolved before assigning a new speed.

[Anlage 3, items 5–6](https://www.gesetze-im-internet.de/stvo_2013/anlage_3.html)
defines 310 and 311 as the beginning and end of a built-up area. Under
[§3(3) StVO](https://www.gesetze-im-internet.de/stvo_2013/__3.html), the ordinary
urban maximum is 50 km/h for motor vehicles. A town exit requires vehicle and
road context; it is not an unconditional 100 km/h or unlimited-speed command.
Town names in the original pictograms are official illustrative artwork, not
recognized text or the user's location.

## Licensing

The German files are public-domain official-work renditions under
[§5(1) UrhG](https://www.gesetze-im-internet.de/urhg/__5.html). Foreign files
retain the license reported by their pinned Commons source, including CC0,
public domain, or CC BY-SA where applicable; attribution requirements are
recorded per file. The owner-approved commercial-use policy excludes only
non-commercial licences. The national regulation URL is the legal reference,
while Commons supplies the checked-in vector rendition. Do not relabel an
original or remove a required attribution.


## Expanded German vocabulary (2026-11-10)

The bundled 142-class checkpoint preserves the original 134 indices and adds
`city:start`, `city:end`, `bus:stop` (DE:224), `supplementary:plate`,
`maxspeed:90` (DE:274-90), `DE:156-10`, `DE:325.1` and `DE:325.2`.
`scripts/tsr/build_de_expanded_catalog.py` binds the frozen 142-label order to
an actual candidate checkpoint and writes matching catalog and class mappings
for both native clients. Its SHA-pinned 134-class baseline is retained under
`../baselines/de134-expanded-reference-2026-11-09/`; future builds do not derive
their predecessor from mutable deployed packs. Candidate generation and
deployment remain separate. Field F1 still requires approved review labels.
The original HF training-crop audit places DE:223.1-50 in the existing `lanes`
family and DE:460-20 in `exit` (numbered motorway diversions); these do not
receive duplicate classifier heads. Their exact inventory pictograms remain
available, while a family-level camera result cannot establish the subtype.

The generic supplementary-plate family has no unique official pictogram.
It deliberately has no image or invented sign code, and is not eligible for
the pictogram card. Its translated text label records unresolved content.
The model mapping routes it through the existing supplementary-plate role
with an unknown restriction; OCR or human review must establish the content.
DE:224 and DE:274-90 use unmodified Commons official-work SVG renditions,
rasterized with ImageMagick 7.1.2-31. Source URLs, revisions and hashes are
pinned in the manifest; see the source audit under
`docs/collection-evidence/2026-11-09-de-expanded-classifier/asset-sources/`.


DE:625-20 was added as exact inventory/reference artwork on 2026-11-09.
The official VwV-StVO catalogue specifies **rechtsweisend, 500 × 500 mm**.
The Commons filename's historical “Aufstellung links” describes placement
on the left side, not a left-pointing arrow. The unmodified source is by
Mediatus after Bundesverkehrsministerium specifications (PD-GermanGov/PD-VzKat).
A train-only audit found both arrow directions and adjacent guide-board forms
in existing `arrow:red`; its output remains broad and has no directional
pictogram. The classifier stays at 142 classes. The already frozen field-review
catalog is retained unchanged as its own presentation revision.
