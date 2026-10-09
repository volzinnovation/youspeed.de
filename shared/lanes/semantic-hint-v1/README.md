# Semantic-hint qualification cores and offline parity

This is preparatory work for issues #21 and #23. Matching native qualification
and owner-cache cores now live in `iphone/SpeedConsumerApp/LaneSemanticHint.swift`
and `android/app/src/main/java/de/youspeed/android/alpha/LaneSemanticHint.kt`.
They are included in the app source builds but **no live camera/model producer
or asynchronous mailbox is wired to them**. The separate offline selector
experiment can consume a bounded score adjustment; shipped callers retain the
nil/default input. No settings, defaults or protected speed-reference behavior
changes here. Real model usefulness, sustained-device qualification and rollout
remain separate gates.

The semantic reference is `scripts/lanes/qualify_semantic_hints.py`. The adjacent
`contract.schema.json` describes three independent documents: `hint`, `context`
and `policy`. The executable qualifier enforces additional cross-field rules.
Schema validation alone does not establish qualified evidence. Unknown fields
are rejected to avoid silently interpreting a newer contract as this prototype.

## Caller-owned context and immutable policy

The caller supplies the current frame's session/camera/calibration identity,
exposure, full-scene image transform and current clock reading. The hint must
match these exactly. All opaque identities compare their exact UTF-8 bytes; Swift canonical Unicode
equivalence must not merge different session/frame/clock IDs. Model ID, pinned
experiment revision, mask dimensions and
maximum capture age come from a frozen `QualificationPolicy`; a model result
cannot choose its own accepted identity or freshness budget. The synthetic
fixture's 200 ms budget is an **engineering example, not a release threshold**.

All times are integer nanoseconds in explicitly named **relative clock epochs**,
bounded to `0..2^53-1` for exact JSON interchange. They are not Unix nanoseconds,
which exceed this range. The source clock can have a different origin from the
capture/arrival/current clock; source values are compared only within their
source clock identity. Capture, arrival and current readings must share one
known clock identity. Never subtract readings from different clocks. Changing
or rebasing a clock requires a new clock ID and an explicit owner scope reset.

This is not a drop-in mapping for `RoadPathCameraFrame.capturedAtSeconds`, which
currently uses epoch seconds. The native `ClockEpoch` adapter performs checked integer rebasing of an
already-trusted source-presentation or capture-monotonic clock. It rejects
unknown clocks, mixed identities, negative readings/origins and relative values
outside the JSON-safe range. The exposure builder keeps the source and capture
epochs separate; source PTS cannot stand in for a monotonic capture reading.
Native callers must retain the original capture time, use the capture epoch
again for arrival/current time, and reset ownership on any epoch change.

Acquiring and proving the actual camera clock mapping remains unimplemented.
The adapter does not convert wall-clock epoch seconds into a verified camera
clock and must not substitute inference completion time for exposure time.
`clockKnown` is a caller-supplied assertion, not a synchronization measurement.
Unknown mappings, future captures/arrivals, arrival before capture and conflicting
exposure metadata fail closed. The cache rejects current-clock regression.

## Exact-exposure, full-scene evidence only

Only `alignment.mode = exact_exposure` is supported. Frame ID, source timestamp,
capture timestamp and both clock identities must agree with the current frame.
There is no propagation, optical flow, alignment-quality threshold or decayed
reuse. A recently delivered old mask does not qualify for a newer frame.

Geometry declares source dimensions, crop, quarter-turn clockwise rotation,
mirroring, upright analysis dimensions, a versioned mapping ID and full-scene
coverage. Coordinates start at the top left. Version 1 requires `fullScene=true`
and a crop covering the complete declared source image. Even a declared partial
TSR crop is unsupported. The caller and hint must match every geometry field;
shifted crops, rotations, mirroring or resampling conventions fail qualification.
`mappingId` identifies the exact transform/resampling convention; callers must
establish the real pixel-center mapping before assigning the same ID. Matching
declarations do not prove actual image alignment or correct calibration.

Masks are row-major single-channel paint probabilities with explicit Boolean
validity per cell. Width/height must match policy, are each at most 512, and the
total map is at most 262,144 cells. Arrays must have exactly width × height
entries. Every score, including invalid cells, must be finite and in `[0,1]`.
At least one cell must be valid. Invalid cells mean **unknown**, not negative
paint. They must not be sampled as zero or counted as evidence. This contract
does not calibrate scores, assess paint quality, add road-area output, or assign
ego-lane identity. Provenance identifies either actual model inference or a
synthetic fixture; a caller must never report synthetic data as model accuracy.

`qualify()` returns a reason and either immutable `QualifiedHint` evidence or
`None`. Rejections therefore provide zero semantic influence. Validation has a
fixed order; diagnostics report the first failed check, not every possible fault.
`prepare_guidance()` returns the **same baseline object reference** next to this
result, without changing confidence, observed support, confirmation count,
identity, or geometry. This property is tested on actual Swift/Kotlin adapter objects and the Python
reference; it does not establish byte-identical live camera behavior. Native
qualified masks retain their original scores and explicit validity. Kotlin
returns detached score/validity arrays and Swift uses owned value arrays.
Foundation's `NSDecimalNumber` mask values are parsed from their exact decimal
spelling, avoiding multi-ulp differences in `doubleValue`; long-decimal real
model probabilities have a shared regression case.

`qualifyTyped` and `Cache.offerTyped` accept the same metadata envelope with
`mask` omitted, plus explicit width/height and native `Double`/`Bool` buffers.
They share all metadata qualification with the JSON bridge. Shape and finite
`[0,1]` scores (including unknown cells) are checked once on accepted owned
buffers; Boolean validity is guaranteed by the native type. Swift retains arrays
with value/COW semantics, and Kotlin copies arrays before validating them.
Later caller mutation or mutation of returned array copies cannot alter accepted
evidence. Callers must not mutate metadata/buffers concurrently while submitting.

The separate `RoadBoundaryEgoSelector` offline experiment accepts per-candidate
score adjustments in `[0, 0.10]` only after existing eligibility gates. A wrong
count, nonfinite value or any out-of-range value makes the entire adjustment
array a no-op. This contract qualifier never creates those adjustments itself;
it returns qualified evidence alongside the unchanged baseline. Same-image
semantic evidence adds no support rows, observations or temporal confirmations.

## Source-time cache behavior

`HintCache(policy, context)` starts from caller-owned context. `advance(context)`
only accepts non-regressing exposures and current-clock readings within the
same scope, geometry and clock identities. Conflicting frame/timestamp pairs
are rejected without state changes. Only explicit `reset_scope(context)` by the
owner can replace that context and clear cached evidence. Arriving results have
no reset/advance capability; wrong-scope hints cannot invalidate newer evidence.

`offer(hint)` accepts at most one qualified result per source exposure. Duplicate
results cannot replace its scores, and old arrivals cannot overwrite a newer
source timestamp. Invalid arrivals leave the cache intact. `current()` requalifies against the last successfully accepted owner exposure
and clock reading. **It does not read a clock.** Before consuming a hint, a future
live caller must advance with fresh authoritative time/exposure and honor any
rejection by withholding guidance. Rejected `advance`/`reset` deliberately retain
the prior state; calling `current()` after ignoring a rejection would only answer
for that prior context. Elapsed host time alone does not expire a hint.

Native caches retain immutable accepted evidence. `current()` validates only
metadata, scope/exposure, clocks and capture age; it never serializes, copies or
rescans the mask. Python retains its full-scan reference implementation. Advancing to a newer
frame makes an old cached map unusable even if no newer map exists. Expiration
does not manufacture a newer source timestamp. All three implementations use the same single-owner rules. These caches are
not thread-safe camera mailboxes or mobile scheduling implementations. A future
producer must schedule updates on the owning queue and prove bounded/nonblocking
behavior before live integration; these tests make no such latency claim.

## Reproducible synthetic checks

`synthetic-cases.json` contains a baseline policy/context/hint and fault cases.
Each case independently clones those baselines, then applies `hintMutations` or
`contextMutations` in order. A mutation contains a `path` array plus either a
replacement `value` or `remove: true`. `missingHint` substitutes a null hint.
`expectedReason` specifies the qualifier result. The parity runner expands this format and executes the actual Swift/Kotlin
cores. `native-cases.json` adds long-decimal/Unicode/type faults, twelve cache
sequences, clock arithmetic and invalid policies. `selector-cases.json` exercises
actual native selection, existing eligibility gates and stateful challenger dwell.

Run from the repository root:

```sh
python -m unittest discover -s tests/lanes -p 'test_*semantic_hint*.py' -v
python scripts/lanes/compare_semantic_hint_platforms.py --output /absolute/new/qualifier-report
python scripts/lanes/compare_semantic_hint_platforms.py --typed --output /absolute/new/typed-report
python scripts/lanes/compare_semantic_selector_platforms.py --output /absolute/new/selector-report
```

The Python checks additionally inject NaN/infinity (not valid JSON), exercise
cache ordering and owner resets, and verify unchanged baseline references.
Optional `jsonschema` validates structural examples when installed; executable
fault qualification does not depend on it. These tests establish prototype
determinism and failure handling, not real-road accuracy, motion alignment,
mobile inference availability, memory/latency targets or release readiness.

## Native execution and private real-mask envelopes

The host runners require `swiftc`, `kotlinc`, `java`, and the existing Android
`kotlinx-serialization-{core,json}-jvm` 1.7.3 jars. They discover Gradle's cache or
accept `--kotlin-classpath`; they do not download dependencies. Output includes
source hashes and native results. Output directories must be new.

`compare_semantic_hint_platforms.py --vectors /absolute/vectors.json --output
/absolute/new/report` also accepts prepared envelopes, allowing real model masks
to pass through both cores without a camera adapter. Its JSON has a frozen
`policy`, `qualificationCases` (`id`, `context`, `hint`, optional
`expectedReason`), and optional `cacheSequences`, `clockCases`, `policyCases`.
A cache sequence provides initial `context` and `operations` with `op` equal to
`offer`, `advance`, `current` or `reset`; include `hint` or `context` as needed.
The default runner is the executable example of the complete prepared format.
Keep real envelopes, source identities, masks and reports outside Git.

The runner checks all reasons, ages, exposure/scope/model/geometry identities,
validity and exact mask contents against both native implementations and the
Python reference. Mask fingerprints are SHA-256 over each row-major score's
big-endian IEEE-754 binary64 bytes, followed by one `0`/`1` byte per validity
cell. This checks imported evidence bit-for-bit without filling reports with
large probability arrays. Actual source masks do not make declared geometry or
synthetic replay timing into measured calibration/synchronization evidence.

The native selector runner proves a bounded input can change initial ranking,
while malformed arrays reproduce baseline output, all tested eligibility gates
remain effective and the existing challenger margin/dwell still applies. Its
fixtures supply synthetic maturity snapshots: this verifies selector behavior,
not the production detector/tracker or real-road benefit.

## Host qualification/cache cost

`benchmark_semantic_hint_platforms.py --vectors /absolute/vectors.json --output
/absolute/new/timing-report` compiles separate Swift/Kotlin timing harnesses
against the unchanged cores. It uses expected-qualified masks only, with three
warmups and twelve measured repetitions per mask by default. `--warmups` and
`--repeats` are bounded explicit overrides.

External file read and whole-document parse are separately reported. The API
samples measure standalone qualification, owner-cache construction, a fresh
accepted offer and cached current revalidation. Core-internal ownership and initial mask validation remain part of those timings.
The native accepted-evidence cache revalidates metadata without scanning masks.
Use `--typed` for native buffers: JSON-to-array materialization is then timed
separately per mask. The unchanged owner context is intentionally held fixed for
the benchmark; this is not a live capture-clock or source-arrival simulation.
The report contains every sample plus median, nearest-rank p95, minimum, maximum
and mean for each mask and aggregate. Swift autorelease-pool draining belongs
to the full benchmark-cycle measurement; Kotlin retains ordinary JVM garbage
collection. The cycle performs multiple independent operations and is not a
proposed production schedule.

These JSON-facing cores establish functional semantics. Their host timings must
not be used to claim a mobile guidance budget or suitable frame-path latency.
The typed buffer adapter now has its own parity/ownership checks and host timing
control. A real tensor producer, fresh owner clock supply, bounded consumer path
and actual minimum-device measurements remain separate implementation and
acceptance work.
