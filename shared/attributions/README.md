# Mobile source credits

Both apps expose `sources.json` through **Info → Sources and credits**. Credits
and licence text work offline; opening an original source uses the system
browser. UI controls are localized. Author names and original licence texts
retain their published spelling and language.

`THIRD_PARTY_NOTICES.txt` contains the shared image/mapping, font and software
notices and the app's AGPL text. The existing model-pack notice is additionally
available from Info on both platforms. Test-photo credits identify photographs
used in development; those photographs are not production app resources.

## Updating credits

Run from the repository root:

```sh
python3 scripts/attributions/generate.py
python3 scripts/attributions/generate.py --check
python3 -m pytest -q tests/tsr/test_attributions.py
```

The generator reads each of the 107 sign images' exact author, source revision,
licence basis and modification record from `../tsr/sign-pictograms/manifest.json`.
It also reads national rule citations, `additional-sources.json`, and
`android-components.json`. Edit those inputs, then regenerate; do not hand-edit
the two generated files.

`android-components.json` records the resolved `releaseRuntimeClasspath`
artifacts, not just direct dependencies: 71 artifacts representing 70 unique
Maven coordinates at this review. One coordinate has more than one resolved
artifact. APK shrinking can remove unused parts. The inventory deliberately
credits the full resolved set. Artifact hashes and hashes of embedded notices
are retained; local Gradle cache paths are not.

`licenses/ANDROID_ARTIFACT_NOTICES.txt` preserves all distinct licence/notice
texts found in those AARs/JARs, including nested `classes.jar`, without changing
their text. JNA permits Apache-2.0 or LGPL-2.1-or-later; this app selects Apache-2.0
and preserves the publisher's full dual-licence notice. Re-resolve and review
this inventory and the notices when dependencies change. Do not assume a new
dependency has the same licence as its group.

`licenses/U_DIN_OFL.txt` is the complete original copyright and OFL notice from
the bundled font's name-table licence entry. This preserves both `usr_share`
and Peter Wiegel, plus the reserved font name. Font bytes are unchanged.

`VOSK_NATIVE_NOTICES.txt` supplements the AAR notices with the static native
dependencies identified in Vosk's binary and upstream build recipe.
`ANDROID_CONVERSION_NOTICES.txt` follows the packaged Android export report's
tool versions. Each includes original licence URLs, text hashes and a clear
distinction between reviewed source revisions and attested binary provenance.

The source audit and remaining model-release review items are documented in
`../../docs/license-audit-2026-09-10/README.md`.
