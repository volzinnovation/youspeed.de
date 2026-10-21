# Branch and device validation — 2026-10-10

Branch: `codex/youspeed-v1.4-app-foundations`. The remote default branch was inspected as `main`; no merge was performed. The owner authorized deployment to attached phones, test execution, fixes, logical commits, and a push to this branch. Store submission and website publication were not performed.

## Local suites and builds

| Check | Result |
| --- | --- |
| Python repository and map tests | 853 passed, 26 skipped, 570 subtests passed; Python 3.11 isolated environment |
| TSR mapping-review and attribution regression tests | 45 passed, including four newly added mapping-review cases |
| Node inspector and repository tests | 80 passed |
| Native Swift lane-preview tests | 90 passed |
| Frozen speed-reference contract | 39 scenarios, 171 steps, all 16 transitions and 5 states passed; artifact hashes and both app pins match |
| Shared mobile legal rules | 12 authoritative country rules passed |
| Store metadata and image validation | 220 files checked, zero errors |
| Android debug unit tests | 655 executed, zero failures/errors, one optional installed-map skip |
| Android release unit tests | 655 executed, zero failures/errors, one optional installed-map skip |
| Android debug/release builds and debug lint | Passed; lint has zero errors and 178 warnings |
| Android full isolated emulator suite | 145 executed: 126 passed, 18 skipped, one attribution-screen timeout; the corrected attribution target subsequently passed |
| Android affected-case reruns | All five smoke tests passed; real CameraX recorder/photo-continuity test passed; orientation and road-path targeted suite passed with the physical wall-time case skipped |
| Final iPhone isolated simulator unit suite | 613 executed: 587 passed, 26 skipped, zero failures |
| iPhone simulator UI suite | Initial full run: 12 passed and one failed. The failing manual-mount dashboard test passed after the preview accessibility fix in all six mount/preview combinations |
| Normal signed iPhone device build | Passed with the final source |

The real iPhone release-map download test passed in the earlier full simulator suite. It was excluded from the final unit rerun and physical retries because the physical download was slow; the other 26 skips require optional map fixtures, explicit physical-device opt-ins, or unsupported simulator hardware. The final unit fixtures inject confirmation-tone playback rather than opening a real simulator audio device. Three earlier audio-service aborts were diagnosed at `AVAudioEngine.mainMixerNode`, before this isolation was added. Live app confirmation audio is unchanged.

The Android attribution timeout was resolved by using an owned `ActivityScenario`, closing it after the test, and waiting for the legal sheet before opening credits. Its dedicated rerun passed in 23.4 seconds. The full emulator run and subsequent targeted pass cover 127 passing cases and 18 explicit skips; there was no second full run after this final test-only correction. The 18 skips require optional recorded/map fixtures, explicit live/hardware opt-ins, or physical GPU/timing capability. The Gradle progress display reported 163 at completion; the retained JUnit XML contains 145 test cases and is the source of these counts.

## Device availability and deployment limits

The iPhone 14 Pro and Moto g86 5G became available after reconnect/unlock requests. Both received isolated test installations. A normal iPhone build was installed and its dashboard inspected through a QuickTime movie preview, without recording. That installation preceded the final preview accessibility and unit-audio fixture changes.

The Android physical suite was interrupted by disconnection after 116 received test results. Its physical GPU and road-path wall-time benchmarks passed. Four fixture/UI test failures were investigated; a further suite placeholder resulted from lost device communication. Subsequent emulator reruns exercised the corrected fixture and navigation paths. Hardware wall-time acceptance runs only on a physical phone; GPU tests skip emulator CPU fallback.

The corrected iPhone physical attempt could not launch because the phone was locked and the test-manager connection was lost; it executed no actual tests. At the last connection check the iPhone was unavailable and Android discovery showed only the emulator. Complete final physical suites, Android parity acceptance, and deployment of both final normal builds remain pending reconnection and unlock. Simulator/emulator success does not constitute completed physical acceptance.

## iPhone test-isolation incident and recovery

The initial physical unit run used the normal application's data container. Some unit fixtures delete `Library/Application Support/SpeedConsumer`; the run log confirmed removal of the installed map. The run was stopped and the owner was informed. This was a validation error, not an intended data migration.

The exact Baden-Württemberg map version `2026-07-04` was restored from its published release archive, together with its manifest, coverage file, and active-bundle selection. A copy read back from the phone matched the original SQLite SHA-256:

`4f447cf8afc5faba75dc7a582ba89fc7173c86bae1f4a85d0402185f880bcc22`

Original driving logs and local observations from the affected support directory may also have been removed. Their full recovery has **not** been verified. The retained after-incident files are not proof that the original data survived. No claim is made that all original app data or preferences were recovered.

The test wrapper now installs `de.youspeed.SpeedConsumer.TestHost` by default. Destructive `SpeedConsumerTests` fixtures skip if launched in the normal app container. The hosted unit-test application does not create the live app's camera/view-model owner. Tests against the driver's installed app are restricted to explicitly selected UI tests. Android full-suite instructions likewise use the separate `de.youspeed.android.testhost` installation. Normal app builds omit these isolation suffixes.

## Evidence

Raw logs, result bundles, recovery files, screenshots, and the retained Android preference/active-map snapshot are outside the repository in `/tmp/youspeed-validation-20261010/`. Preserve this directory for follow-up investigation; it contains private device evidence and is not committed. Archived historical source restoration remains governed by `AGENTS.md` and `docs/DEVICE_EVIDENCE_BACKUP_2026-10-01.md`.

No frozen speed-reference policy, interpreter semantics, or shared pictogram artwork was changed. Preexisting untracked browser artifacts and `:memory:.ses` were left untouched and uncommitted.
