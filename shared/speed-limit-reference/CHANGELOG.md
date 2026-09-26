# Speed-limit reference model history

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
