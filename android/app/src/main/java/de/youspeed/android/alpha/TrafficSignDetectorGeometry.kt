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

/** Tight classifier crop in upright source pixels, centered in the tensor at a uniform scale. */
internal class TrafficSignClassifierGeometry private constructor(
    val sourceLeft: Double,
    val sourceTop: Double,
    width: Double,
    height: Double,
) {
    val scale = SIZE / maxOf(width, height)
    val scaledWidth = width * scale
    val scaledHeight = height * scale
    val left = (SIZE - scaledWidth) / 2
    val top = (SIZE - scaledHeight) / 2

    companion object {
        const val SIZE = 224
        const val PREPROCESSING_VERSION = "crop-fit-letterbox-rgb-224-min-aspect-0.8-v1"

        fun from(box: NormalizedTrafficSignBoundingBox, sourceWidth: Int, sourceHeight: Int): TrafficSignClassifierGeometry? {
            val width = box.width * sourceWidth
            val height = box.height * sourceHeight
            if (width <= 0 || height <= 0 || width < height * 0.8) return null
            return TrafficSignClassifierGeometry(box.x * sourceWidth, box.y * sourceHeight, width, height)
        }
    }
}

/** Horizontal source window spanning the full upright frame height. */
internal data class TrafficSignDetectorWindow(val left: Int, val width: Int, val height: Int) {
    init { require(left >= 0 && width > 0 && height > 0) }

    fun sourceBox(box: NormalizedTrafficSignBoundingBox, sourceWidth: Int) =
        NormalizedTrafficSignBoundingBox(
            x = (left + box.x * width) / sourceWidth,
            y = box.y,
            width = box.width * width / sourceWidth,
            height = box.height,
        )

    companion object {
        fun twoEdges(width: Int, height: Int): List<TrafficSignDetectorWindow> {
            require(width > 0 && height > 0)
            val whole = TrafficSignDetectorWindow(0, width, height)
            if (width <= height) return listOf(whole)
            val edges = listOf(TrafficSignDetectorWindow(0, height, height),
                TrafficSignDetectorWindow(width - height, height, height))
            return if (width > 2 * height) edges + whole else edges
        }
    }
}
