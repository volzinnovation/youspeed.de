package de.youspeed.android.alpha

import android.content.Context
import androidx.exifinterface.media.ExifInterface
import java.io.File
import java.io.FileInputStream
import java.nio.file.Files
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.double
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put

/**
 * File-backed queue for Panoramax originals and metadata. The queue lives below
 * noBackupFilesDir so Android backup/device transfer never includes imagery,
 * thumbnails, precise locations, or queue state.
 */
class PanoramaxQueueStore(private val appRoot: File) {
    constructor(context: Context) : this(context.noBackupFilesDir)

    private val root = File(appRoot, "panoramax")
    private val batchesDir = File(root, "batches")
    private val json = Json { prettyPrint = false }

    init {
        batchesDir.mkdirs()
    }

    @Synchronized
    fun createBatch(captureSessionId: String, createdAt: Instant = Instant.now()): PanoramaxBatchRecord {
        require(captureSessionId.isNotBlank())
        val batch = PanoramaxBatchRecord(
            batchId = UUID.randomUUID().toString(),
            captureSessionId = captureSessionId,
            createdAt = createdAt,
            state = PanoramaxBatchState.CAPTURING,
            items = emptyList(),
        )
        write(batch)
        return batch
    }

    @Synchronized
    fun listBatches(): List<PanoramaxBatchRecord> = batchesDir.listFiles { file -> file.extension == "json" }
        ?.mapNotNull { file -> runCatching { decode(file.readText()) }.getOrNull() }
        ?.sortedByDescending { it.createdAt }
        ?: emptyList()

    @Synchronized
    fun getBatch(batchId: String): PanoramaxBatchRecord? = fileFor(batchId).takeIf(File::exists)?.let { decode(it.readText()) }

    @Synchronized
    fun addJpeg(
        batchId: String,
        jpeg: File,
        thumbnail: File,
        metadata: PanoramaxCaptureMetadata,
    ): PanoramaxItemRecord {
        require(jpeg.isFile && jpeg.length() > 0) { "JPEG does not exist or is empty" }
        require(thumbnail.isFile && thumbnail.length() > 0) { "thumbnail does not exist or is empty" }
        require(jpeg.isJpeg()) { "original must be a JPEG" }
        val metadataErrors = metadata.validate(Instant.now())
        require(metadataErrors.isEmpty()) { metadataErrors.joinToString("; ") }
        require(metadata.byteSize == jpeg.length()) { "metadata byteSize does not match JPEG" }
        val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
        require(batch.captureSessionId == metadata.captureSessionId) { "capture session mismatch" }
        require(batch.state == PanoramaxBatchState.CAPTURING) { "Panoramax batch is no longer capturing" }
        val itemId = metadata.captureId
        require(batch.items.none { it.itemId == itemId }) { "duplicate captureId" }
        val itemDir = File(File(batchesDir, batchId), itemId).apply { mkdirs() }
        val original = File(itemDir, "$itemId.jpg")
        val thumb = File(itemDir, "$itemId.thumb.jpg")
        jpeg.copyTo(original, overwrite = false)
        thumbnail.copyTo(thumb, overwrite = false)
        val item = PanoramaxItemRecord(itemId, original.relativeTo(root).path, thumb.relativeTo(root).path, metadata, PanoramaxItemState.CAPTURED)
        write(batch.copy(items = batch.items + item))
        return item
    }

    /**
     * Repairs EXIF Photo.UserComment from the durable queue sidecar immediately
     * before upload. The staged JPEG and its hash/size are updated atomically.
     */
    @Synchronized
    fun prepareOriginalForUpload(batchId: String, itemId: String): File {
        val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
        val index = batch.items.indexOfFirst { it.itemId == itemId }
        require(index >= 0) { "Unknown Panoramax item" }
        val item = batch.items[index]
        val original = File(root, item.originalPath)
        require(original.isFile && original.isJpeg()) { "Panoramax original is unavailable" }
        val annotations = item.metadata.trafficSignAnnotations.orEmpty()
        if (annotations.isEmpty()) return original
        val expectedComment = requireNotNull(PanoramaxExifUserCommentCodec.encode(annotations)) {
            "Panoramax annotation sidecar is invalid"
        }
        val existing = runCatching {
            ExifInterface(original.absolutePath).getAttribute(ExifInterface.TAG_USER_COMMENT)
        }.getOrNull()
        if (PanoramaxExifUserCommentCodec.decode(existing) == annotations) return original

        val temporary = File(original.parentFile, ".${original.name}.annotated.tmp")
        temporary.delete()
        original.copyTo(temporary, overwrite = false)
        try {
            val exif = ExifInterface(temporary.absolutePath)
            exif.setAttribute(ExifInterface.TAG_USER_COMMENT, expectedComment)
            exif.saveAttributes()
            val verifiedExif = ExifInterface(temporary.absolutePath)
            check(PanoramaxExifUserCommentCodec.decode(
                verifiedExif.getAttribute(ExifInterface.TAG_USER_COMMENT),
            ) == annotations) { "Unable to verify Panoramax EXIF annotation envelope" }
            try {
                Files.move(
                    temporary.toPath(),
                    original.toPath(),
                    StandardCopyOption.ATOMIC_MOVE,
                    StandardCopyOption.REPLACE_EXISTING,
                )
            } catch (_: AtomicMoveNotSupportedException) {
                Files.move(
                    temporary.toPath(),
                    original.toPath(),
                    StandardCopyOption.REPLACE_EXISTING,
                )
            }
            val refreshedExif = ExifInterface(original.absolutePath)
            val refreshedMetadata = item.metadata.copy(
                sha256 = sha256(original),
                byteSize = original.length(),
                imageWidthPixels = refreshedExif
                    .getAttributeInt(ExifInterface.TAG_IMAGE_WIDTH, 0)
                    .takeIf { it > 0 } ?: item.metadata.imageWidthPixels,
                imageHeightPixels = refreshedExif
                    .getAttributeInt(ExifInterface.TAG_IMAGE_LENGTH, 0)
                    .takeIf { it > 0 } ?: item.metadata.imageHeightPixels,
            )
            val refreshedItems = batch.items.toMutableList().also {
                it[index] = item.copy(metadata = refreshedMetadata)
            }
            write(batch.copy(items = refreshedItems))
            return original
        } finally {
            temporary.delete()
        }
    }

    @Synchronized
    fun updateBatch(batch: PanoramaxBatchRecord) {
        require(batch.batchId.isNotBlank())
        write(batch)
    }

    /** Updates lifecycle state on the latest stored snapshot so concurrently
     * appended capture items cannot be lost by sealing a stale batch value. */
    @Synchronized
    fun transitionBatch(batchId: String, state: PanoramaxBatchState): PanoramaxBatchRecord {
        val current = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
        val updated = current.copy(state = state)
        write(updated)
        return updated
    }

    @Synchronized
    fun updateItem(batchId: String, itemId: String, state: PanoramaxItemState, remoteId: String? = null): PanoramaxBatchRecord {
        val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
        val updated = batch.copy(items = batch.items.map { item ->
            if (item.itemId == itemId) item.copy(state = state, remoteId = remoteId ?: item.remoteId) else item
        })
        write(updated)
        return updated
    }

    @Synchronized
    fun deleteItem(batchId: String, itemId: String): PanoramaxBatchRecord {
        val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
        val item = batch.items.firstOrNull { it.itemId == itemId }
        item?.let { File(root, it.originalPath).parentFile?.deleteRecursively() }
        val updated = batch.copy(items = batch.items.filterNot { it.itemId == itemId })
        write(updated)
        return updated
    }

    @Synchronized
    fun deleteBatch(batchId: String) {
        File(batchesDir, batchId).deleteRecursively()
        fileFor(batchId).delete()
    }

    private fun write(batch: PanoramaxBatchRecord) {
        val destination = fileFor(batch.batchId)
        val temporary = File(destination.parentFile, ".${destination.name}.tmp")
        temporary.writeText(encode(batch).toString())
        check(temporary.renameTo(destination)) { "Could not commit Panoramax queue transaction" }
    }

    private fun fileFor(batchId: String) = File(batchesDir, "$batchId.json")

    private fun encode(batch: PanoramaxBatchRecord) = buildJsonObject {
        put("batch_id", batch.batchId)
        put("capture_session_id", batch.captureSessionId)
        put("created_at", batch.createdAt.toString())
        put("state", batch.state.name)
        batch.remoteUploadSetId?.let { put("remote_upload_set_id", it) }
        batch.instanceOrigin?.let { put("instance_origin", it) }
        put("items", buildJsonArray { batch.items.forEach { add(encode(it)) } })
    }

    private fun encode(item: PanoramaxItemRecord) = buildJsonObject {
        put("item_id", item.itemId)
        put("original_path", item.originalPath)
        put("thumbnail_path", item.thumbnailPath)
        put("state", item.state.name)
        item.remoteId?.let { put("remote_id", it) }
        put("metadata", buildJsonObject {
            put("capture_id", item.metadata.captureId)
            put("capture_session_id", item.metadata.captureSessionId)
            put("captured_at", item.metadata.capturedAt.toString())
            put("sha256", item.metadata.sha256)
            put("byte_size", item.metadata.byteSize)
            put("software", item.metadata.software)
            item.metadata.imageWidthPixels?.let { put("image_width_pixels", it) }
            item.metadata.imageHeightPixels?.let { put("image_height_pixels", it) }
            item.metadata.trafficSignAnnotations?.let { annotations ->
                PanoramaxExifUserCommentCodec.encode(annotations)?.let {
                    put("traffic_sign_user_comment", it)
                }
            }
            put("location", buildJsonObject {
                put("latitude", item.metadata.location.latitude)
                put("longitude", item.metadata.location.longitude)
                put("captured_at", item.metadata.location.capturedAt.toString())
                put("accuracy_m", item.metadata.location.accuracyMeters)
                item.metadata.location.altitudeMeters?.let { put("altitude_m", it) }
                item.metadata.location.headingDegrees?.let { put("heading_deg", it) }
            })
        })
    }

    private fun decode(raw: String): PanoramaxBatchRecord {
        val root = json.parseToJsonElement(raw).jsonObject
        val items = root["items"]?.jsonArray?.map { decodeItem(it.jsonObject) } ?: emptyList()
        return PanoramaxBatchRecord(
            batchId = root.requiredString("batch_id"),
            captureSessionId = root.requiredString("capture_session_id"),
            createdAt = Instant.parse(root.requiredString("created_at")),
            state = PanoramaxBatchState.valueOf(root.requiredString("state")),
            items = items,
            remoteUploadSetId = root["remote_upload_set_id"]?.jsonPrimitive?.content,
            instanceOrigin = root["instance_origin"]?.jsonPrimitive?.content,
        )
    }

    private fun decodeItem(root: JsonObject): PanoramaxItemRecord {
        val metadata = root.requiredObject("metadata")
        val location = metadata.requiredObject("location")
        return PanoramaxItemRecord(
            itemId = root.requiredString("item_id"),
            originalPath = root.requiredString("original_path"),
            thumbnailPath = root.requiredString("thumbnail_path"),
            state = PanoramaxItemState.valueOf(root.requiredString("state")),
            remoteId = root["remote_id"]?.jsonPrimitive?.content,
            metadata = PanoramaxCaptureMetadata(
                captureId = metadata.requiredString("capture_id"),
                captureSessionId = metadata.requiredString("capture_session_id"),
                capturedAt = Instant.parse(metadata.requiredString("captured_at")),
                sha256 = metadata.requiredString("sha256"),
                byteSize = metadata.requiredLong("byte_size"),
                software = metadata.requiredString("software"),
                imageWidthPixels = metadata["image_width_pixels"]?.jsonPrimitive?.longOrNull?.toInt(),
                imageHeightPixels = metadata["image_height_pixels"]?.jsonPrimitive?.longOrNull?.toInt(),
                trafficSignAnnotations = metadata["traffic_sign_user_comment"]
                    ?.jsonPrimitive
                    ?.content
                    ?.let(PanoramaxExifUserCommentCodec::decode),
                location = PanoramaxLocationSample(
                    latitude = location.requiredDouble("latitude"),
                    longitude = location.requiredDouble("longitude"),
                    capturedAt = Instant.parse(location.requiredString("captured_at")),
                    accuracyMeters = location.requiredDouble("accuracy_m"),
                    altitudeMeters = location["altitude_m"]?.jsonPrimitive?.doubleOrNull,
                    headingDegrees = location["heading_deg"]?.jsonPrimitive?.doubleOrNull,
                ),
            ),
        )
    }

    companion object {
        fun sha256(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            FileInputStream(file).use { input ->
                val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                while (true) {
                    val read = input.read(buffer)
                    if (read < 0) break
                    digest.update(buffer, 0, read)
                }
            }
            return digest.digest().joinToString("") { "%02x".format(it) }
        }
    }
}

private fun File.isJpeg(): Boolean {
    if (length() < 4) return false
    FileInputStream(this).use { input ->
        val header = ByteArray(2)
        if (input.read(header) != 2 || header[0] != 0xFF.toByte() || header[1] != 0xD8.toByte()) return false
        input.skip(length() - 4)
        val footer = ByteArray(2)
        return input.read(footer) == 2 && footer[0] == 0xFF.toByte() && footer[1] == 0xD9.toByte()
    }
}

data class PanoramaxBatchRecord(
    val batchId: String,
    val captureSessionId: String,
    val createdAt: Instant,
    val state: PanoramaxBatchState,
    val items: List<PanoramaxItemRecord>,
    val remoteUploadSetId: String? = null,
    val instanceOrigin: String? = null,
)

data class PanoramaxItemRecord(
    val itemId: String,
    val originalPath: String,
    val thumbnailPath: String,
    val metadata: PanoramaxCaptureMetadata,
    val state: PanoramaxItemState,
    val remoteId: String? = null,
)

private fun JsonObject.requiredString(key: String): String = this[key]?.jsonPrimitive?.content?.takeIf { it.isNotBlank() }
    ?: error("Missing $key")
private fun JsonObject.requiredObject(key: String): JsonObject = this[key]?.jsonObject ?: error("Missing $key")
private fun JsonObject.requiredLong(key: String): Long = this[key]?.jsonPrimitive?.longOrNull ?: error("Missing $key")
private fun JsonObject.requiredDouble(key: String): Double = this[key]?.jsonPrimitive?.doubleOrNull ?: error("Missing $key")
