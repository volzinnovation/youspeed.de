# Mapillary supervision for the mobile sign detector

14 November 2026. Feasibility study using a frozen Hugging Face export and cached Mapillary data. The product owner selected a feasibility study before an exhaustive visual review.

**Use Mapillary to find likely missed signs and prioritize review, then train from verified image boxes.** Removing Mapillary classifications from the matching inputs is useful: it avoids reinforcing wrong classes and supports a single `sign` detector. A geographic point alone cannot establish that a sign is visible, which panel it identifies, or where its image rectangle lies.

The study audited the inventory and metadata of **all 35,147 images**, visually inspected **16 stratified images**, and checked original-resolution details in four. It did not visually review the remaining 35,131 images, establish a corpus-wide matching accuracy, or train a new model. Visual findings are model-assisted review proposals, not adjudicated ground truth.

## What the HF copy contains

The pinned dataset revision is [`d2c5cc44716166e2604655d7fd8cad93a8dd9468`](https://huggingface.co/datasets/loffenauer/streetshots/tree/d2c5cc44716166e2604655d7fd8cad93a8dd9468/data/2026-11/detector). Its source cutoff is **12 November 2026, 20:07:58 UTC**. The month is the export month; captures span 4 September–11 November.

| Check | Result | Interpretation |
| --- | ---: | --- |
| Full images and matching sidecars | 35,147 each | All indexed as active and media verified |
| Unique image hashes | 35,147 | No exact byte duplicates in the index; related views still require grouped splits |
| Frames with normalized sign boxes | 12,493 | 22,339 sign boxes in total |
| Frames without normalized sign boxes | 22,654 | Unreviewed scenes, not certified negatives |
| Frames marked exhaustively sign annotated | 0 | A complete transfer is not complete ground truth |
| Earlier full-instance image IDs retained | 34,556 / 34,556 | Plus 591 additional images |
| Image GPS positions inside BW | 29,409 | 5,738 outside; boundary-crossing sightlines remain possible |

**The HF export is not restricted to images with sign classifications.** Its exporter selects all `panoramax_items`, without an annotation filter. It includes every image from the November 10 ready-image instance inventory, whose storage/catalog reconciliation found no missing or extra paths. This establishes coverage of those frozen inventories, not the current live instance or every photograph ever captured on a phone. No live database was queried.

The export preserves source annotations and edit history. Of the normalized boxes, 22,218 retain detection-model provenance and 121 are labelled `source_annotation`. Neither figure counts human-reviewed boxes reliably: manual class edits can retain the original detection-model tag, and absence of that tag does not prove human authorship. Reconstruct annotation revisions and distinguish **class correction, box correction, and exhaustive scene review**.

The source-plan and final metadata hashes were verified against the HF manifest. All 16 downloaded sample images were independently checked against the final metadata hashes and decoded dimensions. The other image hashes are indexed export evidence, not a fresh local verification of all 94 GB.

## The teacher must use data before app filters

| Mapillary representation | Records | Relevant exclusions |
| --- | ---: | --- |
| Cached unique BW points before class filtering | 868,563 | Geographic boundary and valid source identity only |
| State traffic-sign GeoJSON | 764,478 | Excludes 104,085 general-direction-board records |
| Runtime bundle Mapillary inventory | 534,305 | Further excludes missing artwork, speed/settlement families and one reviewed duplicate |

A class-blind point file was rebuilt from all 14,241 cached cells, retaining **all 868,563 points**, including direction boards. It contains source IDs and coordinates; original classifications remain in the unchanged source caches. This avoids using UI display eligibility as a training-data filter. Completed tile/Graph requests do not establish complete real-world inventory.

The state GeoJSON supplies 2D positions and observation timestamps, but no facing direction, height, position uncertainty or detection confidence, and generally no contributing-image IDs. Only 42 records carry image-review metadata. Its last-seen date falls in 2025–2026 for 292,805 records (38.3%); older and implausible timestamps require explicit handling. Observation dates are not installation or removal dates.

Existing route exports supply the provider's `aligned_direction` for **6,556 unique feature IDs**. Join these by ID for an initial orientation experiment. Verify the angle convention against contributing imagery before using it to reject candidates. The statewide export omitted this field; it is not evidence that the provider lacks it.

[Mapillary describes map features](https://help.mapillary.com/hc/en-us/articles/115002332165-Map-features) as triangulated detections whose positional quality depends on source GPS. Its [official API SDK documentation](https://mapillary.github.io/mapillary-python-sdk/docs/mapillary.config.api/mapillary.config.api.entities/) exposes contributing images and detection geometry. Those polygons belong to the Mapillary source images. Different Panoramax viewpoints require new localization, not copying those polygons.

## Camera metadata needs qualification

Every frame has position, heading, declared FOV and capture/fix times. All 35,147 lack explicit pitch, roll, optical yaw and sensor width. There are 25,554 landscape and 9,593 portrait images, across 3,000 sequences. Panoramax marks 2,213 headings as computed.

Both apps write **vehicle course into `GPSImgDirection`**, rather than measuring optical camera yaw: see [iPhone capture](../../iphone/SpeedConsumerApp/PanoramaxRecorder.swift) and [Android capture](../../android/app/src/main/java/de/youspeed/android/alpha/ConsumerSessionController.kt). A forward-mounted phone on a straight road may make that a useful proxy. Turning, a mount offset, a sideways view or low-speed course instability can invalidate it. `heading_computed=false` does not prove optical calibration.

Every frame reports 5 m GPS accuracy, but every frame also has a missing-GPS-accuracy warning. Treat 5 m as an estimated fallback. Declared FOV values of 67°, 69° and 72° likewise need verification against the actual lens, crop and registered raster.

Preserve and, for future captures, measure:

- Optical view heading relative to true north, vehicle course separately, mount offset, orientation source and uncertainty.
- Exposure time, sensor/fix time and clock alignment; actual GPS uncertainty and course accuracy where available.
- Camera intrinsics or calibrated horizontal/vertical FOV, active lens, stabilization/crop and raster rotation transform.
- Pitch/roll, camera height and an explicit mounting session ID.
- Map-feature facing direction, position uncertainty, contributing image IDs and dates, plus height when available.

For historical photos, recover route continuity and mount orientation from adjacent frames, existing EXIF and visible landmarks. Keep the result an estimated pose. Distance and azimuth can suggest a horizontal search region; vertical projection and a bounding box need additional geometry or visual localization. Buildings, vegetation, vehicles, road crests and sign backs still require image evidence.

## Class-blind spatial pass over every image

The prototype searches within **150 m** and, for qualified landscape-phone metadata, screens by **half the declared FOV plus 15°** around the course proxy. These are experimental search settings, not calibrated visibility bounds. Portrait, computed/mismatched-heading and otherwise unqualified cases retain all nearby points without a cone filter. Original EXIF rotation by 180° is allowed for this central-axis screen; no image-pixel projection is performed.

| Result using all 868,563 cached points | Count |
| --- | ---: |
| Images emitted in the audit | 35,147 |
| Images passing metadata gates for the forward-phone hypothesis | 23,372 |
| Images with any point within 150 m | 24,074 |
| Qualified images with at least one point in the hypothetical cone | 12,884 |
| Images retaining candidates, including unqualified poses | 21,694 |
| Retained image–map-point pairs | 369,171 |

The pair count includes repeated views of the same feature and ambiguous/unqualified candidates; it is **not a count of visible signs or training labels**. Restoring direction boards added candidates to 196 qualified images and added 44,145 retained pairs compared with the filtered state export. The review workload is large enough that pose enrichment, temporal association and visual proposal ranking matter.

## Visual feasibility findings

The deterministic sample balances existing-box/empty-box frames across Android, landscape iPhone and portrait images, with a 250 m spacing rule. It is deliberately diagnostic rather than a prevalence sample. Mapillary classes were not used by the candidate generator.

| Example | Observation | Consequence |
| --- | --- | --- |
| `bb7282d9…` | Six visible faces in two three-panel roadside stacks; six forward Mapillary points cluster about 41 m away, in two bearing groups | Promising class-blind association at assembly level. Co-located point IDs cannot identify individual stacked panels by geometry alone |
| `9960c0e9…` | Existing box covers a no-overtaking face; supplementary panel below it and a farther sign assembly are unboxed | Review the whole image, including small panels around existing detections |
| `00aec52b…` | Clearly visible Frauenalb town sign above a car has no source box; existing annotation is elsewhere | Town-sign training examples can be recovered without new collection |
| `9e624fca…` | Clear reflective chevron board at night, with no source annotations and no cached Mapillary point within 150 m | Empty annotation lists contain useful positives; map-guided review alone would miss this example |
| `66980323…` | Visible sign backs and clipped backs despite nearby map points | Presence in a heading cone does not establish a front-facing sign |
| `89019252…` | Nearly black image with numerous nearby points | Add image usability and visibility states; do not manufacture labels from the map |
| `da508393…` | Foggy village with forward map candidates but no clear face established in the preview | Review original pixels and neighboring frames; do not infer removal or a detector miss |

Approximate original-pixel proposals were independently checked for the supplementary panel, town sign and chevron board. The distant assembly is a review region, not one training box. These findings demonstrate recoverable omissions; they do not establish that every proposed box corresponds to a particular Mapillary feature.

## Training approach and alternatives

The November 11 experimental YOLO26n already learns **one class, `sign`**. Its face/vehicle-plate outputs are inactive compatibility channels; both native consumers use sign proposals. Removing those two output channels is an export/decoder change and should not be expected to produce a large speedup. The subsequent pilot follows the product owner’s narrower scope: destination/direction boards and separate supplementary plates are excluded; town-entry/exit signs remain included. Vehicle registration plates and faces are out of detector scope; upload/server anonymisation remains a separate concern.

The next useful experiment should change supervision before changing architecture:

1. **Build exhaustive sign-only scenes.** Review random full frames, empty-annotation frames, Mapillary candidates, model disagreements and small signs. Apply the agreed pilot scope: retain primary regulatory, warning and non-directional information signs, including town-entry/exit signs; exclude destination/direction boards and separate supplementary plates. Record sign backs, unreadable faces and uncertain regions separately. Certify negative scenes only after full review.
2. **Combine spatial and visual teachers.** Run a stronger offline detector at original resolution or with overlapping tiles; merge its proposals with SGBlur and the current mobile detector. Use Mapillary to prioritize plausible misses and cross-frame association. Accept image boxes after review; unresolved regions remain ignored/partial rather than background.
3. **Test the added value of Mapillary.** Hold architecture, training budget and reviewed splits fixed. Compare reviewed labels alone, reviewed plus visual-teacher proposals, and reviewed plus visual-teacher/Mapillary-guided additions. Measure verified extra boxes per review hour and association errors as well as detector quality.
4. **Focus on small signs and difficult backgrounds.** Use realistic blur, exposure, distance/downsampling and crops; include hard negatives such as advertising, windows and vehicle graphics. Test sliced training/inference at a fixed device pixel/latency budget. [SAHI](https://arxiv.org/abs/2202.06934) motivates this experiment; its reported gains on other datasets are not a forecast for YouSpeed.
5. **Score full encounters and both devices.** Report recall by sign pixel size and condition, false proposals per frame, time to first correct detection, skipped frames, classifier workload and sustained p95 latency. Group physical signs, nearby sites, overlapping routes and sequences before splitting. Existing examples used for tuning are development evidence; reserve fresh geography for independent testing.

Existing evidence supports this priority. On the 64-scene native trial, YOLO26n improved town-sign recall from 2/23 to 6/23 but reduced other-sign recall from 27/48 to 22/48. A separate two-window diagnostic improved town exits from 2/7 to 5/7. Its one-proposal device probe took about 383 ms on Android versus 38 ms on iPhone; increasing false proposals adds costly classifier work. See [trial replay](../../scripts/tsr/town-trial/README.md) and [November 11 device evidence](DE142_REVIEWED_CLASSIFIER_2026-11-11.md).

Begin with a few hundred fully reviewed development scenes, covering the failure types above, plus a separately collected geographic holdout. Calibrate review yield, mapping ambiguity and model benefit there before reviewing all 35,147 images. The exhaustive pass should retain a row for every image and every candidate, with states such as visible, back-facing, occluded, outside frame, too small, stale/absent or ambiguous; preserve unmapped newly found signs equally.

## Reproduction and retained evidence

The offline [audit script](../../scripts/research/audit_hf_mapillary_teacher.py) emits a record for every HF image, including zero-candidate and unqualified-pose images. It reads no semantic sign classes and makes no training-label or visibility claims. Tests cover bearing wraparound, behind-camera rejection, coincident coordinates, missing pose, the date line, streaming input and record completeness.

Local research artifacts are under `output/mapillary-teacher-feasibility-2026-11-14/`:

- `coverage-audit.json`, `coverage-pose-audit.json`, `bw-geographic-coverage.json` contain full metadata checks.
- `mapillary-all-sign-points.provenance.json` pins the class-blind extraction, boundary and source-cache hashes.
- `visual-review-ledger.json` records all 16 inspected images, final hashes, observations and review limitations; `independent-visual-review-05-13-16.json` contains approximate box proposals.
- `summary.json` and `image-candidates.jsonl.gz` contain the full class-blind spatial audit; `bundle-subset/` retains the comparison using the filtered state export.

The [compact evidence record](MAPILLARY_DETECTOR_TEACHER_FEASIBILITY_2026-11-14.json) retains aggregate results and source hashes beside this note. HF images and downloaded source metadata remain outside the source tree at `/private/tmp/youspeed-detector-audit-2026-11-14/`. The large JSONL files are losslessly gzipped; decoded hashes remain equal to the HF manifest. Raw imagery, caches and local research outputs are not added to Git. No model, app behavior or governed speed-limit reference policy was changed or deployed.

```sh
python3 scripts/research/audit_hf_mapillary_teacher.py \
  --tree /private/tmp/youspeed-detector-audit-2026-11-14/hf-tree.json \
  --metadata /private/tmp/youspeed-detector-audit-2026-11-14/hf/data/2026-11/metadata.jsonl.gz \
  --source-plan /private/tmp/youspeed-detector-audit-2026-11-14/hf/data/2026-11/source-plan.jsonl.gz \
  --mapillary output/mapillary-teacher-feasibility-2026-11-14/mapillary-all-sign-points.geojson.gz \
  --output output/mapillary-teacher-feasibility-2026-11-14 \
  --radius-m 150 --cone-margin-deg 15
python3 -m unittest discover -s tests/map -p test_hf_mapillary_teacher.py
```
