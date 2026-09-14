package de.youspeed.android.alpha

import android.content.Context
import android.graphics.BitmapFactory
import java.security.MessageDigest

internal data class AndroidTrafficSignStartupResult(
    val timingProfile: TrafficSignInferenceTimingProfile,
    val warmInferenceTimesMs: List<Double>,
    val executionBackend: String,
    val accelerationFallbackReason: String?,
    val gpuPrecisionLossAllowed: Boolean? = null,
)

/** Functional and timing check only. Reference detections never enter the live event pipeline. */
internal object AndroidTrafficSignStartupProbe {
    const val REFERENCE_ASSET = "tsr/runtime-reference/panoramax-0906fc23.jpg"
    const val REFERENCE_SHA256 = "3ad4c4349a121ab9695a8febaeb0bff4feadef4739672f434c63e98c8f0d3d0b"
    const val REFERENCE_CLASS_ID = "maxspeed:70"
    private const val WARM_RUNS = 2

    /** Call on the engine's owner thread, before admitting live camera frames. */
    fun run(
        context: Context,
        engine: AndroidLiteRtTrafficSignInferenceEngine,
        pack: TrafficSignModelPack,
    ): AndroidTrafficSignStartupResult {
        val bytes = context.assets.open(REFERENCE_ASSET).use { it.readBytes() }
        val hash = MessageDigest.getInstance("SHA-256").digest(bytes)
            .joinToString("") { "%02x".format(it.toInt() and 0xff) }
        check(hash == REFERENCE_SHA256) { "Traffic-sign startup reference failed its integrity check" }
        val bitmap = checkNotNull(BitmapFactory.decodeByteArray(bytes, 0, bytes.size)) {
            "Traffic-sign startup reference could not be decoded"
        }
        val threshold = pack.classMapping.single { it.classId == REFERENCE_CLASS_ID }.threshold
        fun checkRecognition(result: AndroidTrafficSignInferenceResult) {
            check(result.detections.any { detection ->
                val candidate = detection.candidate
                candidate.rawClassId == REFERENCE_CLASS_ID &&
                    candidate.semantic.kind == TrafficSignSemanticKind.MAXIMUM_SPEED &&
                    candidate.semantic.value == 70 &&
                    candidate.rawScore >= maxOf(threshold, pack.thresholds.confirmed) &&
                    (candidate.classifierRawScore ?: 0.0) >= TrafficSignDisplayPolicy.MINIMUM_SCORE
            }) { "Traffic-sign startup check could not recognize the reference 70 km/h sign" }
        }
        try {
            // Compilation/cold caches are excluded from the allowance for steady live frames.
            checkRecognition(engine.recognizeAllWithDiagnostics(bitmap))
            val warmResults = List(WARM_RUNS) {
                engine.recognizeAllWithDiagnostics(bitmap).also(::checkRecognition)
            }
            val timings = warmResults.map { it.inferenceMs }
            return AndroidTrafficSignStartupResult(
                timingProfile = checkNotNull(TrafficSignInferenceTimingPolicy.profile(
                    manifestConfirmationWindowMs = pack.thresholds.confirmationWindowMs,
                    referenceVerified = true,
                    warmInferenceTimesMs = timings,
                )),
                warmInferenceTimesMs = timings,
                executionBackend = warmResults.last().executionBackend,
                accelerationFallbackReason = warmResults.last().accelerationFallbackReason,
                gpuPrecisionLossAllowed = engine.gpuPrecisionLossAllowed.takeIf {
                    warmResults.last().executionBackend in setOf("gpu", "mixed")
                },
            )
        } finally {
            bitmap.recycle()
        }
    }
}
