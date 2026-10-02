# Swiss junction challenge: Le Vaud, 30 beside 50

[Original user-supplied image](https://panoramax.youspeed.de/?focus=pic&pic=f8ea80f9-c525-44fb-a6d8-7af479f7fdd8&seq=2d99a379-6410-4a15-accd-79264ee714ed),
captured **2026-09-27 13:50:56.384 UTC**, shows two simultaneous signs. The user
assigns **30 to the left-turn street** and **50 to the current main street**.
The through road bends right; the side street climbs left. Continuous painted
ego lane boundaries are not visible. This challenges a lane-marking-only
estimator as well as motorway-only rules, a left/right image veto, or choosing
the lowest detected number. The 30 must become relevant if the driver actually
enters that street.

`corpus.json` preserves those labels, original frame/sequence identity and
timestamp, image/metadata hashes, public attribution and the generic SGBlur
traffic-sign boxes whose numerical identities were visually checked. The HD
image is 4224 × 2376, rectilinear and upright (decoded EXIF orientation 1).
Original metadata EXIF orientation 3 must not rotate it again. Image bytes remain
in the ignored evidence cache; hash-pinned public item metadata is stored alongside
the fixture.

The EXIF app annotation records a historical **50**, classifier
`ch-panoramax-bootstrap-evaluation-v1`, applicability **UNKNOWN**, and way
`1284897716`. These are historical observations, not an independently checked
map assignment, a measured 30 detection, or a replay result.

`image-geometry.report.json` runs the existing offline support-to-road experiment
with approximate manually reviewed asphalt polygons and support points:

| Sign | User governing-road label | Reviewed geometry result |
| --- | --- | --- |
| 30 | Left street / other | Other: visible support is near the separate street. |
| 50 | Through street / ego | Unknown: exact support ground contact is obscured by the roadside marker/grass. |

This is a manual geometry ablation, **not automatic vision accuracy**. Removing
reviewed geometry makes both results unknown. The legitimate 50 remains
unresolved; the user label is used only for scoring. There is no temporal track
carry, historical fixed-x baseline, inferred lane count, driver intent, behavior
feature, OSM graph, or device latency measurement. Local road IDs are semantic
labels, not fabricated OSM IDs. One inspected still is development material,
not a locked holdout or simulated video.

The separate `test_swiss_junction_challenger.py` oracle tests deliberately supply
correct road association and an ideal current pose. They verify two independent
candidate decisions in one frame, candidate-order invariance, equivalent results
when image positions swap, abstention without geometry/pose, and release of the
30 when hypothetically entering the branch. These are decision-wiring tests;
they do not count supplied labels as successful inferred geometry or confirm a
displayed speed-limit transition. No shared speed-reference policy changes.

```sh
python3 -m pytest tests/tsr/test_swiss_junction_challenger.py -q
python3 scripts/tsr/applicability/fetch_public_image_corpus.py shared/tsr/applicability/fixtures/panoramax-swiss-junction-v1/corpus.json
python3 scripts/tsr/applicability/image_geometry_replay.py shared/tsr/applicability/fixtures/panoramax-swiss-junction-v1/corpus.json --output /tmp/youspeed-swiss-junction-report.json
```

The explicit fetch accepts this exact HTTPS Panoramax host and hash-verifies the
image. Source: admin / Panoramax YouSpeed, CC-BY-SA-4.0, per preserved metadata.
