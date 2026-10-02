# Device evidence backup — 1 October 2026

Destination: private [loffenauer/youspeed.de dataset](https://huggingface.co/datasets/loffenauer/youspeed.de).
**Backup verification and local cleanup are complete.** The main batch finished
verification on 1 October 2026 at 23:09 CEST; the build 10029 supplement finished
at 20:37 CEST. In total, 567 remote objects (33,132,707,822 bytes) were verified,
679 original copied paths and all 567 staging objects were removed, and no
changed/out-of-scope sources were retained. Manifests, proof and analysis remain.

Rechecked against the live private dataset on 2 October 2026 at revision
`bd12056313e00acc790d25ebe5486aac11f4cf79`: both manifests match exactly, every
object's size and LFS SHA-256/Git blob identity agree with the backup proof,
and none of the original or staging object paths remain locally. Recheck record:
`/Users/raphaelvolz/YouSpeedDeviceBackups/2026-10-01/status-recheck-2026-10-02.json`.

Snapshots and manifests are outside the repository at
`/Users/raphaelvolz/YouSpeedDeviceBackups/2026-10-01/`.

| Batch | Scope | Manifest | Verification report |
| --- | --- | --- | --- |
| Main | 674 source paths, 562 unique movie/log objects, 33,063,485,566 unique bytes | `upload/device-backups/2026-10-01/manifest.json` | `remote-verification.json` |
| Build 10029 supplement | 5 additional movie/runtime log paths, 69,222,256 bytes | `upload-late/device-backups/2026-10-01-10029/manifest.json` | `late-remote-verification.json` |

The source-to-object mapping preserves original local paths and SHA-256 hashes.
Main cleanup is restricted to copied evidence in `inspector/logs/` and
`android/app/build/reports/`; it excludes source code, reports, labels,
calibration/settings metadata and photos. The supplement contains the newly
copied build 10029 dashcam/runtime evidence, excluding the full preference
plist and review screenshots.

`scripts/device_evidence/verify_hf_backup.py` checks a pinned private dataset
revision, every remote object's size and LFS SHA-256 or Git blob identity, and
an independent download of the exact manifest. It writes proof before deleting
anything. Sources are freshly checked for identical content and stable file
identity before deletion; changed files, symlinks and paths outside the
explicit roots are retained. Verified staging objects are removed afterwards.
A missing object or hash mismatch prevents cleanup. Six isolated checks covered
missing objects, wrong remote hash, changed source, out-of-scope path, symlink
and successful verified removal.

Progress logs: `upload-http.log`, `verification-worker.log`, `upload-late.log`.
When the corresponding verification report has `complete: true`, use its
`revision` and `manifestPath` to restore a specific source from the manifest's
`records[].remotePath`:

```sh
hf download loffenauer/youspeed.de REMOTE_OBJECT_PATH --type dataset \
  --revision PINNED_VERIFIED_REVISION --local-dir RESTORE_DIRECTORY
```

Validate the downloaded SHA-256 against its manifest record before copying it
to a desired local path. Keep manifests and verification reports after cleanup.
Existing analysis documents' historical raw-evidence paths may no longer exist
after successful cleanup; this mapping is their restore index.

## Additional local cleanup — 2 October 2026

Removed one remaining 225,504,768-byte device-log tar archive after its three
member hashes and sizes were checked against the live verified HF objects.
Also removed 20 rebuildable replay Swift compiler caches containing only
compiled modules and timestamps. Additional local content removed:
1,532,216,487 bytes (1.53 GB); this is file-size accounting, not a measurement
of immediate APFS free-space gain. Small restore manifests and verification
records remain. Cleanup proof: `final-disk-cleanup-2026-10-02.json` in the
external backup directory.
