# Revisioned correction overlay prototype — 26 October 2026

The immutable map pack and the writable correction history are different data
structures. A correction must survive a new pack generation without depending
on a pack offset, road-row ordinal, tile ID or nearest-road guess. The executable
C++17 prototype in `shared/runtime-corrections-prototype/` supplies that second
layer for all three storage-backend experiments. It does not change either app
or the approved speed-reference state machine.

## Implemented data model

Each logical correction has a stable string ID and an immutable sequence of
numbered revisions. Writes require the expected current revision; stale edits
fail without changing history. Deletion appends a tombstone. An amendment can
target an OSM way, an OSM node, a government inventory sign or a newly added
local sign with its own stable local ID.

Anchors retain the source namespace, exact signed 64-bit source ID, direction,
optional chainage interval and a caller-provided source-target fingerprint.
Fingerprints must cover relevant geometry, topology and source semantics when
the builder supplies them. The prototype does not substitute its own heuristic
for a missing authoritative fingerprint.

Node records retain E7 coordinates, sign type, all raw source tags,
supplementary text and source way memberships. Each membership contains a way
ID, original node ordinal, bit-exact source chainage double (alongside an optional
millimeter index value) and direction. Membership is stored
separately from the verified directed-road applicability association: being on a
way does not prove which direction a sign faces. A node lookup returns unresolved
until the road association and node passage are proven.

Sign types distinguish generic maximum speed, numeric maximum speed, unlimited,
variable, unknown, end-of-limit and zone events. Numeric values, unlimited,
walking pace and unresolved values are separate limit types. A generic
`traffic_sign=maxspeed` node can remain a useful persisted sign record without an
invented numeric value. Raw `signals`, `variable` and national/default values are
preserved as unresolved when there is no supported interpretation. This module
contains no sign artwork or display code.

## Restrictions and amendments

Rules are an ordered typed decision list. The private prototype AST supports:

- Boolean `all`, `any` and `not`, with correlated unknown facts.
- Local weekday/clock schedules, overnight windows anchored to their start day,
  and annual ranges.
- Context facts such as wetness and qualified holiday facts.
- Vehicle class, lane and gross-weight restrictions.
- Absolute validity intervals, with an exclusive end.
- Explicit unsupported conditions with their exact original text.

`amendLimit()` changes one clause's value while retaining its complete condition
AST, raw source tags, node metadata and anchor. This avoids turning a restricted
30 km/h correction into an unrestricted speed. Advanced edits use a new complete
record revision, so the previous condition and source evidence remain auditable.
`rawTags` are lossless source evidence, while the typed clauses contain the
amended interpretation; exporting a corrected OSM tag string is a separate step.

Evaluation requires qualified clock, direction, vehicle and other context.
Unknown facts are enumerated consistently, bounded to twelve distinct facts.
A concrete result is returned only when all admitted outcomes agree. Different
active corrections for the same target that yield different limits return a
conflict. Unsupported or variable sign values stay unresolved. These are
data-layer results; existing camera/voice/map producer priority, passage policy,
reference lifetime and UI behavior are outside this module.

The existing iPhone implementation was inspected before coding:
`ConsumerModels.swift` admits structurally validated permanent unconditional
runtime corrections and retains typed target provenance;
`ConditionalSpeedRules.swift` uses last-matching-clause semantics, qualified
calendar context and correlated unknowns. The prototype follows those
data-evaluation principles without broadening either app's runtime admission
policy. Its AST is not a replacement implementation of the full
`youspeed-osm-speed-1` compiler or its whole conformance corpus.

## Bundle changes and provenance

Every revision retains its original bundle, current basis bundle, source
revision, author, evidence ID, action and timestamp. A lookup against a different
generation or source-target fingerprint returns `RebaseRequired`.

Automatic rebase succeeds only for one exact source target with unchanged
fingerprint, direction, road association and chainage interval. Missing targets,
changed geometry/semantics and one-to-many splits remain pending review.
`confirmRebase()` records an explicitly reviewed replacement anchor as a new
revision. Original provenance is immutable. An ordinary amendment cannot
silently reassign a correction to a different source ID or fingerprint.

## Persistence and native API

The writable prototype uses a small standalone binary revision journal, rather
than rewriting the immutable road pack. Its `YSPOVR01` format uses fixed little
endian primitives, length-prefixed strings and complete typed records. It does
not serialize compiler-dependent C++ layouts. Decode bounds file size, record
count, string sizes, AST depth and unknown contexts; it validates all revisions
before replacing an existing in-memory overlay. A checksum detects accidental
corruption and is not an authentication mechanism.

`save()` writes a sibling temporary file and renames it over the destination;
`load()` validates and restores the complete history. The current prototype is
single-writer and bounded to 16 MiB and 100,000 revisions. Production adoption
would need platform durability/locking and a history-compaction policy. Source
feature lookup uses an index over stable feature keys, so unrelated corrections
are not scanned for each road lookup.

Native harness entry points have C linkage and require no third-party library:

```cpp
const char* ysp_corrections_selftest_json();
const char* ysp_corrections_persistence_selftest_json(const char* scratchPath);
const char* ysp_corrections_source_node_probe_json(
    const char* sourceNodeJSON, const char* scratchPath);
const char* ysp_corrections_dataset_probe_json(
    int64_t wayID, int64_t nodeID, const char* generation, int iterations);
```

Each returned string has thread-local lifetime until the next same-thread call
to that function. The dataset probe accepts real IDs selected by the benchmark,
but its amendments are explicitly hypothetical and never modify the base map.
It measures overlay lookup separately from backend lookup. The header exposes
the full `Overlay`/`Record` C++ API for actual imported node records.

## Verification

The host executable currently passes **56 of 56** native assertions. They cover
CRUD, stale writers, tombstones, full-history roundtrip, byte-exact serialization,
corruption rejection without partial replacement, exact 64-bit IDs, restriction
preservation on edits, weekday overnight boundaries, validity, vehicle/lane/
weight scopes, unknown facts, node directions and passage, generic/variable/
unlimited nodes, topology membership, local additions, government anchors,
bundle rebasing, split-target review and overlapping amendment conflicts.

The host harness also performs actual disk create/reopen, amendment/reopen and
tombstone/reopen checks, retaining all three revisions. The same disk probe is
available to both device harnesses through the C ABI above. A minimal
unrestricted revision is 288 bytes; the two-revision restricted fixture is
852 bytes. These are correction-journal examples, not full-BW bundle sizes.

```sh
clang++ -std=c++17 -O2 -Wall -Wextra -Wpedantic \
  shared/runtime-corrections-prototype/runtime_corrections.cpp \
  shared/runtime-corrections-prototype/tests/main.cpp \
  -o /private/tmp/ysp-corrections-test
/private/tmp/ysp-corrections-test /private/tmp/ysp-overlay-test.bin
```

The complete 56-assertion snapshot and disk mutation/reopen checks also pass
AddressSanitizer and UndefinedBehaviorSanitizer. Device measurements belong in
the main packed/SQLite/GeoDesk benchmark report, not in these host smoke results.

## Source-bound restricted amendment

The source-node probe accepts the actual full JSON returned by
`storage_node_json()` for BW node **2532969814**. It validates the source ID,
`maxspeed=50`, `maxspeed:hgv:conditional=30 @ (weight>7.5)`, and the explicit
membership in way **159830790**, source vertex ordinal **8**, original chainage
**261.9489296929296 m**. All supplied source tags and memberships are imported;
JSON IDs never pass through floating point. Malformed/duplicate-key/deep JSON
and a different source case fail explicitly.

The probe amends only the restricted clause from 30 to 25, saves and reopens the
journal, and verifies car/light-HGV baseline 50, heavy-HGV 25, unknown weight
unresolved, and tombstone restoration of baseline 50 after another reopen.
Because gross weight is represented in integral kilograms, the strict source
predicate `weight>7.5` tonnes is compiled to `>=7501 kg`; 7500 kg stays at 50.
The source direction and membership remain unverified on import. Evaluation
then uses a separately labelled, hypothetical forward association and confirmed
passage solely to test data composition. This supplies no new legal authority
or production reference-policy behavior.

The actual packed full-BW source record passes **18 of 18** additional
assertions, including bit-exact source membership, restriction preservation,
disk reopen and tombstone checks. Input-record FNV-1a is
`e71e7bbba1cc2d29` for the 420-byte native source JSON; the CLI fixture with its
trailing newline hashes to `84f962d3edf0b279`. FNV identifies the probe input;
it is not a security signature. The source API has the same thread-local return
lifetime as the other correction functions. Callers retain the source JSON
until the probe returns and use a separate scratch-journal path.
