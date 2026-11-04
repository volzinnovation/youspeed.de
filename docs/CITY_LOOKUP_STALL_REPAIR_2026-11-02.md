# City lookup stall diagnosis and repair — 2 November 2026

The attached iPhone's stalled map updates are consistent with an expensive
city-name fallback repeatedly finishing after a newer GPS fix has superseded
it. The repair is installed on the attached iPhone as **1.5, build 10083**, with the
equivalent Android query change implemented and tested. All selected native
regressions and full-map acceptance checks passed. The unlocked normal app also passed a stationary live-publication check.
The owner directly confirmed the visible current limit and resolved city/street.
Automated screen capture remained unavailable.

All times below use Europe/Berlin, **CET (UTC+1)**. Raw device logs, exact drive
coordinates, preferences and app data remain outside Git.

## Observed behavior and attribution

QuickTime's attached-iPhone preview showed a current GPS position and zero
speed, but an unknown place and no displayed limit. Device inventory identifies
the installed app as **1.5 build 10081**, bundle identifier
`de.youspeed.SpeedConsumer.TestHost`. Despite its historical suffix, this is the
driver's actual app and data container; it must not be used for destructive
test fixtures.

The last retained published lookup is at **09:52:43.918**, for Birkenfeld
(Enzkreis), with a 13.14 ms query. The retained drive contains no published
Pforzheim result. Live system logging continued to show GPS callbacks during
inspection. Earlier publication gaps occur around the Neuenbürg/Birkenfeld
portion of the drive, but the exact earlier incident and its in-flight SQL
cannot be independently reconstructed from published-result logs.

A CPU-resource report covers **09:59:09–10:01:18**. It reports 90 seconds of CPU
over approximately 129 seconds and **Action taken: none**. Twenty-one of its
24 samples descend into SQLite. The lower native stack is consistent with
packed-map reads and decompression, but no matching executable or dSYM was
available to symbolicate it. This report supports CPU-intensive database work;
it does not establish a crash, watchdog termination or lock cycle.

## Failure mechanism

The existing city resolver skips the areas fallback only when the dedicated
polygon result reaches its maximum score of 53: a named administrative polygon
plus a separate district name. Pforzheim's administrative-level-6 city and
district have the same name. Display formatting correctly suppresses that
duplicate district, leaving a score of 52, so the areas fallback still runs.

The old fallback combines point-overlap and nearby-place searches with an
`OR` across the RTree and the `areas` table. It reads area records throughout
the nearby window before rejecting unrelated landuse records. On a compressed
regional map, those reads repeatedly decompress packed blocks.

The exact production SELECT was reproduced through the production packed VFS
using the active Baden-Württemberg map. At the inspected location, the query
alone took approximately **12.30 seconds with native `-O0`** and **2.03 seconds
with native `-O3`** on the Mac. These are host measurements, excluding Swift
geometry decoding and the remaining matcher, not iPhone acceptance timings.
The project previously used native `-O0` for Debug builds while already
optimizing device Swift. Exact compiler flags for the installed executable
were not retained, so the build configuration is an identified amplifier,
not independently proven installed-binary provenance.

Every new submission invalidates the running token in
[`LatestPendingLookupWorker.swift`](../iphone/SpeedConsumerApp/LatestPendingLookupWorker.swift).
The controller publishes only a current token and the newest fix. A city query
that repeatedly exceeds the incoming fix interval can therefore consume CPU
while publishing no new road, place or limit. The observed symptoms and source
reproduction strongly support this mechanism; accepted-result logs do not
identify the exact historical SQL that was running at the reported boundary.

## Repair and parity

The Swift and Kotlin fallbacks now select candidate IDs before loading area
records or geometry:

1. Query point-overlap IDs from the RTree.
2. Query nearby spatial IDs separately and intersect them with IDs from the
   place classification search, using the existing covering place index.
3. Deduplicate IDs, retain point overlaps before nearby-only places, and apply
   the existing 512-candidate bound. Row ID breaks ties deterministically.
4. Load only the selected area rows. City geometry is loaded only for supported
   administrative levels 6, 8 and 9. Android also retains geometry needed by
   its shared residential-context path.

`LIMIT -1 OFFSET 0` deliberately keeps the nearby spatial subquery from being
flattened into thousands of random RTree row-ID probes. The RTree comparisons
retain their existing bounds. Administrative geometry admission casts the raw
level numerically; the existing native parser still decides whether the level
is supported. This preserves closed-ring checks for accepted legacy values
such as `06`.

Point-overlap priority matters in crowded windows: an order based solely on
row ID could let more than 512 nearby places evict the containing administrative
polygon. The old query had no explicit ordering. The repaired query makes the
bounded selection deterministic while reserving it first for point overlaps.
Place ranking, district completion, independent-city name formatting and
closed-ring containment remain in their existing resolvers.

The iPhone application target now compiles native sources with **`-O2`**,
retaining debug information. The map itself is unchanged. The active packed
context identity used for reproduction is:

`66bff716fa57500f482f7a8707fb1fcfa059beadcecab260b34934b7576666e5`

Production sources:

- [`V3SpeedLimitService.swift`](../iphone/SpeedConsumerApp/V3SpeedLimitService.swift)
- [`V3SpeedLimitLookup.kt`](../android/app/src/main/java/de/youspeed/android/alpha/V3SpeedLimitLookup.kt)
- [`project.yml`](../iphone/project.yml) and its generated Xcode project

No shared speed-limit-reference policy, approval lock, threshold or interpreter
semantics changes are part of this repair. No map replacement or schema change
is required.

## Validation

The new
[`CityLookupPublicationRegressionTests.swift`](../iphone/SpeedConsumerTests/CityLookupPublicationRegressionTests.swift)
covers independent-city naming, incomplete district completion, irrelevant
geometry, place selection, deduplication and crowded bounded selection.
Opt-in full-region tests exercise cold/warm queries and publication while
one-hertz fixes continue, using the actual packed map in a separate test app.

| Check | Status |
| --- | --- |
| Selected Swift semantic and packed-runtime regressions | 35 passed, zero failures/skips, on the physical iPhone |
| Full-region iPhone query-budget acceptance | 20 cold/warm samples passed; maximum 200.71 ms |
| Full-region iPhone one-hertz publication acceptance | All 10 submitted fixes published |
| Android semantic and query-plan parity regressions | 30 city/settlement instrumented tests, one full-map test, and 27 JVM tests passed |
| New iPhone build and installed version verification | Apple signature verified; installed 1.5 build 10083 |
| Post-install data-preservation verification | 119 persistent files retained at their original sizes; seven durable core files hash-identical |
| Normal-app live GPS and dashboard publication | 93 accepted current results; owner confirmed the visible current 50 km/h limit and resolved city/street |

Full-map iPhone wall times on the actual iPhone 14 Pro:

| Case | Cold | Warm range |
| --- | ---: | ---: |
| Pforzheim inspected area | 200.71 ms | 125.64–126.07 ms |
| Pforzheim centre road | 187.23 ms | 142.86–143.33 ms |
| Neuenbürg centre | 65.46 ms | 2.93–3.05 ms |
| Neuenbürg approach | 59.12 ms | 0.73–0.84 ms |
| Birkenfeld last published area | 61.57 ms | 1.15–1.28 ms |

The first physical selection met the timing budget but failed a road-presence
assertion for an off-road centre coordinate. The nearest mapped secondary-road
point replaced that sample; the complete final 35-test selection then passed.

Android acceptance ran in a separate API 36 emulator installation. All nine
full matcher lookups resolved the expected city. Maximum query time was
322.24 ms; Pforzheim warm queries were 250.68–254.87 ms, and Neuenbürg warm
queries were 10.18–10.44 ms. The actual packed file hash was verified. The
normal Android installation was not updated. Five new semantic cases cover
independent-city naming, geometry admission, candidate deduplication, crowded
selection, and zero-padded legacy administrative levels. The framework SQLite
lacks RTree on that emulator, so small fixtures exercise the production native
SQL adapter through an internal database injection; full-map acceptance uses
its real RTree and packed VFS. The temporary test emulator was stopped.

Full-region physical tests must run in
`de.youspeed.SpeedConsumer.CityLookupTests`, never the driver's `.TestHost`
container. The normal unit-test runner now uses `.UnitTests`.
[`ConsumerTestHost.swift`](../iphone/SpeedConsumerTests/ConsumerTestHost.swift)
admits these explicit isolated identifiers and rejects the historical
`.TestHost` identifier on a physical phone. Captured incident staging uses the
same separate test-host identifiers.

## Installation and data preservation

The existing `de.youspeed.SpeedConsumer.TestHost` app was updated in place to
**1.5 build 10083**. No uninstall or data clear of the driver's app occurred.
Before the update, its stopped container was copied privately: **187 files,
2,106,864,769 bytes**. The copied trip journal, sign collection and local
observations passed SQLite `quick_check` with their retained WALs.

Before first launch, all **119 persistent files** were present with identical
sizes, including maps, media, preferences and logs. SHA-256 comparisons also
confirmed seven durable core files byte-for-byte: the active map pointer,
preferences, local observations, trip journal plus WAL, and sign collection
plus WAL. SQLite shared-memory caches were excluded from byte comparisons
because the local integrity checks rebuild them. No map replacement occurred.

The temporary `.CityLookupTests` app created for this task was removed after
acceptance, leaving the updated normal app. Its matching executable and dSYM
are retained privately for future crash-report symbolication. The binary UUID
is `EFBC63AF-CB6B-3162-ACA3-B62225DF8BE4`.

The first launch request was denied while the phone was locked. After the
owner unlocked it, the normal app produced **93 accepted results** from
13:50:40 to 13:57:34 CET, all with a resolved road/place and a current **50 km/h**
bundle limit. Median query time was **157.12 ms**, maximum **335.73 ms**; warm
queries ranged from **128.24 to 169.72 ms**. These records are written after the
current-token/newest-fix publication guards. They demonstrate continuing
publication rather than raw GPS reception alone.

QuickTime's screen preview remained black despite reselecting the screen and
restarting the preview. A separate read-only UI runner compiled and launched,
but iOS timed out enabling automation mode before executing the test method.
The legacy screenshot service was also unavailable. No dashboard assertion
failed; the visual check could not execute. The task-owned UI runner was
removed and the normal app returned to the foreground. Its presentation log
records the current 50 km/h sign as visible again at **13:57:20 CET**; this is
application-state evidence, not observed screen pixels. The owner subsequently confirmed directly on the phone that the current
50 km/h limit and expected city/street were visible. This completes the live
dashboard check, with visual confirmation attributed to the owner.

This was a stationary live check, including a brief background interval while
the unsuccessful UI runner started. It does not constitute a repeated road
drive through either city entry. No preferences, recording controls or
location inputs were changed during the live check.

## Evidence

Private source copies, device inventories, crash/resource reports, live syslog,
the exact fallback harness, host timings, diagnosis and SHA-256 manifest are at
`/private/tmp/youspeed-iphone-20261102/`. Validation logs, the full backup, test results, retained symbols and installation
receipts are at `/private/tmp/youspeed-city-fix-20261102/`. The summarized
[validation receipt](CITY_LOOKUP_STALL_REPAIR_2026-11-02.validation.json) contains
source and log hashes. Raw private device evidence is not committed.
