package de.youspeed.android.alpha

import java.time.Duration
import java.time.Instant
import kotlin.math.max
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

/** The durable lifecycle of a reviewed Panoramax contribution. */
enum class PanoramaxBatchState {
    CAPTURING,
    AWAITING_REVIEW,
    APPROVED,
    CREATING_UPLOAD_SET,
    UPLOADING,
    PROCESSING,
    COMPLETE,
    PARTIAL,
    BLOCKED,
}

enum class PanoramaxItemState {
    CAPTURED,
    INCLUDED,
    EXCLUDED,
    QUEUED,
    UPLOADING,
    UPLOADED,
    ACCEPTED,
    DUPLICATE,
    REJECTED,
    RETRYABLE_ERROR,
    PERMANENT_ERROR,
}

data class PanoramaxLocationSample(
    val latitude: Double,
    val longitude: Double,
    val capturedAt: Instant,
    val accuracyMeters: Double,
    val altitudeMeters: Double? = null,
    val headingDegrees: Double? = null,
)

data class PanoramaxSemanticTag(
    val key: String,
    val value: String,
)

data class PanoramaxTrafficSignAnnotation(
    val annotationId: String,
    val sourceEventId: String,
    val frameTimestampUtc: Instant,
    val shape: List<Int>,
    val semantics: List<PanoramaxSemanticTag>,
    val speedLimitKmh: Int,
    val physicalSignTrackId: String?,
    val detectionConfidence: Double,
    val classificationConfidence: Double,
    val wayId: String,
    val latitude: Double,
    val longitude: Double,
    val headingDegrees: Double,
    val travelDirection: TrafficSignTravelDirection,
) {
    fun isValid(): Boolean = annotationId.isNotBlank() && sourceEventId.isNotBlank() &&
        shape.size == 4 && shape[0] >= 0 && shape[1] >= 0 && shape[2] > shape[0] && shape[3] > shape[1] &&
        isSharedTrafficSignSpeedKmh(speedLimitKmh) && detectionConfidence.isFinite() &&
        detectionConfidence in 0.0..1.0 && classificationConfidence.isFinite() &&
        classificationConfidence in 0.0..1.0 && wayId.isNotBlank() && latitude.isFinite() &&
        latitude in -90.0..90.0 && longitude.isFinite() && longitude in -180.0..180.0 &&
        headingDegrees.isFinite() && headingDegrees >= 0.0 && headingDegrees < 360.0 &&
        semantics.any { it.key == "osm|traffic_sign" && it.value.isNotBlank() }
}

data class PanoramaxTrafficSignAnnotationDraft(
    val annotationId: String,
    val sourceEventId: String,
    val frameTimestampUtc: Instant,
    val normalizedShape: NormalizedTrafficSignBoundingBox,
    val semantics: List<PanoramaxSemanticTag>,
    val speedLimitKmh: Int,
    val physicalSignTrackId: String?,
    val detectionConfidence: Double,
    val classificationConfidence: Double,
    val context: TrafficSignDetectionContext,
) {
    fun projected(
        imageWidth: Int,
        imageHeight: Int,
        imageTimestamp: Instant,
        maximumTimeDelta: Duration = Duration.ofSeconds(5),
    ): PanoramaxTrafficSignAnnotation? {
        if (imageWidth <= 0 || imageHeight <= 0 ||
            Duration.between(frameTimestampUtc, imageTimestamp).abs() > maximumTimeDelta
        ) return null
        val minX = (normalizedShape.x * imageWidth).toInt().coerceIn(0, imageWidth - 1)
        val minY = (normalizedShape.y * imageHeight).toInt().coerceIn(0, imageHeight - 1)
        val maxX = kotlin.math.ceil((normalizedShape.x + normalizedShape.width) * imageWidth).toInt()
            .coerceIn(minX + 1, imageWidth)
        val maxY = kotlin.math.ceil((normalizedShape.y + normalizedShape.height) * imageHeight).toInt()
            .coerceIn(minY + 1, imageHeight)
        return PanoramaxTrafficSignAnnotation(
            annotationId = annotationId,
            sourceEventId = sourceEventId,
            frameTimestampUtc = frameTimestampUtc,
            shape = listOf(minX, minY, maxX, maxY),
            semantics = semantics,
            speedLimitKmh = speedLimitKmh,
            physicalSignTrackId = physicalSignTrackId,
            detectionConfidence = detectionConfidence.coerceIn(0.0, 1.0),
            classificationConfidence = classificationConfidence.coerceIn(0.0, 1.0),
            wayId = context.wayId ?: return null,
            latitude = context.latitude,
            longitude = context.longitude,
            headingDegrees = context.headingDegrees,
            travelDirection = context.travelDirection,
        ).takeIf(PanoramaxTrafficSignAnnotation::isValid)
    }

    companion object {
        fun from(event: TrafficSignRecognitionEvent): PanoramaxTrafficSignAnnotationDraft? {
            val candidate = event.candidate ?: return null
            val semanticKind = candidate.semantic.kind
            val speed = candidate.semantic.value
            val context = event.roadContext
            if (event.source != TrafficSignInputSource.LIVE_FRAME ||
                event.state != TrafficSignRecognitionState.CONFIRMED ||
                semanticKind !in setOf(TrafficSignSemanticKind.MAXIMUM_SPEED, TrafficSignSemanticKind.ZONE_START) ||
                speed == null || !isSharedTrafficSignSpeedKmh(speed) || context?.wayId.isNullOrBlank()
            ) return null
            val semanticValue = trafficSignValue(speed, semanticKind, event.packId)
            val qualifiedSemantic = "osm|traffic_sign=$semanticValue"
            val detectionConfidence = (candidate.proposalCalibratedConfidence
                ?: candidate.proposalRawScore
                ?: candidate.rawScore).coerceIn(0.0, 1.0)
            val classificationConfidence = (candidate.classifierCalibratedConfidence
                ?: candidate.classifierRawScore
                ?: candidate.calibratedConfidence
                ?: candidate.rawScore).coerceIn(0.0, 1.0)
            val sourceEventId = listOf(
                event.packId,
                event.frameTimestampUtc.toEpochMilli(),
                candidate.trackId ?: candidate.rawClassId,
            ).joinToString("-")
            val detectorModel = event.modelComponents.firstOrNull {
                it.role == "proposal_detector" || it.role == "direct_detector"
            }?.artifactSha256 ?: event.packId
            val classifierModel = event.modelComponents.firstOrNull {
                it.role == "semantic_classifier"
            }?.artifactSha256 ?: event.packId
            return PanoramaxTrafficSignAnnotationDraft(
                annotationId = "tsr-$sourceEventId",
                sourceEventId = sourceEventId,
                frameTimestampUtc = event.frameTimestampUtc,
                normalizedShape = candidate.boundingBox,
                semantics = listOf(
                    PanoramaxSemanticTag("osm|traffic_sign", semanticValue),
                    PanoramaxSemanticTag("detection_model[$qualifiedSemantic]", detectorModel),
                    PanoramaxSemanticTag("detection_confidence[$qualifiedSemantic]", "%.3f".format(java.util.Locale.ROOT, detectionConfidence)),
                    PanoramaxSemanticTag("classification_model[$qualifiedSemantic]", classifierModel),
                    PanoramaxSemanticTag("classification_confidence[$qualifiedSemantic]", "%.3f".format(java.util.Locale.ROOT, classificationConfidence)),
                ),
                speedLimitKmh = speed,
                physicalSignTrackId = candidate.trackId,
                detectionConfidence = detectionConfidence,
                classificationConfidence = classificationConfidence,
                context = requireNotNull(context),
            )
        }

        private fun trafficSignValue(
            speedLimitKmh: Int,
            semanticKind: TrafficSignSemanticKind,
            packId: String,
        ): String = if (packId.lowercase().startsWith("de-")) {
            if (semanticKind == TrafficSignSemanticKind.ZONE_START) {
                if (speedLimitKmh == 30) "DE:274.1" else "DE:274.1-$speedLimitKmh"
            } else {
                "DE:274-$speedLimitKmh"
            }
        } else if (semanticKind == TrafficSignSemanticKind.ZONE_START) {
            "maxspeed:zone_start:$speedLimitKmh"
        } else {
            "maxspeed:$speedLimitKmh"
        }
    }
}

object PanoramaxExifUserCommentCodec {
    const val PREFIX = "YouSpeed.PanoramaxAnnotations/1 "
    private val json = Json { explicitNulls = false }

    fun encode(annotations: List<PanoramaxTrafficSignAnnotation>): String? {
        if (annotations.isEmpty() || annotations.any { !it.isValid() }) return null
        return PREFIX + buildJsonObject {
            put("schemaVersion", 1)
            put("annotations", buildJsonArray { annotations.forEach { add(it.toJson()) } })
        }
    }

    fun decode(comment: String?): List<PanoramaxTrafficSignAnnotation>? = runCatching {
        if (comment == null || !comment.startsWith(PREFIX)) return null
        val envelope = json.parseToJsonElement(comment.removePrefix(PREFIX)).jsonObject
        if (envelope.getValue("schemaVersion").jsonPrimitive.int != 1) return null
        envelope.getValue("annotations").jsonArray
            .map { annotationFromJson(it.jsonObject) }
            .takeIf { annotations ->
                annotations.isNotEmpty() && annotations.all(PanoramaxTrafficSignAnnotation::isValid)
            }
    }.getOrNull()

    private fun PanoramaxTrafficSignAnnotation.toJson() = buildJsonObject {
        put("annotationID", annotationId)
        put("sourceEventID", sourceEventId)
        put("frameTimestampUTC", frameTimestampUtc.toString())
        put("shape", buildJsonArray { shape.forEach { add(JsonPrimitive(it)) } })
        put("semantics", buildJsonArray {
            semantics.forEach { tag ->
                add(buildJsonObject {
                    put("key", tag.key)
                    put("value", tag.value)
                })
            }
        })
        put("speedLimitKmh", speedLimitKmh)
        put("physicalSignTrackID", physicalSignTrackId?.let(::JsonPrimitive) ?: JsonNull)
        put("detectionConfidence", detectionConfidence)
        put("classificationConfidence", classificationConfidence)
        put("wayID", wayId)
        put("latitude", latitude)
        put("longitude", longitude)
        put("headingDegrees", headingDegrees)
        put("travelDirection", travelDirection.wireValue)
    }

    private fun annotationFromJson(value: JsonObject): PanoramaxTrafficSignAnnotation =
        PanoramaxTrafficSignAnnotation(
            annotationId = value.getValue("annotationID").jsonPrimitive.content,
            sourceEventId = value.getValue("sourceEventID").jsonPrimitive.content,
            frameTimestampUtc = Instant.parse(value.getValue("frameTimestampUTC").jsonPrimitive.content),
            shape = value.getValue("shape").jsonArray.map { it.jsonPrimitive.int },
            semantics = value.getValue("semantics").jsonArray.map { element ->
                element.jsonObject.let { tag ->
                    PanoramaxSemanticTag(
                        tag.getValue("key").jsonPrimitive.content,
                        tag.getValue("value").jsonPrimitive.content,
                    )
                }
            },
            speedLimitKmh = value.getValue("speedLimitKmh").jsonPrimitive.int,
            physicalSignTrackId = value["physicalSignTrackID"]
                ?.takeUnless { it is JsonNull }
                ?.jsonPrimitive
                ?.content
                ?.takeIf(String::isNotBlank),
            detectionConfidence = value.getValue("detectionConfidence").jsonPrimitive.double,
            classificationConfidence = value.getValue("classificationConfidence").jsonPrimitive.double,
            wayId = value.getValue("wayID").jsonPrimitive.content,
            latitude = value.getValue("latitude").jsonPrimitive.double,
            longitude = value.getValue("longitude").jsonPrimitive.double,
            headingDegrees = value.getValue("headingDegrees").jsonPrimitive.double,
            travelDirection = TrafficSignTravelDirection.fromWire(
                value.getValue("travelDirection").jsonPrimitive.content,
            ),
        )
}

data class PanoramaxCaptureMetadata(
    val captureId: String,
    val captureSessionId: String,
    val capturedAt: Instant,
    val location: PanoramaxLocationSample,
    val sha256: String,
    val byteSize: Long,
    val software: String,
    val imageWidthPixels: Int? = null,
    val imageHeightPixels: Int? = null,
    val trafficSignAnnotations: List<PanoramaxTrafficSignAnnotation>? = null,
) {
    fun validate(now: Instant = capturedAt): List<String> = buildList {
        if (captureId.isBlank()) add("captureId is missing")
        if (captureSessionId.isBlank()) add("captureSessionId is missing")
        if (capturedAt.isAfter(now.plusSeconds(60))) add("capture time is in the future")
        if (!location.latitude.isFinite() || location.latitude !in -90.0..90.0) add("latitude is invalid")
        if (!location.longitude.isFinite() || location.longitude !in -180.0..180.0) add("longitude is invalid")
        if (!location.accuracyMeters.isFinite() || location.accuracyMeters < 0.0) add("location accuracy is invalid")
        if (location.capturedAt.isAfter(now.plusSeconds(60))) add("location time is in the future")
        if (kotlin.math.abs(Duration.between(location.capturedAt, capturedAt).seconds) > 120) add("location is not associated with shutter time")
        if (location.headingDegrees != null && (!location.headingDegrees.isFinite() || location.headingDegrees !in 0.0..360.0)) add("heading is invalid")
        if (byteSize <= 0) add("image is empty")
        if (!sha256.matches(Regex("[0-9a-fA-F]{64}"))) add("sha256 is invalid")
        if (software.isBlank()) add("software provenance is missing")
        if (imageWidthPixels != null && imageWidthPixels <= 0) add("image width is invalid")
        if (imageHeightPixels != null && imageHeightPixels <= 0) add("image height is invalid")
        if ((imageWidthPixels == null) != (imageHeightPixels == null)) add("image dimensions are incomplete")
        if (trafficSignAnnotations?.all(PanoramaxTrafficSignAnnotation::isValid) == false) {
            add("traffic-sign annotation is invalid")
        }
    }
}

data class PanoramaxCadenceConfig(
    val distanceMeters: Double = 25.0,
    val fallbackInterval: Duration = Duration.ofSeconds(5),
    val maxLocationAge: Duration = Duration.ofSeconds(10),
    val maxAccuracyMeters: Double = 50.0,
) {
    init {
        require(distanceMeters > 0.0)
        require(!fallbackInterval.isNegative && !fallbackInterval.isZero)
        require(!maxLocationAge.isNegative && !maxLocationAge.isZero)
        require(maxAccuracyMeters > 0.0)
    }
}

/** Pure policy: cadence is independent from TSR frames or sign detections. */
object PanoramaxCapturePolicy {
    fun shouldCapture(
        lastCapture: PanoramaxLocationSample?,
        current: PanoramaxLocationSample,
        now: Instant = current.capturedAt,
        config: PanoramaxCadenceConfig = PanoramaxCadenceConfig(),
    ): Boolean {
        if (current.capturedAt.isAfter(now.plusSeconds(60))) return false
        if (Duration.between(current.capturedAt, now) > config.maxLocationAge) return false
        if (!current.accuracyMeters.isFinite() || current.accuracyMeters < 0.0 || current.accuracyMeters > config.maxAccuracyMeters) return false
        val previous = lastCapture ?: return true
        if (!current.capturedAt.isAfter(previous.capturedAt)) return false
        val distance = haversineMeters(previous.latitude, previous.longitude, current.latitude, current.longitude)
        val requiredMovement = max(
            config.distanceMeters,
            2.0 * max(current.accuracyMeters, previous.accuracyMeters),
        )
        // A time fallback is only useful while moving; it must not produce stationary duplicates.
        return distance >= requiredMovement ||
            (Duration.between(previous.capturedAt, current.capturedAt) >= config.fallbackInterval && distance >= requiredMovement)
    }

    private fun haversineMeters(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val earthRadius = 6_371_000.0
        val dLat = Math.toRadians(lat2 - lat1)
        val dLon = Math.toRadians(lon2 - lon1)
        val a = kotlin.math.sin(dLat / 2) * kotlin.math.sin(dLat / 2) +
            kotlin.math.cos(Math.toRadians(lat1)) * kotlin.math.cos(Math.toRadians(lat2)) *
            kotlin.math.sin(dLon / 2) * kotlin.math.sin(dLon / 2)
        return earthRadius * 2 * kotlin.math.atan2(kotlin.math.sqrt(a), kotlin.math.sqrt(1 - a))
    }
}
