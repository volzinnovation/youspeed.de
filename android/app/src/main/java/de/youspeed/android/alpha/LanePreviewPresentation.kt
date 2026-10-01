package de.youspeed.android.alpha

/** Current camera geometry, independent of map/TSR admission. No camera pixels retained. */
internal data class LanePreviewSourceGeometry(
    val scope: Long,
    val geometry: LaneImageGeometry,
    val observedAtNanos: Long,
    val thermalPaused: Boolean,
) {
    val orientationKey get() = "rear:rotation:${geometry.rotationDegrees}"
}

internal enum class LanePreviewPresentationMode { OBSERVED, CALIBRATION_REFERENCE, HIDDEN }
internal data class LanePreviewPresentationDecision(
    val mode: LanePreviewPresentationMode,
    val reason: String,
    val referenceLines: List<List<LanePoint>> = emptyList(),
) {
    val referenceOpacity get() = if (mode == LanePreviewPresentationMode.CALIBRATION_REFERENCE) .28f else 0f
}

/** Reference lines are display only; they never become detected road or sign evidence. */
internal object LanePreviewPresentationPolicy {
    fun decide(enabled: Boolean, visible: Boolean, active: Boolean, scope: Long,
        source: LanePreviewSourceGeometry?, calibration: VisualRoadCalibration?,
        matureBoundaryCount: Int, staleObservedBoundary: Boolean, nowNanos: Long): LanePreviewPresentationDecision {
        fun hidden(reason: String) = LanePreviewPresentationDecision(LanePreviewPresentationMode.HIDDEN, reason)
        if (!enabled) return hidden("lanes_disabled")
        if (!visible) return hidden("preview_hidden")
        if (!active) return hidden("activity_paused")
        if (source == null || source.scope != scope || source.geometry.width <= 0 || source.geometry.height <= 0 ||
            source.geometry.rotationDegrees !in listOf(0, 90, 180, 270)) return hidden("source_geometry_unavailable")
        if (source.thermalPaused) return hidden("thermal_paused")
        if (nowNanos - source.observedAtNanos !in 0..750_000_000L) return hidden("source_geometry_stale")
        if (matureBoundaryCount > 0) return LanePreviewPresentationDecision(LanePreviewPresentationMode.OBSERVED, "mature_boundaries")
        if (calibration == null) return hidden("calibration_unavailable")
        if (!calibration.compatible(source.geometry.uprightWidth, source.geometry.uprightHeight, source.orientationKey))
            return hidden("calibration_geometry_incompatible")
        return LanePreviewPresentationDecision(LanePreviewPresentationMode.CALIBRATION_REFERENCE,
            if (staleObservedBoundary) "stale_context" else "no_confirmed_boundaries",
            listOf(listOf(calibration.leftBottom, calibration.leftTop), listOf(calibration.rightBottom, calibration.rightTop)))
    }
}

/** Delay the fixed reference after observed paint disappears. Never retain or invent observed points. */
internal class LaneReferenceHysteresis {
    private var key: String? = null
    private var lastTime = Double.NEGATIVE_INFINITY
    private var referenceAfter = Double.NEGATIVE_INFINITY
    fun apply(decision: LanePreviewPresentationDecision, scope: String, now: Double): LanePreviewPresentationDecision {
        if (!now.isFinite()) return LanePreviewPresentationDecision(LanePreviewPresentationMode.HIDDEN,"invalid_timestamp")
        if (scope != key || now < lastTime) { key=scope; referenceAfter=now+1.0 }
        lastTime=now
        if (decision.mode == LanePreviewPresentationMode.OBSERVED) referenceAfter=now+2.0
        if (decision.mode == LanePreviewPresentationMode.CALIBRATION_REFERENCE && now < referenceAfter)
            return LanePreviewPresentationDecision(LanePreviewPresentationMode.HIDDEN,"reference_hysteresis")
        return decision
    }
}
