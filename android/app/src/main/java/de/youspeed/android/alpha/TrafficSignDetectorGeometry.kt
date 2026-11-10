package de.youspeed.android.alpha

/** Centered letterbox for the upright camera frame. */
internal data class TrafficSignDetectorGeometry(val sourceWidth: Int, val sourceHeight: Int) {
    init { require(sourceWidth > 0 && sourceHeight > 0) }

    val scale: Double get() = SIZE.toDouble() / maxOf(sourceWidth, sourceHeight)
    val scaledWidth: Double get() = sourceWidth * scale
    val scaledHeight: Double get() = sourceHeight * scale
    val left: Double get() = (SIZE - scaledWidth) / 2
    val top: Double get() = (SIZE - scaledHeight) / 2

    companion object { const val SIZE = 1024 }
}
