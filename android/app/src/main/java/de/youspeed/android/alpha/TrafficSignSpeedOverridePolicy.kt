package de.youspeed.android.alpha

enum class TrafficSignTravelDirection(val wireValue: String) {
    FORWARD("forward"),
    REVERSE("reverse"),
    UNKNOWN("unknown"),

    ;

    companion object {
        fun fromWire(raw: String): TrafficSignTravelDirection = entries.firstOrNull { it.wireValue == raw }
            ?: error("Unsupported traffic-sign travel direction: $raw")
    }
}

data class TrafficSignRuntimeSourceSignature(
    val osmRevision: String,
    val localCorrectionRevision: String?,
) {
    init {
        require(osmRevision.isNotBlank()) { "OSM source revision is required" }
        require(localCorrectionRevision == null || localCorrectionRevision.isNotBlank()) {
            "Local-correction revision must not be blank"
        }
    }
}

/** Snapshot taken with the frame, before any asynchronous inference starts. */
data class TrafficSignDetectionContext(
    val wayId: String,
    val latitude: Double,
    val longitude: Double,
    val headingDegrees: Double,
    val travelDirection: TrafficSignTravelDirection,
    val sourceSignature: TrafficSignRuntimeSourceSignature,
) {
    init {
        require(wayId.isNotBlank()) { "Detection way ID is required" }
        require(latitude.isFinite() && latitude in -90.0..90.0) { "Detection latitude is invalid" }
        require(longitude.isFinite() && longitude in -180.0..180.0) { "Detection longitude is invalid" }
        require(headingDegrees.isFinite() && headingDegrees >= 0.0 && headingDegrees < 360.0) {
            "Detection heading is invalid"
        }
    }
}

data class TrafficSignSpeedOverride(
    val speedKmh: Int,
    val detectedAtUtc: java.time.Instant,
    val trackId: String?,
    val context: TrafficSignDetectionContext,
)

/** Pure transition rules; controller wiring deliberately remains outside this slice. */
object TrafficSignSpeedOverridePolicy {
    /**
     * Pack/event v2 enters the app only through this fail-closed overload in
     * M0. Even a confirmed numeric shadow event leaves the current source
     * untouched. Gate reports in a pack are evidence, not runtime authority.
     */
    @Suppress("UNUSED_PARAMETER")
    fun applyRecognition(
        current: TrafficSignSpeedOverride?,
        event: TrafficSignRecognitionEventV2,
        currentSourceSignature: TrafficSignRuntimeSourceSignature,
    ): TrafficSignSpeedOverride? = current

    fun applyRecognition(
        current: TrafficSignSpeedOverride?,
        event: TrafficSignRecognitionEvent,
        currentSourceSignature: TrafficSignRuntimeSourceSignature,
    ): TrafficSignSpeedOverride? {
        if (event.state != TrafficSignRecognitionState.CONFIRMED) return current
        if (event.source == TrafficSignInputSource.DIAGNOSTIC_IMPORT) return current
        if (current != null && !event.frameTimestampUtc.isAfter(current.detectedAtUtc)) return current
        val context = event.roadContext ?: return current
        if (context.travelDirection == TrafficSignTravelDirection.UNKNOWN) return current
        if (context.sourceSignature != currentSourceSignature) return current

        // Any newer confirmed sign ends the older speed assertion. A numeric
        // maximum-speed sign immediately replaces it with a fresh override.
        val candidate = event.candidate ?: return null
        val speed = candidate.semantic.value
            ?.takeIf {
                it > 0 &&
                    candidate.semantic.kind in setOf(
                        TrafficSignSemanticKind.MAXIMUM_SPEED,
                        TrafficSignSemanticKind.ZONE_START,
                        TrafficSignSemanticKind.TEMPORARY,
                    ) &&
                    candidate.semantic.unit == "km/h" &&
                    candidate.conditionState == TrafficSignConditionState.NONE &&
                    candidate.restrictions.isEmpty()
            }
            ?: return null
        return TrafficSignSpeedOverride(
            speedKmh = speed,
            detectedAtUtc = event.frameTimestampUtc,
            trackId = candidate.trackId,
            context = context,
        )
    }

    /**
     * Repeated GPS fixes must not clear a vision result. Only a source revision
     * change—meaning genuinely new bundled-map/local-correction information—does.
     */
    fun reconcileSource(
        current: TrafficSignSpeedOverride?,
        sourceSignature: TrafficSignRuntimeSourceSignature,
    ): TrafficSignSpeedOverride? {
        return current?.takeIf { it.context.sourceSignature == sourceSignature }
    }

    fun effectiveSpeedKmh(
        current: TrafficSignSpeedOverride?,
        localCorrectionKmh: Int?,
        bundledMapKmh: Int?,
    ): Int? = current?.speedKmh ?: localCorrectionKmh ?: bundledMapKmh
}
