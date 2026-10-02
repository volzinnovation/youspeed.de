# Shared country rules

These JSON files are the single source for both native apps and map-bundle
generation. Gradle packages them at `assets/Rules/`; XcodeGen includes the same
files as app resources. Existing filenames and JSON schemas are unchanged.

Edit rules here. Do not restore copies under either app source tree. The original
source citations and review dates are retained inside each file and in the offline
attribution catalog.

Run `python3 scripts/check_mobile_rules.py` from the repository root. To verify
actual built resources, add `--android-apk <apk>` and/or `--iphone-app <app>`.
The checker compares the complete country set and byte contents with this source.
