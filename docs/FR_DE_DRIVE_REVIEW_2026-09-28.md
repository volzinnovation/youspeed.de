# France–Germany drive review, 28 September 2026

## Evidence and limits

Android was inspected read-only while Panoramax continued uploading. No force-stop,
reinstall, instrumentation, or UI navigation was performed on the physical phone.
Tests ran on the Mac, iPhone simulator, and Android emulator.

The preserved evidence is in the Git-ignored directory
`inspector/logs/2026-09-28-fr-de-review/`, with SHA-256 inventory. It includes the
532 MiB Android runtime log, the surviving GPS/matcher logs, Panoramax checkpoint
and journal metadata, and eight original stills. The 28 September runtime subset
contains 37,477 events, including 24,910 frame applicability diagnostics. The day's
Panoramax batch has 826 captures spanning 14:06:32–17:42:11 UTC.

The iPhone app had already restarted at 18:47 UTC before the first successful
container copy. Only the new, short GPS/matcher/TSR logs remained. Its startup code
explicitly deleted prior matcher/TSR logs and overwrote GPS. The Panoramax inventory
contained no 28 September captures; its latest retained batches were from 27
September. Therefore today's iPhone drive cannot be compared event-for-event.
Its successful German penalty behavior is the user's observation, not a recovered
log result. The log-retention fix below prevents this loss on subsequent launches
once installed; it cannot recover deleted evidence.

## Exit and service-area signs

All 30 Android manual dismissals transitioned from CAMERA to BUNDLE (T16). The
button works at that instant. It does not suppress every subsequent sign along an
exit: at 16:09:32 UTC a dismissal was followed by another camera activation 3.07
seconds later, with a subsequent 50 km/h exit sign. This is distinct from restoring
the same dismissed evidence. A later dismissal at 16:09:57 was followed by a new
110 km/h observation, so immediate reactivation is not automatically an error.

Automatic exclusion produced only **eight exit-rejection candidate decisions**,
not eight distinct signs. No access-road rejection occurred. Among 359 candidate
observations that were recognition-eligible, 30–90 km/h, below the map limit, and
on a stable motorway match with map limit at least 100:

| Blocking condition for the existing exit guard | Observations |
| --- | ---: |
| Road snapshot older than 1.5 seconds (or future-dated) | 322 / 359 (89.7%) |
| No qualifying connected motorway-link branch | 265 / 359 (73.8%) |
| Sign centre left of x=0.60 | 195 / 359 (54.3%) |

These conditions overlap. Median road-snapshot age in this subset was 2.866 seconds.
Android requested precise GPS only every three seconds. Query latency adds to the
age before camera inference can consume the road match. Merely raising the age
limit would reuse evidence across substantial travel and potentially across exits.

The installed Lorraine/Alsace July bundles report endpoint-only topology. They
lack the newer directed exit lookahead capability. A split mainline way can thus
lose visibility of an approaching ramp. The current service-road guard also
explicitly excludes motorways: it only handles trunk/primary/secondary roads,
requires a repeated recent main-road sign, and looks for a nearby service road.
It cannot address motorway rest-area signs as currently written.

The general applicability evaluator runs in shadow mode. An UNKNOWN result for
stale or uncalibrated road context does not itself veto recognition. The dedicated
exit/access guards are the exceptions. Consequently high classifier confidence
can become camera authority even when road applicability is unknown.

### Visually inspected examples

Times below are UTC; add two hours for France/Germany local time.
Original stills and recognition frames are separate captures: use their timestamps,
not the annotation rectangle as an exact overlay on a later still.

| Event | Image evidence and matching diagnostics |
| --- | --- |
| 14:18:25 dismissal | `android/photo-141823.jpg`, captured 14:18:20.337, shows the main carriageway continuing beside a separating right-hand exit. A 90 was accepted before dismissal; a later 70 candidate was around x=0.56, left of the guard boundary despite the exit being to the right of the car. |
| 14:34:47 dismissal | `android/photo-143443.jpg`, captured 14:34:44.362, clearly shows the **Aire de Brouck 30** beside the service-area road while the car remains on the motorway. Diagnostics see 30 at 14:34:45–46, x=0.73–0.93, map 130. There is no qualifying branch and road context is stale. |
| 15:37:52 dismissal | `android/photo-153749.jpg`, captured 15:37:51.359, shows a separate right-hand ramp and its signs. The log contains lower-speed detections around that ramp, but its road snapshot is stale. |
| 15:43:00 dismissal | `android/photo-154300.jpg`, captured 15:42:57.337, shows the separate ramp climbing on the right; the 70 candidate had a 5.027-second-old road snapshot and no branch. Detailed orientation-corrected review shows a sign back in this still, so the earlier 70's identity/value cannot be verified from these pixels. The road-context failure is recorded, but this still is not verified truth for that candidate. |
| 16:09:32 dismissal | `android/photo-160930.jpg`, captured 16:09:29.393, shows the right-side exit lane and its 70. Recognition initially places it near image centre (x≈0.51–0.53); the subsequent exit 50 becomes a new camera claim after dismissal. |

These daylight examples support wrong-road attribution, not night visibility, as
the primary cause in this drive. A camera-image x threshold alone is not a reliable
road/lane assignment: mounting position, road curvature and perspective matter.

### Remaining automatic-filter work

The evidence supports the proposed preprocessing direction, but it must describe
**directed mainline intervals**, not blanket exclusion of entire OSM ways. Include
exit/service-road side, start/end distance along the mainline, connected branch ID,
provenance, and a release when the vehicle actually takes the ramp. Carry exclusion
through candidate selection, immediate overrides, passage finalization, and image
annotations. Rebuild the French bundles with the new context; an app update alone
cannot supply topology absent from the installed databases. Validate paired
mainline limits and roadworks as positive controls before expanding a right-side
mask. Military capture exclusions require separate semantics from TSR attribution.

The current extractor already preserves source vertices. Disabling simplification
again is not a fix; older installed bundles need rebuilding to obtain that geometry
and the newer preprocessing. This review does not claim the complete exit/service
filter is fixed.

## Germany penalty investigation

Confirmed sequence:

- At 16:35:11.845 UTC Android switched from Alsace to Baden-Württemberg, country DEU.
- At 16:35:15.384 it requested the DE TSR model from location-country selection.
- At 16:35:21.288 the German model loaded successfully.
- Replaying retained capture coordinates against the exact deployed coverage asset
  gives FR at 16:30:04, FR+DE overlap at 16:32:58, and DE alone at 16:35:06.
  All 232 later retained capture positions resolve to DE alone.

The installed APK hash was
`cfa2e2ffdb10c80209d2646c51033d70f2765387bd1519b48f60bac7257eb2db`, identical to
the local pre-change artifact. It includes `Rules/DEU-rules.json` with ten bands.
Android and the previously built iPhone have identical coverage asset hashes.
The German parser and a France→overlap→Germany presentation regression pass.
For the tested 50-limit/60-speed/outside-town input, the existing shared German
rules produce the expected 20 value in the UI. No legal tariff values were changed.

The user clarified that Android displayed **speed with the warning background**,
rather than retaining French amounts. That is reproducible when penalty rules are
unavailable: background colour uses overspeed independently of the fine. Active
tunnel suppression is another presentation path that can hide the fine. The old
runtime log did not record penalty availability, rule country/file, or enough
presentation state to establish the exact historical cause after the transition;
the detailed drive matcher log had been truncated at restart.

A definite parity bug was found and fixed: `onTrafficSignBundleSelected` required
the GPS country to equal the selected map country before showing any rules. iPhone
uses fresh location evidence even when a neighboring extract remains selected.
Android now does the same, checks evidence expiry on bundle activation, and still
withholds rules for invalid/ambiguous location. This removes a real route-switch
failure path, but is **not proof that it explains the entire reported drive**.

New `penalty_rules_selected` diagnostics record country, map country, rule file,
number of bands, availability and trigger when selection changes. For location
updates they also record fix timestamp/age, accuracy and coverage-country matches.
Retained matcher logs allow the next incident to be distinguished from tunnel or
stale-speed presentation.

## Recognizer identity

Panoramax annotation lineage confirms these actual Android classifier hashes:

- France: `fr-panoramax-bootstrap-evaluation-v1`, classifier
  `a4652db06265013f10610b984bc7ab55d7ca32a5ec8e040785db47c276ae00ea`.
- Germany: `de-panoramax-bootstrap-live-v1`, classifier
  `28d2ce40455d0f9cac2f7c61a51b5a5f95f17fa57fc5706a56f64fa9f8bd7df0`.
- Both used detector
  `e5490acd60ceb015336bed487b5e247c2728b2b98b6336790bf6ffe02a6f7207`.

No model or recognition confidence threshold was changed.

## Local changes and validation

- iPhone startup now preserves all previous matcher/TSR files and appends to the
  existing GPS file. New matcher/TSR session files retain timestamped names.
- Android startup creates missing GPS/matcher files without truncating existing
  contents. Runtime diagnostics already appended. Explicit clear actions remain.
- Android bundle activation respects fresh GPS penalty-country evidence, matching
  iPhone, and logs selection availability.
- Android precise location requests now use one second instead of three, to avoid
  making the 1.5-second applicability limit impossible between normal fixes.
  iPhone already requests continuous best-accuracy updates without a distance
  filter. The Android lookup worker still coalesces pending fixes. Actual device
  latency and power impact remain to be measured on a subsequent drive; this
  freshness correction does not resolve missing exit geometry or lane attribution.

Validation: 49 Android unit tests passed (country penalties and consumer parity),
2 iPhone simulator tests passed (restart preservation and explicit clearing), and
1 Android emulator controller test passed, including neighboring-map penalty
reconciliation, invalid-location withholding, road recovery and manual dismissal.
Android debug app and instrumentation APKs build successfully. `git diff --check`
passes. The shared speed-reference policy was not changed in this review.

**Not installed on the attached phones.** Android's upload was left running.

## Offline follow-up

Four of these incidents are now preserved as exact, hash-bound candidate replays
in the [recorded-failure fixtures](../shared/tsr/applicability/fixtures/README.md).
The [simulation design](TSR_EXIT_SIMULATION_DESIGN_2026-09-28.md) maps failures and
positive controls to tests and separates recorded timing from sparse Panoramax
imagery. The [related scientific work](TSR_ROAD_APPLICABILITY_RESEARCH_2026-09-28.md)
compares road geometry, scene context and motion approaches. These additions are
offline experiments; they do not establish that the production exit filter is
fixed or change either phone's running app.
