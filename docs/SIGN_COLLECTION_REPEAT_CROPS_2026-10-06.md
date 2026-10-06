# Repeated exact-frame crops and recorded-drive comparison

The owner approved bounded repeated crops on 6 October 2026. Both clients now
commit one sighting after two supporting frames spanning 100 ms, then collect
up to six regular crops at least 500 ms apart. Two further crops are reserved
for a view whose normalized sign area is at least 1.5 times the largest
successfully saved area. Eight successful crops is the encounter maximum.
Tracks expire after two seconds without support; session/privacy reset also
clears selection state. Multiple same-class signs retain independent tracks.

The observer retains only geometry. There is no extra model inference,
sharpness scoring, retained full-frame sequence, or delayed sighting commit.
The coordinator attempts at most four crops per processed frame, converts the
iPhone frame once when needed, and preserves Android's bounded frame ownership.
Missing frames and per-frame capacity skips consume no slot or interval.
Storage failures consume the interval but retain the slot for a later retry.

Every crop carries a new crop UUID and its own exact analyzed frame time,
frame token and box, linked to the original sighting UUID. Existing opaque,
metadata-free PNG encoding, downward extension, clipping, permissions, queue
limits and best-effort delivery remain in use. Private crop pixels come from
the analyzed camera buffer, not a detector thumbnail or a separately timed
Panoramax still. A box from a video frame cannot be applied blindly to a later
still; accurate still-image crops would require a fresh detection/alignment.

The crop contract now also permits nullable `vehicle_position` using the same
Position schema as sightings. Both clients snapshot the location for each current
analyzed frame before asynchronous storage and attach its coordinates, course,
accuracy and frame/fix timing to that crop, independently of the immutable parent
sighting. Missing GPS is explicit null; replay crops remain unlocated. The
inspector prefers crop position and shows GPS course/accuracy/timing, with an
explicit sighting-level fallback only for old manifests lacking the field.
The crop-position extension was subsequently installed on the attached iPhone as
version 1.4, build 10041; see the deployment record below.

## Replay evidence

The newest saved recording copied from the attached iPhone was completed on
5 October, approximately 18:59:34–19:17:43 UTC. It contains 1,088.923 seconds of
3840×2160 video. Its SHA-256 is
`9ba3ed8c64f6d62b4eca27e7783ad41d01f1ce8a97d623b03f551a1ffba88b03`.
Source bytes, logs, pixels and request/acknowledgment records remain outside Git
at `/private/tmp/youspeed-repeat-crops-20261006/`.

Fresh bundled Swiss Core ML inference used iPhone Vision preprocessing on Mac,
with native-resolution decoded frames sampled every 100 ms. The production
Swift observer and PNG encoder produced both the previous first-crop baseline
and the new sequence from exactly the same detections.

| Measure | First qualifying crop | Bounded sequence |
| --- | ---: | ---: |
| Analyzed frames | 10,890 | 10,890 |
| Sightings | 48 | 48 |
| Crops | 48 | 92 |
| Encoded bytes | 2,320,842 | 4,810,655 |
| Encounters with more sign pixels | — | 20 of 48 |
| Encounters with at least 1.5× sign area | — | 17 of 48 |

The maximum largest-crop sign-area ratio was 11.21×. Twenty-eight sightings had
only one sample, so the median across all encounters stayed at 1×. Extra
generation for the 44 later crops took 848 ms total, with median 18.84 ms per
additional crop, including frame conversion when needed and disk writes.
These are unpaced Mac measurements, not live phone CPU/battery/thermal results.
Larger sign area is a detail proxy, not proof of sharpness or correct recognition;
later frames can still contain motion blur. Recorded compressed video differs
from both the original live buffer and Panoramax photographic stills.

The initial two-frame-per-second coarse replay qualified only four sightings
and missed the later-crop benefit. Its results are retained separately and
were not selected for upload. The recording lacks reconstructed GPS and visual
calibration; uploaded vehicle/sign positions are null, and UTC is estimated
from file completion time minus duration.

The fake installation UUID is `b4c71b1a-73e9-4737-b3cf-4d8a108f17de`. Upload
payloads identify `dashcam_replay`, `simulated_installation`,
`recording_time_estimated`, and `gps_missing`, with app build `dashcam-replay`.
Only sequence crops are selected for upload. Model component provenance records
the actual detector artifact hash and its known pre-existing manifest hash
discrepancy documented in `SWITZERLAND_TEST_READINESS_2026-09-27.md`; neither
model bytes nor manifests were changed here.

## Verification and reproduction

Shared Swift/Kotlin vectors cover cadence, reserved growth, the hard maximum,
failed/skipped capture, distinct same-class signs, expiration/reset, correction
identity, and durable sighting-before-crop ordering. Native PNG/store tests cover
two distinct frame crops linked to one immutable sighting and independent drain.
Swift host checks passed. All 11 Android collection tests passed, including
selection counts and current boxes across the complete 10,890-frame replay.
The signed iPhone build passed six native collection tests on the attached
iPhone 14 Pro. Android app and instrumentation APKs built; physical execution
awaits the detached Android phone. The initial repeated-crop checks used unchanged shared contract bytes; the subsequent optional crop-position extension is verified separately below.

Run the local Mac harness with a private source/output directory:

```sh
scripts/tsr/collection/run_dashcam_replay.sh VIDEO MODEL_PACK OUTPUT 0.1
python3 scripts/tsr/collection/summarize_replay.py OUTPUT/report.json
python3 scripts/tsr/collection/upload_replay.py --report OUTPUT/report.json \
  --model-pack MODEL_PACK --recorded-start-utc ESTIMATED_UTC
python3 scripts/tsr/collection/upload_replay.py --upload OUTPUT/upload-plan.json
```

The uploader validates shared schemas and model/image identities, creates a
fresh simulator UUID, preserves request identity on retry, and requires an
active `best_effort_v2` backend before sending. On this Mac's Python installation,
`SSL_CERT_FILE=/etc/ssl/cert.pem` supplies the trusted system CA bundle; HTTPS
verification stays enabled. Replay inference requires native macOS media/Core ML
services. Android trace verification uses `YOUSPEED_REPEAT_CROP_REPLAY_TRACE`
and Gradle `--rerun-tasks` so an existing test cache cannot hide the new trace.

## Deployment coordination

Build 10040 was installed and tested, then temporarily restored to the compatible
existing build 10038 when the still-active earlier backend protocol was discovered.
The owner explicitly approved coordinated backend release
`5421cb15073cc7abfc3ac01bdc9943207a1fe407`. Its 432-file source archive and shared
runtime image were built, verified and staged on live-eu and volz-db, preserving
the current static seed revision and data volumes. Live-eu's complete runtime
transaction and YouSpeed intake activation succeeded; public charging-service
health checks passed and intake advertises `best_effort_v2`.

All 92 sequence crops and 48 sightings received successful backend upload
acknowledgments under the simulator installation above (95 acknowledged requests,
including two consent controls and one sighting batch). The inspector now lists
all 92 crops linked to all 48 sightings. Every imported manifest equals its
prepared request, with matching crop identity and encoded SHA-256; three fetched
image bodies also match the original byte lengths and hashes. Replay build markers
and null GPS are preserved. Existing archive import completed before management
activation. The administrator then activated the matching approved runtime on
volz-db: archive checksum and management preflight passed, both report and exchange
services started, and the revision-pinned bounded cron was installed. A read-only
check confirms the configured management revision is
`5421cb15073cc7abfc3ac01bdc9943207a1fe407`; after activation the inspector still
lists the exact 92 expected crop IDs and 48 linked sightings, while live intake
continues to advertise `best_effort_v2`.

The iPhone was updated again after live activation; device inventory confirms
version 1.4, build 10040. Launch was blocked by the phone's lock state. Android
build 10040 and its instrumentation APK are ready; physical installation and
parity execution require the detached phone. Private run logs retain the full
deployment, upload and device evidence.

## Crop-position extension verification

The subsequent frame-position extension passed Swift host collection checks,
including distinct course/fix metadata on repeated crops and durable queue
preservation. All 12 targeted Android collection unit tests passed, and the app
and instrumentation APKs built. The iPhone simulator app and test targets built;
phone tests were not rerun at this initial verification stage. The five inspector
JavaScript tests and 18 inspector HTTP tests passed (plus 18 HTTP subtests).
Thirteen targeted sibling-backend tests passed, including optional/invalid
position validation and preservation of distinct crop positions through intake
and signed archive export. Shared schema bytes, native pins, generated requests,
Swift/Kotlin numeric parity and PNG metadata checks passed. Logs/output are in
`/private/tmp/youspeed-crop-position-checks/` and the adjacent
`youspeed-crop-position-ios-*.log` files. Production activation is not included.

## Crop-position extension iPhone deployment

The owner authorized commit, push and deployment to the attached iPhone on
6 October 2026. Backend contract commit
`e378973ea0` was pushed to `Woladen.de-analytics/main`; app commit `4071d55`
was pushed to `youspeed.de/codex/youspeed-v1.4-app-foundations`. The app's shared
source lock now references the committed backend schema rather than a local
working-tree extension.

A signed device build used `MARKETING_VERSION=1.4`,
`CURRENT_PROJECT_VERSION=10041`, and the existing development team. Device
installation succeeded on the attached iPhone 14 Pro. The device's installed-app
inventory independently confirms bundle `de.youspeed.SpeedConsumer`, version
1.4, build 10041. The packaged crop schema and manifest match the source and
native contract pin. Initial launch was rejected by iOS because the phone was
locked. The owner subsequently confirmed the phone was unlocked and the app
was launched. The follow-up focused device test could not start: both CoreDevice
and Xcode then reported the iPhone unavailable to this Mac, so no passing native
test result is claimed for build 10041. The signed test target had built
successfully. Host collection, Android unit, inspector and backend checks remain
the verified automated evidence for this extension.
Build/install evidence is retained in `/private/tmp/youspeed-crop-position-*`.
No backend or inspector production deployment was performed in this step.

## Hugging Face archive replay

The owner requested the same simulation for the archived dashcam videos. The
two verified backup manifests at dataset revision
`bd12056313e00acc790d25ebe5486aac11f4cf79` identify 41 unique original camera
recordings: 15 iPhone and 26 Android, totaling 28,253,099,029 bytes. Duplicate
source paths are merged by SHA-256; derived review/overlay clips are excluded.
Native camera movies from device workload tests are included, and may contain
no qualifying signs. `validation-movie.mp4` is included because the build 10021
device report confirms it is original camera footage, despite its generic name.

One original is already documented as unfinalized crash evidence:
`277a274a1423d5582bba334ebcb25565627a8ec06ddc0e2ac67c441d712f5c5b`,
681,557,690 bytes. Its restored hash matches, but it has no `moov` index and its
`mdat` extends past the file end; AVFoundation returns −11829/−12848. This agrees
with `LANE_ANDROID_LOG_AUDIT_2026-10-01.md`. Its verified original is retained in
the private restore directory; it produces no replay uploads, and no specialized
container-recovery claim is made. The other 40 originals continue through replay.

A visual check of recording `81d5cfae8e631f40` shows the same give-way sign in
`baseline-44.png` and the later `sequence-61.png`, with 8.37× original sign pixel
area in the later sample. Both are native decoded crops, with no generated detail
or upscaling. Files are in that recording's private replay directory. This is a
checked example, not an assertion of dataset-wide sharpness or label accuracy.

The batch runner restores only each selected object, verifies its original
size and SHA-256, inspects it with native AVFoundation, then runs the same
production crop replay at 100 ms intervals. Each recording with sightings gets
a fresh simulator installation. Upload provenance includes `hf_archive_replay`,
the original recording platform and `model_country_assumed`; crop frame tokens
include the verified video SHA-256. The inference implementation and app-platform
marker remain iPhone Core ML on Mac even for Android-origin recordings. The Swiss
pack's country denotes the model domain, not a recovered journey country.
Positions remain null. Android filename milliseconds provide an estimated start
when available; other files use the backup source mtime minus video duration.
Neither method asserts exact GPS/capture synchronization.

Private progress, source evidence, per-video traces, requests and acknowledgments
are in `/private/tmp/youspeed-hf-replay-20261006/`. `results.json`,
`parallel-results.json` and `extra-results.json` are resumable disjoint recording
indices. The first part ran sequentially; the remaining recordings use two bounded
workers with separate indices and recording directories. Each uploader stays
below 120 requests/minute; combined nominal traffic stays below the backend's
300 requests/minute edge bound. Future replay timing includes any contention
between those two Mac workers, recorded in source evidence and limitations.
With `--release-video-copies`, only restored files whose original
hash still matches are removed after successful replay; original backup objects,
backup manifests and verification records are preserved. Each worker restores
one current source; at most one additional upcoming source is prefetched. This
bounds disk use, and each restore requires a 4 GiB free-space reserve.
The batch is currently in progress; completed counts and inspector checks will
be recorded when all selected originals have finished.

`scripts/tsr/collection/replay_hf_archive.py` accepts an explicit archive plan,
model pack, compiled replay/probe binaries and output directory. `--upload`
authorizes delivery of prepared plans; reruns preserve acknowledged request
identities. Compile `probe_dashcam.swift` with `swiftc -parse-as-library` and the
replay binary from the same production sources used by `run_dashcam_replay.sh`.
