package de.youspeed.android.alpha

import android.content.Context
import android.location.Location
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.serialization.json.*
import java.time.Instant
import java.util.concurrent.Executors
import java.util.concurrent.Future

/** Camera processing never waits for consent, SQLite or the network worker. */
internal class SignCollectionCoordinator(private val context: Context, private val foundation: SignCollectionFoundation) {
    private val preferences = context.getSharedPreferences("youspeed.sign_collection", Context.MODE_PRIVATE)
    var enabled by mutableStateOf(preferences.getBoolean("enabled", true)); private set
    var authorized by mutableStateOf(false); private set
    var cropsAuthorized by mutableStateOf(false); private set
    @Volatile var wantsCropFrame = false; private set
    private var framePending = false
    var consentPresented by mutableStateOf(false); private set
    var status by mutableStateOf("idle"); private set
    var deletions by mutableStateOf<List<Map<String, Boolean>>>(emptyList()); private set
    private val main = Handler(Looper.getMainLooper())
    private val storage = Executors.newSingleThreadExecutor()
    private val network = Executors.newSingleThreadExecutor()
    private val observer = SignCollectionObserver()
    private val client = SignCollectionHTTPClient()
    private val worker = foundation.store.getOrNull()?.let { SignCollectionUploadWorker(it, client) }
    private var upload: Future<*>? = null
    private var cameraActive = false
    private var session: String? = null
    private var generation = 0
    private var privacyChangePending = false
    private var currentEpoch: Int? = null
    @Volatile private var closed = false
    private val storageLifecycle = Any()
    private var pack: AndroidTrafficSignVerifiedPack? = null // Storage executor only.
    private val tick = object : Runnable { override fun run() { if (!closed) { deliver(); main.postDelayed(this, 60_000) } } }
    init { if (worker == null) status = "storage_unavailable"; perform { it.migrateAutomaticCrops(); main.post { deliver() } }; main.post(tick) }
    fun cameraChanged(active: Boolean) {
        val becameActive = active && !cameraActive; cameraActive = active; if (!active) wantsCropFrame = false
        if (becameActive) {
            if (session == null) session = SignCollectionJson.uuid()
            val id = session!!; perform { it.beginSession(id) }; requestConsent()
        }
        if (!active) deliver()
    }
    fun endSession() {
        wantsCropFrame = false; cropsAuthorized = false
        session = null; consentPresented = false; authorized = false; cameraActive = false
        perform { observer.reset(); it.endSession() }; deliver()
    }
    fun modelLoaded(value: AndroidTrafficSignVerifiedPack) { executeStorage { pack = value; observer.reset() } }
    private fun requestConsent() {
        if (!enabled || !cameraActive || consentPresented) return
        val token = generation; val expectedSession = session
        perform { store ->
            val prompt = store.shouldPrompt("sign_metadata", SignCollectionCapabilities.metadataDisclosure)
            main.post { if (generation == token && session == expectedSession && enabled && cameraActive) consentPresented = prompt }
        }
    }
    fun dismissConsent() { consentPresented = false }
    fun decide(granted: Boolean, dontAskAgain: Boolean) {
        consentPresented = false
        privacy { it.decide("sign_metadata", SignCollectionCapabilities.metadataDisclosure, granted, dontAskAgain) }
    }
    fun updateEnabled(value: Boolean) {
        if (value == enabled) return
        enabled = value; preferences.edit().putBoolean("enabled", value).apply()
        invalidateUpload(); authorized = false; cropsAuthorized = false; wantsCropFrame = false; consentPresented = false
        privacy {
            observer.reset()
            if (value) it.allowPromptAgain("sign_metadata") else it.withdraw("sign_metadata", SignCollectionCapabilities.metadataDisclosure)
        }
        if (value) requestConsent()
    }
    fun deleteObservations() {
        invalidateUpload(); authorized = false; cropsAuthorized = false; wantsCropFrame = false; consentPresented = false; session = null
        privacy { observer.reset(); it.requestDeletion() }
    }
    fun clearPendingForDeveloper() { invalidateUpload(); perform { observer.reset(); it.clearPendingForDeveloper() } }
    private fun invalidateUpload() { generation++; client.cancel(); upload?.cancel(true); upload = null }
    private fun privacy(action: (SignCollectionStore) -> Unit) {
        invalidateUpload(); privacyChangePending = true; authorized = false; cropsAuthorized = false; wantsCropFrame = false
        val token = generation
        perform { store ->
            action(store)
            main.post { if (generation == token) { privacyChangePending = false; deliver() } }
        }
    }
    private fun perform(refreshAfter: Boolean = true, action: (SignCollectionStore) -> Unit) {
        if (closed) return
        val store = foundation.store.getOrNull() ?: return
        executeStorage {
            try { action(store) } catch (_: Exception) { main.post { status = "local_operation_failed" } }
            if (refreshAfter) refresh()
        }
    }
    private fun refresh() {
        if (closed) return
        val store = foundation.store.getOrNull() ?: return
        val token = generation
        executeStorage {
            val allowed = store.isAuthorized("sign_metadata", SignCollectionCapabilities.metadataDisclosure)
            val phases = runCatching { store.controlHistory().filter { it.kind == "deletion" }.takeLast(3).map { control ->
                listOf("active_data_removed", "archives_purged", "backup_expiry_complete").associateWith { control.response?.get(it) == JsonPrimitive(true) }
            } }.getOrDefault(emptyList())
            if (allowed) runCatching { store.authorizeAutomaticCrops() }
            val crops = store.isAuthorized("crop_storage", SignCollectionCapabilities.cropDisclosure)
            runCatching { store.expireCrops() }
            val barrier = store.deletionIsPending
            val epoch = store.collectionEpoch
            main.post {
                if (closed || generation != token) return@post
                if (currentEpoch != null && currentEpoch != epoch) { session = null; perform { observer.reset() } }
                currentEpoch = epoch
                authorized = allowed && enabled && !privacyChangePending; deletions = phases
                cropsAuthorized = crops && authorized; wantsCropFrame = cropsAuthorized && cameraActive
                if (cameraActive && session == null && !privacyChangePending && !barrier) {
                    session = SignCollectionJson.uuid(); val id = session!!
                    perform { it.beginSession(id) }; requestConsent()
                }
            }
        }
    }
    fun deliver() {
        if (closed || upload?.isDone == false) return
        val transport = worker ?: return
        val manager = context.getSystemService(ConnectivityManager::class.java)
        val caps = manager.getNetworkCapabilities(manager.activeNetwork)
        val available = caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true
        val allowed = enabled && !privacyChangePending; val token = generation
        upload = network.submit {
            val result = runCatching { transport.runOnce(available, allowed) }.getOrDefault("delivery_unavailable")
            val delay = when (result) {
                "crop_sent", "metadata_sent", "crop_dropped", "metadata_dropped", "batch_split" -> 1_000L
                "backoff", "crop_delivery_unavailable", "delivery_unavailable" -> runCatching { transport.retryDelayMillis() }.getOrDefault(60_000L)
                else -> null
            }
            main.post { if (!closed && generation == token) {
                if (!privacyChangePending) status = result
                upload = null; refresh()
                if (delay != null) main.postDelayed({ if (!closed && generation == token) deliver() }, delay)
            } }
        }
    }
    fun observe(event: TrafficSignRecognitionEvent, detections: List<TrafficSignDetection>, location: Location?, frame: SignCollectionFrame? = null) {
        if (closed || !enabled || !authorized || !cameraActive || event.source != TrafficSignInputSource.LIVE_FRAME || framePending) { frame?.close(); return }
        val id = session ?: run { frame?.close(); return }
        val cropRequested = cropsAuthorized
        framePending = true
        // Snapshot mutable Location data for this frame before asynchronous storage.
        val framePosition = position(location?.let { Location(it) }, event.frameTimestampUtc)
        perform(refreshAfter = false) { store ->
          try {
            if (!store.isAuthorized("sign_metadata", SignCollectionCapabilities.metadataDisclosure)) return@perform
            val modelPack = pack ?: return@perform
            if (modelPack.modelPack.packId != event.packId || !Regex("^[a-f0-9]{64}$").matches(modelPack.manifestSHA256)) return@perform
            val components = event.modelComponents.map { component -> buildJsonObject {
                put("role", component.role); put("artifact_sha256", component.artifactSha256.lowercase()); put("preprocessing_version", component.preprocessingVersion)
                put("calibration_id", component.calibrationId?.let(::JsonPrimitive) ?: JsonNull); put("calibration_sha256", JsonNull)
            } }
            if (components.isEmpty()) return@perform
            val model = buildJsonObject {
                put("pack_id", event.packId); put("pack_version", "manifest-schema-${modelPack.modelPack.schemaVersion}"); put("pack_sha256", modelPack.manifestSHA256)
                put("components", JsonArray(components))
            }
            val country = modelPack.modelPack.countries.firstOrNull { Regex("^[A-Z]{2}$").matches(it) } ?: "unknown"
            val position = framePosition
            val eligible = detections.filter { it.candidate.rawScore.isFinite() && it.candidate.rawScore >= (modelPack.modelPack.classFor(it.candidate.rawClassId)?.threshold ?: modelPack.modelPack.thresholds.provisional) }.take(64)
            val presentationMatches = event.candidate?.let { candidate -> eligible.count { it.candidate.rawLabel == candidate.rawLabel && it.candidate.boundingBox.intersectionOverUnion(candidate.boundingBox) >= 0.5 } } ?: 0
            val mapped = eligible.map { detection ->
                val d = detection.candidate; val box = d.boundingBox
                val mapping = modelPack.modelPack.classFor(d.rawClassId)
                val payload = buildJsonObject {
                    put("schema_version", 1); put("collection_session_id", id); put("observer_version", "sighting-observer-1"); put("source_kind", "detector")
                    put("app", buildJsonObject { put("platform", "android"); put("version", BuildConfig.VERSION_NAME); put("build", BuildConfig.VERSION_CODE.toString()) })
                    put("clock_quality", "device_unverified"); put("vehicle_position", position); put("sign_position", JsonNull)
                    put("classification", buildJsonObject {
                        put("country", country); put("model_label", d.rawLabel); put("canonical_code", JsonNull); put("family", d.semantic.kind.wireValue)
                        put("value", d.semantic.value?.let(::JsonPrimitive) ?: JsonNull); put("unit", d.semantic.unit?.let(::JsonPrimitive) ?: JsonNull)
                        put("role", mapping?.let { if (it.signRole == TrafficSignRole.SUPPLEMENTARY_PLATE) "supplementary" else "primary" } ?: "unknown"); put("mapping_revision", JsonNull); put("mapping_sha256", JsonNull); put("alternatives", JsonArray(emptyList()))
                    })
                    put("scores", buildJsonObject {
                        put("detector_raw", d.proposalRawScore?.let(::JsonPrimitive) ?: if (modelPack.modelPack.pipeline == TrafficSignPipeline.DIRECT_DETECTION) JsonPrimitive(d.rawScore) else JsonNull)
                        put("classifier_raw", d.classifierRawScore?.let(::JsonPrimitive) ?: JsonNull); put("raw_domain", "model_declared_score_0_1"); put("calibrated_confidence", JsonNull); put("track_support", 0)
                    })
                    put("model", model); put("road_context", JsonNull); put("media_refs", JsonArray(emptyList()))
                    put("evidence", buildJsonObject {
                        put("track_id", JsonNull); put("assembly_id", d.assemblyId?.let(::JsonPrimitive) ?: JsonNull); put("analyzed_frames", 0); put("finalization_reason", "qualified_track")
                        put("quality_flags", JsonArray((if (position == JsonNull) listOf("gps_missing", "manifest_schema_version") else listOf("manifest_schema_version")).map(::JsonPrimitive)))
                        put("normalized_box", buildJsonObject { put("x", box.x); put("y", box.y); put("width", box.width); put("height", box.height) })
                    })
                }
                val presentation = event.candidate?.takeIf { presentationMatches == 1 && it.rawLabel == d.rawLabel && it.boundingBox.intersectionOverUnion(box) >= 0.5 }?.trackId
                SignCollectionObserver.Detection(modelPack.manifestSHA256 + ":" + d.rawLabel, listOf(box.x,box.y,box.width,box.height), payload, presentation)
            }
            var cropCount = 0
            observer.observe(event.frameTimestampUtc, mapped, captureCrop = { candidate ->
                if (!cropRequested || frame == null || cropCount >= 4) SignCollectionObserver.CropCaptureResult.SKIPPED
                else runCatching {
                    cropCount++
                    val claim = store.claim("crop_storage", SignCollectionCapabilities.cropDisclosure)
                    val box = listOf("x", "y", "width", "height").zip(candidate.box).toMap()
                    val crop = frame.crop(box)
                    val metadata = crop.metadata(SignCollectionJson.uuid(), candidate.observationId,
                        store.installationId, store.collectionEpoch, "detector", candidate.frameAt, frame.token, "passed", "metadata-strip-1", claim,
                        vehiclePosition = framePosition)
                    store.enqueueAutomaticCrop(metadata, crop.bytes)
                    SignCollectionObserver.CropCaptureResult.STORED
                }.getOrElse {
                    main.post { status = "crop_capture_unavailable" }
                    SignCollectionObserver.CropCaptureResult.FAILED
                }
            }) { observation ->
                store.enqueue("sighting", observation, SignCollectionCapabilities.metadataDisclosure)
            }
          } finally { frame?.close(); main.post { framePending = false } }
        }
    }
    fun freezeCorrection(attempt: String, presentation: String?) { perform { observer.freeze(attempt, presentation) } }
    fun correct(attempt: String, modality: String) { perform { store -> observer.correction(attempt, modality, Instant.now())?.let { store.enqueue("correction", it, SignCollectionCapabilities.metadataDisclosure) } } }
    private fun executeStorage(action: () -> Unit) = synchronized(storageLifecycle) {
        if (!closed) storage.execute(action)
    }
    fun close() {
        synchronized(storageLifecycle) {
            if (closed) return
            closed = true
            storage.shutdown()
        }
        main.removeCallbacks(tick); invalidateUpload(); network.shutdownNow()
    }
    private fun position(fix: Location?, at: Instant): JsonElement {
        if (fix == null || !fix.hasAccuracy() || fix.accuracy !in 0f..100_000f || !fix.latitude.isFinite() || !fix.longitude.isFinite() || fix.latitude !in -90.0..90.0 || fix.longitude !in -180.0..180.0 || kotlin.math.abs(at.toEpochMilli() - fix.time) > 30_000) return JsonNull
        return buildJsonObject {
            put("latitude", fix.latitude); put("longitude", fix.longitude); put("horizontal_accuracy_m", fix.accuracy)
            put("fix_at", Instant.ofEpochMilli(fix.time).toString()); put("frame_fix_delta_ms", at.toEpochMilli()-fix.time)
            put("source", fix.provider ?: "android_location"); put("alignment", "nearest_fix")
            put("course_degrees", if (fix.hasBearing() && fix.bearing.isFinite() && fix.bearing >= 0f && fix.bearing < 360f) JsonPrimitive(fix.bearing) else JsonNull)
            put("course_accuracy_degrees", if (fix.hasBearingAccuracy() && fix.bearingAccuracyDegrees in 0f..180f) JsonPrimitive(fix.bearingAccuracyDegrees) else JsonNull)
        }
    }
}
