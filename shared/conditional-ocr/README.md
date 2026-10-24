# Conditional OCR evidence, version 1

`templates-v1.json` is a shared Swift/Kotlin parser fixture. A supported parse
preserves the full recognized restriction; partial/truncated or residual text is
not stripped to obtain an executable clock. The pure interpreter separates
candidate text, verified complete assembly and current applicability.

Verification requires explicit complete-assembly, exact parent/plate association,
quality, country, source and scope evidence, plus two distinct supporting frames.
Current applicability retains the original evidence origin and 300-second/5-km
limits. Wetness remains unknown without qualified road-surface evidence; clock
evaluation uses Berlin civil time, half-open windows and overnight start-day
anchors. A source annotation with `evaluation_enabled=false` cannot become
runtime-eligible through parsing alone.

The native live adapters carry the captured frame identity, observation time,
primary bounds, measured panel bounds and full OCR reads. The live tracker checks
that evidence before creating a verified record. Supported conditional signs
require complete readable assemblies in two distinct captured frames; two OCR
passes over one image count as one frame. Plain numeric signs also require
measured clear lower-area evidence. Missing, clipped, blank or ambiguous panels
remain unresolved. A no-text read or absent detector result does not prove that
a restriction is absent.

Live conditional authority also requires the existing positive road/lane
applicability decision and verified bundle lineage. Clock reevaluation uses the
existing applicability revision mechanism and retains original observation
anchors. A newer physical sign retires older conditional evidence, including an
older rule that has never been active. Explicit corrections retain priority and
do not permit discarded camera authority to reappear after correction expiry.

Camera-to-bundle same-rule quarantine still requires positive identity evidence.
Matching only speed, way, time or proximity cannot establish that identity. This
implementation uses the existing native OCR and measured image checks; no new
trained assembly model or field recognition improvement is claimed.

See [`CONDITIONAL_SPEED_LIMITS_OCR_SPEC.md`](../../docs/CONDITIONAL_SPEED_LIMITS_OCR_SPEC.md)
and the [current implementation and verification receipt](../../docs/CONDITIONAL_RESTRICTIONS_2026-10-24.md).
