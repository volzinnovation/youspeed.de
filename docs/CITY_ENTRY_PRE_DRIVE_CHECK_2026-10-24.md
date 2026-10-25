# City-entry preview pre-drive check — 24 October 2026

Passed the native reader and bundle checks for upcoming German city-entry signs.
Both clients derive an upcoming **50 km/h** from a valid, directed DE:310 rule.
A valid explicit numeric limit at the same station takes precedence. Opposite
directions, ambiguous associations and unresolved conditions are withheld;
DE:311 does not invent an upcoming outside-city limit.

Both physical phones' active-map metadata identifies
`2026-10-23-v1.5-journal-conditional`, SHA-256
`e973d279de2803b13037b9e87132be72f28a22d8f9c9bbef79d73093772b1849`.
The local complete database was decompressed and independently hashed to that
same digest. It contains 10,709 accepted DE:310 entries with accepted all-lane
city rules: 6,351 from MobiData BW and 4,358 OSM fallbacks.

Five unmodified source examples were checked through both native readers:
three MobiData examples and two OSM examples, covering both directions. Every
example yielded the expected physical sign, 50 km/h and distance ahead.

- iPhone simulator: five focused tests passed, including 150 reader calls
  over the five real examples, plus direction, explicit-limit precedence,
  conditional applicability and certified-split checks.
- Physical Moto g86: five focused native tests passed, including the same five
  real examples. The tests used the separate testhost app.
- The earlier Android Fahrtenbuch follow-up also passed its physical off/on/off
  and history/normal-Settings navigation UI test in that isolated app. The normal
  driver app was reopened with its original unconfigured/off recording choice
  and conditional map retained.

The preview follows the existing lower-limit presentation rule. It appears
within the 30-second speed-dependent horizon (minimum 300 m), with a fresh usable
road match, when 50 is lower than the current applicable limit. If the current
limit is already 50, the duplicate 50 preview is suppressed. Map coverage and
direction confidence still determine which approaches qualify; these checks
are not a road test or a guarantee for every city boundary.

No runtime policy, source priority, production code or bundle data changed.
No driver GPS/TSR contents were read or exported. The temporary decompressed
3.19 GB map was removed after verification. Small native results and the public
source-row probe remain under `/private/tmp/youspeed-town-entry-check-20261024/`.
The initial probe omitted the conditional capability table; both readers
correctly withheld its OSM examples. Final passing runs retained the exact
source capability table and verified the Android staged probe hash.

[Machine-readable receipt](CITY_ENTRY_PRE_DRIVE_CHECK_2026-10-24.validation.json)
