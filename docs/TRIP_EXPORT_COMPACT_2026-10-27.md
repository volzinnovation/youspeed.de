# Compact native Fahrt exports

Both native apps now default to a compact schema-v1 Fahrt ZIP. This fixes the
large repeated diagnostic exports without changing the web importer, recorded
journal facts, capture behavior, counters, encrypted backups or speed-reference
policy.

## Archive behavior

- `journal.json` is the single canonical event representation. Per-kind GPS,
  TSR, sign and gap JSON/CSV/NDJSON copies, `sign_events.ndjson` and
  `media.ndjson` are no longer written. Android also removes its duplicate
  `media-index.json`; `media.json` remains.
- Compact mode omits only `tsr` events whose payload contains a string `message`
  and no keys other than `message` and optional `received_at`. Every other
  event keeps its original ID, time and payload. In particular, structured
  camera/OCR frames with candidates, lineage, restrictions, bounding boxes,
  frame/track IDs and gaps remain.
- Full verbose prose diagnostics are explicitly opt-in. Diagnostic mode retains
  all events once in the same canonical journal. Both ordinary sharing and the
  export-options sheet default to compact; unmasking does not silently opt in.
- Optional `export_profile` and `omitted_verbose_message_events` metadata in the
  journal and manifest describe the result. Measurement units/schema version
  and the pre-existing masked export projection stay unchanged.
- iPhone now writes streaming ZIP DEFLATE for text with system zlib and fast CRC;
  already-compressed media uses STORE. Output is atomically replaced, failure
  leaves no partial export, and ZIP32 limits and paths are checked. Android's
  ZIP compressor remains in use. Media-selection and masked-image processing
  rules are unchanged.
- Small compatibility reports, track formats and checksums remain. A media
  record without `archive_path` is a reference, not image/video bytes.

## Verified large-export projection

A user-provided export contained 841,990,281 bytes across 24 files. Most of it
was the same verbose TSR information in four representations. Its normal
compact projection keeps 30,066 events, including 11,670 structured TSR frames
and 3,818 supplementary-OCR records, and omits 22,656 message-only diagnostic
records. The resulting ZIP is 1,864,664 bytes, with 32,592,966 bytes uncompressed
across 10 entries. All retained event dictionaries match the originals, every
ZIP CRC and recomputed manifest hash passes, and the existing importer accepts
it within unchanged upload/session caps. The supplied original and all of its
manifest hashes remain intact. No user coordinates or event contents are stored
in this repository; the ready-to-use private artifact remains outside it.

The source export has photo metadata but no photo files; the compact copy
cannot manufacture missing images. Users select available originals in the
native export controls when they want them included.

## Validation

- iPhone isolated simulator: TripJournalTests, JournalZIPTests and
  TripStopPromptPolicyTests: 40 tests passed, zero failures.
- Independent Swift/zlib/Python ZIP interoperability checks validate lossless
  text/media roundtrips, UTF-8 paths, CRCs, streaming compression, replacement
  and failure cleanup.
- Android full JVM suite: 886 tests, zero failures/errors, 1 skipped.
  Selection tests exercise the production compact predicate,
  structured/unknown evidence preservation, raw opt-in and unchanged inputs.
  Archive/compression/masking instrumentation tests compile; no attached-device
  installation is performed.
- Xcode test fixtures now preserve the packed-runtime directory instead of
  flattening same-named fixture files into duplicate output paths; project
  regenerated from its existing source specification.

## Attached-device installation

At the user's explicit request, development build **10075** was built and
installed over the existing apps without uninstalling or clearing data:

- iPhone 14 Pro: `de.youspeed.SpeedConsumer`, version **1.6**, build **10075**,
  signed with the existing development configuration. Before launch, the trip
  database and WAL were byte-for-byte identical: **5 trips, 114,789 events**.
  iOS blocked the launch because the device was locked; the update is installed
  and the user can open it after unlocking to complete the manual export test.
- moto g86 5G: `de.youspeed.android.debug`, version **1.6-debug**, build **10075**.
  In-place upgrade preserved **3 trips, 95,664 events**, trip identities and
  settings. The attached-device compact archive test passed using isolated
  synthetic test data, then the real app cold-launched successfully.

Build numbers were supplied as build overrides; release version sources were
not bumped and nothing was published to an app store. Private preservation
copies and device receipts are outside the repository. Existing trips can be
re-exported; their recorded originals are unchanged.
