package de.youspeed.android.alpha

import java.nio.ByteBuffer

/** Bulk writes preserve the model's RGB / 255 float32 input without millions of direct-buffer writes. */
internal class TrafficSignRgbTensorEncoder(chunkPixels: Int = 4096) {
    private val values = FloatArray(chunkPixels.also { require(it > 0) } * 3)

    fun write(buffer: ByteBuffer, pixels: IntArray) {
        require(pixels.size <= buffer.capacity() / (3 * Float.SIZE_BYTES))
        buffer.clear()
        buffer.limit(pixels.size * 3 * Float.SIZE_BYTES)
        val output = buffer.asFloatBuffer()
        var pixelIndex = 0
        while (pixelIndex < pixels.size) {
            val end = minOf(pixels.size, pixelIndex + values.size / 3)
            var valueIndex = 0
            while (pixelIndex < end) {
                val color = pixels[pixelIndex++]
                values[valueIndex++] = ((color ushr 16) and 0xff) / 255f
                values[valueIndex++] = ((color ushr 8) and 0xff) / 255f
                values[valueIndex++] = (color and 0xff) / 255f
            }
            output.put(values, 0, valueIndex)
        }
        buffer.rewind()
    }
}
