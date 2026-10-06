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
container-recovery claim is made. The other 40 originals completed replay.

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
indices. A network-interrupted download was resumed in `retry-results.json`;
that successful checkpoint supersedes its earlier failed download entry. The
final union is `archive-results.json`, with `archive-summary.json` and
`recording-index.md`. The first part ran sequentially; the remaining recordings use two bounded
workers with separate indices and recording directories. Each uploader stays
below 120 requests/minute; combined nominal traffic stays below the backend's
300 requests/minute edge bound. Future replay timing includes any contention
between those two Mac workers, recorded in source evidence and limitations.
With `--release-video-copies`, only restored files whose original
hash still matches are removed after successful replay; original backup objects,
backup manifests and verification records are preserved. Each worker restores
one current source; at most one additional upcoming source is prefetched. This
bounds disk use, and each restore requires a 4 GiB free-space reserve.
All 40 readable recordings completed. Fifteen contained no qualifying sightings
and generated no simulator installations. The remaining 25 recordings uploaded
under independent simulator installation UUIDs. The one unfinalized original
is recorded as `unreadable_source` in the final union, with its verified bytes
and failure proof preserved. There are no unresolved replay or upload failures.

`scripts/tsr/collection/replay_hf_archive.py` accepts an explicit archive plan,
model pack, compiled replay/probe binaries and output directory. `--upload`
authorizes delivery of prepared plans; reruns preserve acknowledged request
identities. Compile `probe_dashcam.swift` with `swiftc -parse-as-library` and the
replay binary from the same production sources used by `run_dashcam_replay.sh`.

## Completed HF replay results

The pinned original recordings contain 18,733.936 readable video seconds, sampled at 10 frames/second. The batch analyzed 187,361 frames, qualified 2,472 immutable sightings, and uploaded 5,360 sequence crops across 25 simulator installations. All 5,448 prepared requests have successful acknowledgments and retain their original identities and request hashes. Baseline crops remain local.

| Measure | First qualifying crop | Bounded sequence |
| --- | ---: | ---: |
| Crops | 2,472 | 5,360 |
| Encoded bytes | 29,839,790 | 73,189,435 |
| Encounters with more sign pixels | — | 1,014 |
| Encounters with at least 1.5× sign area | — | 858 |

All 2,472 baseline encounters have sequence crops and can be compared. Median largest sign-area ratio is 1.00×, maximum 54.95×. These describe geometry, not reviewed classification accuracy or image sharpness. Every encounter remains at or below eight sequence crops.

Read-only inspector verification found every expected crop ID: 5,360/5,360. All imported manifests equal the prepared requests, with matching encoded hashes and source frame tokens. Their parent sighting IDs match the prepared crop-linked set (2,472 sightings); metadata-only sightings are not fabricated into media. One image body per simulator installation was fetched and checked against its original byte length and SHA-256. Source-platform and simulator flags, estimated timing, and missing GPS are preserved.

## Observed upload timing

Across the HF batch, 2,472 sightings received 5,360 crops. Mean upload service time is **1.815 seconds per sighting with crops**, median 0.949 seconds. Mean per crop is 0.837 seconds; mean crop count per sighting is 2.168. Total summed crop-upload service time is 4,486.746 seconds across concurrent installations. A sighting is an immutable tracked encounter, not a deduplicated physical sign across journeys.

Sum each crop acknowledgment timestamp minus preceding request acknowledgment, grouped by immutable sighting UUID. Includes 0.55 s client pacing, HTTP/network/file overhead and retry gaps. Excludes consent/sighting-only intervals, replay/restore and archive import delay. Sum across concurrent installations is client service time, not elapsed batch wall time. Pure network latency was not recorded. No separate per-request start/latency timestamps were recorded, so this is a paced client measurement rather than a pure network-transfer benchmark. Backend import delay is excluded. Detailed acknowledgment-derived calculations are in `upload-timing-summary.json`.

## All volz-db crops by sign class

A direct PostgreSQL snapshot at `2026-10-06T15:56:14.367620+00:00` authenticated as the read-only `youspeed_report` role in `youspeed` on the documented volz-db private database endpoint. It counts **5,695 crop records** across 61 stored classes, including **5,360 HF replay crops**. All rows of youspeed.media across every installation and epoch, including inactive/expired records if still stored. Left join retains unclassified crops. Classes use model_label, with canonical_code fallback; these are recorded labels, not reviewed ground truth.

| Sign class | Crops | Linked sightings | HF replay crops |
| --- | ---: | ---: | ---: |
| `pedestrian_crossing` | 646 | 272 | 618 |
| `give_way` | 623 | 252 | 579 |
| `no_parking` | 375 | 183 | 375 |
| `maxspeed:30` | 371 | 145 | 371 |
| `maxspeed:70` | 359 | 169 | 359 |
| `parking` | 343 | 234 | 298 |
| `hazard` | 284 | 110 | 282 |
| `priority:start` | 263 | 159 | 261 |
| `maxspeed:50` | 262 | 117 | 258 |
| `no_stop` | 249 | 135 | 249 |
| `hazard:pedestrian_crossing` | 144 | 55 | 144 |
| `hazard:road_works` | 139 | 70 | 135 |
| `arrow_right` | 132 | 89 | 125 |
| `maxspeed:40` | 126 | 56 | 123 |
| `no_overtaking` | 111 | 52 | 111 |
| `no_entry` | 109 | 51 | 102 |
| `hazard:wild_animals` | 107 | 43 | 107 |
| `hazard:school` | 102 | 26 | 102 |
| `hazard:traffic_signal` | 99 | 31 | 87 |
| `maxspeed:60` | 82 | 53 | 78 |
| `maxweight` | 81 | 39 | 79 |
| `maxspeed:80` | 75 | 37 | 63 |
| `hazard:slippery` | 73 | 34 | 73 |
| `hazard:intersection` | 70 | 20 | 70 |
| `tunnel:start` | 68 | 59 | 21 |
| `no_overtaking:hgv` | 67 | 55 | 10 |
| `no_way` | 66 | 40 | 61 |
| `maxspeed:100` | 46 | 29 | 33 |
| `zone:no_parking` | 40 | 24 | 40 |
| `pedestrian:start` | 32 | 24 | 32 |
| `hazard:bicycle` | 22 | 9 | 22 |
| `motorway:end` | 15 | 4 | 14 |
| `priority:forward` | 14 | 11 | 3 |
| `zone:30` | 13 | 7 | 13 |
| `hazard:zigzag:left` | 12 | 10 | 12 |
| `maxheight` | 10 | 6 | 10 |
| `hazard:rocks` | 8 | 4 | 8 |
| `no_pedestrian` | 7 | 2 | 7 |
| `exit` | 4 | 4 | 0 |
| `no_dangerous` | 4 | 4 | 4 |
| `no_u_turn` | 4 | 4 | 3 |
| `arrow_through` | 3 | 3 | 3 |
| `hazard:crossing` | 3 | 3 | 3 |
| `hazard:level_crossing` | 3 | 2 | 3 |
| `hazard:narrow_right` | 3 | 1 | 3 |
| `no_hgv` | 3 | 3 | 3 |
| `arrow:red` | 2 | 2 | 0 |
| `bad` | 2 | 2 | 0 |
| `hazard:narrow_both` | 2 | 2 | 0 |
| `Maximum speed 100 km/h` | 2 | 2 | 0 |
| `min_distance` | 2 | 2 | 2 |
| `Start of 30 km/h zone` | 2 | 2 | 0 |
| `stop` | 2 | 2 | 0 |
| `trunk:start` | 2 | 2 | 0 |
| `arrow_right_down` | 1 | 1 | 0 |
| `arrow_turn_right` | 1 | 1 | 0 |
| `bicycle:start` | 1 | 1 | 0 |
| `hazard:bumps` | 1 | 1 | 1 |
| `Maximum speed 50 km/h` | 1 | 1 | 0 |
| `no_dangerous_liquid` | 1 | 1 | 0 |
| `traffic_signal` | 1 | 1 | 0 |

The class totals equal an independent `SELECT count(*) FROM youspeed.media` in the same repeatable-read, read-only transaction. No active-media filter or simulator-only filter is applied. The gallery intentionally applies consent, deletion and expiry filters, so it may display fewer crops than this all-records count. The sortable export is [HF_REPLAY_CROP_COUNTS_2026-10-06.csv](HF_REPLAY_CROP_COUNTS_2026-10-06.csv).

## Recording-to-simulator index

| Source SHA-256 prefix | Origin | Duration (s) | Sightings | Sequence crops | Simulator installation UUID | Status |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `00706e93f69657e0` | android | 0.200 | 0 | 0 | `—` | no sightings |
| `7701f1def79a3177` | android | 0.934 | 0 | 0 | `—` | no sightings |
| `9cd0627f79f2a729` | ios | 0.165 | 0 | 0 | `—` | no sightings |
| `42751ee96f2dd9e0` | ios | 1.698 | 0 | 0 | `—` | no sightings |
| `1edf61fcb7be249f` | ios | 3.265 | 0 | 0 | `—` | no sightings |
| `9f038b18d8a07685` | android | 23.076 | 0 | 0 | `—` | no sightings |
| `d91669b185d26e2a` | ios | 7.367 | 0 | 0 | `—` | no sightings |
| `4805cf29b15ccf09` | android | 31.313 | 0 | 0 | `—` | no sightings |
| `5531a364c961051c` | android | 37.615 | 0 | 0 | `—` | no sightings |
| `643f5cc258b3d78a` | ios | 229.085 | 0 | 0 | `—` | no sightings |
| `9e649a4d9c2fc4fc` | android | 64.656 | 25 | 62 | `454b235c-0110-408f-80c3-0369e0de8ed8` | uploaded |
| `f622d4746220f98b` | ios | 30.368 | 1 | 3 | `1ed9eaaf-7318-47a9-b4e4-546bf668184f` | uploaded |
| `c677ab0a1dce9fd5` | ios | 44.135 | 7 | 29 | `e79799ac-23cc-4726-b787-a48efce5efd9` | uploaded |
| `3d30561e54f39549` | ios | 65.070 | 6 | 30 | `367eaebb-60c1-4f20-8118-3721ff1d752f` | uploaded |
| `900a302386dc2ad9` | android | 175.938 | 37 | 65 | `cd0835ab-f444-4599-a811-4455ceed8e29` | uploaded |
| `167880a6243f8737` | ios | 135.912 | 18 | 34 | `6cb12aa3-fdc8-404b-9f89-c2d1c0aa4f07` | uploaded |
| `f365898fde4363f7` | android | 432.575 | 53 | 114 | `8d1d7b5e-88ad-4aad-9938-3b96fc1700b5` | uploaded |
| `bff0e9bef3acc918` | android | 435.876 | 55 | 127 | `0591cab5-7650-4552-a422-9befd7f6ef97` | uploaded |
| `56ee1b44115b0284` | android | 538.317 | 87 | 167 | `5536c8fc-d7c7-4714-b7ff-81196ccb05b3` | uploaded |
| `3a1523b40f4e8f15` | ios | 120.542 | 0 | 0 | `—` | no sightings |
| `282c717cbddb8b99` | android | 573.631 | 126 | 283 | `2a307340-08d5-4773-ba09-2ac1d05126b3` | uploaded |
| `df520e672db85d24` | android | 559.026 | 80 | 177 | `596b4740-736d-4cfe-b674-b776c7a40383` | uploaded |
| `81d5cfae8e631f40` | android | 598.740 | 81 | 197 | `267647ca-8e93-41c1-891e-fd95bd0f805e` | uploaded |
| `f033a13f4a4a73d3` | ios | 144.112 | 0 | 0 | `—` | no sightings |
| `d4c41d82259a34d5` | android | 597.808 | 135 | 326 | `0e902155-1c09-48ae-9367-0a43af5d1641` | uploaded |
| `93d6161b30bb1c43` | android | 611.203 | 0 | 0 | `—` | no sightings |
| `991e2dad4b84db28` | android | 610.813 | 0 | 0 | `—` | no sightings |
| `277a274a1423d558` | android | — | — | — | — | Unfinalized original |
| `7f25c4c0057b202e` | android | 646.628 | 142 | 337 | `c7674bf3-3805-48d5-bac1-a17050203b07` | uploaded |
| `f4e3fea877da7e8b` | android | 655.498 | 32 | 64 | `316b3530-5f48-41ce-b001-158a3e70a015` | uploaded |
| `556e0ed4392e8763` | android | 786.187 | 100 | 237 | `b9ca937b-e86f-4855-914b-ae36dd103f71` | uploaded |
| `9d5af19d0bc18e4e` | ios | 213.758 | 46 | 110 | `5df2bc08-73ac-481f-928f-35ca962b3570` | uploaded |
| `9186883347a86a9f` | android | 990.342 | 152 | 381 | `9f330944-b0e4-46e5-a61c-7781fc749682` | uploaded |
| `2fe183d9c2946f68` | ios | 504.138 | 87 | 152 | `a8ab3e7d-6d88-4e98-956c-edad207f509f` | uploaded |
| `5a92dae03a379741` | android | 1637.084 | 261 | 577 | `94bb7e86-213b-4927-b179-1ca48febd3aa` | uploaded |
| `7b535a3ea3fde0ee` | android | 1740.437 | 239 | 497 | `2f041332-0e35-43ab-9a14-1a59b1c1ca96` | uploaded |
| `db92ae8297b5ea86` | ios | 562.238 | 93 | 230 | `f972dbbb-287f-4dfd-a08c-4dbee7bf01f4` | uploaded |
| `f9c2b76a58b08d13` | android | 1745.271 | 223 | 423 | `428585fe-b686-4bd7-b5ca-481659719a91` | uploaded |
| `b6751a95dd8166a3` | android | 2086.027 | 246 | 502 | `adb78f1e-5097-4461-aacb-994d6904b267` | uploaded |
| `abd4974dc4a06b17` | ios | 1057.672 | 140 | 236 | `5fb64a5b-a8aa-4f57-8889-36574e02ec63` | uploaded |
| `4984daac923fef78` | android | 35.214 | 0 | 0 | `—` | no sightings |

The original full SHA-256 is also present in each uploaded `hf-replay:` frame token. Private source aliases and pinned object paths remain in `archive-plan.json` and per-record source evidence. Source restoration preserves the archived objects and original backup manifests.

The latest inspector package `cd89bc0a07402225` was built with 155 hash-verified files and staged on volz-db; its archive SHA-256 is `ed4856b8851e00052e53ffad89a59913ceb1e020db57f61f1fe7013cb3d4591d`. The administrator redeployment helper preserves the previous container for rollback. All 64 inspector JavaScript tests and 18 HTTP tests passed, and the served gallery JavaScript hash matches the latest local code. This inspector update does not change the accepted backend runtime revision.
