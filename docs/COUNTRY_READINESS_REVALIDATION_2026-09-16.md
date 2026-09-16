# France, Netherlands and Belgium readiness revalidation

Revalidated on 16 September 2026. This review separates legal warning rules,
speech input/output, and traffic-sign recognition. A country is not release-ready
for the full product until all three are ready on both mobile clients.

## Result

| Area | France | Netherlands | Belgium |
| --- | --- | --- | --- |
| Legal warning rules | Ready for the scoped ordinary passenger-car warning model | Ready for the scoped warning model; exact tariffs remain context-dependent | Ready only for the current-code scoped warning model; zone type and administrative fee remain explicit qualifiers, and the 2027 Belgian code transition must be pinned before release |
| Android offline speech input | Bundled Vosk `vosk-model-small-fr-0.22` | Bundled Vosk `vosk-model-small-nl-0.22` | Uses Dutch or French profile; no separate Belgian language is required |
| iPhone offline speech input | Uses `fr-FR` and requires an available Apple on-device locale | Uses `nl-NL` and requires an available Apple on-device locale | Uses the selected Dutch/French profile and the same on-device requirement |
| Speech generation | Localized TTS profile | Localized TTS profile | Localized Dutch/French profile |
| Traffic-sign pictograms | Expanded reviewed set: 114 SVG/PNG pairs (111 Panoramax-linked + 3 preserved core) | Expanded reviewed set: 111 SVG/PNG pairs | Expanded reviewed set: 115 SVG/PNG pairs (111 Panoramax-linked + 4 preserved core/transition); B7 retained only as legacy/transition artwork |
| Country TSR model pack | Not ready; registry has no reviewed runtime manifest | Not ready; registry has no reviewed runtime manifest | Not ready; registry has no reviewed runtime manifest |

The legal JSON files are byte-identical between iPhone and Android and now carry
`source_checked_at: 2026-09-16`. France uses the current standard fine and
French point bands, including the criminal classification from +50 km/h.
Netherlands and Belgium intentionally do not invent scalar points or fixed ban
durations where the official material makes the result context-dependent.

Bundle targets for DEU, FRA, NLD and BEL now carry the matching rule artifact
(`DEU/FRA/NLD/BEL-rules.json`). The release workflow passes that mapping into
the v3 publisher; the manifest carries the checksum-pinned `penalty_rules`
artifact, both clients download and verify it with the bundle, and the active
country uses that installed file when available. The bundled rule file remains
the offline fallback.

## Official legal sources checked

- [France: excès de vitesse](https://www.service-public.gouv.fr/particuliers/vosdroits/F19460)
- [France: criminal classification for very high excess speed](https://www.service-public.gouv.fr/particuliers/actualites/A18723)
- [Netherlands: speed enforcement and criminal thresholds](https://www.om.nl/onderwerpen/v/verkeer/handhaving/snelheid-en-te-hard-rijden)
- [Netherlands: licence seizure](https://www.om.nl/onderwerpen/v/verkeer/handhaving/rijbewijs/inhouding-rijbewijs)
- [Belgium: official immediate-settlement tariffs and referral thresholds](https://mobilit.belgium.be/nl/weg/rijden/wegcode-verkeersregels-en-sancties/sancties/boetes-en-onmiddellijke-inningen)
- [Belgium: FOD Mobility update recording the postponed public-road-code date](https://mobilit.belgium.be/nl/file/12543/download?token=32rGuX0v)

## Sign-set decision

`shared/tsr/sign-pictograms/national-set-index-v1.json` is the authoritative
set index. Germany is active. France, the Netherlands and Belgium are
`artwork_ready` but have `runtime_status: not_ready`: their country-separated
manifests contain expanded reviewed SVG/PNG artwork, official regulation links
and model-code mappings, while every runtime model class remains null. The Belgian
mapping now follows the new catalogue: B1 is give-priority, B5 is stop, and B7
is retained only as a legacy/transition stop-ahead artwork. Numeric speed-sign
artwork is not used as a runtime override; the existing schematic speed-limit
UI exception remains in force.

The remaining release blockers are independent TSR evaluation, calibrated model
weights, export parity, full legal-action semantic review, device parity, and
runtime model manifests for each foreign pack. The expanded artwork and the
complete Panoramax model-code country mapping are now materialized, but these
countries are therefore
not yet full-product ready despite the speech and legal-rule support. The owner
handoff and exact evidence contract are listed in
[FOREIGN_TSR_COMPLETION_CHECKLIST.md](FOREIGN_TSR_COMPLETION_CHECKLIST.md).

Belgian legal/sign coverage has an additional date gate: the official new Code
de la voie publique catalogue is effective 1 June 2027, while older publication
pages showed 1 September 2026. The Belgian runtime pack must pin the effective
date and sign catalogue that the release is intended to cover; it must not
combine old-code artwork with new-code semantics without an explicit transition
policy.
