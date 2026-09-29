package de.youspeed.android.alpha

/** Frozen horizontal 5-pixel white top-hat enhancement, verified against OpenCV uint8 fixtures. */
object RoadPathLaneFilter {
    const val ID = "top_hat5_horizontal_gain1_5_v1"

    fun apply(gray: ByteArray, width: Int, height: Int, shouldContinue: () -> Boolean = { true }): ByteArray? {
        if (width !in 1..384 || height !in 1..216 || gray.size != width * height) return null
        val erosion = ByteArray(gray.size)
        val output = ByteArray(gray.size)
        for (y in 0 until height) {
            if (!shouldContinue()) return null
            for (x in 0 until width) {
                if (x % 32 == 0 && !shouldContinue()) return null
                var minimum = 255
                for (dx in maxOf(0, x - 2)..minOf(width - 1, x + 2))
                    minimum = minOf(minimum, gray[y * width + dx].toInt() and 255)
                erosion[y * width + x] = minimum.toByte()
            }
        }
        for (y in 0 until height) {
            if (!shouldContinue()) return null
            for (x in 0 until width) {
                if (x % 32 == 0 && !shouldContinue()) return null
                var opened = 0
                for (dx in maxOf(0, x - 2)..minOf(width - 1, x + 2))
                    opened = maxOf(opened, erosion[y * width + dx].toInt() and 255)
                val value = gray[y * width + x].toInt() and 255
                output[y * width + x] = minOf(255, value + (value - opened) * 3 / 2).toByte()
            }
        }
        return output.takeIf { shouldContinue() }
    }
}
