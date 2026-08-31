# F-Droid packaging proposal

This directory contains a draft `fdroiddata` build recipe for YouSpeed:

- application ID: `de.youspeed.android`
- proposed category: `Navigation`
- source license: `AGPL-3.0-only`
- first build: version `1.0.0`, version code `10000`
- F-Droid Gradle subdirectory: `android/app/`
- proposed anti-features: `NonFreeNet` and `TetheredNet`, because map bundles
  use a non-configurable GitHub release source even though the downloaded data
  itself is free under ODbL 1.0

The recipe intentionally uses a full commit hash, as requested by the current
F-Droid build metadata reference. Android releases use app-specific
`android-v*` tags so F-Droid ignores the repository's unrelated map-data tags.

## Readiness findings

The application is structurally suitable for F-Droid: it has public source,
an OSI-approved license, no Google Play Services/Firebase/advertising/tracking
SDK, only trusted Google Maven and Maven Central repositories, and a normal
command-line Gradle release build. F-Droid Server 2.4.5 reports zero fatal
source findings and zero non-free APK class/signing findings. Its local build
workflow also successfully built version 1.0.0 from the exact commit and recipe
in this proposal.

An Android API 36 emulator exercised all 52 originally configured download entries. Each
successful run verified the manifest, compressed and uncompressed size/SHA-256,
and opened the installed file as SQLite. Fifty entries passed on the first
sweep, Sweden passed on an immediate retry after one 60-second read timeout,
and Guyane consistently returned HTTP 404. The unsupported Guyane entry was
therefore removed from both app catalogs; all 51 entries now advertised by the
apps passed the download test.

Release commit `e4cf0b7017e1b8161fa58ebe2e47ccef9e8e39ff`
also adds F-Droid's recognized Fastlane layout for nine locales and is tagged
`android-v1.0.0`. The draft uses that exact commit and app-specific tag update
checks. Before opening the merge request, re-run `fdroid readmeta`,
`fdroid rewritemeta de.youspeed.android`, `fdroid lint de.youspeed.android`,
and `fdroid build -v -l de.youspeed.android` in a current `fdroiddata` checkout.

## Submission flow

1. Fork `fdroid/fdroiddata` on GitLab and create a branch named
   `de.youspeed.android`; do not work on the fork's protected `master` branch.
2. Copy `de.youspeed.android.yml` to
   `fdroiddata/metadata/de.youspeed.android.yml`.
3. Run the validation commands above and push the branch to the fork.
4. Confirm that the fork pipeline succeeds.
5. Open a merge request against `fdroid/fdroiddata`, complete its template,
   and respond to packager review. A first-time contributor can alternatively
   open a Request for Packaging issue in `fdroid/rfp`.

The application repository carries the release tag and this fork-ready recipe;
the actual `fdroiddata` fork, branch, and merge request are separate GitLab
operations.
