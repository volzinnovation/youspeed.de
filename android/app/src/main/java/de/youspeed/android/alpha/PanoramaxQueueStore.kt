package de.youspeed.android.alpha

import android.content.Context
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
import kotlinx.serialization.json.booleanOrNull
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
    private val deletedItemIds = mutableMapOf<String, MutableSet<String>>()
    @Volatile var startupCleanupReport = PanoramaxQueueCleanupReport()
        private set
    @Volatile var unreadableRelativePaths: List<String> = emptyList()
        private set

    init {
        check(batchesDir.isDirectory || batchesDir.mkdirs()) { "Could not create local Panoramax queue" }
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
    fun listBatches(): List<PanoramaxBatchRecord> {
        val failures = mutableListOf<String>()
        val files = checkNotNull(batchesDir.listFiles { file -> file.extension == "json" }) { "Could not read local Panoramax queue" }
        val batches = files.mapNotNull { file ->
            runCatching {
                decode(file.readText()).also { require(it.batchId == file.nameWithoutExtension) }
            }.getOrElse { failures += file.relativeTo(root).path; null }
        }
        unreadableRelativePaths = failures.sorted()
        return batches.sortedByDescending { it.createdAt }
    }

    fun thumbnailFile(item: PanoramaxItemRecord): File = assetFile(item.thumbnailPath)

    fun originalFile(item: PanoramaxItemRecord): File = assetFile(item.originalPath)

    internal fun uploadTemporaryDirectory(): File = File(appRoot, "panoramax-multipart")

    /** Runs on the caller's background executor; referenced originals survive missing previews. */
    @Synchronized
    fun repairMissingThumbnails(): Int {
        var repaired = 0
        listBatches().forEach { batch -> batch.items.forEach item@{ item ->
            val original = originalFile(item)
            val thumbnail = thumbnailFile(item)
            if (!original.isFile) return@item
            val bounds = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
            android.graphics.BitmapFactory.decodeFile(thumbnail.absolutePath, bounds)
            if (bounds.outWidth > 0 && bounds.outHeight > 0) return@item
            val temporary = File(thumbnail.parentFile, ".${thumbnail.name}.tmp")
            try {
                PanoramaxJpegMetadata.createThumbnail(original, temporary)
                try { Files.move(temporary.toPath(), thumbnail.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING) }
                catch (_: AtomicMoveNotSupportedException) { Files.move(temporary.toPath(), thumbnail.toPath(), StandardCopyOption.REPLACE_EXISTING) }
                repaired++
            } finally { temporary.delete() }
        } }
        return repaired
    }

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
        require(metadata.sha256.equals(sha256(jpeg), ignoreCase = true)) { "metadata hash does not match JPEG" }
        val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
        require(batch.captureSessionId == metadata.captureSessionId) { "capture session mismatch" }
        require(batch.state == PanoramaxBatchState.CAPTURING) { "Panoramax batch is no longer capturing" }
        val itemId = metadata.captureId
        requireValidId(itemId)
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
        val original = originalFile(item)
        require(original.isFile && original.isJpeg()) { "Panoramax original is unavailable" }
        val annotations = item.metadata.trafficSignAnnotations.orEmpty()
        val temporary = File(original.parentFile, ".${original.name}.annotated.tmp")
        temporary.delete()
        original.copyTo(temporary, overwrite = false)
        try {
            PanoramaxJpegMetadata.write(temporary, item.metadata.location, annotations)
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
            val dimensions = PanoramaxJpegMetadata.pixelDimensions(original)
            val refreshedMetadata = item.metadata.copy(
                sha256 = sha256(original),
                byteSize = original.length(),
                imageWidthPixels = dimensions?.first ?: item.metadata.imageWidthPixels,
                imageHeightPixels = dimensions?.second ?: item.metadata.imageHeightPixels,
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

    /** A result may arrive just after its still; attach it to the nearest image in the same live batch. */
    @Synchronized
    fun attachTrafficSignAnnotation(
        batchId: String,
        draft: PanoramaxTrafficSignAnnotationDraft,
        maximumTimeDelta: java.time.Duration = java.time.Duration.ofSeconds(5),
        eligibleCaptureIds: Set<String>? = null,
        minimumCapturedAt: Instant? = null,
    ): String? {
        val batch = getBatch(batchId) ?: return null
        if (batch.state != PanoramaxBatchState.CAPTURING) return null
        // Selection is restricted before finding the nearest photo. An image
        // from another mount position can be closer in time to this result.
        val item = batch.items.asSequence()
            .filter { eligibleCaptureIds == null || it.itemId in eligibleCaptureIds }
            .filter { minimumCapturedAt == null || !it.metadata.capturedAt.isBefore(minimumCapturedAt) }
            .minByOrNull { java.time.Duration.between(it.metadata.capturedAt, draft.frameTimestampUtc).abs() } ?: return null
        if (java.time.Duration.between(item.metadata.capturedAt, draft.frameTimestampUtc).abs() > maximumTimeDelta) return null
        val original = originalFile(item)
        if (!original.isFile) return null
        val dimensions = PanoramaxJpegMetadata.pixelDimensions(original) ?: return null
        val annotation = draft.projected(dimensions.first, dimensions.second, item.metadata.capturedAt, maximumTimeDelta) ?: return null
        val annotations = item.metadata.trafficSignAnnotations.orEmpty().toMutableList()
        if (annotations.any { it.sourceEventId == annotation.sourceEventId }) return item.itemId
        val existingIndex = if (annotation.physicalSignTrackId == null) -1 else annotations.indexOfFirst {
            it.physicalSignTrackId == annotation.physicalSignTrackId && it.speedLimitKmh == annotation.speedLimitKmh
        }
        if (existingIndex >= 0) {
            if (annotation.classificationConfidence <= annotations[existingIndex].classificationConfidence) return item.itemId
            annotations[existingIndex] = annotation
        } else annotations += annotation
        val temporary = File(original.parentFile, ".${original.name}.annotation.tmp")
        original.copyTo(temporary, overwrite = true)
        try {
            PanoramaxJpegMetadata.write(temporary, item.metadata.location, annotations)
            val metadata = item.metadata.copy(sha256 = sha256(temporary), byteSize = temporary.length(),
                imageWidthPixels = dimensions.first, imageHeightPixels = dimensions.second, trafficSignAnnotations = annotations)
            try {
                Files.move(temporary.toPath(), original.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
            } catch (_: AtomicMoveNotSupportedException) {
                Files.move(temporary.toPath(), original.toPath(), StandardCopyOption.REPLACE_EXISTING)
            }
            // The store lock excludes capture sealing, deletion, and simultaneous item updates.
            write(batch.copy(items = batch.items.map { if (it.itemId == item.itemId) it.copy(metadata = metadata) else it }))
            return item.itemId
        } finally { temporary.delete() }
    }

    @Synchronized
    fun updateBatch(batch: PanoramaxBatchRecord) {
        requireNotNull(getBatch(batch.batchId)) { "Unknown Panoramax batch" }
        write(batch.copy(items = batch.items.filterNot { it.itemId in deletedItemIds[batch.batchId].orEmpty() }))
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
        require(batch.items.any { it.itemId == itemId }) { "Unknown Panoramax item" }
        val updated = batch.copy(items = batch.items.map { item ->
            if (item.itemId == itemId) item.copy(state = state, remoteId = remoteId ?: item.remoteId) else item
        })
        write(updated)
        return updated
    }

    @Synchronized
    fun deleteItem(batchId: String, itemId: String): PanoramaxBatchRecord {
        val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
        val report = deleteItems(batchId, setOf(itemId))
        check(!report.hasFailures) { "Could not remove local images: ${report.failedRelativePaths.joinToString()}" }
        return getBatch(batchId) ?: batch.copy(items = emptyList())
    }

    @Synchronized
    fun deleteBatch(batchId: String) {
        val batch = getBatch(batchId) ?: return
        val report = deleteItems(batchId, batch.items.map { it.itemId }.toSet())
        check(!report.hasFailures) { "Could not remove local images: ${report.failedRelativePaths.joinToString()}" }
    }

    @Synchronized
    fun updateItemFavorite(batchId: String, itemId: String, isFavorite: Boolean): PanoramaxBatchRecord {
        val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
        require(batch.items.any { it.itemId == itemId }) { "Unknown Panoramax item" }
        return batch.copy(items = batch.items.map { if (it.itemId == itemId) it.copy(isFavorite = isFavorite) else it }).also(::write)
    }

    /** Explicit selection is the only path from local review to upload approval. */
    @Synchronized
    fun approveSelection(batchId: String, selectedItemIds: Set<String>): PanoramaxBatchRecord {
        val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
        require(PanoramaxQueuePolicy.canEditSelection(batch.state)) { "Batch is not reviewable" }
        val selected = batch.items.filter { it.itemId in selectedItemIds && PanoramaxQueuePolicy.canSelectItem(it.state) }
        require(selected.isNotEmpty()) { "No images selected" }
        return batch.copy(
            state = PanoramaxBatchState.APPROVED,
            items = batch.items.map { item ->
                if (PanoramaxQueuePolicy.canSelectItem(item.state)) {
                    item.copy(state = if (item.itemId in selectedItemIds) PanoramaxItemState.QUEUED else PanoramaxItemState.EXCLUDED)
                } else item
            },
        ).also(::write)
    }

    @Synchronized
    fun abandonInFlightItems(batchId: String): PanoramaxBatchRecord {
        val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
        val nextState = when (batch.state) {
            PanoramaxBatchState.CREATING_UPLOAD_SET -> if (batch.remoteUploadSetId == null) PanoramaxBatchState.APPROVED else PanoramaxBatchState.PARTIAL
            PanoramaxBatchState.UPLOADING -> PanoramaxBatchState.PARTIAL
            else -> batch.state
        }
        return batch.copy(state = nextState, items = batch.items.map {
            if (it.state == PanoramaxItemState.UPLOADING) it.copy(state = PanoramaxItemState.ABANDONED) else it
        }).also(::write)
    }

    /** Local deletion is authoritative, including while a cancelled upload unwinds. */
    @Synchronized
    fun deleteItems(batchId: String, itemIds: Set<String>): PanoramaxDeletionReport {
        val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
        val removed = batch.items.filter { it.itemId in itemIds }
        if (removed.isEmpty()) return PanoramaxDeletionReport()
        val updated = batch.copy(items = batch.items.filterNot { it.itemId in itemIds })
        write(updated)
        deletedItemIds.getOrPut(batchId) { mutableSetOf() }.addAll(removed.map { it.itemId })
        val failures = mutableListOf<String>()
        removed.forEach { item ->
            listOf(item.originalPath, item.thumbnailPath).forEach { path ->
                runCatching { val file = assetFile(path); check(!file.exists() || file.delete()) }
                    .onFailure { failures += path }
            }
            runCatching { originalFile(item).parentFile?.let { if (it.listFiles()?.isEmpty() == true) it.delete() } }
        }
        pruneEmptyBatch(updated, failures)
        return PanoramaxDeletionReport(removed.map { it.itemId }, failures)
    }

    @Synchronized
    fun deleteUploadedItems(batchId: String): PanoramaxDeletionReport {
        val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
        require(batch.state == PanoramaxBatchState.COMPLETE) { "Remote upload set is not complete" }
        return deleteItems(batchId, batch.items.filter { PanoramaxQueuePolicy.isUploaded(it.state) }.map { it.itemId }.toSet())
    }

    @Synchronized
    fun deleteUploadedItemsInCompletedBatches(): PanoramaxDeletionReport {
        val deleted = mutableListOf<String>()
        val failures = mutableListOf<String>()
        listBatches().filter { it.state == PanoramaxBatchState.COMPLETE }.forEach { batch ->
            runCatching { deleteUploadedItems(batch.batchId) }.onSuccess {
                deleted += it.deletedItemIds; failures += it.failedRelativePaths
            }.onFailure { failures += "batches/${batch.batchId}.json" }
        }
        return PanoramaxDeletionReport(deleted, failures)
    }

    @Synchronized
    fun enforceStorageLimit(maxBytes: Long): PanoramaxDeletionReport {
        if (maxBytes <= 0) return PanoramaxDeletionReport()
        val batches = listBatches()
        val entries = batches.flatMap { batch -> batch.items.map { batch to it } }
        fun bytes(item: PanoramaxItemRecord) = originalFile(item).length() + thumbnailFile(item).length()
        var total = entries.sumOf { bytes(it.second) }
        val deleted = mutableListOf<String>()
        val failures = mutableListOf<String>()
        entries.filter { (batch, item) -> !item.isFavorite && PanoramaxQueuePolicy.canEvictItem(batch.state, item.state) }
            .sortedBy { it.second.metadata.capturedAt }.forEach { (batch, item) ->
                if (total <= maxBytes || failures.isNotEmpty()) return@forEach
                val size = bytes(item)
                runCatching { deleteItems(batch.batchId, setOf(item.itemId)) }.onSuccess {
                    deleted += it.deletedItemIds; failures += it.failedRelativePaths
                    if (it.deletedItemIds.isNotEmpty()) total -= size
                }.onFailure { failures += "batches/${batch.batchId}.json" }
            }
        return PanoramaxDeletionReport(deleted, failures)
    }

    /** Call once on a background executor before allowing the first camera session. */
    @Synchronized
    fun performStartupMaintenanceNow(): PanoramaxQueueCleanupReport {
        val recovered = mutableListOf<String>()
        val failures = mutableListOf<String>()
        var removedFiles = 0
        var removedBytes = 0L
        var removedBatches = 0
        val batches = listBatches()
        failures += unreadableRelativePaths
        batches.forEach { loaded ->
            var batch = loaded
            runCatching {
                if (batch.state == PanoramaxBatchState.CAPTURING) {
                    batch = transitionBatch(batch.batchId, PanoramaxBatchState.AWAITING_REVIEW)
                }
                batch = abandonInFlightItems(batch.batchId)
                if (batch != loaded) recovered += batch.batchId
                val referenced = batch.items.flatMap { listOf(originalFile(it).canonicalPath, thumbnailFile(it).canonicalPath) }.toSet()
                val directory = File(batchesDir, batch.batchId)
                // Never inspect undecodable records' directories or follow symlinks.
                if (directory.isDirectory && !Files.isSymbolicLink(directory.toPath())) {
                    directory.walkBottomUp().onEnter { !Files.isSymbolicLink(it.toPath()) }.forEach asset@{ file ->
                        if (Files.isSymbolicLink(file.toPath())) return@asset
                        if (file.isFile && file.canonicalPath !in referenced) {
                            val size = file.length()
                            if (file.delete()) { removedFiles++; removedBytes += size }
                            else failures += file.relativeTo(root).path
                        } else if (file.isDirectory && file.listFiles()?.isEmpty() == true) file.delete()
                    }
                }
                if (pruneEmptyBatch(batch, failures)) removedBatches++
            }.onFailure { failures += "batches/${loaded.batchId}.json" }
        }
        uploadTemporaryDirectory().listFiles()?.filter { it.isFile && it.extension == "multipart" }?.forEach { file ->
            if (!file.delete()) failures += "panoramax-multipart/${file.name}"
        }
        return PanoramaxQueueCleanupReport(recovered, removedFiles, removedBytes, removedBatches, failures.distinct().sorted())
            .also { startupCleanupReport = it }
    }

    private fun pruneEmptyBatch(batch: PanoramaxBatchRecord, failures: MutableList<String>): Boolean {
        if (batch.items.isNotEmpty() || batch.state == PanoramaxBatchState.CAPTURING ||
            (batch.remoteUploadSetId != null && batch.state != PanoramaxBatchState.COMPLETE)) return false
        val directory = File(batchesDir, batch.batchId)
        if (directory.exists() && directory.listFiles()?.isNotEmpty() != false) return false
        if (directory.exists() && !directory.delete()) { failures += directory.relativeTo(root).path; return false }
        val record = fileFor(batch.batchId)
        if (record.exists() && !record.delete()) { failures += record.relativeTo(root).path; return false }
        return true
    }

    private fun write(batch: PanoramaxBatchRecord) {
        val destination = fileFor(batch.batchId)
        val temporary = File(destination.parentFile, ".${destination.name}.tmp")
        temporary.writeText(encode(batch).toString())
        try {
            Files.move(temporary.toPath(), destination.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
        } catch (_: AtomicMoveNotSupportedException) {
            Files.move(temporary.toPath(), destination.toPath(), StandardCopyOption.REPLACE_EXISTING)
        }
    }

    private fun fileFor(batchId: String): File {
        requireValidId(batchId)
        return File(batchesDir, "$batchId.json")
    }

    private fun requireValidId(id: String) = require(id.matches(Regex("[A-Za-z0-9_-]+"))) { "Invalid Panoramax identifier" }

    private fun assetFile(relativePath: String): File {
        val file = File(root, relativePath)
        require(!File(relativePath).isAbsolute && file.canonicalPath.startsWith(root.canonicalPath + File.separator)) {
            "Invalid Panoramax image path"
        }
        return file
    }

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
        put("is_favorite", item.isFavorite)
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
        ).also { batch ->
            requireValidId(batch.batchId)
            require(batch.items.map { it.itemId }.distinct().size == batch.items.size) { "Duplicate image records" }
            batch.items.forEach { item ->
                requireValidId(item.itemId)
                require(item.metadata.captureSessionId == batch.captureSessionId && item.metadata.captureId == item.itemId) { "Capture metadata belongs to another session" }
                val expectedDirectory = File(File(batchesDir, batch.batchId), item.itemId).canonicalPath + File.separator
                require(originalFile(item).canonicalPath.startsWith(expectedDirectory) &&
                    thumbnailFile(item).canonicalPath.startsWith(expectedDirectory)) { "Image path does not belong to this capture" }
            }
        }
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
            isFavorite = root["is_favorite"]?.jsonPrimitive?.booleanOrNull ?: false,
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
    val isFavorite: Boolean = false,
)

private fun JsonObject.requiredString(key: String): String = this[key]?.jsonPrimitive?.content?.takeIf { it.isNotBlank() }
    ?: error("Missing $key")
private fun JsonObject.requiredObject(key: String): JsonObject = this[key]?.jsonObject ?: error("Missing $key")
private fun JsonObject.requiredLong(key: String): Long = this[key]?.jsonPrimitive?.longOrNull ?: error("Missing $key")
private fun JsonObject.requiredDouble(key: String): Double = this[key]?.jsonPrimitive?.doubleOrNull ?: error("Missing $key")
