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
)
internal data class RoadPathLiveOverlay(val boundaries: List<RoadBoundaryEvidence>, val capturedAtSeconds: Double,
    val geometry: LaneImageGeometry)


class RoadPathSession(private val nowNanos: () -> Long = System::nanoTime) {
    private data class Fix(val time: Double, val latitude: Double, val longitude: Double,
        val course: Double, val speed: Double, val accuracy: Double, val courseAccuracy: Double)
    private data class LocationSnapshot(val fixes: List<Fix>, val origin: Fix?, val epoch: Long, val overlayEpoch: Long)
    private val lock = Any()
    private val evaluationLock = Any()
    private val fixes = ArrayDeque<Fix>()
    private var origin: Fix? = null
    private var locationEpoch = 0L
    // Only the serial evaluator owns association history; location callbacks never mutate it.
    private var evaluatedLocationEpoch = -1L
    private var scope: String? = null
    private var lastCapture = Double.NEGATIVE_INFINITY
    private val histories = linkedMapOf<String, List<RoadPathObservation>>()
    private val detector = RoadBoundaryDetector()
    private var liveOverlay: RoadPathLiveOverlay? = null
    private var overlayEpoch = 0L
    internal fun overlay(): RoadPathLiveOverlay? = synchronized(lock) { liveOverlay }
    fun invalidateOverlay() = synchronized(lock) { liveOverlay = null; overlayEpoch++ }

    fun recordLocation(time: Double, latitude: Double, longitude: Double, course: Double,
        speed: Double, accuracy: Double, courseAccuracy: Double) = synchronized(lock) {
        if (!listOf(time, latitude, longitude, course, speed, accuracy, courseAccuracy).all(Double::isFinite)) return@synchronized
        if (latitude !in -90.0..90.0 || longitude !in -180.0..180.0 || course !in 0.0..<360.0 ||
            speed < 0 || accuracy < 0 || courseAccuracy < 0) return@synchronized
        if (fixes.lastOrNull()?.let { time <= it.time } == true) {
            fixes.clear(); origin = null; locationEpoch++; liveOverlay = null
        }
        val fix = Fix(time, latitude, longitude, course, speed, accuracy, courseAccuracy)
        if (origin == null) origin = fix
        fixes.addLast(fix)
        while (fixes.size > 32 || (fixes.firstOrNull()?.let { time - it.time > 8 } == true)) fixes.removeFirst()
    }

    fun evaluate(frame: RoadPathCameraFrame, diagnostic: TSRApplicabilityDiagnostic): String = synchronized(evaluationLock) {
        // Camera work and JSON encoding must not hold the lock polled by the main-thread overlay
        // or by GNSS updates. Freeze one bounded, coherent location snapshot instead.
        val location = synchronized(lock) { LocationSnapshot(fixes.toList(), origin, locationEpoch, overlayEpoch) }
        if (evaluatedLocationEpoch != location.epoch) { histories.clear(); evaluatedLocationEpoch = location.epoch }
        val batch = diagnostic.batch
        val key = "${batch.scope.sessionId}:${batch.scope.generation}:${batch.scope.contextGeneration}:${batch.scope.traversalEpoch}:${batch.scope.bundleId}:${frame.geometryId}:${frame.calibration}"
        if (scope != key || frame.capturedAtSeconds <= lastCapture) { histories.clear(); scope = key }
        lastCapture = frame.capturedAtSeconds
        val start = frame.startedAtNanos
        fun elapsedMs() = (nowNanos() - start) / 1e6
        val deadline = start + 200_000_000L
        val geometryDeadline = start + 50_000_000L
        val geometry = detector.detect(frame.grayscale, frame.width, frame.height, frame.capturedAtSeconds) {
            nowNanos() < geometryDeadline
        }
        val geometryMs = elapsedMs() - frame.preprocessingMs
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
            put("imageWidth", if (frame.rotationDegrees % 180 == 0) frame.rawWidth else frame.rawHeight)
            put("imageHeight", if (frame.rotationDegrees % 180 == 0) frame.rawHeight else frame.rawWidth)
            put("captureClockKnown", frame.clockKnown); put("mountProfile", "test-bus-2026-09-29")
            put("cameraHeightMeters", 1.60); put("cameraLateralOffsetMeters", -0.08)
            put("calibrationAvailable", calibration != null); put("trajectorySamples", poses.size)
            put("preprocessingMs", frame.preprocessingMs); put("geometryMs", geometryMs)
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
            if (locationEpoch != location.epoch) false else {
                if (overlayEpoch == location.overlayEpoch) {
                    liveOverlay = if (totalMs >= 200 || geometry.budgetExceeded || !frame.clockKnown) null else
                        RoadPathLiveOverlay(geometry.boundaries, frame.capturedAtSeconds,
                            LaneImageGeometry(frame.rawWidth, frame.rawHeight, frame.rotationDegrees, frame.sensorToBuffer))
                }
                true
            }
        }
        if (totalMs >= 200 || !locationCurrent) {
            histories.clear()
            return@synchronized buildJsonObject { put("schemaVersion", 1); put("mode", "shadow"); put("frameId", batch.frameId)
                put("capturedAtSeconds", frame.capturedAtSeconds); put("geometryId", frame.geometryId)
                put("deadlineExceeded", totalMs >= 200); put("totalAddedProcessingMs", totalMs)
                put("reason", if (locationCurrent) "added_processing_deadline" else "trajectory_clock_discontinuity")
                putJsonArray("associations") {} }.toString()
        }
        encoded.dropLast(1) + ",\"totalAddedProcessingMs\":" + totalMs + "}"
    }
}
