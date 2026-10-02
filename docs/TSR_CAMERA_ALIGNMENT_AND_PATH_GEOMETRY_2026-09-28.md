# Camera alignment and a cheap path-geometry experiment

**Try a bounded classical boundary detector first, in parallel with TSR. Use
road segmentation as an independently evaluated alternative.** The budget is
200 ms of **added decision cost**, not total sign recognition time. Neither
approach has yet met that budget in a measured run on the attached Android.

The subsequent [classical extraction probe](TSR_CLASSICAL_GEOMETRY_PROBE_2026-09-28.md)
tests Canny/Hough, EDLines, FastLineDetector and LSD on saved video and stills.
Its desktop timing and overlays narrow the experiment; they do not qualify the
Android budget or establish governing-road accuracy.

The missing information is the relationship between the camera's road, adjacent
branches and individual signs. A lane marking, a binary road mask, and a driver's
future intended route are different things. NVIDIA describes PathNet as predicting
visible drivable paths in image and 3D space; its sign system then performs
sign-to-path association. It does not establish that we can infer a driver's
future turn from one image. See [PathNet's original description](https://developer.nvidia.com/blog/?p=29001)
and [the three-network sign pipeline](https://blogs.nvidia.com/blog/drive-labs-ai-based-live-perception/).

## Haar: useful features, insufficient output by itself

A trained Haar cascade classifies image windows and normally returns rectangles.
It would still need a geometric reconstruction stage for lanes, bends and forks.
Haar-like bright-stripe features are a more direct first experiment: compare a
candidate paint strip with its darker neighbours, then fit supported boundaries.
[OpenCV's cascade documentation](https://docs.opencv.org/4.12.0/db/d28/tutorial_cascade_classifier.html)
explains the distinction between inexpensive rectangle features and the trained
multi-scale classifier that consumes them.

We already have that simpler starting point at commit
`de4c08d35ac8c550c8ab08560681e41ba8f2c8f6` on
`codex/lane-detection-dashcam`; it is not integrated into the current issue-8 branch.
The Swift/Kotlin prototype uses a 384-pixel-wide grayscale image, 24–48 sampled
rows and four stripe widths. It fits two locally straight, converging boundaries.
Its 16 synthetic cases / 48 frames established platform parity, not exit accuracy.
The two historical portrait-still smoke checks returned uncertain single boundaries.

Reuse its stride-aware luminance sampling, coordinate transforms, capture-clock
handling, bounded worker and timing diagnostics. Extend the estimator to preserve
multiple supported boundaries and a possible divergence instead of forcing every
scene into one straight lane pair. Bound fit hypotheses and use prefix sums/fixed
buffers where measurements justify them. Do not assume the whole old branch can
be merged without reconciling subsequent camera changes.

Target less than 50 ms for this optional stage, leaving margin inside the 200 ms
added budget. This is an engineering target, not a measured claim. Measure the
entire increment: preprocessing, extraction, fitting, association, scheduling and
interference with concurrent TSR/recording. Record p50/p95/p99 and deadline misses.
The old 5 Hz cadence is not a throughput measurement. Its two-frame confirmation
also needs at least one 200 ms sampling interval from a cold start. Run geometry
alongside TSR and use fresh, exposure-matched results; do not make each sign wait
for two new geometry frames. At the deadline, unavailable evidence stays unknown.
Stopping the wait does not cancel an already executing GPU job.

## What the visual stage must return

Start with image-space evidence: ego-carriageway edges, additional supported
boundaries, up to two branch corridors, separation/gore evidence and confidence.
Include occluded/unknown regions. A binary road mask joins the main road and the
exit at a junction; it does not identify which signs govern each branch. The
current box detector has no road-mask head, so adding a road class is not enough.
A separate small segmentation model is the simplest isolated learned experiment;
keep the user-approved CH sign classifier unchanged.

The new Swiss Le Vaud image makes the scope clear: the main road bends right,
the side road climbs left, the 30 belongs to the side road and the 50 to the main
road according to the driver. The image visibly contains both signs and lacks
clear painted lane boundaries. Road edges, pavement connections, sign orientation
and topology may help there; a white-stripe detector must be allowed to abstain.
Painted text on the branch is corroborating scene evidence, not automatic OCR.
The [original public view](https://panoramax.youspeed.de/?pic=f8ea80f9-c525-44fb-a6d8-7af479f7fdd8&seq=2d99a379-6410-4a15-accd-79264ee714ed)
also contains a roadworks sign, useful as a separate visual distractor.

The [Swiss still corpus](../shared/tsr/applicability/fixtures/panoramax-swiss-junction-v1/corpus.json)
now records both labels, source metadata and reviewed support points. With those
manual geometric inputs, the existing proximity replay assigns the 30 to the
branch but leaves the legitimate 50 unknown: its exact support contact is obscured
by the bollard/grass and is not a reliable ground anchor. This is a useful
remaining limitation, not a completed automatic solution. Evaluate road-relative
roadside/verge association with uncertainty and cues that do not require a visible
post foot; do not manufacture a precise contact point to fit this photograph.

Do not restrict recognition to the ego lane or the right side. Valid signs can
be beside another same-direction lane, on the left or overhead. A sign's elevated
centre is not a road-plane point. Boundary evidence must feed the per-sign road
association, with corrected topology and physical tracks; it is not a pixel mask
that proves applicability. Keep driver behaviour off in the first comparison.

## Mounting aid on iPhone and Android

Use the same three cues on both clients: a horizon line for side tilt (roll), an
aiming band for up/down pitch, and a separate forward-direction target for yaw.
Gravity determines roll/pitch relative to vertical; it cannot determine camera
yaw relative to the vehicle. A compass adds north, not the car's forward axis.
The UI must keep forward alignment unverified until a separate reference exists.
Apple's [vertical attitude reference](https://developer.apple.com/documentation/coremotion/cmattitudereferenceframe/xarbitraryzvertical)
explicitly leaves the horizontal reference arbitrary; Android's
[game rotation vector](https://developer.android.com/develop/sensors-and-location/sensors/sensors_position)
likewise does not provide a fixed magnetic heading and can drift around vertical.

Let the driver aim the camera while parked. Store this as provisional forward
alignment, with measured residual tilt, rather than require perfect zero angles.
Later, passively refine it only during sustained straight, well-observed travel
with consistent course and visual evidence. Curves, stops, lane changes or missing
markings must not validate yaw. Hills, banking, braking and vibration must not
automatically rewrite the mounting calibration or be treated as proof the phone
moved in its holder. Gravity level is not the same thing as the local road plane.

Store camera/lens identity, calibration revision and the effective image mapping.
Use pose at exposure time, with an explicit camera/sensor clock mapping. Keep
analysis-to-sensor-to-preview rotation, crop and aspect-fill transforms intact.
Invalidate incompatible tracks when that mapping changes. Device rotation must
not silently override the app's manual portrait/landscape choice. Metric bird's-eye
projection additionally needs camera height, lateral position and road-plane
assumptions; initial image-space separator experiments need not pretend these
are already measured. Android's [camera timestamp source](https://developer.android.com/reference/android/hardware/camera2/CameraCharacteristics#SENSOR_INFO_TIMESTAMP_SOURCE)
must be checked before comparing camera timestamps with motion sensors.

## Decisive order of work

1. Keep the corrected-topology/physical-track replay with reviewed road assignments
   as the control. Add the Swiss simultaneous 30/50 case with explicit label provenance.
2. Evaluate automatic classical geometry on the five clear-gore negative images,
   the actual ramp-positive, truck occlusion, the unmarked Swiss junction, and
   night images. Include known geometric mounting perturbations. Static images
   establish spatial performance only; use real capture cadence for temporal tests.
3. Compare a compact learned road/branch model on exactly those cases. Add driver
   behaviour as another separate arm only after map/timing defects are resolved.
4. Benchmark on the slow Android with normal camera, TSR and capture workloads.
   Distinguish warm decision overhead, first acquisition delay and evidence age;
   a fast desktop replay or scheduled 5 Hz rate is insufficient.

This note and the interactive alignment explanation are design work. No native
mounting screen, new model or production suppression rule was enabled. The shared
speed-reference policy remains outside this change.
