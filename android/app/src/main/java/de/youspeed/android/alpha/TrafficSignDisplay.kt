package de.youspeed.android.alpha

import java.util.Locale
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** A catalog pictogram is presentation only; it never represents a speed assertion. */
data class TrafficSignPictogram(
    val classId: String,
    val imagePath: String?,
    val labels: Map<String, String>,
) {
    fun label(locale: Locale = Locale.getDefault()): String = labels[locale.language] ?: labels.getValue("en")
}

/** Country packs that are physically bundled in both mobile applications. */
internal object AndroidTrafficSignModelPackSelection {
    // CH is bundled for evaluation/shadow use; registry rollout remains gated.
    val bundledCountryCodes: Set<String> = setOf("DE", "FR", "NL", "BE", "CH")

    fun availableCountryCode(raw: String?): String? {
        val country = PenaltyCountryCodes.alpha2(raw) ?: return null
        return country.takeIf(bundledCountryCodes::contains)
    }

    fun assetRoot(raw: String?): String {
        val country = availableCountryCode(raw) ?: error("Unsupported bundled TSR country: $raw")
        return "tsr/$country.panoramax-bootstrap.tsrmodelpack"
    }
}

internal class TrafficSignDisplayCatalog private constructor(
    val checkpointSha256: String,
    val classLabels: List<String>,
    private val pictograms: Map<String, TrafficSignPictogram>,
) {
    fun classId(index: Int): String = classLabels.getOrNull(index) ?: "classifier:$index"
    fun pictogram(classId: String): TrafficSignPictogram? = pictograms[classId].takeIf { classId in classLabels }

    companion object {
        const val ASSET_PATH = "tsr/prolix-de-class-catalog-v1.json"

        fun assetPath(countryCode: String): String {
            val alpha2 = PenaltyCountryCodes.alpha2(countryCode)
                ?: error("Unsupported TSR catalog country: $countryCode")
            return "tsr/prolix-${alpha2.lowercase(Locale.ROOT)}-class-catalog-v1.json"
        }

        fun decode(raw: String, expectedCountryCode: String? = null): TrafficSignDisplayCatalog {
            val root = Json.parseToJsonElement(raw).jsonObject
            require(root.getValue("schema_version").jsonPrimitive.int == 1)
            val country = root.getValue("country").jsonPrimitive.content
            require(expectedCountryCode == null || PenaltyCountryCodes.alpha2(country) == PenaltyCountryCodes.alpha2(expectedCountryCode))
            val labels = root.getValue("class_labels").jsonArray.map { it.jsonPrimitive.content }
            require(labels.isNotEmpty() && labels.distinct().size == labels.size)
            val signs = root.getValue("signs").jsonArray.map { it.jsonObject }
            val pictograms = signs.mapNotNull { sign ->
                val classId = sign.getValue("class_id").jsonPrimitive.content
                val imagePath = sign["image_path"]?.jsonPrimitive?.contentOrNull
                if (!sign.getValue("display_eligible").jsonPrimitive.boolean || classId !in labels) {
                    null
                } else {
                    imagePath?.let { path ->
                        // National evaluation catalogs retain the shared
                        // sign-pictograms/national/<CC>/... resource path.
                        require(
                            path.startsWith("tsr/sign-pictograms/") &&
                                path.endsWith(".png") &&
                                !path.split('/').contains(".."),
                        )
                    }
                    val names = sign.getValue("label").jsonObject.mapValues { it.value.jsonPrimitive.content }
                    require(listOf("en", "de", "fr", "nl").all { !names[it].isNullOrBlank() })
                    classId to TrafficSignPictogram(classId, imagePath, names)
                }
            }.toMap()
            return TrafficSignDisplayCatalog(root.getValue("classifier_checkpoint_sha256").jsonPrimitive.content, labels, pictograms)
        }
    }
}

/** Non-null means an accepted new sign, including one that must clear the previous pictogram. */
data class TrafficSignDisplayObservation(
    val candidate: TrafficSignCandidate,
    val generation: Long,
    val driveSessionId: String,
    val applicabilityDecision: TSRApplicabilityDecision? = null,
    val isSpeedLimitEnd: Boolean = candidate.normalizedPrimarySemantic().kind in setOf(
        TrafficSignSemanticKind.MAXIMUM_SPEED_END,
        TrafficSignSemanticKind.ZONE_END,
    ),
)

internal object TrafficSignDisplayPolicy {
    const val MINIMUM_SCORE = 0.90

    fun accepted(detections: List<TrafficSignDetection>): TrafficSignCandidate? = detections
        .map(TrafficSignDetection::candidate)
        .filter { candidate ->
            !candidate.rawClassId.startsWith("bad") && !candidate.rawClassId.startsWith("classifier:") &&
                (candidate.classifierRawScore ?: candidate.rawScore).let { it.isFinite() && it in MINIMUM_SCORE..1.0 } &&
                candidate.rawScore.isFinite() && candidate.rawScore in 0.25..1.0 &&
                (candidate.proposalRawScore?.let { it.isFinite() && it in 0.25..1.0 } != false)
        }
        .maxWithOrNull(compareBy<TrafficSignCandidate> { it.classifierRawScore ?: it.rawScore }.thenBy { it.rawScore })

    fun next(current: TrafficSignPictogram?, observation: TrafficSignDisplayObservation?, catalog: TrafficSignDisplayCatalog): TrafficSignPictogram? {
        val candidate = observation?.candidate ?: return current
        // An accepted speed sign supersedes the previous other sign, but is shown only in the speed lane.
        return when (candidate.normalizedPrimarySemantic().kind) {
            TrafficSignSemanticKind.UNKNOWN, TrafficSignSemanticKind.NON_SPEED_RESTRICTION_END -> catalog.pictogram(candidate.rawClassId)
            else -> null
        }
    }
}

/** Explicit reference aliases do not add visual classes to a national model vocabulary. */
internal fun TrafficSignCandidate.normalizedPrimarySemantic(): TrafficSignSemantic {
    val token = rawClassId.trim().lowercase(Locale.ROOT)
    val numericEnd = Regex("^(?:de:)?278(?:-([0-9]{1,3}))?$").matchEntire(token)
    return when {
        token == "maxspeed:end" -> TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED_END)
        token in setOf("zone:end", "zone:30:end") -> TrafficSignSemantic(TrafficSignSemanticKind.ZONE_END)
        Regex("^(?:de:)?28[01](?:-[0-9]+)?$").matches(token) ||
            token in setOf("no_overtaking:end", "no_overtaking:end:hgv", "no_overtaking:hgv:end") -> TrafficSignSemantic(TrafficSignSemanticKind.NON_SPEED_RESTRICTION_END)
        numericEnd != null -> {
            val value = numericEnd.groupValues[1].toIntOrNull() ?: semantic.value
            if (value != null && !isSharedTrafficSignSpeedKmh(value)) TrafficSignSemantic(TrafficSignSemanticKind.UNKNOWN)
            else TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED_END, value)
        }
        (token.startsWith("de:278") || token.startsWith("278")) -> TrafficSignSemantic(TrafficSignSemanticKind.UNKNOWN)
        token in setOf("310", "de:310", "city:start", "city_limit:start") -> TrafficSignSemantic(TrafficSignSemanticKind.CITY_ENTRY)
        token in setOf("311", "de:311", "city:end", "city_limit:end") -> TrafficSignSemantic(TrafficSignSemanticKind.CITY_EXIT)
        token in setOf("282", "de:282", "no:end") -> TrafficSignSemantic(TrafficSignSemanticKind.ALL_RESTRICTIONS_END)
        token == "motorway:end" -> TrafficSignSemantic(TrafficSignSemanticKind.MOTORWAY_EXIT)
        token == "trunk:end" -> TrafficSignSemantic(TrafficSignSemanticKind.MOTORROAD_EXIT)
        else -> semantic
    }
}

/** Covers all publication paths, including route/city generation increments outside camera lifecycle methods. */
internal fun ConsumerUiState.withCurrentTrafficSignDisplayGeneration(previousGeneration: Long, currentGeneration: Long): ConsumerUiState =
    if (previousGeneration != currentGeneration || trafficSignGeneration != currentGeneration) {
        copy(lastTrafficSignPictogram = null, trafficSignGeneration = currentGeneration)
    } else this
