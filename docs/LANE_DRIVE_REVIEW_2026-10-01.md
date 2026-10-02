# Lane drive review — 2026-10-01

**Android follow-up:** The device was later connected and its indexing crash diagnosed. The user clarified that 50 ms is a performance target; the cutoff has now been removed in source on both platforms. See [the follow-up](LANE_ANDROID_CRASH_FIX_2026-10-01.md). The review below describes the earlier installed builds.

The iPhone performance fix is validated on the new drive: only 1 of 4,953 preview evaluations exceeded 50 ms. The remaining problems are dashed-marking fragmentation, restrictive presentation/selection, a saved calibration that does not match the current ego lane, residual tracking resets, and a sustained thermal pause. Two calibrated search bands are a worthwhile experiment, provided they remain soft constraints and are combined with fragment-aware tracking.

The Android phone was not present in two USB inventories during this review. Its newly reported crash and night recordings could not be retrieved. An Android out-of-memory diagnosis would therefore be premature. Only the attached iPhone's new build-10024 session was transferred; it is a daylight recording, not evidence validating the reported night improvement.

## Evidence and integrity

- iPhone 14 Pro, installed version 1.3/build 10024, verified through CoreDevice.
- October 1 session from 10:44:43 CEST. Copied 43,581,956 bytes of TSR/lane diagnostics, 3,539,961 bytes of drive diagnostics, saved calibration preferences and the new dashcam MOV. Device originals retained.
- MOV: **1,831,974,307 bytes**, **562.238 seconds**, 3840×2160, approximately 30 fps. All **16,866 frames** decoded successfully. The 180-degree MOV orientation was honored. SHA-256: `db92ae8297b5ea86753d7c15cff633207755428f65706dff383b99bf4793cfa7`.
- Twenty evenly spaced overview samples and four contiguous 20-second sections were inspected. The selected sections were sampled at 10 Hz, giving **800 frames**, with an 80-second video reconstructing the logged visible overlays.
- Device inventory byte counts match the copies. Hashes are local, not remote cryptographic verification. Recording callback anchors provide approximate video/log alignment, not exact exposure synchronization. The review overlay uses the nearest logged frame within 80 ms; all 800 selected samples matched.

Local evidence: `inspector/logs/2026-10-01-drive-review/`. [Overview contact sheet](../inspector/logs/2026-10-01-drive-review/contact.jpg), [logged overlay video](../inspector/logs/2026-10-01-drive-review/live-overlay-review.mp4), [overlay samples](../inspector/logs/2026-10-01-drive-review/live-overlay-contact.jpg), [calibration comparison](../inspector/logs/2026-10-01-drive-review/calibration-contact.jpg).

## What changed on the actual iPhone

| Measurement | New build 10024 |
| --- | ---: |
| Preview budget failures | 1 / 4,953 = **0.0202%** |
| Preparation median / p95 | **3.18 / 9.50 ms** |
| Frames with raw candidates | 4,736 = **95.62%** |
| Frames with any selected visible border | 3,071 = **62.00%** |
| Frames with two selected borders | 75 = **1.51%** |
| Confirmed tracks but no selected visible border | **499 frames** |
| `scope_or_geometry` resets | **67** |
| Motion-projection eligibility | 4,257 = **85.95%** |

These are output-availability metrics, not lane-detection accuracy or recall: raw candidates include distractors, some scenes legitimately lack markings, and some borders are occluded. The earlier failure had 744/744 budget failures. This establishes that optimization fixed the dominant preparation failure; it does not establish that every selected line is correct.

The sole new budget failure, about 121.7 seconds into the video, includes 73.23 ms waiting in the queue and 77.03 ms total preparation. It was not a sustained filter bottleneck.

Thermal protection pauses lane analysis at approximately **495.35 seconds (8:15)** and remains reported during the final **67 seconds** of recording. Logs cannot identify the heat contribution of 4K capture, TSR, preview, screen and ambient conditions individually. Keep thermal protection; measure the combined workload before changing recording quality.

See the [full log audit](LANE_IPHONE_LOG_AUDIT_2026-10-01.md) for timing, scope-reset and thermal qualifications.

## What the dashcam shows

At 110–130 seconds, the right solid border is repeatedly rendered while a clearly painted dashed left border is mostly absent. At 230–250 seconds, interruptions in the right marking coincide with much weaker output. Road edges/grass or other non-marking structure can also attract the overlay in this section; simply retaining the strongest response can select the wrong structure. The motorway section with a long continuous right stripe is substantially more stable. Truck occlusion and fragmented left paint are present in the final selected section.

| Video interval | Scene | Frames with any selected border | Frames with two |
| --- | --- | ---: | ---: |
| 110–130 s | Dashed left, solid right | 151 / 200 | 12 / 200 |
| 230–250 s | Interrupted border markings | 58 / 200 | 0 / 200 |
| 340–360 s | Motorway merge, continuous right stripe | 194 / 200 | 0 / 200 |
| 430–450 s | Trucks and intermittent occlusion | 156 / 200 | 0 / 200 |

This is a descriptive sample, not a controlled solid-versus-dashed accuracy experiment; scene, curve, vehicle occlusion and calibration differ. It nevertheless supports the reported dashed-line weakness.

The same 800 decoded images were replayed through frozen production Swift sources with optimized compilation: 0 budget failures, raw candidates on 799 frames and selected output on 457. This replay omits GPS and calibration, uses decoded grayscale rather than original sensor luma, and resets at each selected section. It is an image-pipeline baseline, not a faithful reproduction of live counts or a device-speed benchmark. Source/input hashes, per-frame results and metadata are in `replay-baseline/`.

## Why dashed lines fail

The production detector stops a fragment after a four-scan-row gap, requires at least eight observations and sufficient vertical span, and multiplies confidence by the density of occupied rows. Later gates require overlap and crossing a fixed lower-image row. These rules favor continuous paint. A dash gap is being treated partly as lost evidence of the whole boundary.

A frozen-source synthetic probe confirms the mechanism with unchanged image size, contrast and two-border geometry:

| Paint / blank scan-row pattern | Raw boundaries |
| --- | ---: |
| Solid | 2 |
| Six painted, three blank | 2 |
| Six painted, four blank | 0 |
| Eight painted, four blank | 0 |
| Ten painted, four blank | 4 separate fragments |

Scan-row counts are detector sampling units, not physical dash lengths. This isolates an algorithmic failure mode; it does not attribute every missed dash in the drive to one threshold. Probe fixtures, source hashes, executable and results are preserved in `dash-probe/`.

Research supports fitting one boundary to separated compatible fragments and tracking its geometry through time. For example, [Aly's lane-marker method](https://arxiv.org/abs/1411.7113) combines stripe responses with robust line/Bézier fitting. Our proposed adaptation is to preserve observed paint intervals, group fragments by geometry and stripe consistency, and keep confidence in the fitted boundary separate from how much of it is painted. See [the primary-source research review](LANE_DASHED_LINE_RESEARCH_2026-10-01.md) for temporal methods, mobile constraints and false-positive risks.

## Calibration and the proposed two zones

The app already displays at most one selected border per side. The new benefit would be splitting the search and hypothesis budget before association, so strong candidates on one side cannot consume the whole candidate limit.

However, the current compatible saved profile puts the selector center at **x=0.2838 at y=0.78**. The calibration comparison at 121.3, 353.8 and 440.9 seconds shows that the saved left guide points into the neighboring lane/left roadside, while the right guide runs inside the ego lane. The computed divider is near or left of the actual dashed left border, rather than centered between the ego borders. A true left border can therefore fall into the selector's center rejection strip or compete in its right-side pool. This is a confirmed mismatch in the reviewed images; its exact contribution requires a controlled selection ablation. Do not replace it blindly with image center, which is also not reliable on bends or off-center mounts.

Use **two flexible, row-dependent search bands**, initialized from plausible compatible calibration and updated from visual evidence and vehicle-motion prediction. Widen and reacquire after uncertainty or loss. Keep limited broad search and multiple internal hypotheses at merges, while rendering zero or one accepted boundary per side. A rigid vertical split or tight static crop would turn calibration errors and bends into guaranteed misses. Both bands should share the existing small luma/filter buffers.

## Night and Android limitations

The reported better night behavior is plausible: retroreflective paint can have strong contrast under headlights, as described by [FHWA's pavement-marking review](https://www.fhwa.dot.gov/hfl/partnerships/all_weather_pavement/hif13004/chap01.cfm). This is a mechanism consistent with the observation, not a measured conclusion from the transferred daylight clip. Wet glare, headlights, studs and guardrails remain useful negative controls. Avoid broad brightness-threshold changes until matched night recordings are available.

For Android, source review found avoidable full-resolution TSR bitmap intermediates and UI-result retention opportunities. The small bounded lane buffers alone do not establish an OOM cause. Historical memory snapshots are from older successful tests and cannot diagnose this incident. Retrieve package/build, `ApplicationExitInfo`, crash/all log buffers and recording logs before modifying or reinstalling Android. See the [Android memory review](LANE_ANDROID_MEMORY_REVIEW_2026-10-01.md).

## Recommended implementation order

1. **Capture/classify the Android exit when connected**, and add next-start exit diagnostics plus memory/queue measurements. In parallel, measure the iPhone's sustained combined thermal workload.
2. **Add stage rejection and calibration-generation diagnostics**, including reset component, current intrinsics, chosen side and rejection reason. Validate or correct the saved guides against the current mount and visible ego borders; downgrade inconsistent guides to a weak prior.
3. **Run two-band and fragment-grouping ablations offline**, keeping brightness thresholds fixed: baseline, bands only, fragments only, then both. Preserve painted support intervals, allow geometrically consistent gaps, and remove the assumption that every valid border has paint at one fixed lower row. Include arrows, merges, unmarked roads and guardrails as negative cases.
4. **Track a boundary model and its painted fragments separately** using speed/calibration uncertainty. Match actual paint/endpoints across exposures; cap missing-evidence age and avoid drawing predictions as newly detected paint. Retain one accepted border per side.
5. **Validate both clients on held-out day/night clips and sustained devices**: manually labelled border correctness, unsupported visible duration, identity changes, jitter, reacquisition, p95 latency, peak memory, thermal pause time. Preserve Swift/Kotlin parity and shared policy.

No production code, device settings or deployment was changed in this review.
