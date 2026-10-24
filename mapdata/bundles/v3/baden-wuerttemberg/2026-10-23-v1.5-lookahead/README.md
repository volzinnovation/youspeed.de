# BW 1.5 upcoming-limit test bundle

Version: **2026-10-23-v1.5-lookahead**. Minimum app version: **1.5**.
Prepared locally on 23 October 2026; no external publication or release catalog
change. Native iPhone and Android validation builds used 1.5 (10059).

Use [baden-wuerttemberg_manifest.json](baden-wuerttemberg_manifest.json) and
`baden-wuerttemberg_speeds.sqlite.gz` together. The manifest retains the ordinary
v3 contract and advertises the optional `upcoming_path.version=1` capability.
The directory includes the existing official 49-pair BW sign-artwork subset,
source/license notices and validation reports.

| Bytes | Size | SHA-256 |
| --- | ---: | --- |
| Gzip transfer | 974,577,648 | `d07ce7bd06481d5ff915206bbbec1d2cd990a607bbc1a0b385cdf8f23b99ed3f` |
| Decoded SQLite | 3,099,021,312 | `34b31aac1dc5a6abacce959afb8ec44043146f5aa4f1ea488c07cb4a68efe09c` |

The materialized database is at
`mapdata/dist-v3/baden-wuerttemberg-v1.5-lookahead/speeds_v3.sqlite` relative to
the repository. The original `baden-wuerttemberg-v1.5-runtime` database remains
unchanged, SHA-256
`e1a36e56cc4809cc69d2d5161b993eff21a1c08264e8d9300e79ec7546ccd00b`.

Topology covers all 1,085,790 admitted ways and contains 4,346,282 directed
segments. There are 284,670 certified continuation decisions; other successors
stop conservatively. Physical signs may be previewed across an ordinary way
split only while the frozen followed relation and directed certificate agree.
Forks, merges, restrictions, uncertain access and conflicting sign applicability
stop prediction. This capability supplies no chosen future turn.

The apps automatically show the nearest lower eligible sign within 300 m and
drop it on passage, relation departure or loss of reliable context. Main limit
resolution and camera/voice precedence keep their existing policy.

Deliver a **full bundle**. Delta creation involving this optional capability is
disabled until every topology and physical-event change can be carried safely.
The source PBF and MobiData snapshots are the existing pinned 1.5 snapshots;
this package does not refresh the underlying source data.

[bundle-verification.json](bundle-verification.json) records full gzip/decoded
hash and original preservation checks. The topology, runtime and structural
reports each pass without errors. [implementation-validation.json](implementation-validation.json)
records native tests and their scope. [checksums.sha256](checksums.sha256)
covers the package files except itself. Initial native performance measurements
used an extracted fixture. Subsequent user-authorized build 10059 installation
and measurements on the full database are recorded separately in
[physical-device-validation.json](physical-device-validation.json). Warm
preview-reader p95 was 3.00 ms on iPhone and 2.29 ms on Android; the reader
boundaries differ. The user's reported missing previews in real drives await
the returned device logs; normal-controller offline replays passed.

See the repository's
[implementation record](../../../../../docs/UPCOMING_SPEED_LIMIT_IMPLEMENTATION.md)
and [topology contract](../../../../spec/upcoming_path_v1.md) for reproduction
and detailed behavior.
