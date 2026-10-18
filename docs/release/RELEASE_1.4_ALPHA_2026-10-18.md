# YouSpeed 1.4 alpha release handoff — 18 October 2026

The intended alpha uses the current application code for three additional test drives in daylight and at night. See [English/German release notes and drive checks](RELEASE_NOTES_1.4_ALPHA.md).

## Source and binaries

- Application code: `c1ee94a68c6e13b9371d64b15aa758379746896d` on `codex/youspeed-v1.4-app-foundations`. Subsequent release commits update documentation, artwork and release tooling; they do not change the application code or protected speed-reference policy.
- Android signed-build source: `2bab2e6`, base version code `10052`, version name `1.4-alpha`. The valid semantic version is necessary because the existing map compatibility parser rejects `1.4alpha`.
- Android prerelease: [four signed APKs](https://github.com/volzinnovation/youspeed.de/releases/tag/android-v1.4-alpha), produced by the [signed alpha workflow](https://github.com/volzinnovation/youspeed.de/actions/runs/39140274853). The release is a prerelease and does not replace the stable latest release. The published tag points to `4273698`; its application/runtime files are identical to the build checkout `2bab2e6`. Future workflow runs pin new tags directly to their checkout SHA. The superseded `1.4alpha` workflow was cancelled before publication.
- iPhone: **1.4 (10052)**, archived/exported with the existing Apple Distribution identity and Xcode 26.6. Both archive and IPA passed the release-credential-key checks. IPA: **248,827,522 bytes**, SHA-256 `c9a85eb8431c274232fe80af54786909307da8f760dcc20fa3bf104f4ac9c99a`.
- Apple confirmed upload success at **17:13:34 CEST**. Build `1d85c9a1-3026-417c-b934-c24240eced95` is processed as `VALID`, version 1.4, build 10052. Existing export-compliance treatment was retained: no non-exempt encryption.

The [artifact receipt](BUILD_10052_ARTIFACTS_2026-10-18.json) records all APK sizes/digests. The downloaded arm64 APK independently matches its SHA-256, verifies its v2 signature, uses package `de.youspeed.android`, version `1.4-alpha` (100522), and has the same signing certificate as the signed 10033 artifact. `SHA256SUMS` and the detailed release notes are attached to the GitHub prerelease.

## Apple and TestFlight

- Invitation: **https://testflight.apple.com/join/k3a1pgce**. Existing external group `Beta-Ext`, public-link limit 100, retained.
- Build 10052 is available for internal testing (`IN_BETA_TESTING`). External review was submitted and is `WAITING_FOR_BETA_REVIEW`; until approval, the public link may still offer the previously approved build.
- German TestFlight instructions describe the three further drives, daylight/night conditions, capture checks and deliberate post-drive uploads.
- App Store version **1.4** was created as a **manual-release draft**, ID `6e138df5-32ab-4050-919f-8b574159133b`. No production App Review submission or production release was performed.
- **All 40 screenshots** were uploaded to that draft: ten each in DE/EN/FR/NL. All remote delivery states were `COMPLETE`, and source MD5 values matched the local validated PNGs.
- Localized release notes are saved in the draft. Descriptions preserve the existing store edits and disclose permission-based sign-sighting/crop contributions separately from full Panoramax photo uploads.

## Screenshot and website package

- Fresh native 1.4 captures cover the four main iPhone views in four languages and Android recognition/dashcam views in nine languages. The selected country-reference captures are retained. Galleries contain ten Apple images or eight Play images per language.
- Native captures remain in `store/artwork/raw-screenshots/`. `store/artwork/screenshot-layouts.json` records input/output hashes. The dashcam creative uses the existing genuine recording frame; it is an explicitly documented composition, not a claim of a live simulator road scene.
- Capture scripts now use the selected gallery filenames and wait for the native UI. Android rejects splash/tutorial overlays and verifies portrait/landscape dimensions before accepting a capture. Website captures explicitly use German portrait mode.
- Website warning screenshots and four localized store-image derivatives are refreshed. Captions identify 1.4-alpha demonstration screens while retaining the stable 1.3 download destination.
- The website's GitHub Pages environment permits **only `main`**. The updated website source/output is prepared in website-only commit `4273698`; publication requires applying that reviewed commit to `main`. The environment policy was not changed.
- Play gallery/metadata sources and Fastlane mirrors are prepared. The operator supplied an authenticated Chrome Console session, but native UI control repeatedly stopped as the active Chrome profile/window changed. Play upload remains pending a stable idle YouSpeed Console window; this is separate from the completed GitHub APK prerelease.

## Validation

- Protected policy: **39 scenarios, 171 steps**, all 16 transitions and five states; artifact hashes and both app pins match.
- Shared mobile rules: **12 authoritative countries** pass source/packaging checks.
- Android: **716 unit tests**, zero failures, one skipped; debug build succeeded for capture.
- Maps: **122 passed, 25 skipped**, plus 58 passing subtests. Skips require separate environment support.
- iPhone: signed Release archive/export and simulator builds succeeded. The unit run reported **657 passed, 27 skipped, two failing tests**. One test process was terminated while cancelling an earlier full-country network-download test; the lane frame test returned no current geometry under the loaded simulator. Both failed tests then passed in a focused isolated rerun (**two tests, zero failures**) without source changes. The full-country live-download test is excluded from the bounded unit run; the original mixed full run is retained as failed evidence, not relabelled green.
- Store package: **220 metadata/image checks, zero errors**, covering dimensions, PNG transparency, text limits, exact gallery membership, retained hashes and Fastlane parity (`scripts/release/validate_store_package.py`).
- Static website check: **82 HTML files, one CSS file** pass.
- No physical-device/night-drive acceptance is inferred from simulator or unit results. No Android phone was attached during preparation.

A review ZIP can be recreated with `python3 scripts/release/package_store_submission.py --version 1.4-alpha --release-date 2026-10-18`. Packaging uses a new dated validation report and current build metadata, retains historical audit reports, and contacts neither store.

## Eight Panoramax student accounts

Approved names: `student01` through `student08` on **https://panoramax.youspeed.de**.

The instance uses private Keycloak administration on volz-db. Interactive sudo is required. The ignored local launcher `tmp/release-1.4-20261018/CREATE_STUDENT_ACCOUNTS.command` stages the reviewed helper and asks the operator to authenticate. It selects the existing `panoramax-backend_auth` network, creates ordinary users with unique temporary passwords and a first-login password-change requirement, and verifies enabled accounts. It grants no administrator roles, does not accept terms for the students, and does not change an existing account's password.

The first attempt stopped before account creation because the helper expected one attached Keycloak network; that assumption was corrected to the documented auth network. Successful completion produces a **mode-0600** `student-accounts.csv` beside the launcher. Credentials and root-only provisioning receipts must remain outside Git. Do not report eight accounts as created until the CSV and server creation checks succeed.

## Before production 1.4

Complete the three further drives and review the recordings, supplementary OCR, capture states, offline/reconnection behavior and corresponding iPhone/Android results. Confirm external TestFlight approval and student-account access. Reconcile store privacy/Data safety declarations with the new permission-based crop contribution behavior before a production submission. Google Play submission, production App Review, merging and website publication remain distinct actions from this alpha handoff.
