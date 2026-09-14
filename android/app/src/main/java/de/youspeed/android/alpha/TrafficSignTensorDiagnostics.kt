package de.youspeed.android.alpha

internal data class TrafficSignRawOutputSummary(
    val signTopScore: Double?,
    val globalTopScore: Double?,
    val signScoresAboveThreshold: Int,
)

/** Scan tensor diagnostics without allocating a boxed Double for every output element. */
internal object TrafficSignTensorDiagnostics {
    fun summarize(output: FloatArray, signOffset: Int, signCount: Int, minimumScore: Double): TrafficSignRawOutputSummary {
        require(signOffset >= 0 && signCount >= 0 && signOffset <= output.size - signCount)
        var signTop = Float.NEGATIVE_INFINITY
        var globalTop = Float.NEGATIVE_INFINITY
        var aboveThreshold = 0
        val signEnd = signOffset + signCount
        for (index in output.indices) {
            val value = output[index]
            if (!value.isFinite()) continue
            globalTop = maxOf(globalTop, value)
            if (index >= signOffset && index < signEnd) {
                signTop = maxOf(signTop, value)
                if (value >= minimumScore) aboveThreshold += 1
            }
        }
        return TrafficSignRawOutputSummary(
            signTopScore = if (signTop.isFinite()) signTop.toDouble() else null,
            globalTopScore = if (globalTop.isFinite()) globalTop.toDouble() else null,
            signScoresAboveThreshold = aboveThreshold,
        )
    }
}
