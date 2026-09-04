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

    /** Stable bundle identity; per-way/value decorations are navigation state, not a new bundle. */
    val bundleRevision: String
        get() = osmRevision.substringBefore("|way:")
}

/** Snapshot taken with the frame, before any asynchronous inference starts. */
data class TrafficSignDetectionContext(
    val wayId: String?,
    val latitude: Double,
    val longitude: Double,
    val headingDegrees: Double,
    val travelDirection: TrafficSignTravelDirection,
    val sourceSignature: TrafficSignRuntimeSourceSignature,
    /** Verified SHA-256 of the materialized SQLite bundle used for this match. */
    val bundleSha256: String? = null,
    val countryCode: String = "DEU",
    val routeRelationGroupIds: Set<Long> = emptySet(),
    val sourceRelationIds: Set<Long> = emptySet(),
    val continuityCapable: Boolean = false,
    val traversalEpoch: Long = 0L,
    val matchedWayStable: Boolean = true,
    val speedMetersPerSecond: Double = 0.0,
) {
    init {
        require(wayId == null || wayId.isNotBlank()) { "Detection way ID must not be blank" }
        require(latitude.isFinite() && latitude in -90.0..90.0) { "Detection latitude is invalid" }
        require(longitude.isFinite() && longitude in -180.0..180.0) { "Detection longitude is invalid" }
        require(headingDegrees.isFinite() && headingDegrees >= 0.0 && headingDegrees < 360.0) {
            "Detection heading is invalid"
        }
        require(countryCode.isNotBlank()) { "Detection country code is required" }
        require(bundleSha256 == null || VERIFIED_SHA256.matches(bundleSha256)) {
            "Detection bundle SHA-256 is invalid"
        }
        require(routeRelationGroupIds.none { it <= 0L }) { "Route-relation group IDs must be positive" }
        require(sourceRelationIds.none { it <= 0L }) { "Source relation IDs must be positive" }
        require(traversalEpoch >= 0L) { "Traversal epoch must not be negative" }
        require(speedMetersPerSecond.isFinite() && speedMetersPerSecond >= 0.0) {
            "Detection speed is invalid"
        }
    }

    val hasVerifiedBundle: Boolean
        get() = bundleSha256 != null && VERIFIED_SHA256.matches(bundleSha256)

    private companion object {
        val VERIFIED_SHA256 = Regex("^[a-f0-9]{64}$")
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

    /** Only a finalized visible-to-missing passage may change the legacy numeric projection. */
    fun applyPassage(
        current: TrafficSignSpeedOverride?,
        event: TrafficSignPassageEvent,
    ): TrafficSignSpeedOverride? {
        if (!event.overrideEligible || event.action.isConditional || !event.action.isPermanentRuntimeAction) return current
        val context = event.activationContext ?: return current
        if (context.wayId.isNullOrBlank() || context.travelDirection == TrafficSignTravelDirection.UNKNOWN) return current
        if (!context.continuityCapable || !context.matchedWayStable || !context.hasVerifiedBundle) return current
        if (current != null && !event.passageBoundary.timestampUtc.isAfter(current.detectedAtUtc)) return current
        return when (event.resolution.kind) {
            TrafficSignResolvedLimitKind.NUMERIC -> TrafficSignSpeedOverride(
                speedKmh = requireNotNull(event.resolution.speedKmh),
                detectedAtUtc = event.passageBoundary.timestampUtc,
                trackId = event.physicalTrackId,
                context = context,
            )
            else -> null
        }
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
