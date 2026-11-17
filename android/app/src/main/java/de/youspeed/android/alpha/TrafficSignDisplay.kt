package de.youspeed.android.alpha

import java.time.Duration
import java.time.Instant
import java.util.Locale
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

internal object SecondarySignDisplayPolicy {
    enum class Presentation { HIDDEN, BRIEF, PERSISTENT }
    const val lifetimeMs = 3_000L

    fun presentation(classId: String, signCode: String? = null, country: String = "DE"): Presentation {
        val national = (signCode ?: classId).removePrefix("$country:")
        val base = national.substringBefore('-').substringBefore('[')
        if (classId.startsWith("arrow_") || classId.startsWith("city:") || classId.startsWith("city_limit:")) {
            return Presentation.HIDDEN
        }
        when (country) {
            "DE" -> {
                if (base in setOf("209", "211", "214", "222", "274", "274.1", "274.2", "278", "282", "310", "311")) {
                    return Presentation.HIDDEN
                }
                if (base in germanWarnings) return Presentation.PERSISTENT
            }
            "FR" -> {
                if (national.startsWith("B21") || base in setOf("EB10", "EB20", "B31", "B33", "B51", "B55")) {
                    return Presentation.HIDDEN
                }
                if (national in setOf("AB1", "AB2", "AB25") || frenchWarning.containsMatchIn(national)) return Presentation.PERSISTENT
            }
            "BE" -> {
                if (national.startsWith("D1") || national.startsWith("D3") || base in setOf("F1", "F3", "C45", "C46")) {
                    return Presentation.HIDDEN
                }
                if (belgianWarning.containsMatchIn(national)) return Presentation.PERSISTENT
            }
            "NL" -> {
                if (national.startsWith("C04") || national in setOf("D02", "D03", "D04", "D05", "D06", "D07", "A02", "A02-ZE", "F08", "H01", "H02")) {
                    return Presentation.HIDDEN
                }
                if (national.startsWith("J") || national in setOf("B03", "B04", "B05")) return Presentation.PERSISTENT
            }
            "CH" -> {
                if (national.toDoubleOrNull()?.let { it in 2.32..2.41 } == true ||
                    national in setOf("2.53", "2.58", "2.59.4b", "2.59.6a")) return Presentation.HIDDEN
                if (national.startsWith("1.") || national in setOf("3.05", "3.06")) return Presentation.PERSISTENT
            }
        }
        return Presentation.BRIEF
    }

    private val germanWarnings = setOf(
        "101", "102", "103", "105", "112", "114", "117", "120", "121", "123", "124", "125",
        "131", "136", "138", "142", "151", "301",
    )
    private val frenchWarning = Regex("^A(?:K)?[0-9]")
    private val belgianWarning = Regex("^A[0-9]")

    fun inventoryPresentation(sign: InventorySign): Presentation {
        if (sign.kind in setOf("speed_limit", "speed_limit_end", "settlement_boundary") ||
            sign.modelClasses.any { it.startsWith("city:") || it.startsWith("arrow_") }) return Presentation.HIDDEN
        return presentation(sign.code, country = sign.code.take(2))
    }
}

/** Continuous camera evidence keeps the original deadline, even when classes alternate. */
internal class SecondarySignDisplayWindow {
    private data class Window(val lastSeen: Long, val deadline: Long)
    private val windows = mutableMapOf<String, Window>()

    fun observe(classId: String, now: Long): Long {
        windows.entries.removeAll { now - it.value.lastSeen >= SecondarySignDisplayPolicy.lifetimeMs }
        val deadline = windows[classId]?.deadline ?: (now + SecondarySignDisplayPolicy.lifetimeMs)
        windows[classId] = Window(now, deadline)
        return deadline
    }
}

internal object InventorySpeedEndCode {
    private val numbered = Regex("^DE:278(?:-([0-9]{1,3})|\\[([0-9]{1,3})(?:\\s*km/h)?\\])$")
    fun number(code: String): Int? = numbered.matchEntire(code)?.groupValues?.drop(1)
        ?.firstOrNull { it.isNotEmpty() }?.toIntOrNull()?.takeIf { it > 0 }
}

/** A catalog pictogram is presentation only; it never represents a speed assertion. */
data class TrafficSignPictogram(
    val classId: String,
    val imagePath: String?,
    val labels: Map<String, String>,
    val speech: Map<String, String>? = null,
    val signCode: String? = null,
) {
    fun label(locale: Locale = Locale.getDefault()): String = labels[locale.language] ?: labels.getValue("en")

    /** Never read technical labels/class IDs, or another language's phrase aloud. */
    fun spokenText(locale: Locale = Locale.getDefault()): String? =
        speech?.get(locale.language.lowercase(Locale.ROOT))?.trim()?.takeIf { it.isNotEmpty() }
}

/** Country packs that are physically bundled in both mobile applications. */
internal object AndroidTrafficSignModelPackSelection {
    // CH v9 is owner-accepted for bundled use (shared/tsr/field-acceptance); signed registry rollout is separate.
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
    val country: String,
    val checkpointSha256: String,
    val classLabels: List<String>,
    private val pictograms: Map<String, TrafficSignPictogram>,
) {
    fun classId(index: Int): String = classLabels.getOrNull(index) ?: "classifier:$index"
    fun pictogram(classId: String): TrafficSignPictogram? = pictograms[classId].takeIf { classId in classLabels }

    fun endSign(action: TrafficSignAction, recognizedClassId: String?): TrafficSignPictogram? {
        pictograms[recognizedClassId]?.takeIf { it.imagePath != null }?.let { return it }
        val classId = when (action.kind) {
            TrafficSignActionKind.MAXIMUM_SPEED_END -> {
                if (country == "DE") {
                    pictograms["DE:278-${action.valueKmh}"]?.takeIf { it.imagePath != null }?.let { return it }
                    "DE:278"
                } else if (country == "FR") "B31" else "no:end"
            }
            TrafficSignActionKind.ALL_RESTRICTIONS_END -> if (country == "FR") "B31" else "no:end"
            TrafficSignActionKind.ZONE_END -> when {
                country == "FR" -> "B51"
                country == "DE" && action.valueKmh == null -> "zone:30:end"
                else -> "zone:${action.valueKmh}:end"
            }
            TrafficSignActionKind.PEDESTRIAN_ZONE_END -> if (country == "FR") "B55" else "zone:pedestrian:end"
            TrafficSignActionKind.MOTORWAY_EXIT -> if (country == "FR") "C208" else "motorway:end"
            TrafficSignActionKind.MOTORROAD_EXIT -> if (country == "FR") "C108" else "trunk:end"
            else -> return null
        }
        return pictograms[classId]?.takeIf { it.imagePath != null }
    }

    /** Bundle inventory can identify an exact sign independently of camera vocabulary. */
    fun inventorySpeedEnd(signCode: String, value: Double?, unit: String?, parameterStatus: String): TrafficSignPictogram? {
        if (signCode == "DE:278" && (value == null || parameterStatus != "parsed_source_value")) {
            return pictograms["DE:278"]?.takeIf { it.imagePath != null }
        }
        val sourceNumber = InventorySpeedEndCode.number(signCode)
        val exactCode = when {
            sourceNumber != null -> "DE:278-$sourceNumber"
            signCode == "DE:278" && parameterStatus == "parsed_source_value" && (unit == null || unit == "km/h") -> {
                val number = value?.takeIf { it.isFinite() } ?: return null
                val speed = number.toInt().takeIf { it.toDouble() == number } ?: return null
                "DE:278-$speed"
            }
            else -> return null
        }
        // Known numeric variants still require their exact reviewed artwork.
        return pictograms[exactCode]?.takeIf { it.imagePath != null }
    }

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
                if (!sign.getValue("display_eligible").jsonPrimitive.boolean) {
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
                    val speech = sign["speech"]?.let { metadata ->
                        (metadata as? kotlinx.serialization.json.JsonObject)?.mapNotNull { (language, value) ->
                            (value as? kotlinx.serialization.json.JsonPrimitive)?.takeIf { it.isString }
                                ?.contentOrNull?.trim()?.takeIf { it.isNotEmpty() }?.let { language to it }
                        }?.toMap()
                    }
                    val signCode = sign["sign_code"]?.jsonPrimitive?.contentOrNull
                    classId to TrafficSignPictogram(classId, imagePath, names, speech, signCode)
                }
            }.toMap()
            return TrafficSignDisplayCatalog(country, root.getValue("classifier_checkpoint_sha256").jsonPrimitive.content, labels, pictograms)
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
        TrafficSignSemanticKind.ALL_RESTRICTIONS_END,
        TrafficSignSemanticKind.PEDESTRIAN_ZONE_END,
        TrafficSignSemanticKind.MOTORWAY_EXIT,
        TrafficSignSemanticKind.MOTORROAD_EXIT,
    ),
    val capturedAtUtc: Instant? = null,
    val source: TrafficSignInputSource? = null,
    /** Same-frame primary feedback wins even while its durable delivery is pending. */
    val hasPrimaryFeedback: Boolean = false,
)

/** Runs on the main delivery lane, after asynchronous inference and context changes. */
internal class TrafficSignDisplayDeliveryGate {
    private var lastAcceptedAt: Instant? = null

    fun accept(observation: TrafficSignDisplayObservation, generation: Long, sessionId: String?): Boolean {
        if (observation.generation != generation || observation.driveSessionId != sessionId) return false
        val capturedAt = observation.capturedAtUtc ?: return false
        if (lastAcceptedAt?.let { capturedAt <= it } == true) return false
        lastAcceptedAt = capturedAt
        return true
    }

    fun reset() { lastAcceptedAt = null }
    fun invalidate(at: Instant) { if (lastAcceptedAt?.let { at > it } != false) lastAcceptedAt = at }
}

/** No queue: every attempt needs a fresh accepted frame and an idle speech lane. */
internal class SecondaryTrafficSignSpeechGate(
    private val absence: Duration = Duration.ofSeconds(8),
    private val spacing: Duration = Duration.ofSeconds(3),
    private val maximumAge: Duration = Duration.ofSeconds(2),
) {
    private val lastSeen = mutableMapOf<String, Instant>()
    private val emittedSinceGap = mutableSetOf<String>()
    private var newestObservation: Instant? = null
    private var lastEmission: Instant? = null

    fun consume(classId: String, observedAt: Instant, now: Instant, canSpeak: Boolean,
                emit: () -> Boolean): Boolean {
        val age = Duration.between(observedAt, now)
        if (age.isNegative || age > maximumAge || newestObservation?.let { observedAt <= it } == true) return false
        newestObservation = observedAt
        val previous = lastSeen.put(classId, observedAt)
        if (previous == null || Duration.between(previous, observedAt) >= absence) emittedSinceGap.remove(classId)
        // Busy frames still refresh lastSeen. Waiting never creates a deferred announcement.
        if (!canSpeak || classId in emittedSinceGap ||
            lastEmission?.let { Duration.between(it, now) < spacing } == true) return false
        if (!emit()) return false
        emittedSinceGap.add(classId)
        lastEmission = now
        return true
    }

    fun reset() {
        lastSeen.clear()
        emittedSinceGap.clear()
        newestObservation = null
        lastEmission = null
    }
}

/** Includes submitted-but-not-started speech and ignores callbacks from flushed utterances. */
internal class TrafficSignSpeechPlaybackState {
    private var activeUtteranceId: String? = null
    private var secondaryUtteranceId: String? = null
    private var supplementaryUtteranceId: String? = null
    var supplementarySpeechKey: String? = null
        private set
    val hasSupplementaryUtterance: Boolean
        get() = supplementaryUtteranceId != null && supplementaryUtteranceId == activeUtteranceId
    val hasSecondaryUtterance: Boolean
        get() = secondaryUtteranceId != null && secondaryUtteranceId == activeUtteranceId

    fun isIdle(engineSpeaking: Boolean): Boolean = activeUtteranceId == null && !engineSpeaking

    fun begin(utteranceId: String, secondary: Boolean, supplementaryKey: String? = null) {
        activeUtteranceId = utteranceId
        secondaryUtteranceId = utteranceId.takeIf { secondary }
        supplementaryUtteranceId = utteranceId.takeIf { secondary && supplementaryKey != null }
        supplementarySpeechKey = supplementaryKey.takeIf { secondary }
    }

    fun finish(utteranceId: String) {
        if (utteranceId == activeUtteranceId) activeUtteranceId = null
        if (utteranceId == secondaryUtteranceId) secondaryUtteranceId = null
        if (utteranceId == supplementaryUtteranceId) { supplementaryUtteranceId = null; supplementarySpeechKey = null }
    }

    fun reset() { activeUtteranceId = null; secondaryUtteranceId = null; supplementaryUtteranceId = null; supplementarySpeechKey = null }
}

internal object SecondaryTrafficSignSpeechPolicy {
    fun canSpeak(mode: TrafficSignFeedbackMode, displayEnabled: Boolean, runtimeEnabled: Boolean,
                 liveFrame: Boolean, speedKmh: Double, captureIdle: Boolean, speechIdle: Boolean,
                 primaryFeedbackPending: Boolean, visionDismissalIdle: Boolean = true): Boolean =
        mode == TrafficSignFeedbackMode.SPOKEN_SPEED_AND_SIGNS && displayEnabled && runtimeEnabled && liveFrame &&
            speedKmh.isFinite() && speedKmh >= 1.0 && captureIdle && speechIdle && !primaryFeedbackPending && visionDismissalIdle
}

internal object TrafficSignDisplayPolicy {
    const val MINIMUM_SCORE = 0.90

    fun accepted(detections: List<TrafficSignDetection>, preferSecondary: Boolean = false,
                 country: String = "DE"): TrafficSignCandidate? {
        val accepted = detections.map(TrafficSignDetection::candidate)
        .filter { candidate ->
            !candidate.rawClassId.startsWith("bad") && !candidate.rawClassId.startsWith("classifier:") &&
                (candidate.classifierRawScore ?: candidate.rawScore).let { it.isFinite() && it in MINIMUM_SCORE..1.0 } &&
                candidate.rawScore.isFinite() && candidate.rawScore in 0.25..1.0 &&
                (candidate.proposalRawScore?.let { it.isFinite() && it in 0.25..1.0 } != false)
        }
        val candidates = if (preferSecondary) accepted.filter {
            it.normalizedPrimarySemantic().kind == TrafficSignSemanticKind.UNKNOWN &&
                SecondarySignDisplayPolicy.presentation(it.rawClassId, country = country) != SecondarySignDisplayPolicy.Presentation.HIDDEN
        }.takeIf { it.isNotEmpty() } ?: accepted else accepted
        return candidates.maxWithOrNull(compareBy<TrafficSignCandidate> { it.classifierRawScore ?: it.rawScore }.thenBy { it.rawScore })
    }

    fun next(current: TrafficSignPictogram?, observation: TrafficSignDisplayObservation?, catalog: TrafficSignDisplayCatalog): TrafficSignPictogram? {
        val candidate = observation?.candidate ?: return current
        // Numeric/scope observations have their own speed lane. A committed typed
        // boundary explicitly invalidates the secondary lane after resolver admission.
        return when (candidate.normalizedPrimarySemantic().kind) {
            TrafficSignSemanticKind.UNKNOWN, TrafficSignSemanticKind.NON_SPEED_RESTRICTION_END ->
                catalog.pictogram(candidate.rawClassId)?.takeIf {
                    it.imagePath != null && SecondarySignDisplayPolicy.presentation(it.classId, it.signCode, catalog.country) !=
                        SecondarySignDisplayPolicy.Presentation.HIDDEN
                } ?: current
            else -> current
        }
    }
}

/** Explicit reference aliases do not add visual classes to a national model vocabulary. */
internal fun TrafficSignCandidate.normalizedPrimarySemantic(): TrafficSignSemantic {
    val token = rawClassId.trim().lowercase(Locale.ROOT)
    val numericEnd = Regex("^(?:de:)?278(?:-([0-9]{1,3}))?$").matchEntire(token)
    return when {
        Regex("^b33-[0-9]+$").matches(token) -> token.substringAfter('-').toIntOrNull()
            ?.takeIf(::isSharedTrafficSignSpeedKmh)
            ?.let { TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED_END, it) }
            ?: TrafficSignSemantic(TrafficSignSemanticKind.UNKNOWN)
        Regex("^maxspeed:[0-9]+:end$").matches(token) -> token.split(':')[1].toIntOrNull()
            ?.takeIf(::isSharedTrafficSignSpeedKmh)
            ?.let { TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED_END, it) }
            ?: TrafficSignSemantic(TrafficSignSemanticKind.UNKNOWN)
        token == "maxspeed:end" -> TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED_END)
        token == "zone:end" -> TrafficSignSemantic(TrafficSignSemanticKind.ZONE_END, semantic.value)
        token == "zone:30:end" -> TrafficSignSemantic(TrafficSignSemanticKind.ZONE_END, 30)
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
        token in setOf("282", "de:282", "no:end", "b31") -> TrafficSignSemantic(TrafficSignSemanticKind.ALL_RESTRICTIONS_END)
        token in setOf("motorway:end", "c208") -> TrafficSignSemantic(TrafficSignSemanticKind.MOTORWAY_EXIT)
        token in setOf("trunk:end", "c108") -> TrafficSignSemantic(TrafficSignSemanticKind.MOTORROAD_EXIT)
        else -> semantic
    }
}

/** Covers all publication paths, including route/city generation increments outside camera lifecycle methods. */
internal fun ConsumerUiState.withCurrentTrafficSignDisplayGeneration(previousGeneration: Long, currentGeneration: Long): ConsumerUiState =
    if (previousGeneration != currentGeneration || trafficSignGeneration != currentGeneration) {
        copy(trafficSignSupplementaryText = null, trafficSignPendingSpeedKmh = null, trafficSignGeneration = currentGeneration)
    } else this
