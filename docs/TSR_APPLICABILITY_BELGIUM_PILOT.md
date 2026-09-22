# Belgium applicability pilot

## Field result, 22 September 2026

The user reported fewer recognitions and unresolved issues after the pilot.
The installed applicability policy was diagnostic-only, so this was not a
successful field fix. Logs and retained videos have been copied locally for
investigation; private images and route traces remain outside the repository.
All 3,018 logged applicability decisions were UNKNOWN. Camera calibration and
reviewed encounter qualification remain missing; enforcement stays disabled.

The available evidence exposed two concrete national-recognition defects:

- The iPhone kept the German model loaded after restoring an installed Belgium
  map. The map country was set before the first route lookup, which then skipped
  model selection because the route had not changed. Country restoration now
  reconciles the runtime and catalog even without a new GPS fix or map download.
  Repeated same-country updates preserve the runtime. Android already reads the
  persisted active country when creating its runtime.
- Both Belgium packs omitted numeric zone classes present in the classifier.
  The metadata generator incorrectly depended on the pictogram inventory for
  these schematic signs. Numeric speed and zone mappings now come from the
  model's actual vocabulary independently of artwork. Non-speed `:end` labels
  are not inferred to end speed restrictions; the affected Belgium mappings are
  corrected on both platforms.

Local replay of 104 logged regions from 86 saved images compared the unchanged
German and Belgian classifiers. Selected visually inspected examples showed
the Belgian model recognizing a 30-zone, town entry and town exit that the
German model rejected, and distinguishing a 50-zone from a posted maximum.
This is a classifier diagnostic on retained JPEGs, not a full-pipeline replay,
independent holdout or route-wide recall estimate. The overall recognition drop
and the original wrong-road failures remain unresolved. No new model weights,
map schema, thresholds or enforcement setting are justified by this comparison.

Regression coverage restores a Belgium map without a location/bundle transition,
checks the actual loaded pack and catalog, exercises rapid country changes and
no-map fallback, and sends Belgian zone classifications through both native
fusion engines. Shared checks keep the two manifests aligned and prevent the
generator from dropping schematic speed classes again.

Validation on 22 September: iPhone suite 329 tests, 23 skipped, zero failures;
47 targeted Android tests; 43 shared Python checks. Device build 10010 succeeds.

## Original collection plan

The first planned collection is the Belgium drive from Bree to Lamorteau. Keep
precise endpoints and private traces outside the repository. No new map-bundle
schema is required for the current implementation; use the existing Belgium
bundle. Any later justified schema pilot must use Belgium.

The software is prepared on `codex/8-tsr-applicability`. On 2026-09-21, the user
authorized committing, pushing this branch and installing this version on the
attached iPhone. The shared policy remains **shadow**; enforcement and broader
rollout still require qualification and separate approval.

Before collection, record the app commit/build, platform/OS/device, detector and
classifier hashes, Belgium bundle hash, shared applicability config hash and
camera mount/orientation. Leave the internal policy in **shadow**. Live camera
calibration is currently unavailable, so UNKNOWN results are expected and are
useful diagnostics, not measured failures against unreviewed imagery.

Use the existing TSR controls and local diagnostic export. If reviewed image
sequences are needed, use the existing explicit recording/diagnostic consent;
metadata alone cannot establish which road a sign serves. Dashcam and Panoramax
retain their independent capture, review and upload controls. Collection does
not authorize uploading or training on recordings.

During later review:

1. Link frame IDs/times to only the separately consented retained images. Keep
   original captures immutable and apply the existing redaction/retention process.
2. Label physical-sign encounters, including visible interval and actual passage,
   sign-class correctness separately from vehicle-path applicability, ambiguity,
   reviewer and provenance. Unknown remains unknown.
3. Tag exits, parallel roads, side-road/ego Yield, opposite direction, left/median/
   overhead signs, curves, splits, junction approach/actual turn, equal-value signs,
   stopped travel, poor GPS/maps, mount changes, low cadence and dropouts. Keep
   negative driving stretches and report missing scenarios explicitly.
4. Group all frames of a drive, repeated physical signs, shared route/geography and
   near duplicates together before allocating development/calibration/holdout.
   A single drive is not independent holdout evidence. Freeze hashes and review
   decisions before fitting; no selection based on model predictions.
5. Replay identical encounter IDs for the old native pipeline and policy ablations.
   Record actual confirmed previews, end/pictogram effects, warnings, finalized
   passages and store contents. The proposal replay tool is not full-image replay.

Commands and contracts: [shared applicability README](../shared/tsr/applicability/README.md).
Minimum-device sustained timing, battery, thermal and shared-camera coexistence
measurements remain pending on both platforms. Do not infer production readiness
from one route or synthetic parity. Optional directed maps and learned reranking
remain deferred until reviewed development failures support them.
