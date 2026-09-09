# Mobile copyright and attribution review — 2026-09-10

The review corrected missing in-app credits and licence access. It found no
contradiction in the selected sign artwork's public-domain declarations. It
does not establish complete legal clearance for all model training inputs or
every distribution channel.

## Artwork and mapping evidence

- **104 shared sign images:** every current Commons file record declares public
  domain, with attribution not required. Every exact page revision pinned in
  the image manifest retains the German-government official-work template.
  `commons-file-revisions.json` retains the page/revision IDs, revision content
  hash and declarations. Each original SVG and PNG also passes the offline hash
  verifier. The legal basis cited by Commons is [§5(1) UrhG](https://www.gesetze-im-internet.de/urhg/__5.html).
- **Per-image credits:** source revision, digitization author, original source,
  licence basis and rendition changes are now visible in both apps' Info.
  White backgrounds were removed in native UI code; the original artwork bytes
  and required white sign faces remain unchanged.
- **Existing pedestrian-zone artwork:** the separate 242.1 source was checked
  independently. The iPhone SVG differs from the original only by a final
  newline; Android uses a vector conversion. Mediatus is credited.
- **Mapping correction:** deployed `class_maps/DE.json` is not a file at the
  pinned upstream Prolix commit. All 142 entries match the DE column of the
  [Panoramax CSV at 7a811057](https://huggingface.co/Panoramax/classify_nl_road_signs/blob/7a811057049f6de207f909c0f1be2905fa9baf01/road_signs_mapping.csv)
  after the recorded sign-code normalization. The repository card declares
  Etalab 2.0. Panoramax, the source date and adaptations are credited and the
  full licence is included. Prolix's MIT licence is credited separately.
- **Bernbach photograph:** the source API confirms author `admin`, CC BY-SA 4.0
  and the fixture's bytes. It remains an Android test asset. Info identifies it
  as a diagnostic reference, not production artwork. Existing Panoramax test
  frames retain their photographer, source and CC BY-SA credits.

## Sources and software notices

The shared offline catalog includes the image credits, OpenStreetMap/Geofabrik,
all bundled countries' rule-source citations, model/checkpoint and conversion
sources, Prolix and the actual mapping source, the font and resolved Android
runtime components. Source and licence links are available in native screens.

The Android font's prior short credit omitted `usr_share`. The full embedded
OFL 1.1 licence and both copyright holders are now included. Embedded Android
AAR/JAR licence files are retained, including LiteRT's additional notices and
JNA's dual-licence declaration. Both apps expose full model notices offline;
Android previously did not expose those bundled notices in Info.

The binary and Vosk's 0.3.75 build recipe also identify native OpenBLAS,
CLAPACK/libf2c, Kaldi and OpenFst dependencies. Their full upstream notices are
now included. The recipe does not pin Kaldi/OpenFst commits, so the reviewed
notice revisions are not represented as proven binary revisions. The Android
model export report's ONNX, onnx2tf, TensorFlow and Python LiteRT versions are
credited separately from the shipped LiteRT runtime and iPhone conversion tools.

Full source declarations are recorded rather than replacing each component's
licence with the app's AGPL licence. No Wikipedia article text was copied into
the image catalog. Rule-source links identify references; they do not relicense
the original publishers' websites.

## Remaining model-release questions

The repository's existing [training-source manifest](../../shared/tsr/training-sources-v1.json)
and [training round-trip document](../TSR_TRAINING_ROUND_TRIP.md) require a
documented assessment of the Panoramax classifier's CC BY-SA training-data
lineage and Ultralytics obligations before a public model release.

The app itself is already AGPL-3.0. That is not evidence of an incompatibility.
The missing conclusion is whether the exact distributed model, corresponding
source/build materials and intended distribution satisfy all applicable
obligations. The [upstream AGPL text](https://www.ultralytics.com/legal/agpl-3-0-software-license)
sets conditions beyond attribution; adding credits alone does not resolve
that assessment. The model card's Etalab declaration is recorded as the
publisher's declaration, not a warranty about its training-data rights.

This change does not silently mark those existing release gates approved, buy
an enterprise licence, remove working recognition, or publish a new release.
Publishing these source and attribution updates does not approve those model-release gates.

## Validation

See `summary.json` for source-audit evidence. Run the shared asset verifier and
attribution tests with the commands in [the attribution README](../../shared/attributions/README.md).
Native package/resource checks and UI screenshots verify that the credits are
available from Info and readable offline on both platforms.

Completed for this change:

- Shared attribution/catalog checks: 8 passed; all 104 SVG/PNG pairs verified.
- Android: Debug and Release builds, 181 unit tests per variant, both lint
  variants, and the final native Info navigation test passed.
- iPhone: Debug simulator build and 3 focused resource tests passed; unsigned
  Release device build passed. Native source and complete-notice views checked.
- All four app packages contain the same 220-entry source catalog and complete
  shared notices, with byte-for-byte comparisons against the source files.
- UI controls include DE, EN, FR and NL. Native visual checks used DE on iPhone
  and EN on Android; this is not a claim of a full multilingual regression run.

The catalog SHA-256 is
`12c332c10713de5c58d1187f9b29bcade749ace4e8497b46e41769751c65d172`;
the shared notices SHA-256 is
`fcb93bd43eeb0b36651ae46b11d9cc569cb00101ae4818477b7439b638b5ad87`.
No physical-device deployment or public distribution was performed in this
attribution update.
