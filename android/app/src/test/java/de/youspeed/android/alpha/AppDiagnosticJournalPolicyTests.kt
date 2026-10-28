package de.youspeed.android.alpha

import java.util.concurrent.Callable
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test

class AppDiagnosticJournalPolicyTests {
    @Test fun repeatedPerformanceAndUiDiagnosticsStayInTheirDedicatedLog() {
        val policy = AppDiagnosticJournalPolicy()
        listOf(
            "speed_lookup_publication", "traffic_sign_inference",
            "lane_preview_frame", "lane_preview_performance", "lane_overlay_presentation",
            "capture_configuration", "sign_ui_composition",
        ).forEach { event -> assertFalse(event, policy.retainInJournal(event)) }
    }

    @Test fun healthyInferenceTelemetryIsOmittedButEmbeddedFailuresRemainInJournal() {
        val policy = AppDiagnosticJournalPolicy()
        val healthy = mapOf<String, Any?>("frameId" to "frame-7", "inferenceMs" to 220.0,
            "executionBackend" to "cpu", "accelerationFallbackReason" to "",
            "backendFailureReason" to null, "terminalBackendFailure" to false)
        assertFalse(policy.retainInJournal("traffic_sign_inference", healthy))
        listOf("error", "exception", "backendFailureReason", "accelerationFallbackReason").forEach { field ->
            assertTrue(field, policy.retainInJournal("traffic_sign_inference", healthy + (field to "Backend unavailable")))
            assertFalse(field, policy.retainInJournal("traffic_sign_inference", healthy + (field to " \t")))
        }
        assertTrue(policy.retainInJournal("traffic_sign_inference", healthy +
            ("accelerationFallbackReason" to "GPU delegate initialization failed; using CPU")))
        assertTrue(policy.retainInJournal("traffic_sign_inference", healthy + ("terminalBackendFailure" to true)))
        assertTrue(policy.retainInJournal("traffic_sign_inference", healthy + ("exception" to mapOf("code" to "future_failure"))))
    }

    @Test fun onlyKnownCameraHousekeepingStagesAreOmittedAndFailuresArePreserved() {
        val policy = AppDiagnosticJournalPolicy()
        listOf("cadence", "first_frame", "consumer_changed", "graph_bound").forEach { stage ->
            assertFalse(stage, policy.retainInJournal("traffic_sign_camera_analysis", mapOf("stage" to stage)))
        }
        assertTrue(policy.retainInJournal("traffic_sign_camera_analysis", mapOf("stage" to "future_ocr_evidence")))
        assertTrue(policy.retainInJournal("traffic_sign_camera_analysis", emptyMap()))
        assertTrue(policy.retainInJournal("traffic_sign_camera_analysis", mapOf("stage" to "cadence", "error" to "Camera disconnected")))
    }

    @Test fun typedEvidenceStateChangesFailuresAndUnknownEventsRemainInJournal() {
        val policy = AppDiagnosticJournalPolicy()
        listOf(
            "recognition", "supplementary_ocr", "tsr_applicability_v1", "tsr_path_evidence_v1",
            "tsr_path_recording_v1", "speed_reference", "traffic_sign_camera_runtime",
            "lookup_worker_failed", "uncaught_exception", "future_frame_evidence",
        ).forEach { event -> assertTrue(event, policy.retainInJournal(event)) }
    }

    @Test fun speechPlaybackKeepsActualFailureInterruptionAndUnknownStatePayloads() {
        val policy = AppDiagnosticJournalPolicy()
        val utterance = mapOf<String, Any?>("utteranceId" to "speed-warning-7")
        listOf("started", "finished").forEach { state ->
            assertFalse(state, policy.retainInJournal("speech_playback", utterance + ("state" to state)))
        }
        listOf("failed", "interrupted", "future_state").forEach { state ->
            assertTrue(state, policy.retainInJournal("speech_playback", utterance + ("state" to state)))
        }
        assertTrue(policy.retainInJournal("speech_playback", utterance))
        assertTrue(policy.retainInJournal("speech_playback", utterance + mapOf("state" to "started", "error" to "Playback failed")))
    }

    @Test fun captureConfigurationIgnoresReasonButKeepsRealChangesAndNewFields() {
        val policy = AppDiagnosticJournalPolicy()
        val initial = mapOf("photosEnabled" to true, "recognitionEnabled" to false, "reason" to "startup")
        assertTrue(policy.shouldLogCaptureConfiguration(initial, 0))
        assertFalse(policy.shouldLogCaptureConfiguration(initial + ("reason" to "camera_reconciled"), 0))
        assertTrue(policy.shouldLogCaptureConfiguration(initial + ("recognitionEnabled" to true), 0))
        assertFalse(policy.shouldLogCaptureConfiguration(initial + mapOf("recognitionEnabled" to true, "reason" to "location"), 0))
        assertTrue(policy.shouldLogCaptureConfiguration(initial, 0))
        assertTrue(policy.shouldLogCaptureConfiguration(initial + ("futureConfiguration" to "available"), 0))
    }

    @Test fun disabledLoggingDoesNotRememberUnwrittenConfigurationsAndReenableLogsCurrentState() {
        val policy = AppDiagnosticJournalPolicy()
        val logging = DebugLogPersistence(initiallyEnabled = false)
        val details = mapOf("photosEnabled" to true)
        assertFalse(policy.shouldLogCaptureConfiguration(details, logging.ticket()))
        logging.setEnabled(true)
        assertTrue(policy.shouldLogCaptureConfiguration(details, logging.ticket()))
        assertFalse(policy.shouldLogCaptureConfiguration(details, logging.ticket()))
        logging.setEnabled(false)
        assertFalse(policy.shouldLogCaptureConfiguration(details + ("photosEnabled" to false), logging.ticket()))
        logging.setEnabled(true)
        assertTrue(policy.shouldLogCaptureConfiguration(details, logging.ticket()))
        assertFalse(policy.shouldLogCaptureConfiguration(details, logging.ticket()))
    }

    @Test fun captureConfigurationRemembersAValueSnapshot() {
        val policy = AppDiagnosticJournalPolicy()
        val details = mutableMapOf<String, Any?>("photosEnabled" to true)
        assertTrue(policy.shouldLogCaptureConfiguration(details, 0))
        details["photosEnabled"] = false
        assertTrue(policy.shouldLogCaptureConfiguration(details, 0))
        assertFalse(policy.shouldLogCaptureConfiguration(mapOf("photosEnabled" to false), 0))
    }

    @Test fun concurrentIdenticalConfigurationsProduceOneDiagnostic() {
        val policy = AppDiagnosticJournalPolicy()
        val start = CountDownLatch(1)
        val workers = Executors.newFixedThreadPool(8)
        try {
            val results = (1..24).map {
                workers.submit(Callable {
                    check(start.await(5, TimeUnit.SECONDS))
                    policy.shouldLogCaptureConfiguration(mapOf("photosEnabled" to true), 0)
                })
            }
            start.countDown()
            assertEquals(1, results.count { it.get(5, TimeUnit.SECONDS) })
        } finally {
            start.countDown()
            workers.shutdownNow()
        }
    }
}
