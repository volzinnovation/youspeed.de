# YouSpeed 1.4 app integration

Branch: `codex/youspeed-v1.4-app-foundations`. The sibling backend owns the API and wire contract.

Both apps connect ordinary camera detections and every captured crop to the automatic sign-sharing outbox and deployed API. Camera recognition continues while consent is declined, the network is unavailable, an upload is paused, or deletion is pending. There is no synthetic observation producer, pilot screen, synthetic build setting or release switch in either app. Synthetic integration requests exist only in the separate computer-run suite.

## Backend alignment

The source contract was exported from `Woladen.de-analytics`, branch `codex/youspeed-backend-services`, commit `bae998285660e4e1beb113a24a200bdbe58937b1`. All 18 listed schema/fixture files retain the exact sibling bytes and manifest SHA-256:

```text
820aa65f8999a4af54a40435363161279ee56ebf880c6e83dfa5d4c0103e2c96
```

The deployed runtime advertised by the handoff is `c329bee419702704554ab7ee7634889c74a7186a`; the sibling checkout was rechecked at `a686124159b2896fc53f2553101dcb739240e28f`. The contract remains provisional (`cross_client_approved: false`). Native byte validation permits transport; every upload run additionally checks deployed capabilities and the event's explicit authorization. Contract success alone never grants collection consent.

- API: `https://live-eu.woladen.de/youspeed/v1`, configurable through the HTTP client constructor.
- Metadata disclosure: `youspeed-camera-use-pilot-1`.
- Automatic crop wire authorization (covered by sign sharing, no separate user prompt): `youspeed-crop-storage-pilot-1`.
- Limits: 100 events, 512 KiB/batch, **16 KiB/event** in canonical UTF-8 JSON. Both constants are compared against sibling `spool.Limits` by the checker.
- Anonymous HTTPS, identity content encoding, no installation credential, no redirect forwarding, no payload/receipt/location diagnostic logging.

`enforcement_enabled` controls future payment/contribution enforcement. `external_processor_enabled` controls forwarding optional crops to an external AI service. Neither flag governs camera recognition or metadata delivery. Their currently disabled state does not prevent metadata uploads. Optional crop capabilities likewise do not gate metadata.

## App behavior

| Area | iPhone and Android |
| --- | --- |
| Identity | Generate one lowercase UUIDv4 at first launch, independently of consent. Persist UUID and epoch in SQLite; deletion preserves UUID. Missing/corrupt lifecycle data fails rather than rotating identity. No account, hardware identifier, registration or device key. |
| Consent | Contribution preference defaults on, but uploading camera observations requires an affirmative camera-use decision. The unchecked “Don't ask again” checkbox remembers neither answer; checked acceptance/refusal persists. Prompt once per logical camera session, preserving that session through interruption/resume. Closing the prompt grants nothing. An explicit Off action withdraws permission and purges pending private data. |
| Camera | Collection receives all eligible raw classes before numeric speed applicability/dismissal filtering. It uses independent collection tracks and does not modify the protected speed-reference policy. Existing explicit TSR choices are preserved. |
| Sightings | Two distinct analyzed frames spanning at least 100 ms qualify one immutable sighting. Continued frames suppress duplicates until 2 s without support. A successful SQLite commit precedes marking a track recorded. Multiple signs have separate IDs. Bounding-box tracking is approximate; server aggregation must not treat these local track IDs as permanent physical sign identities. |
| Provenance | Actual raw class/model scores, component artifacts/preprocessing/calibration IDs, manifest byte hash, frame times and nearest real location fix. Vehicle position remains distinct from sign position. Missing GPS, unverified clock and manifest schema-version provenance are explicit. The pack has no separate release-version field, so `pack_version` records `manifest-schema-<revision>` with the `manifest_schema_version` quality flag. Unknown OSM mapping/calibration hashes and calibrated confidence remain null. |
| Manual entry | Removed from both apps. Ordinary camera detections create observations and photos automatically; the legacy wire fixture remains for compatibility only. |
| Corrections | Existing touch dismissal and Wrong/Falsch listening for a presented numeric camera sign append `unspecified_wrong` corrections when uniquely associated with a collected observation. The target is frozen when speech starts, not reassigned at transcript delivery. Ambiguous/unassociated commands still work locally and do not manufacture server targets. General non-numeric speech windows remain future work. |
| Queue | SQLite WAL/FULL transactions, immutable IDs/epochs/captured authorization, 20,000 ordinary events/50 MiB and 1,000 corrections/5 MiB reserved separately. Thirty-day expiry, bounded crop storage and explicit capacity errors. Storage work runs separately from camera/UI and network workers. |
| Delivery | Automatic one-way upload whenever internet is available, including active camera use and metered/mobile connections. Consent, contribution-off, privacy changes and deletion barriers still govern ordinary delivery. Foreground startup/network changes plus a 60 s timer resume delivery. Successful transfers schedule another cycle to drain the backlog. There are no synchronization or user-triggered send controls. Interrupted requests retain the same saved body and batch identity. |
| HTTP outcomes | Per-event accepted/duplicate/rejected/retry-later handling; 413 creates new batch IDs while preserving events/claims/epoch; 429/408/5xx honor Retry-After with jitter; 409 deletion-pending defers ordinary work while privacy polling continues; conflicts/permanent errors/410 quarantine safely without relabeling epochs. Non-JSON error replies retain HTTP retry/split semantics. |
| Withdrawal/deletion | Cancel stale transport work, stop new collection locally, purge relevant pending data transactionally and retain privacy controls. Ordinary delivery cannot resume ahead of a privacy transaction. Failed privacy storage changes keep ordinary contribution delivery paused. |
| Receipts | Intake is not completion. Persist opaque receipts and POST them in an operation-status JSON body. Poll the active deletion barrier first; old unsent consent cannot starve it. Fairly poll historical archive/backup operations. Processor withdrawal terminal state is `processing_stop_applied`, never `processing_stopped`. |
| Deletion UI | “Delete my observations” reports active removal, archive purging and backup expiry separately, including earlier requests. Advance epoch once after active removal; old snapshots never advance it again or clear a newer barrier. Require a fresh camera-use decision for new collection. |
| Developer controls | “Clear pending observations” appears only in diagnostics and retains withdrawal/deletion operations. |
| Crops | Every captured crop is sent as part of automatic sign sharing. No separate crop toggle or consent prompt. The backend crop claim is recorded from the overall sharing decision. Keep the exact analyzed upright frame, outward-round bounds, add the original height below and clip without padding. Freshly encode an opaque metadata-free PNG. Runtime source hash is null with an exact local frame token; encoded bytes remain SHA-256 verified. |
| Automatic crops | New captures enter the upload queue directly. Upgrade migrates the former review queue transactionally using captured grants. `privacy_preflight: passed` and `redaction_version: metadata-strip-1` describe automatic file/metadata validation; neither user review nor face/plate redaction is asserted. The product owner explicitly removed review on 5 October. Session end/restart preserves captured grants; withdrawal/deletion still purges pending bytes. |
| Crop transport | Reserve with immutable metadata, persist the scoped handle/receipt, PUT exact bytes, and erase local bytes only after a validated `media_durable` receipt. Identical reservation replay recovers lost content ACKs and refreshes expired handles. Append linked/missing/expired media status under the captured metadata grant. Optional image retry backoff is persisted separately, so it cannot pause metadata or privacy controls. |
| Crop limits | 5 MiB encoded image, 16 MP decoded crop, 1 GiB queued image storage, seven-day local expiry, at most four crops from one processed representative frame and one media transfer per worker cycle. Frame ownership is bounded; camera work never waits for generation, storage or delivery. Backend media retention is separately advertised as 30 days. |
| Panoramax capture filter | “Capture recognized traffic signs only” defaults off. When on, suspend distance/time stills; all admitted classes qualify after two frames spanning 100 ms, independently from speed applicability and private contribution permission. Deduplicate by encounter, keep separate boxes for multiple same-class signs, enforce a global two-second minimum and require foreground/movement/fresh accurate GPS. Missing TSR waits instead of falling back to cadence. Capture reason, recognition frame ID/time, labels, boxes and scores persist in the sidecar. |
| Panoramax gallery filter | “Show traffic-sign captures only” filters originals with explicit sign-capture evidence or existing sign annotations. It displays the active filter and preserves hidden selections, exclusions, favorites and batch approval. Clearing the filter restores all originals. Legacy files acquire no invented evidence. Existing Panoramax account and post-drive upload approval remain separate from private sign sharing. |

Session prompt/claim state is in memory for the active camera lifecycle; finalized events persist their collection session UUID and captured claim. Process termination ends that camera session. Restart recovers its immutable queued requests, controls and receipts, while a newly opened camera session obtains a new session decision unless remembered.

## Handoff acceptance and remaining release work

The handoff's identity, explicit local claims, durable sightings/corrections, metadata upload/replay, withdrawal and deletion-barrier integration are connected. Both native clients use the pinned fixtures; the desktop suite additionally checks backup-image recovery, preserved UUID/epoch/body and deleted-epoch quarantine. Local contribution storage is excluded from normal cloud backups.

The live host-only smoke verified native HTTPS capabilities, one fresh synthetic manual observation, durable intake and exact replay. It submitted deletion and persisted the receipt. A later host-only receipt poll confirmed **active removal and advancement to epoch 1**; archive purging and backup expiry remain pending. This client smoke does not independently confirm signed import into volz-db or completed server recovery/backup acceptance. The sibling handoff reports separate operator acceptance; keep the two evidence sources distinct.

The user's instruction supersedes putting synthetic/release gates in the ordinary device camera path. Consent and deletion remain mandatory client behavior. Physical-device deployment is recorded below. No code was committed, pushed, merged or changed in the sibling repository.

Remaining v1.4 release features: general non-numeric correction windows; restriction-enabled bundle consumption when the backend contract exists. External extraction and payment/contribution enforcement require separate backend/product acceptance. This branch does not claim App Store policy approval or enable payment enforcement.

## Computer-run verification

```sh
scripts/tsr/collection/run_swift_checks.sh /private/tmp/youspeed-collection-results
cd android
./gradlew --offline :app:testDebugUnitTest \
  --tests de.youspeed.android.alpha.SignCollectionContractTests \
  --tests de.youspeed.android.alpha.SignCaptureFilterTests \
  --tests de.youspeed.android.alpha.PanoramaxCaptureTests :app:assembleDebug
cd ..
python3 scripts/tsr/collection/check_contracts.py \
  --backend ../Woladen.de-analytics \
  --native-output /private/tmp/youspeed-collection-results
```

Explicit live smoke, confined to the computer suite:

```sh
scripts/tsr/collection/run_swift_checks.sh /private/tmp/youspeed-collection-results --live
```

Resume existing host deletion receipts without generating more observations:

```sh
scripts/tsr/collection/run_swift_checks.sh /private/tmp/youspeed-collection-results --resume-live
```

The live suite generates a fresh synthetic installation/session/event plus one solid-color pixel crop, commits and replays the immutable metadata and crop reservation, checks linked media status, then requests deletion. Receipts stay in the host-only SQLite directory so incomplete deletion can be recovered; the suite never erases those pending control records. Do not delete that test directory until server cleanup completes. No synthetic generator is included in app targets.

Validation on 2026-10-05: Swift host contract/store/crop/transport/observer checks; Android desktop contract/observer/capability tests and app build; iPhone simulator build and five focused foundation tests; sibling schema/Pydantic/semantic/pixel comparisons. Prior simulator/emulator SQLite and native pixel tests also cover 16,384-byte acceptance/16,385-byte rejection and recovery of separate deletion phases. Follow-up compilation covers the final metadata and privacy-ordering changes.


## Earlier optional crop and Panoramax acceptance (5 October 2026)

The separate crop opt-in and review behavior recorded here was superseded later
that day by the owner's automatic-all-crops instruction. See
[MOBILE_PERFORMANCE_UPLOAD_REVIEW_2026-10-05.md](MOBILE_PERFORMANCE_UPLOAD_REVIEW_2026-10-05.md).

Desktop Swift tests cover local review across session end/restart, recovery from a copied SQLite image, lost PUT response recovery without a second content transfer, separate crop backoff, linked/expired status and withdrawal. Both native crop implementations still pass the exact shared geometry/RGB hash fixtures. The iPhone simulator runs five focused foundation tests; the standalone Android emulator runs five native SQLite/pixel/transport/privacy tests. Focused Android unit suites cover the capture filter, sidecar roundtrip and existing recognition/passage behavior.

The separate live computer smoke passed deployed capabilities, synthetic metadata plus a one-pixel PNG, linked media status, exact metadata replay and durable crop reservation replay. It requested deletion and retained the receipt in `/private/tmp/youspeed-crop-results/live-host-*`. A later receipt-only poll confirmed active removal and advancement to epoch 1; archive purging and backup completion remain pending. The earlier metadata-only smoke's active removal remains separate evidence. The live smoke used no physical-device synthetic producer, backend modification or external LLM call.

Crop generation uses the first qualifying encounter frame; it does not retain an ongoing image stream or claim automatic privacy redaction. Sign-only Panoramax stills retain recognition evidence from their trigger frame; this does not assert that those normalized boxes locate pixels in the later still. Private crops always use their exact analyzed source. On-road framing and photographic quality still need ordinary device acceptance.

## Physical-device deployment (5 October 2026)

Version 1.4, build 10036, was installed as an update on the attached iPhone 14 Pro (`de.youspeed.SpeedConsumer`, signed Debug) and Moto g86 5G (`de.youspeed.android.debug`, 1.4-debug). Both device inventories confirmed the final version/build, both launch commands succeeded, and the ordinary dashboards were observed. The iPhone screen was viewed through QuickTime's preview without recording. Installation retained the existing app containers; no uninstall, app-data reset or synthetic device test was performed.

Metadata and optional crop disclosures use “our servers” / “unsere Server” in both clients. The crop disclosure omits the requested expansion, sensitive-image and post-drive discard sentences in both languages. Swift/Kotlin copy equality was checked. Android's disclosure text scrolls within its dialog while the unchecked “Don't ask again” choice has a separate row, addressing the clipped label found during the initial landscape inspection.

On the Moto g86, the contribution and optional crop controls and shortened crop disclosure were observed in Settings; the sign-only gallery filter was visible. The existing Panoramax capture preference was off, so its dependent capture filter stayed hidden and that preference was preserved. Capture quality during a drive remains a separate acceptance check. Both native builds passed, and the shared checker still matched the sibling's 18 pinned files and 16 KiB event limit.

Build, install, launch, device UI inspection and artifact hashes are retained under `/private/tmp/youspeed-v14-device-deploy-20261005/`, including `deployment.json`. The final APK SHA-256 is `60ed0a9a0d68a5510e0a91c232fb34c0cd8efa038e39b9092fd459e47775d31b`; the signed iPhone executable SHA-256 is `7e48776a0da0ac27c3f517f52f15da4af92d84d42b06995349a245e27bc4733f`. Version/build overrides were supplied to the build commands; release 1.3 source defaults remain unchanged.


## Upload scheduling correction (5 October 2026)

Both clients now automatically deliver authorized observations whenever internet
is available, including mobile/metered connections and active camera use. The
product owner explicitly removed the camera-idle and unmetered-network gates.
Contribution-off, pending privacy changes, consent, deletion barriers, retries
and explicit crop review remain enforced. The settings explanation matches on
both platforms.

The attached Moto's build 10036 retained 67 pending sightings and four unreviewed
crops. Its metadata and crop grants had durable server consent receipts, but no
metadata batch had been created. Android reported the iPhone hotspot as metered
and the camera remained active, explaining why the old ordinary upload path
never sent those observations.

Separately, the installed Baden-Württemberg map passed its exact manifest
SHA-256 check. Its legacy schema has no ordinary spatial tile index. In the
second run, 106 of 107 logged discarded lookups exceeded the six-second road
context limit, with median probe time 4.08 seconds and selected query time
2.24 seconds. Camera delivery and the GPU startup reference were healthy, but
missing fresh road context prevented almost all live inference. This map lookup
performance issue is diagnosed and is not repaired by the upload change.

Validation: Android unit tests and builds, five emulator SQLite/crop/transport
tests, the Swift host contract/transport/recovery suite, and an iPhone simulator
build passed. Physical-device deployment uses version 1.4 build 10037.
