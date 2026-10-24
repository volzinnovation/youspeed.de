# Conditional speed restrictions — implementation and device verification

The owner requested completion of OSM and camera restriction handling, including
ignoring a conditional limit outside its time window, while retaining own
corrections > camera evidence > accepted government evidence (MobiData only in
Baden-Württemberg) > OSM. Data-structure optimization remains separate. The
owner's subsequent setup, disabled-journal notice and town-entry preview fixes
are included in [the combined build 10064](V1_5_BUILD_10064_2026-10-24.md).

## OSM and bundle

The full `2026-10-23-v1.5-journal-conditional` bundle retains raw source tags,
9,672 interpreted way sets and 15,797 ordered rules. A fresh streamed verification
checks both compressed and uncompressed hashes, gzip integrity, sidecars and
compiler provenance. A materialized database also passed SQLite `quick_check`.
Its database SHA-256 is
`e973d279de2803b13037b9e87132be72f28a22d8f9c9bbef79d73093772b1849`.

Both evaluators retain the geographic time zone during cached reevaluation and
reject incomplete capability declarations. Time windows are start-inclusive and
end-exclusive; overnight weekdays follow the date on which the window starts.
An inactive conditional clause leaves an independently established base value in
force. Missing wetness, holiday, unsupported vehicle/lane or other necessary
context remains unresolved instead of inventing a current limit.

Condition-aware bundle offers retain the evaluated rule AST, selected result and
evaluation time in the existing applicability envelope. Cached replay and camera
reevaluation preserve that metadata at the current revision. An inactive clause
can still yield an applicable independent base; its envelope does not claim that
the inactive clause is active.

Eight checks use exact rules extracted from this bundle: way 3453385 has base 50
and night-only 30; way 4014680 has base 120 and night-only unlimited. Daytime,
start, before-end and exact-end cases pass in the native Swift evaluator, including
its cached reevaluation path.

Selected regional versions must supersede older copies during coverage loading
and route probing. A stale numeric value must not win over an unresolved
conditional rule from the activated version. Older files can remain available
for rollback without participating as competing versions of that region.

- [Full bundle verification](../output/conditional-restrictions-10063/bundle-readiness.json)
- [Exact packaged rules](../output/conditional-restrictions-10063/actual-bundle-schedule-cases.json)
- [Native packaged-rule results](../output/conditional-restrictions-10063/actual-bundle-swift-evaluation.json)

## Camera acceptance contract

Live authority requires measured source-pixel evidence, exact parent/plate
association, complete supported text and agreement from two distinct captured
frames. Interpolated OCR passes over one frame do not count as independent frames.
An unread, clipped, deferred or ambiguous assembly must not become a bare numeric
claim. A detector returning no plate is not by itself proof of a plain sign.

The original observation time, distance and road/session scope remain fixed
across OCR retries and clock reevaluation. Inactive and unresolved rules cannot
produce an authoritative camera limit, while valid independent evidence and own
corrections retain their priority. Repeated active/inactive transitions must not
renew evidence or leave a withdrawn limit active.

Positive road/lane applicability, the captured frame and exact numeric parent
must agree with the live assembly evidence. A newer physical speed sign retires
older conditional evidence even when its schedule has never been active. The
original 300-second/5-km expiry still applies. A civil-clock change in an OSM rule
does not by itself invalidate a camera sign on the same road and bundle lineage.
Known deferred plates immediately revoke an earlier plain-sign admission.

Both live readers retain their six-attempt budget and minimum 300-ms retry
spacing. A successful later read permits a bounded confirming read without
requiring another 80% increase in crop area. Frame interpolation remains useful
for reading text but cannot provide independent confirmation.

The shared reference-policy check passes 39 scenarios and 171 steps, covering
all 16 transitions and five states. Its policy files, approval lock and both
application pins are unchanged. The simple Fahrtenbuch screen and journal UI
files are byte-identical to their state before this restriction work.

- [Policy and UI preservation check](../output/conditional-restrictions-10063/preservation-check.json)

## Native verification

iPhone: the focused batch completed 177 tests with 175 passes, two existing
intentional skips and zero failures. The final controller-source follow-up
passed all 14 tests. Coverage includes live activation and repeated clock
boundaries, unsupported and unread conditions, exact parent/frame/road scope,
original expiry, own corrections, later-sign supersession, independent zone
fallback, OSM envelopes, routing, passage and collection.

The actual Vision fixture run reads 19 of the 32 shared crops and abstains on 13.
The complete native night-plate proof passes with an annotated primary box.
Fixture primary boxes, frame identities and times are controlled test inputs;
that proof alone does not demonstrate CoreML detection-to-admission. These are
OCR and state-transition checks, not two independently recorded roadside
captures or a field recognition-rate estimate.

Two unmodified 4224×2376 original scenes have now been retrieved from the public
YouSpeed Panoramax instance. Both hashes exactly match the fixture manifest's
source asset hashes, and both visibly contain the complete 30/22–6h assembly.
Both native detector-to-proof paths pass on the original night-sign scene
`0c6575e7`; the other scene is conservatively withheld for unknown geometry.
Controlled frame identities replay the static image, so this does not establish
naturally recorded two-frame recognition or field accuracy.
The [original scene fixtures](../tests/fixtures/tsr-ocr-32/source-scenes/README.md)
retain source links, hashes and CC BY-SA attribution and are included only in
test resources.

Android: the final JVM batch completed 855 tests with 854 passes, one existing
skip and zero failures or errors. All 34 final native ML Kit and controller
checks pass against the matching original-pixel and envelope implementation.

- [iPhone native validation](../output/conditional-restrictions-10063/iphone/validation.json)
- [iPhone final source hashes](../output/conditional-restrictions-10063/iphone/source-hashes.json)

## Physical installation status

The final combined build 10064 is installed on both phones. The full conditional
bundle is active on Android and the iPhone active pointer and manifest have
been read back and verified. The iPhone database passed complete device
readback, exact SHA-256 and SQLite `quick_check` before activation.

The Mac's signing-key authorization failure cleared after the owner restarted
the Mac; the same identity signed and verified successfully without changing
keychain access or certificate trust. The iPhone launched and its normal
dashboard was inspected in QuickTime after the startup log prompt.
Post-launch metadata confirms the conditional map remains active. The old
iPhone GPS/matcher/TSR files are no longer listed after the owner-confirmed Keep
action. Synthetic UI checks preserve every fixture byte on iOS 18.6 and 26.5;
the physical outcome remains unexplained and is tracked in the combined record.
Android's new history-to-normal-Settings flow was verified on
the physical phone. Existing iPhone preferences are identical immediately after
installation, and original journal files remain. Original GPS/TSR
logs stay on the phones per the owner's instruction. No backend or store
publication was performed.
