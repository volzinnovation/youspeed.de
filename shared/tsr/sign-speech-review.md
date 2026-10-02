# Secondary traffic-sign speech review

Reviewed 2026-10-02 against the existing pinned model classes and national sign
codes, then integrated onto current main
`366132efd566da0e46833738f13e8ddf255bf199`. This is presentation metadata, not
legal-action or model validation. The locked speed-limit reference policy and
its Swift/Kotlin interpreter semantics are untouched.

## Contract

A sign's optional `speech` dictionary contains concise, independently selected
phrases for `de`, `en`, `fr` and `nl`. Missing speech means **stay silent**. Clients
must never derive speech from a class identifier, technical placeholder, artwork
filename or unreviewed label. `label` remains the explanatory display name.

Speech identifies a sign type. It does not infer supplemental plates, affected
lanes, vehicle-specific exceptions, distances, durations, recognized numeric
values, or a new speed limit. Non-speed numeric restrictions can identify the
type (for example, “Höhenbeschränkung”), but do not announce an unknown number.
Numeric speed signs and structural speed-context signs have no secondary speech.
The current baseline blocks generic numeric-restriction pictograms entirely;
those entries remain display-blocked and silent, even though generic wording had
been reviewed under the previous display contract.

Every speech entry is an existing `class_labels` member with
`display_eligible: true`. Class order, checkpoint hashes, sign codes, artwork,
existing provenance, eligibility and all country/review gates are unchanged.
In particular, Swiss metadata does not enable CH production recognition or
change its shadow/redistribution/legal-action review status.

## Coverage

| Country | Real display-eligible classes | Spoken in all 4 languages | Silent |
| --- | ---: | ---: | ---: |
| DE | 97 | 76 | 21 |
| FR | 98 | 77 | 21 |
| NL | 84 | 76 | 8 |
| BE | 88 | 67 | 21 |
| CH | 102 | 92 | 10 |

388 sign classes have 1,552 spoken phrases. Of the 81 silent display-eligible
classes, 70 are speed/structural classes and 11 remain ambiguous (FR 2, NL 1,
BE 8). Switzerland’s previous three ambiguous classes are now display-blocked
by the current baseline and are no longer counted as eligible omissions. All German secondary classes are
covered; its 21 omissions are speed/structural context. Reference-only aliases
and display-blocked classes do not gain speech. For example, `DE:310` is not a
new model capability, and the Netherlands' model vocabulary containing `no_stop`
does not create a missing display-catalog entry.

Catalog `provenance.speech_review` records the exact reviewed `(class_id,
sign_code)` pairs, the source URLs and a reason for every silent real
display-eligible entry. English/Dutch and cross-country labels are plain-language
translations, not official legal text.

## Sources

- Germany: official [StVO warning signs](https://www.gesetze-im-internet.de/stvo_2013/anlage_1.html),
  [regulatory signs](https://www.gesetze-im-internet.de/stvo_2013/anlage_2.html), and
  [information signs](https://www.gesetze-im-internet.de/stvo_2013/anlage_3.html)
- France: official [consolidated arrêté of 24 November 1967](https://www.legifrance.gouv.fr/loda/id/LEGITEXT000006075080/),
  especially articles 3, 3-1, 4, 5 and temporary-sign provisions
- Netherlands: [RVV 1990, Annex 1](https://wetten.overheid.nl/BWBR0004825/2026-07-01),
  the government's [English sign guide](https://www.government.nl/documents/2024/02/09/road-traffic-signs-and-regulations-in-the-netherlands),
  official [F13/F15 definitions](https://zoek.officielebekendmakingen.nl/stb-2017-181.html),
  [F5/F6 priority definitions](https://zoek.officielebekendmakingen.nl/stcrt-2019-71185.pdf),
  [C8 vehicle categories](https://zoek.officielebekendmakingen.nl/stb-2025-1.pdf), and
  [L14 emergency lay-by definition](https://zoek.officielebekendmakingen.nl/stb-2006-248.html).
  The English guide's F6 caption conflicts with its Dutch definition; the Dutch
  definition is authoritative
- Belgium: official [Flemish consolidated road rules](https://codex.vlaanderen.be/PrintDocument.ashx?geannoteerd=true&id=1023782),
  Wallonie's [A7 variants](https://securotheque.wallonie.be/equipements/signalisation-c/verticale/de-police/a7b-signaux-danger)
  and [cycle-zone definitions](https://securotheque.wallonie.be/e-amenagements-usagers-et-vehicules/velos/amenagements-cyclables/zone-cyclable).
  The [2024 decree and reproduced sign drawings](https://www.wegcode.be/nl/regelgeving/2024005817~0mocswfbry)
  were cross-checked where existing artwork provenance explicitly pins the 2024
  rendition. This is not an assumption that its future provisions already apply
- Switzerland: official [German SSV](https://www.fedlex.admin.ch/eli/cc/1979/1961_1961_1961/de),
  [French OSR](https://www.fedlex.admin.ch/eli/cc/1979/1961_1961_1961/fr), current
  version effective 2026-10-01, and [ASTRA sign overview](https://www.astra.admin.ch/de/signale).
  The historical cantonal police PDF is a cross-check only

## Corrections and safe omissions

### France

- B21d1 means ahead or right; B21d2 means ahead or left. The old technical labels
  reversed them. Labels and speech now follow the exact official codes
- C107 means a restricted-access road and C207 motorway **start**. Current main
  already corrected their technical labels and notes. Readable translations
  preserve that correction; both remain silent in the secondary lane
- A9 is a legacy identifier predating the current A9a/A9b split. No current
  subtype is inferred; speech stays absent
- B9i depends on the vehicle/trailer combination and weight. Its readable
  generic label is retained without automatic speech
- Height, weight, axle load, width and minimum-distance classes have readable
  generic labels but remain display-blocked and silent under the current baseline

### Netherlands

- C4 left/right are one-way-road signs, not turn obligations
- L14 is an emergency lay-by, not a rest area
- J24 includes cyclists and moped riders; C8 includes tractors, limited-speed
  motor vehicles and mobile machinery
- E8 (`parking:car`) specifies the depicted vehicle category. The exact subtype
  could not be independently matched to the absent pinned artwork; the label
  names the category requirement and speech stays absent

### Belgium

The catalog mixes legacy and 2024 artwork codes, so codes cannot be interpreted
without their existing artwork provenance. Actual mappings/artwork remain
unchanged. These conflicts require a separate mapping review:

- D1c points right at a junction but is mapped to `arrow_left_down`
- D1d passes left but is mapped to `arrow_right_down`
- D1e passes right but is mapped to `arrow_turn_left`
- D1f points left but is mapped to `arrow_right`
- D1g points right but is mapped to `arrow_left`
- 2024 C23 denotes buses but is mapped to `no_hgv`
- 2024 D10 ends the separated path but is mapped to its start
- 2024 D11 is a shared path but is mapped to a pedestrian-only path

Those eight classes are silent; labels identify the pinned code's sign. D3a and
D3b were visually checked and safely announce ahead-or-left/ahead-or-right.
A1c/A1d reverse the first-bend direction implied by the existing aliases; both
therefore announce only “double bend” without a direction. Legacy C22 correctly
identifies coaches. C8's agricultural prohibition is identified from the pinned
2024 source; no rollout or legal-applicability gate is changed.

Current main independently corrected `maxheight` from C27 (width) to C29
(height), removed its numeric artwork and made it display-ineligible. That fix
is preserved, with a readable height-restriction label and no speech.

### Switzerland

The following earlier conflicts are now display-blocked by current main, and
remain silent:

- `hazard:horse` points to 1.24a (wild animals), not riders
- `no_exit:car` points to 4.10 (water protection area), not a dead end
- `zone:no_parking:end` points to an unverified 2.59.2e artwork variant; the base
  2.59.2 only establishes end of a signposted zone

Those three classes stay display-blocked and silent. Labels identify verified
base-code meanings without overriding the newer notes, image paths or gates.
1.15 announces barriers without assuming a railway: barriers may also protect
airfields. 1.28 aircraft is supported by the current ordinance, despite the
historical 2017 edition omitting it. The 10 remaining display-eligible omissions are primary-speed or
structural classes; other previously silent classes were also display-blocked
upstream.

## Integration onto current main

All five ordered class vocabularies and checkpoint hashes are unchanged from
the initial review. Current main expands foreign catalogs to include all actual
model outputs, mostly with `display_eligible: false`. It also removes unsafe
numeric art, preserves new audit notes, corrects Belgian height to C29, and
blocks three Swiss mapping conflicts. Every one of those upstream fields is
preserved byte-for-value in the metadata contract fingerprint.

377 existing reviewed speech entries transfer unchanged. 22 older spoken entries
are now display-blocked and lose speech: FR 7, NL 5, BE 2, CH 8. Eleven newly
display-eligible entries received a source-backed meaning review:

- NL B01 priority road; B04/B05 priority over a side junction from left/right
- NL J02/J03 right/left bends and J05 double bend with first bend left
- NL F04 end of the lorry overtaking ban and F14 end of the bus lane
- NL L08 dead end
- BE A1a/A1b left/right bends

These definitions were rechecked in the official government sign guide,
Staatsblad 2017/181 (F14), and the Belgian decree/sign tables linked above.
The current `mapping-review-v1.json` gives every spoken entry a non-speed
semantic (`unknown` or `non_speed_restriction_end`). Road applicability remains
an independent runtime gate; this review does not alter or enable it.

## Offline regression tests

Run `python3 tests/tsr/test_sign_speech_catalog.py -v`.

Nine tests cover four-language completeness, exact reviewed scope, explicit
omissions, requested examples, no technical identifiers, short phrases, upstream numeric/artwork
blocks, all eleven new display mappings, national-code corrections, and immutable fingerprints of every
non-label/non-speech field against baseline
`366132efd566da0e46833738f13e8ddf255bf199`. They need neither model/artwork downloads
nor pytest. Missing large asset files prevent the existing full-artwork/model
suite from running in this checkout; that is distinct from these metadata checks.
