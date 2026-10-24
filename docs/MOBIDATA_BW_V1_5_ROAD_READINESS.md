# BW v1.5 road-base readiness repair

Built and validated on 2026-10-21. The complete road/settlement/inventory base at
`mapdata/dist-v3/baden-wuerttemberg-v1.5-roads/speeds_v3.sqlite` passes the current
`validate_v3_testing_bundle.py --require-settlement` gate with **zero errors and
zero warnings**. `PRAGMA quick_check` returns `ok`.

The [machine-readable receipt](MOBIDATA_BW_V1_5_ROAD_READINESS.json) preserves the
validated counts, capabilities, geometry results and source identities before
the separate directed sign-runtime overlay. All ten errors inherited by the
earlier disabled pilot are repaired by rebuilding the actual data:

- Every one of the 1,085,790 road ways retains its original source vertices.
- Detailed topology contains 1,753,356 endpoint links.
- Paired corridor precomputation contains 45,674 progress rows and 5,634 pairs
  across 7,756 components.
- The directed motorway-exit approach table contains 1,497 records.
- Settlement evidence contains 1,294,214 segments and has no incomplete,
  zero-length or fallback source ways.
- The full independent traffic-sign inventory contains 163,504 records.

This is a rebuild from the pinned PBF with replication timestamp
`2026-09-13T20:21:20Z`, not a network road-data refresh. Its SHA-256 is
`1856f4ac7c18435e17d74c7ba24a7b21b3a1231e60449851890dc0109638ded3`.
The MobiData snapshot timestamp is `2026-10-17T22:00:00.013Z`, hash
`cb4c89d3d2b18a06a1d5956b94865310929ff455d7a33005053bccaac66b79c3`.
The source-age limitation remains explicit even though structural readiness
passes. No driving-accuracy or device-deployment claim follows from this gate.

The source artifacts under `mapdata/dist/baden-wuerttemberg-v1.5-roads/` include
full `raw_tags`, directional speed tags and source geometry. The sign-runtime
builder can derive explicit directional/lane structure from them without
guessing direction from sampled geometry.

Reproduce with a Python environment containing the pinned map requirements:

```sh
python3 scripts/map/rebuild_bw_v15_roads.py \
  --input-pbf mapdata/raw/baden-wuerttemberg-260913.osm.pbf \
  --geojson /private/tmp/youspeed-mobidata-bw-20261021-signs.geojson \
  --execute
```

The command prints a plan without `--execute` and refuses to overwrite an
existing generated road DB without `--replace-output`. It runs fresh extraction,
source-manifest generation, detailed way links, paired corridors, original-source
settlement extraction, inventory import and the readiness gate. It performs no
upload or release publication. The optional runtime overlay is built separately
or through `build_spatialite_v3.py --build-traffic-sign-runtime` with the inventory
and decoder dependencies available.

Sixteen focused v3/v4 pipeline tests and sixteen validator tests passed. The new
pipeline fixtures verify that a complete generated road DB passes readiness,
that an invalid runtime request preserves an existing output, and that an
inventory record without a directed OpenLR association cannot become a speed
rule merely because it contains a speed number.
