package de.youspeed.android.alpha

import java.time.Instant
import org.junit.Assert.*
import org.junit.Test

class ConsumerLifecycleParityTests {
    @Test fun automaticPhotosFollowSelectionAndLifecycleWithoutDashcamOrTsr() {
        assertTrue(DriveRecorderPolicy.shouldRunAutomaticPhotos(true, true, true, true))
        assertFalse(DriveRecorderPolicy.shouldRunAutomaticPhotos(false, true, true, true))
        assertFalse(DriveRecorderPolicy.shouldRunAutomaticPhotos(true, false, true, true))
        assertFalse(DriveRecorderPolicy.shouldRunAutomaticPhotos(true, true, false, true))
        assertFalse(DriveRecorderPolicy.shouldRunAutomaticPhotos(true, true, true, false))
        assertFalse(PanoramaxCapturePolicy.isMoving(0.0))
        assertFalse(PanoramaxCapturePolicy.isMoving(-1.0))
        assertFalse(PanoramaxCapturePolicy.isMoving(Double.NaN))
        assertTrue(PanoramaxCapturePolicy.isMoving(0.5))
    }

    @Test fun standaloneRecognitionIsOptInAndRequiresForegroundDriving() {
        assertFalse(DriveRecorderPolicy.shouldRunRecognition(true, false, false, true, true))
        assertTrue(DriveRecorderPolicy.shouldRunRecognition(true, true, false, true, true))
        assertTrue(DriveRecorderPolicy.shouldRunRecognition(true, false, true, true, true))
        assertFalse(DriveRecorderPolicy.shouldRunRecognition(false, true, true, true, true))
        assertFalse(DriveRecorderPolicy.shouldRunRecognition(true, true, true, false, true))
        assertFalse(DriveRecorderPolicy.shouldRunRecognition(true, true, true, true, false))
    }

    @Test fun reviewUnlocksAfterCaptureStopsIncludingErrorStates() {
        for (state in listOf(DriveRecorderState.REQUESTING_PERMISSION, DriveRecorderState.PREPARING,
            DriveRecorderState.RECORDING, DriveRecorderState.STOPPING)) {
            assertFalse(state.name, DriveRecorderPolicy.canProcessPanoramaxUploads(state))
        }
        for (state in listOf(DriveRecorderState.DISABLED, DriveRecorderState.DENIED,
            DriveRecorderState.FAILED, DriveRecorderState.UNAVAILABLE)) {
            assertTrue(state.name, DriveRecorderPolicy.canProcessPanoramaxUploads(state))
        }
        // The persisted capture preference must not lock the review library.
        assertTrue(ConsumerUiState().panoramaxCaptureEnabled)
        assertTrue(DriveRecorderPolicy.canProcessPanoramaxUploads(ConsumerUiState().driveRecorderState))
    }

    @Test fun previewRequiresAnActiveMovieAndYieldsToVoiceCorrection() {
        assertTrue(DriveRecorderPolicy.canShowPreview(DriveRecorderState.RECORDING, true, false))
        assertFalse(DriveRecorderPolicy.canShowPreview(DriveRecorderState.RECORDING, false, false))
        assertFalse(DriveRecorderPolicy.canShowPreview(DriveRecorderState.RECORDING, true, true))
        assertFalse(DriveRecorderPolicy.canShowPreview(DriveRecorderState.STOPPING, true, false))
    }

    @Test fun panoramaxSessionIsRecheckedWhenCameraWasAlreadyActive() {
        assertTrue(DriveRecorderPolicy.shouldEnsurePanoramaxCaptureSession(
            panoramaxEnabled = true,
            driving = true,
            applicationActive = true,
            cameraState = TrafficSignCameraRuntimeState.ACTIVE,
        ))
        assertFalse(DriveRecorderPolicy.shouldEnsurePanoramaxCaptureSession(
            panoramaxEnabled = true, driving = true,
            applicationActive = true, cameraState = TrafficSignCameraRuntimeState.STARTING,
        ))
        assertTrue(DriveRecorderPolicy.shouldEnsurePanoramaxCaptureSession(
            panoramaxEnabled = true, driving = true,
            applicationActive = true, cameraState = TrafficSignCameraRuntimeState.ACTIVE,
        ))
        assertFalse(DriveRecorderPolicy.shouldEnsurePanoramaxCaptureSession(
            panoramaxEnabled = false, driving = true,
            applicationActive = true, cameraState = TrafficSignCameraRuntimeState.ACTIVE,
        ))
    }

    @Test fun previewStaysAttachedWhileTelemetryIsVisible() {
        val telemetry = DriveRecorderPreviewPresentation.resolve(
            sessionAvailable = true,
            selection = DriveRecorderWorkspaceSelection.TELEMETRY,
            previewAvailable = true,
        )
        assertTrue(telemetry.isAttached)
        assertFalse(telemetry.isVisible)

        val preview = DriveRecorderPreviewPresentation.resolve(
            sessionAvailable = true,
            selection = DriveRecorderWorkspaceSelection.PREVIEW,
            previewAvailable = true,
        )
        assertTrue(preview.isAttached)
        assertTrue(preview.isVisible)

        val unavailable = DriveRecorderPreviewPresentation.resolve(
            sessionAvailable = true,
            selection = DriveRecorderWorkspaceSelection.PREVIEW,
            previewAvailable = false,
        )
        assertTrue(unavailable.isAttached)
        assertFalse(unavailable.isVisible)

        val noSession = DriveRecorderPreviewPresentation.resolve(
            sessionAvailable = false,
            selection = DriveRecorderWorkspaceSelection.PREVIEW,
            previewAvailable = true,
        )
        assertFalse(noSession.isAttached)
        assertFalse(noSession.isVisible)
    }

    @Test fun feedbackDeduplicatesAWholeTrackButPermitsDistinctSignsAndNewSessions() {
        val gate = TrafficSignFeedbackGate()
        val context = context()
        val now = Instant.parse("2026-09-11T12:00:00Z")
        assertTrue(gate.shouldEmit("sign-1", 30, context, now))
        assertFalse(gate.shouldEmit("sign-1", 30, context, now.plusSeconds(60)))
        assertTrue(gate.shouldEmit("sign-2", 30, context, now.plusSeconds(61)))
        gate.reset()
        assertTrue(gate.shouldEmit("sign-1", 30, context, now.plusSeconds(62)))
    }

    @Test fun missingTrackFeedbackUsesAnEightSecondContextCooldown() {
        val gate = TrafficSignFeedbackGate()
        val now = Instant.parse("2026-09-11T12:00:00Z")
        assertTrue(gate.shouldEmit(null, 30, context(), now))
        assertFalse(gate.shouldEmit(null, 30, context(), now.plusSeconds(7)))
        assertTrue(gate.shouldEmit(null, 30, context(), now.plusSeconds(8)))
        assertTrue(gate.shouldEmit(null, 50, context(), now.plusSeconds(9)))
    }

    private fun context() = TrafficSignDetectionContext("42", 49.0, 8.0, 90.0,
        TrafficSignTravelDirection.FORWARD, TrafficSignRuntimeSourceSignature("2026-09-11", null))
}
