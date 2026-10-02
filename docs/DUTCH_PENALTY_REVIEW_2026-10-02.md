# Dutch penalties reviewed anew — 2 October 2026

At the product owner’s request, Dutch monetary estimates now replace the generic “! Prüfen” display when the matched road category and posted limit are known. Both native engines consume the same `shared/Rules/NLD-rules.json`, revision `20261002`; an older downloaded revision cannot supersede it. The protected speed-reference policy is unchanged.

The fresh review used the [OM Feitenboekje 2026](https://www.om.nl/site/binaries/site-content/collections/documents/mulderbundel/map/map/mulderbundel-2026/Feitenboekje%2B2026.pdf), effective 1 January 2026, speeding category C1 (ordinary passenger car without trailer). Its SHA-256 is `9cf20d3369ca4e7063074343ef088a962bc6094cdd92aadecef16af5f1f67d65`. All [three published errata](https://www.om.nl/documenten/mulderbundel/map/map/mulderbundel-2026) were reviewed; they concern turning lanes, special mopeds and emission systems, not these speeding tariffs. The earlier Staatscourant advisory annex is not the final tariff source: its motorway cap of 520 differs from the final 524.

The JSON holds 145 per-km/h context entries, including ordinary urban VA, urban 30-km/h VS, urban 15-km/h woonerf VV, rural VF and motorway VL rates. The [live OM calculator](https://www2.om.nl/snelheidsovertredingen/) independently confirmed urban corrected +12 → 140 EUR, motorway corrected +37 → 524 EUR, and the 130-km/h motorway exception (+1/+2/+3 → 12/16/22 EUR). The [OM tariff page](https://www.om.nl/onderwerpen/b/boetebase) identifies the separate 9 EUR administrative fee; it is included in localized details, not added silently to the dashboard’s base fine.

| Ordinary context | Displayed / illustrative corrected excess | Dashboard estimate |
| --- | ---: | ---: |
| Urban, posted 50 | +12 | 140 EUR |
| Urban 30-km/h zone | +12 | 194 EUR |
| Rural | +12 | 134 EUR |
| Motorway | +12 | 126 EUR |
| Motorway, posted 130 | +1 | 12 EUR |
| Motorway | +39 | 524 EUR |

The engines deliberately retain the existing product convention: displayed GPS excess is used illustratively as corrected excess; no police measurement deduction is applied to GPS speed. [Official measurement correction](https://www.om.nl/onderwerpen/v/verkeer/handhaving/snelheid-en-te-hard-rijden/marges-en-meetcorrecties) can therefore yield a different amount. For example, a police measurement of 62 in a 50 zone becomes 59 after a 3-km/h correction: corrected +9 gives 84 EUR, plus the fee. The ordinary lower threshold is corrected +4; on a motorway posted at 130 it is +1. A known ordinary below-threshold context displays 0 EUR with an explicit explanation, not permission to speed.

Unknown/trunk/link-only road categories or a missing limit suppress exact figures and say “Road type” / “Straßenart” / “Type de route” / “Wegtype”. Outside the implemented administrative table, the UI shows a scales symbol and a localized criminal-assessment label, rather than a fictitious scalar fine or “Prüfen”. The urban 30 and woonerf tables end at +29; their +30 police criminal tariff is intentionally not presented as an administrative fine. Ordinary roads end at +30; motorway administrative rates end at +39. Licence seizure at +50 remains a contextual warning. No points or fixed ban duration are invented. Roadworks, trailers, other vehicle classes and repeat offences are not assumed.

Validation uses `shared/penalty-rules-tests/NLD-cases.json`: 175 independent source/boundary/context vectors, exercised by production Swift and Kotlin engines in all four core runtime languages. The Android dashboard test additionally checks visible urban/rural/motorway amounts, criminal labels, unknown-road fallback and stale-reference suppression. Fresh native iPhone captures confirm country selection and 140 EUR in all four core locales; Android captures cover all nine store locales. The source dictionaries and JSON aliases are also exercised by the shared documentation tests.

The previously exported 1.3 (10031) IPA and unsigned AAB predate this update and the documentation view. They need rebuilding before upload; this work does not claim those earlier binaries contain the new functionality. No physical-device deployment or store submission was performed.
