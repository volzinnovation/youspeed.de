# Normalized Update Metrics

Daily rows normalize each architecture to touched units per 1,000 changed OSM ways. S1 replacement bytes use the first available region manifest as a full-replacement reference; S2 bytes use the median tile-pack size when a v2 catalog is present. S3/S4 validation and decompression timings are measured from checked-in zlib SQL patch samples.

| Arch. | Unit | Days | Median touched/day | Touched/1k changed | Median apply ms/day | Payload MB/day | Payload status |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| S1 | invalidated index partitions | 30 | 6728.0 | 109.550 |  | 915.629 | observed_reference_full_replacement |
| S2 | invalidated tile packs | 30 | 2683.5 | 44.297 |  | 57.239 | estimated_from_reference_tilepack_median |
| S3 | SQL rows touched | 30 | 131253.0 | 2212.378 | 1026.153 |  | sampled_sql_patch_payloads |
| S4 | SQL rows touched | 30 | 177937.5 | 3005.581 | 1358.823 |  | sampled_sql_patch_payloads |

## Karlsruhe Patch Manifest Samples

| Sample | Patch KB | Inflated KB | SHA-256 ms | Inflate ms | Changed ways | Way links |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| delta_base_geom8 | 0.240 | 0.346 | 0.0047 | 0.0092 | 1044 | disabled |
| delta_base_geom8_3d | 50.182 | 356.796 | 0.0187 | 0.5520 | 2558 | disabled |
| delta_waylinks | 0.240 | 0.346 | 0.0012 | 0.0047 | 1044 | enabled |
| delta_waylinks_3d | 63.872 | 569.720 | 0.0230 | 0.7276 | 2558 | enabled |
| delta_waylinks_3d_optimized | 62.037 | 530.597 | 0.0224 | 0.6823 | 2558 | enabled |
