# YouSpeed best-effort contribution uploads — version 2

Owner decision: 6 October 2026. Speed takes priority over lossless delivery of
ordinary signs and crops. This is the sole upload protocol for the v1.4
development branch. The old receipt/reservation protocol and its routes are
removed; neither client has a fallback. Both mobile platforms behave identically.

## Sending

- Every automatically captured crop is sent under overall sign sharing. There
  is no crop review, separate crop choice, manual entry, or camera-idle/network
  class condition. Camera recognition never waits for uploads.
- One POST contains a crop's metadata and encoded image together. No reservation,
  upload handle, receipt polling, confirmation request, or client media-status
  request follows it. The server links the crop to its observation internally.
- Sightings and corrections are sent in batches of up to 100 events. One
  successful HTTP response completes the whole batch. There are no per-event
  outcomes, response checksums, or replay/content-identity comparisons.
- Any 2xx response means **sent**. It does not promise crash-proof storage,
  replication, analytics import, or credit. An empty 204 response is sufficient.
- Cache capabilities for five minutes. Transfer up to eight crops per worker
  cycle and immediately schedule remaining work. Requests reuse normal HTTPS
  transport; there is no additional acknowledgement protocol.
- An ordinary crop or metadata batch gets at most **three attempts**, including
  the first. Respect Retry-After on temporary failures and resume at that
  deadline rather than the next minute tick. Permanent 4xx failures drop the
  item immediately; 408/429 are temporary. After the third temporary failure,
  discard that item and continue. Loss and duplicates are acceptable.
- Offline queues remain bounded by the existing storage and age limits. Global
  sharing withdrawal/deletion cancels uploads and removes queued private data.
  Permission and deletion controls retain their existing separate lifecycle.

## Routes and framing

| Request | Body | Success |
| --- | --- | --- |
| POST `/youspeed/v1/capture-crops` | Four-byte unsigned big-endian JSON length, UTF-8 crop metadata, then encoded image bytes | Empty 204 |
| POST `/youspeed/v1/capture-sightings` | Existing batch envelope with sighting events | Empty 204 |
| POST `/youspeed/v1/capture-corrections` | Existing batch envelope with correction events | Empty 204 |
| POST `/youspeed/v1/capture-media-status` | Retained status records in the development queue | Empty 204 |

Crop Content-Type is `application/vnd.youspeed.crop`. JSON batches use
`application/json`. No base64 or multipart encoding is required. Envelope JSON
uses existing evidence fields; canonical JSON bytes and the v1 manifest checksum
are not prerequisites for upload acceptance.

Crop metadata is at most 16 KiB; image content is at most 5 MiB. Batches are at
most 512 KiB / 100 events, with bounded event sizes. The server permits 120
capture requests per minute per installation, with existing edge/concurrency,
body-size and storage bounds. Installation labels, epochs, sharing claims and
withdrawal/deletion barriers still associate and control private data.

## Work outside the upload path

The live handler stores image bytes without decoding/re-encoding the image,
checking its declared hash, checking every provenance/geometry field, or
creating an operation receipt. New automatic client capture trusts its own
encoder and does not hash the same image again to validate or insert it.
Image interpretation and archive identity calculation happen in background
processing. Malformed, missing or unusable signs can be discarded there.

The archive/extraction pipelines remain separate from driving and upload.
Map/model downloads, their activation checks and the protected speed-reference
policy are unaffected. Deploy the matching backend before activating these
clients; there are no older supported upload implementations.
