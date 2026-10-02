# Research on assigning traffic signs to the road being driven

Research checked on 28 September 2026. This is a design and experiment review;
it changes no recognition model, runtime policy, bundle, or device installation.

The full review is attached to
[issue #8 as a research addendum](https://github.com/volzinnovation/youspeed.de/issues/8#issuecomment-5877087063).
The next experiment prioritizes manually reviewed road geometry and physical
sign association with driver behaviour disabled. Newly sourced French motorway
imagery is an external exploratory corpus; it is not automatically an approved
independent holdout or production qualification.

The relevant research problem is **sign applicability**, also called sign
salience, sign-to-lane attribution, or logical lane assignment. Reading a sign's
number correctly does not establish that it governs the vehicle. The practical
direction for YouSpeed is to combine directed road geometry, visual relationships,
and a causal history of movement before admitting a sign as camera evidence.

The ranking below reflects relevance to our exit/service-area failure, not an
across-paper performance ranking. Their datasets and metrics are incompatible.
Primary papers, author/institution pages and official implementation repositories
were used. “Code not verified” means this review did not establish a usable public
release; it does not mean the authors have no code. The original literature review
did not install or run external implementations. The follow-up classical-geometry
experiment below uses an isolated desktop OpenCV environment; it does not change
either mobile app.

The [low-compute geometry shortlist](#low-compute-geometry-shortlist) adds classical
lane/edge methods, older-phone evidence and the saved-dashcam experiment requested
later on 28 September. The companion
[mounting and path-geometry design](TSR_CAMERA_ALIGNMENT_AND_PATH_GEOMETRY_2026-09-28.md)
defines what gravity can calibrate and what still needs a vehicle-forward reference.

## Direct sign-to-road applicability research, ranked

### 1. Bargeton et al. — the closest match to the exit problem

Alexandre Bargeton, Fabien Moutarde, Fawzi Nashashibi and Anne-Sophie Puthon,
**“Joint interpretation of on-board vision and static GPS cartography for
determination of correct speed limit,” 17th ITS World Congress, 2010.**
[Author-deposited paper and publication record](https://arxiv.org/abs/1010.3867).

Inputs are signs and supplementary exit arrows, map information, and visual lane
changes estimated from lane-line history. Temporal rules distinguish seeing an
exit sign from entering its lane, and handle mainline signs seen from the exit.
The abstract reports 90% main-sign recognition and 80% exit-subsign detection;
these are **recognition figures, not applicability accuracy**. End-to-end evidence
is several illustrated real-time vehicle scenarios, without a large quantitative
exit benchmark. The authors explicitly leave signs between adjacent roads as
further work. [Full paper, sections on joint interpretation and perspectives](https://arxiv.org/pdf/1010.3867).

Public code was not verified. Proposed experiment: retain a branch-associated
sign track and change its applicability only when observed road/lane movement
supports entering that branch. Test both continuing straight and taking the exit.
Do not copy its blanket prohibition on limit increases inside exits without our
own positive controls.

### 2. Schreier and Grewe — explicit uncertainty in lane attribution

Matthias Schreier and Ralph Grewe, **“A High-Level Road Model Information Fusion
Framework and its Application to Multi-Lane Speed Limit Inference,” IEEE
Intelligent Vehicles Symposium, 2017**, DOI 10.1109/IVS.2017.7995876.
[Full paper uploaded by Schreier](https://www.researchgate.net/publication/317741698_A_High-Level_Road_Model_Information_Fusion_Framework_and_its_Application_to_Multi-Lane_Speed_Limit_Inference).

Inputs include uncertain sign positions, lane polylines, sign existence/classes,
lane-precise localization, map attributes and situation cues. Monte Carlo position
relations feed Bayesian logical lane assignment; Dempster–Shafer fusion and
temporal discounting combine lane-specific evidence. The paper reports a real-time
Continental test-vehicle implementation and worked scenarios, rather than a
reproducible large exit-rejection benchmark. Public code was not verified.

The project's primary presentation explicitly illustrates wrong Autobahn sign
associations and construction zones requiring reduced map trust.
[Ko-HAF presentation, slides 20–33](https://ko-haf.de/wp-content/uploads/2021/02/15_Ko-HAF_Online-Localization-and-Fusion-via-Vehicle-Sensor-and-Backend-HD-Map-Data.pdf).

Proposed experiment: compare an explicit current-road/branch/unknown assignment
with today's Boolean right-side guard. Perturb GPS, heading and lane boundaries
instead of treating geometry as exact. Keep uncertainty separate from classifier
confidence. The full HD-map/vehicle-sensor architecture is not established as a
smartphone solution.

### 3. Greer et al. — visual appearance plus manoeuvre context

Ross Greer, Jason Isa, Nachiket Deo, Akshay Rangesh and Mohan M. Trivedi,
**“On Salience-Sensitive Sign Classification in Autonomous Vehicle Path Planning:
Experimental Explorations With a Novel Dataset,” IEEE/CVF WACV Workshops,
2022, pp. 636–644**; preprint 2021.
[Official proceedings record](https://openaccess.thecvf.com/WACV2022_workshops/HPIV).

The model combines sign crops with optional coordinates, road type and manoeuvre
labels. LAVA contains 14,112 samples around San Diego, including 563 speed signs.
Reported salience accuracy is 66.50% for a right-side baseline, 74.22% for ResNet50
crops and 75.99% with manoeuvre augmentation. Adding all context features gives
73.58%, so additional signals do not automatically help.
**Manoeuvre labels use the following ten seconds of speed/yaw.** That is useful
for retrospective labeling but unavailable to a causal live implementation.
[Paper, sections 3–4 and Table 5](https://arxiv.org/pdf/2112.00942).

Public code/weights were not verified. Proposed experiment: compare crop-only
applicability against crop plus strictly past/current movement on our labeled
encounters. Future trajectory may determine evaluation truth, never an input.
These results neither validate speed-only suppression nor establish European
motorway performance.

#### Follow-on: Greer et al. 2023 — full-image context during detection

Ross Greer, Akshay Gopalkrishnan, Nachiket Deo, Akshay Rangesh and Mohan Trivedi,
**“Salient Sign Detection In Safe Autonomous Driving: AI Which Reasons Over Full
Visual Context,” International Conference on the Enhanced Safety of Vehicles
(ESV), 2023, paper 23-0333.**
[Author-deposited conference paper](https://arxiv.org/pdf/2301.05804).

This follow-on moves from cropped-sign classification to full-image Deformable
DETR detection. Salience-sensitive focal loss weights salient training examples
more strongly. Experiments on the San Diego LAVA Salient Signs dataset show
improved recall for salient signs and all signs in precision–recall comparisons;
the authors characterize the limited-training results as preliminary. Public
project code/weights were not verified.

This supports evaluating surrounding visual context, but does **not** jointly
implement explicit road geometry, temporal motion and sign-road assignment. Its
target is prioritizing relevant detections, not a measured French exit-sign
rejection policy. Proposed experiment: compare crop-only versus wider-context
applicability features while keeping detection outputs fixed; consider salience-
weighted detector training separately only if that experiment justifies it.

### 4. Guo et al. — relationships between signs, lanes and road branches

Yunfei Guo, Fei Yin, Xiao-hui Li, Xudong Yan, Tao Xue, Shuqi Mei and Cheng-Lin Liu,
**“Visual Traffic Knowledge Graph Generation from Scene Images,” IEEE/CVF ICCV,
2023.** [Official proceedings record](https://openaccess.thecvf.com/content/ICCV2023/html/Guo_Visual_Traffic_Knowledge_Graph_Generation_from_Scene_Images_ICCV_2023_paper.html).

Their hierarchical graph attention network links sign components, supplementary
signs and road/lane elements using appearance, semantics and spatial features.
It assumes position-known signs, roads and lanes. RS10K contains 10,066 Chinese
road images from 31 cities, including service areas and diverging roads. Reported
arrow-to-traffic-element relation F1 is .823; this is not wrong-speed-activation
accuracy. [Paper, dataset description and Tables 3–4](https://openaccess.thecvf.com/content/ICCV2023/papers/Guo_Visual_Traffic_Knowledge_Graph_Generation_from_Scene_Images_ICCV_2023_paper.pdf).

The [author laboratory's RS10K page](https://nlpr.ia.ac.cn/pal/RS10K.html)
advertises generation/evaluation code and data, with research-use conditions and
separate commercial licensing. The advertised release was verified in the page;
download contents and runnability were not. Public data also differ from paper
statistics after image removals.

Proposed experiment: annotate each French sign with its governing road polygon
and supplementary arrow/parent panel. First test relationships with manually
correct geometry, then predicted geometry, exposing perception-versus-association
errors separately. A single-image graph does not resolve a future lane change.

### 5. Yang et al., SignEye — ego-relative visual reasoning

Chuang Yang, Xu Han, Tao Han, Yuejiao Su, Junyu Gao, Hongyuan Zhang, Yi Wang and
Lap-Pui Chau, **“SignEye: Traffic Sign Interpretation From Vehicle First-Person
View,” IEEE Transactions on Intelligent Transportation Systems, 26(11),
19413–19425, 2025**, DOI 10.1109/TITS.2025.3590935; preprint 2024.
[Author institution publication record](https://research.polyu.edu.hk/en/publications/signeye-traffic-sign-interpretation-from-vehicle-first-person-vie/).

SignEye uses lane/road regions and sign descriptions to associate instructions
with current/left/right roads and lanes. Its Traffic-CN dataset has 20,000 Chinese
images, split 18,000/2,000, with substantial automatically generated supervision.
Speed-plan accuracy rises from 81.5% without the ego-relative representation to
85.6% with it. This evaluates scenario answers, not continuous exit suppression.
[Author's journal manuscript, Tables IV–V](https://omtcyang.github.io/pdf/2025%20SignEye.pdf).

Public application code/weights were not verified. Proposed experiment: compare
sign position relative to the estimated current-road boundary against absolute
image-x. Use full scene context for offline annotation assistance, with human
review. The VLM pipeline's reported GPU evaluation does not establish mobile
latency, and image-based association needs separate temporal validation.

### 6. Lazar et al. — modern relevance filtering and sign-track attributes

Meda Lazar, Sourab Sridhar, Shashwata Gupta, Alexandra Tripcea, Varun Ravi and
Senthil Yogamani, **“Multi-Modal Traffic Sign Detection with Semantic Attributes
for Autonomous Driving,” arXiv:2608.20874, August 2026 preprint**; no peer-reviewed
venue verified. [Author submission](https://arxiv.org/abs/2608.20874).

Camera/LiDAR tracking is followed by readability, embedded-sign and relevance
attributes, using lane geometry and semantic context. In the relevance ablation,
adding polygon containment to a five-metre lane-distance test improves precision
from .54 to .64, with recall .89. The broader proprietary dataset spans 60+
countries; headline object-miss performance is a different metric. The 3-D
multi-sweep experiment aggregates ten **future** LiDAR sweeps, so its gains cannot
be transferred to causal phone-camera replay.
[Paper, sections V-D, VI-F and VI-H; Table VIII](https://arxiv.org/html/2608.20874v1).

Public pipeline code was not verified. Proposed experiment: maintain applicability
as a physical-track attribute, and compare distance-only versus corridor geometry
on branch signs. Smartphone monocular geometry and sparse stills cannot reproduce
the paper's 3-D sensor inputs. Its relevance precision also argues against treating
geometric proximity alone as decisive.

## Supporting geometry and topology implementations

### 7. Qin et al., UFLDv2 — a practical lane-geometry experiment

Zequn Qin, Pengyi Zhang and Xi Li, **“Ultra Fast Deep Lane Detection with Hybrid
Anchor Driven Ordinal Classification,” IEEE Transactions on Pattern Analysis and
Machine Intelligence, 2022**, DOI 10.1109/TPAMI.2022.3182097.
[Author paper](https://arxiv.org/abs/2206.07389).

The image model predicts sparse lane coordinates using global features and hybrid
anchors. The [official MIT-licensed implementation](https://github.com/cfzd/Ultra-Fast-Lane-Detection-v2)
provides pretrained ResNet18/34 models for CULane, TuSimple and CurveLanes,
evaluation code and ONNX export. Its ResNet18 CULane result is 75.0 F1. Repository
and model links were verified; inference and phone performance were not tested.

This detects lane geometry, **not sign applicability**. Proposed experiment: run
it offline on forward-looking Panoramax images and compare predicted boundaries
with manual annotations around gore areas. Score missing and false branch
boundaries explicitly, especially with worn markings, night glare and curves.
Published throughput must not be reported as measured iPhone/Android throughput.

### 8. Poggenhans et al., Lanelet2 — a schema and matching reference

Fabian Poggenhans, Jan-Hendrik Pauls, Johannes Janosovits, Stefan Orf, Maximilian
Naumann, Florian Kuhnt and Matthias Mayr, **“Lanelet2: A High-Definition Map
Framework for the Future of Automated Driving,” IEEE ITSC, 2018**.
[Author-hosted paper](https://www.mrt.kit.edu/z/publ/download/2018/Poggenhans2018Lanelet2.pdf).

The [official open implementation](https://github.com/fzi-forschungszentrum-informatik/Lanelet2)
supplies geometry, matching, routing and traffic-rule interpretation. Its
[regulatory-element schema](https://github.com/fzi-forschungszentrum-informatik/Lanelet2/blob/master/lanelet2_core/doc/RegulatoryElementTagging.md)
links signs/restrictions to lanelets, with validity and cancellation lines.
Code existence was verified; it was not run. The paper demonstrates map structure
and uses, not visual wrong-road rejection accuracy.

Proposed experiment: borrow the explicit directed association and bounded-extent
concept for small replay fixtures containing mainline, ramp and service road.
Lanelet2 expects authored associations; it does not infer them from camera images.
Our OSM bundles are not HD lane maps, so adopting its library would not create
missing lane geometry or legal sign associations automatically.

## Driver behavior: supporting evidence, with a direct counterexample

Yongfeng Ma, Wenbo Zhang, Xin Gu and Jiguang Zhao, **“Impacts of experimental
advisory exit speed sign on traffic speeds for freeway exit ramp,” PLOS ONE
14(11):e0225203, 2019.** The study collected 480 vehicle speed profiles at three
Chinese ramps over twelve hours. It describes drivers retaining mainline speed
in the deceleration lane and braking sharply around the physical gore, with
behavior varying by ramp and signage.
[Primary article](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0225203).

This is a behavioral study, not an applicability algorithm. It undermines the
claim that absence of early slowing proves the car is staying on the motorway.
Conversely, slowing may reflect congestion on the mainline. Use motion as
corroboration after spatial association, and include actual-exit/late-braking
cases in evaluation. The study does not supply a transferable French/German
threshold for acceleration or speed discrepancy.

## Proposed synthesis for YouSpeed

These are engineering hypotheses to test, not results established by the papers.

1. **Separate recognition from assignment.** Keep the country classifier. For
   each physical sign track, record candidate governing roads, their confidence,
   and the evidence used. A readable “30” may still have unknown applicability.
   Do this before immediate overrides and passage finalization so a late veto
   does not arrive after an erroneous speed claim.
2. **Use directed corridor context.** Preprocess mainline intervals around
   departures, connecting ramps, service-area access and parallel roads. Store
   branch side, direction, corridor geometry, extent and provenance. An entire
   OSM way or a fixed right-side camera region is too coarse. Camera mounting,
   curves and perspective require calibration or estimated road-relative
   positions with uncertainty.
3. **Add visual relationships.** Consider sign tracks relative to road
   boundaries/gore, their associated arrows/panels and matching signs across the
   carriageway. Do not project an elevated sign centre onto the road plane as if
   it were a ground point. Start with manually annotated geometry to establish
   whether attribution can work before adding another imperfect model.
4. **Use temporal road membership.** Observe heading, lateral lane movement and
   directed route continuity. When the vehicle takes the branch, re-evaluate
   associated signs promptly. Retain enough history to distinguish a new physical
   sign from repeated detections; changing classification of one track is not a
   90→70→50→30 sequence of four signs.
5. **Add behavior only as a bounded contribution.** A rapid descending sequence
   on distinct branch-side tracks, stable mainline movement and no slowing is
   stronger evidence than any one cue. Spatial or semantic evidence must support
   a branch before behavior increases rejection confidence. Genuine roadworks,
   variable limits and toll approaches can also produce rapid reductions. Driver
   compliance must not become the definition of a valid restriction.

An experimental current-road/other-road/unknown output belongs to the applicability
producer. Whether and how an unresolved sign changes the displayed reference is a
separate product-policy decision. This review does not revise the approved shared
speed-reference state machine or assume approval for a new runtime hold rule.

## Replay protocol using the existing drive and Panoramax

Use the [28 September drive review](FR_DE_DRIVE_REVIEW_2026-09-28.md) to seed
encounters, particularly the Aire de Brouck service-area sign and the 16:09 UTC
exit sequence. Manual dismissals are useful review markers, not automatically
correct labels for every surrounding sign.

| Experiment | Controlled comparison | Evidence it can establish |
| --- | --- | --- |
| A: topology and freshness | Current guard versus fresh directed mainline/branch context; identical detections | Missing context versus inadequate attribution |
| B: road-relative geometry | Image-x threshold versus manually annotated, then predicted, road boundaries | Whether geometry fixes perspective failures and what lane-model errors cost |
| C: physical-track history | Independent frames versus linked sign tracks with past observations | Early wrong activation, recovery delay and repeated/new sign handling |
| D: behavior ablation | C with and without past/current speed, heading and deceleration | Incremental benefit and harm of the proposed driver heuristics |
| E: supplementary context | D with arrows, panels, paired mainline signs and roadwork cues | Whether counterevidence protects real restrictions |

Create ground truth for **governing road, physical sign identity and first
decidable time**, plus an unknown label when the image cannot decide. Retain
capture timestamps, camera orientation/FOV where known, location quality,
sequence identity, image source/license and model hashes. Associate stills and
live detections by time with their offset; they are not the same frame.

Hold out entire exits/service areas and capture runs; adjacent frames must not
cross the tuning/test boundary. Include true mainline reductions, actual ramp
entry, late braking, curved mainlines, paired signs, overhead signs, roadworks,
missing OSM branches, night imagery and stale/inaccurate GPS. Evaluate uncertainty
and false rejection as well as rejection success. Bootstrap confidence intervals
by encounter rather than treating hundreds of frames as independent evidence.

Use three separate evaluation levels:

- **Still-image association:** Panoramax can supply geometry and visual context.
- **Causal sequence replay:** use original timestamps and real past movement when
  present; synthetic speed profiles are labeled stress tests, not observed drives.
- **Phone parity/performance:** after offline selection, use identical fixtures
  through Swift/Kotlin paths and measure latency, thermal load and memory locally.

Sparse public still sequences cannot prove live tracking recall, shutter behavior
or subsecond decision timing. No interpolation should manufacture sign detections
or vehicle deceleration and then be counted as field validation. Keep final
ground-truth trajectory separate from features available at each replay instant.

Primary metrics are wrong-road activations per encounter, legitimate-mainline
sign rejection, delay to accept an actual ramp restriction, unresolved duration,
and recovery after uncertainty. Specify an acceptable false-rejection budget
before tuning; a method that hides every sign near exits would otherwise score
misleadingly well on rejection alone.

## Remaining research gaps

The reviewed work provides architectures and partial evidence, not a verified
drop-in answer for our French/German smartphone setup. Important open questions
are whether coarse OSM topology plus monocular imagery is enough before the gore,
how to calibrate uncertainty across mounting positions, and how to preserve real
temporary restrictions when map and movement suggest motorway continuity.

Prioritize the cheapest decisive experiment: manually label governing roads in
our failing encounters, then replay corrected topology and physical-track
association with behavior turned off. Add behavior and learned lane geometry
separately. This establishes whether those additions solve remaining errors
instead of concealing missing map context or timing defects.

## Low-compute geometry shortlist

The [completed desktop extraction probe](TSR_CLASSICAL_GEOMETRY_PROBE_2026-09-28.md)
now compares four OpenCV methods on 173 saved-video frames and 10 suitable stills.
It measures extraction and preserves video timing; lane grouping and sign-road
association are not yet evaluated by that probe.

**Compare Canny + probabilistic Hough, ELSED, and the existing stripe/ridge
baseline first.** This ranks useful experiments for YouSpeed, not universal lane
accuracy. We need several road boundaries and a branch relationship. None of
these extractors by itself identifies which road a sign governs.

| Approach | Role and useful output | Important limitation |
| --- | --- | --- |
| Canny + `HoughLinesP` | Most transparent baseline; finite line segments from paint, curbs and other edges. Main OpenCV `imgproc` module. | Segments are straight; shadows, fences and vehicles also generate them. Requires grouping and curved/branch hypotheses. |
| ELSED | Strongest new candidate by published older-Android extraction cost; author C++ implementation. | Compare with/without discontinuity jumps so merging does not erase fork evidence. No road semantics. |
| Stripe/ridge contrast + bounded robust curve fitting | Cheapest integration starting point because Swift/Kotlin stripe code already exists on the lane branch; paint-specific evidence before fitting. | Missing/worn paint, headlights and broad pavement edges require abstention or another input. Existing two-line estimator is insufficient. |
| EdgeDrawing / EDLines | Useful alternative when connected pixel chains help preserve a curved edge before fitting short straight sections. | OpenCV contrib dependency; connected edge chains still include non-road objects. |
| FastLineDetector | Convenient additional OpenCV contrib baseline, including internal Canny and optional merging. | No verified phone benchmark in this review; merge policy and edge clutter need evaluation. |
| LSD | Useful independent segment-quality comparison, available in OpenCV `imgproc`. | Lower priority for a tight CPU budget; statistical line validation does not validate lanes or sign applicability. |

### Research and inspectable implementations

**Canny + progressive probabilistic Hough.** OpenCV's
[official tutorial and C++/Java examples](https://docs.opencv.org/4.13.0/d9/db0/tutorial_hough_lines.html)
provide the direct baseline. Use finite-segment `HoughLinesP`, rather than treating
infinite Hough lines as complete road boundaries. Kuzmic and Rudolph's
[2021 filtered-Canny study](https://www.scitepress.org/Papers/2021/103837/103837.pdf)
uses horizontal sections to handle curves. It reports roughly 6 ms at 320×160
on an i7-9750H system in a Unity simulation. That is a desktop/simulator result,
not real-road or mobile qualification. Huang and Liu's
[real-world limitation study](https://journals.sagepub.com/doi/10.1177/17298814211008752)
documents illumination/reflection problems and lane-like roadside clutter.
These motivate evaluating false boundaries, not just visible painted-line recall.

**ELSED — Suárez, Buenaposada and Baumela, Pattern Recognition 2022.** The
[paper's efficiency experiment, Table 4](https://arxiv.org/html/2108.03144v2#S4.SS5)
reports average extraction time on 101 YUD images at 640×480:

| Author implementation | Samsung J5 (2017) | OnePlus 7 Pro |
| --- | ---: | ---: |
| ELSED without jumps | 45.84 ms | 8.28 ms |
| ELSED | 59.99 ms | 10.20 ms |
| EDLines | 65.79 ms | 13.79 ms |
| LSD | 390.91 ms | 58.68 ms |

These are extraction means, not tail latency or our added app cost. They establish
plausibility on old phone hardware, not a guarantee under concurrent TSR/capture.
The [author repository](https://github.com/iago-suarez/ELSED) supplies Apache-2.0
C++ code with an OpenCV dependency. A shared native core could serve Android and
iPhone. No ELSED integration or local ELSED run is claimed here.

**Ridge/stripe features and curves — Aly, IEEE IV 2008.**
[The author paper](https://arxiv.org/pdf/1411.7113) combines an inverse-perspective
view, oriented Gaussian ridge filters, initial line hypotheses and RANSAC Bézier
splines. It supports multiple boundaries rather than just the ego-lane pair.
It reports 50 Hz on Intel Core2 2.4 GHz for 640×480 input, with a small IPM region
illustrated at 160×120. Camera pose and a near-planar road are assumptions, not
free outputs. Its false-positive examples include street text, crosswalks, curbs
and vehicles. Borrow bounded robust multi-boundary fitting; do not import its
camera/road assumptions into an uncalibrated phone.

**Haar-like features — Jung, Min and Kim, IEEE IV 2013.**
The [KAIST publication record](https://pure.kaist.ac.kr/en/publications/an-efficient-lane-detection-algorithm-for-lane-departure-detectio/)
describes integral-image Haar features, supporting points and geometric validation
of two-line hypotheses. This supports simple contrast features, not the need for
a trained object-classifier cascade. Its central-camera assumption is unsuitable
for arbitrary phone mounts. The accessible abstract's timing figure lacks enough
verified hardware/resolution detail for our budget and is deliberately not used.

**Other ready-made extractors.** OpenCV's
[FastLineDetector API](https://docs.opencv.org/4.13.0/df/d4c/classcv_1_1ximgproc_1_1FastLineDetector.html)
and [EdgeDrawing API](https://docs.opencv.org/4.13.0/d1/d1c/classcv_1_1ximgproc_1_1EdgeDrawing.html)
are practical comparators. EdgeDrawing can return connected pixel chains and map
lines back to those chains, potentially useful for curved-road grouping. The
[LSD paper and reference code](https://www.ipol.im/pub/art/2012/gjmr-lsd/)
describe linear-time line extraction and statistical false-alarm control; those
false alarms concern image lines, not lane correctness. The reference archive's
AGPL license differs from current OpenCV's implementation history: pin and review
the implementation actually selected rather than copying arbitrary source files.

**Watchlist: SweepLSD, August 2026.** The
[new preprint](https://arxiv.org/html/2608.22086v1) and
[MIT C++17 author code](https://github.com/yosh-shimizu/sweeplsd) offer a single-pass,
low-memory alternative. Its reported Full-HD timing uses an i7-8700K with AVX2,
not Android. The authors explicitly identify raw lane/contour extraction as a poor
fit because curved runs are rejected; weak/soft edges are another limitation.
This may help calibration-line experiments but does not displace the first three
candidates for our road task.

### Comparison protocol, including saved dashcam video

Use upright luminance at 320×180 and 384×216 as initial size bounds, preserving
aspect ratio. Keep the whole plausible carriageway/branch region; do not crop
away left-hand roads or use the sign classifier's input mask. Mask padding during
feature extraction. Apply calibrated horizon/pose constraints only when known.
Retain multiple supported polylines, visibility and uncertainty, with bounded
fitting work. Do not average every positive/negative slope into two painted lines.

Hold downstream road/sign association and corrected topology constant. Driver
behaviour remains off. Add temporal tracking separately; evaluate flicker, loss
through occlusion, false-boundary persistence and recovery after a turn. Maintain
exposure-time alignment and avoid waiting for new confirmation frames on every
sign decision. The full added path includes image preparation, fitting, association
and scheduling; extractor milliseconds alone do not settle the 200 ms requirement.

The saved 24 September drive contains a directly relevant sequence at video
614–626 s: main-road 90 followed by a different access-road 30, while the vehicle
continues on the main road. Include 550–562 s (paired legitimate 90) and 1360–1370 s
(legitimate 50 on the exit actually taken) as positive controls. These observations
come from the prior local field review and extracted images; the clip start UTC
is only known to one-second precision. Preserve actual presentation timestamps,
not frame-index/nominal-fps guesses, when sampling video.

For stills, 10 current corpus images are rectilinear/perspective. Three A10 images
are equirectangular panoramas and require a verified forward projection before
the same geometry comparison. Orient the four original Android stills using EXIF
once; do not double-rotate the already-upright Swiss derivative. The Swiss 30/50
case has no continuous lane paint, so it must expose the limits of stripe-only
geometry. It is now included as a separate
[reviewed development challenger](../shared/tsr/applicability/fixtures/panoramax-swiss-junction-v1/README.md).

Report sign-level wrong-road admissions and legitimate-sign losses only once a
real association stage consumes the extracted geometry. Until then, timing,
segment counts and overlays are extraction diagnostics, not lane accuracy. Test
on the actual Android afterwards with TSR and capture active, reporting added
p50/p95/p99, deadline misses and sustained thermal behaviour. A <50 ms optional
geometry target leaves margin; it is not an already demonstrated result.
