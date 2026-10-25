# Speed-limit reference model history

## 1.2.0 — 2026-10-25

Explicit product-owner authorization: accept fresh, stable map limits after a
confirmed road change without the eight-second stale interval, with Android
kept in line with iPhone. The 24 October evening iPhone drive contains 79 stale
outputs despite 78 of those lookups having a selected way.

Ordinary different-road departures now confirm after two consecutive distinct
fixes on the same pending road/way/relation. Both must have age 0–3 seconds,
accuracy 0–20 m, selected-way distance 0–10 m, an applicable typed map value,
and no more than three seconds between fixes. Duplicate timestamps cannot add
proof; missing/unusable fixes reset it. The controller retires old-scope camera
and voice producers before publishing the fresh map reference on that lookup.
Unqualified/ambiguous departures and direction reversals retain eight seconds.
Priority, ordinary expiry, missing-context bounds and camera applicability do
not change. Published 1.0.0 and 1.1.0 files remain immutable.

The new policy and conformance corpus, plus twelve shared native adapter cases,
are hash-pinned in the updated owner approval lock. See the controller validation
and device-log review in `docs/IPHONE_TRIP_AND_REFERENCE_REVIEW_2026-10-25.md`.

## Adapter repair — 2026-10-24

Explicit owner request: clear the outbound camera limit after a turnaround,
including a return across intervening ways on the same road/relation. Both
adapters retain bounded per-way accepted directions and preserve the pending
reversal through those intervening ways. The existing eight-second confirmation
still applies. Controllers retire the old camera producers when the confirmed
scope generation changes. Policy 1.1.0, its interpreter semantics, versioned
artifacts and approval lock are unchanged.

## 1.1.0 — 2026-09-27

Owner-approved disregard-vision button: `camera_dismissed` withdraws ordinary
and enclosing camera claims and camera-derived last-known memory. Current road
and explicit voice claims remain intact. Same-track and pending-frame rejection
are controller responsibilities. No expiry, priority or road-context thresholds
changed. Published v1.0.0 artifacts remain unchanged.

The producer adapter also emits an unresolved passage's authority withdrawal
once per physical evidence ID. Re-rendering that same unresolved passage must
not clear every subsequently verified road-bundle input.

## 1.0.0 — 2026-09-26

Initial runtime policy explicitly requested by the product owner in the
September 26 device-log investigation. Explicit clarifications:

- Apps consume the configuration at runtime; no state-machine UI. Documentation
  and standard-tool visualization are development/configuration artifacts.
- Ordinary speech/camera evidence expires at **5 km or 300 seconds**, whichever
  occurs first. Only explicit owner commands authorize policy edits.
- Camera candidate selection using the camera-specific embedded network and
  road/lane applicability using bundle topology stay in the external visual
  pipeline. Its evaluated output is input 2.
- Camera and bundle inputs support future vehicle-class, time, rain/weather and
  other restrictions through applicable/inapplicable/unresolved envelopes.

Priority: speech > applicable camera > applicable current bundle; last-known
continuity is display-only, with no violation/penalty baseline. Confirmed city
entry/exit, road-relation departure, direction reversal and applicable ends
invalidate old scope. A tentative road change preserves authority; the adapter
uses 8 seconds of sustained different-road evidence to confirm departure.

The common JSON transition table is interpreted in Swift and Kotlin, with a
Python reference oracle and shared scenarios. Artifacts and approval lock are
hash-pinned. Native runtime adapters, expiry ticks and final controller
publication consume the resulting reference. External visual-pipeline topology
repairs, detection of future restrictions and Android log retention are separate.

## 0.1.0 — 2026-09-26

Descriptive snapshot of both clients at `99d62f2`, tied to the device findings.
This is evidence about the former implementation, not a selectable runtime policy.
