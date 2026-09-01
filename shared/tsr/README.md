# YouSpeed traffic-sign recognition contracts

This directory defines the portable boundary between the YouSpeed training and
release pipeline and the iOS/Android runtimes. Model binaries do not belong in
the normal source tree. A released country pack is a directory containing a
`manifest.json` plus the explicitly listed artifacts.

The runtime rules are deliberately strict:

- National model labels are mapped to `tsr-semantic-v1`; app logic never
  switches on a German training class ID.
- Every mobile artifact identifies the pinned source checkpoint, exporter,
  preprocessing and output contracts, calibration input, parity result, and
  SHA-256.
- Live frames, rear-camera stills, and imported diagnostic fixtures emit the
  same `recognition-event-v1` structure.
- Every live provisional/confirmed event carries the way ID, coordinate,
  heading, travel direction, and OSM/local source signature captured with the
  frame. An asynchronous result is rejected for runtime override if that
  signature is no longer current.
- A confirmed numeric result is a transient source with precedence
  `TSR > local correction > bundled OSM`. It never mutates the lower layers,
  survives repeated fixes with the same source signature, and is cleared by a
  newer detection or genuinely new OSM/local information.
- Primary signs and white supplementary plates are separate objects linked by
  an assembly ID. `resolving`/`unresolved` plate state must not be collapsed
  into an unconditional permanent speed correction.
- Bounding boxes use the fully orientation-normalized image, top-left origin,
  and normalized `[0, 1]` coordinates.
- `raw_score` is never presented as probability. `calibrated_confidence` is
  present only when the pack declares a passing calibration.
- Ordinary inference events contain no pixels or image path. Diagnostic image
  retention is a separate consented feature and storage root.
- Downloaded packs require a trusted signature in addition to per-artifact
  hashes. Bundled/developer packs may be admitted by a separate explicit trust
  policy, but are still hash checked.

`fixtures/de-direct-pack-v1.json` and `fixtures/recognition-events-v1.json` are
contract fixtures, not release manifests or benchmark ground truth. Their hash
values are intentionally synthetic and no model artifact is implied.

`diagnostic-bundle.schema.json` defines the separate, consented image round
trip. Ordinary inference never writes frames into that storage root. The
dataset builder verifies consent, redaction state, asset hashes, road context,
assembly links, and group-safe train/validation/test splitting before materializing
anything for training.
