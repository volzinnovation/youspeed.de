# City context where speed evidence is absent

This recheck restricts the [Baden-Württemberg pilot](BADEN_WUERTTEMBERG_SETTLEMENT_PILOT_2026-09-14.md)
to roads without recorded explicit or implicit speed evidence. Source snapshot:
13 September 2026, 20:21:20 UTC. The original recheck changed no bundle or client
behavior; the subsequent consumer fallback adjustment is documented below.

## Population and filter

The filter uses the original `raw_tags` in `ways.meta`, because the final `ways`
table does not retain all directional, conditional and vehicle-specific tags.
It excludes a whole OSM way if either direction has a nonempty tag in any of
these families, including colon-separated descendants:

- `maxspeed`, including symbolic values such as `none` and `DE:urban`;
- `source:maxspeed`, `zone:maxspeed`, or `max:speed`;
- `zone:traffic`;
- `traffic_sign` with value `maxspeed` or a recognized German speed sign
  (`DE:274`, `DE:278`, `DE:282`, including variants and shared country prefixes).

It also excludes `motorway`, `motorway_link` and `living_street`, whose class
rules can be applied independently of city detection. Ordinary classes such as
`residential`, `primary` and `service` remain eligible in this source-evidence
audit even when a consumer can supply a road-class fallback speed.

This is deliberately a conservative **absence-of-recorded-tags** filter.
Provenance-only, advisory, vehicle-specific, variable and malformed speed values
also exclude a road; an excluded tag does not necessarily supply a usable
passenger-car limit. Town-entry/exit signs and settlement polygons remain part
of the city-context outcome being measured, rather than exclusions that would
remove the evidence under evaluation.

| Filter step | OSM ways |
| --- | ---: |
| All admitted roads | 1,085,790 |
| Excluded by recorded speed evidence | 418,365 |
| Remaining without those tags | 667,425 |
| Further excluded by independent class rules | 19,206 |
| **Eligible for this recheck** | **648,219** |

The independent-class exclusions are 17,030 living streets, 2,165 motorway
links and 11 motorways. Among eligible ways, 491,351 (75.80%) are service roads,
97,892 residential, and 32,295 unclassified. The result is therefore strongly
influenced by service roads.

## Filtered result

| `inside_city` | Confidence | Segment records | Share |
| --- | --- | ---: | ---: |
| `true` | high | 1,711 | 0.225% |
| `false` | high | 1,700 | 0.224% |
| `true` | low, landuse | 497,747 | 65.449% |
| `NULL` | unknown | 259,348 | 34.102% |
| **Total** | | **760,506** | **100.000%** |

Only **0.449%** of these records have high-confidence context, compared with
9.69% across the complete pilot. Unknown context increases from 32.71% overall
to **34.10%** in this population. The unknown records include 14 conflicts and
259,334 records lacking usable evidence.

Most high-confidence results here come from town signs: 1,473 inside and 1,697
outside records. Explicit urban/traffic polygons contribute another 238 inside
and three outside records. Weak landuse supplies the large remainder of known
inside states; under the implemented client policy, it cannot select a city
default speed or settlement penalty variant. Accordingly, **99.551%** of the
filtered segment records lack high-confidence settlement evidence. This measures
city-context coverage, not the share of roads that can display a fallback speed.

Following review of the Bad Herrenalb examples, the approved consumer policy
provides a **50 km/h road-class fallback for residential and service ways**
without usable speed evidence when no high-confidence settlement default takes
precedence. City state remains nullable and independent of that fallback. All
eight mapped examples satisfy this rule: their original pilot rows have one of
those two classes, empty `maxspeed`/`maxspeed_type`/`source_maxspeed` values, and
`inside_city=NULL` with `source=missing`. The source-evidence filter and counts
above remain unchanged; road-class fallback is not recorded OSM speed evidence.

At whole-way grain, 167,869 ways (25.90%) are unknown throughout and 73,980
(11.41%) are unknown on at least one, but not every, segment. OSM ways are map
pieces, not unique street names. Segment records can split a way and represent
directions separately; these percentages are not distance-weighted or measured
driving accuracy.

## Checks and reproduction

All 1,085,790 original way IDs matched the pilot database exactly in both
directions. The filter's primary key rejects duplicate IDs. No eligible way
lacks a settlement segment, and whole-way groups sum to 648,219. Sign-filter
edge checks cover shared country prefixes, country changes, zone signs and
town signs.

The database SHA-256 remains
`1938df90ffa6b9ff0f5dfb2b4f09c622f4208cb03102fc5fb2c2f5ebc531a183`.
The raw metadata SHA-256 is
`ba5efb698e12f76a9a719d756e64911f010c7ed6bc53f5d842738d9433ad9969`.

The [complete result](baden-wuerttemberg-no-speed-evidence-2026-09-14.json)
records SQL, counts, exclusions and source hashes. The
[analysis script](../scripts/map/audit_unmapped_speed_context.py) uses a
read-only database connection and an in-memory temporary filter table:

```sh
python3 scripts/map/audit_unmapped_speed_context.py \
  mapdata/dist-v3/baden-wuerttemberg-settlement-pilot/speeds_v3.sqlite \
  mapdata/dist/baden-wuerttemberg-settlement-pilot/ways.meta
```
