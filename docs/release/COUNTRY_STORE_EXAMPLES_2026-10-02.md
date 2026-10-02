# Country store examples — 1.3 / 2 October 2026

These fixtures show the actual implemented app notices for Germany’s neighboring release markets. They are illustrative GPS warning displays, not assessed offences or legal advice. **No enforcement measurement correction is automatically deducted.** Amounts in the rule snapshots refer to officially retained excess; fees, driver status and individual circumstances can change the outcome. Preserve the app disclaimer in screenshots and explanatory copy.

## Matching screenshot inputs on iPhone and Android

Use state `country-penalty`; posted limit 50 km/h, inside city true, matched `highway=residential` for every case. iPhone uses `YOUSPEED_SCREENSHOT_COUNTRY`, `_DELTA`, `_LIMIT`, `_INSIDE_CITY`, `_HIGHWAY`; Android uses the corresponding country-penalty screenshot scenario inputs in its screenshot script.

| Country | Country code | GPS delta | Displayed speed | Implemented scalar warning | Detail |
| --- | --- | --- | --- | --- | --- |
| France | FRA | +3 km/h | 53 km/h | 135 EUR; no French licence points deducted | Ordinary retained +1–4 band at a posted limit up to 50; chosen so the money-only UI displays the amount. |
| Switzerland | CHE | +11 km/h | 61 km/h | 250 CHF; no points | Urban first-offence band. `residential` establishes a non-motorway road, preventing unknown-category suppression. |
| Belgium | BEL | +5 km/h | 55 km/h | 58 EUR; no points | Detail also states the 2026 administrative fee of 10.67 EUR. |
| Netherlands | NLD | +12 km/h | 62 km/h | **140 EUR** | Ordinary urban passenger-car tariff; 9 EUR administration fee is separate in details. Uses the displayed excess illustratively, without police measurement correction. |

## Verified localized notice text

Generated with the production Swift `SpeedPenaltyRuleEngine.resolveNotice` and shared JSON rules, using `insideCity=true`, `postedLimitKmh=50`, `isMotorway=false`, and each explicit language code. Only unrelated app integration types were stubbed to run the engine as a CLI. The Dutch update also verifies native simulator country resolution and the visible 140 EUR screenshot in all four core locales; physical-device behavior is not covered. Engine results are preserved in `COUNTRY_STORE_EXAMPLES_2026-10-02.json`; the `official_reference_example` field on Dutch records distinguishes the displayed-excess estimate from an actual police measurement correction. Screenshot scripts must additionally verify the actual app’s `country-review.json` output.

### FRA

| Language | Title | Detail |
| --- | --- | --- |
| de | Geldbuße möglich | Regelbetrag: 135 EUR bei Tempolimit bis 50 km/h, sonst 68 EUR. Kein Punkteabzug im französischen System. |
| en | Fine possible | Standard fine: 135 EUR at limits up to 50 km/h, otherwise 68 EUR. No French licence point deduction. |
| fr | Amende possible | Amende forfaitaire : 135 EUR si la limite est de 50 km/h ou moins, sinon 68 EUR. Aucun retrait de point au barème français. |
| nl | Boete mogelijk | Standaardboete: 135 EUR bij een limiet tot 50 km/u, anders 68 EUR. Geen puntenaftrek in het Franse stelsel. |

### CHE

| Language | Title | Detail |
| --- | --- | --- |
| de | Geschätzte Folgen der Überschreitung | Innerorts: Ordnungsbuße 250 CHF. Außerorts / Autostraße: Ordnungsbuße 160 CHF. Autobahn: Ordnungsbuße 120 CHF. Nur GPS-Schätzung; Beträge gelten für die amtlich festgestellte Überschreitung nach dem vorgeschriebenen Messabzug. Erstverstoß; Wiederholungs- und Probeführerausweisfälle können abweichen. |
| en | Speeding consequences estimate | Urban: fixed fine 250 CHF. Rural / autostrasse: fixed fine 160 CHF. Motorway: fixed fine 120 CHF. GPS estimate only; amounts refer to excess after the applicable enforcement deduction. First offence; repeat/probationary cases differ. |
| fr | Conséquences estimées de l’excès | En localité: amende d’ordre 250 CHF. Hors localité / semi-autoroute: amende d’ordre 160 CHF. Autoroute: amende d’ordre 120 CHF. Estimation GPS seulement; montants pour l’excès retenu après la déduction de mesure applicable. Première infraction; récidive et permis à l’essai peuvent différer. |
| nl | Geschatte gevolgen van te hard rijden | Binnen bebouwde kom: vaste boete 250 CHF. Buiten bebouwde kom / autoweg: vaste boete 160 CHF. Autosnelweg: vaste boete 120 CHF. Alleen GPS-schatting; bedragen gelden na de toepasselijke officiële meetcorrectie. Eerste overtreding; herhaling en voorlopig rijbewijs kunnen afwijken. |

Additional English advisory caption: GPS estimate · first offence · assessed excess may differ

### BEL

| Language | Title | Detail |
| --- | --- | --- |
| de | Geldbuße möglich | Regelbetrag im vereinfachten Verfahren: 58 EUR zuzüglich 10,67 EUR Verwaltungsgebühr (2026). |
| en | Fine possible | Standard immediate settlement: 58 EUR, plus a 10.67 EUR administrative fee (2026). |
| fr | Amende possible | Perception immédiate ordinaire : 58 EUR, plus 10,67 EUR de redevance administrative (2026). |
| nl | Boete mogelijk | Gewone onmiddellijke inning: 58 EUR, plus 10,67 EUR administratiekosten (2026). |

### NLD

The new Dutch tariff engine shows **140 EUR** in each core locale for the ordinary urban +12 km/h store example. The detail includes the additional **9 EUR** fee.

| Language | Title | Detail |
| --- | --- | --- |
| de | Bußgeldschätzung | Normaler Pkw ohne Anhänger, keine Baustelle: 140 EUR Bußgeld + 9 EUR Verwaltungsgebühr. Die angezeigten +12 km/h dienen als korrigierte Überschreitung; eine amtliche Messkorrektur kann den Betrag ändern. Innerörtliche 30-km/h-Zonen und 15-km/h-Wohnverkehrsbereiche haben einen höheren Tarif. |
| en | Fine estimate | Ordinary passenger car without trailer, no roadworks: 140 EUR fine + 9 EUR administrative costs. Estimate uses the displayed +12 km/h as corrected excess; an official police measurement correction can change the amount. Urban 30-km/h zones and 15-km/h woonerven use their higher tariff. |
| fr | Estimation de l’amende | Voiture ordinaire sans remorque, sans travaux : 140 EUR d’amende + 9 EUR de frais administratifs. Les +12 km/h affichés sont utilisés comme excès corrigé ; la correction officielle de mesure peut modifier le montant. Les zones urbaines à 30 km/h et les woonerven à 15 km/h ont un tarif plus élevé. |
| nl | Boeteraming | Gewone personenauto zonder aanhanger, geen wegwerkzaamheden: 140 EUR boete + 9 EUR administratiekosten. De getoonde +12 km/u wordt als gecorrigeerde overschrijding gebruikt; de officiële meetcorrectie kan het bedrag veranderen. Een 30-km/u-zone binnen de bebouwde kom en een woonerf met 15 km/u hebben een hoger tarief. |

## Separate official Dutch monetary reference example

The apps now implement the ordinary Dutch per-km/h tariffs and the screenshots show **140 EUR** for the displayed +12 case. **The GPS estimate is not a prediction of a ticket:** the police measurement correction is not automatically applied. It assumes an ordinary passenger car (tariff category 1), a normal urban 50 km/h road and no roadworks. The [OM Feitenboekje 2026](https://www.om.nl/site/binaries/site-content/collections/documents/mulderbundel/map/map/mulderbundel-2026/Feitenboekje%2B2026.pdf), printed A17/A19 (PDF pages 43/45), lists VA012/VB012 at **140 EUR** for officially corrected +12 km/h and VA009/VB009 at **84 EUR** for corrected +9 km/h. The [OM tariff page](https://www.om.nl/onderwerpen/b/boetebase) excludes the **9 EUR** administrative fee. These primary sources were checked on 2 October 2026.

| Example | Speed after official correction | Retained excess over 50 | Base fine | Fee | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Already corrected +12 | 62 km/h | +12 km/h | 140 EUR | 9 EUR | **149 EUR** |
| Police measured 62 km/h, then subtracts 3 km/h | 59 km/h | +9 km/h | 84 EUR | 9 EUR | **93 EUR** |

The second calculation uses the [OM measurement correction](https://www.om.nl/onderwerpen/v/verkeer/handhaving/snelheid-en-te-hard-rijden/marges-en-meetcorrecties). The app does not automatically make this deduction. A raw GPS display of 62 in a 50 zone therefore cannot establish the officially corrected +12 case. Different limits, vehicle classes, roadworks and road categories require their own tariff selection; precise Dutch monetary tariff support remains a product limitation.

| Language | Reference explanation (separate from app output) |
| --- | --- |
| de | Normaler Pkw, innerorts bei Tempo 50, ohne Baustelle. Amtlich korrigierte Überschreitung +12 km/h: 140 EUR Bußgeld + 9 EUR Verwaltungsgebühr = 149 EUR. Misst die Polizei hingegen 62 km/h, ergibt der Messabzug von 3 km/h eine korrigierte Geschwindigkeit von 59 km/h (+9): 84 EUR + 9 EUR = 93 EUR. Die App zieht keine amtliche Messkorrektur ab und zeigt für die Niederlande weiterhin nur den kontextabhängigen Warnhinweis. |
| en | Ordinary passenger car, normal urban 50 km/h road, no roadworks. Officially corrected excess +12 km/h: 140 EUR fine + 9 EUR administrative fee = 149 EUR. If police instead measure 62 km/h, subtracting the 3 km/h measurement correction gives 59 km/h (+9): 84 EUR + 9 EUR = 93 EUR. The app applies no enforcement measurement correction and now displays the ordinary urban tariff for the shown excess. |
| fr | Voiture particulière ordinaire, route normale en agglomération limitée à 50 km/h, sans travaux. Excès officiellement corrigé de +12 km/h : 140 EUR d’amende + 9 EUR de frais administratifs = 149 EUR. Si la police mesure plutôt 62 km/h, la correction de 3 km/h donne 59 km/h (+9) : 84 EUR + 9 EUR = 93 EUR. L’app n’applique aucune correction officielle de mesure et affiche toujours seulement un avertissement contextuel pour les Pays-Bas. |
| nl | Gewone personenauto, normale weg binnen de bebouwde kom met een limiet van 50 km/u, geen wegwerkzaamheden. Officieel gecorrigeerde overschrijding +12 km/u: 140 EUR boete + 9 EUR administratiekosten = 149 EUR. Meet de politie daarentegen 62 km/u, dan geeft de meetcorrectie van 3 km/u een gecorrigeerde snelheid van 59 km/u (+9): 84 EUR + 9 EUR = 93 EUR. De app past geen officiële meetcorrectie toe en toont nu het gewone tarief binnen de bebouwde kom voor de getoonde overschrijding. |

The companion JSON now records each Dutch engine output’s `money_fine` as `140`. The separately retained reference calculations explain how an official police measurement can differ.

## Rule sources and freshness

The source inputs are `shared/Rules/FRA-rules.json`, `CHE-rules.json`, `BEL-rules.json`, `NLD-rules.json`, and the native Swift/Kotlin rule engines. French/Belgian rule metadata was checked on 16 September 2026; Dutch rules were independently reviewed anew and implemented on 2 October 2026; the Swiss revision was approved by the product owner on 1 October 2026. The Dutch tariff rules and both native resolvers were updated at the product owner’s explicit request. No protected speed-reference policy was changed. See [Dutch review](../DUTCH_PENALTY_REVIEW_2026-10-02.md).

The [French government page](https://www.service-public.gouv.fr/particuliers/vosdroits/F19460) supports the ordinary retained below-5 band at a 50 km/h limit used here. The [Belgian police update](https://www.police.be/shape/fr/actualites/amendes-routieres-ce-qui-change-des-le-1er-juillet-2026) describes the July 2026 base and administrative fee. The [Swiss ordinance](https://www.fedlex.admin.ch/eli/cc/2019/93/de) and [Dutch prosecutor guidance](https://www.om.nl/onderwerpen/v/verkeer/handhaving/snelheid-en-te-hard-rijden) are the rule-source links; their pages were opened on 2 October, but this preparation does not claim a fresh independent legal review of every rule.

## Traffic-sign coverage language

The listing may say “country models contain hundreds of country-specific sign classes in total.” The product owner directed standard camera-recognition positioning on 2 October; technical rollout/calibration evidence below does not change that product label. Do not convert class/artwork/catalog counts into unique reliable detections or validated accuracy.

| Country | Pinned classifier outputs | Display-eligible pinned classes | Display-eligible catalogue entries | Shared artwork records |
| --- | ---: | ---: | ---: | ---: |
| Germany | 134 | 97 | 118 | 111 |
| France | 256 | 98 | 98 | 114 |
| Netherlands | 160 | 84 | 84 | 111 |
| Belgium | 143 | 88 | 88 | 115 |
| Switzerland | 127 | 102 | 102 | 116 |
| Total (country-specific counts; not unique signs) | 820 | 469 | 490 | 567 |

The German catalogue includes 21 aliases that do not add model capability. Excluding Switzerland, model outputs total 693 and eligible pinned classes total 367. Catalogues declare display-only semantics; displaying an additional sign does not itself authorize a speed override. Model class mappings have many `unknown` actions, and numeric speed signs use the intentional schematic platform display.

`shared/tsr/country-pack-registry-v1.json` retains German shadow and French/Belgian/Dutch evaluation rollout, with calibration/review work still pending. Switzerland is absent from that registry; its artwork manifest remains source-preparation-only with commercial redistribution approval false. `TrafficSignModelPackSelection` documents Swiss evaluation/shadow scope. Consequently, map/advisory support for Switzerland is advertised separately from camera model approval, and store-country availability does not authorize changing these review gates.
