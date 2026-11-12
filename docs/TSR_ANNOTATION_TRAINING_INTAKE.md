# Panoramax source annotations and training intake

Every bounded Panoramax traffic-sign annotation belongs in the crop corpus,
including manual annotations whose class is absent from the current classifier.
Discovery selects the `osm|traffic_sign` source key; crop rendering depends on
source availability, registered image geometry and current lifecycle state.
Classifier support and model confidence do not control crop inclusion.
The existing backend sync/render workflow owns this corpus.

The German classifier currently has 134 outputs. `DE:310` maps to `city:start`
and `DE:311` to `city:end` through the semantic catalog, although neither is an
output of that classifier. The student course's fixed
[136-class index](../lectures/tsr-sgblur-de-2026-10-26/praktikum/class-index.json)
preserves those 134 outputs and appends the two town-sign classes. Resolving a
source annotation does not create an output in an installed model.

The read-only inventory from **4 November 2026, 00:12 CET** contains **17,777
ready Panoramax crops**, including **97 German town-sign crops: 65
`city:start` and 32 `city:end`**. The administrator-authenticated refresh
imported the complete source snapshot from **3 November, 23:54:53 CET** and
rendered five new crops without errors. No eligible active crop work remains,
and reconciliation found no corrupt crop objects. One image-level tag remains
metadata-only because it has no bounding box.

The source denominator reconciles exactly: 18,212 sign annotations comprise
17,778 imported annotations (17,777 crops plus the image-level tag) and 434
excluded annotations on deleted pictures or pictures with unresolved effective
visibility. These source exclusions keep the service's formal coverage status
incomplete and its completed crop checkpoint at 27 October; they are separate
from pending crop extraction and unresolved classes. Annotations changed after
the source snapshot need a later sync. Stored crops can contain repeated views
of the same sign. Dated evidence is retained privately under
`docs/collection-evidence/2026-11-04-panoramax-refresh/`; the earlier 3 November
snapshot is preserved separately.

[source_annotation_labels.py](../scripts/tsr/source_annotation_labels.py)
resolves source identities independently of classifier support. A unique
classifier-catalog mapping can identify the same source tag; `selected_yolo`
is a reverse catalog mapping, not evidence that a classifier ran or agreed.
When that mapping is absent, a unique semantic catalog identity can still
resolve the source class. Conflicting countries, compound classes and unresolved
tags remain visible. Generic `yes` is detection evidence and does not compete
with a specific `DE:310` or `DE:311` on the same annotation.

A **source annotation** is not automatically a **human-reviewed training
label**. A missing model qualifier does not prove human authorship. Raw tags,
source qualifiers, annotation identity and provenance remain attached to the
record. Explicit review records identify the reviewer and accepted class.

Refresh the class statistics from the [Streetshots Inspector](https://github.com/volzinnovation/streetshots-inspector)
repository root using the existing private Inspector report connection:

```sh
python3 scripts/inspector/panoramax_annotation_statistics.py \
  --output-dir /tmp/youspeed-annotation-class-statistics
```

`--database-file`, `--db-host` and `--db-port` select an existing private report
connection or tunnel; `--mapping-file` selects the pinned backend reverse map.
The command uses one read-only, repeatable-read snapshot, reconciles independent
crop and join counts, and writes `annotation-class-statistics.csv`, `.json`,
`.md`, source SQL and a checksummed validation receipt. Unsupported source
classes remain counted; classifier support is a separate output column.

The [student intake adapter](../scripts/tsr/student_crop_intake.py) reads the
five learning archives from `loffenauer/ws26_hspf_imo`, pinned to dataset
revision `8a18036ee9403a3487a55f397f82999a3911b99c`. Their collection manifest
lists **409 crop candidates**, including **265 town-sign candidates: 200
`DE:310` and 65 `DE:311`**. The archives already reside under
`lectures/tsr-sgblur-de-2026-10-26/output/`; native crop members can be streamed
without downloading or extracting the full road images.

The base collection preserves source annotation tags. The four MobiData and
Mapillary additions carry visual proposals requiring review. The adapter
preserves this distinction and every stock candidate remains unreviewed.
The demo, teacher-reserved test packages and separate 85-candidate review
gallery are excluded from this learning intake. A registry search code or
visual proposal alone does not become an approved training label.

[annotation_training_intake.py](../scripts/tsr/annotation_training_intake.py)
combines an exported current Panoramax crop selection with those five archives.
For the refreshed town-sign selection, run:

```sh
python3 scripts/tsr/annotation_training_intake.py \
  --panoramax-export docs/collection-evidence/2026-11-04-panoramax-refresh/panoramax-city-records.json \
  --panoramax-images docs/collection-evidence/2026-11-04-panoramax-refresh/panoramax-city-images \
  --student-collection docs/collection-evidence/2026-11-03-student-dataset-context/LEARNING_COLLECTION.json \
  --student-archives lectures/tsr-sgblur-de-2026-10-26/output \
  --student-revision 8a18036ee9403a3487a55f397f82999a3911b99c \
  --classes lectures/tsr-sgblur-de-2026-10-26/praktikum/class-index.json \
  --output /tmp/youspeed-annotation-training-intake-2026-11-04 \
  --include-source-labels
```

The Panoramax export contains `as_of` and `records`; each record binds source,
picture, annotation and fingerprint to `crop_sha256`, native dimensions,
geometry, source labels and attribution. Its local PNG is named
`<crop_sha256>.png`. The CLI accepts any explicit exported selection matching
this contract; the town-sign example does not restrict corpus inclusion to
town signs.

`--include-source-labels` admits unique source labels with valid image and
attribution evidence while retaining `human_approved=false`. Visual proposals
remain in `review-queue.csv`. Supply `--reviewed-csv` with
`sample_id,label,reviewer` columns to admit explicitly reviewed examples.
The existing course `import_sorted_folders.py` remains the review route for
manually sorted course packages; the class folder is the reviewer's label.

The builder checks ZIP and PNG SHA-256 values, decodes each PNG and checks its
native dimensions. It preserves encoded crop bytes without resizing. Exact
German source codes also resolve through the shared DE catalog, intersected
with the selected 136-class index. The manifest records that catalog's SHA-256,
the mapping policy and all candidate classes; ambiguous source codes remain
withheld instead of selecting an arbitrary class. Exact
crop hashes and shared source annotation identities prevent repeated source
records from adding duplicate training samples; all original records remain
in `manifest.json`. Sequence, picture and declared group relationships remain
connected across providers and archives. These relationships do not establish
complete physical-sign independence.

Outputs are `manifest.json`, `class-index.json`, native `images/`, `train.csv`
and `review-queue.csv`. Training samples use the `train` split only. Validation,
calibration and independent test sets require their own reviewed grouping and
coverage. Use a new output directory for each build. Actual admitted training
counts are taken from the completed manifest after native images and labels
have been verified; inventory and candidate counts above do not predict them.

The completed 4 November intake retains 506 input records and 506 unchanged
native PNG objects as 436 deduplicated samples. Its 219 source-labelled training
samples comprise all 97 current town-sign crops and 122 other signs across 33
classes. The 217-sample review queue contains 195 visual proposals, 20
detection-only annotations and two ambiguous source codes. All admitted source
labels retain `human_approved=false`.

Focused checks:

```sh
python3 -m unittest discover -s tests/tsr -p 'test_source_annotation_labels.py'
python3 -m unittest discover -s tests/tsr -p 'test_student_crop_intake.py'
python3 -m unittest discover -s tests/tsr -p 'test_annotation_training_intake.py'
```
