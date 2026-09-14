package de.youspeed.android.alpha

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class TrafficSignRgbTensorEncoderTests {
    @Test
    fun bulkEncodingPreservesEveryChannelValueAcrossPartialChunksAndReuse() {
        val encoder = TrafficSignRgbTensorEncoder(chunkPixels = 17)
        val pixels = IntArray(256) { value ->
            (value shl 24) or (value shl 16) or ((255 - value) shl 8) or ((value + 113) % 256)
        }
        val output = ByteBuffer.allocateDirect(pixels.size * 12).order(ByteOrder.nativeOrder())
        // Reproduce the previous scalar encoder to pin the model input bytes exactly.
        val scalar = ByteBuffer.allocate(output.capacity()).order(ByteOrder.nativeOrder())
        for (value in 0..255) {
            scalar.putFloat(value / 255f)
            scalar.putFloat((255 - value) / 255f)
            scalar.putFloat(((value + 113) % 256) / 255f)
        }
        output.position(23)
        output.limit(29)
        encoder.write(output, pixels)
        assertEquals(0, output.position())
        assertEquals(scalar.capacity(), output.limit())
        val actualBytes = ByteArray(output.remaining())
        output.get(actualBytes)
        assertArrayEquals(scalar.array(), actualBytes)

        encoder.write(output, intArrayOf(0x00000000, 0x00ffffff))
        assertEquals(0, output.position())
        assertEquals(24, output.limit())
        val values = FloatArray(6)
        output.asFloatBuffer().get(values)
        assertArrayEquals(floatArrayOf(0f, 0f, 0f, 1f, 1f, 1f), values, 0f)
    }
}
