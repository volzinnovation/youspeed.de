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
