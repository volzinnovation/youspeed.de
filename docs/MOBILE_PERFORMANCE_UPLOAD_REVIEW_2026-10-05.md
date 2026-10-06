# Mobile performance and upload review — 5–6 October 2026

## Findings from both attached phones

Read-only snapshots were taken before updating the apps. No drive logs, photos,
map bundles or contribution queues were cleared. Raw evidence remains outside
Git in `/private/tmp/youspeed-followup-20261005/`.

| Before fixes | Android build 10037 | iPhone build 10037 |
| --- | --- | --- |
| Accepted real sightings, durable server receipts | 78 | 228 |
| Pending metadata events | 0 | 0 |
| Uploaded private crops | 0 | 0 |
| Captured crops held by local review | 15 / 283,764 bytes | 228 / 10,313,520 bytes |

Every retained crop matched its recorded encoded SHA-256 and byte length.
Both metadata stores held `live_eu_committed` receipts. Their receipt bodies
advertised `analytics_state: pending_archive`: live intake is confirmed; later
analytics/archive import is not established by those receipts.

### Android map regression

The reported stale state concerns the **age of the GPS match**, not the age of
legal rules or the downloaded bundle. The installed Baden-Württemberg map is
legacy schema 1 (2026-07-04). Its spatial index is present, but the attached
phone reports **no `ENABLE_RTREE`** in platform SQLite. The existing fallback
scanned the million-way table repeatedly for networks and accuracy windows.

The last discarded lookup at 16:51:23 UTC recorded 8,137.9 ms of overlapping
bundle probes and an 8,575 ms matched-fix age. The latest GPS fix was only
579 ms old. Its rejection was `matched_fix_stale`, before a selected query.
Consequently, the camera continued delivering frames while almost no new
recognition inference was admitted for that run's unusable road context.

Git identifies the relevant change as **fce6a0c, 3 October**: bundle selection
began comparing full-radius geographic feature counts. Android added broader
candidate queries for those counts; iPhone added a separate feature-count query
after each route probe. This exposed the expensive Android legacy fallback.
The six-second freshness limit already existed before this commit and did not
change. The earlier Play 1.3 artifact used **a067abb7**; the newer GitHub 1.3
release used fce6a0c. The shared version label does not identify identical code.
See `docs/release/BUILD_10033_ARTIFACTS_2026-10-03.json` and the 4 October audit.

Android inference on 5 October: 3,359 samples, median **311.1 ms**, p95
**434.8 ms**, median frame conversion **28.5 ms**. Earlier 27 September evidence
reported 294 / 400 ms. Those drives used different conditions and model/input
configurations; this comparison cannot establish an isolated model regression.
The multi-second map starvation is much larger than that timing difference.

### iPhone findings

The 16:52–19:43 UTC run continued recognizing signs. Its match log contains
8,739 results: query median **11.3 ms**, p95 **18.7 ms**, maximum **100.4 ms**.
The earlier 13:31 run's 1,455 queries had median **34.8 ms** and p95 **42.6 ms**.
The corresponding sampled recognition latencies were 51.0 / 74.9 ms and
73.6 / 93.5 ms. These samples do not support the same map starvation on iPhone.
They also exclude some collection/storage/UI overhead and do not establish a
complete end-to-end comparison with v1.3.

The new crop implementation unnecessarily converted and hashed whole upright
frames (up to 3840 × 2160) in utility storage work. Both coordinators refreshed
consent, expiry and deletion state after every analyzed frame, even without a
new sighting. These are identifiable v1.4 additions removed from routine work.
A new live drive is still needed to measure their user-visible impact.

## Implemented behavior

- Every automatically captured sign crop accompanies sign sharing. There is no
  separate crop toggle, crop consent prompt, user review or manual sighting entry.
- The backend's existing crop authorization scope is recorded from the overall
  sharing decision. Global sharing withdrawal and deletion remain effective.
- New crops enter the durable upload queue directly. Upgrade migrates existing
  review rows transactionally with their original capture grants and timestamps.
- Automatic file preflight uses `passed` / `metadata-strip-1`; it never claims
  user review or face/plate redaction. The pinned wire contract is unchanged.
- Runtime crops omit the optional full-frame pixel hash and retain the exact
  frame token. Encoded SHA-256, dimensions, geometry and metadata-free PNG
  validation remain. Full source hashing remains available for golden fixtures.
- Android reads existing immutable two-dimensional R-tree shadow nodes when
  the SQLite module is unavailable. Candidate bounds, network filtering,
  deterministic ordering, limits and matcher behavior remain in SQL. The reader
  is bounded and falls back to the previous SQL path on malformed/unsupported
  index data. Neither bundles nor the protected speed-reference policy change.
- Successful uploads schedule another cycle instead of waiting one minute for
  each crop; failures retain durable backoff and privacy controls retain priority.

## Verification and deployment

**647 Android unit tests passed**, including 128 differential windows over
4,096 entries generated by real SQLite R-tree queries, plus corruption fallback.
**11 native tests passed on the attached Moto**, covering SQLite lifecycle,
crop migration/transport/privacy, route feature-count parity and the installed
legacy map. Swift host contract/store/crop/transport recovery checks passed;
the signed iPhone app built successfully. Shared validation confirmed all
18 pinned files, backend Pydantic/canonicalization, numeric parity and PNG bytes.

The attached Android installed-map benchmark verifies production actually reads
the index: **11 cached node reads**. At the stalled coordinate, warm road probe
**21.4 ms** plus selected lookup **131.4–132.1 ms**; cold values **84.5 / 159.4 ms**.
This benchmark covers one installed pack, not the complete two-pack live route
selection or a fresh driving session. Exact overlap candidates also matched a
read-only scan of the installed map's way bounds.

Android **1.4 (10038)** is installed. A second on-device acceptance run exercised
the actual upload worker with the existing real backlog: **all 15 crops received
`media_durable` / `live_eu_committed` receipts**, all 15 linked status records were
accepted, and pending events/review rows/crop bytes are now zero. No synthetic
server observations were created. The app was relaunched after acceptance.

The iPhone **1.4 (10038)** was installed and launched on 6 October after the
device was unlocked; Apple's installed-app inventory confirms the version.
The update preserved all 228 crops and migrated every review row automatically.
The first post-launch snapshot confirms **4 `media_durable` /
`live_eu_committed` receipts**, with **224 crops still queued** and no pending
metadata events. Upload is progressing through the app's automatic worker;
this snapshot does not claim that the full iPhone backlog has completed.
Earlier deployment attempts had failed with
`kAMDMobileImageMounterDeviceLocked`; the paired installation-service fallback
had also failed before the successful CoreDevice installation.
