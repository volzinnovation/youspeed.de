package de.youspeed.android.alpha

/** Mobile-only upright detector window. Mounting/lane calibration never changes it. */
internal data class TrafficSignDetectorGeometry(val sourceWidth: Int, val sourceHeight: Int) {
    init { require(sourceWidth > 0 && sourceHeight > 0) }

    val scale: Double get() = SIZE.toDouble() / sourceHeight
    val scaledWidth: Double get() = sourceWidth * scale
    val left: Double get() = scaledWidth - SIZE

    companion object { const val SIZE = 1024 }
}
