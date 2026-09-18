package de.youspeed.android.alpha

import java.io.File
import java.io.IOException
import java.io.InterruptedIOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.UUID
import java.util.concurrent.Semaphore
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

class PanoramaxHttpException(val statusCode: Int) : Exception("HTTP $statusCode")
class PanoramaxProcessingTimeout : Exception("Panoramax is still processing this upload")
class PanoramaxInvalidResponse : IOException("Invalid Panoramax response")

data class PanoramaxHttpRequest(
    val method: String,
    val path: String,
    val token: String? = null,
    val contentType: String? = null,
    val body: ByteArray? = null,
    val bodyFile: File? = null,
    val origin: String = PanoramaxServiceConfiguration.origin,
) {
    // Never let diagnostic interpolation expose an account token or multipart contents.
    override fun toString(): String = "PanoramaxHttpRequest($method $path)"
}

data class PanoramaxHttpResponse(val statusCode: Int, val body: ByteArray = byteArrayOf()) {
    fun requireSuccess() { if (statusCode !in 200..299) throw PanoramaxHttpException(statusCode) }
}

class PanoramaxRequestCancellation {
    private val cancelled = AtomicBoolean(false)
    private var connection: HttpURLConnection? = null
    val isCancelled: Boolean get() = cancelled.get()
    fun check() { if (isCancelled || Thread.currentThread().isInterrupted) throw InterruptedIOException("Upload stopped") }
    @Synchronized fun attach(value: HttpURLConnection) { check(); connection = value }
    @Synchronized fun detach(value: HttpURLConnection) { if (connection === value) connection = null }
    fun cancel() {
        val active = synchronized(this) { cancelled.set(true); connection }
        active?.disconnect()
    }
}

fun interface PanoramaxUploadTransport {
    fun execute(request: PanoramaxHttpRequest, cancellation: PanoramaxRequestCancellation): PanoramaxHttpResponse
}

fun PanoramaxUploadTransport.execute(request: PanoramaxHttpRequest): PanoramaxHttpResponse =
    execute(request, PanoramaxRequestCancellation())

/** The transport uses the selected HTTPS instance and never follows token-bearing redirects. */
class HttpPanoramaxUploadTransport : PanoramaxUploadTransport {
    override fun execute(request: PanoramaxHttpRequest, cancellation: PanoramaxRequestCancellation): PanoramaxHttpResponse {
        cancellation.check()
        require(request.path.startsWith("/api/") && !request.path.contains("\\") && !request.path.contains(".."))
        val connection = URL(request.origin.trimEnd('/') + request.path).openConnection() as HttpURLConnection
        cancellation.attach(connection)
        try {
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 30_000
            connection.readTimeout = 60_000
            connection.requestMethod = request.method
            connection.setRequestProperty("Accept", "application/json")
            request.token?.let { connection.setRequestProperty("Authorization", "Bearer $it") }
            request.contentType?.let { connection.setRequestProperty("Content-Type", it) }
            val length = request.bodyFile?.length() ?: request.body?.size?.toLong()
            if (length != null) {
                connection.doOutput = true
                connection.setFixedLengthStreamingMode(length)
                connection.outputStream.use { output ->
                    request.bodyFile?.inputStream()?.use { input ->
                        val buffer = ByteArray(1024 * 1024)
                        while (true) {
                            cancellation.check()
                            val read = input.read(buffer)
                            if (read < 0) break
                            output.write(buffer, 0, read)
                        }
                    } ?: request.body?.let(output::write)
                }
            }
            val status = connection.responseCode
            if (status !in 200..299 || request.bodyFile != null) {
                // A file transfer's definitive status is its durable acceptance evidence;
                // neither an irrelevant body-read failure nor cancellation may erase it.
                return PanoramaxHttpResponse(status)
            }
            // Upload success only requires a definitive status. Error text is never logged.
            val stream = if (status in 200..299) connection.inputStream else connection.errorStream
            val bytes = stream?.use { input ->
                val buffer = java.io.ByteArrayOutputStream()
                val chunk = ByteArray(8192)
                while (true) {
                    val read = input.read(chunk)
                    if (read < 0) break
                    if (buffer.size() + read > 4 * 1024 * 1024) throw PanoramaxInvalidResponse()
                    buffer.write(chunk, 0, read)
                }
                buffer.toByteArray()
            } ?: byteArrayOf()
            return PanoramaxHttpResponse(status, bytes)
        } finally {
            cancellation.detach(connection)
            connection.disconnect()
        }
    }
}

data class PanoramaxUploadSetStatus(val id: String, val isReady: Boolean) {
    companion object {
        fun decode(bytes: ByteArray): PanoramaxUploadSetStatus = try {
            val root = Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
            val id = root.getValue("id").jsonPrimitive.content
            require(id.isNotBlank())
            val state = (root["status"] ?: root["state"])?.jsonPrimitive?.content?.lowercase().orEmpty()
            PanoramaxUploadSetStatus(id, root["ready"]?.jsonPrimitive?.booleanOrNull == true || state in setOf("ready", "complete", "completed", "finished"))
        } catch (_: Exception) { throw PanoramaxInvalidResponse() }
    }
}

enum class PanoramaxUploadPhase { PREPARING, UPLOADING, PROCESSING, STOPPING }
data class PanoramaxUploadProgress(val completedItems: Int, val totalItems: Int, val phase: PanoramaxUploadPhase) {
    val fractionCompleted: Double get() = if (totalItems <= 0) 0.0 else (completedItems.toDouble() / totalItems).coerceIn(0.0, 1.0)
}

class PanoramaxUploadClient(
    private val token: String,
    private val temporaryDirectory: File,
    private val transport: PanoramaxUploadTransport = HttpPanoramaxUploadTransport(),
    private val cancellation: PanoramaxRequestCancellation = PanoramaxRequestCancellation(),
    private val requireProcessingAllowed: () -> Unit = {},
    private val uploadLimiter: Semaphore = sharedUploadLimiter,
    private val origin: String = PanoramaxServiceConfiguration.origin,
) {
    private fun execute(request: PanoramaxHttpRequest): PanoramaxHttpResponse {
        cancellation.check()
        requireProcessingAllowed()
        return transport.execute(request, cancellation).also { it.requireSuccess() }
    }

    fun createUploadSet(title: String, estimatedFileCount: Int): PanoramaxUploadSetStatus {
        val payload = buildJsonObject { put("title", title); put("estimated_nb_files", estimatedFileCount.coerceAtLeast(1)) }
        return PanoramaxUploadSetStatus.decode(execute(PanoramaxHttpRequest(
            "POST", "/api/upload_sets", token, "application/json", payload.toString().toByteArray(Charsets.UTF_8),
            origin = origin,
        )).body)
    }

    fun upload(file: File, uploadSetId: String, fileName: String, beforeRequest: () -> Unit = {}) {
        cancellation.check()
        uploadLimiter.acquire()
        try {
            cancellation.check()
            val boundary = "YouSpeed-${UUID.randomUUID()}"
            withMultipartBodyFile(file, fileName, boundary, temporaryDirectory, cancellation) { body ->
                cancellation.check()
                requireProcessingAllowed()
                beforeRequest()
                execute(PanoramaxHttpRequest("POST", "/api/upload_sets/${pathSegment(uploadSetId)}/files", token,
                    "multipart/form-data; boundary=$boundary", bodyFile = body, origin = origin))
            }
        } finally { uploadLimiter.release() }
    }

    fun complete(uploadSetId: String): PanoramaxUploadSetStatus {
        val response = execute(PanoramaxHttpRequest("POST", "/api/upload_sets/${pathSegment(uploadSetId)}/complete", token, origin = origin))
        return if (response.body.isEmpty()) PanoramaxUploadSetStatus(uploadSetId, false) else PanoramaxUploadSetStatus.decode(response.body)
    }

    fun pollUntilReady(uploadSetId: String, attempts: Int = 12, intervalMillis: Long = 2000): PanoramaxUploadSetStatus {
        repeat(attempts.coerceAtLeast(1)) { attempt ->
            val status = PanoramaxUploadSetStatus.decode(execute(PanoramaxHttpRequest("GET", "/api/upload_sets/${pathSegment(uploadSetId)}", token, origin = origin)).body)
            if (status.isReady) return status
            if (attempt + 1 < attempts) Thread.sleep(intervalMillis)
        }
        throw PanoramaxProcessingTimeout()
    }

    companion object {
        private val sharedUploadLimiter = Semaphore(2, true)
        fun pathSegment(value: String): String = URLEncoder.encode(value, Charsets.UTF_8.name()).replace("+", "%20")
        fun durableItemStateAfterUploadFailure(error: Throwable, taskIsCancelled: Boolean): PanoramaxItemState =
            if (taskIsCancelled || error is IOException || error is InterruptedException || error is PanoramaxProcessingTimeout)
                PanoramaxItemState.ABANDONED else PanoramaxItemState.RETRYABLE_ERROR

        fun userMessage(error: Throwable): String = when (error) {
            is PanoramaxHttpException -> "HTTP ${error.statusCode}"
            is PanoramaxProcessingTimeout -> "Panoramax is still processing this upload"
            is InterruptedIOException, is InterruptedException -> "Upload stopped"
            is IOException -> "Connection interrupted; the last image may have reached Panoramax"
            else -> "The operation could not be completed"
        }

        fun <T> withMultipartBodyFile(
            file: File, fileName: String, boundary: String, temporaryDirectory: File,
            cancellation: PanoramaxRequestCancellation = PanoramaxRequestCancellation(), operation: (File) -> T,
        ): T {
            cancellation.check()
            temporaryDirectory.mkdirs()
            val body = File.createTempFile("panoramax-", ".multipart", temporaryDirectory)
            try {
                body.outputStream().use { output ->
                    val safeName = fileName.replace('\r', '_').replace('\n', '_').replace('"', '_')
                    output.write("--$boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"$safeName\"\r\nContent-Type: image/jpeg\r\n\r\n".toByteArray(Charsets.UTF_8))
                    file.inputStream().use { input ->
                        val buffer = ByteArray(1024 * 1024)
                        while (true) {
                            cancellation.check()
                            val count = input.read(buffer)
                            if (count < 0) break
                            output.write(buffer, 0, count)
                        }
                    }
                    cancellation.check()
                    output.write("\r\n--$boundary--\r\n".toByteArray(Charsets.UTF_8))
                }
                cancellation.check()
                return operation(body)
            } finally { body.delete() }
        }
    }
}
