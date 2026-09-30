package de.youspeed.android.alpha

import kotlin.math.*
import kotlinx.serialization.json.*

/** Experimental sidecar only. It cannot authorize, suppress, or finalize a sign. */
data class RoadPathCameraFrame(
    val grayscale: ByteArray, val width: Int, val height: Int,
    val capturedAtSeconds: Double, val geometryId: String,
    val calibration: RoadPathCalibration?, val clockKnown: Boolean,
    val preprocessingMs: Double, val startedAtNanos: Long,
    val rawWidth: Int = width, val rawHeight: Int = height, val rotationDegrees: Int = 0,
    val sensorToBuffer: List<Double> = listOf(1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0),
    val sourceTimestampSeconds: Double? = null,
    val visualCalibration: VisualRoadCalibration? = null,
    val orientationKey: String = "",
)
internal data class RoadPathLiveOverlay(val boundaries: List<RoadBoundaryEvidence>, val capturedAtSeconds: Double,
    val geometry: LaneImageGeometry, val presentation: RoadBoundaryPresentationSnapshot? = null,
    val captureSessionID: String? = null, val orientationKey: String = "", val visualCalibrationRevision: String? = null)


/** One admitted exposure. Pixel storage is discarded after preparation; geometry is reused exactly once. */
class RoadPathPreparedFrame internal constructor(
    internal val owner: RoadPathSession,
    internal val frame: RoadPathCameraFrame,
    val frameId: String,
    internal val scope: TSRApplicabilityScope,
    internal val key: String,
    internal val location: RoadPathSession.LocationSnapshot,
    internal val serial: Long,
    val geometry: RoadBoundaryFrame,
    val presentation: RoadBoundaryPresentationSnapshot,
    val motionHint: RoadBoundaryMotionHint,
    val filterMs: Double,
    val geometryMs: Double,
    val preparationAddedMs: Double,
    val preparationReadyNanos: Long,
    internal val skipReason: String?,
    internal val publicationAtSeconds: Double,
    internal val publicationSuppressionReason: String?,
) {
    internal var consumed = false // Accessed only under the owner's serial evaluation lock.
}


class RoadPathSession(private val nowNanos: () -> Long = System::nanoTime) {
    internal data class Fix(val time: Double, val latitude: Double, val longitude: Double,
        val course: Double, val speed: Double, val accuracy: Double, val courseAccuracy: Double)
    internal data class LocationSnapshot(val fixes: List<Fix>, val origin: Fix?, val epoch: Long, val overlayEpoch: Long,
        val duplicateFixesDropped: Long, val outOfOrderFixesDropped: Long)
    private val lock = Any()
    private val evaluationLock = Any()
    private val fixes = ArrayDeque<Fix>()
    private var origin: Fix? = null
    private var locationEpoch = 0L
    private var duplicateFixesDropped = 0L
    private var outOfOrderFixesDropped = 0L
    // Only the serial evaluator owns association history; location callbacks never mutate it.
    private var evaluatedLocationEpoch = -1L
    private var scope: String? = null
    private var lastCapture = Double.NEGATIVE_INFINITY
    private var lastSourceTimestampSeconds: Double? = null
    private val histories = linkedMapOf<String, List<RoadPathObservation>>()
    private val detector = RoadBoundaryDetector()
    private val temporal = RoadBoundaryTemporalTracker()
    private val presentationGate = RoadBoundaryPresentationGate()
    private var liveOverlay: RoadPathLiveOverlay? = null
    private var overlayEpoch = 0L
    private var preparationSerial = 0L
    internal fun overlay(): RoadPathLiveOverlay? = synchronized(lock) { liveOverlay }
    fun invalidateOverlay() = synchronized(lock) { liveOverlay = null; overlayEpoch++ }

    /** Explicit drive/clock lifecycle boundary. Re-delivered GNSS fixes are not a reset signal. */
    fun resetTrajectory() = synchronized(lock) {
        fixes.clear(); origin = null; locationEpoch++; liveOverlay = null; overlayEpoch++
    }

    fun recordLocation(time: Double, latitude: Double, longitude: Double, course: Double,
        speed: Double, accuracy: Double, courseAccuracy: Double) = synchronized(lock) {
        if (!listOf(time, latitude, longitude, course, speed, accuracy, courseAccuracy).all(Double::isFinite)) return@synchronized
        if (latitude !in -90.0..90.0 || longitude !in -180.0..180.0 || course !in 0.0..<360.0 ||
            speed < 0 || accuracy < 0 || courseAccuracy < 0) return@synchronized
        val latestTime = fixes.lastOrNull()?.time
        if (latestTime != null && time <= latestTime) {
            // GPS and fused providers can deliver the same fix, or an older one, serially.
            // Keep the first accepted trajectory immutable; neither arrival is new motion.
            if (time == latestTime) duplicateFixesDropped++ else outOfOrderFixesDropped++
            return@synchronized
        }
        val fix = Fix(time, latitude, longitude, course, speed, accuracy, courseAccuracy)
        if (origin == null) origin = fix
        fixes.addLast(fix)
        while (fixes.size > 32 || (fixes.firstOrNull()?.let { time - it.time > 8 } == true)) fixes.removeFirst()
    }

    fun evaluate(frame: RoadPathCameraFrame, diagnostic: TSRApplicabilityDiagnostic): String =
        evaluate(prepare(frame, diagnostic.batch.frameId, diagnostic.batch.scope), diagnostic)

    /** Runs on the admitted frame's worker before TSR; the guard makes context validation/publication atomic. */
    fun prepare(frame: RoadPathCameraFrame, frameId: String, scope: TSRApplicabilityScope,
        publishIfCurrent: (() -> Unit) -> Boolean = { publication -> publication(); true }): RoadPathPreparedFrame = synchronized(evaluationLock) {
        val location = synchronized(lock) { LocationSnapshot(fixes.toList(), origin, locationEpoch, overlayEpoch,
            duplicateFixesDropped, outOfOrderFixesDropped) }
        if (evaluatedLocationEpoch != location.epoch) {
            histories.clear(); evaluatedLocationEpoch = location.epoch; lastCapture = Double.NEGATIVE_INFINITY
            lastSourceTimestampSeconds = null
        }
        val key = "${scope.sessionId}:${scope.generation}:${scope.contextGeneration}:${scope.traversalEpoch}:${scope.bundleId}:${frame.geometryId}:${frame.calibration}"
        val sourceTimestamp = frame.sourceTimestampSeconds?.takeIf(Double::isFinite)
        val previousSourceTimestamp = lastSourceTimestampSeconds
        val sourceOrdering = sourceTimestamp != null && previousSourceTimestamp != null
        val orderingTime = if (sourceOrdering) requireNotNull(sourceTimestamp) else frame.capturedAtSeconds
        val previousOrderingTime = if (sourceOrdering) requireNotNull(previousSourceTimestamp) else lastCapture
        var skipReason: String? = null
        if (this.scope != key) { histories.clear(); this.scope = key }
        else if (orderingTime <= previousOrderingTime) {
            skipReason = if (orderingTime == previousOrderingTime) "duplicate_frame" else "out_of_order_frame"
        }
        if (skipReason == null) {
            lastCapture = frame.capturedAtSeconds
            lastSourceTimestampSeconds = sourceTimestamp
            preparationSerial++
        }
        val filterStart = nowNanos()
        val deadline = frame.startedAtNanos + 50_000_000L
        val filtered = if (skipReason == null) RoadPathLaneFilter.apply(frame.grayscale, frame.width, frame.height) {
            nowNanos() < deadline
        } else null
        val filteredAt = nowNanos()
        val uprightWidth = if(frame.rotationDegrees%180==0) frame.rawWidth else frame.rawHeight
        val uprightHeight = if(frame.rotationDegrees%180==0) frame.rawHeight else frame.rawWidth
        val visual = frame.visualCalibration?.takeIf { it.compatible(uprightWidth,uprightHeight,frame.orientationKey) }
        val temporalKey = "${scope.sessionId}:${scope.generation}:${frame.geometryId}:${frame.calibration}:${location.epoch}:${location.overlayEpoch}:visual:${visual?.revision}:orientation:${frame.orientationKey}:rawClock:${sourceTimestamp!=null}:known:${frame.clockKnown}"
        val motionHint = RoadBoundaryMotionHint.from(location.fixes.map { RoadBoundaryMotionSample(
            it.time,it.speed,it.course,it.accuracy,it.courseAccuracy) },frame.capturedAtSeconds,frame.clockKnown)
        var geometry: RoadBoundaryFrame
        if (skipReason != null || filtered == null) {
            if(skipReason==null) temporal.reset()
            geometry = RoadBoundaryFrame(emptyList(),emptyList(),frame.capturedAtSeconds,budgetExceeded=skipReason==null)
        } else {
            val prediction = temporal.predict(frame.grayscale,frame.width,frame.height,sourceTimestamp ?: frame.capturedAtSeconds,
                temporalKey,frame.capturedAtSeconds,motionHint=motionHint,shouldContinue={ nowNanos()<deadline })
            val guides = prediction.boundaries.map { it.points } + (visual?.let { listOf(
                listOf(LanePoint(it.leftTopX,it.horizonY),it.leftBottom),
                listOf(LanePoint(it.rightTopX,it.horizonY),it.rightBottom)) } ?: emptyList())
            val fresh = if(prediction.budgetExceeded) RoadBoundaryFrame(emptyList(),emptyList(),frame.capturedAtSeconds,budgetExceeded=true) else
                detector.detect(filtered,frame.width,frame.height,frame.capturedAtSeconds,
                    guidance=RoadBoundarySearchGuidance(visual?.horizonY,guides)) { nowNanos()<deadline }
            geometry = temporal.complete(prediction,fresh,frame.grayscale) { nowNanos()<deadline }
        }
        val presentation = when {
            skipReason != null -> RoadBoundaryPresentationSnapshot.rejected(skipReason,geometry.boundaries.size)
            geometry.budgetExceeded || !frame.clockKnown -> {
                presentationGate.reset()
                RoadBoundaryPresentationSnapshot.rejected(if(geometry.budgetExceeded) "geometry_budget" else "capture_clock_unknown",geometry.boundaries.size)
            }
            else -> presentationGate.update(geometry.boundaries,sourceTimestamp ?: frame.capturedAtSeconds,
                "$temporalKey:${frame.width}x${frame.height}") { nowNanos()<deadline }
        }
        val ready = nowNanos()
        val addedMs = (ready - frame.startedAtNanos).coerceAtLeast(0L) / 1e6
        if (skipReason == null && addedMs >= 50) {
            temporal.reset(); presentationGate.reset()
            geometry = RoadBoundaryFrame(emptyList(), emptyList(), frame.capturedAtSeconds,
                budgetExceeded = true, operationCount = geometry.operationCount)
        }
        var publicationAtSeconds = System.currentTimeMillis() / 1000.0
        var suppression = skipReason
        if (skipReason == null) {
            val current = publishIfCurrent {
                synchronized(lock) {
                    publicationAtSeconds = System.currentTimeMillis() / 1000.0
                    suppression = when {
                        locationEpoch != location.epoch -> "trajectory_reset"
                        overlayEpoch != location.overlayEpoch -> "overlay_invalidated"
                        addedMs >= 200 -> "added_processing_deadline"
                        geometry.budgetExceeded -> "geometry_budget"
                        !presentation.accepted -> presentation.reason ?: "presentation_rejected"
                        !frame.clockKnown -> "capture_clock_unknown"
                        else -> null
                    }
                    if (locationEpoch == location.epoch && overlayEpoch == location.overlayEpoch) {
                        liveOverlay = if (suppression != null) null else RoadPathLiveOverlay(presentation.visibleBoundaryIndices.map { geometry.boundaries[it] },
                            frame.capturedAtSeconds, LaneImageGeometry(frame.rawWidth, frame.rawHeight,
                                frame.rotationDegrees, frame.sensorToBuffer.toList()),presentation,scope.sessionId,frame.orientationKey,visual?.revision)
                    }
                }
            }
            if (!current) suppression = "context_invalidated"
            if (suppression != null) presentationGate.reset()
        }
        RoadPathPreparedFrame(this, frame.copy(grayscale = ByteArray(0), sensorToBuffer = frame.sensorToBuffer.toList()),
            frameId, scope, key, location, preparationSerial, geometry, presentation, motionHint, (filteredAt-filterStart)/1e6,
            (ready-filteredAt)/1e6, addedMs, ready, skipReason, publicationAtSeconds, suppression)
    }

    private fun presentationJson(p: RoadBoundaryPresentationSnapshot) = buildJsonObject {
        put("accepted",p.accepted); put("reason",p.reason); put("rawCount",p.rawCount)
        put("visibleCount",p.visibleBoundaryIndices.size); put("confirmedCount",p.confirmedCount)
        put("tentativeCount",p.tentativeCount); put("missingCount",p.missingCount); put("operationCount",p.operationCount)
        putJsonArray("visibleBoundaryIndices") { p.visibleBoundaryIndices.forEach { add(it) } }
        putJsonArray("items") { p.items.forEach { item -> add(buildJsonObject {
            put("trackId",item.trackId); put("boundaryIndex",item.boundaryIndex); put("state",item.state)
            put("observationCount",item.observationCount); put("firstObservedSeconds",item.firstObservedSeconds)
            put("lastObservedSeconds",item.lastObservedSeconds); put("missedExposures",item.missedExposures)
        }) } }
    }
    private fun motionHintJson(h: RoadBoundaryMotionHint) = buildJsonObject {
        put("used",h.used); put("reason",h.reason); put("sourceAgeSeconds",h.sourceAgeSeconds)
        put("speedMetersPerSecond",h.speedMetersPerSecond); put("courseAccuracyDegrees",h.courseAccuracyDegrees)
        put("pairIntervalSeconds",h.pairIntervalSeconds); put("headingDeltaDegrees",h.headingDeltaDegrees)
        put("headingRateDegreesPerSecond",h.headingRateDegreesPerSecond)
        put("horizontalSearchRadiusFloor",h.horizontalSearchRadiusFloor)
    }

    /** Consumes the exact prepared exposure after TSR. The intervening model time is not path processing. */
    fun evaluate(prepared: RoadPathPreparedFrame, diagnostic: TSRApplicabilityDiagnostic): String = synchronized(evaluationLock) {
        val frame = prepared.frame
        val batch = diagnostic.batch
        val location = prepared.location
        val sourceTimestamp = frame.sourceTimestampSeconds?.takeIf(Double::isFinite)
        fun skipped(reason: String) = buildJsonObject {
            put("schemaVersion", 1); put("mode", "shadow"); put("frameId", batch.frameId)
            put("capturedAtSeconds", frame.capturedAtSeconds); put("geometryId", frame.geometryId)
            sourceTimestamp?.let { put("sourceTimestampSeconds", it) }
            put("frameOrderingClock", if (sourceTimestamp != null) "source_exposure" else "capture_utc_fallback")
            put("deadlineExceeded", false); put("reason", reason); putJsonArray("associations") {}
        }.toString()
        if (prepared.owner !== this || prepared.frameId != batch.frameId || prepared.scope != batch.scope)
            return@synchronized skipped("prepared_frame_mismatch")
        prepared.skipReason?.let { return@synchronized skipped(it) }
        if (prepared.consumed || prepared.serial != preparationSerial) return@synchronized skipped("prepared_frame_already_consumed_or_superseded")
        prepared.consumed = true
        if (prepared.publicationSuppressionReason == "context_invalidated") return@synchronized skipped("context_invalidated")
        val invalidation = synchronized(lock) {
            when {
                locationEpoch != location.epoch -> "trajectory_reset"
                overlayEpoch != location.overlayEpoch -> "overlay_invalidated"
                else -> null
            }
        }
        if (invalidation != null) return@synchronized skipped(invalidation)
        val key = prepared.key
        val associationStart = nowNanos()
        fun elapsedMs() = prepared.preparationAddedMs + (nowNanos() - associationStart).coerceAtLeast(0L) / 1e6
        val deadline = associationStart + ((200 - prepared.preparationAddedMs).coerceAtLeast(0.0) * 1e6).toLong()
        val geometry = prepared.geometry
        val geometryMs = prepared.geometryMs
        val reference = location.origin
        val poses = if (reference == null) emptyList() else location.fixes.filter {
            it.time <= frame.capturedAtSeconds && frame.capturedAtSeconds - it.time <= 5
        }.map {
            val deltaLongitude = ((it.longitude - reference.longitude + 540) % 360) - 180
            RoadPathPose(key, it.time, Math.toRadians(deltaLongitude) * 6_371_000 * cos(Math.toRadians(reference.latitude)),
                Math.toRadians(it.latitude - reference.latitude) * 6_371_000,
                it.course, it.speed, it.accuracy, it.courseAccuracy)
        }
        val calibration = frame.calibration
        val pose = RoadPathEvidence.causalPoseAt(key, frame.capturedAtSeconds, poses)
        val projected = if (calibration == null || pose == null || !frame.clockKnown || geometry.budgetExceeded) emptyList() else
            geometry.corridors.mapIndexedNotNull { index, corridor ->
                val left = geometry.boundaries.getOrNull(corridor.leftBoundaryIndex) ?: return@mapIndexedNotNull null
                val right = geometry.boundaries.getOrNull(corridor.rightBoundaryIndex) ?: return@mapIndexedNotNull null
                fun reduced(points: List<LanePoint>) = if (points.size <= 16) points else List(16) { points[it * (points.size - 1) / 15] }
                val pixels = reduced(left.points) + reduced(right.points).asReversed()
                val polygon = pixels.mapNotNull {
                    RoadPathEvidence.projectGround(it.x, it.y, pose, calibration)
                }
                if (polygon.size != pixels.size) null else RoadPathCorridor(
                    "visual-$index", "unknown", polygon, corridor.confidence, true, 2.5)
            }
        val corridors = RoadPathEvidence.inferCorridorRoles(key, frame.capturedAtSeconds, poses, projected)
        val currentTracks = diagnostic.tracks.filter { it.visibility == "observed" && !it.associationAmbiguous }.take(24)
        histories.keys.retainAll(diagnostic.tracks.map { it.trackId }.toSet())
        val associations = mutableListOf<Pair<String, RoadPathResult>>()
        for (track in currentTracks) {
            if (nowNanos() >= deadline) break
            val sample = track.samples.lastOrNull()?.takeIf { it.frameId == batch.frameId } ?: continue
            val point = sample.candidate.box
            val observation = RoadPathObservation(track.trackId, key, calibration?.revision ?: "unavailable",
                frame.capturedAtSeconds, point.centerX, point.centerY)
            val history = ((histories[track.trackId].orEmpty().filter { frame.capturedAtSeconds - it.timeSeconds <= 2.5 }) + observation).takeLast(12)
            histories[track.trackId] = history
            val result = RoadPathEvidence.evaluate(key, frame.capturedAtSeconds, history, poses,
                calibration.takeIf { frame.clockKnown && !geometry.budgetExceeded }, corridors)
            associations += track.trackId to result
        }
        val exceeded = elapsedMs() > 200
        val encoded = buildJsonObject {
            put("schemaVersion", 1); put("mode", "shadow"); put("frameId", batch.frameId)
            put("capturedAtSeconds", frame.capturedAtSeconds); put("geometryId", frame.geometryId)
            sourceTimestamp?.let { put("sourceTimestampSeconds", it) }
            put("frameOrderingClock", if (sourceTimestamp != null) "source_exposure" else "capture_utc_fallback")
            put("imageWidth", if (frame.rotationDegrees % 180 == 0) frame.rawWidth else frame.rawHeight)
            put("imageHeight", if (frame.rotationDegrees % 180 == 0) frame.rawHeight else frame.rawWidth)
            put("captureClockKnown", frame.clockKnown); put("mountProfile", "test-bus-2026-09-29")
            put("cameraHeightMeters", 1.60); put("cameraLateralOffsetMeters", -0.08)
            put("calibrationAvailable", calibration != null); put("trajectorySamples", poses.size)
            put("visualCalibrationRevision",frame.visualCalibration?.revision)
            put("temporalOperationCount",geometry.temporalOperationCount)
            put("lanePresentation",presentationJson(prepared.presentation))
            put("laneMotionHint",motionHintJson(prepared.motionHint))
            geometry.temporalResetReason?.let { put("temporalResetReason",it) }
            putJsonObject("locationIngestion") {
                put("duplicateFixesDropped", location.duplicateFixesDropped)
                put("outOfOrderFixesDropped", location.outOfOrderFixesDropped)
                put("resetCount", location.epoch)
            }
            put("preprocessingMs", frame.preprocessingMs); put("geometryMs", geometryMs)
            put("laneFilter", RoadPathLaneFilter.ID); put("laneFilterMs", prepared.filterMs)
            put("preparationAddedMs", prepared.preparationAddedMs)
            put("preparationReadyNanos", prepared.preparationReadyNanos)
            put("preparationBeforeTSR", true); put("preparedGeometryReused", true)
            put("associationProcessingMs", (nowNanos() - associationStart).coerceAtLeast(0L) / 1e6)
            put("addedProcessingMs", elapsedMs()); put("deadlineExceeded", exceeded)
            put("geometryDeadlineExceeded", geometry.budgetExceeded)
            putJsonObject("imageMapping") { put("rawWidth", frame.rawWidth); put("rawHeight", frame.rawHeight)
                put("rotationDegrees", frame.rotationDegrees); putJsonArray("sensorToBuffer") { frame.sensorToBuffer.forEach { add(it) } } }
            put("analysisWidth", frame.width); put("analysisHeight", frame.height)
            put("sourceCallbackAtSeconds", batch.capturedAtMs / 1000.0)
            put("captureAgeAtEvaluationMs", System.currentTimeMillis() - frame.capturedAtSeconds * 1000)
            put("trajectoryReference", "local GNSS phone position used as approximate vehicle centre; mounting and road-plane uncertainty remain")
            put("associationTimeBasis", "exposure_relative_research_result")
            put("scope", key); put("rawCandidateCount", batch.rawCandidateCount); put("candidatesTruncated", batch.truncated)
            putJsonArray("trajectory") { poses.forEach { p -> add(buildJsonObject {
                put("timeSeconds", p.timeSeconds); put("eastMeters", p.eastMeters); put("northMeters", p.northMeters)
                put("courseDegrees", p.courseDegrees); put("speedMetersPerSecond", p.speedMetersPerSecond)
                put("horizontalAccuracyMeters", p.horizontalAccuracyMeters); put("courseAccuracyDegrees", p.courseAccuracyDegrees)
            }) } }
            if (reference != null) putJsonObject("localOrigin") { put("latitude", reference.latitude); put("longitude", reference.longitude) }
            if (calibration != null) putJsonObject("calibration") {
                put("revision", calibration.revision); put("verified", calibration.verified)
                put("fx", calibration.fx); put("fy", calibration.fy); put("cx", calibration.cx); put("cy", calibration.cy)
                put("yawDegrees", calibration.yawDegrees); put("pitchDegrees", calibration.pitchDegrees); put("rollDegrees", calibration.rollDegrees)
                put("heightMeters", calibration.heightMeters); put("lateralOffsetMeters", calibration.lateralOffsetMeters)
                put("provenance", "owner-supplied approximate bus mount; level camera assumption; camera metadata intrinsics")
            }
            putJsonArray("signBoxes") { currentTracks.forEach { t -> t.samples.lastOrNull()?.let { sample ->
                val b = sample.candidate.box
                add(buildJsonObject { put("trackId", t.trackId); put("candidateId", sample.candidate.candidateId)
                    put("semanticKey", sample.candidate.semanticKey); put("x", b.x); put("y", b.y); put("width", b.width); put("height", b.height) })
            } } }
            putJsonArray("boundaries") {
                geometry.boundaries.forEach { boundary ->
                    add(buildJsonObject {
                        put("confidence", boundary.confidence); put("cue", boundary.cue.toString().lowercase())
                        put("supportRows", boundary.supportRows)
                        put("provenance",boundary.provenance.toString().lowercase())
                        put("lastFreshTimestampSeconds",boundary.lastFreshTimestampSeconds)
                        put("evidenceAgeSeconds",boundary.evidenceAgeSeconds)
                        put("trackedAnchorCount",boundary.trackedAnchorCount)
                        putJsonArray("points") { boundary.points.forEach { p -> add(buildJsonArray { add(p.x); add(p.y) }) } }
                    })
                }
            }
            putJsonArray("corridors") { corridors.forEach { c -> add(buildJsonObject {
                put("id", c.id); put("role", c.role); put("confidence", c.confidence)
                putJsonArray("polygon") { c.polygon.forEach { p -> add(buildJsonArray { add(p.x); add(p.y) }) } }
                c.id.substringAfter("visual-").toIntOrNull()?.let { index -> geometry.corridors.getOrNull(index)?.let { h ->
                    putJsonArray("imagePolygon") { (geometry.boundaries[h.leftBoundaryIndex].points +
                        geometry.boundaries[h.rightBoundaryIndex].points.asReversed()).forEach { p -> add(buildJsonArray { add(p.x); add(p.y) }) } }
                } }
            }) } }
            putJsonArray("associations") { associations.forEach { (track, result) -> add(buildJsonObject {
                put("trackId", track); put("classification", if (exceeded) "unknown" else result.classification)
                put("reason", if (exceeded) "added_processing_deadline" else result.reason)
                put("supportingObservations", result.supportingObservations)
                put("shadowOnly", true)
                putJsonArray("observations") { histories[track].orEmpty().forEach { o -> add(buildJsonObject {
                    put("timeSeconds", o.timeSeconds); put("imageX", o.imageX); put("imageY", o.imageY)
                    put("calibrationRevision", o.calibrationRevision)
                }) } }
                result.eastMeters?.let { put("eastMeters", it) }; result.northMeters?.let { put("northMeters", it) }
                result.heightMeters?.let { put("heightMeters", it) }; result.baselineMeters?.let { put("baselineMeters", it) }
                result.parallaxDegrees?.let { put("parallaxDegrees", it) }
                result.uncertaintyEastMeters?.let { put("uncertaintyEastMeters", it) }; result.uncertaintyNorthMeters?.let { put("uncertaintyNorthMeters", it) }
                result.oldestPoseTimeSeconds?.let { put("oldestPoseTimeSeconds", it) }
                result.newestPoseTimeSeconds?.let { put("newestPoseTimeSeconds", it) }
                result.maximumPoseAgeSeconds?.let { put("maximumPoseAgeSeconds", it) }
                result.rangeMeters?.let { put("rangeMeters", it) }; result.residualMeters?.let { put("residualMeters", it) }
            }) } }
        }.toString()
        val totalMs = elapsedMs()
        val locationCurrent = synchronized(lock) {
            if (totalMs >= 200 && locationEpoch == location.epoch && overlayEpoch == location.overlayEpoch) liveOverlay = null
            locationEpoch == location.epoch
        }
        // Publication happened before TSR. Completion must never refresh the exposure's overlay TTL.
        val publicationDetails = buildJsonObject {
            put("overlayPublicationDecisionAtSeconds", prepared.publicationAtSeconds)
            put("overlayPublished", prepared.publicationSuppressionReason == null)
            prepared.publicationSuppressionReason?.let { put("overlayPublicationSuppressionReason", it) }
            if (prepared.publicationSuppressionReason == null) {
                put("overlayPublishedAtSeconds", prepared.publicationAtSeconds)
                put("captureToOverlayPublicationMs", (prepared.publicationAtSeconds - frame.capturedAtSeconds) * 1000)
            }
        }
        if (totalMs >= 200 || !locationCurrent) {
            histories.clear()
            temporal.reset(); presentationGate.reset()
            return@synchronized buildJsonObject { put("schemaVersion", 1); put("mode", "shadow"); put("frameId", batch.frameId)
                put("capturedAtSeconds", frame.capturedAtSeconds); put("geometryId", frame.geometryId)
                put("deadlineExceeded", totalMs >= 200); put("totalAddedProcessingMs", totalMs)
                put("reason", if (locationCurrent) "added_processing_deadline" else "trajectory_reset")
                publicationDetails.forEach { (key, value) -> put(key, value) }
                putJsonArray("associations") {} }.toString()
        }
        encoded.dropLast(1) + ",\"totalAddedProcessingMs\":" + totalMs + "," + publicationDetails.toString().drop(1)
    }
}
