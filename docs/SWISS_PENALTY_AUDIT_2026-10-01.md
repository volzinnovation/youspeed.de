# Swiss penalty selection and display audit — 1 October 2026

Both clients select `CHE-rules.json` from a synthetic Zürich GPS fix
(47.3769, 8.5417) through their normal regional-coverage country selector.
They parse the same rule bytes and return identical results for seven native
dashboard scenarios. Loading succeeds; legal-content/display correctness does
not pass the audit. No recorded country-specific legal sign-off was found.

## Executed verification

- iOS 18.6, iPhone 16e simulator: built current Debug source, installed it,
  replayed GPS, map reference and speed inputs, resolved actual bundled rules,
  saved JSON and unedited simulator screenshots. The existing country capture
  harness needed a Zürich fixture and map-reference events after the runtime
  reset; these harness corrections do not modify shared reference policy.
- Android API 36 emulator: `SwissPenaltyAuditInstrumentedTest` launches the real
  activity with Zürich GPS/road/speed inputs, asserts the selected country,
  filename and CHF currency, and captures the real dashboard output.
- All seven output records agree across Swift/Kotlin, including conditional
  withdrawal fields. Shared JSON, Android APK asset, iOS simulator resource and
  physical iPhone build 10029 resource agree byte-for-byte: SHA-256
  `ce06277387b3de4420ecf5cf52f923c9ca46261f8b4f195c6e07bcc09478c8e2`.
- This is synthetic input replay through native clients, not a Swiss field
  drive or an independent test of GPS reception/map matching. Motorway cases
  supply non-urban context and a 120 limit; the current penalty API cannot
  accept a motorway road category. A 120 limit alone must not establish it.

Machine-readable results: [SWISS_PENALTY_AUDIT_2026-10-01.json](SWISS_PENALTY_AUDIT_2026-10-01.json).
Original pixels and raw test output are outside the repository at
`/Users/raphaelvolz/YouSpeedDeviceBackups/2026-10-01/swiss-audit/`.

## Findings requiring correction before Swiss display sign-off

| Input / context | Current output, both clients | Official rule / implication |
| --- | --- | --- |
| Urban 50, +5 | CHF 40 | Correct fixed fine if the excess is the legally assessed excess after the applicable measurement deduction. |
| Rural/autostrasse 80, +10 | CHF 100 | Correct on the same basis. |
| Motorway-style 120, +10, non-urban | CHF 100 | An actual motorway violation in this band has CHF 60. The schema/resolver picks rural; explanatory text does not correct the large dashboard amount. |
| Motorway-style 120, +32, non-urban | 3 months | An actual motorway first offence at +31–34 has at least 1 month. The current shared band supplies 3 months regardless of road category. |
| Urban 30, +40 | 3 months; conditional field 24 | Raser threshold reached. The primary metric ignores the conditional field and still shows 3. |
| Rural 80, +60 | 3 months; conditional field 24 | Same missing posted-limit-dependent Raser evaluation. |
| Motorway-style 120, +80 | 24 months | Generally the two-year Raser minimum, but the copy omits the statutory possibility of reduction to one year in qualifying cases. |

The fixed-fine **text** matches the official table: urban 40/120/250 CHF,
rural/autostrasse 40/100/160/240 CHF and motorway 20/60/120/180/260 CHF.
The first-offence withdrawal thresholds in the text also match the official
urban/rural/motorway tables. Correct text is insufficient when the structured
result and primary dashboard metric disagree with it.

Other limits: the app passes its live rounded speed excess to the rule engine;
it does not derive a police-device-specific assessed excess. Measurement
deductions depend on the actual enforcement method and must not be blindly
subtracted from GPS speed. The JSON detail mentions deduction, but the prominent
amount does not explain that basis. Repeat offences, probationary licences and
case-specific criminal penalties are not represented by the current simple
bands. Swiss copy has no localized templates, so German/French UI can receive
English warning details.

## Official sources checked

- [St. Gallen cantonal police: fines and measurement deductions](https://www.sg.ch/sicherheit/kantonspolizei/verkehr/geschwindigkeit---radar.html).
  Supports the fixed-fine table and different radar/laser deductions; amounts
  apply after the prescribed deduction.
- [Canton Zürich: speeding, first/repeat offences and Raser cases](https://www.zh.ch/de/mobilitaet/fuehrerausweis-fahren-lernen/ausweisentzug/zu-schnell-fahren.html).
  Supports the three distinct first-offence withdrawal tables and general
  two-year Raser minimum, with possible one-year reduction in exceptional cases.
- [Swiss Intellectual Property Institute guide, July 2024, pp. 34–35](https://www.ige.ch/fileadmin/user_upload/kmu/d/A6_Pocket_Guide_Gedacht_Gemacht_Geschuetzt_2024_de_DS_web.pdf).
  Explains that laws and official enactments are outside copyright protection.
  This supports using legal provisions in independently authored summaries;
  it does not grant rights to arbitrary website prose or certify this app.

The bundled source-check date remains 4 July 2026; it was not advanced to imply
that the defective structured display has passed review. The current Fedlex
HTML endpoint required JavaScript in this check, so no claim is made that a
complete consolidated-statute review was performed. The official cantonal
sources above directly establish the observed contradictions.

## Approval and recommended implementation

`shared/attributions/sources.json` records the Swiss reference and explicitly
retains the original publisher's website rights. That attribution is not legal
or governmental app approval. `docs/release/STORE_RELEASE_CHECKLIST.md` still
requires legal review of advisory fine/points/driving-ban copy for each release
country. No completed Swiss sign-off record was found; no approval is inferred
from installation on testing phones or inclusion in a bundle.

Recommended order:

1. Add a shared explicit motorway category using reliable matched-road context,
   retain urban/rural/autostrasse distinctions, and suppress exact amounts when
   the legally relevant category is uncertain. Check both parsers and clients.
2. Evaluate Raser thresholds using the posted limit, express standard minimum
   withdrawal versus conditional exceptions, and remove misleading unconditional
   primary metrics. Do not introduce a Swiss points system.
3. Clarify estimated/GPS versus legally assessed excess and first-offence scope;
   localize Swiss wording and cite current provisions rather than copying pages.
4. Add independently specified legal boundary fixtures for all three road
   categories, posted-limit thresholds, uncertainty, repeat/probationary scope
   and the 2023 Raser exceptions. Existing parity alone reproduces shared errors.
5. Record a dated, artifact-specific legal/product sign-off before claiming the
   Swiss display is approved for release. This audit does not grant that sign-off.

Only simulator harnesses and audit evidence were changed by this check; the Swiss
rule content and production penalty semantics have not been silently revised.
