package de.youspeed.android.alpha

import android.content.Context
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock
import java.io.FileInputStream
import java.nio.channels.ClosedByInterruptException
import java.nio.channels.FileChannel
import java.nio.file.StandardOpenOption
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
    private class SharedRoot {
        val lock = ReentrantLock()
        val revisions = mutableMapOf<String, Long>()
        val deletedItemIds = mutableMapOf<String, MutableSet<String>>()
    }
    private val shared = synchronized(sharedRoots) { sharedRoots.getOrPut(root.canonicalPath) { SharedRoot() } }
    private val deletedItemIds get() = shared.deletedItemIds
    private data class CachedBatch(
        val batch: PanoramaxBatchRecord, val sequence: Long, val journalCount: Int,
        val journalBytes: Long, val checkpointItems: Int, val checkpointBytes: Long,
        val revision: Long,
    )
    private val cache = LinkedHashMap<String, CachedBatch>(4, 0.75f, true)
    private var statistics = PanoramaxQueueIOStatistics()
    val persistenceStatistics: PanoramaxQueueIOStatistics get() = shared.lock.withLock { statistics.copy() }
    private val journalMaintenanceFailures = mutableSetOf<String>()

    @Volatile var startupCleanupReport = PanoramaxQueueCleanupReport()
        private set
    @Volatile var unreadableRelativePaths: List<String> = emptyList()
        private set

    init {
        check(batchesDir.isDirectory || batchesDir.mkdirs()) { "Could not create local Panoramax queue" }
    }

    fun createBatch(captureSessionId: String, createdAt: Instant = Instant.now()): PanoramaxBatchRecord {
        shared.lock.lock()
        try {
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
        } finally { shared.lock.unlock() }
    }

    fun listBatches(): List<PanoramaxBatchRecord> {
        shared.lock.lock()
        try {
            val failures = mutableListOf<String>()
            val files = checkNotNull(batchesDir.listFiles { file -> file.extension == "json" }) { "Could not read local Panoramax queue" }
            val batches = files.mapNotNull { file ->
                runCatching {
                    read(file.nameWithoutExtension, cacheResult = false)
                }.getOrElse { failures += file.relativeTo(root).path; null }
            }
            unreadableRelativePaths = failures.sorted()
            return batches.sortedByDescending { it.createdAt }
        } finally { shared.lock.unlock() }
    }

    fun thumbnailFile(item: PanoramaxItemRecord): File = assetFile(item.thumbnailPath)

    fun originalFile(item: PanoramaxItemRecord): File = assetFile(item.originalPath)

    internal fun uploadTemporaryDirectory(): File = File(appRoot, "panoramax-multipart")

    /** Runs on the caller's background executor; referenced originals survive missing previews. */
    fun repairMissingThumbnails(): Int {
        shared.lock.lock()
        try {
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
        } finally { shared.lock.unlock() }
    }

    fun getBatch(batchId: String): PanoramaxBatchRecord? {
        shared.lock.lock()
        try { return read(batchId) } finally { shared.lock.unlock() }
    }

    fun addJpeg(
        batchId: String,
        jpeg: File,
        thumbnail: File,
        metadata: PanoramaxCaptureMetadata,
    ): PanoramaxItemRecord {
        shared.lock.lock()
        try {
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
        } finally { shared.lock.unlock() }
    }

    /**
     * Repairs EXIF Photo.UserComment from the durable queue sidecar immediately
     * before upload. The staged JPEG and its hash/size are updated atomically.
     */
    fun prepareOriginalForUpload(batchId: String, itemId: String): File {
        shared.lock.lock()
        try {
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
        } finally { shared.lock.unlock() }
    }

    /** A result may arrive just after its still; attach it to the nearest image in the same live batch. */
    fun attachTrafficSignAnnotation(
        batchId: String,
        draft: PanoramaxTrafficSignAnnotationDraft,
        maximumTimeDelta: java.time.Duration = java.time.Duration.ofSeconds(5),
        eligibleCaptureIds: Set<String>? = null,
        minimumCapturedAt: Instant? = null,
    ): String? {
        shared.lock.lock()
        try {
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
        } finally { shared.lock.unlock() }
    }

    fun updateBatch(batch: PanoramaxBatchRecord) {
        shared.lock.lock()
        try {
            requireNotNull(getBatch(batch.batchId)) { "Unknown Panoramax batch" }
            write(batch.copy(items = batch.items.filterNot { it.itemId in deletedItemIds[batch.batchId].orEmpty() }))
        } finally { shared.lock.unlock() }
    }

    /** Applies a focused change to the latest snapshot in one root transaction. */
    fun mutateBatch(batchId: String, change: (PanoramaxBatchRecord) -> PanoramaxBatchRecord): PanoramaxBatchRecord = shared.lock.withLock {
        val current = requireNotNull(read(batchId)) { "Unknown Panoramax batch" }
        val updated = change(current)
        require(updated.batchId == batchId && updated.captureSessionId == current.captureSessionId)
        write(updated)
        updated
    }

    /** Updates lifecycle state on the latest stored snapshot so concurrently
     * appended capture items cannot be lost by sealing a stale batch value. */
    fun transitionBatch(batchId: String, state: PanoramaxBatchState): PanoramaxBatchRecord {
        shared.lock.lock()
        try {
            val current = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
            val updated = current.copy(state = state)
            write(updated)
            return updated
        } finally { shared.lock.unlock() }
    }

    fun updateItem(batchId: String, itemId: String, state: PanoramaxItemState, remoteId: String? = null): PanoramaxBatchRecord {
        shared.lock.lock()
        try {
            val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
            require(batch.items.any { it.itemId == itemId }) { "Unknown Panoramax item" }
            val updated = batch.copy(items = batch.items.map { item ->
                if (item.itemId == itemId) item.copy(state = state, remoteId = remoteId ?: item.remoteId) else item
            })
            write(updated)
            return updated
        } finally { shared.lock.unlock() }
    }

    fun deleteItem(batchId: String, itemId: String): PanoramaxBatchRecord {
        shared.lock.lock()
        try {
            val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
            val report = deleteItems(batchId, setOf(itemId))
            check(!report.hasFailures) { "Could not remove local images: ${report.failedRelativePaths.joinToString()}" }
            return getBatch(batchId) ?: batch.copy(items = emptyList())
        } finally { shared.lock.unlock() }
    }

    fun deleteBatch(batchId: String) {
        shared.lock.lock()
        try {
            val batch = getBatch(batchId) ?: return
            val report = deleteItems(batchId, batch.items.map { it.itemId }.toSet())
            check(!report.hasFailures) { "Could not remove local images: ${report.failedRelativePaths.joinToString()}" }
        } finally { shared.lock.unlock() }
    }

    fun updateItemFavorite(batchId: String, itemId: String, isFavorite: Boolean): PanoramaxBatchRecord {
        shared.lock.lock()
        try {
            val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
            require(batch.items.any { it.itemId == itemId }) { "Unknown Panoramax item" }
            return batch.copy(items = batch.items.map { if (it.itemId == itemId) it.copy(isFavorite = isFavorite) else it }).also(::write)
        } finally { shared.lock.unlock() }
    }

    /** Explicit selection is the only path from local review to upload approval. */
    fun approveSelection(batchId: String, selectedItemIds: Set<String>): PanoramaxBatchRecord {
        shared.lock.lock()
        try {
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
        } finally { shared.lock.unlock() }
    }

    fun abandonInFlightItems(batchId: String): PanoramaxBatchRecord {
        shared.lock.lock()
        try {
            val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
            val nextState = when (batch.state) {
                PanoramaxBatchState.CREATING_UPLOAD_SET -> if (batch.remoteUploadSetId == null) PanoramaxBatchState.APPROVED else PanoramaxBatchState.PARTIAL
                PanoramaxBatchState.UPLOADING -> PanoramaxBatchState.PARTIAL
                else -> batch.state
            }
            return batch.copy(state = nextState, items = batch.items.map {
                if (it.state == PanoramaxItemState.UPLOADING) it.copy(state = PanoramaxItemState.ABANDONED) else it
            }).also(::write)
        } finally { shared.lock.unlock() }
    }

    /** Local deletion is authoritative, including while a cancelled upload unwinds. */
    fun deleteItems(batchId: String, itemIds: Set<String>): PanoramaxDeletionReport {
        shared.lock.lock()
        try {
            val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
            return deleteItems(batch, itemIds).report
        } finally { shared.lock.unlock() }
    }

    private data class ItemDeletion(val batch: PanoramaxBatchRecord, val report: PanoramaxDeletionReport)

    /** The caller holds the store lock and supplies its latest validated snapshot. */
    private fun deleteItems(batch: PanoramaxBatchRecord, itemIds: Set<String>): ItemDeletion {
        val removed = batch.items.filter { it.itemId in itemIds }
        if (removed.isEmpty()) return ItemDeletion(batch, PanoramaxDeletionReport())
        val updated = batch.copy(items = batch.items.filterNot { it.itemId in itemIds })
        write(updated)
        deletedItemIds.getOrPut(batch.batchId) { mutableSetOf() }.addAll(removed.map { it.itemId })
        val failures = mutableListOf<String>()
        removed.forEach { item ->
            listOf(item.originalPath, item.thumbnailPath).forEach { path ->
                runCatching { val file = assetFile(path); check(!file.exists() || file.delete()) }
                    .onFailure { failures += path }
            }
            runCatching { originalFile(item).parentFile?.let { if (it.listFiles()?.isEmpty() == true) it.delete() } }
        }
        pruneEmptyBatch(updated, failures)
        return ItemDeletion(updated, PanoramaxDeletionReport(removed.map { it.itemId }, failures))
    }

    fun deleteUploadedItems(batchId: String): PanoramaxDeletionReport {
        shared.lock.lock()
        try {
            val batch = requireNotNull(getBatch(batchId)) { "Unknown Panoramax batch" }
            require(batch.state == PanoramaxBatchState.COMPLETE) { "Remote upload set is not complete" }
            return deleteItems(batchId, batch.items.filter { PanoramaxQueuePolicy.isUploaded(it.state) }.map { it.itemId }.toSet())
        } finally { shared.lock.unlock() }
    }

    fun deleteUploadedItemsInCompletedBatches(): PanoramaxDeletionReport {
        shared.lock.lock()
        try {
            val deleted = mutableListOf<String>()
            val failures = mutableListOf<String>()
            listBatches().filter { it.state == PanoramaxBatchState.COMPLETE }.forEach { batch ->
                runCatching { deleteUploadedItems(batch.batchId) }.onSuccess {
                    deleted += it.deletedItemIds; failures += it.failedRelativePaths
                }.onFailure { failures += "batches/${batch.batchId}.json" }
            }
            return PanoramaxDeletionReport(deleted, failures)
        } finally { shared.lock.unlock() }
    }

    fun enforceStorageLimit(maxBytes: Long): PanoramaxDeletionReport {
        shared.lock.lock()
        try {
            if (maxBytes <= 0) return PanoramaxDeletionReport()
            val batches = listBatches()
            data class Candidate(val batchId: String, val item: PanoramaxItemRecord, val bytes: Long)
            val candidates = mutableListOf<Candidate>()
            var total = 0L
            batches.forEach { batch -> batch.items.forEach { item ->
                val bytes = originalFile(item).length() + thumbnailFile(item).length()
                total += bytes
                if (!item.isFavorite && PanoramaxQueuePolicy.canEvictItem(batch.state, item.state)) {
                    candidates += Candidate(batch.batchId, item, bytes)
                }
            } }
            if (total <= maxBytes) return PanoramaxDeletionReport()
            // Retention already owns the store lock. Reuse its validated snapshots;
            // reloading the whole batch for each image repeatedly canonicalizes every
            // remaining asset path and can hold this lock for minutes on a long drive.
            val currentBatches = batches.associateBy { it.batchId }.toMutableMap()
            val deleted = mutableListOf<String>()
            val failures = mutableListOf<String>()
            for (candidate in candidates.sortedBy { it.item.metadata.capturedAt }) {
                if (total <= maxBytes || failures.isNotEmpty()) break
                // Commit one eviction before removing its assets, then stop at the
                // first failure just as on iPhone. A bulk commit would drop later
                // gallery records even when an earlier asset could not be removed.
                runCatching { deleteItems(currentBatches.getValue(candidate.batchId), setOf(candidate.item.itemId)) }
                    .onSuccess { result ->
                        currentBatches[candidate.batchId] = result.batch
                        deleted += result.report.deletedItemIds; failures += result.report.failedRelativePaths
                        if (result.report.deletedItemIds.isNotEmpty()) total -= candidate.bytes
                    }.onFailure { failures += "batches/${candidate.batchId}.json" }
            }
            return PanoramaxDeletionReport(deleted, failures)
        } finally { shared.lock.unlock() }
    }

    /** Call once on a background executor before allowing the first camera session. */
    fun performStartupMaintenanceNow(): PanoramaxQueueCleanupReport {
        shared.lock.lock()
        try {
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
            return PanoramaxQueueCleanupReport(recovered, removedFiles, removedBytes, removedBatches, (failures + journalMaintenanceFailures).distinct().sorted())
                .also { startupCleanupReport = it }
        } finally { shared.lock.unlock() }
    }

    private fun pruneEmptyBatch(batch: PanoramaxBatchRecord, failures: MutableList<String>): Boolean {
        if (batch.items.isNotEmpty() || batch.state == PanoramaxBatchState.CAPTURING ||
            (batch.remoteUploadSetId != null && batch.state != PanoramaxBatchState.COMPLETE)) return false
        val directory = File(batchesDir, batch.batchId)
        if (directory.exists() && directory.listFiles()?.isNotEmpty() != false) return false
        if (directory.exists() && !directory.delete()) { failures += directory.relativeTo(root).path; return false }
        val record = fileFor(batch.batchId)
        if (record.exists() && !record.delete()) { failures += record.relativeTo(root).path; return false }
        if (runCatching { synchronizeDirectory(batchesDir) }.isFailure) { failures += record.relativeTo(root).path; return false }
        changed(batch.batchId)
        cache.remove(batch.batchId)
        val journal = journalDirectory(batch.batchId)
        if (journal.exists() && !journal.deleteRecursively()) failures += journal.relativeTo(root).path
        return true
    }

    private fun read(batchId: String, cacheResult: Boolean = true): PanoramaxBatchRecord? {
        val file = fileFor(batchId)
        if (!file.exists()) { cache.remove(batchId); return null }
        cache[batchId]?.takeIf { it.revision == revision(batchId) }?.let { return it.batch }
        val raw = file.readText()
        statistics = statistics.copy(snapshotReads = statistics.snapshotReads + 1)
        var batch = decode(raw)
        require(batch.batchId == batchId) { "Batch identifier does not match checkpoint" }
        var sequence = json.parseToJsonElement(raw).jsonObject["_queue_checkpoint"]?.jsonPrimitive?.long ?: 0L
        require(sequence >= 0 && sequence < Long.MAX_VALUE)
        val checkpointItems = batch.items.size
        val items = LinkedHashMap<String, PanoramaxItemRecord>()
        batch.items.forEach { items[it.itemId] = it }
        var count = 0
        var bytes = 0L
        val directory = journalDirectory(batchId)
        if (directory.exists()) {
            checkNotNull(directory.listFiles { file -> file.extension == "json" }) { "Could not read queue journal" }
                .sortedBy { it.name }.forEach { file ->
                    val number = file.nameWithoutExtension.toLong()
                    if (number <= sequence) return@forEach
                    val recordBytes = file.readBytes()
                    val record = json.parseToJsonElement(recordBytes.decodeToString()).jsonObject
                    require(record.requiredLong("version") == 1L && record.requiredLong("sequence") == sequence + 1 && number == sequence + 1) { "Incomplete queue journal" }
                    val header = decode(record.requiredObject("header").toString())
                    require(header.batchId == batchId && header.captureSessionId == batch.captureSessionId && header.items.isEmpty()) { "Invalid queue journal header" }
                    record["removed"]!!.jsonArray.forEach { items.remove(it.jsonPrimitive.content) }
                    val upserts = record["upserts"]!!.jsonArray.map { decodeItem(it.jsonObject) }
                    validateItems(header.copy(items = upserts))
                    upserts.forEach { items[it.itemId] = it }
                    record["order"]?.jsonArray?.map { it.jsonPrimitive.content }?.let { order ->
                        require(order.size == items.size && order.toSet() == items.keys) { "Invalid journal item order" }
                        val reordered = order.map { items.getValue(it) }
                        items.clear()
                        reordered.forEach { items[it.itemId] = it }
                    }
                    batch = header
                    sequence = number
                    count++
                    bytes += recordBytes.size
                }
        }
        batch = batch.copy(items = items.values.toList())
        // A gallery scan must not evict hot capture/upload batches.
        if (cacheResult) cache(CachedBatch(batch, sequence, count, bytes, checkpointItems, raw.toByteArray().size.toLong(), revision(batchId)))
        return batch
    }

    private fun revision(batchId: String) = shared.revisions[batchId] ?: 0L
    private fun changed(batchId: String) { shared.revisions[batchId] = revision(batchId) + 1 }
    private fun cache(value: CachedBatch) {
        cache[value.batch.batchId] = value.copy(revision = revision(value.batch.batchId))
        while (cache.size > 4) cache.remove(cache.keys.first())
    }
    private fun journalDirectory(batchId: String) = File(batchesDir, "$batchId.journal")

    private fun write(batch: PanoramaxBatchRecord) {
        val previous = read(batch.batchId)
        val entry = cache[batch.batchId]
        if (previous == null || entry == null) {
            val bytes = checkpointBytes(batch, 0)
            atomicWrite(fileFor(batch.batchId), bytes)
            changed(batch.batchId)
            statistics = statistics.copy(checkpointWrites = statistics.checkpointWrites + 1)
            cache(CachedBatch(batch, 0, 0, 0, batch.items.size, bytes.size.toLong(), revision(batch.batchId)))
            return
        }
        if (batch == previous) return
        val oldItems = previous.items.associateBy { it.itemId }
        val ids = batch.items.map { it.itemId }
        val idSet = ids.toSet()
        require(idSet.size == ids.size) { "Duplicate image records" }
        val replayOrder = previous.items.map { it.itemId }.filter { it in idSet } + ids.filter { it !in oldItems }
        val number = entry.sequence + 1
        val record = buildJsonObject {
            put("version", 1)
            put("sequence", number)
            put("header", encode(batch.copy(items = emptyList())))
            put("removed", buildJsonArray { oldItems.keys.filter { it !in idSet }.forEach { add(JsonPrimitive(it)) } })
            put("upserts", buildJsonArray { batch.items.filter { oldItems[it.itemId] != it }.forEach { add(encode(it)) } })
            if (replayOrder != ids) put("order", buildJsonArray { ids.forEach { add(JsonPrimitive(it)) } })
        }.toString().toByteArray()
        val directory = journalDirectory(batch.batchId)
        val directoryExisted = directory.isDirectory
        check(directoryExisted || directory.mkdirs()) { "Could not create queue journal" }
        if (!directoryExisted) synchronizeDirectory(batchesDir)
        atomicWrite(File(directory, "%020d.json".format(java.util.Locale.ROOT, number)), record)
        changed(batch.batchId)
        statistics = statistics.copy(journalWrites = statistics.journalWrites + 1)
        val updated = entry.copy(batch = batch, sequence = number, journalCount = entry.journalCount + 1, journalBytes = entry.journalBytes + record.size)
        cache(updated)
        if (updated.journalCount >= maxOf(128, updated.checkpointItems) || updated.journalBytes >= maxOf(256 * 1024L, updated.checkpointBytes * 2)) {
            // The mutation is already durable. Maintenance failure cannot undo
            // an accepted network response or turn it into an ambiguous retry.
            runCatching { checkpoint(batch.batchId) }.onFailure { journalMaintenanceFailures += directory.relativeTo(root).path }
        }
    }

    /** Existing JSON shape plus an ignored replay watermark. Replacement is
     * durable before obsolete records are removed, including after a crash. */
    fun checkpoint(batchId: String) = shared.lock.withLock {
        val batch = read(batchId) ?: return@withLock
        val entry = cache.getValue(batchId)
        val bytes = checkpointBytes(batch, entry.sequence)
        atomicWrite(fileFor(batchId), bytes)
        changed(batchId)
        statistics = statistics.copy(checkpointWrites = statistics.checkpointWrites + 1)
        cache(entry.copy(checkpointItems = batch.items.size, checkpointBytes = bytes.size.toLong(), journalCount = 0, journalBytes = 0))
        val directory = journalDirectory(batchId)
        if (directory.exists()) checkNotNull(directory.listFiles()).forEach { file ->
            if (file.extension == "json" && (file.nameWithoutExtension.toLongOrNull() ?: Long.MAX_VALUE) <= entry.sequence) {
                check(file.delete()) { "Could not prune queue journal" }
            }
        }
        journalMaintenanceFailures.remove(directory.relativeTo(root).path)
        Unit
    }

    private fun checkpointBytes(batch: PanoramaxBatchRecord, sequence: Long) =
        JsonObject(encode(batch) + ("_queue_checkpoint" to JsonPrimitive(sequence))).toString().toByteArray()

    private fun atomicWrite(destination: File, bytes: ByteArray) {
        val temporary = File(destination.parentFile, ".${destination.name}.tmp")
        FileOutputStream(temporary).use { output -> output.write(bytes); output.fd.sync() }
        try {
            Files.move(temporary.toPath(), destination.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
        } catch (_: AtomicMoveNotSupportedException) {
            Files.move(temporary.toPath(), destination.toPath(), StandardCopyOption.REPLACE_EXISTING)
        }
        // A failed post-rename sync may still leave a visible new record.
        // Invalidate peers before that barrier to avoid reusing its sequence.
        val parent = requireNotNull(destination.parentFile)
        val batchId = if (parent.extension == "journal") parent.nameWithoutExtension else destination.nameWithoutExtension
        changed(batchId)
        cache.remove(batchId)
        synchronizeDirectory(parent)
        statistics = statistics.copy(metadataBytesWritten = statistics.metadataBytesWritten + bytes.size)
    }

    private fun synchronizeDirectory(directory: File) {
        // Stop interrupts the upload worker. A known server response and its
        // recovery ledger still need a durable rename; restore interruption
        // only after this barrier, so the next network boundary stays blocked.
        var interrupted = Thread.interrupted()
        try {
            while (true) {
                try {
                    FileChannel.open(directory.toPath(), StandardOpenOption.READ).use { it.force(true) }
                    return
                } catch (_: ClosedByInterruptException) {
                    interrupted = true
                    Thread.interrupted()
                }
            }
        } finally {
            if (interrupted) Thread.currentThread().interrupt()
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
            item.metadata.captureReason?.let { put("capture_reason", it) }
            item.metadata.signEvidence?.let { evidence -> put("sign_evidence", JsonArray(evidence.map { e -> buildJsonObject {
                put("track_id", e.trackId); put("model_label", e.modelLabel); put("frame_at", e.frameAt.toString()); put("normalized_box", JsonArray(e.normalizedBox.map(::JsonPrimitive))); put("raw_score", e.rawScore); e.sourceFrameId?.let { put("source_frame_id", it) }
            } })) }
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
            validateItems(batch)
        }
    }

    private fun validateItems(batch: PanoramaxBatchRecord) {
        require(batch.items.map { it.itemId }.toSet().size == batch.items.size) { "Duplicate image records" }
        batch.items.forEach { item ->
                requireValidId(item.itemId)
                require(item.metadata.captureSessionId == batch.captureSessionId && item.metadata.captureId == item.itemId) { "Capture metadata belongs to another session" }
                val expectedDirectory = File(File(batchesDir, batch.batchId), item.itemId).canonicalPath + File.separator
                require(originalFile(item).canonicalPath.startsWith(expectedDirectory) &&
                    thumbnailFile(item).canonicalPath.startsWith(expectedDirectory)) { "Image path does not belong to this capture" }
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
                captureReason = metadata["capture_reason"]?.jsonPrimitive?.content,
                signEvidence = metadata["sign_evidence"]?.jsonArray?.map { e -> e.jsonObject.let {
                    SignCaptureEvidence(it.requiredString("track_id"), it.requiredString("model_label"), Instant.parse(it.requiredString("frame_at")), it.getValue("normalized_box").jsonArray.map { b -> b.jsonPrimitive.double }, it.requiredDouble("raw_score"), it["source_frame_id"]?.jsonPrimitive?.content)
                } },
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
        private val sharedRoots = mutableMapOf<String, SharedRoot>()
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

/** Deterministic IO counters for regression tests and local profiling. */
data class PanoramaxQueueIOStatistics(
    val metadataBytesWritten: Long = 0, val checkpointWrites: Int = 0,
    val journalWrites: Int = 0, val snapshotReads: Int = 0,
)
