# BW v1.5 attached-device drive review — 2026-10-21

The installed dataset was queried successfully. Nearby inventory encounters,
direction-qualified applicability, controller selection, UI presentation and
camera observation are different measurements. The old builds did not record
painted-screen counts; reconstructed selections must not be described as signs
actually displayed or seen.

## Recorded route and display findings

The iPhone log window is 20:51–21:51 Europe/Berlin: 2,701 fixes and 31.16 km of
connected route. The Android overlapping drive contains 2,630 fixes and 30.90 km;
its later indoor tail is excluded from the geographic comparison.

| Measurement | iPhone | Android |
|---|---:|---:|
| Distinct source sign IDs inside a recorded 10/30 m geofence | 209 | 198 |
| Distinct encounter-journal sign IDs | 209 | 199 |
| Camera-analyzed sign frames | 0 | 0 |
| Reconstructed secondary-slot IDs | 81 | At least 63 ordinary signs; full directed selection unrecorded |
| Actual painted-screen sign count | Unrecorded | Unrecorded |

Android's extra journal sign is an accepted speed-end station crossing without a
GPS sample inside its circle; this is the existing passage fallback, not an
unexplained source record. All expected sampled-geofence IDs appear in both
journals.

On iPhone the 209 nearby IDs include 101 numeric speed signs, 17 town boundaries
and 91 other non-numeric records. Exact logged single-slot selection reconstructs
81 IDs: 72 ordinary secondary signs, seven town signs and two speed ends. Multiple
signs compete for one secondary slot. Fifty-one selections last only one GPS fix.

Direction matters: 25 of those 81 IDs have strongly opposing recorded courses;
23 have independent qualified heading evidence. One additional profile-only
opposition flag is a curved-route nearest-segment artifact and is correctly
retained when evaluated against the actual vehicle course. Stored association
headings follow source geometry and rotate once by 180° for direction -1.

At 10 m the median geometric ordinary-sign window is 1.38 s on iPhone and 1.27 s
on Android. The 20/30 m comparisons give 3.30/4.97 s and 3.16/4.90 s respectively.
Larger circles also admit additional opposite/adjacent-road candidates. The
product owner's correction therefore makes the geofence a trigger and retains
secondary presentation until replacement/invalidation; the live capture and
confirmation gates remain 10/30 m.

The old Android base lookup median is 866 ms (90th percentile 913 ms), compared
with iPhone's 43.57 ms median (95th percentile 47.41 ms). These are query timings,
not measured compositor delays. The updated diagnostics separate lookup stages,
inventory overlay, fix age, selection and presentation lifecycle.

The Android follow-up isolated a concrete query defect: its topology lookup used
`way_id IN (...) OR linked_way_id IN (...)`, but the frozen bundle indexes only
`way_id`. SQLite therefore scanned all 1,753,356 link rows for each lookup.
Every link in this BW bundle has an exact reverse; the incoming clause is
redundant here. The iPhone implementation already uses the indexed outgoing
lookup. The Android parity correction leaves the bundle and legacy no-link-table
fallback unchanged.

Replaying ten recorded locations as read-only arguments to the production
Android matcher in the emulator returned identical road, speed, city, direction
and candidate counts before and after this correction. Median lookup time fell
from 632.24 to 137.13 ms; the topology stage fell from 246.06 to 0.53 ms. These
are controlled emulator measurements, not a measured improvement on the physical
drive. City resolution still costs approximately 114 ms in that replay.

## Speed origin and camera state

On iPhone, 1,957 fixes use explicit OSM values, 576 use inventory rules, 167 use
derived highway defaults and one uses retained inventory town context. The 576
inventory fixes reference 33 distinct sign records, including 25 numeric posted
speed signs. Both OSM and inventory offers entered the existing reference policy
as bundle values; the old UI did not distinguish their upstream provenance.
Android's old `explicit_tag` field also conflated those origins, so its historical
OSM/inventory split cannot be recovered reliably from that enum.

The model loaded on iPhone, and the user's recognition selections persisted.
Every recorded fix on both phones fails the existing night/daylight gate; camera
recognition remained inactive. This was not evidence of a failed model toggle.
The old generic camera/output status did not explain the night pause. Ordinary
photo capture was also selected off after approximately 20:51:42 local; all new
capture batches in this drive are empty. No visual confirmation or successful
inventory photo capture is claimed.

## Panoramax first: are the photo signs in the bundle?

Controlling source: the existing [Panoramax origin](https://panoramax.woladen.de/).
A frozen metadata query returns 2,147 photos in the route bounding box. Of these,
516 cameras lie within 25 m of the route and align with travel within 35°; 881
opposite-direction photos and 750 outside-corridor photos are excluded. The
aligned cohort contains 1,029 sign annotations. Panoramax leads this comparison:
take each forward-facing photo annotation, then look for the same sign and value
in the frozen bundle. These are machine annotations, not 1,029 independently
reviewed physical signs. Repeated photos can show the same sign.

| Result starting from a photo annotation | Photo annotations |
|---|---:|
| Nearby bundle entry has the same sign and value, with one directional candidate | 40 |
| Nearby entry has the same sign and value, but its identity or direction is uncertain | 55 |
| Same kind of sign, exact variant unclear | 18 |
| Nearby speed entry has a different number; physical identity uncertain | 3 |
| Sign type absent from the source dataset | 418 |
| Sign type exists, but no matching nearby entry could be established | 308 |
| Annotation label incomplete or unknown | 187 |
| **Total** | **1,029** |

Thus 95 photo annotations have a nearby same-code/value bundle candidate. Forty
have one candidate with compatible verified direction; 55 remain ambiguous.
The 418 observations cover 31 missing sign families, chiefly stopping and parking
restrictions. They are not 418 distinct missing roadside objects. The 308 other
unmatched observations can reflect missing source coverage, camera/sign offset,
the search window or ambiguous association. No reliable physical-object count
can be recovered from camera positions without object identities or image review.

The three possible number conflicts include one with a single nearby candidate
and two with ambiguous candidate identity. None is a confirmed physical-object
mismatch. The historical builds also did not record an actual painted-screen
count, so neither these photo totals nor reconstructed app selections answer
how many signs the driver actually saw on screen.

## Bundle first: supporting cross-check

Panoramax GPS locates the **camera**, not the sign. Pairing additionally requires
a source sign ahead/in the camera cone, within 30 m, classification confidence
at least 0.8 and compatible source direction. Repeated photo observations are
deduplicated by inventory ID for the following exclusive counts over all 347
source records within 100 m of the route:

| Comparison category | Inventory records |
|---|---:|
| Exact code/value, unique candidate and verified source direction | 26 |
| Additional exact code/value-compatible evidence with ambiguous physical identity | 43 |
| Family consistent, exact variant unresolved | 8 |
| Unique numeric value conflict candidate | 1 |
| Other unresolved associations | 3 |
| No comparable annotation | 266 |

These are metadata associations, not a census of physical signs. Of the 209
sampled-geofence source IDs, 66 have exact-compatible evidence and 143 do not.
Of the 81 reconstructed secondary selections, 15 have exact-compatible evidence
and another six have family-consistent evidence. Missing annotations, model gaps
or unmatched camera positions do not establish that an inventory sign is absent.

The unique numeric conflict is inventory 50 versus an annotated 70 in
[this October 19 photograph](https://panoramax.woladen.de/?pic=ae36cd6e-8f0b-43d1-b73d-333b5b601d95&focus=pic).
Manual source-image inspection confirms a legible 70 sign. The source record is
29.7 m ahead of the camera and directionally aligned, but identifying the exact
physical pole remains unverified; this is a likely mismatch, not a confirmed
inventory error. Wrong-value numeric evidence is never counted as a family match.

The 418 repeated annotation observations above have sign families
absent from all 53 MobiData source classes: examples include no-stopping,
restricted parking, priority road, truck restrictions and roadworks. Five grade,
one weight, two axle-weight and one height observations exist, but generic class
labels do not supply their printed numbers. These counts are photo observations,
not counts of missing physical signs. This explains why the inventory is not a
complete description of every sign visible along the road.

## Reproduction and evidence

- `scripts/research/profile_bw_sign_route.py`: read-only source geometry and
  actual-fix corridor comparison.
- `scripts/research/prepare_bw_drive_map.py`: private map data and shared official
  vector artwork; no coordinate uploads.
- The Panoramax pairing helper and tests under `scripts/research/` and
  `tests/map/` preserve direction, numeric-value and ambiguity checks.
- Private iPhone evidence: `/private/tmp/youspeed-v15-iphone-drive-review/`.
- Private Android evidence: `/private/tmp/youspeed-v15-android-drive-review/`.
- Frozen Panoramax metadata and pair receipts:
  `/private/tmp/youspeed-v15-panoramax-compare/`.

The original materialized bundle remains unchanged with SHA-256
`e1a36e56cc4809cc69d2d5161b993eff21a1c08264e8d9300e79ec7546ccd00b`.
Private coordinates, raw logs and full source responses are not committed in
this report. Mobile follow-up validation and physical installation are recorded
separately; this analysis does not establish a new real-drive acceptance result.

The iPhone build 10058 is installed in place with the existing bundle and all
22 preferences, 1,302 application-support files and 755 media files retained.
Its 53 regression/full-bundle checks passed. On October 22, the normal app launch
succeeded after unlock and all 22 preferences and active BW metadata were
unchanged. The physical UI runner timed out while enabling iOS automation mode
before running a test case, and a fresh QuickTime iPhone preview stayed black.
The user subsequently reported starting the app. A fresh preference read still
showed TSR selected on, automatic photos off and inventory-sign capture selected.
The following read-only UI retry lost its physical test destination, and
CoreDevice reported the paired iPhone unavailable. Dashboard label verification
therefore remains pending; no successful physical camera or drive check is
claimed.
See [the build 10058 iPhone receipt](MOBIDATA_BW_V1_5_IPHONE_DEVICE_INSTALL_10058.json).

The final Android build 10058 includes the indexed topology correction and is
also installed in place. Validation passed 155 focused unit tests, four adapter
and actual full-BW-bundle tests, and 21 matcher/directional integration tests.
On October 22, the actual landscape dashboard revealed missing idle TSR/photo
status labels and a dim speed-origin label against the night background. A small
dashboard correction now mirrors the iPhone's always-visible status labels and
uses the dashboard foreground color for provenance. The corrected normal APK
was compiled, installed in place and hash-verified on the Moto. The physical
dashboard reads `OSM-Karte`, `TSR · Aus`, and `Automatische Fotos aus`; the photo
button reads `Fotoaufnahme starten`. All 28 preferences and the active BW bundle
remain identical; all 1,839 media files and 791 existing queue metadata files
were retained without size changes. Existing logs were explicitly kept at
startup. The preceding runtime test results still apply to unchanged runtime
code; the final UI correction was compiled and checked on the physical device.
Automatic photos remain selected off on both devices, so no inventory-triggered
photo capture is expected until the user enables photo capture. See
[the build 10058 Android receipt](MOBIDATA_BW_V1_5_ANDROID_DEVICE_INSTALL_10058.json).
