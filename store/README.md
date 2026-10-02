# YouSpeed 1.3 store handoff

The local listing assets describe dashcam recording, on-device camera traffic-sign recognition, hundreds of country-specific sign classes, offline maps and country advisory information. Camera recognition is presented as a standard feature. The release preparation retains source version **1.3 (10031)**; verify that build number against both consoles before upload.

| Destination | Text | Upload imagery |
| --- | --- | --- |
| App Store Connect | `apple/metadata/<locale>/` | Ten ordered PNGs per locale in `apple/screenshots/<locale>/iphone-6.9/` |
| Google Play Console | `android/metadata/<locale>/` | Eight ordered PNGs, 512px icon and 1024×500 feature graphic in `android/listing/<locale>/` |
| Fastlane Android handoff | `../fastlane/metadata/android/<locale>/` | Byte-identical mirrors; candidate changelog `10031.txt` |

Apple locales: German, English, French and Dutch. Android locales: those four plus Spanish, Italian, Polish, Brazilian Portuguese and Swedish. French and Dutch localization serve the named countries; Switzerland also has German coverage. Preserve existing store territories and add France, Switzerland, Belgium and the Netherlands using `country-availability-1.3.json` as a proposed configuration.

Screenshots are the real native interfaces rendered with deterministic demonstration inputs. Their dashcam preview is empty in the simulator/emulator; generated road photography is used only in the Android feature graphic. Shared traffic-sign artwork is unchanged. Editable graphic sources and generation provenance are in `artwork/source/`.

See [the submission dossier](../docs/release/STORE_SUBMISSION_1.3_2026-10-02.md) for binaries, checks and outstanding requirements. `apple/privacy/app_privacy.md` and `android/data-safety/` are evidence-based form drafts with explicitly pending answers; they are not submitted declarations. The included Web privacy/support files are local revisions awaiting publication.

Validate with `python3 scripts/release/validate_store_package.py` from the repository root. Build a review ZIP with `python3 scripts/release/package_store_submission.py`. Neither command contacts a store or submits an app. The ZIP excludes app binaries, credentials, device recordings and debug logs. Source and historical-audit links in the reports refer to the full repository; the ZIP is a listing handoff, not a standalone app source checkout.

No console edits, availability changes, binary uploads, review submissions or publication were performed in this preparation. Authenticated Safari/Chrome control is blocked by the Computer Use runtime despite the user's authorization.
