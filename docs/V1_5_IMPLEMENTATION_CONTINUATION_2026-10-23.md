# v1.5 implementation continuation — 23 October 2026

Working-tree implementation on `codex/youspeed-v1.5-mobidata-bw`. At this
implementation checkpoint no commit, push, merge, device deployment, store
publication or live-service activation had been performed. Earlier unrelated
working-tree changes were preserved. The owner subsequently authorized
[build 10060 installation on both phones](V1_5_DEVICE_INSTALL_10060_2026-10-23.md);
that later validation is recorded separately.

The owner requested the full initial Fahrtenbuch, existing native button style
with Fahrten second from right immediately left of Settings, preview signs,
v1.5 proposals and better inner/outer-city detection. Representation/storage
optimization is explicitly deferred. The implementation retains SQLite REAL
metre/second counters and the existing road storage layout.

## Delivered application behavior

### Fahrtenbuch on iPhone and Android

Both dashboards use their existing circular/pill control appearance. Fahrten
is immediately before Settings in the parked button row. Existing moving and
recorder-finalization gates apply. Settings and the map-bootstrap state also
provide history access. A compact iPhone SE landscape regression found that
default spacer minimums consumed the intended margins. The row now lets gaps
contract while retaining its existing 40/44 pt buttons and 8 pt inset. Android
retains its 48 dp buttons and verifies all seven at 360 dp with larger text.

The private journal starts independently of map/model/network readiness using
the existing authorized location intake. GPS-only driving is supported. It
stores original GPS/TSR evidence and explicit quality/coverage gaps, with broad
camera discoveries before actionable-speed filtering and separately identified
inventory evidence. Contribution consent, diagnostic logging, camera and public
uploads remain independent. Opting out retains minimal lifetime counters and
never stores or later backfills a private route.

Recording handles duplicate/out-of-order fixes, invalid/nonfinite evidence,
bounded writer loss, stop intent and late-sign finalization, a 300-second
foreground recovery window, abandoned process state and late media callbacks.
Network-only Android fixes remain original log evidence without advancing GNSS
distance or bridging a measurement gap. Both clients use the versioned distance
and clock gates in [`shared/trip-journal/`](../shared/trip-journal/README.md).

Native history includes date/vehicle/sign/media/gap/search filters, retained-trip
totals and independent lifetime distance/usage with origin dates. Custom date
bounds select complete trips by their start time using inclusive local dates;
7/30/365-day presets include today and the preceding 6/29/364 days. Period
charts aggregate saved trip distance and observed foreground trip time; they do
not invent a daily allocation of usage retained only in lifetime counters.
Optional odometer entries preserve entered km/mi units and are write-once.
Saved facts have no editing, split or merge flow.

Trip detail has geographic route context, gap styling, linked route/event/media
selection, timeline, replay, speed chart, original GPS/TSR logs and sign
discoveries. iPhone uses MapKit; Android reads road names/geometry from its
installed offline road bundle and retains a neutral geographic grid when no
bundle is available. Missing map context never changes recorded coordinates or
distance. Existing media galleries support a trip filter and grouped camera
sessions.

Exports include GPX, GeoJSON, GPS/TSR CSV/JSON/NDJSON, discovery/media indices,
PDF overview, counters, ZIP and SHA-256 file manifests. Each archive includes
the portable [`journal.json` contract](../shared/trip-journal/export-v1.schema.json).
Masked sharing removes endpoint/home-zone evidence consistently, excludes raw
unstructured logs/videos/remote links, omits photos of unknown location and
re-encodes selected safe photos without GPS metadata. Originals remain intact.
Password backups use AES-256-GCM/PBKDF2 and replace the journal/counter epoch
transactionally; restored samples never add imported distance or usage again.
Trip deletion preserves lifetime counters; reset-all starts a new epoch.
Eligible local-media deletion respects active recording and upload ownership.

Recorder sidecars retain UTC/monotonic origin, segment duration and timing
quality. Native callback anchors are **estimated, with up to 2 s tolerance**.
Uncertain/out-of-interval seek actions are refused. Exact frame/presentation
alignment within 250 ms is a separate contract and is not claimed for callback
anchors or old files without clock metadata.

### Preview signs, locality and source preference

The adaptive preview uses a 30-second observed-speed horizon with the existing
300 m minimum. It follows certified source-node topology across ordinary way
splits, stops at ambiguous junctions/restrictions, uses along-road distance and
expires on passage, departure, source/context changes or stale GPS. A timer
clears it without requiring another fix. Preview artwork uses the shared asset
set; numeric limits retain the explicit schematic exception.

The source preference remains **own correction > accepted camera evidence >
applicable government inventory > OSM**. MobiData inventory and its lookahead
data require the BW region/country/source identity. Copying those tables into a
different region does not enable them there; ordinary OSM lookup still works.

Accepted physical DE:310 and DE:311 passages set inner-city and outer-city
context respectively. An entry does not toggle back to rural if a duplicate
entry is seen. Accepted multiple crossings in one update are consumed in order.
Camera town context overrides ordinary mapped/inventory context; a later
independently accepted physical boundary starts the next locality context.
Residential roads establish an urban fallback while explicit incorporated OSM
urban/rural evidence and physical town boundaries retain their meaning. A
synthetic residential fallback does not upgrade inherited symbolic tags that
the existing settlement-v1 contract suppresses for missing/weak context; it uses
the derived urban road default. Conflicting settlement evidence stays unknown.
Explicit numeric restrictions are preserved independently of the locality used
for defaults and penalty classes. Ordinary speed-end signs do not act as town
exits. No protected speed-reference policy bytes or interpreter semantics were
changed.

### Conditional speed rules

`scripts/map/conditional_speed_rules.py` is part of core full v3 generation.
It preserves source tags and compiler/source provenance and writes declarative
ordered clauses/condition trees. Legal rules, metadata, direction, mode, lanes,
variable signals, unsupported syntax and malformed source remain distinct.
Explanatory `reason`, `source`, `type`, `note`, check-date and advisory metadata
cannot mask a legal motorcar speed. The 191 audited BW conditional patterns are
retained; unsupported meanings remain unresolved instead of silently flattening
to the numeric prefix or road-class default.

Swift and Kotlin evaluate numeric and explicit `none` results, clock/weekday/
annual clauses and logical combinations. Unknown wetness, public/school
holidays, unsupported vehicle/lane context and electronic `signals` remain
unknown when relevant. Native controllers re-evaluate clock boundaries without
renewing camera evidence. Known corrupt capabilities fail closed. Legacy BW
conditional/electronic markers cannot silently fall back to a scalar/default.
The capability requires app 1.5 and **full delivery**; heuristic and exact delta
generation reject it. Shared conformance has 24 native vectors.

Conditional OCR has separate parsing, complete-assembly verification and
applicability layers, including distinct-frame support, scope, original evidence
age/distance and source evaluation prohibitions. A parser match is not authority.
Matching-parent attempted OCR, including unread/failed results, withdraws or
blocks its plain numeric camera claim without cancelling an own correction or
unrelated camera claim. Independent map evidence can remain available.

Known attached/unassigned restrictions also latch that exact parent while OCR
is deferred by heat, crop size or other unavailable-read conditions. A later
bare frame cannot remove the block. Unrelated ordinary bare candidates retain
their existing admission path before an unverified OCR attempt.

**OCR enablement limit:** existing collection DTOs do not prove complete plate
assembly, exact plate association or reviewed training quality. They therefore
cannot automatically activate a parsed conditional rule. Full live assembly
verification, positive deferred/tiny-crop completeness proof, proven same-rule duplicate
bundle quarantine and measured new-model recall remain acceptance/implementation
gates; no fabricated verifier or new classifier training is claimed. The pinned
classifier still lacks exact outputs for some inventory signs, including town
signs. Inventory artwork does not create a camera model capability.

### Optional reported roadworks

Both apps have the same initially-off preference, explicit network disclosure,
bounded dedicated HTTPS transport, one in-flight request, cancellation generation,
five-minute refresh with jitter/retry and validated current/previous disk caches.
They use region/snapshot downloads and local proximity; requests contain no GPS
or installation identity. Clear-cache wins over earlier in-flight parse/write
work. Offline and app-update-required states survive local relevance evaluation.

The independent advisory uses actual line/Point distance, resolved intervals,
trusted source age, current GPS and 500/750 m admission/retention hysteresis.
It presents a neutral reported-nearby card after two eligible fixes, including
closure/works type, road, rounded distance, source age and delayed/offline state.
Parked rows retain full German source text, dates, operator/schedule status,
direction uncertainty and complete source ID. Records are not destructively
grouped. It never supplies speed references, warnings, camera sightings or
capture triggers.

The sibling backend implementation is in
[`Woladen.de-analytics`](../../Woladen.de-analytics/docs/youspeed/ROADWORKS_IMPLEMENTATION.md):
bounded conditional fetching, hashed raw evidence, exact GeoJSON/DATEX joins,
Berlin/DST schedule compilation, quarantine, immutable snapshots, SQLite/R-tree,
atomic current/previous generation, withdrawal lineage, rollback, retention,
public cached API and an isolated opt-in Compose tools profile. Source and
reverse-proxy configuration are prepared; the server feature remains disabled
and no recurring scheduler was installed.

A read-only sample on 23 October contained 1,050 source IDs and 875 accepted
evaluation-window features. Four suspect Points were quarantined. All sampled
schedules remained unknown because publisher representation clocks differed by
more than 15 minutes. These reports cannot be presented as confirmed active
roadworks. Seven-day cadence, physical direction and operational pilot targets
remain unmeasured.

## Separate local full BW bundle

The new draft is
[`2026-10-23-v1.5-journal-conditional`](../mapdata/bundles/v3/baden-wuerttemberg/2026-10-23-v1.5-journal-conditional/baden-wuerttemberg_manifest.json).
It extends a copy of the existing lookahead DB; the old bundle was not modified.
It contains the existing 1,085,790 roads, directed sign inventory/town events,
source-node lookahead topology, shared review artwork and the new conditional
tables. This is local packaging, not a release, upload or device installation.

The source OSM PBF remains the recorded **13 September** extract (SHA-256
`1856f4ac7c18435e17d74c7ba24a7b21b3a1231e60449851890dc0109638ded3`);
an October package does not make those source tags newer. MobiData is the
17 October snapshot `cb4c89d3d2b18a06a1d5956b94865310929ff455d7a33005053bccaac66b79c3`.
The conditional build has 9,672 interpreted way sets, 15,797 rule rows and
28,245 interpretation records, including 1,230 unsupported/review outcomes.
All 589,661 selected raw speed/provenance tags remain in the source table.

The compressed DB is 989,583,784 bytes, SHA-256
`b2c451a245172879f9ab3e90376b590eeaa1c789eee99ce47200eba820643dcb`;
the uncompressed DB is 3,185,627,136 bytes, SHA-256
`e973d279de2803b13037b9e87132be72f28a22d8f9c9bbef79d73093772b1849`.
Streaming decompression/hash checks, coverage/rules hashes, compiler hash and
SQLite `quick_check` passed. The
[bundle receipt](../output/fahrtenbuch-v15-2026-10-23/bundle/validation.json)
records the manifest, provenance and table counts. No representation optimization
was introduced.

## Verification and remaining release gates

The final machine-readable
[continuation receipt](V1_5_IMPLEMENTATION_CONTINUATION_2026-10-23.validation.json)
records the final native/build results, source hashes and limitations:

| Check | Final result |
| --- | --- |
| iPhone selected native simulator suite | **107 passed, 1 skipped, 0 failures** out of 108; physical-only installed-bundle measurement skipped |
| iPhone compact button-row UI | **Passed** in portrait and both landscape mounts; circles retain size, margins and order |
| Android complete JVM suite | **845 passed, 1 skipped, 0 failures** out of 846; unavailable archived dashcam-crop fixture skipped |
| Android selected API 36 emulator suite | **52 passed, 1 skipped, 0 failures** out of 53; optional installed full-BW probe skipped |
| Android button-row layout | All seven controls unclipped/nonoverlapping in 12 mount/recorder/font states and 360 dp portrait at 1.5× font |
| Backend | **35 passed**; Compose model and sampled OpenAPI outputs validate |

The expanded iPhone suite includes native journal/privacy/recovery, complete
preview fixtures and actual legacy full-BW reader/controller probes, inventory
runtime, conditional rules/OCR, roadworks, camera town locality and inherited
residential-context regressions. The final Android APK pair and all 531 hashed
source/test inputs match its receipt. iPhone's final source/contract snapshot
contains 152 files. No physical-device test was substituted for a simulator run.

An earlier optional full-BW reader probe hit the unchanged **25 ms** work budget
and correctly withheld the preview. Its original failed-run log is retained in
[the diagnostic](../output/fahrtenbuch-v15-2026-10-23/iphone-cold-budget-diagnostic.log).
That fixture now verifies empty output on exhaustion and exact target recovery
on one subsequent normal lookup, retaining warm misses in its timing samples.
The final 21-case run had zero budget misses, 42 warm samples, p95 6.02 ms and
maximum 7.07 ms on this simulator host. This is functional reader-recovery
evidence, not a guarantee every GPS fix meets budget, a timed GPS recovery test,
or a performance-improvement claim. No runtime limit or data representation was
relaxed to obtain the result.

Other verification: 35 backend tests, Compose-model validation, sampled API
responses against OpenAPI, eight conditional compiler tests, 11 context-delta
tests, ten bundle/delta tests, 14 spatial pipeline passes with two dependency
skips, 16 country-generation tests and two shared pictogram-set checks. The protected-policy checker passed all
39 scenarios/171 steps, all 16 transitions and five states, with unchanged
artifact hashes and both app pins. The shared lookup also builds in SpeedDBBench.
Native exported envelopes validate against the same JSON schema.

Native test builds explicitly use app compatibility version 1.5, as in the
existing v1.5 test-bundle workflow. Release defaults and store metadata were
not advanced by this implementation continuation.

Inspected simulator/emulator screenshots:
[iPhone history](../output/fahrtenbuch-v15-2026-10-23/iphone-history-de.png),
[iPhone route/detail](../output/fahrtenbuch-v15-2026-10-23/iphone-detail-de.png),
[Android history](../output/fahrtenbuch-v15-2026-10-23/android/history.png),
[Android route/detail](../output/fahrtenbuch-v15-2026-10-23/android/detail.png).
These use synthetic fixtures, not a real recorded drive.
The native button row is also captured in
[compact portrait](../output/fahrtenbuch-v15-2026-10-23/iphone-action-row-portrait.png),
[landscape, camera lower right](../output/fahrtenbuch-v15-2026-10-23/iphone-action-row-landscape_camera_lower_right.png)
and [landscape, camera upper left](../output/fahrtenbuch-v15-2026-10-23/iphone-action-row-landscape_camera_upper_left.png),
with corresponding measured-bounds text and a retained UI-test log.

No physical device installation or driving was requested in this continuation.
Real-camera capture/precise media alignment, sustained storage-full/reboot/load,
large-history accessibility/performance and source-cadence acceptance remain
unverified. Continuous background tracking, cloud synchronization, fleet/OBD/tax
workflows and richer route comparison/photo stories remain outside the specified
initial Fahrtenbuch release. Formal German tax/§31a compliance is not promised.
