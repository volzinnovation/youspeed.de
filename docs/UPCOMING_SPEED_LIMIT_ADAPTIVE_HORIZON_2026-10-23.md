# Upcoming speed limits: 30-second preview window

Date: 23 October 2026. Applies equally to iPhone and Android.

The product owner confirmed seeing previews in the first drives, but the notice
was too short. This update replaces the original 300 m ceiling with a search
window based on the observed driving speed:

```text
lookahead_distance_m = max(300, observed_speed_kmh / 3.6 * 30)
```

At 50 km/h this is 416.67 m; at 80 km/h, 666.67 m; at 100 km/h, 833.33 m;
and at 130 km/h, 1,083.33 m. The distance caption still rounds upward to 10 m.
The minimum 300 m gives 36 seconds at 30 km/h. Missing, negative or nonfinite
speed, including arithmetic overflow, falls back to 300 m. There is no fixed
distance ceiling.

Both clients use the driving speed already supplied to the map lookup. Each
lookup snapshot retains its calculated window, so the physical-event query and
final preview selection apply the same unrounded threshold. Older snapshots
without the field default to 300 m. A new accepted fix recalculates the window.
Observed speed affects distance; the upcoming numeric value still compares
against the final effective main limit. Existing passage memory, relation scope,
direction, sign applicability, current-limit authority and three-second expiry
continue to apply. Existing diagnostics now include the queried horizon.
Slowing can shrink the window enough to hide a target until it enters the
recalculated range; this does not erase passage memory.

## Bundle compatibility and work bounds

The installed BW bundle's `upcoming_path.version=1` contains source segments and
successor decisions independently of search distance. No SQLite schema change,
new bundle, larger download or topology regeneration is needed for this update.
The 32-segment work limit, 25 ms cooperative deadline and bounded event reads
remain in place. An unfinished path never establishes a target beyond its
verified portion.

Read-only measurements across 51,389 numeric origin-rule cases found the
following topology windows. These are upper bounds on availability, not live
preview success rates: intervening physical events, main-limit comparison,
matching and freshness may suppress more candidates.

| Required approach | Origins with sufficient verified topology |
| --- | ---: |
| 300 m | 5,292 |
| 500 m | 3,142 |
| 833.33 m | 1,849 |
| 1,083.33 m | 1,404 |
| 1,300 m | 1,145 |
| 2,500 m | 340 |

The longest inspected chain through 2,500 m required 16 segments, below the
existing 32-segment cap. Extending that cap would not improve this measured BW
coverage. The median available topology window, including certified
continuations, was only 28.83 m. This calculation excludes 717 zero-length
origin cases needing a child-way offer and 271 cases without an allowed
approach/entry segment; native tests separately cover endpoint ownership.

The evidence and reproducible read-only measurement are in
[`output/upcoming-speed-limit-adaptive-horizon-2026-10-23/`](../output/upcoming-speed-limit-adaptive-horizon-2026-10-23/README.md).
The source database and packaged bundle remain unchanged.

## Notice limitations

Thirty seconds is the target search horizon at constant observed speed where
the sign and directed approach are established. It cannot guarantee 30 seconds
of actual display for every sign. In this BW data, many approaches still stop
at an unresolved junction, restriction or relation boundary. Town-entry signs
remain barriers rather than numeric upcoming-50 candidates. An earlier main
OSM-limit change can also make a physical target no longer lower. The
[first-drive investigation](UPCOMING_SPEED_LIMIT_NO_PREVIEW_INVESTIGATION_2026-10-23.md)
documents those distinct causes of short or absent previews.

Improving those cases requires better verified approach/applicability data and
relation-aware junction evidence. Increasing this distance alone does not
establish which road the driver will take. First qualifying fix timing, lookup
delivery and acceleration can also shorten nominal notice.

## Original Android drive evidence

The original installed-10059 text logs were copied read-only when Android
reconnected. Across 5,906 logged match samples, 2,443 were above 36 km/h, where
the original 300 m ceiling permits less than 30 seconds at constant speed.
The highest logged speed was about 92.25 km/h, corresponding to only 11.7
seconds at 300 m. These samples are not independent sign encounters or proof
that a preview was visible. The old logs contain no upcoming-target, horizon
or visibility fields, so they cannot establish actual displayed notice times.

The [speed-only summary](../output/upcoming-speed-limit-adaptive-horizon-2026-10-23/android/original-drive-log-summary.json)
contains no user coordinates or road names. Original text files and their capture
hashes remain in the local evidence directory; no media was copied and no app,
settings or map installation was changed on the phone.

## Validation scope

The shared corpus now has 42 scenarios and 59 steps. It covers exact and
just-outside adaptive thresholds, low-speed fallback, forward/reverse travel,
an 800 m cross-way target, speed changes, main-limit independence, hidden
passage with jitter and expiry without another fix. Native tests also exercise
the SQLite query boundaries and longer public BW source cases.

| Check | Result |
| --- | --- |
| Shared conformance | 42 scenarios / 59 steps passed on both platforms |
| iPhone native suite | 27 executed, one physical-only test skipped, zero failures |
| iPhone full BW reader | 21 source cases beyond 300 m, 63 attempts; correct physical target in each |
| iPhone full production service | Both corridor-HMM and M7 branches return the physical 30 target at 500 m with a 501 m horizon |
| Android JVM | Eight focused tests passed, including the shared corpus |
| Android native reader | Eight emulator tests passed; exact forward/reverse boundaries, longer cross-way passage and work-cap checks |
| Android controller lifetime | Scheduled three-second expiry and clock-rollback regression passed |
| Android public-source reader | All 21 cases pass on the extracted SQLite test subset |
| Android long captions | 1090 m and 2500 m each pass all 12 mount/camera/text-scale combinations |
| Protected reference checker | 39 scenarios / 171 steps passed; artifact hashes and both app pins match |

The iPhone's 42 warm full-database samples had p95 5.93 ms and maximum 6.70 ms
on the simulator. Android's final 21 extracted-fixture reads had median 0.79 ms,
p95 1.25 ms and maximum 1.55 ms on the emulator. These use different datasets,
caches and timing boundaries and must not be compared as platform performance.
They do not establish the physical-device warm-p95 target of 5 ms for the longer
window. The Android test permits up to three bounded retry attempts for a
deadline-limited sample; the final run needed one attempt per case. An earlier
single nil remains preserved in its first-run log. iPhone's first failed run
also remains preserved; its exact reverse-boundary subtraction issue and a
test-only bundle-identity fixture were corrected before the passing run.

Native evidence: [combined validation](../output/upcoming-speed-limit-adaptive-horizon-2026-10-23/validation.json),
[iPhone validation](../output/upcoming-speed-limit-adaptive-horizon-2026-10-23/iphone/validation.json),
[Android validation](../output/upcoming-speed-limit-adaptive-horizon-2026-10-23/android/validation-summary.json),
[Android long cases](../output/upcoming-speed-limit-adaptive-horizon-2026-10-23/android/long-horizon-native-results.json).

This is a working-tree app update. The original build 10059 installation and
physical measurements describe the earlier 300 m behavior. They do not prove
this update is installed on either phone, nor measure its physical-device
latency. The protected speed-reference artifact, interpreter policy and pins
remain unchanged.
