# Visual calibration and lane continuity, 2026-09-30

The new reference frame and temporal lane processing are native Kotlin and Swift. TSR keeps its existing models, thresholds, classification, temporal fusion, admission and delivery semantics. Its only input change is the saved calibration's horizontal crop. The speed-limit reference policy is unchanged. Lane/path evidence remains a diagnostic sidecar; it does not independently authorize a sign.

## Calibration contract

The calibration button uses the existing standstill control gate. The five steps adjust the horizon vertically, the left lower point in both axes, the left horizon point horizontally, the right lower point in both axes, and the right horizon point horizontally. Movement locks dismiss the screen. Cancel discards the draft. Save persists a versioned, normalized reference in local app settings; defaults are only editable guides, never detected evidence.

The screen displays an aspect-fit copy of the actual, oriented analysis frame. Guide coordinates refer to that frame, including its complete height, rather than the separately cropped dashcam preview. Saving requires a valid reference and a fresh matching preview. Rotation or aspect-ratio changes disable an incompatible saved reference; proportional resizing preserves it. A mounting change requires recalibration.

TSR's region is exactly `[floor(leftTopX × width), 0, width, height]`. The right guide and horizon do not crop TSR. Both inference stages use the cropped exposure; output boxes are restored to normalized full-frame coordinates before the existing consumers see them. With no compatible saved reference the original full-frame input remains in use. Calibration is captured immutably with each admitted exposure, so saving cannot mix coordinate systems within an inference.

The reference supplies a search horizon and two starting guides to lane extraction. The approximate bus height (1.60 m) and left camera offset (0.08 m) remain separate from this image-space calibration: these five controls do not measure camera intrinsics or establish a surveyed road plane.

## Continuity and presentation

One previous raw-luma image is retained. Bounded patch matching predicts supported boundary points before the new frame's detector scan. Predicted points and calibration guides help candidate selection; fresh image evidence is still required. Forward/backward agreement, texture, matching cost, motion consistency and a maximum evidence age reject unsupported carryover. The tracker drops duplicate or older exposures without clearing usable history.

After two current observations, a prior guide can move the fresh grouping prediction by at most one analysis pixel. This prevents a previous curve from bending a newly observed line toward a nearby competing stripe. A two-stripe regression exercises that failure at both 192- and 384-pixel analysis widths.

Fresh, fused and tracked boundaries have explicit provenance. Each carries the last fresh observation time, evidence age and matched-anchor count. Calibration guides never become observations. Only fresh detector corridor pairs survive into path diagnostics; carried boundaries cannot manufacture a corridor. Curves are reduced to at most 12 points and gently smoothed. The display uses inexpensive midpoint quadratic joins within individual boundaries, retaining the actual point markers and logged coordinates.

Road-path lines remain fully bright until 600 ms after exposure, then fade to the unchanged 750 ms expiry. This avoids starting a fade before the usual next result at the observed approximately 2.2 Hz cadence. It changes presentation only and does not extend evidence lifetime. The separate legacy lane preview used with TSR completely disabled retains its existing detector and temporal behavior.

The filter, prediction, detector and update share the existing 50 ms preparation deadline. The complete lane/path sidecar retains its 200 ms added-work deadline, excluding intervening TSR inference. Abort and lifecycle/geometry changes clear incompatible temporal state. Camera source timestamps govern sequence ordering; wall-clock delivery is separately logged.

## Findings from the two attached recordings

Both substantial videos and the intervening short fragment were copied and verified against device SHA256 values. Private media, positions and detailed logs remain under the ignored Android build-report directory.

| Historical build 10017 | First recording | Second recording |
|---|---:|---:|
| Admitted path frames | 2,205 | 3,544 |
| Average path output rate | 2.225 Hz | 2.164 Hz |
| Empty boundary frames | 19.8% | 16.6% |
| Adjacent boundary-count changes | 49.6% | 57.3% |
| Added work p95 / maximum | 35.93 / 57.13 ms | 38.43 / 67.67 ms |
| 50 ms preparation aborts | 46 | 92 |
| 200 ms added-work misses | 0 | 0 |

The lane setting and preview were enabled throughout almost all of both drives, and valid lane preparation preceded model inference. Independent boundary rebuilding and sparse updates explain much of the visible instability. Count changes are a continuity diagnostic, not a lane-accuracy score.

Some output gaps of roughly 5–7 seconds coincide with missing road context. Android currently rejects such frames before lane preparation; iPhone already permits image processing through ordinary map-context gaps. This change preserves TSR admission as requested and does not mask these long gaps with stale lane geometry. Separating Android's image-only lane admission is an outstanding follow-up.

The replay set contains six 10-second sequences, 23 actual source-PTS samples each, at approximately 0.45-second intervals. They include clear straight markings, a marked bend, dashed-paint losses, unmarked turns and roadside clutter. Temporal state resets between sequences. Source videos are 1280×720 whereas live analysis was 1600×1200, so decoded-video replay cannot establish exact live-image equivalence or camera calibration. No fabricated reference is saved on the device.

## Validation

- Android full unit suite: 514 tests passed, zero failures or skipped tests.
- iPhone simulator: 14 focused tests passed, including actual runtime crop/box remapping in four mounting orientations. The app also built for iPhone without signing or deployment.
- Native Swift: 25 detector/session tests passed, including full saved-calibration diagnostics and exact rotated-source crop coordinates.
- Moto calibration UI: verified all five steps, live analysis-frame display, exact arrow controls, adjustment and Cancel. The test left no saved calibration; the lane-overlay preference remains enabled.
- Both logs contain complete calibration coordinates, revision, source geometry and actual TSR crop pixels, plus boundary provenance, freshness, anchor support and temporal operation counts. The existing inspector accepts the additional fields; they are available in raw details.

The first Moto continuity replay completed all 138 frames with zero freshness violations and zero 50/200 ms temporal-session deadline misses. Total component p95/max was 24.48/36.17 ms; all 138 reference-filter hashes matched. This measurement excludes decoding, full camera sampling, TSR inference and live recording contention. It is not a complete live-drive performance qualification.

That first run produced 41 fused boundaries and no tracked-only recovery. Matched point displacement improved on the marked straight sequence but worsened on the marked bend; unmarked urban flicker was largely unchanged. The one-frame availability increase came from a cold stateless-detector abort, not demonstrated gap recovery. Visual review found guardrail, signpost and parked-car contours in both arms. These results do not establish solved continuity or semantic lane accuracy.

Native replay reproduced the Moto's initial geometry on all 138 frames before further comparisons. Wider vertical motion searches and normal-direction/brightness-normalized searches were rejected: extra fused or carried curves did not improve displacement, and the sole added carried curve in the brightness-normalized variant did not align with road paint. The final change keeps the conservative matcher and bounds prior-guide influence on fresh grouping. Its native count changes fell from 73 to 70; marked-bend displacement p95 fell from 0.04358 to 0.03910 image widths, still above the stateless 0.03683. No tracked-only recovery was added. This is evidence for limiting prior bias, not a claim of improved semantic accuracy.

### Final Moto verification

The final installed build is **1.3-debug / 10018**, APK SHA256 `6213181b231aaa4cb3bea87fd7608e200e7a4c408b83866eb3083328c88ae8b3`. The unchanged replay harness verified identical source bytes, source PTS and source-video hashes against the first run.

| Final temporal session, 138 frames | Result |
|---|---:|
| Component time p50 / p95 / maximum | 12.91 / 24.18 / 35.95 ms |
| Session-reported added work p95 / maximum | 24.00 / 35.04 ms |
| 50 ms preparation aborts / 200 ms misses | 0 / 0 |
| Reference filter hash matches | 138 / 138 |
| Freshness/provenance violations | 0 |
| Fresh / fused / tracked-only boundaries | 328 / 38 / 0 |
| Boundary-count changes | 70 / 132 adjacent pairs |

The Moto confirmed the native comparison: count changes dropped from 73 to 70, and the marked bend's count changes dropped from 16 to 13. The straight section's displacement improvement was retained. Availability and unmarked urban flicker did not improve, and reliable tracked-only gap recovery remains unproven. Thermal status stayed nominal throughout the short replay. Sustained live capture still needs the next road test after the owner saves the actual mounting calibration.

Private replay outputs are under `android/app/build/reports/road-path/drive-20260930-first/moto-continuity/`, with rejected native variants and their reproducible source snapshots under `temporal-lab/`. No private recordings, locations or generated build outputs are part of this change.

## Research context

[YOLOP's official implementation](https://github.com/hustvl/YOLOP) shares an encoder and separates object detection, drivable-area segmentation and lane outputs. It is useful architectural context for keeping these signals explicit. This implementation does not port YOLOP weights, claim learned drivable-area segmentation, or infer road semantics from a smoothed boundary. A learned road/marking model would need its own mobile export and measured validation on these recordings.
