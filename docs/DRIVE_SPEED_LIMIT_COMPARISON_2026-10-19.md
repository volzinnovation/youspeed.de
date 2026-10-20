# Android/iPhone speed-limit comparison — 19 October 2026

The historical full-frame recognition validation below predates the fixed mobile
window. The current input and native upload-crop behavior is documented in
[MOBILE_TSR_WINDOW_2026-10-20.md](MOBILE_TSR_WINDOW_2026-10-20.md).

Both attached phones ran build 10053. The main differences are incorrect
zone inputs on iPhone, later restoration of those incorrect enclosing zones,
and an Android recognition crop that excludes legitimate signs on the left.
These are distinct from supplementary text OCR and its short display lifetime.

## Evidence and comparison method

Read-only USB copies are outside Git in
`/private/tmp/youspeed-drive-2026-10-19/`. `evidence-manifest.json` records
snapshot sizes and SHA-256 hashes. The iPhone app/upload was not restarted,
stopped, updated or otherwise controlled. Neither phone was redeployed during
this investigation. Selected original photos were checked against the SHA-256
in each phone's photo metadata; image inspection respected EXIF orientation.

The compared moving-trip window is **09:24:23–10:05:22 CEST** (UTC+2).
Each phone has 2,460 matching-log samples in that window. Nearest-time pairing
within one second matched all 2,460 iPhone samples; median timestamp separation
was 0.419 seconds, median position separation approximately 12.4 m. This confirms
the shared trip but does not make the two camera frames pixel-identical.

Use three distinct sources:

- `tsr_applicability_v1.batch.candidates`: raw camera classes and scores.
- `speed_reference_camera_offer_v1`: confirmed camera offers, resulting source,
  value, evidence ID, producer frame/action and pending-context status.
- `match.ndjson`: `speedLimitOverrideKmh` records the resulting presented limit;
  `result.speedLimitKmh` is the map lookup. It must not be counted as another
  camera recognition.

`compare_speed.py` deduplicates offers by evidence ID/value, not physical sign.
`speed_intervals.py` compares the one-second resulting-limit samples. Durations
below are approximate sampled durations. They are not recognition-accuracy
estimates. End signs producing a statutory/enclosing 100 km/h are not literal
recognitions of a printed “100” sign.

## Material differences in resulting speed limits

All times are CEST; values are km/h.

| Time / sampled interval | iPhone | Android | Trace/evidence |
| --- | ---: | ---: | --- |
| 09:25:45.749 | 30 briefly | 60 | iPhone confirms `zone:30` at the extreme left, alongside a 60 sign. The zone is committed at 09:25:45.924; 60 replaces its immediate value at 09:25:46.067. |
| 09:26:18–09:29:48, ~211 s | 30 | 100 | Both process the maximum-speed end. iPhone restores the previously committed 30 zone as enclosing context (`:enclosing` evidence); both maps report 100 for 210 of the 211 differing samples. |
| 09:30:45–09:30:48, ~4 s | 20 | 30, then 40 | iPhone confirms `zone:20`; the photo within 0.04 s shows a rectangular 40 / Kurort information panel. Both maps already report 40; Android confirms the actual 40 at 09:30:48.166. |
| 09:31:40–09:31:42, ~3 s | 30 | 40 | Another iPhone `zone:30` offer replaces 40 until iPhone recognizes 40 again at 09:31:42.794. Both maps remain 40. |
| 09:41:31–09:42:13, ~43 s | 100 | 70 | iPhone recognizes the end-of-70 sign on the left. The 09:41:28 iPhone photo clearly shows it. Android's logged candidates in the corresponding interval contain no `maxspeed:end`; both maps report 100. |
| 09:45:10–09:45:11 | 20 | 70 | iPhone confirms `zone:20` from the rectangular 70 / danger information panel, visible in the photo within 0.37 s. It returns to 70 at 09:45:11.461. |
| 09:45:41–09:46:08, ~28 s | 20 | 100 | After an all-restrictions-end passage, iPhone restores the false 20 zone. Android returns to the statutory/enclosing 100. |
| 09:46:37–09:48:28, ~112 s | 20 | 100 | After another end-of-70 passage, iPhone again restores the false 20 zone. Both maps report 100 throughout these differing samples. |
| 09:48:34–09:49:56, ~83 s | 30 | 50 | iPhone confirms a real 30-zone sign at a side-road entrance, visible in the nearby photo, as if it applied to the current road. Both maps remain 50. |
| 09:54:31–09:54:37, ~7 s | 70 | 50 | Both offer camera 70, initially while context is pending. iPhone exits that pending road context at 09:54:31.147; Android at 09:54:37.864. This is context/adoption timing, not a missing 70 recognition. |

## Why the camera inputs differ

Every one of the Android trip's **5,670** analyzed frames logs the same saved
visual-calibration crop: **left=591, right=1600, top=0, bottom=1200**. Android
therefore removes the left **36.94%** before detector/classifier inference.
Calibration revision: `e258ddcc-0d4a-46a1-8833-2c064b9c5ed5`.

All **10,154** analyzed iPhone trip frames have `visual:none`, with no calibrated
crop, at 3840×2160. These counts are analyzed frames, not recognized signs.

The build 10053 implementation applied this crop before inference in
`android/app/src/main/java/de/youspeed/android/alpha/AndroidTrafficSignRuntime.kt`;
iPhone applied the equivalent crop when a compatible calibration existed. The working-tree fix below removes it on both platforms.
This is an actual configuration/input difference, not evidence of a different
state-machine policy. The missed end sign appears in the left portion of the
scene; the crop is a strong explanation, although an exact Android analysis-frame
replay would be needed to isolate crop effects from field of view and motion blur.
The Android photo at 09:41:28.649 also has visibly more blur on the left sign.

The crop can also exclude side-road zone signs that iPhone admits. More full-frame
detections therefore do not necessarily mean more correct applicable speed limits.

## Where the incorrect iPhone values originate

The five unmatched iPhone zone-start offers are at 09:25:45.749 (30),
09:30:45.046 (20), 09:31:39.505 (30), 09:45:09.456 (20), and
09:48:34.063 (30). Their classes are from live camera inference, not map data or
supplementary text OCR. Android does not make corresponding zone-start offers at
these encounters; it does make a separate 30-zone offer later at 10:03:39.508.

Two mechanisms are established:

1. **Classification:** information panels containing 40 or 70 are classified as
   `zone:20`. The 09:45:09 candidate has classifier score 0.9741 despite the photo
   showing 70. Increasing a generic confidence threshold alone is insufficient.
2. **Applicability:** a correctly recognized zone sign on a side road is applied
   to the current road. The diagnostics for the five iPhone frames report
   `UNKNOWN` with `camera_calibration_unavailable` (or unqualified track evidence),
   while applicability is in `shadow` mode. These diagnostics are not an enforced
   veto on the existing live camera path.

Once committed, a false zone is retained as enclosing context. An ordinary posted
limit can temporarily cover it; a later end sign restores it. The 30/100 and
20/100 disagreements are therefore not all fresh misreadings of end signs.
The resolver has retained a bad upstream zone input. Both logs identify the same
shared reference policy, `1.1.0` with SHA-256
`497e157de2d04ed067897ecc9abde29ecf304a4147c9897b26e71d5c5fc0fcd9`.

The working-tree recognition changes below address the photographed information-panel false positives and side-road admission. The shared reference policy and Swift/Kotlin interpreter semantics remain unchanged.

## Separate UI/OCR fixes prepared locally

The earlier requested controls/OCR fixes are implemented in the working tree:
controls and Settings remain available below 4 km/h and without a usable fresh
GPS signal; display-only OCR text survives misses and same-class tracks until a
different class replaces it. Speech/capture freshness remains separate. Android
no longer cancels an already admitted utterance solely because the three-second
OCR evidence lifetime ends. Both clients now log speech submission/gating and
completion/interruption information for future diagnosis.

Validation: Android 717 unit tests, zero failures/errors, one existing skipped
case; debug APK built and updated device tests compile. iPhone simulator: 54
focused tests, zero failures, one skipped fixture; the UI test covering 18
speed/orientation combinations passes. These changes have not been installed on
either attached phone. The subsequent recognition changes are described below.


## Recognition admission changes prepared locally

Both camera runtimes now analyze the full upright source frame, including when
visual road calibration is saved. Calibration continues to guide lane analysis;
it does not crop TSR input. Diagnostics explicitly report `full_frame` and the
full source rectangle. Camera resolutions, models and shared reference policy
are unchanged.

A separate live admission guard operates before numeric fusion and finalization:

- A `zone_start` requires native on-device OCR of the primary panel to read
  `ZONE`/`ZONA` and exactly the class's numeric value. The 40/Kurort and 70/danger
  panel examples cannot be accepted merely because the zone classifier scores
  highly. This primary proof is separate from supplementary-plate OCR and is
  bounded to two zone candidates per frame, native crops of at least 48×48 and
  at most one megapixel. Unreadable or unavailable proof withholds the zone.
- Known branch/competing-corridor decisions veto display, immediate authority
  and passage even in the existing shadow mode. With no metric camera pose,
  peripheral maximum-speed signs on the side of a nearby linked branch are
  also withheld, provided the road fix/course are fresh and reliable.
- An uncalibrated verified zone additionally needs a central, growing,
  unambiguous approach observed in at least two frames on a fresh stable matched
  road. Extreme-left side-road zones remain observations. A new traversal onto
  that road can establish its own approach; a stale or missing road cannot.
- Rejection is cancellation rather than an analyzed disappearance, so it cannot
  finalize a previously observed candidate. Other valid signs from the same
  frame remain eligible. Raw detections and annotation evidence remain available
  for diagnostics and collection.

This is conservative applicability filtering, not a claim of complete legal
lane or road inference. In particular, a real zone whose panel is too small or
unreadable is withheld rather than guessed. End signs are not rejected simply
for appearing on the left. Exact recognition improvement for the missed end sign
still requires a comparable analysis frame or a new drive; a nearby saved photo
is not that frame.

The retained OCR display is independent of fresh speech/capture evidence. It
survives misses, textless same-class observations and track fragmentation, and
clears on an admitted class replacement or explicit display/session reset.
The actual three-second controller timeout clears only the fresh evidence.

Final validation: Android 724 unit tests, zero failures/errors, one existing
skipped test; debug app and instrumentation APKs compile. Both native Android
emulator checks pass: bundled ML Kit primary-panel proof (positive zone,
mismatched zone number, 40/Kurort and 70/danger negatives) and the actual
three-second controller expiry retaining display text. The isolated test host
used `de.youspeed.android.testhost`, never the installed driving app.

The final iPhone recognition/OCR simulator run passes 57 tests, with zero
failures and one external-fixture skip. This includes primary-panel native
Vision OCR, saved-calibration/full-frame inference, side-road and actual-turn
cases, late untracked zones, class replacement and actual controller expiry.
The preceding run also passes all 14 controls tests. The shared reference checker
passes all 39 scenarios / 171 steps and confirms unchanged artifact hashes and
both app pins. `git diff --check` passes.

Validation logs/results remain outside Git:

- `/private/tmp/youspeed-admission-final-verification-android.log`
- `/private/tmp/youspeed-admission-native-android-final.log`
- `/private/tmp/youspeed-admission-final-verification-iphone.log`
- `/private/tmp/youspeed-admission-final-verification-iphone.xcresult`

The Android phone disconnected during validation. Native Android verification
therefore used a disposable read-only emulator, which was stopped afterward.
Neither attached production app has been replaced by these changes; the iPhone
uploading session was left undisturbed.
