# Conditional road speeds, version 1

The core full-bundle builder compiles all raw speed namespaces independently of
government inventory. `road_speed_source_tag` retains exact tags and snapshot;
`road_speed_rule_set` holds the bounded JSON consumed by both native adapters.
Rule, condition and interpretation tables retain ordered clauses and unsupported
evidence. Capability/grammar changes and all conditional-capable bundles require
full delivery; both exact and heuristic delta creation fail before writing output.

Grammar `youspeed-osm-speed-1` supports numeric/`none` values, daily and weekday
windows, comma windows, overnight start-day anchors, annual date/month ranges,
Boolean AND/OR and PH/SH exclusions. Calendar coverage, wetness, vehicle/lane
qualifiers and unsupported syntax remain unresolved when evidence is missing.
One unknown fact stays correlated throughout the ordered decision list. Only a
single reachable typed outcome can be an exact current limit. Variable-sign
inventory cannot prove its currently displayed number. Numeric 5 stays numeric.

The clients evaluate current time in a geographically qualified zone (Germany:
Europe/Berlin), including both occurrences of a repeated DST hour. Other zones
must be supplied explicitly. They keep raw rules for minute-boundary evaluation
without renewing GPS or camera evidence. Legacy BW bundles retaining raw
conditional tags mask affected scalar fallbacks until the compiled rules arrive.

Producer precedence stays: own correction, current visual evidence, accepted
government evidence (MobiData only in BW), evaluated OSM. Conditions do not
modify the protected reference policy. Source annotations with
`evaluation_enabled=false` are never executable rules.

On 2026-11-18 the product owner selected normal-road reference plus conditional
preview while wetness detection is unavailable. Both driving adapters evaluate
the wet branch as inactive for this presentation choice; this is not evidence
that the road is dry. The generic evaluator still reports unknown wetness as
unresolved. Previews translate the raw `wet` token in all four app languages.

A recognized numeric camera sign is linked to supported motorcar conditional
clauses only on the same stable bundle way and matching travel direction, with
the same numeric value. In that case the evaluated bundle owns the selection
(including the independent base outside a schedule), even without OCR. Existing
camera claims are reassessed when bundle context arrives. No OCR verification
or new camera observation is fabricated; unrelated camera numbers, own
corrections and the protected reference-policy priority/expiry remain intact.

`conformance-v1.json` is the shared Swift/Kotlin fixture. The compiler also checks
all 191 observed BW key/value patterns, preserving unsupported forms verbatim.
Public packaging raises minimum app compatibility to 1.5 when this capability
is present; this does not publish or install a bundle.
