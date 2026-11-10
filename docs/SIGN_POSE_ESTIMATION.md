# Private sign position and facing estimates

Freiburg publishes physical sign points and `azimut`, the compass direction of
the sign's front face. The batch uses degrees clockwise from true north.
GeoJSON geometry is WGS 84 longitude and latitude, while `ost` and `nord`
follow Freiburg's EPSG:25832 convention.
[Freiburg catalog](https://mobidata-bw.de/de/dataset/vz-freiburg) · [Freiburg schema](https://geoportal.freiburg.de/wfs/digit_verkehrszeichen/digit_verkehrszeichen?SERVICE=WFS&VERSION=2.0.0&REQUEST=DescribeFeatureType&TYPENAMES=ms%3Averkehrszeichen_2024)

## Camera rays and sign hypotheses

The source adapters in the sibling Woladen backend produce private optical-ray
inputs. The mobile adapter uses timestamped rear-camera axes from observer v2,
with a reviewed lens and mounting sensitivity profile. The Panoramax adapter
uses registered annotation pixels and the stored camera model. For supported
phone captures, the optional forward-mount model treats EXIF travel course as
an approximate camera axis and accounts for the uncertainty. For a public
candidate, the annotation and pose must agree with the current public origin.
[Panoramax annotation geometry](https://docs.panoramax.fr/backend/install/deep_dive/semantics/) · [Panoramax picture metadata](https://docs.panoramax.fr/pictures-metadata/)

The estimator tests intersections between same-class rays and fits candidates
using the existing bounded bearing solver. It requires at least three
independent views, a useful baseline and intersection angle, and an unclipped
position envelope with a radius of at most 20 metres. Repeated GPS fixes and
source images cannot add votes. Competing assignments that reuse the same
sightings are withheld when the leading fits disagree about the position.
Mobile rays with more than 50 metres of position uncertainty are counted
and withheld before fitting.
The fit separates clearly opposing approaches across sequences. It combines
disjoint fits only if they share the exact StVO class, come from different
sequences, lie less than 20 metres apart, and have sequence-balanced viewing
directions within 30 degrees. Every pair in a merged group must satisfy the
checks, and the combined position must have independent support from each fit.

A center ray constrains position. A separate face model checks which compass
directions are compatible with all front-visible viewpoints. Where full panel
width was verified, it also tests the apparent width change with obliquity. A
heading is written only when the remaining interval has a half-width of at
most 45 degrees. Wider bounded intervals are retained as
`front_azimuth_arc_deg`. Its two endpoints run clockwise and may wrap across
north. Position and heading bounds are conditional on the declared
camera models, source association, front visibility, and panel geometry.
[Traffic-sign pose estimation study](https://doi.org/10.1049/iet-ipr.2019.0023)

## Run a static review batch

Use the Woladen backend's `requirements-sign-wfs.txt` and its
`docs/youspeed/MOBILE_SIGN_POSE_RAYS.md` and
`docs/youspeed/PANORAMAX_SIGN_POSE_RAYS.md` instructions. Keep the ray inputs
and ID key owner-readable. The batch accepts
a Panoramax JSON array or an object containing `rays`, and mobile JSON Lines.
Run from the YouSpeed checkout with the sibling analytics checkout on
`PYTHONPATH`. Add one `--rays` argument per qualified source. If mobile
lifecycle checks fail, its extraction produces no file.

A crop-less mobile sighting can contribute a center ray when the sighting
binds its camera direction, detection box and GPS fix to the same frame.
Without calibrated intrinsics, it uses a declared camera model and has no
apparent-width constraint. Crop-linked observations and repeated frames or
fixes contribute once.

```sh
umask 077
openssl rand -out /private/sign-pose/id.key 32
PYTHONPATH=../Woladen.de-analytics python -m scripts.tsr.collection.run_sign_pose_batch \
  --rays /private/sign-pose/panoramax-rays.json \
  --id-key-file /private/sign-pose/id.key \
  --boundaries /private/sign-pose/two-city-boundaries.geojson \
  --area 08235033:bad-herrenalb --area 08231000:pforzheim \
  --output /private/sign-pose/city-review
```

Use a new output directory. The exported positions determine municipal
membership. Files contain estimated sign points, a front-facing azimuth
when supported, and their uncertainty fields. Camera positions, image IDs,
and device identifiers remain in the private input. The files are local
review drafts. Source and publication checks still govern a later WFS
release.

The batch writes the private `sign-identities.json` ledger with the two
exports. Reuse the same ID key and pass the previous batch's ledger via
`--previous-identities` to preserve an ID when the qualified observations
change. Matching prefers shared inliers and requires a unique match in both
directions. The ledger stores HMAC tokens for the inliers. Keep it alongside
the private inputs.

For a selective Panoramax origin check, run the batch command with the
provisional rays and `--candidate-images-file /private/sign-pose/candidate-images.json`
in place of `--output`. Recheck those images with the Panoramax adapter, then
run the output command on the same provisional input with
`--confirmed-rays /private/sign-pose/panoramax-checked.json`. Every inlier
must match a rechecked input exactly. This preserves the original association
competition while withholding candidates with any stale or missing support.

For private review by the Panoramax operator, pass an owner-only authoritative
corpus ray document via `--private-panoramax-rays`. The document marks
`private_panoramax_review: true` and `origin_rechecked: false` and preserves
the corpus visibility provenance. It can be combined with eligible mobile
rays. This path writes owner-review drafts and cannot serve as the
`--confirmed-rays` input.

For a Panoramax-only review, pass the original, complete JSON Lines report
from the same snapshot via `--panoramax-bridge-report`. It matches detections
of the exact class across different sequences when the camera positions are
less than 20 metres apart and the headings differ by at most 30 degrees.
Panel-center bearings and apparent box height help reject conflicting
matches. Every pair in a group must pass the checks.

The companion `*-sequence-bridges.geojson` contains matched camera
locations. A group links to a sign ID only when at least two of its
observations support the same fitted position. The sign-point file keeps
position and viewing-direction checks separate. Estimates with a bounded
radius between 20 and 40 metres also need a stable refit after dropping a
sequence and are marked `coarse_review`.

## Optional OSM and image-approach fallback

Pass `--osm-road-graph` with an original OSM graph produced by
`scripts/tsr/collection/extract_candidate_road_graph.py`. Pin the PBF checksum
and cover both municipalities plus a buffer. OSM is road geometry context.
Sign positions and sightings still come from the crop and Panoramax inputs.
[OSM way direction and side convention](https://wiki.openstreetmap.org/wiki/Forward_%26_backward%2C_left_%26_right)

For eligible roadside signs, right of the ordered way suggests forward travel
and left suggests backward travel. The front-face azimuth points toward
approaching traffic, 180 degrees from that travel direction. The estimator
checks the full fitted position region, stable local tangents, competing roads
and explicit one-way direction. Parking and median signs do not use the
right-side convention. An image approach direction comes from the geotagged
camera displacement in a time-ordered sequence. The sightline and road
alignment must support the approach. The batch reports weak two-image pairs
separately from stronger trajectories.

A road-only result appears as `osm_candidate_azimut_deg` for review. By default,
the batch writes a road-derived `azimut` only with corroborating evidence. Image
approach bearings appear separately in `image_approach_deg`, even when they
are too weak to assign an azimuth. All of these remain private draft estimates.

Use `--road-azimuth-fallback` to fill remaining private azimuths with the
opposite of the selected road's local approach bearing. The batch prefers an
inlier's recorded way ID, then the existing road association, then the nearest
way in the pinned graph. It uses verified recorded traversal, explicit
one-way direction, the roadside convention, or OSM node order in that order.
The export records the selected way, direction basis, distance and tangent
ambiguity alongside the estimate. It retains the stricter road analysis status.

### Freiburg validation

The WFS benchmark tests published positions and class codes as input. It uses
the published `azimut` only for scoring. In addition to a 0.5-metre position
disk, it checks a centered 18-metre disk comparable to the current drafts.
Freiburg's publisher did not report validating its own azimuth accuracy.
[Freiburg dataset](https://mobidata-bw.de/de/dataset/vz-freiburg)

```sh
python -m scripts.tsr.collection.validate_osm_sign_heading \
  --reference /private/sign-pose/freiburg-reference.geojson \
  --osm-road-graph /private/sign-pose/freiburg-road-graph.json
```

## Direct image-heading review

For each inlier image, project the panel center to a compass bearing using the
camera orientation and lens model. The reverse bearing points from the sign
toward the camera. The batch combines those directions on a circle, giving each
sequence equal weight. `image_candidate_azimut_deg` is the resulting
viewpoint proxy. Its spread and camera-bearing allowance describe the source
evidence. The same optical rays bound the front-facing arc without using OSM.
A narrow arc with assumed camera pose is retained as
`image_visibility_candidate_azimut_deg` with its half-width.
[Panoramax camera metadata](https://docs.panoramax.fr/pictures-metadata/tech/api_reference/)

For a rectangular panel, `--panel-evidence` takes reviewed full face corners
in the native pixel frame, panel aspect ratio, horizontal field of view and
camera yaw. The supplied model allowances cover lens, yaw, tilt and corner
placement. The homography estimates a camera-relative face normal in each
image, then intersects the modeled heading intervals across images. The
interval is a sensitivity calculation under the stated assumptions.
[Traffic-sign plane pose study](https://doi.org/10.1049/iet-ipr.2019.0023)

A private panel evidence array carries `source`, `observation_id`,
`image_id`, `review_group_id`, `image_width`, `image_height`,
`horizontal_fov_deg`, `camera_yaw_deg`, `corners_xy` in clockwise order,
`panel_aspect_ratio` (defaults to 1), `corner_allowance_px`,
`fov_allowance_deg`, `yaw_allowance_deg` and `tilt_allowance_deg`. A group
must depict the same face on all reviewed images. Every member must be
currently qualified. The group must link to exactly one fitted sign through
at least two of its exact observations. Extra reviewed views affect facing
only. The batch keeps the panel candidate and sensitivity separate from
`azimut` and excludes image IDs and corner coordinates from the city files.

`validate_image_sign_heading` compares frozen image correspondences with
Freiburg's published angle. It reads the angle after computing the prediction.
Use its `--reference`, `--matches`, `--rays` and optional
`--panel-evidence` arguments. The November 10 review used four conditional
public Panoramax matches and one separately visually confirmed pair. The
five cases use assumed pose and are too few to establish export accuracy.
[Freiburg reference](https://mobidata-bw.de/de/dataset/vz-freiburg)

## Recorded way and drive-log evidence

The mobile crop adapter passes through a stable `phone_road_match` with
known direction and an original matcher fix within one second of the frame.
Use `--travel-bundle /private/maps/original.sqlite` alongside
`--osm-road-graph` for a SQLite bundle. For a packed bundle, pass
`--travel-packed-manifest /private/maps/manifest.json` and keep the original
installed context and geometry artifacts beside it. Repeat either option for
multiple revisions. The command verifies the SHA-256 recorded by the phone.
For packed bundles, it verifies the road artifact and the shared original
source identity before reading the way. It compares ordered way vertices
with the OSM graph.
A completely reversed vertex order reverses the recorded direction. Changed
geometry, an unavailable bundle, or ambiguous order withholds the match.
[Cropped-frame road-match contract](CROP_PHONE_ROAD_MATCH_2026-10-09.md)

At least two independent inlier frames must agree on the exact traveled way
and direction, with a camera clearly upstream of the sign. The sign must
still have an unambiguous approach road and compatible front visibility.
Image-only tracks also check for competing ways along the camera corridor.
A recorded direction can corroborate the private road-derived `azimut`.
The export retains no drive log, raw device ID or capture-session identifier.

A drive log is usable when there is an exact same-drive link. A journal's
Panoramax photo binding or an original capture ID can anchor the photo to the
correct session before matching its original frame time to a recorded fix.
Keep those joins and the surrounding fixes private. Nearby timestamps or GPS
positions across unrelated sessions do not establish a link.
[Private trip journal contract](../shared/trip-journal/README.md)
