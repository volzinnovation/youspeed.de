# Native passage suppression conformance

`PassageParityTests` in Swift and Kotlin execute `suppression-v1.json` through
the production finalizers. The 16 scenarios cover the five-second boundary,
positions just below/above 30 metres, reused and new track IDs, missing current
coordinates, clock rollback, and retention of the last known visible position.
Prefixes establish a valid recognition origin and commit; suppression time is
measured from that commit, not from the last visible frame.

The finalizers sit at different pipeline stages. iPhone validates recognition
origin and boundary scope before commit. Android can emit raw passage evidence
before its applicability/activation resolver rejects it. A raw Android commit
with no recognition origin is therefore not an equivalent observable state to
an iPhone committed passage. Each native suite separately verifies that a sign
seen entirely without an origin cannot activate a camera speed limit when map
context returns only at loss. Android's lower-level tests retain cases where a
previous suppression coordinate is absent.

The corpus describes the existing iPhone reference behavior. It does not modify
or replace the governed policy in `shared/speed-limit-reference/`, and does not
claim complete vision, tracking, passage or activation parity.
