# Mobile TSR mapping and pictogram review — 2026-09-10

The mobile apps now preserve all 134 labels emitted by their pinned German
classifier. Android previously named only 19 output indices; the remaining
outputs could not be matched to the Prolix sign catalog. Both bundled manifests
also omitted `no:end`, `motorway:end`, and `trunk:end` from their actionable
mapping. These omissions are corrected without changing model weights or
lowering the passage-confirmation gates.

## Reference and model boundaries

The initially supplied Prolix deployment directory contained empty candidate
maps. The active worker's release deployment contained the populated maps used
for this review. Its German map has 142 entries and identifies
`Panoramax/classify_nl_road_signs/road_signs_mapping.csv@7a81105`, DE column.
The map file SHA-256 is
`76b65eb1d35a4ad5dcb1e25e920b07d7f45fedbbdba08048315bc6075b9b7238`.

The deployed German classifier and both mobile exports share source checkpoint
`Panoramax/classify_de_road_signs@5360aa6f4ef6c7b1998044b18d00b4d0b1a5a790`,
SHA-256 `f8277a3790fd3357b3ca31a086c7dc9f365785c7fa44bfd3b5c68834555699c7`.
The backend uses a larger detector and different crop padding. This change
aligns class identity and reviewed sign semantics; it does not establish equal
detector accuracy or mobile/backend prediction parity.

The [shared catalog](../shared/tsr/prolix-de-class-catalog-v1.json) separates the
134 actual classifier outputs from reference aliases. The
[pictogram provenance manifest](../shared/tsr/sign-pictograms/manifest.json)
records Commons sources, revisions, licenses and image hashes. Ambiguous
classes remain without artwork: a generic height, weight, distance or bend
class must not display an invented number or direction. Corrections to
inaccurate upstream class-to-sign mappings are recorded in the catalog.

## Speed effects

| Sign or model class | State-machine effect |
| --- | --- |
| `maxspeed:end`, DE:278, DE:278-x | End the applicable posted maximum; a numbered alias carries the ended speed and cannot cancel a different posted maximum. |
| `no:end`, DE:282 | End route-specific restrictions and resolve surviving zone, city and road context. |
| DE:280 / DE:281 | End overtaking restrictions only; no speed change. |
| `motorway:end` / `trunk:end` | End the corresponding road context and resolve the remaining context. |
| DE:310 | Typed German town-entry action resolves the city default of 50 km/h after a valid finalized passage. The bundled classifier cannot emit this class. |
| DE:311 | Typed town-exit action resolves surviving context; it does not blindly assign 100 km/h or unlimited speed. The bundled classifier cannot emit this class. |

These effects follow [StVO Anlage 2](https://www.gesetze-im-internet.de/stvo_2013/anlage_2.html),
[Anlage 3](https://www.gesetze-im-internet.de/stvo_2013/anlage_3.html) and
[§3](https://www.gesetze-im-internet.de/stvo_2013/__3.html).
An end sign with insufficient surviving context continues to produce unknown,
masking a stale camera limit. A visible sign alone does not change the main
speed: existing confirmation, physical-passage, visual-loss, generation and
road-context checks remain required.

The classifier emits only generic `maxspeed:end`, not separate 278-x labels.
The aliases fix interpretation of numbered evidence from a capable pack or
diagnostic replay; they do not establish visual recognition of every numbered
end sign. There is also no dedicated truck-overtaking-end class in the current
134-label model.

## Optional other-sign display

A new persisted option, off by default, shows one small pictogram in the upper
right corner. Icons use their existing alpha outside the sign outline, with
no added background; white within the sign remains opaque. An independent
stream considers all admitted primary detections
before speed-oriented fusion selects its candidate. Classifier score must meet
0.90 and the detector must pass the existing admission floor. These are raw
scores from an uncalibrated model, not probabilities.

An accepted non-speed class with faithful artwork replaces the previous icon.
An accepted speed-affecting or unsupported sign clears it. Empty frames,
low-score observations and `bad` rejection classes retain the previous icon.
Disabling the option, stopping the session or invalidating the TSR generation
clears it. The display stream cannot activate or persist a speed rule.
The option and catalog labels are localized in German, English, French and
Dutch. The German catalog is not a new FR, NL or BE recognition model.

## Bernbach Zeichen 310 experiment

The supplied [Panoramax picture](https://panoramax.woladen.de/?pic=a458609a-bbf1-413a-a039-5e0f685e9923&focus=pic)
shows the Bernbach / Stadt Bad Herrenalb / Lkr. Calw town-entry sign.
The source image is 2376 × 4224 pixels, SHA-256
`11c4eb3729167234ec35474192e301b0e74b9f4fd68582d4ccc959e80b43e9ae`.
Annotation `3a3a9e24-e879-41e8-a868-682fe934d952` covers pixel rectangle
`(1827, 2244)–(2039, 2392)`. Source metadata credits provider/producer `admin`
on panoramax.woladen.de under CC BY-SA 4.0. The annotation says
`traffic_sign=yes`; the town-entry identification is the reviewed expectation,
not a model prediction.

Using the unchanged iPhone models through Core ML on macOS CPU, the detector
found the sign with raw score 0.49325. Its mobile crop classified as `bad` at
1.0. The tight annotated crop classified as `bad` at 0.98096; Prolix-style
15% padding also classified as `bad` at 0.99805. This is an actual model run,
not physical-iPhone validation or a successful town-entry recognition.

The real LiteRT runtime on an Android API 36 emulator found the sign with
detector raw score 0.70517, then classified the mobile crop as `bad` at 0.99999.
The tight annotated crop classified as `bad` at 0.98354; the 15%-padded crop
classified as `bad` at 0.99949. None was admitted to the additional-sign display
or the city-entry state transition. The pinned 70 km/h real-image regression
also passed. Scores differ across platform exports and preprocessing; this
single image establishes the current capability gap, not an accuracy benchmark.

The unchanged photo and attribution metadata are retained in
`android/app/src/androidTest/assets/tsr-city310-bernbach.{jpg,json}` for the
native diagnostic test. The reusable macOS Core ML probe is
[`scripts/iphone/probe_city_entry.swift`](../scripts/iphone/probe_city_entry.swift).

The label inventory and image experiment agree: a classifier update with
separate town-entry/town-exit classes and independent validation is needed for
real Zeichen 310/311 recognition. Padding or relabeling `bad` cannot supply
that capability.

## Validation

- Shared TSR contracts: 264 existing tests plus 4 new mobile catalog,
  model-vocabulary, translation and artwork-provenance checks passed.
- Android: Debug and Release builds, 179 unit tests in each configuration,
  and lint passed. The API 36 emulator instrumentation suite ran 47 tests:
  41 passed and 6 were skipped (one opt-in live bootstrap and five missing
  benchmark/replay database fixtures), with no failures. The real LiteRT
  photo diagnostic and sign-display UI test both passed.
- iPhone: Debug simulator build and unsigned device Release build passed;
  256 tests passed with 22 existing optional map/benchmark-fixture and
  physical-device tests skipped.
- All 104 original SVG/PNG pairs passed offline hash/provenance verification
  and visual review. The final Android Debug/Release APKs and iPhone simulator
  Debug/device Release apps contain the exact reviewed catalog and PNG bytes.
- All four iPhone localization files contain the same 284 keys, without
  duplicates. The new Android UI keys are present in all existing static
  localizations; catalog labels cover DE/EN/FR/NL.

Native screenshots exercise synthetic give-way/STOP/replacement/clearing
states while preserving each fixture's main limit: camera-derived 30 km/h on
Android, and 50 km/h with a driving speed of 47 km/h on iPhone. They validate UI
rendering and are not evidence that the models recognized those fixture signs.
The separate Bernbach reports contain actual inference results.
