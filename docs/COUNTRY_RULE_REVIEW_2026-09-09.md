# France, Netherlands and Belgium penalty rules

Reviewed on 9 September 2026 for the Android and iPhone passenger-car warning
cards. The two platforms contain byte-identical JSON for each country. This is
a review of the app's illustrative warnings, not a determination of an
individual driver's liability.

## Corrections supported by official sources

**France.** Below a retained excess of 20 km/h, the posted limit determines the
standard fine: €135 at limits of 50 km/h or less, €68 above 50. An urban/rural
flag cannot substitute for that limit. The six point-deduction bands are
0/1/2/3/4/6 in the French system; they must not be presented as German penalty
points. At +30 and +40, the €135 standard fine can accompany a judicial licence
suspension of up to three years; this is not an automatic duration.
[Service Public's speeding guide](https://www.service-public.gouv.fr/particuliers/vosdroits/F19460)
was verified by its publisher on 29 December 2025.

An excess of **at least 50 km/h** has been a criminal *délit*, including a first
offence, since 29 December 2025. A €300 fixed criminal settlement is one
available procedure, while the court fine can reach €3,750. Therefore €300 is
not stored as the single expected fine. The card retains six French points
and describes possible licence sanctions without an invented mandatory ban.
See [Service Public's notice, updated 7 January 2026](https://www.service-public.gouv.fr/particuliers/actualites/A18723)
and [Code de la route, Article L413-1](https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006074228/LEGISCTA000006159544).

**Netherlands.** The old €50/€120/€240/€350/€480 approximations are removed.
Exact tariffs vary by corrected excess, road, vehicle and roadworks. Ordinary
criminal handling starts **above +30**, but **at +40 on motorways**. This is
inclusive of +40: the 2026 table lists VL039 as administrative (`m`) and VL040
as prosecutorial (`p`). At +50 or more, police seize the licence when the driver
is stopped; the prosecutor or judge determines the subsequent duration.
[OM's current speeding guidance](https://www.om.nl/onderwerpen/v/verkeer/handhaving/snelheid-en-te-hard-rijden)
and [Feitenboekje 2026, printed page A38, PDF page 64](https://www.om.nl/site/binaries/site-content/collections/documents/mulderbundel/map/map/mulderbundel-2026/Feitenboekje%2B2026.pdf)
support these distinctions. No general points score, court fine or fixed ban
duration is inferred.

The +1–3 warning does not promise that no fine applies. After correction, OM
specifies an ordinary +4 threshold at limits up to 120 km/h, but **+1 when the
limit is 130 km/h**. This detail appears in the
[official trajectory-control FAQ](https://www.om.nl/onderwerpen/v/verkeer/handhaving/snelheid-en-te-hard-rijden/trajectcontroles).

**Belgium.** From **1 July 2026**, the ordinary immediate-settlement base is
€58 for the first 10 km/h, then €12 per additional km/h in built-up/protected
areas and €7 elsewhere; the 2026 administrative fee is another €10.67. The old
€53 base and arbitrary higher totals are removed. The higher-rate contexts
include zone 30, school surroundings, residential and shared zones. Referral
thresholds are above +30 in these contexts and above +40 on other roads.
Because the app lacks complete zone and procedural context, only the base
band has a scalar amount, expressly excluding the fee. Higher cards explain
the formula or referral risk, with no general points score or fixed ban.
Sources: [Federal Mobility's July 2026 increase](https://mobilit.belgium.be/nl/news/onmiddellijke-inningen-verhoging-van-de-bedragen-op-1-juli-2026),
[official police tariff notice, 7 July 2026](https://www.police.be/shape/fr/actualites/amendes-routieres-ce-qui-change-des-le-1er-juillet-2026),
and [Federal Mobility's excessive-speed contexts](https://mobilit.belgium.be/fr/faq/quelles-sont-les-infractions-en-matiere-de-vitesse-qui-sont-visees).

## Runtime contract and limits

Legal thresholds use **officially retained/corrected excess**. GPS speed minus
a detected limit is an illustrative input, not an enforcement measurement.
Do not subtract a universal tolerance: authorities distinguish measurement
correction, enforcement thresholds and equipment. The app needs a localized
notice explaining that no enforcement tolerance has been deducted and that
the displayed penalties are indicative. See
[ANTAI's measured/retained-speed explanation](https://www.antai.gouv.fr/particulier/vous-avez-recu-une-amende/)
and [OM's correction guidance](https://www.om.nl/onderwerpen/v/verkeer/handhaving/snelheid-en-te-hard-rijden/marges-en-meetcorrecties).

Additive schema fields, agreed by both engine owners:

- `localized_templates` maps `de`, `en`, `fr`, `nl` to objects containing
  `title_template` and `detail_template`. Existing English fields are fallbacks.
- France's first two bands use `posted_limit_variants.at_most_50` and
  `.above_50`, each with `money_fine_eur` and `penalty_points`. With no known
  positive posted limit, the scalar amount stays absent; text explains both
  possibilities. There is no French `locality_variants` fallback.
- `enforcement_class` is optional: `criminal` or `context_dependent` means
  serious referral potential, independently of numeric points. Netherlands
  and Belgium retain `severity: money_only`; no fictitious point badge is
  needed to render a serious warning.
- An absent fine/point/ban value means it was not determined, not zero. France's
  zero-point first band is deliberate. All six files omit numeric ban fields.

These bands are consumer warning groups, not complete tariff tables. They do
not resolve repeat/novice-driver rules, all vehicle classes, local enforcement
policy, settlement eligibility or every court sanction.

## Verification inputs

| Country | Inclusive bands, km/h excess | Representative deltas | Expected scalar fine / points |
| --- | --- | --- | --- |
| FRA | 1–4, 5–19, 20–29, 30–39, 40–49, 50+ | 2, 10, 25, 35, 45, 55 | At limit 50: €135/0, €135/1, €135/2, €135/3, €135/4, absent/6 |
| NLD | 1–3, 4–30, 31–39, 40–49, 50+ | 2, 10, 35, 45, 55 | All scalar fines and points absent |
| BEL | 1–10, 11–20, 21–30, 31–40, 41+ | 5, 15, 25, 35, 45 | First fine €58 excluding fee; remaining fines and all points absent |

Check every boundary and its neighbours, zero/negative excess (no warning),
all four translation dictionaries, placeholder expansion, and platform JSON
equality. France at +2/+10 must select €135 with a 40/50 limit and €68 with a
70/80 limit regardless of the city flag; absent limit must not invent €135.
Check the Dutch exact +40 motorway threshold and the +1–3 explanatory text.
Serious referral classes start at FRA +50, NLD +31 and BEL +31, with the latter
two lower bands explicitly dependent on road context.

Screenshot coverage uses synthetic country locations: France in French,
Netherlands in Dutch, and Belgium in Dutch/French/German, every listed band on
both platforms. Those screenshots validate selection, localization and
rendering; they do not turn raw GPS excess into a legally retained speed.
