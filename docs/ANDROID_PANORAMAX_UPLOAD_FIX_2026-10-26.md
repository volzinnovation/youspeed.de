# Android Panoramax upload selection — 26 October 2026

The attached Moto g86 on 1.5-debug / build 10072 showed **Batch is not
reviewable** in the photo gallery after an upload attempt. The application
remained responsive. Its queue also contained seven batches in `PROCESSING`.
Owner-authorized, read-only status checks confirmed that all seven batches had
already completed on Panoramax: every response reported `ready=true` and
`completed=true`, with no broken, rejected or pending photos. Three sets are
empty; a ready set does not establish that every originally estimated photo
remains published.

Android reused the gallery's local selection as its upload selection. Selecting
all therefore tried to approve completed or processing batches again, which the
queue correctly rejects. The iPhone gallery instead filters selected photos by
batch and item eligibility, then separately resumes existing remote work. Its
Upload action remains available for resumable batches without a new selection.

Android now uses that same distinction in the gallery and controller. The
upload count includes only eligible selected originals. Completed, accepted and
ambiguous items remain available for local gallery actions without being
reapproved or resent. Existing processing and accepted partial batches resume
through the ordinary upload worker; a resume-only action is labeled explicitly.
Capture gating, original-file preflight, opt-in retention and the prohibition on
automatic uploads remain in effect.

A separate Android error-reporting defect classified `SocketTimeoutException`
as intentional interruption because it inherits `InterruptedIOException`.
Timeouts now show a connection-timeout message with a resume instruction. The
in-flight item remains `ABANDONED`, preserving the existing duplicate-avoidance
behavior; remaining queued items are available for explicit resume. The device
evidence did not establish that a timeout caused the reported attempt.

Validation before installation:

- All 51 Panoramax JVM tests pass, including mixed select-all/resume dispatch,
  terminal/ambiguous item exclusion, and timeout/resume persistence.
- Normal build 10073 assembles successfully.
- The gallery instrumented test compiles, including a mixed-state selection
  fixture that checks separate delete/upload counts and the resume-only control.
- Both gallery instrumented tests pass on the physical Moto in the separate
  `de.youspeed.android.testhost` app. The new test verifies nine selected local
  photos yield an upload count of three, then verifies the resume-only control
  when only finished/processing photos remain. The existing layout test checks
  landscape, portrait and enlarged text.
- iPhone parity was checked against `PanoramaxGalleryView` in `MainView.swift`
  and the upload workflow in `DriveSessionViewModel.swift`. No iPhone source or
  shared speed-reference policy was changed.

Build 10073 was installed in place on the attached Moto with owner approval.
The installed package reports `de.youspeed.android.debug`, version `1.5-debug`,
version code `10073`. APK SHA-256:
`c3337a9c617ee3ed01ab9b8f403764107e922ae0b0087ae9e15901eaadc4f7f3`.
No uninstall or data-clear operation was used. The main preferences, trip
preferences and active-map pointer hashes match before/after installation;
the JPEG file count remains 2,072 (originals plus thumbnails). Queue metadata
hashes changed during the app lifecycle, so this is not a claim of identical
queue bytes. The launched dashboard still reports 1,036 local photos. The
startup retention prompt was answered with **Logs behalten und fortfahren**.
In the normal installed gallery, **Alle auswählen** selected 1,036 local photos
for local actions while the upload action remained **Upload fortsetzen**:
none were counted as new transferable photos. The selection was then cleared
without starting an upload or deletion.

The driver's saved **delete local images after upload** setting is enabled.
Server completion was therefore checked independently using read-only GETs;
the live app's Resume action was not activated, because completing the local
queue through that action would apply the saved cleanup preference. This
preserves the current local photos while verifying remote completion.

Private APKs, test output, hash-only preservation records and filtered server
status receipts are at `/private/tmp/youspeed-upload-10073/`.

Full queue export was declined by automatic privacy review. Diagnosis used
on-device field filtering and counters, without copying originals, credentials
or precise photo locations into the repository. Expanded server-status checks
were initially declined; the owner then explicitly approved checks for all
seven existing batches. No new photos were uploaded.
