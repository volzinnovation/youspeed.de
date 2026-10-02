# Swiss penalty correction — review proposal, 1 October 2026

Status: **owner approved on 1 October 2026**. The owner approved the Swiss rule
content and advisory presentation, and authorized commit/push. The correction is on
`codex/8-tsr-applicability`, based on commit `b9c0aea`. It has been exercised in
both native simulators; the attached phones still have the earlier build 10029.
No corrected Swiss bundle or physical-device build has been published/deployed.

## Proposed behavior

Both clients now select the motorway table from the accepted matched road's
`highway=motorway`, even at a reduced posted limit or within a settlement.
The existing matching result supplies this information; no new lookup is needed.
The posted speed alone never establishes the road category. Missing/stale road
context, motorway/trunk links and an unspecified `trunk` suppress an exact fine
or ordinary withdrawal duration and retain the advisory warning.

Swiss fixed fines are separated from first-offence administrative withdrawal
minimums. Raser risk is evaluated against the **posted limit**, including lower
limits, with a normal minimum of 24 months and a conditional minimum of 12 months
in qualifying statutory cases. There are no Swiss licence points. The dashboard
shows `≥` for ordinary withdrawal minimums and a visible GPS-estimate caption;
Raser copy explicitly distinguishes the normal and exceptional minimums.
English, German, French and Dutch copy is provided in shared JSON.

| Replay input | Before, both clients | Proposed, both clients |
| --- | --- | --- |
| Urban 50, excess 5 | CHF 40 | CHF 40, estimate caption |
| Rural 80, excess 10 | CHF 100 | CHF 100, estimate caption |
| Motorway 120, excess 10 | CHF 100 | **CHF 60**, estimate caption |
| Motorway 120, excess 32 | 3 months | **≥1 month**, first-offence estimate |
| Urban 30, excess 40 | 3 months; conditional 24 | **24 months normally; ≥12 in qualifying exceptions** |
| Rural 80, excess 60 | 3 months; conditional 24 | Same corrected Raser presentation |
| Motorway 120, excess 80 | 24 months, exceptions omitted | Same corrected Raser presentation |

These are consequences estimates for ordinary passenger-car first offences.
Actual enforcement uses the assessed excess after the prescribed measurement
deduction. The app does not subtract an invented police-device tolerance from
GPS speed. Repeat offences, probationary licences, additional danger, criminal
sentencing and vehicle measures require individual assessment; the app does not
claim to determine those outcomes.

## Source verification

Checked on 1 October 2026:

- [Fedlex OBV, SR 314.11](https://www.fedlex.admin.ch/eli/cc/2019/93/de),
  current version **1 August 2026**, Annex 1 item 303. The JavaScript-rendered
  official text confirms the distinct urban, rural/Autostrasse and motorway
  fixed-fine bands and their measurement-deduction basis.
- [Fedlex SVG, SR 741.01](https://www.fedlex.admin.ch/eli/cc/1959/679_705_685/de),
  current version **1 July 2026**, Art. 90(4) and Art. 16c(2)(abis).
  Confirms posted-limit threshold ranges and the possible reduction of up to
  twelve months when the qualifying criminal sentence is less than one year
  under Art. 90(3bis)/(3ter). Reaching a GPS threshold is presented as risk;
  it does not establish every element of a criminal offence.
- [Canton Zürich first-offence tables](https://www.zh.ch/de/mobilitaet/fuehrerausweis-fahren-lernen/ausweisentzug/zu-schnell-fahren.html)
  corroborate ordinary administrative minimums and scope qualifications.
- [St. Gallen road authority](https://www.sg.ch/verkehr/strassenverkehr/fuehrerausweisentzuege/geschwindigkeitsueberschreitung.html)
  explicitly places **divided Autostrassen** with motorways for administrative
  measures. A `trunk` tag does not prove division; this draft therefore avoids
  showing an exact result for that ambiguous context. Fixed-fine and withdrawal
  category definitions must not be assumed identical for every Autostrasse.

The text is independently authored. Source citations and a fresh check date are
not governmental app approval or a recorded legal sign-off. The existing
[country release checklist](release/STORE_RELEASE_CHECKLIST.md) remains the
place for release review. The owner has approved the specific implementation and advisory presentation
described here; no governmental or independent legal certification is inferred.

## Validation and evidence

- **105 independently specified boundary/context cases × four languages**, in
  both Swift and Kotlin: **840 engine evaluations**, all passed. Cases cover
  every band edge, all posted-limit threshold ranges, reduced motorway limits,
  motorway within a settlement, unknown road/limit, links and ambiguous
  Autostrassen. Expectations are shared fixtures, independently specified from
  official tables rather than derived from production JSON.
- Android: **589 unit tests**, zero failures/errors/skips; Debug app/test APKs
  built successfully. Presentation checks verify matched motorway behavior and
  suppression for uncertain/stale context.
- iOS: **five focused tests**, zero failures/skips, covering the legal corpus,
  downloaded-rule precedence and existing country parsing/resolution.
- Seven Zürich GPS/road/speed scenarios through each native client; country
  selection resolves **CHE**, currency **CHF** and the corrected output.
  This validates input replay through production selectors/resolvers/renderers,
  not GPS reception or a Swiss field drive.
- Both native screens were visually checked for the one-month motorway minimum
  and Raser exception caption. Original pixels and raw reports are retained
  outside the repository at
  `/Users/raphaelvolz/YouSpeedDeviceBackups/2026-10-01/swiss-correction-review/`.
- Attribution generator check and `git diff --check` pass.

Native dashboard captures (original pixels):
[iPhone motorway minimum](/Users/raphaelvolz/YouSpeedDeviceBackups/2026-10-01/swiss-correction-review/ios/case-3.png),
[Android motorway minimum](/Users/raphaelvolz/YouSpeedDeviceBackups/2026-10-01/swiss-correction-review/swiss-penalty-audit/case-3.png),
[iPhone Raser caption](/Users/raphaelvolz/YouSpeedDeviceBackups/2026-10-01/swiss-correction-review/ios/case-4.png),
[Android Raser caption](/Users/raphaelvolz/YouSpeedDeviceBackups/2026-10-01/swiss-correction-review/swiss-penalty-audit/case-4.png).

Machine-readable parity evidence:
[SWISS_PENALTY_CORRECTION_REVIEW_2026-10-01.json](SWISS_PENALTY_CORRECTION_REVIEW_2026-10-01.json).

Tested rule SHA-256, before approval metadata:
`3deac5a5b6a5c586d094893349eafce4c88b5c02ba413e5739651002cc0f0a96`.
Approved rule SHA-256:
`bc004831ab90542d6e073fad5143453745f008dc5c9bb94d5dbbedb3216219ed`.
Only the review status, approval date/role and explanatory note changed after
testing; all executable rule fields match the tested native resource.
Schema version 2; content revision 20261001; review status owner_approved.

## Delivery scope after approval

The correction updates shared CHE rules, both parsers/resolvers, matched-road
context wiring, both dashboard captions, revision preference, native replay
harnesses and shared boundary tests. It does not change the protected
speed-limit reference state-machine policy.

Both loaders prefer the packaged correction over an installed older CHE rule
file (legacy revision 0), preventing existing downloaded bundles from restoring
the defective figures. Same/newer revisions remain eligible. Other countries
retain their existing semantics. Historical map bundle content is preserved.

Approved scope: commit and push this correction. The owner also approved the
rule content and advisory presentation. A subsequent installation on the
attached phones and real-device Swiss-location replay remains a separate step. Publishing a schema-2 downloadable rule bundle for older
clients is a separate release: those clients cannot apply the new motorway and
Raser semantics and need an app-version compatibility gate. Record product and
country legal-copy review against the resulting commit before store release.
