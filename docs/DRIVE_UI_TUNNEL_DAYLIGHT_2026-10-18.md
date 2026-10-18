# Driving controls, Gernsbach tunnel and nighttime TSR — 18 October 2026

## Changes

Both apps now show ordinary controls only when the screen faces up within 10°
of horizontal and the speed gate allows interaction. Either raw or displayed
speed above 20 km/h locks controls regardless of posture. Fresh speed at or below
20 km/h can restore that gate; invalid/stale GPS cannot clear a moving lock.
Missing posture does not establish that the phone is flat. Permission and native
review prompts continue to require fresh measured standstill.

The manual shutter retains its existing >1 km/h visibility threshold. It replaces
Settings on the same bottom-right action-row baseline, including in both landscape
mounts and right-to-left layouts. Other controls keep their existing slots. It
remains independently available while the ordinary controls are hidden.

iPhone circle sizing uses the dimensions from before the supplementary OCR
reservation. Supplementary text is accommodated in the workspace so it does not
shrink the speed-limit circle. The workspace keeps its reservation stable as text
arrives and expires.

Both clients calculate solar elevation offline from coordinates and the current
absolute UTC instant, using the [NOAA general solar-position equations](https://gml.noaa.gov/grad/solcalc/solareqns.PDF).
Camera TSR is paused below the standard sunrise/sunset horizon of −0.833°.
UTC avoids ambiguous local times and country-specific daylight-saving rules;
leap years, opposite hemispheres, the date line and polar day/night are covered.
Unknown/invalid coordinates leave camera TSR paused. The last known coordinates
are reevaluated each second during a drive, so sunset does not require a new fix.

The saved TSR selection is preserved. Sunrise permits new recognition; it cannot
restore an old camera assertion. At night, in-flight generations and transient
signs are invalidated and camera authority is withdrawn through the existing
reference-policy event. The current bundle is offered again; voice corrections
retain their existing priority. Recording and photos remain independent. Neither
the versioned speed-reference policy nor its interpreter semantics was changed.

## Attached-device evidence

Read-only copies of app logs were obtained from the attached iPhone 14 Pro and
Moto g86. Raw traces and the copied map remain outside the repository under
`/private/tmp/youspeed-20261018-evidence/`; no device evidence was deleted.

The iPhone evening session is `20261018_161838_540_drive_match_log.ndjson`, with
recognition diagnostics in the corresponding `...542_tsr_log.ndjson` session.
The Android evidence is its current `drive_match_log.ndjson`, GPS log and a tail
of runtime diagnostics. Android's active-bundle metadata points at Hessen, while
the installed Baden-Württemberg database has the same verified SHA-256 as the
iPhone copy. The active metadata alone does not identify the database used at
every regional fix.

Between 19:04 and 19:07 CEST in the Gernsbach area, the copied logs contain 178
iPhone matches and 109 Android matches. Neither app reports any tunnel match or
active tunnel mode. iPhone rejects tunnel candidates at 86 fixes, then selects
surface streets such as Isemannweg while accuracy worsens.

The exact iPhone database was copied and its SHA-256 verified against the
installed metadata:

`4f447cf8afc5faba75dc7a582ba89fc7173c86bae1f4a85d0402185f880bcc22`

This July 4 Baden-Württemberg bundle contains `way_endpoints` and normalized
continuity tables, but no legacy `way_links` table. The matcher treated the
missing table as missing portal connectivity, even though the B 462 approach
(3810614) and Tunnel Gernsbach (4287421) share an exact endpoint key.

Both clients now recover exact tunnel portal connections and shared-reference
relationships from endpoint keys for this schema. Surface-only diagnostic
matching retains its previous behavior. No distance-based or shared-ref-only tunnel
admission was added, and the legacy-table path is unchanged.

An offline replay of the iPhone fixes 1480–1608 against that verified installed
database now produces 86 tunnel matches, starting at fix 1507 and ending at 1592,
then returns to a surface road. The original recorded window has zero tunnel
matches. This replay validates matcher selection; a new real drive is still
needed to confirm the complete device presentation and sensor behavior.

The evening iPhone TSR log retains camera authority at 19:17:59 CEST, after dark.
The solar function places the sun near −5.98° at the Gernsbach passage around
19:05 CEST. These logs demonstrate that camera recognition remained admitted
at night; they do not establish a labeled nighttime recognition accuracy or
prove a model crash. The new gate prevents these nighttime camera offers.

## Validation

- Android: 715 unit tests, zero failures/errors, one existing skipped case.
- Attached Moto g86: all 18 instrumented matcher, control, capture and daylight
  tests pass in the isolated testhost, including narrow right-to-left layout.
- iPhone simulator: 18 targeted unit/controller tests pass, including night
  withdrawal and bundle restoration; manual capture and stable OCR geometry
  pass in portrait and both landscape mounts. The final shutter threshold/layout
  run passes all 18 combinations of speed/orientation, including the explicit
  right-to-left mount: Settings is replaced, ordinary controls hide above 20 km/h,
  and the shutter shares the physical action-row position.
- Shared reference contract: all 39 scenarios / 171 steps pass, covering all 16
  transitions and five states; artifact hashes and both app pins match.
- Verified-map replay: 129 fixes, 86 consecutive tunnel matches, correct return
  to the surface road. Evidence hashes are retained in `evidence-manifest.json`
  beside the private copied files.

Tests use isolated containers. The normal apps installed on the phones have not
been replaced. A new real drive is needed to confirm complete on-road behavior.
