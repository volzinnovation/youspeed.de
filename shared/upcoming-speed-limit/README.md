# Upcoming speed-limit conformance

`scenarios-v1.json` is the shared iPhone/Android preview selection and lifetime
corpus. All records are synthetic. Each case starts a fresh tracker/session;
steps supply a raw lookup snapshot, current effective limit and timestamps.
Adaptive cases also supply observed `speedKmh` and snapshot
`lookaheadDistanceM`; both native harnesses verify
`max(300, speedKmh / 3.6 * 30)`. Legacy snapshots without the field retain
the 300 m default. Snapshot distance affects preview lookup/eligibility only;
the lower-limit comparison still uses the effective main limit.
`tick` reevaluates the prior snapshot without refreshing its fix timestamp.

The corpus contains 42 scenarios and 59 steps. It covers the inclusive 300 m
floor and adaptive boundaries at 50/80/100/130/300 km/h, speed changes,
longer forward/reverse and certified cross-way approaches, strictly lower comparison,
unlimited/unknown current references, nearest eligible selection, reverse travel,
same-way fallback, certified cross-way paths, expiry without a new fix, and
passage memory while a candidate is hidden by higher-priority current evidence.
OSM identities are strings so JSON does not lose 64-bit identifiers.

Native SQLite tests and the Python topology builder tests separately verify
physical station queries, interval applicability, source-node connectivity,
conflicts, junction stops and path distances. Preview fixtures do not change the
protected speed-limit-reference policy.

The 24 October turnaround repair permits a preview to follow unique contiguous
segments of the **same directed OSM way** through a side junction, with verified
geometry, allowed motorcar travel and no way/node restriction barrier. Choosing
a different way still requires the certified unbranched source-node successor
and a shared followed relation. A plain numeric `road_speed_capability=1` OSM
tag may supply a map-boundary preview there, carrying its real source snapshot
and an `osm-road-boundary:` identity. It does not assert a physical sign or alter
the current limit. Conditional/vehicle-specific tags remain withheld. An
endpoint-only physical numeric rule may be supported by an equal independently
verified mapped boundary; the preview then retains the map identity. Town
locality does not suppress an explicit mapped numeric limit at the boundary.
