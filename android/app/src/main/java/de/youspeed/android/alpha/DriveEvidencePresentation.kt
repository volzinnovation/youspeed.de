package de.youspeed.android.alpha

/** Display decoration only; current authority wins over a retained map origin. */
internal object MobiDataSignSourcePresentation {
    fun isMobiData(sourceId: String?): Boolean = sourceId == "mobidata-bw-vzk"

    fun showsLimitContour(source: EffectiveSpeedLimitSource, hasValue: Boolean, provenance: BundleSpeedProvenance?,
                          isInSpeedCaptureMode: Boolean, hasPendingCameraLimit: Boolean,
                          showsCameraEndSign: Boolean): Boolean =
        !isInSpeedCaptureMode && !hasPendingCameraLimit && !showsCameraEndSign && hasValue &&
            source == EffectiveSpeedLimitSource.BUNDLE && isMobiData(provenance?.sourceId) &&
            when (provenance?.kind) {
                "inventory_sign", "inventory_town_context", "inventory_reset_context" -> true
                else -> false
            }
}

/** Describes the bundle evidence without changing the speed resolver's authority. */
data class BundleSpeedProvenance(
    val kind: String,
    val sourceId: String? = null,
    val signId: String? = null,
    val ruleId: String? = null,
    val signCode: String? = null,
    val snapshotSha256: String? = null,
    val wayId: String? = null,
    val direction: Int? = null,
)

enum class TrafficSignRuntimeStatus {
    DISABLED, WAITING_LOCATION, PAUSED_NIGHT, PAUSED_SESSION, WAITING_CAMERA, UNAVAILABLE, ACTIVE,
}

internal object DriveEvidencePresentation {
    fun retainSecondary(reason: String, preserveDisplay: Boolean = false): Boolean = preserveDisplay ||
        reason !in setOf("bundle_country_switch", "drive_started", "drive_stopped", "bundle_removed")

    fun recognitionStatus(selected: Boolean, daylightAllowed: Boolean, hasLocation: Boolean,
                          sessionAllowed: Boolean, camera: TrafficSignCameraRuntimeState): TrafficSignRuntimeStatus = when {
        !selected -> TrafficSignRuntimeStatus.DISABLED
        !hasLocation -> TrafficSignRuntimeStatus.WAITING_LOCATION
        !daylightAllowed -> TrafficSignRuntimeStatus.PAUSED_NIGHT
        !sessionAllowed -> TrafficSignRuntimeStatus.PAUSED_SESSION
        camera in setOf(TrafficSignCameraRuntimeState.DENIED, TrafficSignCameraRuntimeState.FAILED,
            TrafficSignCameraRuntimeState.UNAVAILABLE) -> TrafficSignRuntimeStatus.UNAVAILABLE
        camera != TrafficSignCameraRuntimeState.ACTIVE -> TrafficSignRuntimeStatus.WAITING_CAMERA
        else -> TrafficSignRuntimeStatus.ACTIVE
    }

    fun mapProvenance(source: DerivedSpeedSource, wayId: String?, direction: TrafficSignTravelDirection): BundleSpeedProvenance? =
        when (source) {
            DerivedSpeedSource.EXPLICIT_TAG, DerivedSpeedSource.INHERITED_TAG, DerivedSpeedSource.EXPLICIT_UNLIMITED_TAG -> "osm_tag"
            DerivedSpeedSource.HIGHWAY_CLASS -> "road_default"
            else -> null
        }?.let { BundleSpeedProvenance(it, wayId = wayId,
            direction = when (direction) { TrafficSignTravelDirection.FORWARD -> 1; TrafficSignTravelDirection.REVERSE -> -1; else -> null }) }

    fun inventoryProvenance(kind: String, sign: InventorySign?, rule: InventoryWayRule? = null): BundleSpeedProvenance =
        BundleSpeedProvenance(kind, sign?.sourceId, sign?.id, rule?.id, sign?.code, sign?.snapshotSha256,
            rule?.wayId ?: sign?.associatedWayId, rule?.direction ?: sign?.associatedDirection)

    /** Current authority wins: an old inventory origin must never label camera/local/stale output. */
    fun sourceKind(source: EffectiveSpeedLimitSource, hasValue: Boolean, bundle: BundleSpeedProvenance?): String = when {
        !hasValue -> "unknown"
        source == EffectiveSpeedLimitSource.CAMERA -> "camera"
        source == EffectiveSpeedLimitSource.LOCAL_CORRECTION -> "local_correction"
        source == EffectiveSpeedLimitSource.STALE_BUNDLE -> "stale_bundle"
        source == EffectiveSpeedLimitSource.LAST_KNOWN -> "last_known"
        source == EffectiveSpeedLimitSource.BUNDLE -> bundle?.kind ?: "bundle"
        else -> "unknown"
    }
}
