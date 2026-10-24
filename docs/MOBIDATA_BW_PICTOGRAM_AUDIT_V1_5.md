# MobiData BW pictogram and classifier audit for v1.5

Updated 2026-10-21. The source contains **163,504 records and 53 exact codes**. [JSON mapping](MOBIDATA_BW_PICTOGRAM_AUDIT_V1_5.json) preserves source identity, counts, pinned artwork and model capability.

The six previously missing source artworks have now been acquired as official-work SVG renditions, pinned with Commons revisions/licence/hashes, and rendered as transparent shared PNGs: DE:101-15, DE:156-10, DE:223.1-50, DE:325.1, DE:325.2 and DE:460-20. Both clients package the same shared bytes. This does not add model outputs.

Town signs already have artwork but the pinned classifier has no town-entry/exit outputs. DE:274-90 also has no exact classifier class. Family-only, absent and reference-only labels cannot confirm the exact inventory sign. The runtime overlay therefore gives these records an empty exact-model label list and logs unsupported classes honestly.

The source contains no DE:108/110 or DE:262–266 records or printed grade/mass/dimension fields. Future numeric parameters remain nullable typed source values, with separate synthetic parser fixtures. DE:278 has 9,769 records without a printed value. Bracket annotations remain preserved and cannot authorize dynamic speed rules. Town names and the detour number in reference artwork are illustrative, not source observations.

| Source code | Records | Pictogram status | Classifier capability | Labels |
| --- | ---: | --- | --- | --- |
| `DE:101` | 1,932 | existing_exact | exact_label | hazard |
| `DE:101-15` | 164 | existing_exact | family_only | hazard:rocks |
| `DE:101-51` | 316 | existing_exact | exact_label | hazard:ice |
| `DE:101-52` | 16 | existing_exact | exact_label | hazard:gravel |
| `DE:103-10` | 459 | existing_exact | exact_label | hazard:left_turn |
| `DE:103-20` | 568 | existing_exact | exact_label | hazard:right_turn |
| `DE:105-10` | 107 | existing_exact | exact_label | hazard:zigzag:left |
| `DE:105-20` | 118 | existing_exact | exact_label | hazard:zigzag |
| `DE:112` | 414 | existing_exact | exact_label | hazard:bumps |
| `DE:114` | 463 | existing_exact | exact_label | hazard:slippery |
| `DE:117-10` | 134 | existing_reviewed_alias | family_only | hazard:wind |
| `DE:124` | 203 | existing_exact | exact_label | hazard:traffic_jam |
| `DE:125` | 191 | existing_exact | exact_label | hazard:bothways |
| `DE:142-10` | 746 | existing_reviewed_alias | family_only | hazard:wild_animals |
| `DE:151` | 6 | existing_exact | exact_label | hazard:level_crossing, hazard:train, hazard:train2 |
| `DE:156-10` | 148 | existing_exact | absent |  |
| `DE:205` | 432 | existing_exact | exact_label | give_way |
| `DE:206` | 1,429 | existing_exact | exact_label | stop |
| `DE:209` | 836 | existing_exact | exact_label | arrow_turn_right |
| `DE:215` | 317 | existing_exact | exact_label | roundabout |
| `DE:222` | 6,214 | existing_exact | exact_label | arrow_right_down |
| `DE:222-10` | 47 | existing_exact | exact_label | arrow_left_down |
| `DE:223.1-50` | 186 | existing_exact | absent |  |
| `DE:267` | 4,460 | existing_exact | exact_label | no_entry |
| `DE:274-10` | 267 | numeric_speed_schematic_exception | exact_label | maxspeed:10 |
| `DE:274-100` | 1,694 | numeric_speed_schematic_exception | exact_label | maxspeed:100 |
| `DE:274-120` | 1,706 | numeric_speed_schematic_exception | exact_label | maxspeed:120 |
| `DE:274-130` | 95 | numeric_speed_schematic_exception | exact_label | maxspeed:130 |
| `DE:274-20` | 703 | numeric_speed_schematic_exception | exact_label | maxspeed:20 |
| `DE:274-30` | 35,423 | numeric_speed_schematic_exception | exact_label | maxspeed:30 |
| `DE:274-40` | 4,196 | numeric_speed_schematic_exception | exact_label | maxspeed:40 |
| `DE:274-50` | 12,981 | numeric_speed_schematic_exception | exact_label | maxspeed:50 |
| `DE:274-50[WVZ Rombachtunnel]` | 1 | source_annotation_requires_review | exact_label | maxspeed:50 |
| `DE:274-60` | 3,251 | numeric_speed_schematic_exception | exact_label | maxspeed:60 |
| `DE:274-70` | 19,307 | numeric_speed_schematic_exception | exact_label | maxspeed:70 |
| `DE:274-80` | 3,582 | numeric_speed_schematic_exception | exact_label | maxspeed:80 |
| `DE:274-90` | 70 | numeric_speed_schematic_exception | absent |  |
| `DE:276` | 6,911 | existing_exact | exact_label | no_overtaking |
| `DE:277` | 1,126 | existing_exact | exact_label | no_overtaking:hgv |
| `DE:278` | 9,769 | missing_printed_speed | family_only | maxspeed:end |
| `DE:280` | 440 | existing_exact | exact_label | no_overtaking:end |
| `DE:282` | 1,567 | existing_exact | exact_label | no:end |
| `DE:310` | 13,788 | existing_exact | reference_only |  |
| `DE:311` | 9,312 | existing_exact | reference_only |  |
| `DE:325.1` | 10 | existing_exact | absent |  |
| `DE:325.2` | 3 | existing_exact | absent |  |
| `DE:330.1` | 1,216 | existing_exact | exact_label | motorway:start |
| `DE:330.2` | 994 | existing_exact | exact_label | motorway:end |
| `DE:331.1` | 6 | existing_exact | exact_label | trunk:start |
| `DE:331.2` | 3 | existing_exact | exact_label | trunk:end |
| `DE:331.2[]` | 1 | source_annotation_requires_review | exact_label | trunk:end |
| `DE:350-10` | 15,175 | existing_reviewed_alias | family_only | pedestrian_crossing |
| `DE:460-20` | 1 | existing_exact | absent |  |

All referenced original/PNG hashes are checked by the shared asset verifier. Exact classifier vocabulary availability alone does not establish recognition precision or legal applicability.

[Official VzKat source](https://www.verwaltungsvorschriften-im-internet.de/BMVBW-S32-0001-KF10-BS-A008.htm); per-image Commons provenance and public-domain official-work basis are pinned in `shared/tsr/sign-pictograms/manifest.json`.
