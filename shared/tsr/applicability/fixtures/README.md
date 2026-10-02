# Recorded France exit failures, 28 September 2026

`fr-exit-failures-20260928-v1.json` contains 263 original Android candidate
batches in four independently replayed clips. These are retained field inputs,
not generated test vectors. Batches, candidate identities, road context and
timestamps are unchanged; each clip has five seconds of pre-roll. Empty frames
and classifier flicker are retained. No missing frame or road update is invented.

The corpus is intentionally `unreviewed_real`, with no expected applicability
class. The log review and nearby stills locate suspected errors, but do not
constitute independently verified ground truth for every candidate or track.

The companion `.manifest.json` records exact selection bounds, source hashes,
per-batch hashes, nearby still capture identities and hashes, and original
manual-dismissal/speed-reference log events. Image bytes remain in the ignored
local evidence directory. The still captures differ from the live analysis
frames; they must not be treated as exact annotation overlays. Authority events
are historical observations, not inputs to this applicability-only replay.

The clips retain these failure mechanisms:

| Clip | Characterization |
| --- | --- |
| `clip-141810` | Qualified 70 appears left of image x=0.60 despite fresh road context and a linked exit branch. |
| `clip-143435` | Service-area 30 beside motorway 130, stale context, missing branch, and recorded 90→70→50→30 observations within 8.261 seconds. Earlier 30/90 classification flicker is retained. |
| `clip-154245` | Qualified 70 with a 5.027-second-old snapshot and no recorded branch. |
| `clip-160920` | Camera → manual dismissal → bundle → new camera claim 3.074869 seconds later; later 110 observations remain as a recovery control. |

The `.baseline.json` freezes the actual Swift/Kotlin replay result at the recorded
source/configuration hashes. Native parity passed. All 311 track decisions were
UNKNOWN, including 66 stale-context and eight missing-calibration decisions.
There was no explicit exit/access-road rejection. **This does not mean the signs
were suppressed:** general applicability runs in shadow mode and this replay does
not execute downstream recognition fusion, immediate authority, passage,
resolver, dismissal or speed-reference processing.

Ordinary tests validate the corpus and historical characterization without
compiling native code:

```sh
python3 -m pytest tests/tsr/test_fr_exit_failure_replay.py -q
```

To compile and run the real native implementations, then verify the generated
results against this frozen baseline:

```sh
SWIFT_MODULECACHE_PATH=/tmp/youspeed-tsr-replay-modulecache CLANG_MODULE_CACHE_PATH=/tmp/youspeed-tsr-replay-clangcache python3 scripts/tsr/applicability/replay.py --vectors shared/tsr/applicability/fixtures/fr-exit-failures-20260928-v1.json --output /tmp/youspeed-fr-exit-replay
YOUSPEED_FR_EXIT_REPLAY_OUTPUT=/tmp/youspeed-fr-exit-replay python3 -m pytest tests/tsr/test_fr_exit_failure_replay.py -q
```

The optional native-baseline comparison deliberately requires the recorded source
hashes. A later proposed filter should be evaluated as a separate experiment
against these retained inputs and reviewed positives; it must not overwrite this
historical baseline or interpret UNKNOWN as successful exclusion. These four
clips alone do not establish false-positive/false-negative rates, complete
displayed-limit behavior, or device performance.

## Additional Swiss junction challenger

[`panoramax-swiss-junction-v1/`](panoramax-swiss-junction-v1/README.md) adds the
user-labeled Le Vaud still: a left-street 30 and a through-road 50 simultaneously
visible on an unmarked junction. It has its own provenance, conservative
reviewed-geometry report and explicit oracle decision-wiring regressions. It
does not alter the frozen France baseline or claim automatic lane recognition.
