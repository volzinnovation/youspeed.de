# Offline semantic-hint qualification prototype

This is preparatory work for issues #21 and #23. It is **not an app input format
or a completed Swift/Kotlin integration**. #21 still needs a useful opportunity
result; #23/#24 need real model outputs, platform parity and device qualification.
No detector, tracker, display selection, scheduling, defaults or protected
speed-reference behavior changes here.

The implementation is `scripts/lanes/qualify_semantic_hints.py`. The adjacent
`contract.schema.json` describes three independent documents: `hint`, `context`
and `policy`. The executable qualifier enforces additional cross-field rules.
Schema validation alone does not establish qualified evidence. Unknown fields
are rejected to avoid silently interpreting a newer contract as this prototype.

## Caller-owned context and immutable policy

The caller supplies the current frame's session/camera/calibration identity,
exposure, full-scene image transform and current clock reading. The hint must
match these exactly. Model ID, pinned experiment revision, mask dimensions and
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
currently uses epoch seconds. Mapping actual mobile clocks, preserving the
original exposure timing and proving synchronization remain unimplemented.
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
identity, or geometry. This is an adapter property tested on synthetic objects;
it does not establish byte-identical behavior of either mobile pipeline. No
ranking policy or score adjustment is implemented, even for qualified hints.

## Source-time cache behavior

`HintCache(policy, context)` starts from caller-owned context. `advance(context)`
only accepts non-regressing exposures and current-clock readings within the
same scope, geometry and clock identities. Conflicting frame/timestamp pairs
are rejected without state changes. Only explicit `reset_scope(context)` by the
owner can replace that context and clear cached evidence. Arriving results have
no reset/advance capability; wrong-scope hints cannot invalidate newer evidence.

`offer(hint)` accepts at most one qualified result per source exposure. Duplicate
results cannot replace its scores, and old arrivals cannot overwrite a newer
source timestamp. Invalid arrivals leave the cache intact. `current()` always
requalifies against the current exposure and capture age. Advancing to a newer
frame makes an old cached map unusable even if no newer map exists. Expiration
does not manufacture a newer source timestamp. This is a single-owner offline
cache, not a thread-safe camera mailbox or a mobile scheduling implementation.

## Reproducible synthetic checks

`synthetic-cases.json` contains a baseline policy/context/hint and fault cases.
Each case independently clones those baselines, then applies `hintMutations` or
`contextMutations` in order. A mutation contains a `path` array plus either a
replacement `value` or `remove: true`. `missingHint` substitutes a null hint.
`expectedReason` specifies the qualifier result. This format is intended for
future shared Swift/Kotlin fixtures; those implementations do not yet exist.

Run from the repository root:

```sh
python -m unittest discover -s tests/lanes -p test_qualify_semantic_hints.py -v
```

The Python checks additionally inject NaN/infinity (not valid JSON), exercise
cache ordering and owner resets, and verify unchanged baseline references.
Optional `jsonschema` validates structural examples when installed; executable
fault qualification does not depend on it. These tests establish prototype
determinism and failure handling, not real-road accuracy, motion alignment,
mobile inference availability, memory/latency targets or release readiness.
