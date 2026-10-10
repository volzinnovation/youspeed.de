# Android 1.3 submission audit on 4 October 2026

Google Play has **1.3 (10033)** and **16 changes awaiting review**, with managed publishing enabled. The submission needs corrected privacy and reviewer declarations before review. The recorded Play binary also predates the cross-border fix in the newer GitHub release. This audit inspected the user's authenticated Chrome tab and updated the local handoff; it did not alter Console answers, upload a replacement binary, submit for review or publish.

**Follow-up after the owner's URL instruction:** the Play privacy-policy URL is now saved as **https://panoramax.youspeed.de/terms-of-service**, and the same URL is saved for deletion. The pending queue now contains **18 changes**, including privacy and Data safety. On reopening, the form is set to externally created accounts and labels the second URL **data deletion**; those intervening account selections were preserved. The [prepared page amendment](../../store/android/data-safety/panoramax-terms-of-service-de.html) substitutes Moonshots' `studios@moonshots.gmbh` contact and adds prominent account-and-associated-data deletion instructions. It has not been deployed. The live page still gives the HSPF rights address and refers retention details to a separate policy. The initial observations below remain the pre-change audit record.

[Saved privacy URL](android-submission-audit-2026-10-04/privacy-url-saved.jpg) and [saved deletion URL](android-submission-audit-2026-10-04/deletion-url-saved.jpg) record the follow-up changes. The official [Panoramax app's Data safety page](https://play.google.com/store/apps/datasafety?id=app.panoramax&hl=en-US) declares location, photos, name and email collection/sharing, and links to [IGN terms](https://panoramax.ign.fr/terms-of-service). This establishes a public example of using a terms page; IGN's licence, retention and encryption declaration were not copied into YouSpeed's answers.

## Confirmed Console state

- Production release 2 contains one new App Bundle, **10033 (1.3)**, minimum API 34 and target API 36; the old 10000 bundle is deactivated for this release. The release explicitly says it has not been sent for review.
- Release notes cover **9 of 9 languages**. The pending queue includes eight new listing languages, German listing updates, Belgium availability and the production release.
- The bundle detail panel reports **5,737 supported devices** and **Supports 16 KB**. Play cautions that undetected libraries and page-size assumptions can still cause failures. This does not establish actual runtime acceptance on a 16 KB device.
- App content has ten completed declarations and no declarations on the required-review tab. These completion flags describe the saved answers, not their correctness for 1.3.
- The active Data safety summary, last edited 4 July, says **no user-data collection or sharing** and **data not encrypted**. The separate saved draft has collection Yes, encryption Yes and OAuth selected; its account-deletion URL is empty and Next is disabled.
- The reviewer-access declaration says **No** part of the app is restricted. No reviewer login instructions are present in that form.

[Publishing queue](android-submission-audit-2026-10-04/publishing.jpg), [bundle details](android-submission-audit-2026-10-04/bundle-details.jpg), [declaration summaries](android-submission-audit-2026-10-04/app-content.jpg), [Data safety draft](android-submission-audit-2026-10-04/data-safety-draft.jpg) and [reviewer access](android-submission-audit-2026-10-04/reviewer-access.jpg) preserve the inspected UI.

## Gaps to close before review

| Gap | Evidence and required work |
| --- | --- |
| Incorrect active Data safety declaration | Optional Panoramax uploads send photos, embedded precise location, account identifiers and sign annotations off device. Finish the per-type collection, purpose, optionality and sharing assessment and submit the corrected declaration with the release. The partial draft has not replaced the active July declaration. Operator retention, recipients and additional account/log handling remain unresolved in the [privacy audit](PANORAMAX_PRIVACY_READINESS_2026-10-02.md). |
| Missing account-and-data deletion path | The draft cannot advance without a functioning deletion URL. Confirm an operator process covering contributor accounts and associated uploads, retention exceptions and timing; provide a public resource identifying YouSpeed and a discoverable in-app initiation path. Disconnect revokes authorization and local deletion removes device files; neither establishes account/content deletion. The repository's OSM France account-creation assessment makes this a policy-readiness gap on both clients. |
| Outdated public privacy policy | The [live policy](https://youspeed.de/datenschutz.html) is dated 4 July 2026 and covers local driving data and downloads, but omits Panoramax account association, photo/GPS uploads and public contributions. Reconcile actual operator practices, then approve and publish the revised policy. The more complete `Web/datenschutz.html` source remains a local draft and is not the deployed page inspected. |
| Incorrect reviewer-access declaration | Core driving works without an account, but optional Panoramax uploads require authentication. Replace the unrestricted-access answer with accurate instructions and a functioning review-access route covering those features. Play's form says reviewers cannot create new accounts; do not rely on reviewer signup or invent credentials. |
| Play binary predates the latest fix | The [recorded Play AAB](BUILD_10033_ARTIFACTS_2026-10-03.json) was built from `a067abb7ffc65cbbfe454542c036aa6e68c97a07`, SHA-256 `6102d18a6f567f412cef9b0ae7b7a4c12766025b3058c8003edc9f2a7a8d2d27`. The [GitHub Android 1.3 release](https://github.com/volzinnovation/youspeed.de/releases/tag/android-v1.3) uses `fce6a0cc2f128c3a69c39b8d1b03a59f6761483f`, including the cross-border map-switching and matcher-continuity fix. No newer Play build is recorded. To include that fix in Play, prepare and validate a signed AAB with a fresh unused version code, then replace the pending release bundle. Both releases being named 1.3 and based on 10033 does not imply identical source. The remote original AAB was not downloaded and rehashed in this audit. |

Google defines off-device transmission as collection, including optional transfers; a user-initiated sharing exception does not remove collection. See [Data safety guidance](https://support.google.com/googleplay/android-developer/answer/10787469?hl=en). Its [account-deletion guidance](https://support.google.com/googleplay/android-developer/answer/13327111?hl=en) includes app-directed external account creation and requires both an in-app path and a web request resource. The scope assessment here follows the documented contributor-account flow; it is not a new legal determination about either operator.

## Validation and advisory work

The existing signed Play CI [run 37108240602](https://github.com/volzinnovation/youspeed.de/actions/runs/37108240602) is now confirmed completed successfully at `a067abb7`. The newer GitHub APK release records 636 release unit tests, lint and signature verification for `fce6a0c`; those APK results do not establish that the older Play AAB contains the same fixes.

The production dashboard recommends five improvements: edge-to-edge layout handling, removal of deprecated edge-to-edge APIs, removal of large-screen orientation/resizing restrictions, bitmap downsampling and R8 optimization. These are recommendations rather than new blocking release errors. The 3 October release-validation record separately reports app-size and missing vendor-native-symbol warnings; those warnings were not rerun in this audit.

Physical-device acceptance and actual 16 KB runtime verification remain outstanding in the existing release records. No device deployment or runtime test was performed here. Existing model-rights, calibration and intended-market gates in the release documentation still need evidence before publication; this Console audit does not certify them.

## Next submission sequence

1. Confirm deletion execution and server data practices; finalize privacy content and reviewer access.
2. Align the release source with the intended fixes and build a replacement using a fresh Play version code. Update the signing workflow's hard-coded 10033 artifact names as needed.
3. Verify signatures, artifact/source mapping, release checks and physical acceptance; keep both clients aligned for any deletion-flow implementation.
4. Complete the corrected Data safety form and reviewer instructions, verify the published URLs, then submit the combined changes for review under the user's explicit release authorization. Managed publishing remains enabled; publication is a separate approved action.
