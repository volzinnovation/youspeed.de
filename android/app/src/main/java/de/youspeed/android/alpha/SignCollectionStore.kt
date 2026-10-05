package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import kotlinx.serialization.json.*
import java.io.File
import java.time.Clock

internal data class SignCollectionBatch(val id: String, val epoch: Int, val kind: String, val body: String)
internal data class SignCollectionQueuedCrop(val id: String, val metadata: String, val bytes: ByteArray, val handle: String?, val receipt: String?)
internal data class SignCollectionControl(val id: String, val kind: String, val body: String, val receipt: String?, val response: JsonObject?) {
    val isComplete: Boolean get() = response?.let {
        if (kind == "deletion") listOf("active_data_removed", "archives_purged", "backup_expiry_complete").all { phase -> it[phase] == JsonPrimitive(true) }
        else it["state"]?.jsonPrimitive?.content in listOf("recorded", "processing_stop_applied")
    } ?: false
}

/** App-private SQLite WAL/FULL outbox. UUID is attribution, never authentication. */
internal class SignCollectionStore(root: File, val gate: SignCollectionContractGate, private val clock: Clock = Clock.systemUTC()) : AutoCloseable {
    companion object {
        const val maximumEventBytes = 16 * 1024
        private val scopes = setOf("sign_metadata", "crop_storage")
    }
    private val db: SQLiteDatabase
    private var sessionId: String? = null
    private val claims = mutableMapOf<String, SignCollectionClaim>()
    private val promptedScopes = mutableSetOf<String>()
    init {
        require(root.isDirectory || root.mkdirs())
        db = SQLiteDatabase.openDatabase(File(root, "collection.sqlite"), SQLiteDatabase.OpenParams.Builder().addOpenFlags(SQLiteDatabase.CREATE_IF_NECESSARY).setJournalMode("WAL").setSynchronousMode("FULL").build())
        try {
            rows("PRAGMA busy_timeout=5000"); rows("PRAGMA secure_delete=ON")
            require(rows("PRAGMA journal_mode")[0][0] == "wal" && rows("PRAGMA synchronous")[0][0] == "2")
            require(db.version in 0..1)
            transaction {
                sql("CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
                sql("CREATE TABLE IF NOT EXISTS controls(sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,body TEXT NOT NULL,receipt TEXT,response TEXT)")
                sql("CREATE TABLE IF NOT EXISTS identities(id TEXT PRIMARY KEY,epoch INTEGER NOT NULL,kind TEXT NOT NULL,digest TEXT NOT NULL)")
                sql("CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,epoch INTEGER NOT NULL,kind TEXT NOT NULL,auth TEXT NOT NULL,body TEXT NOT NULL,digest TEXT NOT NULL,created REAL NOT NULL,state TEXT NOT NULL DEFAULT 'pending',batch TEXT,not_before REAL NOT NULL DEFAULT 0)")
                sql("CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,epoch INTEGER NOT NULL,kind TEXT NOT NULL,body TEXT NOT NULL,receipt TEXT,response TEXT)")
                sql("CREATE TABLE IF NOT EXISTS media(id TEXT PRIMARY KEY,epoch INTEGER NOT NULL,metadata TEXT NOT NULL,bytes BLOB NOT NULL,created REAL NOT NULL,encoded_hash TEXT NOT NULL,handle TEXT,receipt TEXT,response TEXT)")
                sql("CREATE TABLE IF NOT EXISTS crop_reviews(id TEXT PRIMARY KEY,metadata TEXT NOT NULL,bytes BLOB NOT NULL,auth TEXT NOT NULL,created REAL NOT NULL)")
                if (rows("PRAGMA table_info(media)").none { it[1] == "auth" }) sql("ALTER TABLE media ADD COLUMN auth TEXT NOT NULL DEFAULT ''")
                if (db.version == 1) require(listOf("installation", "epoch", "generation").all { state(it) != null }) { "missing_lifecycle" }
                if (state("installation") == null) save("installation", SignCollectionJson.uuid())
                sql("INSERT OR IGNORE INTO state VALUES('epoch','0')"); sql("INSERT OR IGNORE INTO state VALUES('generation','0')")
                db.version = 1

                require(SignCollectionJson.isUuid(state("installation")!!) && state("epoch")!!.toInt() in 0..Int.MAX_VALUE && state("generation")!!.toInt() in 0..Int.MAX_VALUE)
            }
        } catch (error: Throwable) { db.close(); throw error }
    }
    val installationId: String @Synchronized get() = state("installation")!!
    val collectionEpoch: Int @Synchronized get() = state("epoch")!!.toInt()
    @Synchronized override fun close() { db.close() }

    /** Stable camera/drive entry session, never renewed on resume/interruption. */
    @Synchronized fun beginSession(id: String) {
        require(SignCollectionJson.isUuid(id))
        if (sessionId != id) { sessionId = id; claims.clear(); promptedScopes.clear() }
    }
    @Synchronized fun endSession() { sessionId = null; claims.clear(); promptedScopes.clear() }
    @Synchronized fun allowPromptAgain(scope: String) { save("consent_$scope", null); claims.remove(scope); promptedScopes.remove(scope) }
    @Synchronized fun shouldPrompt(scope: String, disclosure: String): Boolean {
        if (!gate.verified || sessionId == null || state("deletion") != null || scope in promptedScopes) return false
        remembered(scope)?.let { if (it.state != "granted" || it.disclosureVersion == disclosure) return false }
        promptedScopes += scope
        return true
    }
    @Synchronized fun decide(scope: String, disclosure: String, granted: Boolean, dontAskAgain: Boolean): SignCollectionClaim {
        require(sessionId != null && state("deletion") == null && (scope in scopes || (scope.startsWith("processor:") && scope.length <= 160)) && disclosure.length in 1..160) { "consent_required" }
        val claim = transaction {
            val generation = Math.addExact(state("generation")!!.toInt(), 1)
            val result = SignCollectionClaim(scope, disclosure, clock.instant().toString(), generation, if (granted) "granted" else "refused")
            save("authorization_$scope", SignCollectionJson.canonical(result.wire))
            save("generation", generation.toString()); save("consent_$scope", if (dontAskAgain) SignCollectionJson.canonical(result.wire) else null)
            addControl(SignCollectionJson.uuid(), result)
            if (!granted) purge(scope)
            result
        }
        claims[scope] = claim
        return claim
    }
    @Synchronized fun withdraw(scope: String, disclosure: String) {
        require((scope in scopes || (scope.startsWith("processor:") && scope.length <= 160)) && disclosure.length in 1..160)
        transaction {
            val generation = Math.addExact(state("generation")!!.toInt(), 1)
            val claim = SignCollectionClaim(scope, disclosure, clock.instant().toString(), generation, "withdrawn")
            save("authorization_$scope", SignCollectionJson.canonical(claim.wire))
            save("generation", generation.toString()); save("consent_$scope", SignCollectionJson.canonical(claim.wire))
            addControl(SignCollectionJson.uuid(), claim); purge(scope)
        }
        claims.remove(scope)
    }
    private fun remembered(scope: String) = state("consent_$scope")?.let { SignCollectionClaim.decode(SignCollectionJson.parse(it).jsonObject) }
    private fun authorization(scope: String, disclosure: String): SignCollectionClaim {
        require(sessionId != null && state("deletion") == null) { "consent_required" }
        val claim = claims[scope] ?: remembered(scope) ?: error("consent_required")
        require(claim.state == "granted" && claim.disclosureVersion == disclosure) { "consent_required" }
        require(state("authorization_$scope") == SignCollectionJson.canonical(claim.wire)) { "stale_consent" }
        return claim
    }
    @Synchronized fun claim(scope: String, disclosure: String) = authorization(scope, disclosure)
    /** Sign sharing includes all automatic crops; no separate user decision. */
    @Synchronized fun authorizeAutomaticCrops() {
        authorization("sign_metadata", SignCollectionCapabilities.metadataDisclosure)
        if (!isAuthorized("crop_storage", SignCollectionCapabilities.cropDisclosure)) {
            decide("crop_storage", SignCollectionCapabilities.cropDisclosure, true, remembered("sign_metadata") != null)
        }
    }
    @Synchronized fun enqueue(kind: String, event: JsonObject, disclosure: String) = transaction {
        val id = event.getValue("event_id").jsonPrimitive.content
        require(gate.verified && kind in listOf("sighting", "correction", "media_status") && SignCollectionJson.isUuid(id) && event.getValue("schema_version") == JsonPrimitive(1))
        gate.validate(event, kind.replace('_', '-'))
        val claim = authorization("sign_metadata", disclosure)
        enqueueCaptured(kind, event, claim.wire)
    }
    private fun enqueueCaptured(kind: String, event: JsonObject, claim: JsonObject) {
        val id = event.getValue("event_id").jsonPrimitive.content
        gate.validate(event, kind.replace('_', '-'))
        val body = SignCollectionJson.canonical(event); val digest = SignCollectionJson.sha256(body.toByteArray(Charsets.UTF_8))
        require(body.toByteArray(Charsets.UTF_8).size <= maximumEventBytes) { "capacity" }
        rows("SELECT epoch,kind,digest FROM identities WHERE id=?", id).firstOrNull()?.let { require(it == listOf(collectionEpoch.toString(), kind, digest)); return }
        val correction = kind == "correction"
        val stats = rows("SELECT count(*),COALESCE(sum(length(CAST(body AS BLOB))),0) FROM events WHERE " + if (correction) "kind='correction'" else "kind!='correction'")[0]
        require(stats[0].toInt() < (if (correction) 1_000 else 20_000) && stats[1].toInt() + body.toByteArray(Charsets.UTF_8).size <= (if (correction) 5 else 50) * 1024 * 1024) { "capacity" }
        sql("INSERT INTO events(id,epoch,kind,auth,body,digest,created) VALUES(?,?,?,?,?,?,?)", id, collectionEpoch.toString(), kind, SignCollectionJson.canonical(claim), body, digest, (clock.millis() / 1000.0).toString())
        sql("INSERT INTO identities VALUES(?,?,?,?)", id, collectionEpoch.toString(), kind, digest)
    }
    @Synchronized fun prepareBatch(maxEvents: Int = 100, maxBytes: Int = 512 * 1024): SignCollectionBatch? = transaction {
        require(maxEvents > 0 && maxBytes > 0)
        check(state("deletion") == null) { "deletion_pending" }
        val cutoff = (clock.millis() / 1000.0 - 30 * 86400).toString()
        val expired = rows("SELECT count(*) FROM events WHERE created<?", cutoff)[0][0].toInt()
        if (expired > 0) {
            save("expired_events", ((state("expired_events") ?: "0").toInt() + expired).toString())
            rows("SELECT DISTINCT batch FROM events WHERE created<? AND batch IS NOT NULL", cutoff).forEach {
                sql("DELETE FROM batches WHERE id=?", it[0]); sql("UPDATE events SET batch=NULL WHERE batch=?", it[0])
            }
            sql("DELETE FROM events WHERE created<?", cutoff)
        }
        rows("SELECT id,epoch,kind,body FROM batches WHERE response IS NULL ORDER BY rowid LIMIT 1").firstOrNull()?.let { return@transaction SignCollectionBatch(it[0], it[1].toInt(), it[2], it[3]) }
        val ready = (clock.millis() / 1000.0).toString()
        val first = rows("SELECT kind,auth FROM events WHERE state='pending' AND batch IS NULL AND not_before<=? ORDER BY created,id LIMIT 1", ready).firstOrNull() ?: return@transaction null
        val selected = rows("SELECT id,body FROM events WHERE state='pending' AND batch IS NULL AND kind=? AND auth=? AND not_before<=? ORDER BY created,id LIMIT ?", first[0], first[1], ready, minOf(100, maxEvents).toString())
        val events = mutableListOf<JsonElement>(); val ids = mutableListOf<String>()
        val id = SignCollectionJson.uuid(); val epoch = collectionEpoch
        fun envelope() = buildJsonObject {
            put("schema_version", 1); put("batch_id", id); put("installation_id", installationId); put("collection_epoch", epoch)
            put("collection_authorization", SignCollectionJson.parse(first[1])); put("events", JsonArray(events.toList()))
        }
        for (row in selected) {
            events += SignCollectionJson.parse(row[1])
            if (SignCollectionJson.canonical(envelope()).toByteArray(Charsets.UTF_8).size > maxBytes) {
                events.removeAt(events.lastIndex); require(events.isNotEmpty()) { "capacity" }; break
            }
            ids += row[0]
        }
        val body = SignCollectionJson.canonical(envelope())
        sql("INSERT INTO batches(id,epoch,kind,body) VALUES(?,?,?,?)", id, epoch.toString(), first[0], body)
        ids.forEach { sql("UPDATE events SET batch=? WHERE id=?", id, it) }
        SignCollectionBatch(id, epoch, first[0], body)
    }
    @Synchronized fun transportRetryMillis() = state("transport_retry")?.toLong() ?: 0L
    @Synchronized fun deferTransport(untilMillis: Long) = save("transport_retry", untilMillis.toString())
    @Synchronized fun ordinaryRetryMillis() = state("ordinary_retry")?.toLong() ?: 0L
    @Synchronized fun cropRetryMillis() = state("crop_retry")?.toLong() ?: 0L
    @Synchronized fun deferCrop(untilMillis: Long) = save("crop_retry", untilMillis.toString())
    @Synchronized fun deferOrdinary(untilMillis: Long) = save("ordinary_retry", untilMillis.toString())
    val deletionIsPending: Boolean @Synchronized get() = state("deletion") != null
    @Synchronized fun quarantineBatch(id: String, code: String) = transaction { finishFailedBatch(id, code) }
    @Synchronized fun quarantineControl(id: String, code: String) = transaction {
        require(Regex("^[a-z][a-z0-9_]{0,79}$").matches(code))
        val operation = controlStatus(id) ?: error("invalid_control")
        val response = JsonObject((operation.response ?: buildJsonObject {}) + ("client_error" to JsonPrimitive(code)))
        sql("UPDATE controls SET response=? WHERE id=?", SignCollectionJson.canonical(response), id)
    }
    private fun finishFailedBatch(id: String, code: String) {
        require(Regex("^[a-z][a-z0-9_]{0,79}$").matches(code))
        sql("UPDATE events SET state='quarantined',batch=NULL WHERE batch=?", id)
        sql("UPDATE batches SET body='',response=? WHERE id=? AND response IS NULL", SignCollectionJson.canonical(buildJsonObject { put("transport_error", code) }), id)
    }
    /** A 413 replaces batch IDs; event IDs, epoch and captured authorization survive. */
    @Synchronized fun splitBatch(id: String) = transaction {
        val row = rows("SELECT epoch,kind,body FROM batches WHERE id=? AND response IS NULL", id).firstOrNull() ?: return@transaction
        val envelope = SignCollectionJson.parse(row[2]).jsonObject
        val events = envelope.getValue("events").jsonArray
        if (events.size <= 1) { finishFailedBatch(id, "request_too_large"); return@transaction }
        val middle = events.size / 2
        listOf(events.take(middle), events.drop(middle)).forEach { part ->
            val next = SignCollectionJson.uuid()
            val body = SignCollectionJson.canonical(JsonObject(envelope + mapOf("batch_id" to JsonPrimitive(next), "events" to JsonArray(part))))
            sql("INSERT INTO batches(id,epoch,kind,body) VALUES(?,?,?,?)", next, row[0], row[1], body)
            part.forEach { sql("UPDATE events SET batch=? WHERE id=? AND batch=?", next, it.jsonObject.getValue("event_id").jsonPrimitive.content, id) }
        }
        sql("UPDATE batches SET body='',response=? WHERE id=?", SignCollectionJson.canonical(buildJsonObject { put("transport_error", "request_too_large") }), id)
    }
    @Synchronized fun applyBatchReceipt(receipt: JsonObject) = transaction {
        val id = receipt.getValue("batch_id").jsonPrimitive.content
        val row = rows("SELECT epoch,response FROM batches WHERE id=?", id).firstOrNull() ?: error("invalid_receipt")
        val token = receipt.getValue("operation_receipt").jsonPrimitive.content
        require(receipt.getValue("schema_version") == JsonPrimitive(1) && receipt.getValue("collection_epoch") == JsonPrimitive(row[0].toInt()) && receipt.getValue("durability").jsonPrimitive.content == "live_eu_committed" && token.length in 1..128)
        val encoded = SignCollectionJson.canonical(receipt)
        if (row[1].isNotEmpty()) { require(row[1] == encoded); return@transaction }
        val expected = rows("SELECT id FROM events WHERE batch=?", id).map { it[0] }.toSet()
        val results = receipt.getValue("results").jsonArray.map { it.jsonObject }
        val ids = results.map { it.getValue("event_id").jsonPrimitive.content }
        require(ids.toSet() == expected && ids.size == ids.toSet().size) { "invalid_receipt" }
        results.forEach {
            val status = it.getValue("status").jsonPrimitive.content
            require(status in listOf("accepted", "duplicate", "rejected", "retry_later") && it.getValue("retryable") == JsonPrimitive(status == "retry_later"))
        }
        results.forEach {
            val eventId = it.getValue("event_id").jsonPrimitive.content
            when (it.getValue("status").jsonPrimitive.content) {
                "accepted", "duplicate" -> sql("DELETE FROM events WHERE id=?", eventId)
                "retry_later" -> {
                    val time = clock.millis() / 1000.0
                    val retryAt = if (it["code"]?.jsonPrimitive?.content == "daily_quota") (kotlin.math.floor(time / 86400) + 1) * 86400 else time + 60
                    sql("UPDATE events SET batch=NULL,not_before=? WHERE id=?", retryAt.toString(), eventId)
                }
                else -> sql("UPDATE events SET state='quarantined',batch=NULL WHERE id=?", eventId)
            }
        }
        sql("UPDATE batches SET body='',receipt=?,response=? WHERE id=?", token, encoded, id)
    }
    @Synchronized fun requestDeletion(): String = transaction {
        state("deletion")?.let { return@transaction it }
        val id = SignCollectionJson.uuid()
        val body = SignCollectionJson.canonical(buildJsonObject { put("installation_id", installationId); put("collection_epoch", collectionEpoch); put("deletion_request_id", id) })
        sql("INSERT INTO controls(id,kind,body) VALUES(?,'deletion',?)", id, body)
        save("deletion", id); purge("sign_metadata"); sql("DELETE FROM state WHERE key LIKE 'consent_%' OR key LIKE 'authorization_%'")
        claims.clear(); id
    }
    /** Intake is not completion: expose every unfinished operation for fair polling and phase UI. */
    @Synchronized fun pendingControls(): List<SignCollectionControl> {
        val pending = rows("SELECT id,kind,body,receipt,response FROM controls ORDER BY sequence").map(::control).filterNot { it.isComplete }
        val barrier = state("deletion")
        val remaining = pending.filter { it.id != barrier }
        return pending.filter { it.id == barrier } + remaining.filter { it.receipt == null } + remaining.filter { it.receipt != null }
    }
    @Synchronized fun nextControl(): SignCollectionControl? = pendingControls().firstOrNull()
    /** Completed operations remain readable after restart and later deletions. */
    @Synchronized fun controlStatus(id: String): SignCollectionControl? = rows("SELECT id,kind,body,receipt,response FROM controls WHERE id=?", id).firstOrNull()?.let(::control)
    @Synchronized fun controlHistory(): List<SignCollectionControl> = rows("SELECT id,kind,body,receipt,response FROM controls ORDER BY sequence").map(::control)
    @Synchronized fun isAuthorized(scope: String, disclosure: String) = runCatching { authorization(scope, disclosure) }.isSuccess
    private fun control(row: List<String>) = SignCollectionControl(row[0], row[1], row[2], row[3].ifEmpty { null }, row[4].takeIf { it.isNotEmpty() }?.let { SignCollectionJson.parse(it).jsonObject })
    @Synchronized fun applyControlReceipt(id: String, response: JsonObject) = transaction {
        val operation = controlStatus(id) ?: error("invalid_receipt")
        val token = response.getValue("operation_receipt").jsonPrimitive.content
        require(token.length in 1..128 && (operation.receipt == null || operation.receipt == token))
        if (operation.kind == "deletion") {
            val requestedEpoch = SignCollectionJson.parse(operation.body).jsonObject.getValue("collection_epoch").jsonPrimitive.int
            val next = response.getValue("next_collection_epoch").jsonPrimitive.int
            require(response.getValue("next_collection_epoch") == JsonPrimitive(next) && next.toLong() == requestedEpoch.toLong() + 1 && next >= 0)
            val removed = response.getValue("active_data_removed").jsonPrimitive.boolean
            require(response.getValue("active_data_removed") == JsonPrimitive(removed))
            require(response.getValue("state").jsonPrimitive.content == if (removed) "active_data_removed" else "deletion_pending")
            for (phase in listOf("active_data_removed", "archives_purged", "backup_expiry_complete")) {
                response[phase]?.let { require(it == JsonPrimitive(true) || it == JsonPrimitive(false)) }
                if (operation.response?.get(phase) == JsonPrimitive(true)) require(response[phase] == JsonPrimitive(true))
                if (phase != "active_data_removed" && response[phase] == JsonPrimitive(true)) require(removed)
            }
            val alreadyRemoved = operation.response?.get("active_data_removed") == JsonPrimitive(true)
            if (alreadyRemoved) require(collectionEpoch >= next)
            else require(state("deletion") == id && collectionEpoch == requestedEpoch)
            if (removed && !alreadyRemoved) {
                save("epoch", next.toString()); save("deletion", null)
                // Keep acknowledged operations for polling/history; never replay unsent old consent.
                sql("DELETE FROM controls WHERE kind='consent' AND receipt IS NULL")
                claims.clear(); sessionId = null; promptedScopes.clear()
            }
        } else {
            val status = response.getValue("state").jsonPrimitive.content
            require(status in listOf("recorded", "processing_stop_pending", "processing_stop_applied"))
            if (operation.isComplete) require(operation.response?.get("state") == response["state"])
        }
        sql("UPDATE controls SET receipt=?,response=? WHERE id=?", token, SignCollectionJson.canonical(response), id)
    }
    /** Developer diagnostics only: preserve privacy controls. */
    @Synchronized fun clearPendingForDeveloper() = transaction { purge("sign_metadata") }
    @Synchronized fun pendingCount() = rows("SELECT count(*) FROM events")[0][0].toInt()
    @Synchronized fun expiredEventCount() = (state("expired_events") ?: "0").toInt()
    @Synchronized fun expiredCropCount() = (state("expired_crops") ?: "0").toInt()
    @Synchronized fun enqueueCrop(metadata: JsonObject, bytes: ByteArray, disclosure: String, processorDisclosure: String? = null) = transaction {
        insertCrop(metadata, bytes, disclosure, processorDisclosure)
    }
    /** Automatic, separately consented delivery; retain the capture-time metadata grant. */
    @Synchronized fun enqueueAutomaticCrop(metadata: JsonObject, bytes: ByteArray) = transaction {
        val claim = authorization("sign_metadata", SignCollectionCapabilities.metadataDisclosure)
        require(metadata["privacy_preflight"] == JsonPrimitive("passed"))
        insertCrop(metadata, bytes, SignCollectionCapabilities.cropDisclosure, null)
        sql("UPDATE media SET auth=? WHERE id=?", SignCollectionJson.canonical(claim.wire), metadata.getValue("crop_id").jsonPrimitive.content)
    }
    /** Upgrade the former local review queue using its captured grants, without a new session. */
    @Synchronized fun migrateAutomaticCrops() {
        expireCrops()
        transaction {
            if (state("deletion") != null) return@transaction
            while (true) {
                val row = rows("SELECT id,metadata,auth,created FROM crop_reviews ORDER BY created LIMIT 1").firstOrNull() ?: break
                val bytes = cropReviews().first().second
                val metadata = JsonObject(SignCollectionJson.parse(row[1]).jsonObject + mapOf(
                    "privacy_preflight" to JsonPrimitive("passed"), "redaction_version" to JsonPrimitive("metadata-strip-1")))
                sql("DELETE FROM crop_reviews WHERE id=?", row[0])
                insertCrop(metadata, bytes, SignCollectionCapabilities.cropDisclosure, null, captured = true)
                sql("UPDATE media SET auth=?,created=? WHERE id=?", row[2], row[3], row[0])
            }
        }
    }
    private fun insertCrop(metadata: JsonObject, bytes: ByteArray, disclosure: String, processorDisclosure: String?, captured: Boolean = false) {
        gate.validate(metadata, "crop")
        require(metadata.getValue("installation_id").jsonPrimitive.content == installationId && metadata.getValue("collection_epoch") == JsonPrimitive(collectionEpoch))
        require(metadata.getValue("byte_length") == JsonPrimitive(bytes.size) && metadata.getValue("encoded_sha256").jsonPrimitive.content == SignCollectionJson.sha256(bytes))
        if (!captured) {
            val claim = authorization("crop_storage", disclosure)
            require(SignCollectionJson.canonical(metadata.getValue("collection_authorization")) == SignCollectionJson.canonical(claim.wire))
        }
        metadata["processor_authorization"]?.takeIf { it !== JsonNull }?.let {
            val scope = it.jsonObject.getValue("scope").jsonPrimitive.content
            require(scope.startsWith("processor:") && processorDisclosure != null)
            val authorized = authorization(scope, processorDisclosure)
            require(SignCollectionJson.canonical(it) == SignCollectionJson.canonical(authorized.wire))
        }
        val id = metadata.getValue("crop_id").jsonPrimitive.content; val text = SignCollectionJson.canonical(metadata); val digest = SignCollectionJson.digest(metadata)
        rows("SELECT epoch,kind,digest FROM identities WHERE id=?", id).firstOrNull()?.let { require(it == listOf(collectionEpoch.toString(), "crop", digest)); return }
        val size = rows("SELECT (SELECT COALESCE(sum(length(bytes)),0) FROM media)+(SELECT COALESCE(sum(length(bytes)),0) FROM crop_reviews)")[0][0].toLong()
        require(size + bytes.size <= 1024L * 1024 * 1024) { "capacity" }
        db.execSQL("INSERT INTO media(id,epoch,metadata,created,encoded_hash,bytes) VALUES(?,?,?,?,?,?)", arrayOf(id, collectionEpoch, text, clock.millis() / 1000.0, SignCollectionJson.sha256(bytes), bytes))
        sql("INSERT INTO identities VALUES(?,?,?,?)", id, collectionEpoch.toString(), "crop", digest)
    }
    /** Local-only review. No privacy assertion is sent until explicit approval. */
    @Synchronized fun stageCrop(metadata: JsonObject, bytes: ByteArray) = transaction {
        check(state("deletion") == null)
        val cropClaim = authorization("crop_storage", SignCollectionCapabilities.cropDisclosure)
        val metadataClaim = authorization("sign_metadata", SignCollectionCapabilities.metadataDisclosure)
        require(metadata["collection_authorization"] == cropClaim.wire && metadata["installation_id"] == JsonPrimitive(installationId) && metadata["collection_epoch"] == JsonPrimitive(collectionEpoch))
        require(metadata["encoded_sha256"] == JsonPrimitive(SignCollectionJson.sha256(bytes)) && metadata["byte_length"] == JsonPrimitive(bytes.size))
        gate.validate(JsonObject(metadata + ("privacy_preflight" to JsonPrimitive("user_reviewed"))), "crop")
        val size = rows("SELECT (SELECT COALESCE(sum(length(bytes)),0) FROM media)+(SELECT COALESCE(sum(length(bytes)),0) FROM crop_reviews)")[0][0].toLong()
        require(size + bytes.size <= 1024L * 1024 * 1024 && cropReviewCount() < 500) { "capacity" }
        db.execSQL("INSERT INTO crop_reviews(id,metadata,bytes,auth,created) VALUES(?,?,?,?,?)", arrayOf(metadata.getValue("crop_id").jsonPrimitive.content, SignCollectionJson.canonical(JsonObject(metadata - "privacy_preflight")), bytes, SignCollectionJson.canonical(metadataClaim.wire), clock.millis()/1000.0))
    }
    @Synchronized fun cropReviewCount() = rows("SELECT count(*) FROM crop_reviews")[0][0].toInt()
    @Synchronized fun cropReviews(): List<Pair<String, ByteArray>> = db.rawQuery("SELECT id,bytes FROM crop_reviews ORDER BY created LIMIT 1", null).use { cursor ->
        buildList { while (cursor.moveToNext()) add(cursor.getString(0) to cursor.getBlob(1)) }
    }
    @Synchronized fun reviewCrop(id: String, approved: Boolean) = transaction {
        check(state("deletion") == null)
        val row = rows("SELECT metadata,auth,created FROM crop_reviews WHERE id=?", id).firstOrNull() ?: error("consent_required")
        if (approved) {
            require(row[2].toDouble() >= clock.millis()/1000.0 - 7*86400)
            val bytes = cropReviews().first { it.first == id }.second
            val metadata = JsonObject(SignCollectionJson.parse(row[0]).jsonObject + ("privacy_preflight" to JsonPrimitive("user_reviewed")))
            sql("DELETE FROM crop_reviews WHERE id=?", id)
            insertCrop(metadata, bytes, SignCollectionCapabilities.cropDisclosure, null, captured = true)
            sql("UPDATE media SET auth=?,created=? WHERE id=?", row[1], row[2], id)
        } else sql("DELETE FROM crop_reviews WHERE id=?", id)
        privacyCheckpointNeeded = true
    }
    private fun mediaStatus(metadata: String, auth: String, status: String) {
        if (auth.isEmpty()) return // Older foundation fixtures have no captured metadata grant.
        val crop = SignCollectionJson.parse(metadata).jsonObject
        val event = buildJsonObject {
            put("schema_version", 1); put("event_id", SignCollectionJson.uuid()); put("created_at", clock.instant().toString())
            put("crop_id", crop.getValue("crop_id")); put("observation_id", crop.getValue("observation_id")); put("status", status); put("superseded_by", JsonNull)
        }
        enqueueCaptured("media_status", event, SignCollectionJson.parse(auth).jsonObject)
    }
    @Synchronized fun discardCrop(id: String, status: String = "missing") = transaction {
        rows("SELECT metadata,auth FROM media WHERE id=? AND length(bytes)>0", id).firstOrNull()?.let { row ->
            mediaStatus(row[0], row[1], status)
            sql("UPDATE media SET bytes=X'',metadata='',handle=NULL,response=? WHERE id=?", SignCollectionJson.canonical(buildJsonObject { put("client_error", status) }), id)
            privacyCheckpointNeeded = true
        }
    }
    @Synchronized fun expireCrops() {
        val cutoff = (clock.millis()/1000.0 - 7*86400).toString()
        val expired = rows("SELECT id FROM media WHERE length(bytes)>0 AND created<?", cutoff)
        expired.forEach { discardCrop(it[0], "expired") }
        transaction {
            val reviews = rows("SELECT count(*) FROM crop_reviews WHERE created<?", cutoff)[0][0].toInt()
            sql("DELETE FROM crop_reviews WHERE created<?", cutoff)
            save("expired_crops", ((state("expired_crops") ?: "0").toInt() + expired.size + reviews).toString())
            if (reviews > 0) privacyCheckpointNeeded = true
        }
    }
    @Synchronized fun nextCrop(): SignCollectionQueuedCrop? {
        check(state("deletion") == null) { "deletion_pending" }
        return db.rawQuery("SELECT id,metadata,bytes,handle,receipt FROM media WHERE length(bytes)>0 AND created>=? ORDER BY created,id LIMIT 1", arrayOf((clock.millis() / 1000.0 - 7 * 86400).toString())).use { cursor ->
            if (!cursor.moveToFirst()) null else SignCollectionQueuedCrop(cursor.getString(0), cursor.getString(1), cursor.getBlob(2), cursor.getString(3), cursor.getString(4))
        }
    }
    @Synchronized fun applyCropReceipt(id: String, response: JsonObject) = transaction {
        val row = rows("SELECT encoded_hash,receipt,metadata,auth FROM media WHERE id=?", id).firstOrNull() ?: error("invalid_receipt")
        val token = response.getValue("operation_receipt").jsonPrimitive.content
        require(response.getValue("sha256").jsonPrimitive.content == row[0] && token.length in 1..128 && (row[1].isEmpty() || row[1] == token))
        when (response.getValue("state").jsonPrimitive.content) {
            "reserved" -> {
                val handle = response.getValue("handle").jsonPrimitive.content; require(handle.length in 1..128)
                sql("UPDATE media SET handle=?,receipt=?,response=? WHERE id=?", handle, token, SignCollectionJson.canonical(response), id)
            }
            "media_durable" -> {
                require(response.getValue("durability").jsonPrimitive.content == "live_eu_committed")
                if (row[2].isNotEmpty()) { mediaStatus(row[2], row[3], "linked"); privacyCheckpointNeeded = true }
                sql("UPDATE media SET bytes=X'',metadata='',handle=NULL,receipt=?,response=? WHERE id=?", token, SignCollectionJson.canonical(response), id)
            }
            else -> error("invalid_receipt")
        }
    }
    private var privacyCheckpointNeeded = false
    private fun purge(scope: String) {
        privacyCheckpointNeeded = true
        if (scope == "sign_metadata") { sql("DELETE FROM events"); sql("DELETE FROM batches") }
        if (!scope.startsWith("processor:")) { sql("DELETE FROM media"); sql("DELETE FROM crop_reviews") }
        else rows("SELECT id,metadata FROM media WHERE metadata!=''").forEach { row ->
            val auth = SignCollectionJson.parse(row[1]).jsonObject["processor_authorization"]
            if (auth is JsonObject && auth["scope"]?.jsonPrimitive?.content == scope) sql("DELETE FROM media WHERE id=?", row[0])
        }
    }
    private fun addControl(id: String, claim: SignCollectionClaim) {
        val body = SignCollectionJson.canonical(buildJsonObject { put("schema_version", 1); put("event_id", id); put("installation_id", installationId); put("collection_epoch", collectionEpoch); put("collection_authorization", claim.wire) })
        sql("INSERT INTO controls(id,kind,body) VALUES(?,'consent',?)", id, body)
    }
    private fun state(key: String) = rows("SELECT value FROM state WHERE key=?", key).firstOrNull()?.first()
    private fun save(key: String, value: String?) { if (value == null) sql("DELETE FROM state WHERE key=?", key) else sql("INSERT OR REPLACE INTO state VALUES(?,?)", key, value) }
    private fun sql(query: String, vararg args: String) { db.execSQL(query, args) }
    private fun rows(query: String, vararg args: String): List<List<String>> = db.rawQuery(query, args).use { cursor ->
        buildList { while (cursor.moveToNext()) add((0 until cursor.columnCount).map { cursor.getString(it) ?: "" }) }
    }
    private fun <T> transaction(body: () -> T): T {
        db.beginTransaction()
        val result: T
        try { result = body(); db.setTransactionSuccessful() } catch (error: Throwable) { privacyCheckpointNeeded = false; throw error } finally { db.endTransaction() }
        if (privacyCheckpointNeeded) { rows("PRAGMA wal_checkpoint(TRUNCATE)"); privacyCheckpointNeeded = false }
        return result
    }
}
