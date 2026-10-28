package de.youspeed.android.alpha

/** Performance and UI diagnostics already have a dedicated debug log. Keep
 * actual observations, state changes, failures and future evidence in Fahrten. */
internal class AppDiagnosticJournalPolicy {
    private var lastCaptureConfiguration: Map<String, Any?>? = null
    private var lastCaptureConfigurationLogGeneration: Long? = null

    fun retainInJournal(event: String, details: Map<String, Any?> = emptyMap()): Boolean {
        if (details["terminalBackendFailure"] == true || failureKeys.any { key ->
                details[key]?.let { it !is String || it.isNotBlank() } == true
            }) return true
        return when (event) {
            "traffic_sign_camera_analysis" -> details["stage"] !in cameraHousekeepingStages
            "speech_playback" -> details["state"] !in routineSpeechStates
            else -> event !in debugLogOnlyEvents
        }
    }

    /** A debug-log generation changes after off/on, so the first configuration
     * is written again even when the camera settings themselves did not change. */
    @Synchronized
    fun shouldLogCaptureConfiguration(details: Map<String, Any?>, logGeneration: Long?): Boolean {
        if (logGeneration == null) return false
        val configuration = details.filterKeys { it != "reason" }
        if (lastCaptureConfigurationLogGeneration == logGeneration && lastCaptureConfiguration == configuration) return false
        lastCaptureConfigurationLogGeneration = logGeneration
        lastCaptureConfiguration = configuration
        return true
    }

    private companion object {
        val failureKeys = setOf("error", "exception", "backendFailureReason", "accelerationFallbackReason")
        val cameraHousekeepingStages = setOf("cadence", "first_frame", "consumer_changed", "graph_bound")
        val routineSpeechStates = setOf("started", "finished")
        val debugLogOnlyEvents = setOf(
            "speed_lookup_publication",
            "traffic_sign_inference",
            "lane_preview_frame",
            "lane_preview_performance",
            "lane_overlay_presentation",
            "capture_configuration",
            "sign_ui_composition",
        )
    }
}
