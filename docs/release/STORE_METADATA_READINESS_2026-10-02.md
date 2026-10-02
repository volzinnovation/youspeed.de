# Store metadata readiness — 1.3 / 2 October 2026

## Baseline and scope

The user identifies App Store Connect version **1.0.1 (10003)** at the provided TestFlight metadata URL. Git does not prove the exact source of that console build: the first checked-in iPhone build 10003 is `01153756c52fe9d094d53d14e0f493e08707fc84` (duplicate history `fff38bee5d2d7526e4d044302adcd296089e5dd9`), dated 5 September 2026, and its checked-in marketing version is **1.1**, not 1.0.1. Its parent has 1.0.1 (10002). Do not label any guessed Git commit as the submitted 1.0.1 (10003) baseline without the archive/console record.

Preparation retains marketing version 1.3 and the existing tentative build 10031 pending final build/console checks. Release notes describe current 1.3 capabilities without claiming a proven commit-to-store delta. Historic Fastlane changelogs are preserved. Local candidate `10031.txt` changelogs now exist in all nine locales; console version-code uniqueness remains unverified.

## Prepared text

- Apple: descriptions, promotional copy, release notes and reviewer instructions in all four existing locales (de-DE, en-US, fr-FR, nl-NL).
- Android: full/short descriptions, release notes and reviewer instructions in all nine existing locales, with full/short text mirrored into `fastlane/metadata/android`.
- Text leads with “Drive safely” and driver assistance for every car, independent of its age. The benefit order is automatic traffic-sign recognition, speed alerts and penalty estimates, dashcam recording, offline maps, then privacy and optional contributions. Permission, recognition-limit and default-enabled diagnostic disclosures remain in the descriptions.
- Germany, France, Switzerland, Belgium and the Netherlands are named as map/advisory markets. Hundreds-of-classes wording is qualified; no accuracy guarantee or automatic Swiss production-model approval is claimed. The product owner explicitly directed standard camera-recognition positioning on 2 October; experimental/evaluation labels are excluded from marketing copy, while technical pack readiness remains documented separately.
- Names/titles now pair YouSpeed with the localized safety message; Apple subtitles describe driver assistance. Privacy/support links and historic changelogs remain intact. The audited count is 820 country-specific classifier outputs and 469 display-eligible model classes, including evaluation packs; the listing uses qualified hundreds-of-classes wording rather than a unique-sign or accuracy claim. See `store/artwork/marketing-evidence.json`. Reviewer notes stay English as in the existing repository and describe permissions, controls, defaults, model limits and account flow.
- Descriptions, short descriptions, release notes, promotional text and reviewer notes have been checked against their respective character limits; Fastlane full/short text is identical to the source listings.

See `COUNTRY_STORE_EXAMPLES_2026-10-02.md` and its JSON for historical country-rule outputs. The Dutch screenshots retain fresh native captures from separate tariff work in the primary checkout: 140 EUR at displayed +12 km/h, with administration costs separate. This marketing branch does not include the native tariff implementation. Match these screenshots to the final release binary after that work is integrated; the previously exported IPA/AAB must be rebuilt before upload.

## Privacy preparation

Replaced outdated privacy/Data safety drafts with evidence tables that distinguish local processing from actual off-device collection. Optional Panoramax uploads contain precise GPS, photos, account association and sign annotations; the proposed Apple categories are linked App Functionality data. Ordinary speech audio stays local. Default-enabled diagnostics are described accurately.

The Google checklist proposes collection yes for uploads, optional/non-ephemeral types, known HTTPS flows and no app tracking. The later public-instance audit establishes public defaults, licensing, operator names and published blur statements. OSM France's first-login contributor-account creation supports recommended Google account-deletion applicability yes; the shipped Disconnect flow only revokes a token. Exact server retention/recipients, a complete account-and-content deletion flow, sharing exceptions, additional account-service fields/diagnostics/research purpose mapping and reviewer access remain unresolved. They are not silently answered No/not applicable. The CSV is an internal checklist, not a Play import template. Apple manifest reconciliation is owned by the iPhone release audit. See `PANORAMAX_PRIVACY_READINESS_2026-10-02.md` and its public-response evidence JSON.

Primary definitions checked on 2 October 2026: [Apple App Privacy details](https://developer.apple.com/app-store/app-privacy-details/) and [Google Data safety guidance](https://support.google.com/googleplay/android-developer/answer/10787469).

## Public policy discrepancies identified

The prior `Web/datenschutz.html` omitted camera/dashcam, geotagged photo capture and uploads, supported Panoramax servers and account-linked contributions, the short local dismissal listening window, default-enabled logs, remote-versus-local deletion and server publication/retention. These findings were sent to the release owner, who owns corresponding Web privacy/support edits. Editing the local Web source does not publish it; verify the live URLs and operator statements before submission.

## Verification and limits

The core Android resource audit covered every default XML resource and found missing English Data Manager entries, one English vision-disregard string, and 21 camera-calibration strings each in French and Dutch. These were added and XML/key coverage verified for de/en/fr/nl. All nine Android locale resource sets now cover all 332 default translatable keys, with XML parsing, no duplicate names and exact format-placeholder parity verified. Polish and Swedish each received 158 additive strings; Spanish/Italian and Brazilian Portuguese were completed by the other release contributors. Final Android release lint subsequently passed with zero errors and 172 warnings; both JVM suites passed 615 tests each. Complete XML coverage does not establish complete UI translation: recorder/detail parityText supports de/en/fr/nl and falls back to English for the other five listing languages. See ANDROID_READINESS_2026-10-02.md for final binary evidence. Android onboarding voice-copy was aligned with the implemented four local Vosk languages rather than its obsolete German-only wording.

This preparation does not certify recognition accuracy, all-country physical-device parity, current public map endpoints, server privacy practices, store country availability, reviewer credentials, or the final built binary. No metadata or privacy answers were uploaded and no app was submitted/published. Final console and artifact checks remain in the release owner's readiness checklist.

## Independent public-source and network verification

The revised local Web privacy/support sources and all nine localized feature-graphic text definitions were reviewed against the app implementation. The privacy source now explicitly names both actual Panoramax server choices, Keychain/Android Keystore credential protection and the bounded four-second local dismissal-command listening window; unsupported claims about server retention or deletion were not added. French and Polish rendered feature graphics were visually inspected and their text is legible without experimental-recognition labels.

The default `BundleTargets.top10.json` bytes are identical in both apps. On 2 October 2026, all 51 derived default manifest endpoints returned anonymous HTTP 200, had valid expected format/schema/variant/region fields, minimum app versions compatible with 1.3 and valid positive-size/SHA-256 artifact metadata. All 198 distinct referenced assets returned anonymous HTTP 200 for HTTPS HEAD, and each final Content-Length matched its manifest declaration. Every public manifest identifies the 28 September refresh. Full evidence is in `PUBLIC_MAP_READINESS_2026-10-02.json`.

The availability audit did not download database bodies or verify asset content hashes, SQLite capabilities, actual geographic accuracy or future uptime. Delta-index chains and runtime custom-manifest overrides are outside that 51-endpoint check. No authentication or release mutation was used, and local Web edits remain unpublished.

The Panoramax follow-up inspected only public GET pages/configuration/contracts and unauthenticated login redirects. No accounts, tokens, uploads, messages, deletion requests or server changes were made. Exact supported findings and unresolved matters are in `PANORAMAX_PRIVACY_READINESS_2026-10-02.md`; its JSON excludes temporary OAuth session parameters. Published instance contacts do not establish a tested deletion service, and generic backend blur defaults do not establish either instance's raw-input or backup retention.
