package de.youspeed.android.alpha

import java.time.Duration
import java.time.Instant
import java.util.Locale
import kotlin.math.ceil
import kotlin.math.floor

/** Presentation evidence only. This value never enters the speed-reference policy. */
data class TrafficSignSupplementaryTimeWindow(val startMinutes: Int, val endMinutes: Int) {
    init { require(startMinutes in 0..1439 && endMinutes in 0..1439 && startMinutes != endMinutes) }
    private fun display(minutes: Int): String = if (minutes % 60 == 0) "${minutes / 60}"
        else String.format(Locale.ROOT, "%d:%02d", minutes / 60, minutes % 60)
    val displayText: String get() = "${display(startMinutes)}–${display(endMinutes)} h"

    fun spokenText(locale: Locale = Locale.getDefault()): String {
        fun time(minutes: Int, unit: String): String = "${minutes / 60} $unit" +
            if (minutes % 60 == 0) "" else " ${minutes % 60}"
        return when (locale.language.lowercase(Locale.ROOT)) {
            "de" -> "von ${time(startMinutes, "Uhr")} bis ${time(endMinutes, "Uhr")}"
            "fr" -> "de ${time(startMinutes, if (startMinutes / 60 == 1) "heure" else "heures")} à ${time(endMinutes, if (endMinutes / 60 == 1) "heure" else "heures")}"
            "nl" -> "van ${time(startMinutes, "uur")} tot ${time(endMinutes, "uur")}"
            "it" -> "dalle ${time(startMinutes, "ore")} alle ${time(endMinutes, "ore")}"
            "en" -> {
                fun english(minutes: Int): String {
                    val hour = (minutes / 60 % 12).let { if (it == 0) 12 else it }
                    val value = if (minutes % 60 == 0) "$hour" else String.format(Locale.ROOT, "%d:%02d", hour, minutes % 60)
                    return "$value ${if (minutes < 720) "a.m." else "p.m."}"
                }
                "from ${english(startMinutes)} to ${english(endMinutes)}"
            }
            else -> displayText
        }
    }

    companion object {
        private val expression = Regex("^\\s*([0-9]{1,2})(?::([0-9]{2}))?\\s*[-–—−]\\s*([0-9]{1,2})(?::([0-9]{2}))?\\s*(?:h|uhr)?\\s*$", RegexOption.IGNORE_CASE)
        fun parse(text: String): TrafficSignSupplementaryTimeWindow? {
            if (text.trim().length > 40) return null
            val match = expression.matchEntire(text) ?: return null
            fun minutes(hour: Int, minute: Int): Int? {
                val h = match.groupValues[hour].toIntOrNull() ?: return null
                val m = match.groupValues[minute].ifEmpty { "0" }.toIntOrNull() ?: return null
                return if (h in 0..23 && m in 0..59) h * 60 + m else null
            }
            val start = minutes(1, 2) ?: return null
            val end = minutes(3, 4) ?: return null
            return if (start == end) null else TrafficSignSupplementaryTimeWindow(start, end)
        }
    }
}

data class TrafficSignSupplementaryScope(val generation: Long, val driveSessionId: String)
enum class TrafficSignSupplementaryOCRPhase { NOT_REQUIRED, PENDING, COMPLETED }
enum class TrafficSignSupplementaryOCRStatus { READ, NO_TEXT, FAILED }

/** Raw OCR collection and presentation only. Parsed time is never evaluated for applicability. */
data class TrafficSignSupplementaryTextAnnotation(
    val primaryClassId: String,
    val primarySpeedKmh: Int?,
    val physicalSignId: String,
    val frameId: String,
    val observedAt: Instant,
    val firstSeenAt: Instant,
    val rawText: String?,
    val window: TrafficSignSupplementaryTimeWindow?,
    val status: TrafficSignSupplementaryOCRStatus,
    val primaryBoundingBox: NormalizedTrafficSignBoundingBox,
    val engine: String = "mlkit-latin",
    val modelVersion: String = "16.0.1",
    val sourceObservedAt: Instant = observedAt,
    val ocrBoundingBox: NormalizedTrafficSignBoundingBox? = null,
    val generation: Long = 0,
    val driveSessionId: String = "",
    val qualityDecision: String = "legacy",
    internal val ocrPasses: List<TrafficSignOCRPass> = emptyList(),
    val assemblyEvidence: TrafficSignConditionalAssemblyEvidence? = null,
) {
    val text: String get() {
        if (status != TrafficSignSupplementaryOCRStatus.READ) return ""
        val value = window?.displayText ?: TrafficSignOCRTextFormatting.display(rawText.orEmpty()).map { if (it.isISOControl() || it.isWhitespace()) ' ' else it }
            .joinToString("").trim().split(' ').filter { it.isNotEmpty() }.joinToString(" ")
        return if (value.length <= 160) value else value.take(157) + "…"
    }
    val hasText: Boolean get() = status == TrafficSignSupplementaryOCRStatus.READ && text.isNotBlank()
    val speechKey: String get() = "$primaryClassId:${text.lowercase(Locale.ROOT)}"
    val presentationKey: String get() = "$physicalSignId:$speechKey"
    fun isFresh(now: Instant): Boolean = Duration.between(observedAt, now).let { !it.isNegative && it <= Duration.ofSeconds(3) }
    fun matchesNumeric(speedKmh: Int?, cameraEvidence: Boolean): Boolean = hasText && cameraEvidence && (primarySpeedKmh ?: 0) > 0 && primarySpeedKmh == speedKmh
    fun matchesPictogram(classId: String?): Boolean = hasText && primarySpeedKmh == null && primaryClassId == classId
    fun spokenText(locale: Locale = Locale.getDefault()): String = window?.spokenText(locale) ?: TrafficSignOCRTextFormatting.speech(text, locale)
}

typealias TrafficSignSupplementaryTextObservation = TrafficSignSupplementaryTextAnnotation

/** Display memory never refreshes the OCR evidence used for speech, captures, or authority. */
internal object TrafficSignSupplementaryDisplayPolicy {
    fun retained(current: TrafficSignSupplementaryTextAnnotation?, primaryClassId: String?,
        read: TrafficSignSupplementaryTextAnnotation? = null, now: Instant): TrafficSignSupplementaryTextAnnotation? {
        if (read != null && read.hasText && read.isFresh(now) &&
            (primaryClassId == null || read.primaryClassId == primaryClassId)) return read
        return current?.takeIf { primaryClassId == null || primaryClassId == it.primaryClassId }
    }
}

internal data class TrafficSignSupplementaryTextUpdate(
    val scope: TrafficSignSupplementaryScope,
    val observation: TrafficSignSupplementaryTextAnnotation?,
    val primaryPresent: Boolean,
)

data class TrafficSignSupplementaryOCRRequest(
    val candidate: TrafficSignCandidate,
    val physicalSignId: String,
    val frameId: String,
    val observedAt: Instant,
    val firstSeenAt: Instant,
    val scope: TrafficSignSupplementaryScope,
    val attemptNumber: Int = 1,
    val otherPrimaryBoxes: List<NormalizedTrafficSignBoundingBox> = emptyList(),
) {
    fun annotation(rawText: String?, failed: Boolean = false,
        ocrBox: NormalizedTrafficSignBoundingBox? = null, admitted: Boolean = true,
        decision: String = "legacy", passes: List<TrafficSignOCRPass> = emptyList(),
        assemblyEvidence:TrafficSignConditionalAssemblyEvidence?=null): TrafficSignSupplementaryTextAnnotation {
        val raw = rawText?.trim()?.takeIf { it.isNotEmpty() }
        return TrafficSignSupplementaryTextAnnotation(candidate.rawClassId, candidate.numericSupplementarySpeed(),
            physicalSignId, frameId, observedAt, firstSeenAt, raw, raw?.takeIf { admitted && !failed }?.let(TrafficSignSupplementaryTimeWindow::parse),
            when { failed -> TrafficSignSupplementaryOCRStatus.FAILED; raw == null || !admitted -> TrafficSignSupplementaryOCRStatus.NO_TEXT; else -> TrafficSignSupplementaryOCRStatus.READ },
            candidate.boundingBox, ocrBoundingBox = ocrBox, generation = scope.generation, driveSessionId = scope.driveSessionId,
            modelVersion = "16.0.1-${TrafficSignPlateDetector.revision}", qualityDecision = decision, ocrPasses = passes, assemblyEvidence=assemblyEvidence)
    }
}

fun interface TrafficSignSupplementaryTextRecognition {
    /** Called after primary qualification and bounded pixel-quality admission. Copy pixels before returning. */
    fun recognize(request: TrafficSignSupplementaryOCRRequest, completion: (TrafficSignSupplementaryTextAnnotation) -> Unit)
}

internal fun TrafficSignCandidate.numericSupplementarySpeed(): Int? = normalizedPrimarySemantic().let {
    it.value?.takeIf { value -> value > 0 && it.unit == "km/h" && it.kind in setOf(TrafficSignSemanticKind.MAXIMUM_SPEED,
        TrafficSignSemanticKind.ZONE_START) }
}

internal data class TrafficSignSupplementaryPixelRect(val x: Int, val y: Int, val width: Int, val height: Int)

/** Same native primary-plus-lower crop used by iPhone admission and extraction. */
internal fun supplementaryOCRContextPixelRect(box: NormalizedTrafficSignBoundingBox, width: Int, height: Int): TrafficSignSupplementaryPixelRect? {
    if (width <= 0 || height <= 0) return null
    val x = floor(box.x * width).toInt()
    val y = floor(box.y * height).toInt()
    val cropWidth = ceil(box.width * width).toInt()
    val cropHeight = ceil(box.height * height).toInt() * 2
    return if (cropWidth >= 48 && cropHeight >= 64 && x + cropWidth <= width && y + cropHeight <= height &&
        cropWidth.toLong() * cropHeight <= 4_000_000)
        TrafficSignSupplementaryPixelRect(x, y, cropWidth, cropHeight) else null
}

/** Admission measures the exact lower half that the native crop will retain. */
internal fun supplementaryTextPixelRect(box: NormalizedTrafficSignBoundingBox, width: Int, height: Int): TrafficSignSupplementaryPixelRect? {
    val context = supplementaryOCRContextPixelRect(box, width, height) ?: return null
    return TrafficSignSupplementaryPixelRect(context.x, context.y + context.height / 2, context.width, context.height / 2)
}

/** Pixel-quality retries are independent of sign/speed fusion and never evaluate conditions. */
internal class TrafficSignSupplementaryTextTracker {
    val conditionalInterpretationCandidate: ConditionalOCRInterpretation.Parsed? get() = current?.latest?.let { annotation ->
        annotation.rawText?.takeIf { annotation.status == TrafficSignSupplementaryOCRStatus.READ &&
            annotation.primarySpeedKmh != null && annotation.primaryClassId == "maxspeed:${annotation.primarySpeedKmh}" }
            ?.let(ConditionalOCRInterpretation::parse)
    }
    data class Admission(val request: TrafficSignSupplementaryOCRRequest?,
        val presentation: TrafficSignSupplementaryTextAnnotation?, val latestAttempt: TrafficSignSupplementaryTextAnnotation?)
    private data class Track(val id: String, val classId: String, val speed: Int?, val firstSeen: Instant,
        var box: NormalizedTrafficSignBoundingBox, var lastSeen: Instant, var lastFrame: String,
        var frames: Int = 1, var attempts: Int = 0, var lastAttemptAt: Instant? = null, var lastArea: Int = 0,
        var best: TrafficSignSupplementaryTextAnnotation? = null, var latest: TrafficSignSupplementaryTextAnnotation? = null,
        var pendingConfirmation:Boolean=false,var confirmedProofKey:String?=null)
    private val tracks = linkedMapOf<String, Track>()
    private var current: Track? = null
    private var scope: TrafficSignSupplementaryScope? = null

    fun reset() { tracks.clear(); current = null; scope = null }

    fun begin(candidate: TrafficSignCandidate?, physicalId: String?, frameId: String, at: Instant,
        scope: TrafficSignSupplementaryScope, confirmed: Boolean, evidenceFrames: Int,
        width: Int, height: Int, thermallyDeferred: Boolean = false,
        otherPrimaryBoxes:List<NormalizedTrafficSignBoundingBox> = emptyList()): Admission {
        if (this.scope != scope) { reset(); this.scope = scope }
        val c = candidate ?: return Admission(null, null, null)
        val previous = current
        val gap = previous?.let { Duration.between(it.lastSeen, at) }
        val continuous = previous != null && previous.classId == c.rawClassId && previous.speed == c.numericSupplementarySpeed() &&
            gap != null && !gap.isNegative && gap <= Duration.ofSeconds(2) &&
            if (physicalId != null) previous.id == physicalId else previous.box.intersectionOverUnion(c.boundingBox) >= .1
        val id = physicalId ?: if (continuous) requireNotNull(previous).id else java.util.UUID.randomUUID().toString()
        val key = "${c.rawClassId}:${c.numericSupplementarySpeed()}:$id"
        val track = if (continuous) requireNotNull(previous) else {
            // Retain the attempt budget for an explicit physical ID, but never revive stale display text.
            val old = tracks[key]
            Track(id, c.rawClassId, c.numericSupplementarySpeed(), at, c.boundingBox, at, frameId,
                attempts = old?.attempts ?: 0, lastAttemptAt = old?.lastAttemptAt, lastArea = old?.lastArea ?: 0)
                .also { tracks[key] = it; while (tracks.size > 64) tracks.remove(tracks.keys.first()) }
        }
        if (continuous && frameId != track.lastFrame && at > track.lastSeen) track.frames++
        track.box = c.boundingBox; track.lastSeen = at; track.lastFrame = frameId; current = track
        fun cached() = Admission(null, (track.best ?: track.latest)?.copy(observedAt = at), track.latest)
        val qualified = if (track.speed != null) confirmed && evidenceFrames >= 2 else track.frames >= 2
        if (!qualified || thermallyDeferred) return cached()
        val rect = supplementaryTextPixelRect(c.boundingBox, width, height) ?: return cached()
        val area = rect.width * rect.height
        if (track.attempts >= 6 || track.lastAttemptAt?.let { Duration.between(it, at) < Duration.ofMillis(300) } == true ||
            (track.attempts >= 2 && !track.pendingConfirmation && area < track.lastArea * 1.8)) return cached()
        track.attempts++; track.lastArea = area; track.lastAttemptAt = at
        return Admission(TrafficSignSupplementaryOCRRequest(c, id, frameId, at, track.firstSeen, scope, track.attempts,otherPrimaryBoxes),
            (track.best ?: track.latest)?.copy(observedAt = at), track.latest)
    }

    fun finish(request: TrafficSignSupplementaryOCRRequest, annotation: TrafficSignSupplementaryTextAnnotation): Admission? {
        val track = current?.takeIf { scope == request.scope && it.id == request.physicalSignId &&
            it.classId == request.candidate.rawClassId && it.lastSeen >= request.observedAt &&
            Duration.between(request.observedAt, it.lastSeen) <= Duration.ofSeconds(2) } ?: return null
        fun proofKey(value:TrafficSignSupplementaryTextAnnotation):String? {
            val kind=value.assemblyEvidence?.validate(value.primaryBoundingBox,value.rawText,value.frameId,value.sourceObservedAt)?.kind
            return kind?.takeIf {it!=TrafficSignConditionalAssemblyEvidence.Kind.UNRESOLVED}?.let {
                "${it}:${value.primaryClassId}:${value.primarySpeedKmh}:${value.assemblyEvidence?.plateRects?.size}:${TrafficSignOCRQuality.comparison(value.rawText.orEmpty())}:${value.engine}:${value.modelVersion}"
            }
        }
        val key=proofKey(annotation);val previous=track.latest
        val span=previous?.let {Duration.between(it.sourceObservedAt,annotation.sourceObservedAt).toMillis()}
        if(key!=null && previous!=null && key==proofKey(previous) && previous.frameId!=annotation.frameId && span!=null && span in 100..2000) {
            track.confirmedProofKey=key;track.pendingConfirmation=false
        } else track.pendingConfirmation=key!=null && key!=track.confirmedProofKey
        track.latest = annotation
        if (annotation.hasText) track.best = annotation
        return Admission(null, (track.best ?: annotation).copy(observedAt = track.lastSeen), annotation)
    }
}
