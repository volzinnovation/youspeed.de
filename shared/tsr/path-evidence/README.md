# Experimental visual path evidence

`synthetic-v1.json` is a versioned engineering fixture. It contains idealized
image strokes, exact pinhole observations, known past vehicle poses and supplied
road polygons. It is not a field corpus, an automatic road-assignment benchmark,
a mount calibration certificate or evidence of phone timing.

Run both production implementations from the repository root:

```sh
python3 scripts/lanes/replay_path.py --output /tmp/youspeed-path-parity.json
```

The runner compiles the actual Swift and Kotlin boundary and path-evidence
sources. It renders identical grayscale buffers, compares every boundary point,
confidence, cue, corridor index, operation count, classification, abstention
reason, 3D position, uncertainty, projection and exposure-aligned pose with a
numeric tolerance of `1e-9`, then checks the independently supplied expected
controls. It writes all executable, jar and pixel artifacts to a temporary
directory. Optional reports contain input and source hashes. The existing cached
Android JSON jars are used; nothing is downloaded.

The controls include straight/curved/multiple boundaries, portrait geometry,
paint gaps, occlusion, clutter and deterministic work-budget exhaustion. Sign
cases cover left/right roadside signs, overhead signs, actual turning poses,
separated roads, ambiguity, no supported geometry, calibration availability,
explicit lateral camera offsets, stale/future/repeated fixes, weak heading,
parallel bearings, bounded input counts and short causal exposure alignment.

## Fixture schema v1

The top-level fields are `schemaVersion: 1`,
`provenance: "synthetic_engineering_only"`, `description`, `boundaryCases`, and
`pathCases`. IDs are unique across both arrays and contain only ASCII letters,
digits, underscores and hyphens. `fixture-v1.schema.json` describes the envelope;
the native types and their validation implement the evidence contract.

Each boundary case has `id`, `width`, `height`, `background`, `strokes` and
`expected`. Stroke `points` are normalized `[x,y]` pairs, `width` is pixels, and
`brightness` is a luminance byte. Optional `noiseSeed` replaces strokes with
deterministic Python PRNG bytes. Optional `maximumOperations` exercises a bounded
detector budget. The runner adds temporary `pixelsPath` values only to its
generated manifest. Expectations can constrain budget exhaustion and minimum or
maximum boundary/corridor counts.

Each path case has `id`, `scope`, `nowSeconds`, `calibration`, `poses`,
`observations`, `corridors` and `expected`. Field names match the production
`RoadPath*` types. Coordinates are local east/north metres, height is up, course
is clockwise from north, intrinsics are normalized to the complete upright
image, and all times in a case share one clock. Pose positions represent the
idealized vehicle centre on a locally planar road. Observations are image
centres of the same elevated physical sign; they are triangulated as 3D rays
and are never directly projected onto the road plane.

Calibration has explicit yaw, pitch, roll, camera height and optional lateral
offset, plus a revision and verification state. The fixture's 1.60 m height and
−0.08 m offset reproduce the owner-supplied test mounting dimensions with exact
synthetic geometry. They do not quantify real mount/road-plane uncertainty.
Forward prediction uses only the latest past pose, lasts at most 0.35 seconds
and grows uncertainty; the original fix time remains in result diagnostics.

Corridors have a bounded polygon, independent support flag, confidence, roadside
margin, and role `current_path`, `other_path` or `unknown`. Explicit role labels
are oracle inputs for decision-wiring tests. The automatic-role case starts with
unknown roles and exercises the causal short-path helper. Adjacent touching lane
corridors are not treated as proven unrelated roads.

All core outputs remain shadow evidence and cannot grant or suppress sign
authority. The shared speed-reference state-machine policy is outside this
contract. Real-road validation must assess incorrect rejections as well as wrong
road admissions, mount uncertainty, hills/banking, actual GNSS quality and
sustained processing cost on the target phone.
