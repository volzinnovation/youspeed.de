package de.youspeed.android.alpha

import java.time.Instant
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

internal const val MIN_SHARED_TRAFFIC_SIGN_SPEED_KMH = 5
internal const val MAX_SHARED_TRAFFIC_SIGN_SPEED_KMH = 200

internal fun isSharedTrafficSignSpeedKmh(value: Int): Boolean =
    value in MIN_SHARED_TRAFFIC_SIGN_SPEED_KMH..MAX_SHARED_TRAFFIC_SIGN_SPEED_KMH

enum class TrafficSignPipeline(val wireValue: String) {
    DIRECT_DETECTION("direct_detection"),
    PROPOSAL_CLASSIFICATION("proposal_classification");

    companion object {
        fun fromWire(raw: String): TrafficSignPipeline = entries.firstOrNull { it.wireValue == raw }
            ?: error("Unsupported traffic-sign pipeline: $raw")
    }
}

enum class TrafficSignPlatform(val wireValue: String) {
    IOS("ios"),
    ANDROID("android"),
    REFERENCE("reference");

    companion object {
        fun fromWire(raw: String): TrafficSignPlatform = entries.firstOrNull { it.wireValue == raw }
            ?: error("Unsupported traffic-sign platform: $raw")
    }
}

enum class TrafficSignArtifactFormat(val wireValue: String) {
    CORE_ML("coreml"),
    TFLITE("tflite"),
    ONNX("onnx");

    companion object {
        fun fromWire(raw: String): TrafficSignArtifactFormat = entries.firstOrNull { it.wireValue == raw }
            ?: error("Unsupported traffic-sign artifact format: $raw")
    }
}

enum class TrafficSignPrecision(val wireValue: String) {
    FLOAT32("float32"),
    FLOAT16("float16"),
    INT8("int8"),
    UINT8("uint8");

    companion object {
        fun fromWire(raw: String): TrafficSignPrecision = entries.firstOrNull { it.wireValue == raw }
            ?: error("Unsupported traffic-sign precision: $raw")
    }
}

enum class TrafficSignColorSpace(val wireValue: String) {
    RGB("rgb"),
    BGR("bgr");

    companion object {
        fun fromWire(raw: String): TrafficSignColorSpace = entries.firstOrNull { it.wireValue == raw }
            ?: error("Unsupported traffic-sign color space: $raw")
    }
}

enum class TrafficSignResizeMode(val wireValue: String) {
    SCALE_FIT_LETTERBOX("scale_fit_letterbox"),
    SCALE_FILL("scale_fill");

    companion object {
        fun fromWire(raw: String): TrafficSignResizeMode = entries.firstOrNull { it.wireValue == raw }
            ?: error("Unsupported traffic-sign resize mode: $raw")
    }
}

enum class TrafficSignCalibrationKind(val wireValue: String) {
    NONE("none"),
    TEMPERATURE_SCALING("temperature_scaling"),
    ISOTONIC("isotonic"),
    PLATT("platt");

    companion object {
        fun fromWire(raw: String): TrafficSignCalibrationKind = entries.firstOrNull { it.wireValue == raw }
            ?: error("Unsupported traffic-sign calibration: $raw")
    }
}

enum class TrafficSignCalibrationOutput(val wireValue: String) {
    RAW_SCORE("raw_score"),
    CALIBRATED_CONFIDENCE("calibrated_confidence");

    companion object {
        fun fromWire(raw: String): TrafficSignCalibrationOutput = entries.firstOrNull { it.wireValue == raw }
            ?: error("Unsupported traffic-sign calibration output: $raw")
    }
}

enum class TrafficSignSemanticKind(val wireValue: String) {
    MAXIMUM_SPEED("maximum_speed"),
    MAXIMUM_SPEED_END("maximum_speed_end"),
    ZONE_START("zone_start"),
    ZONE_END("zone_end"),
    RESTRICTION_END("restriction_end"),
    ALL_RESTRICTIONS_END("all_restrictions_end"),
    CITY_ENTRY("city_entry"),
    CITY_EXIT("city_exit"),
    PEDESTRIAN_ZONE_START("pedestrian_zone_start"),
    PEDESTRIAN_ZONE_END("pedestrian_zone_end"),
    MOTORWAY_EXIT("motorway_exit"),
    MOTORROAD_EXIT("motorroad_exit"),
    NON_SPEED_RESTRICTION_END("non_speed_restriction_end"),
    TEMPORARY("temporary"),
    UNKNOWN("unknown");

    companion object {
        fun fromWire(raw: String): TrafficSignSemanticKind = entries.firstOrNull { it.wireValue == raw }
            ?: error("Unsupported traffic-sign semantic: $raw")
    }
}

enum class TrafficSignInputSource(val wireValue: String) {
    LIVE_FRAME("live_frame"),
    CAMERA_STILL("camera_still"),
    DIAGNOSTIC_IMPORT("diagnostic_import");

    companion object {
        fun fromWire(raw: String): TrafficSignInputSource = entries.firstOrNull { it.wireValue == raw }
            ?: error("Unsupported traffic-sign source: $raw")
    }
}

enum class TrafficSignRecognitionState(val wireValue: String) {
    NO_RECOGNITION("no_recognition"),
    PROVISIONAL("provisional"),
    CONFIRMED("confirmed"),
    UNKNOWN("unknown"),
    UNAVAILABLE("unavailable");

    companion object {
        fun fromWire(raw: String): TrafficSignRecognitionState = entries.firstOrNull { it.wireValue == raw }
            ?: error("Unsupported traffic-sign recognition state: $raw")
    }
}

/** Progress of supplementary-plate interpretation for one physical sign assembly. */
enum class TrafficSignConditionState(val wireValue: String) {
    NONE("none"),
    RESOLVING("resolving"),
    RESOLVED("resolved"),
    UNRESOLVED("unresolved");

    companion object {
        fun fromWire(raw: String?): TrafficSignConditionState {
            if (raw == null) return NONE
            return entries.firstOrNull { it.wireValue == raw }
                ?: error("Unsupported traffic-sign condition state: $raw")
        }
    }
}

/**
 * Typed condition carried by a whole sign assembly. Unknown future kinds remain
 * representable as [OTHER] while [rawKind] preserves the wire value.
 */
enum class TrafficSignRestrictionKind(val wireValue: String) {
    WEATHER("weather"),
    TIME_WINDOW("time_window"),
    DAYS_OF_WEEK("days_of_week"),
    VEHICLE("vehicle"),
    MAX_WEIGHT("max_weight"),
    SCHOOL("school"),
    RESIDENT("resident"),
    DISTANCE("distance"),
    EXCEPTION("exception"),
    DIRECTION("direction"),
    EXTENT("extent"),
    TEXT("text"),
    OTHER("other"),
    UNKNOWN("unknown");

    companion object {
        fun fromWire(raw: String): TrafficSignRestrictionKind = entries.firstOrNull { it.wireValue == raw } ?: OTHER
    }
}

enum class TrafficSignRole(val wireValue: String) {
    PRIMARY_SIGN("primary_sign"),
    SUPPLEMENTARY_PLATE("supplementary_plate");

    companion object {
        fun fromWire(raw: String): TrafficSignRole {
            return entries.firstOrNull { it.wireValue == raw }
                ?: error("Unsupported traffic-sign role: $raw")
        }
    }
}

data class TrafficSignRestriction(
    val kind: TrafficSignRestrictionKind,
    val rawKind: String = kind.wireValue,
    val normalizedValue: String,
    val rawText: String? = null,
    val countrySignCode: String? = null,
) {
    init {
        require(rawKind.isNotBlank()) { "Restriction kind must not be blank" }
        require(normalizedValue.isNotBlank()) { "Restriction value must not be blank" }
    }
}

data class TrafficSignPreprocessing(
    val version: String,
    val inputWidth: Int,
    val inputHeight: Int,
    val colorSpace: TrafficSignColorSpace,
    val resize: TrafficSignResizeMode,
    val orientation: String,
)

data class TrafficSignThresholds(
    val provisional: Double,
    val confirmed: Double,
    val unknown: Double,
    val confirmationFrames: Int,
    val confirmationWindowMs: Long,
    val minimumTrackIou: Double,
)

data class TrafficSignCalibration(
    val kind: TrafficSignCalibrationKind,
    val revision: String,
    val datasetSha256: String,
    val calibrated: Boolean,
    val runtimeOutput: TrafficSignCalibrationOutput,
)

data class TrafficSignSemantic(
    val kind: TrafficSignSemanticKind,
    val value: Int? = null,
    val unit: String? = null,
)

data class TrafficSignClassMapping(
    val classId: String,
    val label: String,
    val semantic: TrafficSignSemantic,
    val threshold: Double,
    val signRole: TrafficSignRole = TrafficSignRole.PRIMARY_SIGN,
    val restriction: TrafficSignRestriction? = null,
)

data class TrafficSignSourceCheckpoint(
    val uri: String,
    val revision: String,
    val sha256: String,
)

data class TrafficSignExporter(
    val name: String,
    val version: String,
    val configuration: String,
)

data class TrafficSignParity(
    val tolerance: Double,
    val measuredMaxAbsDifference: Double,
    val passed: Boolean,
)

data class TrafficSignArtifact(
    val platform: TrafficSignPlatform,
    val minimumRuntime: String,
    val format: TrafficSignArtifactFormat,
    val precision: TrafficSignPrecision,
    val inputShape: List<Int>,
    val outputSchema: String,
    val path: String,
    val sha256: String,
    val sourceCheckpointSha256: String,
    val exporter: TrafficSignExporter,
    val calibrationDatasetSha256: String,
    val parity: TrafficSignParity,
)

data class TrafficSignComponent(
    val componentId: String,
    val sourceCheckpoint: TrafficSignSourceCheckpoint,
    val artifacts: List<TrafficSignArtifact>,
)

data class TrafficSignLineage(
    val sourceManifestSha256: String,
    val datasetInventorySha256s: List<String>,
    val trainingRunId: String,
    val trainingRunSha256: String,
    val evaluationReportSha256: String,
    val parityReportSha256: String,
)

data class TrafficSignLicense(
    val name: String,
    val spdx: String,
    val source: String,
)

data class TrafficSignSignature(
    val algorithm: String,
    val keyId: String,
    val value: String,
)

data class TrafficSignModelPack(
    val schemaVersion: Int,
    val packId: String,
    val countries: List<String>,
    val pipeline: TrafficSignPipeline,
    val taxonomyVersion: String,
    val preprocessing: TrafficSignPreprocessing,
    val thresholds: TrafficSignThresholds,
    val calibration: TrafficSignCalibration,
    val classMapping: List<TrafficSignClassMapping>,
    val detector: TrafficSignComponent,
    val classifier: TrafficSignComponent?,
    val lineage: TrafficSignLineage,
    val licenses: List<TrafficSignLicense>,
    val minimumAppVersion: String,
    val signature: TrafficSignSignature?,
) {
    fun classFor(classId: String): TrafficSignClassMapping? = classMapping.firstOrNull { it.classId == classId }

    fun androidArtifact(component: TrafficSignComponent = detector): TrafficSignArtifact? =
        component.artifacts.firstOrNull { it.platform == TrafficSignPlatform.ANDROID }
}

data class NormalizedTrafficSignBoundingBox(
    val x: Double,
    val y: Double,
    val width: Double,
    val height: Double,
) {
    init {
        require(x.isFinite() && y.isFinite() && width.isFinite() && height.isFinite()) {
            "Normalized bounding-box coordinates must be finite"
        }
        require(x in 0.0..1.0 && y in 0.0..1.0) { "Normalized bounding-box origin is outside [0, 1]" }
        require(width > 0.0 && height > 0.0) { "Normalized bounding-box size must be positive" }
        require(x + width <= 1.0 + BOUNDS_EPSILON && y + height <= 1.0 + BOUNDS_EPSILON) {
            "Normalized bounding box extends outside the image"
        }
    }

    val area: Double
        get() = width * height

    fun intersectionOverUnion(other: NormalizedTrafficSignBoundingBox): Double {
        val intersectionLeft = maxOf(x, other.x)
        val intersectionTop = maxOf(y, other.y)
        val intersectionRight = minOf(x + width, other.x + other.width)
        val intersectionBottom = minOf(y + height, other.y + other.height)
        val intersectionWidth = (intersectionRight - intersectionLeft).coerceAtLeast(0.0)
        val intersectionHeight = (intersectionBottom - intersectionTop).coerceAtLeast(0.0)
        val intersectionArea = intersectionWidth * intersectionHeight
        if (intersectionArea == 0.0) return 0.0
        return intersectionArea / (area + other.area - intersectionArea)
    }

    private companion object {
        const val BOUNDS_EPSILON = 1e-9
    }
}

data class TrafficSignCandidate(
    val rawClassId: String,
    val rawLabel: String,
    val semantic: TrafficSignSemantic,
    val rawScore: Double,
    val calibratedConfidence: Double?,
    val boundingBox: NormalizedTrafficSignBoundingBox,
    val proposalRawScore: Double? = null,
    val proposalCalibratedConfidence: Double? = null,
    val classifierRawScore: Double? = null,
    val classifierCalibratedConfidence: Double? = null,
    val assemblyConfidence: Double? = null,
    val trackId: String? = null,
    val evidenceFrames: Int = 1,
    val assemblyId: String? = null,
    val conditionState: TrafficSignConditionState = TrafficSignConditionState.NONE,
    val restrictions: List<TrafficSignRestriction> = emptyList(),
)

data class TrafficSignRecognitionEvent(
    val schemaVersion: Int,
    val packId: String,
    val artifactSha256: String,
    val preprocessingVersion: String,
    val source: TrafficSignInputSource,
    val frameTimestampUtc: Instant,
    val state: TrafficSignRecognitionState,
    val candidate: TrafficSignCandidate?,
    val roadContext: TrafficSignDetectionContext? = null,
    val latencyMs: Double,
    val thermalState: String?,
    val frameId: String? = null,
    val driveSessionId: String? = null,
    val calibrationId: String? = null,
    val componentRole: String? = null,
    val modelComponents: List<TrafficSignModelComponentLineage> = emptyList(),
)

/** No Android inference backend is enabled by this foundation-only slice. */
sealed interface TrafficSignRuntimeState {
    data class Unavailable(val reason: String) : TrafficSignRuntimeState
}

object TrafficSignRuntimeFoundation {
    val state: TrafficSignRuntimeState = TrafficSignRuntimeState.Unavailable(
        reason = "No verified Android traffic-sign model artifact is installed",
    )
}

object TrafficSignModelPackJson {
    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    fun decode(raw: String): TrafficSignModelPack {
        val root = json.parseToJsonElement(raw).jsonObject
        val pack = TrafficSignModelPack(
            schemaVersion = root.tsrRequiredInt("schema_version"),
            packId = root.tsrRequiredString("pack_id"),
            countries = root.tsrRequiredArray("countries").map { it.jsonPrimitive.content },
            pipeline = TrafficSignPipeline.fromWire(root.tsrRequiredString("pipeline")),
            taxonomyVersion = root.tsrRequiredString("taxonomy_version"),
            preprocessing = root.tsrRequiredObject("preprocessing").toPreprocessing(),
            thresholds = root.tsrRequiredObject("thresholds").toThresholds(),
            calibration = root.tsrRequiredObject("calibration").toCalibration(),
            classMapping = root.tsrRequiredArray("class_mapping").map { it.jsonObject.toClassMapping() },
            detector = root.tsrRequiredObject("detector").toComponent(),
            classifier = root.tsrOptionalObject("classifier")?.toComponent(),
            lineage = root.tsrRequiredObject("lineage").toLineage(),
            licenses = root.tsrRequiredArray("licenses").map { it.jsonObject.toLicense() },
            minimumAppVersion = root.tsrRequiredString("minimum_app_version"),
            signature = root.tsrOptionalObject("signature")?.toSignature(),
        )
        TrafficSignModelPackValidator.requireValid(pack)
        return pack
    }

    private fun JsonObject.toPreprocessing() = TrafficSignPreprocessing(
        version = tsrRequiredString("version"),
        inputWidth = tsrRequiredInt("input_width"),
        inputHeight = tsrRequiredInt("input_height"),
        colorSpace = TrafficSignColorSpace.fromWire(tsrRequiredString("color_space")),
        resize = TrafficSignResizeMode.fromWire(tsrRequiredString("resize")),
        orientation = tsrRequiredString("orientation"),
    )

    private fun JsonObject.toThresholds() = TrafficSignThresholds(
        provisional = tsrRequiredDouble("provisional"),
        confirmed = tsrRequiredDouble("confirmed"),
        unknown = tsrRequiredDouble("unknown"),
        confirmationFrames = tsrRequiredInt("confirmation_frames"),
        confirmationWindowMs = tsrRequiredLong("confirmation_window_ms"),
        minimumTrackIou = tsrRequiredDouble("minimum_track_iou"),
    )

    private fun JsonObject.toCalibration() = TrafficSignCalibration(
        kind = TrafficSignCalibrationKind.fromWire(tsrRequiredString("kind")),
        revision = tsrRequiredString("revision"),
        datasetSha256 = tsrRequiredString("dataset_sha256"),
        calibrated = tsrRequiredBoolean("calibrated"),
        runtimeOutput = TrafficSignCalibrationOutput.fromWire(tsrRequiredString("runtime_output")),
    )

    private fun JsonObject.toClassMapping(): TrafficSignClassMapping {
        val semanticObject = tsrRequiredObject("semantic")
        return TrafficSignClassMapping(
            classId = tsrRequiredString("class_id"),
            label = tsrRequiredString("label"),
            semantic = TrafficSignSemantic(
                kind = TrafficSignSemanticKind.fromWire(semanticObject.tsrRequiredString("kind")),
                value = semanticObject.tsrOptionalInt("value"),
                unit = semanticObject.tsrOptionalString("unit"),
            ),
            threshold = tsrRequiredDouble("threshold"),
            signRole = if (containsKey("sign_role")) {
                TrafficSignRole.fromWire(tsrRequiredString("sign_role"))
            } else {
                TrafficSignRole.PRIMARY_SIGN
            },
            restriction = tsrOptionalObject("restriction")?.toRestriction(),
        )
    }

    private fun JsonObject.toRestriction(): TrafficSignRestriction {
        tsrRequireOnlyKeys(
            path = "class_mapping.restriction",
            allowed = setOf("kind", "normalized_value", "raw_text", "country_sign_code"),
        )
        val rawKind = tsrRequiredString("kind")
        return TrafficSignRestriction(
            kind = TrafficSignRestrictionKind.fromWire(rawKind),
            rawKind = rawKind,
            normalizedValue = tsrRequiredString("normalized_value"),
            rawText = if (containsKey("raw_text")) tsrRequiredString("raw_text") else null,
            countrySignCode = if (containsKey("country_sign_code")) tsrRequiredString("country_sign_code") else null,
        )
    }

    private fun JsonObject.toLineage(): TrafficSignLineage {
        tsrRequireOnlyKeys(
            path = "lineage",
            allowed = setOf(
                "source_manifest_sha256",
                "dataset_inventory_sha256s",
                "training_run_id",
                "training_run_sha256",
                "evaluation_report_sha256",
                "parity_report_sha256",
            ),
        )
        return TrafficSignLineage(
            sourceManifestSha256 = tsrRequiredString("source_manifest_sha256"),
            datasetInventorySha256s = tsrRequiredStringArray("dataset_inventory_sha256s"),
            trainingRunId = tsrRequiredString("training_run_id"),
            trainingRunSha256 = tsrRequiredString("training_run_sha256"),
            evaluationReportSha256 = tsrRequiredString("evaluation_report_sha256"),
            parityReportSha256 = tsrRequiredString("parity_report_sha256"),
        )
    }

    private fun JsonObject.toComponent(): TrafficSignComponent {
        val checkpoint = tsrRequiredObject("source_checkpoint")
        return TrafficSignComponent(
            componentId = tsrRequiredString("component_id"),
            sourceCheckpoint = TrafficSignSourceCheckpoint(
                uri = checkpoint.tsrRequiredString("uri"),
                revision = checkpoint.tsrRequiredString("revision"),
                sha256 = checkpoint.tsrRequiredString("sha256"),
            ),
            artifacts = tsrRequiredArray("artifacts").map { it.jsonObject.toArtifact() },
        )
    }

    private fun JsonObject.toArtifact(): TrafficSignArtifact {
        val exporterObject = tsrRequiredObject("exporter")
        val parityObject = tsrRequiredObject("parity")
        return TrafficSignArtifact(
            platform = TrafficSignPlatform.fromWire(tsrRequiredString("platform")),
            minimumRuntime = tsrRequiredString("minimum_runtime"),
            format = TrafficSignArtifactFormat.fromWire(tsrRequiredString("format")),
            precision = TrafficSignPrecision.fromWire(tsrRequiredString("precision")),
            inputShape = tsrRequiredArray("input_shape").map { it.jsonPrimitive.intOrNull ?: error("Invalid input_shape") },
            outputSchema = tsrRequiredString("output_schema"),
            path = tsrRequiredString("path"),
            sha256 = tsrRequiredString("sha256"),
            sourceCheckpointSha256 = tsrRequiredString("source_checkpoint_sha256"),
            exporter = TrafficSignExporter(
                name = exporterObject.tsrRequiredString("name"),
                version = exporterObject.tsrRequiredString("version"),
                configuration = exporterObject.tsrRequiredString("configuration"),
            ),
            calibrationDatasetSha256 = tsrRequiredString("calibration_dataset_sha256"),
            parity = TrafficSignParity(
                tolerance = parityObject.tsrRequiredDouble("tolerance"),
                measuredMaxAbsDifference = parityObject.tsrRequiredDouble("measured_max_abs_difference"),
                passed = parityObject.tsrRequiredBoolean("passed"),
            ),
        )
    }

    private fun JsonObject.toLicense() = TrafficSignLicense(
        name = tsrRequiredString("name"),
        spdx = tsrRequiredString("spdx"),
        source = tsrRequiredString("source"),
    )

    private fun JsonObject.toSignature() = TrafficSignSignature(
        algorithm = tsrRequiredString("algorithm"),
        keyId = tsrRequiredString("key_id"),
        value = tsrRequiredString("value"),
    )
}

object TrafficSignModelPackValidator {
    private val sha256Pattern = Regex("^[a-f0-9]{64}$")
    private val iso2Pattern = Regex("^[A-Z]{2}$")
    private val semanticVersionPattern = Regex("^[0-9]+\\.[0-9]+\\.[0-9]+$")

    fun validate(pack: TrafficSignModelPack): List<String> = buildList {
        if (pack.schemaVersion != 1) add("schema_version must be 1")
        if (pack.packId.isBlank()) add("pack_id is missing")
        if (pack.countries.isEmpty()) add("countries must not be empty")
        if (pack.countries.distinct().size != pack.countries.size) add("countries must be unique")
        pack.countries.filterNot { iso2Pattern.matches(it) }.forEach { add("country must be ISO 3166-1 alpha-2: $it") }
        if (pack.taxonomyVersion != "tsr-semantic-v1") add("unsupported taxonomy_version: ${pack.taxonomyVersion}")
        validatePreprocessing(pack.preprocessing, this)
        validateThresholds(pack.thresholds, this)
        validateCalibration(pack.calibration, this)
        if (pack.classMapping.isEmpty()) add("class_mapping must not be empty")
        if (pack.classMapping.map { it.classId }.distinct().size != pack.classMapping.size) add("class_id values must be unique")
        pack.classMapping.forEachIndexed { index, mapping -> validateClassMapping(mapping, "class_mapping[$index]", this) }
        validateComponent(pack.detector, "detector", pack.calibration.datasetSha256, this)
        when (pack.pipeline) {
            TrafficSignPipeline.DIRECT_DETECTION -> if (pack.classifier != null) {
                add("direct_detection must not declare a classifier")
            }
            TrafficSignPipeline.PROPOSAL_CLASSIFICATION -> if (pack.classifier == null) {
                add("proposal_classification requires a classifier")
            }
        }
        pack.classifier?.let { validateComponent(it, "classifier", pack.calibration.datasetSha256, this) }
        validateLineage(pack.lineage, this)
        if (pack.licenses.isEmpty()) add("licenses must not be empty")
        pack.licenses.forEachIndexed { index, license ->
            if (license.name.isBlank()) add("licenses[$index].name is missing")
            if (license.spdx.isBlank()) add("licenses[$index].spdx is missing")
            if (license.source.isBlank()) add("licenses[$index].source is missing")
        }
        if (!semanticVersionPattern.matches(pack.minimumAppVersion)) add("minimum_app_version is not semantic version x.y.z")
        pack.signature?.let { signature ->
            if (signature.algorithm != "ed25519") add("signature.algorithm must be ed25519")
            if (signature.keyId.isBlank()) add("signature.key_id is missing")
            if (signature.value.isBlank()) add("signature.value is missing")
        }
    }

    fun requireValid(pack: TrafficSignModelPack) {
        val errors = validate(pack)
        require(errors.isEmpty()) { "Invalid traffic-sign model pack: ${errors.joinToString("; ")}" }
    }

    private fun validatePreprocessing(value: TrafficSignPreprocessing, errors: MutableList<String>) {
        if (value.version.isBlank()) errors += "preprocessing.version is missing"
        if (value.inputWidth <= 0 || value.inputHeight <= 0) errors += "preprocessing input dimensions must be positive"
        if (value.orientation != "normalize_exif_and_mirroring") {
            errors += "preprocessing.orientation must normalize EXIF and mirroring"
        }
    }

    private fun validateThresholds(value: TrafficSignThresholds, errors: MutableList<String>) {
        fun unitInterval(raw: Double, name: String) {
            if (!raw.isFinite() || raw !in 0.0..1.0) errors += "$name must be in [0, 1]"
        }
        unitInterval(value.unknown, "thresholds.unknown")
        unitInterval(value.provisional, "thresholds.provisional")
        unitInterval(value.confirmed, "thresholds.confirmed")
        unitInterval(value.minimumTrackIou, "thresholds.minimum_track_iou")
        if (value.unknown > value.provisional || value.provisional > value.confirmed) {
            errors += "thresholds must satisfy unknown <= provisional <= confirmed"
        }
        if (value.confirmationFrames < 2) errors += "thresholds.confirmation_frames must be at least 2"
        if (value.confirmationWindowMs <= 0) errors += "thresholds.confirmation_window_ms must be positive"
    }

    private fun validateCalibration(value: TrafficSignCalibration, errors: MutableList<String>) {
        if (value.revision.isBlank()) errors += "calibration.revision is missing"
        if (!sha256Pattern.matches(value.datasetSha256)) errors += "calibration.dataset_sha256 is invalid"
        if (value.calibrated && value.kind == TrafficSignCalibrationKind.NONE) {
            errors += "calibrated packs require a calibration method"
        }
        if (value.calibrated && value.runtimeOutput != TrafficSignCalibrationOutput.CALIBRATED_CONFIDENCE) {
            errors += "calibrated packs must expose calibrated_confidence"
        }
        if (!value.calibrated && value.runtimeOutput != TrafficSignCalibrationOutput.RAW_SCORE) {
            errors += "uncalibrated packs must expose raw_score"
        }
    }

    private fun validateClassMapping(
        value: TrafficSignClassMapping,
        path: String,
        errors: MutableList<String>,
    ) {
        if (value.classId.isBlank()) errors += "$path.class_id is missing"
        if (value.label.isBlank()) errors += "$path.label is missing"
        if (!value.threshold.isFinite() || value.threshold !in 0.0..1.0) errors += "$path.threshold must be in [0, 1]"
        if (value.semantic.value != null && !isSharedTrafficSignSpeedKmh(value.semantic.value)) {
            errors += "$path semantic speed must be in $MIN_SHARED_TRAFFIC_SIGN_SPEED_KMH..$MAX_SHARED_TRAFFIC_SIGN_SPEED_KMH km/h"
        }
        if (value.semantic.kind == TrafficSignSemanticKind.MAXIMUM_SPEED) {
            if (value.semantic.value == null) errors += "$path maximum_speed requires a value"
            if (value.semantic.unit !in setOf("km/h", "mph")) errors += "$path maximum_speed requires km/h or mph"
        }
        when (value.signRole) {
            TrafficSignRole.PRIMARY_SIGN -> if (value.restriction != null) {
                errors += "$path primary_sign must not declare a restriction"
            }
            TrafficSignRole.SUPPLEMENTARY_PLATE -> {
                if (value.semantic.kind != TrafficSignSemanticKind.UNKNOWN ||
                    value.semantic.value != null ||
                    value.semantic.unit != null
                ) {
                    errors += "$path supplementary_plate must use an unknown semantic"
                }
                if (value.restriction == null) errors += "$path supplementary_plate requires a restriction"
            }
        }
        value.restriction?.let {
            validateRestriction(it, "$path.restriction", errors, requireNonEmptyMetadata = true)
        }
    }

    private fun validateLineage(value: TrafficSignLineage, errors: MutableList<String>) {
        if (!sha256Pattern.matches(value.sourceManifestSha256)) errors += "lineage.source_manifest_sha256 is invalid"
        if (value.datasetInventorySha256s.isEmpty()) errors += "lineage.dataset_inventory_sha256s is empty"
        if (value.datasetInventorySha256s.distinct().size != value.datasetInventorySha256s.size) {
            errors += "lineage.dataset_inventory_sha256s must be unique"
        }
        value.datasetInventorySha256s.filterNot(sha256Pattern::matches).forEach {
            errors += "lineage.dataset_inventory_sha256s contains an invalid hash"
        }
        if (value.trainingRunId.isBlank()) errors += "lineage.training_run_id is missing"
        if (!sha256Pattern.matches(value.trainingRunSha256)) errors += "lineage.training_run_sha256 is invalid"
        if (!sha256Pattern.matches(value.evaluationReportSha256)) errors += "lineage.evaluation_report_sha256 is invalid"
        if (!sha256Pattern.matches(value.parityReportSha256)) errors += "lineage.parity_report_sha256 is invalid"
    }

    private fun validateComponent(
        value: TrafficSignComponent,
        path: String,
        calibrationDatasetSha256: String,
        errors: MutableList<String>,
    ) {
        if (value.componentId.isBlank()) errors += "$path.component_id is missing"
        if (value.sourceCheckpoint.uri.isBlank()) errors += "$path.source_checkpoint.uri is missing"
        if (value.sourceCheckpoint.revision.isBlank()) errors += "$path.source_checkpoint.revision is missing"
        if (!sha256Pattern.matches(value.sourceCheckpoint.sha256)) errors += "$path.source_checkpoint.sha256 is invalid"
        if (value.artifacts.isEmpty()) errors += "$path.artifacts must not be empty"
        value.artifacts.forEachIndexed { index, artifact ->
            val artifactPath = "$path.artifacts[$index]"
            if (artifact.minimumRuntime.isBlank()) errors += "$artifactPath.minimum_runtime is missing"
            if (artifact.inputShape.size !in 3..4 || artifact.inputShape.any { it <= 0 }) {
                errors += "$artifactPath.input_shape must contain 3 or 4 positive dimensions"
            }
            if (artifact.outputSchema.isBlank()) errors += "$artifactPath.output_schema is missing"
            if (artifact.path.isBlank() || artifact.path.startsWith("/") || artifact.path.split('/').contains("..")) {
                errors += "$artifactPath.path must be a safe relative path"
            }
            if (!sha256Pattern.matches(artifact.sha256)) errors += "$artifactPath.sha256 is invalid"
            if (artifact.sourceCheckpointSha256 != value.sourceCheckpoint.sha256) {
                errors += "$artifactPath.source_checkpoint_sha256 does not match its component"
            }
            if (artifact.calibrationDatasetSha256 != calibrationDatasetSha256) {
                errors += "$artifactPath.calibration_dataset_sha256 does not match the pack"
            }
            if (artifact.exporter.name.isBlank() || artifact.exporter.version.isBlank() || artifact.exporter.configuration.isBlank()) {
                errors += "$artifactPath.exporter provenance is incomplete"
            }
            if (!artifact.parity.tolerance.isFinite() || artifact.parity.tolerance < 0.0) {
                errors += "$artifactPath.parity.tolerance is invalid"
            }
            if (!artifact.parity.measuredMaxAbsDifference.isFinite() || artifact.parity.measuredMaxAbsDifference < 0.0) {
                errors += "$artifactPath.parity.measured_max_abs_difference is invalid"
            }
            if (!artifact.parity.passed || artifact.parity.measuredMaxAbsDifference > artifact.parity.tolerance) {
                errors += "$artifactPath parity has not passed"
            }
        }
    }
}

private fun validateRestriction(
    value: TrafficSignRestriction,
    path: String,
    errors: MutableList<String>,
    requireNonEmptyMetadata: Boolean = false,
) {
    if (TrafficSignRestrictionKind.entries.none { it.wireValue == value.rawKind }) {
        errors += "$path.kind is unsupported: ${value.rawKind}"
    }
    if (value.normalizedValue.isBlank()) errors += "$path.normalized_value is missing"
    if (requireNonEmptyMetadata && value.rawText != null && value.rawText.isEmpty()) {
        errors += "$path.raw_text must not be empty"
    }
    if (requireNonEmptyMetadata && value.countrySignCode != null && value.countrySignCode.isEmpty()) {
        errors += "$path.country_sign_code must not be empty"
    }
}

object TrafficSignRecognitionJson {
    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    fun decode(raw: String): TrafficSignRecognitionEvent = decodeObject(json.parseToJsonElement(raw).jsonObject)

    fun decodeList(raw: String): List<TrafficSignRecognitionEvent> =
        json.parseToJsonElement(raw).jsonArray.map { decodeObject(it.jsonObject) }

    fun validate(event: TrafficSignRecognitionEvent, pack: TrafficSignModelPack? = null): List<String> = buildList {
        if (event.schemaVersion != 1) add("schema_version must be 1")
        if (event.packId.isBlank()) add("pack_id is missing")
        if (!event.artifactSha256.matches(Regex("^[a-f0-9]{64}$"))) add("artifact_sha256 is invalid")
        if (event.preprocessingVersion.isBlank()) add("preprocessing_version is missing")
        if (!event.latencyMs.isFinite() || event.latencyMs < 0.0) add("latency_ms is invalid")
        if (event.state in setOf(
                TrafficSignRecognitionState.PROVISIONAL,
                TrafficSignRecognitionState.CONFIRMED,
                TrafficSignRecognitionState.UNKNOWN,
            ) && event.candidate == null
        ) {
            add("${event.state.wireValue} requires a candidate")
        }
        if (event.source == TrafficSignInputSource.LIVE_FRAME &&
            event.state in setOf(TrafficSignRecognitionState.PROVISIONAL, TrafficSignRecognitionState.CONFIRMED) &&
            event.roadContext == null
        ) {
            add("live ${event.state.wireValue} requires frame-time road_context")
        }
        if (event.state in setOf(TrafficSignRecognitionState.NO_RECOGNITION, TrafficSignRecognitionState.UNAVAILABLE) && event.candidate != null) {
            add("${event.state.wireValue} must not include a candidate")
        }
        event.candidate?.let { candidate ->
            if (candidate.rawClassId.isBlank()) add("candidate.raw_class_id is missing")
            if (candidate.rawLabel.isBlank()) add("candidate.raw_label is missing")
            if (!candidate.rawScore.isFinite()) add("candidate.raw_score is invalid")
            if (candidate.calibratedConfidence != null &&
                (!candidate.calibratedConfidence.isFinite() || candidate.calibratedConfidence !in 0.0..1.0)
            ) {
                add("candidate.calibrated_confidence must be in [0, 1]")
            }
            listOf(
                "proposal_raw_score" to candidate.proposalRawScore,
                "proposal_calibrated_confidence" to candidate.proposalCalibratedConfidence,
                "classifier_raw_score" to candidate.classifierRawScore,
                "classifier_calibrated_confidence" to candidate.classifierCalibratedConfidence,
                "assembly_confidence" to candidate.assemblyConfidence,
            ).forEach { (name, score) ->
                if (score != null && (!score.isFinite() || score !in 0.0..1.0)) {
                    add("candidate.$name must be in [0, 1]")
                }
            }
            if (candidate.evidenceFrames < 1) add("candidate.evidence_frames must be positive")
            if (candidate.semantic.value != null && !isSharedTrafficSignSpeedKmh(candidate.semantic.value)) {
                add("semantic speed must be in $MIN_SHARED_TRAFFIC_SIGN_SPEED_KMH..$MAX_SHARED_TRAFFIC_SIGN_SPEED_KMH km/h")
            }
            if (candidate.semantic.kind == TrafficSignSemanticKind.MAXIMUM_SPEED) {
                if (candidate.semantic.value == null) add("maximum_speed requires a value")
                if (candidate.semantic.unit !in setOf("km/h", "mph")) add("maximum_speed requires km/h or mph")
            }
            if (candidate.assemblyId != null && candidate.assemblyId.isBlank()) add("candidate.assembly_id must not be blank")
            candidate.restrictions.forEachIndexed { index, restriction ->
                validateRestriction(restriction, "candidate.restrictions[$index]", this)
            }
        }
        pack?.let { modelPack ->
            if (event.packId != modelPack.packId) add("event pack_id does not match model pack")
            if (event.preprocessingVersion != modelPack.preprocessing.version) add("event preprocessing_version does not match model pack")
            val artifactHashes = buildList {
                addAll(modelPack.detector.artifacts.map { it.sha256 })
                addAll(modelPack.classifier?.artifacts.orEmpty().map { it.sha256 })
            }
            if (event.artifactSha256 !in artifactHashes) add("event artifact is not declared by model pack")
            if (!modelPack.calibration.calibrated && event.candidate?.calibratedConfidence != null) {
                add("uncalibrated model pack must not emit calibrated_confidence")
            }
            if (modelPack.calibration.calibrated &&
                event.candidate != null &&
                event.candidate.calibratedConfidence == null
            ) {
                add("calibrated model pack must emit calibrated_confidence")
            }
        }
    }

    private fun decodeObject(root: JsonObject): TrafficSignRecognitionEvent {
        val event = TrafficSignRecognitionEvent(
            schemaVersion = root.tsrRequiredInt("schema_version"),
            packId = root.tsrRequiredString("pack_id"),
            artifactSha256 = root.tsrRequiredString("artifact_sha256"),
            preprocessingVersion = root.tsrRequiredString("preprocessing_version"),
            source = TrafficSignInputSource.fromWire(root.tsrRequiredString("source")),
            frameTimestampUtc = Instant.parse(root.tsrRequiredString("frame_timestamp_utc")),
            state = TrafficSignRecognitionState.fromWire(root.tsrRequiredString("state")),
            candidate = root.tsrOptionalObject("candidate")?.toCandidate(),
            roadContext = root.tsrRequiredNullableObject("road_context")?.toRoadContext(),
            latencyMs = root.tsrRequiredDouble("latency_ms"),
            thermalState = root.tsrOptionalString("thermal_state"),
        )
        val errors = validate(event)
        require(errors.isEmpty()) { "Invalid traffic-sign recognition event: ${errors.joinToString("; ")}" }
        return event
    }

    private fun JsonObject.toCandidate(): TrafficSignCandidate {
        val box = tsrRequiredObject("bounding_box")
        return TrafficSignCandidate(
            rawClassId = tsrRequiredString("raw_class_id"),
            rawLabel = tsrRequiredString("raw_label"),
            semantic = TrafficSignSemantic(
                kind = TrafficSignSemanticKind.fromWire(tsrRequiredString("semantic_kind")),
                value = tsrOptionalInt("value"),
                unit = tsrOptionalString("unit"),
            ),
            rawScore = tsrRequiredDouble("raw_score"),
            calibratedConfidence = tsrOptionalDouble("calibrated_confidence"),
            boundingBox = NormalizedTrafficSignBoundingBox(
                x = box.tsrRequiredDouble("x"),
                y = box.tsrRequiredDouble("y"),
                width = box.tsrRequiredDouble("width"),
                height = box.tsrRequiredDouble("height"),
            ),
            proposalRawScore = tsrOptionalDouble("proposal_raw_score"),
            proposalCalibratedConfidence = tsrOptionalDouble("proposal_calibrated_confidence"),
            classifierRawScore = tsrOptionalDouble("classifier_raw_score"),
            classifierCalibratedConfidence = tsrOptionalDouble("classifier_calibrated_confidence"),
            assemblyConfidence = tsrOptionalDouble("assembly_confidence"),
            trackId = tsrOptionalString("track_id"),
            evidenceFrames = tsrRequiredInt("evidence_frames"),
            assemblyId = tsrRequiredNullableString("assembly_id"),
            conditionState = TrafficSignConditionState.fromWire(tsrRequiredString("condition_state")),
            restrictions = tsrRequiredArray("restrictions").map { it.jsonObject.toRestriction() },
        )
    }

    private fun JsonObject.toRestriction(): TrafficSignRestriction {
        val rawKind = tsrRequiredString("kind")
        return TrafficSignRestriction(
            kind = TrafficSignRestrictionKind.fromWire(rawKind),
            rawKind = rawKind,
            normalizedValue = tsrRequiredString("normalized_value"),
            rawText = tsrOptionalString("raw_text"),
            countrySignCode = tsrOptionalString("country_sign_code"),
        )
    }

    private fun JsonObject.toRoadContext(): TrafficSignDetectionContext {
        val signature = tsrRequiredObject("source_signature")
        return TrafficSignDetectionContext(
            wayId = tsrRequiredString("way_id"),
            latitude = tsrRequiredDouble("latitude"),
            longitude = tsrRequiredDouble("longitude"),
            headingDegrees = tsrRequiredDouble("heading_degrees"),
            travelDirection = TrafficSignTravelDirection.fromWire(tsrRequiredString("travel_direction")),
            sourceSignature = TrafficSignRuntimeSourceSignature(
                osmRevision = signature.tsrRequiredString("osm_revision"),
                localCorrectionRevision = signature.tsrRequiredNullableString("local_correction_revision"),
            ),
            bundleSha256 = tsrOptionalString("bundle_sha256")?.lowercase(),
        )
    }
}

private fun JsonObject.tsrRequiredArray(key: String): JsonArray =
    this[key]?.jsonArray ?: error("Missing array field: $key")

private fun JsonObject.tsrRequiredStringArray(key: String): List<String> =
    tsrRequiredArray(key).mapIndexed { index, element ->
        val primitive = element as? JsonPrimitive
            ?: error("Expected string field: $key[$index]")
        require(primitive.isString) { "Expected string field: $key[$index]" }
        primitive.content
    }

private fun JsonObject.tsrOptionalArray(key: String): JsonArray? = when (val element = this[key]) {
    null, JsonNull -> null
    is JsonArray -> element
    else -> error("Expected array field: $key")
}

private fun JsonObject.tsrRequiredObject(key: String): JsonObject =
    this[key]?.jsonObject ?: error("Missing object field: $key")

private fun JsonObject.tsrRequiredNullableObject(key: String): JsonObject? {
    if (!containsKey(key)) error("Missing object field: $key")
    return when (val element = this[key]) {
        JsonNull -> null
        is JsonObject -> element
        else -> error("Expected object field: $key")
    }
}

private fun JsonObject.tsrOptionalObject(key: String): JsonObject? = when (val element = this[key]) {
    null, JsonNull -> null
    is JsonObject -> element
    else -> error("Expected object field: $key")
}

private fun JsonObject.tsrRequiredString(key: String): String {
    val primitive = this[key] as? JsonPrimitive ?: error("Missing string field: $key")
    require(primitive.isString) { "Expected string field: $key" }
    return primitive.content
}

private fun JsonObject.tsrRequiredNullableString(key: String): String? {
    if (!containsKey(key)) error("Missing string field: $key")
    return when (val element = this[key]) {
        JsonNull -> null
        is JsonPrimitive -> {
            require(element.isString) { "Expected string field: $key" }
            element.content
        }
        else -> error("Expected string field: $key")
    }
}

private fun JsonObject.tsrRequireOnlyKeys(path: String, allowed: Set<String>) {
    val unexpected = keys - allowed
    require(unexpected.isEmpty()) {
        "$path contains unsupported fields: ${unexpected.sorted().joinToString()}"
    }
}

private fun JsonObject.tsrOptionalString(key: String): String? = when (val element = this[key]) {
    null, JsonNull -> null
    is JsonPrimitive -> {
        require(element.isString) { "Expected string field: $key" }
        element.content
    }
    else -> error("Expected string field: $key")
}

private fun JsonObject.tsrOptionalPrimitiveContent(key: String): String? = when (val element = this[key]) {
    null, JsonNull -> null
    is JsonPrimitive -> element.content
    else -> error("Expected primitive field: $key")
}

private fun JsonObject.tsrRequiredInt(key: String): Int =
    this[key]?.jsonPrimitive?.intOrNull ?: error("Missing integer field: $key")

private fun JsonObject.tsrOptionalInt(key: String): Int? = when (val element = this[key]) {
    null, JsonNull -> null
    is JsonPrimitive -> element.intOrNull ?: error("Expected integer field: $key")
    else -> error("Expected integer field: $key")
}

private fun JsonObject.tsrRequiredLong(key: String): Long =
    this[key]?.jsonPrimitive?.content?.toLongOrNull() ?: error("Missing long field: $key")

private fun JsonObject.tsrRequiredDouble(key: String): Double =
    this[key]?.jsonPrimitive?.doubleOrNull ?: error("Missing number field: $key")

private fun JsonObject.tsrOptionalDouble(key: String): Double? = when (val element = this[key]) {
    null, JsonNull -> null
    is JsonPrimitive -> element.doubleOrNull ?: error("Expected number field: $key")
    else -> error("Expected number field: $key")
}

private fun JsonObject.tsrRequiredBoolean(key: String): Boolean =
    this[key]?.jsonPrimitive?.booleanOrNull ?: error("Missing boolean field: $key")
