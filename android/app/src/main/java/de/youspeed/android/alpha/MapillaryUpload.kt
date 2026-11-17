package de.youspeed.android.alpha

import android.content.Context
import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.exifinterface.media.ExifInterface
import java.io.File
import java.io.IOException
import java.io.InterruptedIOException
import java.net.HttpURLConnection
import java.net.URL
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.concurrent.Executors
import org.json.JSONArray
import org.json.JSONObject

class MapillaryUploadException(val kind: String, val status: Int? = null) : IOException(kind)

data class MapillaryUploadRequest(val url: String, val method: String, val token: String,
    val body: ByteArray? = null, val contentType: String? = null, val headers: Map<String,String> = emptyMap()) {
    override fun toString() = "MapillaryUploadRequest($method ${URL(url).host})"
}

fun interface MapillaryUploadTransport {
    fun execute(request: MapillaryUploadRequest, cancellation: PanoramaxRequestCancellation): PanoramaxHttpResponse
}

class HttpMapillaryUploadTransport : MapillaryUploadTransport {
    override fun execute(request: MapillaryUploadRequest, cancellation: PanoramaxRequestCancellation): PanoramaxHttpResponse {
        val url = URL(request.url)
        require(url.protocol == "https" && url.host in setOf("graph.mapillary.com", "rupload.facebook.com"))
        require(request.token.isNotBlank() && !request.token.contains('\n') && !request.token.contains('\r'))
        cancellation.check()
        val connection = url.openConnection() as HttpURLConnection
        cancellation.attach(connection)
        try {
            connection.instanceFollowRedirects = false
            connection.requestMethod = request.method
            connection.connectTimeout = 30000; connection.readTimeout = 60000
            connection.setRequestProperty("Authorization", "OAuth ${request.token}")
            connection.setRequestProperty("Accept", "application/json")
            request.contentType?.let { connection.setRequestProperty("Content-Type", it) }
            request.headers.forEach { (key,value) -> connection.setRequestProperty(key,value) }
            request.body?.let { body ->
                connection.doOutput = true; connection.setFixedLengthStreamingMode(body.size)
                connection.outputStream.use { stream ->
                    var offset = 0
                    while (offset < body.size) {
                        cancellation.check()
                        val count = minOf(65536,body.size-offset)
                        stream.write(body,offset,count);offset += count
                    }
                }
            }
            val status = connection.responseCode
            if (status !in 200..299) return PanoramaxHttpResponse(status)
            val bytes = connection.inputStream.use { input ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                while (true) {
                    cancellation.check()
                    val count = input.read(buffer);if (count < 0) break
                    if (output.size()+count > 4*1024*1024) throw MapillaryUploadException("response_error")
                    output.write(buffer,0,count)
                }
                output.toByteArray()
            }
            return PanoramaxHttpResponse(status,bytes)
        } finally { cancellation.detach(connection);connection.disconnect() }
    }
}

class MapillaryUploadClient(private val transport: MapillaryUploadTransport = HttpMapillaryUploadTransport()) {
    fun profile(token: String, cancellation: PanoramaxRequestCancellation = PanoramaxRequestCancellation()): Pair<String,String> {
        val profile = request("https://graph.mapillary.com/me?fields=id,username",token,cancellation)
        val id = profile.opt("id") as? String ?: "";val name = profile.opt("username") as? String ?: ""
        if (id.isBlank() || name.isBlank()) throw MapillaryUploadException("account_required")
        return id to name
    }
    fun upload(bytes: ByteArray, key: String, token: String, cancellation: PanoramaxRequestCancellation,
               allowed: () -> Boolean = { true }): String {
        require(key.matches(Regex("[A-Za-z0-9_.-]+")))
        val url = "https://rupload.facebook.com/mapillary_public_uploads/$key"
        var last: Exception = MapillaryUploadException("failed")
        repeat(3) { attempt ->
            cancellation.check()
            if (!allowed()) throw MapillaryUploadException("paused")
            try {
                val value = request(url,token,cancellation).opt("offset")
                if (value !is Number || value.toDouble() != value.toLong().toDouble() || value.toLong() !in 0..bytes.size.toLong())
                    throw MapillaryUploadException("response_error")
                if (!allowed()) throw MapillaryUploadException("paused")
                val offset = value.toInt()
                val result = request(url,token,cancellation,"POST",bytes.copyOfRange(offset,bytes.size),
                    "application/octet-stream",mapOf("Offset" to offset.toString(),"X-Entity-Name" to key))
                return (result.opt("h") as? String)?.takeIf { it.isNotBlank() } ?: throw MapillaryUploadException("response_error")
            } catch (error: MapillaryUploadException) {
                if (error.status == 429 || (error.status ?: 0) >= 500) last = error else throw error
            } catch (error: IOException) {
                cancellation.check(); if (error is InterruptedIOException && error !is java.net.SocketTimeoutException) throw error
                last = error
            }
            if (attempt < 2) Thread.sleep((attempt+1)*1000L)
        }
        throw last
    }
    fun finish(handle: String, token: String, cancellation: PanoramaxRequestCancellation): String {
        val body = JSONObject().put("file_handle",handle).put("file_type","mly_bundle_manifest").toString().toByteArray()
        val result = request("https://graph.mapillary.com/finish_upload",token,cancellation,"POST",body,"application/json")
        val id = result.opt("cluster_id")
        if (id is String && id.isNotBlank()) return id
        if (id is Number && id.toDouble().isFinite() && id.toDouble() > 0 && id.toDouble() == id.toLong().toDouble()) return id.toString()
        throw MapillaryUploadException("response_error")
    }
    private fun request(url: String, token: String, cancellation: PanoramaxRequestCancellation, method: String = "GET",
                        body: ByteArray? = null, type: String? = null, headers: Map<String,String> = emptyMap()): JSONObject {
        if (token.isBlank() || token.contains('\n') || token.contains('\r')) throw MapillaryUploadException("account_required")
        val response = transport.execute(MapillaryUploadRequest(url,method,token,body,type,headers),cancellation)
        if (response.statusCode !in 200..299) throw MapillaryUploadException(
            if (response.statusCode in setOf(401,403)) "account_required" else "http_error",response.statusCode)
        return try { JSONObject(response.body.toString(Charsets.UTF_8)) }
        catch (_: Exception) { throw MapillaryUploadException("response_error") }
    }
}

data class MapillaryPhoto(val itemId: String, val file: File, val metadata: PanoramaxCaptureMetadata)

object MapillaryImageMetadata {
    fun description(metadata: PanoramaxCaptureMetadata): JSONObject {
        if (metadata.validate().isNotEmpty()) throw MapillaryUploadException("image_error")
        return JSONObject().put("MAPLatitude",metadata.location.latitude).put("MAPLongitude",metadata.location.longitude)
            .put("MAPCaptureTime",DateTimeFormatter.ofPattern("yyyy_MM_dd_HH_mm_ss_SSS").withZone(ZoneOffset.UTC).format(metadata.capturedAt))
            .put("MAPSequenceUUID",MapillaryUploadStore.hash(metadata.captureSessionId.toByteArray()))
            .put("MAPGPSAccuracyMeters",metadata.location.accuracyMeters).apply {
                metadata.location.altitudeMeters?.takeIf { it.isFinite() }?.let { put("MAPAltitude",it) }
                metadata.location.headingDegrees?.takeIf { it.isFinite() && it in 0.0..360.0 }?.let {
                    put("MAPCompassHeading",JSONObject().put("TrueHeading",it%360).put("MagneticHeading",it%360))
                }
            }
    }
    fun prepare(photo: MapillaryPhoto, destination: File) {
        val metadata = description(photo.metadata)
        if (!photo.file.isFile || photo.file.length() !in 1..32L*1024*1024 || photo.file.length() != photo.metadata.byteSize ||
            MapillaryUploadStore.hash(photo.file.readBytes()) != photo.metadata.sha256.lowercase()) throw MapillaryUploadException("image_error")
        photo.file.copyTo(destination,overwrite=true)
        ExifInterface(destination).apply {
            setAttribute(ExifInterface.TAG_IMAGE_DESCRIPTION,metadata.toString())
            setAttribute(ExifInterface.TAG_USER_COMMENT,null)
            saveAttributes()
        }
    }
}

data class MapillaryUploadJob(val id: String, val userId: String, val images: MutableList<Image>,
    var manifestHandle: String? = null, var clusterId: String? = null) {
    data class Image(val itemId: String, val name: String, var handle: String? = null)
}

class MapillaryUploadStore(private val root: File) {
    companion object {
        fun hash(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
        fun manifest(job: MapillaryUploadJob): ByteArray = JSONObject().put("version","1").put("upload_type","images")
            .put("image_handles",JSONArray(job.images.map { requireNotNull(it.handle) })).toString().toByteArray()
    }
    @Synchronized fun pending(userId: String): List<MapillaryUploadJob> = jobs(userId).filter { it.clusterId == null }
    @Synchronized fun uploadedItemIds(userId: String): Set<String> = jobs(userId).filter { it.clusterId != null }
        .flatMap { job -> job.images.map { it.itemId } }.toSet()
    private fun jobs(userId: String): List<MapillaryUploadJob> = root.listFiles().orEmpty().mapNotNull { dir ->
        runCatching { decode(File(dir,"job.json").readText()) }.getOrNull()?.takeIf { it.userId == userId }
    }.sortedBy { it.id }
    @Synchronized fun prepare(photos: List<MapillaryPhoto>, userId: String): MapillaryUploadJob {
        require(photos.isNotEmpty())
        val keys = photos.map { "${it.itemId}:${it.metadata.sha256}" }.sorted().joinToString("\n")
        val id = hash("$userId\n$keys".toByteArray());val directory = File(root,id).apply { mkdirs() }
        val existing = File(directory,"job.json")
        if (existing.isFile) return decode(existing.readText()).also { require(it.userId == userId) }
        val uploaded = uploadedItemIds(userId)
        val remaining = photos.filter { it.itemId !in uploaded }
        if (remaining.isEmpty()) throw MapillaryUploadException("already_uploaded")
        val images = remaining.sortedBy { it.metadata.capturedAt }.map { photo ->
            if (Thread.currentThread().isInterrupted) throw InterruptedIOException("Upload stopped")
            val temporary = File(directory,"prepare.tmp")
            try {
                MapillaryImageMetadata.prepare(photo,temporary)
                val name = hash(temporary.readBytes())+".jpg"
                Files.move(temporary.toPath(),File(directory,name).toPath(),StandardCopyOption.REPLACE_EXISTING)
                MapillaryUploadJob.Image(photo.itemId,name)
            } finally { temporary.delete() }
        }.toMutableList()
        return MapillaryUploadJob(id,userId,images).also(::save)
    }
    @Synchronized fun save(job: MapillaryUploadJob) {
        require(job.id.matches(Regex("[a-f0-9]{64}")))
        val directory = File(root,job.id).apply { mkdirs() }
        val json = JSONObject().put("id",job.id).put("user_id",job.userId).put("manifest_handle",job.manifestHandle)
            .put("cluster_id",job.clusterId).put("images",JSONArray(job.images.map {
                JSONObject().put("item_id",it.itemId).put("name",it.name).put("handle",it.handle)
            }))
        val tmp = File(directory,"job.json.tmp");tmp.writeText(json.toString())
        Files.move(tmp.toPath(),File(directory,"job.json").toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING)
    }
    @Synchronized fun bytes(id: String, name: String): ByteArray {
        require(id.matches(Regex("[a-f0-9]{64}")) && name.matches(Regex("[a-f0-9]{64}\\.jpg")))
        val file=File(File(root,id),name)
        if (file.length() !in 1..33L*1024*1024) throw MapillaryUploadException("image_error")
        return file.readBytes().also { if(hash(it)+".jpg" != name) throw MapillaryUploadException("image_error") }
    }
    @Synchronized fun releaseImages(job: MapillaryUploadJob) {
        if (job.clusterId != null) job.images.forEach { File(File(root,job.id),it.name).delete() }
    }
    private fun decode(raw: String): MapillaryUploadJob {
        val json = JSONObject(raw);val images = json.getJSONArray("images")
        return MapillaryUploadJob(json.getString("id"),json.getString("user_id"),(0 until images.length()).map {
            val image = images.getJSONObject(it)
            MapillaryUploadJob.Image(image.getString("item_id"),image.getString("name"),image.optString("handle").takeIf(String::isNotBlank))
        }.toMutableList(),json.optString("manifest_handle").takeIf(String::isNotBlank),json.optString("cluster_id").takeIf(String::isNotBlank))
    }
}

data class MapillaryUploadState(val username: String? = null, val busy: Boolean = false, val uploading: Boolean = false,
    val completed: Int = 0, val total: Int = 0, val status: String = "", val pending: List<MapillaryUploadJob> = emptyList(),
    val uploadedItemIds: Set<String> = emptySet())

class MapillaryUploadWorker(private val client: MapillaryUploadClient, private val store: MapillaryUploadStore) {
    fun submit(job: MapillaryUploadJob, userId: String, token: String, cancellation: PanoramaxRequestCancellation,
               allowed: () -> Boolean = { true }, progress: (Int,Int,String) -> Unit = {_,_,_->}) {
        if (job.userId != userId) throw MapillaryUploadException("account_required")
        if (job.clusterId == null) {
            job.images.forEachIndexed { index,image ->
                cancellation.check();if (!allowed()) throw MapillaryUploadException("paused")
                if (image.handle == null) {
                    progress(index,job.images.size,"uploading")
                    image.handle=client.upload(store.bytes(job.id,image.name),"youspeed_${userId}_${image.name}",token,cancellation,allowed)
                    store.save(job)
                }
                progress(index+1,job.images.size,"uploading")
            }
            cancellation.check();if (!allowed()) throw MapillaryUploadException("paused")
            if (job.manifestHandle == null) {
                val bytes=MapillaryUploadStore.manifest(job)
                job.manifestHandle=client.upload(bytes,"youspeed_${userId}_${MapillaryUploadStore.hash(bytes)}.json",token,cancellation,allowed)
                store.save(job)
            }
            cancellation.check();if (!allowed()) throw MapillaryUploadException("paused")
            progress(job.images.size,job.images.size,"submitting")
            job.clusterId=client.finish(requireNotNull(job.manifestHandle),token,cancellation)
            store.save(job);store.releaseImages(job)
        }
        progress(job.images.size,job.images.size,"submitted")
    }
}

class MapillaryUploadModel(private val context: Context, private val allowed: () -> Boolean,
    private val client: MapillaryUploadClient = MapillaryUploadClient()) : AutoCloseable {
    private val preferences = context.getSharedPreferences("mapillary",Context.MODE_PRIVATE)
    private val credentials = PanoramaxCredentialStore(context)
    private val origin = "https://graph.mapillary.com"
    private val store = MapillaryUploadStore(File(context.noBackupFilesDir,"mapillary-uploads"))
    private val main = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor { runnable -> Thread(runnable,"Mapillary-upload").apply { isDaemon=true } }
    @Volatile private var snapshot = MapillaryUploadState(username = preferences.getString("username",null))
    var state by mutableStateOf(snapshot);private set
    @Volatile private var cancellation: PanoramaxRequestCancellation? = null
    @Volatile private var thread: Thread? = null
    val isUploading get() = snapshot.uploading
    init { worker.execute { refresh() } }
    @Synchronized private fun publish(change: MapillaryUploadState.() -> MapillaryUploadState) {
        snapshot = snapshot.change();val next=snapshot;main.post { state=next }
    }
    fun connect(raw: String) {
        if (snapshot.busy || snapshot.uploading) return
        publish { copy(busy=true) }
        worker.execute {
            try {
                val token=raw.trim();val (id,name)=client.profile(token)
                credentials.save(origin,PanoramaxCredentials(token,id))
                preferences.edit().putString("username",name).putString("user_id",id).apply()
                publish { copy(username=name,status=text("connected")) };refresh()
            } catch (e: Exception) { publish { copy(status=message(e)) } }
            finally { publish { copy(busy=false) } }
        }
    }
    fun disconnect() {
        if (snapshot.busy || snapshot.uploading) return
        worker.execute {
            credentials.delete(origin);preferences.edit().clear().apply()
            publish { copy(username=null,pending=emptyList(),uploadedItemIds=emptySet(),status=text("disconnected")) }
        }
    }
    fun start(photos: List<MapillaryPhoto> = emptyList(), resume: MapillaryUploadJob? = null) {
        if (snapshot.busy || snapshot.uploading || !allowed()) return
        val cancel=PanoramaxRequestCancellation();cancellation=cancel
        publish { copy(uploading=true,completed=0,total=photos.size,status=text("preparing")) }
        worker.execute {
            thread=Thread.currentThread()
            try {
                val credential=credentials.read(origin) ?: throw MapillaryUploadException("account_required")
                val (id,_)=client.profile(credential.token,cancel)
                if (id != credential.tokenId) throw MapillaryUploadException("account_required")
                val job=resume ?: store.prepare(photos,id)
                if (job.userId != id) throw MapillaryUploadException("account_required")
                MapillaryUploadWorker(client,store).submit(job,id,credential.token,cancel,allowed) { done,total,key ->
                    publish { copy(completed=done,total=total,status=text(key)) }
                }
            } catch (error: Exception) { publish { copy(status=if(cancel.isCancelled || error is InterruptedException) text("paused") else message(error)) } }
            finally {
                Thread.interrupted();thread=null;cancellation=null
                refresh();publish { copy(uploading=false) }
            }
        }
    }
    fun stop() { cancellation?.cancel();thread?.interrupt() }
    private fun refresh() {
        val id=preferences.getString("user_id",null)
        publish { copy(pending=if(id==null) emptyList() else store.pending(id),
            uploadedItemIds=if(id==null) emptySet() else store.uploadedItemIds(id)) }
    }
    private fun text(key: String): String = context.getString(when(key) {
        "connected" -> R.string.mapillary_connected
        "disconnected" -> R.string.mapillary_disconnected
        "account_required" -> R.string.mapillary_account_required
        "preparing" -> R.string.mapillary_preparing
        "uploading" -> R.string.mapillary_uploading
        "submitting" -> R.string.mapillary_submitting
        "submitted" -> R.string.mapillary_submitted
        "paused" -> R.string.mapillary_paused
        "image_error" -> R.string.mapillary_image_error
        "response_error" -> R.string.mapillary_response_error
        "http_error" -> R.string.mapillary_http_error
        "already_uploaded" -> R.string.mapillary_already_uploaded
        else -> R.string.mapillary_failed
    })
    private fun message(error: Exception): String {
        val typed=error as? MapillaryUploadException
        return text(typed?.kind ?: "failed") + if(typed?.kind=="http_error") " (${typed.status})" else ""
    }
    override fun close() { stop();worker.shutdownNow() }
}
