package de.youspeed.android.alpha

import kotlinx.serialization.json.*
import java.net.HttpURLConnection
import java.net.URI
import java.time.Clock
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import kotlin.math.pow

internal data class SignCollectionCapabilities(val metadataBytes: Int, val eventBytes: Int, val disclosures: Map<String, List<String>>, val mediaBytes: Int = 0) {
    companion object {
        const val metadataDisclosure = "youspeed-camera-use-pilot-1"
        const val cropDisclosure = "youspeed-crop-storage-pilot-1"
        fun decode(value: JsonObject): SignCollectionCapabilities {
            val limits = value.getValue("limits").jsonObject
            val metadata = limits.getValue("metadata_bytes").jsonPrimitive.int
            val event = limits.getValue("event_bytes").jsonPrimitive.int
            require(limits["metadata_bytes"] == JsonPrimitive(metadata) && metadata in 1..512 * 1024)
            require(limits["event_bytes"] == JsonPrimitive(event) && event in 1..SignCollectionStore.maximumEventBytes)
            val versions = value.getValue("disclosure_versions").jsonObject.mapValues { (_, v) -> v.jsonArray.map { it.jsonPrimitive.content } }
            require(versions["sign_metadata"]?.contains(metadataDisclosure) == true)
            return SignCollectionCapabilities(metadata, event, versions, (limits["media_bytes"]?.jsonPrimitive?.intOrNull ?: 0).coerceIn(0, 5 * 1024 * 1024))
        }
    }
    fun accepts(claim: JsonElement?): Boolean {
        val objectValue = claim as? JsonObject ?: return false
        val scope = objectValue["scope"]?.jsonPrimitive?.content ?: return false
        val version = objectValue["disclosure_version"]?.jsonPrimitive?.content ?: return false
        return disclosures[scope]?.contains(version) == true
    }
}
internal data class SignCollectionHTTPResponse(val status: Int, val body: JsonObject, val retryAfter: String? = null)
internal fun interface SignCollectionRequesting {
    fun request(path: String, body: String?): SignCollectionHTTPResponse
    fun captureCrop(metadata: String, bytes: ByteArray): SignCollectionHTTPResponse = error("unsupported_capture")
}

/** Anonymous HTTP with bounded replies; redirects/cookies/authentication are not used. */
internal class SignCollectionHTTPClient(baseURL: String = defaultBaseURL) : SignCollectionRequesting {
    companion object { const val defaultBaseURL = "https://live-eu.woladen.de/youspeed/v1" }
    private val base = URI(baseURL).also { require(it.scheme == "https" && it.host != null && it.userInfo == null && it.query == null && it.fragment == null) }.toString().trimEnd('/')
    @Volatile private var active: HttpURLConnection? = null
    fun cancel() { active?.disconnect() }
    override fun request(path: String, body: String?): SignCollectionHTTPResponse {
        if (Thread.currentThread().isInterrupted) throw java.io.InterruptedIOException()
        require(path.isNotEmpty() && '/' !in path && '?' !in path)
        return send(path, if (body == null) "GET" else "POST", body?.toByteArray(Charsets.UTF_8), "application/json")
    }
    override fun captureCrop(metadata: String, bytes: ByteArray): SignCollectionHTTPResponse {
        val json = metadata.toByteArray(Charsets.UTF_8)
        require(json.size in 1..16384 && bytes.size <= 5 * 1024 * 1024)
        val body = java.nio.ByteBuffer.allocate(4 + json.size + bytes.size).putInt(json.size).put(json).put(bytes).array()
        return send("capture-crops", "POST", body, "application/vnd.youspeed.crop")
    }
    private fun send(path: String, method: String, body: ByteArray?, contentType: String): SignCollectionHTTPResponse {
        if (Thread.currentThread().isInterrupted) throw java.io.InterruptedIOException()
        val connection = URI("$base/$path").toURL().openConnection() as HttpURLConnection
        active = connection
        try {
            connection.instanceFollowRedirects = false; connection.connectTimeout = 30_000; connection.readTimeout = 30_000
            connection.requestMethod = method
            connection.setRequestProperty("Content-Type", contentType); connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("Content-Encoding", "identity"); connection.setRequestProperty("Accept-Encoding", "identity")
            if (body != null) {
                val bytes = body; connection.doOutput = true; connection.setFixedLengthStreamingMode(bytes.size)
                connection.outputStream.use { it.write(bytes) }
            }
            val status = connection.responseCode
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val bytes = stream?.use { input ->
                val output = java.io.ByteArrayOutputStream(); val buffer = ByteArray(8192)
                while (output.size() <= 512 * 1024) {
                    val count = input.read(buffer, 0, minOf(buffer.size, 512 * 1024 + 1 - output.size()))
                    if (count < 0) break
                    output.write(buffer, 0, count)
                }
                output.toByteArray()
            } ?: ByteArray(0)
            require(bytes.size <= 512 * 1024) { "invalid_receipt" }
            val value = runCatching { SignCollectionJson.parse(bytes.toString(Charsets.UTF_8)).jsonObject }.getOrNull()
            require(path.startsWith("capture-") || status == 204 || status !in 200..299 || value != null) { "invalid_receipt" }
            return SignCollectionHTTPResponse(status, value ?: JsonObject(emptyMap()), connection.getHeaderField("Retry-After"))
        } finally { connection.disconnect(); active = null }
    }
}

/** Execute on a storage/IO worker, independently of camera processing. */
internal class SignCollectionUploadWorker(private val store: SignCollectionStore, private val client: SignCollectionRequesting, private val clock: Clock = Clock.systemUTC(), private val jitter: () -> Double = { Math.random() }) {
    private var pollOffset = 0
    private var failures = 0
    private var mediaFailures = 0
    private var cachedCapabilities: SignCollectionCapabilities? = null
    private var capabilitiesUntil = 0L
    @Synchronized fun capabilities(): SignCollectionCapabilities {
        cachedCapabilities?.let { if (capabilitiesUntil > clock.millis()) return it }
        val response = client.request("capabilities", null); require(response.status == 200)
        return SignCollectionCapabilities.decode(response.body).also { cachedCapabilities = it; capabilitiesUntil = clock.millis() + 300_000 }
    }
    @Synchronized fun retryDelayMillis(): Long = maxOf(1_000, maxOf(store.transportRetryMillis(), store.cropRetryMillis()) - clock.millis())
    @Synchronized fun runOnce(networkAvailable: Boolean, ordinaryDeliveryAllowed: Boolean): String {
        if (!networkAvailable) return "offline"
        if (store.pendingControls().isEmpty()) {
            if (!ordinaryDeliveryAllowed) return "contribution_paused"
        }
        if (store.transportRetryMillis() > clock.millis()) return "backoff"
        var attemptedBatch: String? = null
        try {
            val capabilities = capabilities()
            for (index in 0 until 2) {
                val pending = store.pendingControls()
                val control = (if (store.deletionIsPending) pending.firstOrNull() else pending.firstOrNull { it.receipt == null && it.response?.get("client_error") == null }) ?: break
                if (control.receipt != null || control.response?.get("client_error") != null) break
                if (control.kind == "consent" && !capabilities.accepts(SignCollectionJson.parse(control.body).jsonObject["collection_authorization"])) { store.quarantineControl(control.id, "disclosure_version_unrecognized"); continue }
                val response = client.request(if (control.kind == "deletion") "observation-deletions" else "consent-events", control.body)
                if (response.status !in 200..299) return handle(response, control = control.id)
                store.applyControlReceipt(control.id, response.body)
            }
            val polls = store.pendingControls().filter { it.receipt != null && it.response?.get("client_error") == null }.toMutableList()
            if (store.deletionIsPending && polls.isNotEmpty()) {
                val barrier = polls.removeAt(0)
                val response = client.request("operation-status", SignCollectionJson.canonical(buildJsonObject { put("operation_receipt", barrier.receipt) }))
                if (response.status !in 200..299) return handle(response, control = barrier.id)
                store.applyControlReceipt(barrier.id, response.body)
            }
            if (polls.isNotEmpty()) {
                repeat(minOf(4, polls.size)) { index ->
                    val control = polls[(pollOffset + index) % polls.size]
                    val response = client.request("operation-status", SignCollectionJson.canonical(buildJsonObject { put("operation_receipt", control.receipt) }))
                    if (response.status !in 200..299) return handle(response, control = control.id)
                    store.applyControlReceipt(control.id, response.body)
                }
                pollOffset = (pollOffset + minOf(4, polls.size)) % polls.size
            }
            if (store.deletionIsPending || store.ordinaryRetryMillis() > clock.millis()) return "deletion_pending"
            if (!ordinaryDeliveryAllowed) return "contribution_paused"
            store.expireCrops()
            var result = "idle"
            val batch = store.prepareBatch(100, capabilities.metadataBytes)
            if (batch != null) {
            val envelope = SignCollectionJson.parse(batch.body).jsonObject
            if (!capabilities.accepts(envelope["collection_authorization"])) return "disclosure_update_required"
            val events = envelope.getValue("events").jsonArray
            if (batch.body.toByteArray(Charsets.UTF_8).size > capabilities.metadataBytes || events.size > 100) { store.splitBatch(batch.id); return "batch_split" }
            val path = mapOf("sighting" to "capture-sightings", "correction" to "capture-corrections", "media_status" to "capture-media-status").getValue(batch.kind)
            attemptedBatch = batch.id
            val response = client.request(path, batch.body)
            attemptedBatch = null
            if (response.status !in 200..299) {
                if (response.status < 500 && response.status !in listOf(408,429) || store.recordBestEffortFailure(batch.id) >= 3) { store.finishBestEffortBatch(batch.id,true); return "metadata_dropped" }
                return handle(response, batch = batch.id)
            }
            store.finishBestEffortBatch(batch.id)
            failures = 0; result = "metadata_sent"
            }
            // Drain a bounded group independently of the camera.
            return try {
                for (index in 0 until 8) {
                    if (Thread.currentThread().isInterrupted) throw java.io.InterruptedIOException()
                    val cropResult = sendCrop(capabilities) ?: break
                    result = cropResult
                    if (cropResult != "crop_sent") break
                }
                result
            } catch (error: Exception) {
                if (Thread.currentThread().isInterrupted) throw error
                mediaFailures++; store.deferCrop(clock.millis() + ((minOf(300.0, 2.0.pow(minOf(mediaFailures, 8))) + jitter()) * 1000).toLong())
                "crop_delivery_unavailable"
            }
        } catch (error: Exception) {
            if (Thread.currentThread().isInterrupted) throw error
            attemptedBatch?.let { if (store.recordBestEffortFailure(it) >= 3) { store.finishBestEffortBatch(it,true); return "metadata_dropped" } }
            failures++; store.deferTransport(clock.millis() + (minOf(300.0, 2.0.pow(minOf(failures, 8))) + jitter()).times(1000).toLong())
            throw error
        }
    }
    private fun sendCrop(capabilities: SignCollectionCapabilities): String? {
        if (store.cropRetryMillis() > clock.millis()) return "backoff"
        val crop = store.nextCrop() ?: return null
        if (crop.bytes.size > capabilities.mediaBytes) { store.finishBestEffortCrop(crop.id,true); return "crop_dropped" }
        try {
            val response = client.captureCrop(crop.metadata,crop.bytes)
            if (response.status in 200..299) { store.finishBestEffortCrop(crop.id); mediaFailures = 0; return "crop_sent" }
            if (response.status < 500 && response.status !in listOf(408,429) || store.recordBestEffortFailure(crop.id) >= 3) { store.finishBestEffortCrop(crop.id,true); return "crop_dropped" }
            return handle(response,crop=crop.id)
        } catch (error: Exception) {
            if (Thread.currentThread().isInterrupted) throw error
            if (store.recordBestEffortFailure(crop.id) >= 3) { store.finishBestEffortCrop(crop.id,true); return "crop_dropped" }
            throw error
        }
    }
    private fun handle(response: SignCollectionHTTPResponse, batch: String? = null, control: String? = null, crop: String? = null): String {
        val raw = response.body["code"]?.jsonPrimitive?.content ?: response.body["error"]?.jsonPrimitive?.content ?: "server_rejected"
        val code = raw.takeIf { Regex("^[a-z][a-z0-9_]{0,79}$").matches(it) } ?: "server_rejected"
        if (response.status == 413 && batch != null) { store.splitBatch(batch); return "batch_split" }
        if (response.status == 409 && code == "deletion_pending") { store.deferOrdinary(clock.millis() + 60_000); return "deletion_pending" }
        if (response.status == 429 || response.status >= 500 || response.status == 408) {
            if (crop != null) mediaFailures++ else failures++
            var delay = minOf(300.0, 2.0.pow(minOf(if (crop != null) mediaFailures else failures, 8)))
            response.retryAfter?.let { header ->
                val seconds = header.toDoubleOrNull()?.takeIf { it.isFinite() }
                    ?: runCatching { (ZonedDateTime.parse(header, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant().toEpochMilli() - clock.millis()) / 1000.0 }.getOrNull()
                if (seconds != null) delay = maxOf(delay, seconds)
            }
            if (crop != null) store.deferCrop(clock.millis() + ((delay + jitter()) * 1000).toLong())
            else store.deferTransport(clock.millis() + ((delay + jitter()) * 1000).toLong())
            return "backoff"
        }
        if (crop != null) store.discardCrop(crop, if (code == "media_expired") "expired" else "missing")
        if (batch != null) store.quarantineBatch(batch, code)
        if (control != null) store.quarantineControl(control, code)
        return "quarantined"
    }
}
