package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.graphics.ColorSpace
import java.io.ByteArrayOutputStream
import java.time.Instant
import kotlinx.serialization.json.*

internal data class SignCollectionCrop(val geometry: SignCollectionCropGeometry, val bytes: ByteArray, val sourceHash: String?, val sourceWidth: Int, val sourceHeight: Int) {
    val encodedHash get() = SignCollectionJson.sha256(bytes)
    companion object {
        /** Exact sampled frame already upright; never a nearby Panoramax still. */
        fun generate(upright: Bitmap, box: Map<String, Double>, hashSource: Boolean = true): SignCollectionCrop {
            val width = upright.width; val height = upright.height
            require(width.toLong() * height <= 32_000_000 && upright.colorSpace == ColorSpace.get(ColorSpace.Named.SRGB) && !upright.hasAlpha()) { "upright_opaque_srgb_required" }
            val geometry = SignCollectionCropGeometry.resolve(width, height, box)
            val sourceHash = if (hashSource) {
                val pixels = IntArray(width * height); upright.getPixels(pixels, 0, width, 0, 0, width, height)
                val rgb = ByteArray(width * height * 3)
                pixels.forEachIndexed { i, p -> rgb[i * 3] = (p shr 16).toByte(); rgb[i * 3 + 1] = (p shr 8).toByte(); rgb[i * 3 + 2] = p.toByte() }
                SignCollectionJson.sha256(rgb)
            } else null
            val b = geometry.actual
            val cropped = Bitmap.createBitmap(upright, b[0], b[1], b[2]-b[0], b[3]-b[1])
            val output = ByteArrayOutputStream()
            try { check(cropped.compress(Bitmap.CompressFormat.PNG, 100, output)) } finally { if (cropped !== upright) cropped.recycle() }
            val bytes = privatePng(output.toByteArray()); require(bytes.size <= 5 * 1024 * 1024)
            // Fresh PNG encoding does not carry source EXIF/GPS metadata.
            return SignCollectionCrop(geometry, bytes, sourceHash, width, height)
        }
        private fun privatePng(bytes: ByteArray): ByteArray {
            require(bytes.size >= 8 && bytes.take(8) == listOf(137,80,78,71,13,10,26,10).map(Int::toByte))
            val output = ByteArrayOutputStream(); output.write(bytes, 0, 8); var offset = 8
            while (offset < bytes.size) {
                require(offset + 12 <= bytes.size)
                val length = (0..3).fold(0L) { n, i -> (n shl 8) or (bytes[offset+i].toLong() and 255) }
                require(length <= bytes.size - offset - 12)
                val type = bytes.copyOfRange(offset+4, offset+8).toString(Charsets.US_ASCII)
                if (type in listOf("IHDR", "PLTE", "IDAT", "IEND")) output.write(bytes, offset, length.toInt()+12)
                else require(bytes[offset+4].toInt() and 32 != 0)
                offset += length.toInt()+12
            }
            return output.toByteArray()
        }
    }
    fun metadata(cropId: String, observationId: String, installationId: String, epoch: Int, sourceKind: String, frameAt: Instant,
        localFrameToken: String?, privacyPreflight: String, redactionVersion: String, collectionClaim: SignCollectionClaim, processorClaim: SignCollectionClaim? = null,
        vehiclePosition: JsonElement = JsonNull, phoneRoadMatch: SignCollectionPhoneRoadMatch? = null): JsonObject =
        JsonObject(geometry.wire + buildJsonObject {
            put("schema_version", 1); put("crop_id", cropId); put("observation_id", observationId); put("installation_id", installationId); put("collection_epoch", epoch)
            put("source_kind", sourceKind); put("source_frame_at", frameAt.toString()); put("source_width", sourceWidth); put("source_height", sourceHeight)
            put("vehicle_position", vehiclePosition); put("phone_road_match", phoneRoadMatch?.metadata(frameAt) ?: JsonNull)
            put("source_upright_sha256", sourceHash?.let(::JsonPrimitive) ?: JsonNull); put("local_frame_token", localFrameToken?.let(::JsonPrimitive) ?: JsonNull)
            put("encoded_sha256", encodedHash); put("byte_length", bytes.size); put("decoded_width", geometry.actual[2]-geometry.actual[0]); put("decoded_height", geometry.actual[3]-geometry.actual[1])
            put("encoding", "PNG"); put("orientation_version", "upright-1"); put("crop_version", "downward-1"); put("redaction_version", redactionVersion)
            put("redaction_masks", JsonArray(emptyList())); put("privacy_preflight", privacyPreflight); put("collection_authorization", collectionClaim.wire); put("processor_authorization", processorClaim?.wire ?: JsonNull)
        })
}

/** One owned upright analyzed frame; never shared with the reused rotation buffer. */
class SignCollectionFrame internal constructor(val token: String, private val bitmap: Bitmap, private val released: () -> Unit) : AutoCloseable {
    private val closed = java.util.concurrent.atomic.AtomicBoolean(false)
    internal fun crop(box: Map<String, Double>): SignCollectionCrop { check(!closed.get()); return SignCollectionCrop.generate(bitmap, box, hashSource = false) }
    override fun close() { if (closed.compareAndSet(false, true)) { bitmap.recycle(); released() } }
}
