# YouSpeed 1.3 submission status — 2 October 2026

**The signed iPhone build 1.3 (10032) has uploaded successfully to App Store Connect. Neither store has received a review submission.** The current release includes freshly reviewed Dutch tariffs and both offline Info references. Camera recognition is presented as a standard feature, without an experimental label.

Production source for build 10032 was committed and pushed on main at `8370141` (following the Info implementation at `ef19b22`). Subsequent changes prepare listing assets, reports and a screenshot-only UI test; they do not alter the production binary's runtime behavior or protected speed-reference policy.

## Authenticated console state

| Destination | Verified action | Work still pending |
| --- | --- | --- |
| App Store Connect, Safari | Created version 1.3. Saved description, promotional text, keywords and release notes in DE/EN/FR/NL. Updated DE/EN app names/subtitles. Signed 10032 upload reports “Upload succeeded” and “Uploaded package is processing.” | Verify processing, select 10032 in the draft, update FR/NL app names/subtitles and reviewer notes, replace gallery/preview assets, finish privacy/declarations and submit for review. |
| Apple availability | France, Switzerland, Belgium and Netherlands already enabled among 42 territories; inspected without changing selections. | No addition needed for those four countries. |
| Google Play, Chrome | Created and saved production release draft **1.3 (10032)** with release notes in nine languages and zero app bundles; the old 10000 bundle is excluded. Saved all nine listing languages. All 27 text fields match the prepared source by SHA-256. Discarded the AI import after detecting an altered Spanish word; entered the remaining translations directly. Added Belgium, preserving the six existing production territories (DE, FR, LI, LU, NL, CH); the country change is saved for review. | Advance the listing drafts with new galleries/feature graphics and video URL, upload the signed AAB and submit the combined changes for review. |
| YouTube | Opened upload dialog on Raphael Volz's channel. User authorized unlisted publication of the prepared preview. | The upload dialog accepts Terms/Community Guidelines; action-time confirmation is pending. No video file has been uploaded. |

The browser permission problem was overcome. Chrome browser control remains usable for text and country changes while the Mac is locked; Safari and native file pickers require unlocking. [Play text verification](PLAY_CONSOLE_TEXT_VALIDATION_2026-10-02.json) records all 27 matching field hashes. The current Computer Use blocker is **the Mac being locked**, rather than Safari/Chrome authorization. Native file pickers provide an upload path without changing Chrome extension file-access permissions.

## Prepared assets

| Material | Coverage |
| --- | --- |
| Apple metadata and gallery | Four languages; ten 1320×2868 PNGs per language, 40 total. |
| Play metadata and gallery | Nine languages; eight 1080×1920 PNGs each, 72 total; nine 1024×500 feature graphics and existing 512px icons. Fastlane mirrors match, with candidate changelog 10032. |
| Complete Info capture collection | 68 iPhone and 153 Android native captures: five national sign catalogs and all twelve fine countries in every platform UI language. |
| Apple preview | English 30-second native app preview, 1920×886, H.264/AAC. |
| YouTube/Play film | English 76-second feature film, 1920×1080, H.264/AAC; prepared for unlisted publication. Other-language video files have not been generated. |

The selected upload galleries show every sign country, the Dutch fine table, and camera/dashcam functionality. Full fine-country captures are retained in the review collection because a gallery cannot hold all seventeen references plus core feature images. The Dutch table displays existing JSON amounts and the separate 9 EUR administration fee. Spoken-name rows follow English, French, German, Dutch. Both Info references use a localized not-legal-advice note.

[Reference validation](REFERENCE_SCREENSHOT_VALIDATION_2026-10-02.json) checked 221 captures with zero errors, including every Android country selector. [Listing validation](STORE_PACKAGE_VALIDATION_2026-10-02.json) checked 220 metadata/image files with zero errors. [Screenshot review](STORE_SCREENSHOT_REVIEW_2026-10-02.md) documents capture authenticity and the gallery selection. Apple captures are RGB, preserving decoded pixels and color metadata from fully opaque originals. Layout source/output hashes are retained. No sign artwork or app camera result was fabricated.

## Fresh binaries and deployment

| Artifact | Bytes | SHA-256 | State |
| --- | --- | --- | --- |
| `tmp/store-submission-1.3/YouSpeed-1.3-10032-AppStore.ipa` | 248090715 | `5d22ff0c271dc9c96bde8aaedf39634e5795ad5f6fa3b9f09b2ac8354855480a` | App Store signed; uploaded successfully. |
| `tmp/store-submission-1.3/YouSpeed-1.3-10032-Play-unsigned.aab` | 446670486 | `39062440c7c1bab65b14d18df2d54b96b73f31d25c9c076debf7cc11880a6428` | Unsigned; cannot be submitted. |

The iPhone archive/export verified distribution signing, packaged privacy manifest and absence of release client credentials. A development export of the same archive was installed successfully on the attached iPhone 14 Pro; launch was refused because the phone had locked.

Android build 10032 completed Debug and Release JVM suites, **619 tests each, zero failures**, release lint and bundle preparation. The 1.3-debug (10032) APK was installed on the attached Moto g86 5G and the activity start command succeeded, but the lockscreen prevented actual Info-flow acceptance. Both phones need to be unlocked for final physical verification. The Android release signing configuration remains absent; the existing Play upload keystore and its secure configuration are requested. No replacement or unrelated key was used.

The Android native audit still reports 16 KB LOAD alignment passing for all twelve packaged 64-bit libraries, while the additional RELRO alignment check fails for nine; actual 16 KB runtime verification remains pending. Prior detailed build/source and compatibility findings remain in [Android readiness](ANDROID_READINESS_2026-10-02.md). Prior iPhone suites and platform constraints remain in [iPhone readiness](IPHONE_READINESS_2026-10-02.md); their earlier 10031 artifacts are superseded by the fresh binaries above.

## Concrete submission blockers

1. Unlock the Mac to complete browser uploads, and unlock both attached phones for physical acceptance.
2. Configure the existing matching Google Play upload key using `YOUSPEED_ANDROID_RELEASE_STORE_FILE`, `YOUSPEED_ANDROID_RELEASE_STORE_PASSWORD`, `YOUSPEED_ANDROID_RELEASE_KEY_ALIAS` and `YOUSPEED_ANDROID_RELEASE_KEY_PASSWORD`. Play Console records upload-certificate SHA-256 `79:B3:84:31:15:3D:E1:B1:77:6E:A8:3E:19:70:66:2D:0A:40:C6:A4:1A:EC:BC:A9:58:D7:3E:3F:E5:09:E0:8A`; match the supplied key before building/uploading the signed candidate.
3. Confirm acceptance of the YouTube terms at upload time; then publish the prepared video as unlisted and add its URL to the Play listings.
4. Resolve the evidence-backed Panoramax account-and-content deletion flow and remaining privacy declarations. Optional OSM France login creates a contributor account; Disconnect revokes authorization but does not remove accounts/photos. A verified deletion service and published privacy policy are requested. Server retention, recipients, account fields and research purposes must be reconciled without inventing answers. See [the public instance audit](PANORAMAX_PRIVACY_READINESS_2026-10-02.md), [Apple form draft](../../store/apple/privacy/app_privacy.md) and [Play form draft](../../store/android/data-safety/data_safety.md).
5. Complete remaining release acceptance, model/licence gates already documented in the repository, store declarations and actual review submission. Existing country/model limits must not be represented as universal detection reliability.

The revised public privacy/support HTML is still a local draft. New store galleries and videos have not yet been uploaded. Existing review contact details and Apple manual-release setting were preserved; Google gained Belgium while preserving its other six territories. [Play release draft evidence](PLAY_RELEASE_DRAFT_2026-10-02.json) records the exact draft URL and notes hash. The baseline 1.0.1 (10003) remains historical; the source history does not establish an exact commit mapping for that TestFlight upload.

## Reproducible handoff

Run `python3 scripts/release/validate_store_package.py` and `python3 scripts/release/package_store_submission.py` for the listing ZIP and SHA-256 manifest. The ZIP contains approved listing sources, native references, media and reports; it excludes credentials, device recordings/logs and app binaries. Signed and unsigned binaries are retained separately with [artifact hashes](BUILD_10032_ARTIFACTS_2026-10-02.json). No package-generation command submits an app.
