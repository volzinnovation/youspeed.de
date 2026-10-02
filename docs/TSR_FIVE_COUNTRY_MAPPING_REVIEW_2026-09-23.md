# Five-country sign mapping and France field corrections

Reviewed the ordered classifier vocabularies, speed actions, display catalogs,
national artwork references and both mobile manifests. The machine-readable
record is [mapping-review-v1.json](../shared/tsr/mapping-review-v1.json).
It contains one row for each of the **820 actual model outputs**. This is a
mapping audit; it does not measure recognition accuracy on road video.

| Country | Classifier outputs | Actionable speed mappings | Principal corrections |
| --- | ---: | ---: | --- |
| DE | 134 | 22 | Preserve the number on a zone end; distinguish speed/all-restriction ends from overtaking ends. |
| BE | 143 | 21 | Restore road defaults after C46; preserve zone-end values; a mandatory footpath is not a pedestrian zone. |
| FR | 256 | 31 | Add omitted numeric speeds and B33 ends; correct B30/B51, B52/B53, B54/B55, C108/C208; C207 starts an autoroute, C107 starts a motorroad, B41 ends a mandatory footpath. |
| NL | 160 | 22 | Add omitted numeric speeds and zone ends; restore F08 behavior; B01 is a priority road; reconcile exact classifier spellings with artwork. |
| CH | 127 | 18 | Correct 20-zone and pedestrian-zone transitions; parking and other unrelated ends cannot clear speed. Quarantine three incorrect artwork associations. |

There are 53 changed or newly actionable semantic mappings compared with the
previous branch commit. Other actual outputs now have an explicit `unknown`
speed action, independently of whether a pictogram is available. Ordered model
indices and weights are unchanged. Both platforms use identical mappings.

## Artwork findings

- Unnumbered restriction ends use the shared national assets: DE 282, BE C46,
  FR B31, NL F08 and CH 2.58. They replace the main speed circle briefly.
- A classifier family such as `maxheight` does not identify the printed number.
  Numeric example artwork is no longer presented as the observed value.
  Numbered speed-end actions retain a value when the model provides one; where
  an exact numbered rendition is unavailable, the official unnumbered national
  restriction-end pictogram is used. Zone ends never borrow that round sign.
- The CH source fallback had mapped `hazard:horse` to a deer (1.24),
  `no_exit:car` to water protection (4.10), and `zone:no_parking:end` to an end
  of a 30 zone (2.59.2). These pictures are disabled. The original provenance
  remains available for investigating the training/source-label mismatch.
- Dutch PNG metadata was stale after earlier red-ring and L14 rendition
  repairs. Checksums now describe the existing committed artwork, with the
  earlier checksum and repair commit retained. This change edits no image bytes.
- No country sign is redrawn in platform UI code.

## Runtime corrections

A fresh, sufficiently accurate location can select the France model while an
older Belgian map remains active. A later map refresh cannot undo the confirmed
country selection. Poor or stale positions do not trigger a country switch.

User-entered corrections precede camera values in both the indexed store and
the runtime resolver. A new camera sign cannot overwrite an applicable manual
correction. Entering or leaving a city clears an old posted camera limit even
when the corresponding earlier boundary was missed. Existing zones are kept
separate from the city layer.

Restriction ends resolve against the enclosing zone/city or a supported road
default. If that default is not established, the old limit is cleared and the
result is unknown. Belgian regional defaults use official regional geometry
with a boundary uncertainty margin. Dutch motorway defaults remain unresolved
without the signed/time-dependent regime. The policy covers ordinary passenger
car defaults, not every vehicle, weather, carriageway or local exception.

## PACA topology and exit signs

Used the requested [PACA release](https://github.com/volzinnovation/youspeed.de/releases/tag/provence-alpes-cote-d-azur),
published 2026-09-15, bundle version 2026-07-03. Uncompressed SQLite SHA256:
`301694c7f56686b0d3d9bb5e70603e62b4c59f32a1b7ddba52f1d52701edfe29`.
The database has endpoint coordinates but no `way_links` table. The clients
now query nearby motorway links separately from the narrow road-matching
window and derive shared-endpoint branches without rebuilding the bundle.

The public [SQL regression fixture](../shared/tsr/applicability/paca-exit-topology-v1.sql)
contains 26 actual roads and their network membership around the supplied
Avignon exit example. Mainline ways 135439915 and 4355708 meet ramp 4077706.
The fixture verifies the phone's default M7 matcher before the fork, continuing
on the mainline, and on the ramp. It does not contain a recorded trip.
The Pierrelatte through-traffic example is outside PACA coverage.

A bounded active filter withholds right-side 30–90 signs close to a connected
exit when the vehicle is confidently matched to a motorway with an explicit
map limit of at least 100. It stops withholding on the ramp. Paired same-value
signs on both sides of the mainline remain eligible. Poor/stale GPS, unrelated
parallel roads and opposing branches do not activate the filter. Withholding
cancels pending fusion/passages instead of treating the sign as passed.

This is a topology heuristic, not recognition of the supplementary arrow.
It can miss signs farther from the junction and can withhold a genuine
one-sided mainline restriction near an exit. It needs real drive validation;
the broader applicability policy remains in shadow mode. Here, “shadow” means
it records a proposed decision without changing driving state. The explicit
exit filter and the other corrections above are active.

## Remaining model/data gaps

- DE, NL and CH classifier vocabularies do not include city-entry/exit classes.
  Inventing aliases cannot add recognition capability. FR and BE have those
  classes. Missing legal settlement context can therefore still leave a city
  transition unresolved, especially with older bundles.
- The PACA release has no legal settlement-context tables. Administrative
  city polygons are not treated as evidence of legally signed built-up areas.
- Swiss evaluation/rollout gates remain unchanged. Correcting its metadata
  is not certification of Swiss visual accuracy or a change to those gates.
- Some implicit regulations, including bicycle-road regimes, remain outside
  the implemented speed-action vocabulary. Unknown actions are intentional;
  the ledger must not be read as proof that every legal effect is implemented.
- No reviewed real driving-sequence corpus was supplied. Synthetic parity,
  source-code tests and a real topology fixture cannot establish field recall
  or false-warning rates.

## Verification and reproducibility

- `python3 scripts/tsr/mapping_review.py`: no drift; `--write` reconciles both
  platform manifests, catalogs, readiness hashes and the ledger.
- `python3 -m pytest tests/tsr -q`: 331 passed.
- iPhone `SpeedConsumerTests`: 335 executed, 23 skipped, zero failures.
  Physical-device/full-image checks are among the skipped tests.
- Android `:app:testDebugUnitTest`: 327 passed.
  `:app:compileDebugAndroidTestKotlin` passed. No Android device was attached,
  so the instrumented PACA lookup and on-device parity were not exercised.
- Actual Swift/Kotlin policy replay: identical output for 41 synthetic
  scenarios; evidence is in
  [synthetic-parity-report-v1.json](../shared/tsr/applicability/synthetic-parity-report-v1.json).
- Shared-policy generation and `git diff --check` passed.

## Next drive checks

Before driving, confirm that the model status shows FR and that the appropriate
French map is downloaded. Start the usual recording. A passenger can note the
time of each case; do not interact with the phone while driving.

1. Stay on an autoroute past an exit's 90/70/50 sequence: the ramp signs should
   not lower the mainline limit. Also check a genuine mainline restriction.
2. Take an exit: after the road match moves onto the ramp, its signs should
   apply. Record any delay or missed sign.
3. After a restriction-end sign, expect its large national pictogram briefly,
   followed by the supported default or unknown if context is insufficient.
4. Check a city entry and exit, noting whether an older limit disappears.
5. Enter a correction while stopped or through the supported voice control:
   subsequent camera recognition on that road must not replace it.

Keep the logs and dashcam segment around unexpected behavior. These checks are
for validating the app; the actual road signs govern driving.

## Primary references

- [DE StVO Annex 2](https://www.gesetze-im-internet.de/stvo_2013/anlage_2.html).
- [Belgian road regulation and sign inventory](https://www.codedelaroute.be/fr/reglementation/1975120109~hra8v386pu).
- [French sign regulation](https://www.legifrance.gouv.fr/loda/id/JORFTEXT000000829916/2024-04-22)
  and [ordinary speed regimes](https://www.service-public.gouv.fr/particuliers/vosdroits/F19460).
- [NL RVV Annex 1](https://wetten.overheid.nl/BWBR0004825/#Bijlage1)
  and [motorway limits](https://www.rijksoverheid.nl/vraag-en-antwoord/verkeersveiligheid/wat-is-de-maximumsnelheid-voor-auto-s-op-de-snelweg).
- [ASTRA official Swiss signs](https://www.astra.admin.ch/fr/signaux),
  [Basel-Stadt official sign inventory](https://api.geo.bs.ch/geometa/v1/metadata_details/dataset/published/html/eb581512-120d-4ce5-b3d5-48541a3a0768)
  and [Swiss ordinary speed regimes](https://www.ch.ch/de/fahrzeuge-und-verkehr/verhalten-im-strassenverkehr/verkehrsregeln/geschwindigkeitsuberschreitung/).
