package de.youspeed.android.alpha

import android.content.Context
import android.content.SharedPreferences
import android.database.sqlite.SQLiteDatabase
import java.io.File
import java.security.MessageDigest
import java.time.Clock
import java.util.UUID
import org.json.JSONArray
import org.json.JSONObject

enum class LocalObservationModality(val rawValue: String) {
    VOICE_COMMAND("voice_command"),
    LOCK_CURRENT_SPEED("lock_current_speed"),
}

enum class LocalObservationIntentType(val rawValue: String) {
    SET_MAXSPEED("set_maxspeed"),
    MAP_INCONSISTENCY("map_inconsistency"),
    LOCK_SPEED_SNAPSHOT("lock_speed_snapshot"),
}

enum class LocalObservationState(val rawValue: String) {
    LOCAL_ONLY("local_only"),
    NEEDS_REVIEW("needs_review"),
    APPROVED_FOR_EXPORT("approved_for_export"),
    EXPORTED_OSC("exported_osc"),
    DISCARDED("discarded");

    companion object {
        fun fromRaw(raw: String?): LocalObservationState? = entries.firstOrNull { it.rawValue == raw }
    }
}

data class LocalObservationCaptureContext(
    val lat: Double?,
    val lon: Double?,
    val headingDeg: Double?,
    val roadCandidateIds: List<String>,
    val cityContext: String?,
    val streetContext: String?,
    val confidenceCalibrated: Double?,
    val sourceVersion: String,
)

data class LocalObservationProposalTarget(
    val type: String,
    val id: String,
)

data class LocalObservationProposal(
    val observationId: String,
    val targetObjects: List<LocalObservationProposalTarget>,
    val oscXml: String,
    val confidenceSummary: String,
)

data class LocalObservationExportResult(
    val exportId: String,
    val packageDirectory: File,
    val changesFile: File,
    val reviewFile: File,
    val readmeFile: File,
)

data class LocalObservationBulkExportResult(
    val exportId: String,
    val packageDirectory: File,
    val changesFile: File,
    val includedCount: Int,
)

internal class LocalObservationStore(
    private val context: Context,
    private val rootDir: File,
    private val preferences: SharedPreferences,
    private val clock: Clock,
) {
    fun captureVoiceCommand(command: String, captureContext: LocalObservationCaptureContext): LocalObservation {
        val trimmed = command.trim()
        require(trimmed.isNotEmpty()) { "Voice command must not be empty" }
        val parsedSpeed = extractFirstSpeedKmh(trimmed)
        val intentType = if (parsedSpeed == null) {
            LocalObservationIntentType.MAP_INCONSISTENCY
        } else {
            LocalObservationIntentType.SET_MAXSPEED
        }
        val value = parsedSpeed?.toString() ?: trimmed
        return insertObservation(
            modality = LocalObservationModality.VOICE_COMMAND,
            intentType = intentType,
            value = value,
            captureContext = captureContext,
            initialState = LocalObservationState.NEEDS_REVIEW,
            oldSpeedKmh = null,
            newSpeedKmh = parsedSpeed,
        )
    }

    fun lockCurrentSpeed(speedKmh: Int, captureContext: LocalObservationCaptureContext): LocalObservation {
        require(speedKmh > 0) { "Current speed must be > 0 km/h" }
        return insertObservation(
            modality = LocalObservationModality.LOCK_CURRENT_SPEED,
            intentType = LocalObservationIntentType.LOCK_SPEED_SNAPSHOT,
            value = speedKmh.toString(),
            captureContext = captureContext,
            initialState = LocalObservationState.NEEDS_REVIEW,
            oldSpeedKmh = null,
            newSpeedKmh = speedKmh,
        )
    }

    fun recordSpeedLimitChange(
        oldSpeedKmh: Int?,
        newMaxspeedValue: String,
        captureContext: LocalObservationCaptureContext,
        initialState: LocalObservationState = LocalObservationState.LOCAL_ONLY,
    ): LocalObservation {
        val normalizedValue = newMaxspeedValue.trim()
        require(normalizedValue.isNotEmpty()) { "Recorded maxspeed value must not be empty" }
        val numericSpeed = normalizedValue.toIntOrNull()
        if (numericSpeed != null) {
            require(numericSpeed > 0) { "Recorded speed must be > 0 km/h" }
        }
        return insertObservation(
            modality = LocalObservationModality.VOICE_COMMAND,
            intentType = LocalObservationIntentType.SET_MAXSPEED,
            value = normalizedValue,
            captureContext = captureContext,
            initialState = initialState,
            oldSpeedKmh = oldSpeedKmh,
            newSpeedKmh = numericSpeed,
        )
    }

    fun fetchObservations(
        states: Set<LocalObservationState>? = null,
        limit: Int = 500,
    ): List<LocalObservation> = withDatabase { db ->
        val sql = buildString {
            append(
                """
                SELECT observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
                       city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
                       device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh
                FROM observations
                """.trimIndent(),
            )
            if (!states.isNullOrEmpty()) {
                append(" WHERE state IN (")
                append(states.joinToString(",") { "?" })
                append(")")
            }
            append(" ORDER BY captured_at_utc DESC LIMIT ?")
        }
        val args = buildList {
            states?.forEach { add(it.rawValue) }
            add(limit.coerceAtLeast(1).toString())
        }.toTypedArray()
        db.rawQuery(sql, args).use { cursor ->
            buildList {
                while (cursor.moveToNext()) {
                    add(decodeObservation(cursor))
                }
            }
        }
    }

    fun deleteObservation(observationId: String) {
        withDatabase { db ->
            db.execSQL("DELETE FROM observations WHERE observation_id = ?", arrayOf(observationId))
        }
    }

    fun deleteAllObservations(): Int = withDatabase { db ->
        db.rawQuery("SELECT COUNT(*) FROM observations", null).use { cursor ->
            val existingCount = if (cursor.moveToFirst()) cursor.getInt(0) else 0
            db.execSQL("DELETE FROM observations")
            existingCount
        }
    }

    fun reviewAndApproveProposal(observationId: String): LocalObservation {
        updateObservationState(observationId, LocalObservationState.APPROVED_FOR_EXPORT)
        return fetchObservation(observationId)
    }

    fun discardObservation(observationId: String): LocalObservation {
        updateObservationState(observationId, LocalObservationState.DISCARDED)
        return fetchObservation(observationId)
    }

    fun buildOsmProposal(observationId: String): LocalObservationProposal {
        val observation = fetchObservation(observationId)
        require(
            observation.state == LocalObservationState.APPROVED_FOR_EXPORT ||
                observation.state == LocalObservationState.NEEDS_REVIEW,
        ) {
            "Observation $observationId is not exportable in current state ${observation.state.rawValue}"
        }
        val wayId = observation.wayId?.trim().orEmpty()
        require(wayId.isNotEmpty()) { "Observation $observationId has no road candidate id" }
        val rawValue = observation.newSpeedValue?.trim().orEmpty()
        require(rawValue.isNotEmpty()) { "Observation $observationId does not contain a maxspeed value" }
        return LocalObservationProposal(
            observationId = observation.id,
            targetObjects = listOf(LocalObservationProposalTarget(type = "way", id = wayId)),
            oscXml = makeOsmChangeXml(wayId = wayId, maxspeedValue = rawValue),
            confidenceSummary = observation.confidenceCalibrated?.let { "confidence=%.2f".format(it) } ?: "confidence=n/a",
        )
    }

    fun exportProposalAsOscPackage(observationId: String): LocalObservationExportResult {
        val proposal = buildOsmProposal(observationId)
        val observation = fetchObservation(observationId)
        require(observation.state == LocalObservationState.APPROVED_FOR_EXPORT) {
            "Observation must be approved_for_export before export"
        }
        val createdAtUtc = clock.instant().toString()
        val exportId = UUID.randomUUID().toString().lowercase()
        val packageDirectory = File(exportsDirectory(), "osm-export-${safeTimestamp(createdAtUtc)}-${exportId.take(8)}")
        packageDirectory.mkdirs()

        val changesFile = File(packageDirectory, "changes.osc")
        val reviewFile = File(packageDirectory, "review.json")
        val readmeFile = File(packageDirectory, "README.txt")
        val oscData = proposal.oscXml.toByteArray()
        changesFile.writeBytes(oscData)
        reviewFile.writeText(makeReviewJson(exportId, createdAtUtc, observation, proposal).toString(2))
        readmeFile.writeText(README_TEMPLATE)

        withDatabase { db ->
            db.execSQL(
                """
                INSERT OR REPLACE INTO exports (
                  export_id, created_at_utc, package_path, package_sha256, observation_ids, returned_changeset_id
                ) VALUES (?, ?, ?, ?, ?, NULL)
                """.trimIndent(),
                arrayOf(
                    exportId,
                    createdAtUtc,
                    packageDirectory.absolutePath,
                    sha256Hex(oscData),
                    JSONArray().put(observation.id).toString(),
                ),
            )
            db.execSQL(
                """
                UPDATE observations
                   SET state = ?, updated_at_utc = ?, export_id = ?
                 WHERE observation_id = ?
                """.trimIndent(),
                arrayOf(
                    LocalObservationState.EXPORTED_OSC.rawValue,
                    createdAtUtc,
                    exportId,
                    observation.id,
                ),
            )
        }

        return LocalObservationExportResult(
            exportId = exportId,
            packageDirectory = packageDirectory,
            changesFile = changesFile,
            reviewFile = reviewFile,
            readmeFile = readmeFile,
        )
    }

    fun exportAllLocalObservationsAsOsc(): LocalObservationBulkExportResult {
        val payload = fetchObservations(limit = 1_000)
            .filter { it.state != LocalObservationState.DISCARDED }
            .sortedBy { it.capturedAtUTC }
            .fold(linkedMapOf<String, LocalObservation>()) { partial, observation ->
                val wayId = observation.wayId?.trim().orEmpty()
                val maxspeedValue = observation.newSpeedValue?.trim().orEmpty()
                if (wayId.isNotEmpty() && maxspeedValue.isNotEmpty()) {
                    val numeric = observation.newSpeedKmh ?: maxspeedValue.toIntOrNull()
                    if (numeric == null || numeric > 0 || maxspeedValue == "walk") {
                        partial[wayId] = observation
                    }
                }
                partial
            }
            .values
            .sortedBy { it.capturedAtUTC }
        require(payload.isNotEmpty()) { "Keine lokalen Erfassungen mit Way-ID und maxspeed-Wert vorhanden." }

        val createdAtUtc = clock.instant().toString()
        val exportId = UUID.randomUUID().toString().lowercase()
        val packageDirectory = File(exportsDirectory(), "osm-export-all-${safeTimestamp(createdAtUtc)}-${exportId.take(8)}")
        packageDirectory.mkdirs()
        val changesFile = File(packageDirectory, "changes.osc")
        val oscXml = makeBulkOsmChangeXml(payload)
        val oscData = oscXml.toByteArray()
        changesFile.writeBytes(oscData)

        withDatabase { db ->
            db.execSQL(
                """
                INSERT OR REPLACE INTO exports (
                  export_id, created_at_utc, package_path, package_sha256, observation_ids, returned_changeset_id
                ) VALUES (?, ?, ?, ?, ?, NULL)
                """.trimIndent(),
                arrayOf(
                    exportId,
                    createdAtUtc,
                    packageDirectory.absolutePath,
                    sha256Hex(oscData),
                    JSONArray(payload.map(LocalObservation::id)).toString(),
                ),
            )
        }

        return LocalObservationBulkExportResult(
            exportId = exportId,
            packageDirectory = packageDirectory,
            changesFile = changesFile,
            includedCount = payload.size,
        )
    }

    private fun insertObservation(
        modality: LocalObservationModality,
        intentType: LocalObservationIntentType,
        value: String?,
        captureContext: LocalObservationCaptureContext,
        initialState: LocalObservationState,
        oldSpeedKmh: Int?,
        newSpeedKmh: Int?,
    ): LocalObservation {
        val observationId = UUID.randomUUID().toString().lowercase()
        val nowUtc = clock.instant().toString()
        val roadIdsJson = JSONArray(captureContext.roadCandidateIds).toString()
        withDatabase { db ->
            db.execSQL(
                """
                INSERT INTO observations (
                  observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
                  city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
                  device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """.trimIndent(),
                arrayOf(
                    observationId,
                    modality.rawValue,
                    intentType.rawValue,
                    value,
                    captureContext.lat,
                    captureContext.lon,
                    captureContext.headingDeg,
                    roadIdsJson,
                    captureContext.cityContext,
                    captureContext.streetContext,
                    nowUtc,
                    captureContext.confidenceCalibrated,
                    captureContext.sourceVersion,
                    initialState.rawValue,
                    ensureDevicePseudoId(),
                    nowUtc,
                    oldSpeedKmh,
                    newSpeedKmh,
                ),
            )
        }
        return fetchObservation(observationId)
    }

    private fun fetchObservation(observationId: String): LocalObservation = withDatabase { db ->
        db.rawQuery(
            """
            SELECT observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
                   city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
                   device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh
            FROM observations
            WHERE observation_id = ?
            LIMIT 1
            """.trimIndent(),
            arrayOf(observationId),
        ).use { cursor ->
            require(cursor.moveToFirst()) { "Observation not found: $observationId" }
            decodeObservation(cursor)
        }
    }

    private fun updateObservationState(
        observationId: String,
        newState: LocalObservationState,
    ) {
        withDatabase { db ->
            db.execSQL(
                """
                UPDATE observations
                   SET state = ?, updated_at_utc = ?
                 WHERE observation_id = ?
                """.trimIndent(),
                arrayOf(newState.rawValue, clock.instant().toString(), observationId),
            )
        }
    }

    private fun decodeObservation(cursor: android.database.Cursor): LocalObservation {
        val modality = LocalObservationModality.entries.first { it.rawValue == cursor.getString(1) }
        val intentType = LocalObservationIntentType.entries.first { it.rawValue == cursor.getString(2) }
        val roadIds = runCatching {
            val raw = cursor.getString(7)
            val array = JSONArray(raw)
            buildList(array.length()) {
                for (index in 0 until array.length()) {
                    add(array.optString(index).trim())
                }
            }.filter { it.isNotEmpty() }
        }.getOrElse { emptyList() }
        return LocalObservation(
            id = cursor.getString(0),
            modality = modality,
            intentType = intentType,
            value = cursor.stringOrNull(3),
            lat = cursor.doubleOrNull(4),
            lon = cursor.doubleOrNull(5),
            headingDeg = cursor.doubleOrNull(6),
            roadCandidateIds = roadIds,
            cityContext = cursor.stringOrNull(8),
            streetContext = cursor.stringOrNull(9),
            capturedAtUTC = cursor.getString(10),
            confidenceCalibrated = cursor.doubleOrNull(11),
            sourceVersion = cursor.getString(12),
            state = LocalObservationState.fromRaw(cursor.getString(13)) ?: LocalObservationState.LOCAL_ONLY,
            devicePseudoId = cursor.getString(14),
            updatedAtUTC = cursor.getString(15),
            exportId = cursor.stringOrNull(16),
            oldSpeedKmh = cursor.intOrNull(17),
            newSpeedKmh = cursor.intOrNull(18),
        )
    }

    private fun makeReviewJson(
        exportId: String,
        createdAtUtc: String,
        observation: LocalObservation,
        proposal: LocalObservationProposal,
    ): JSONObject {
        return JSONObject()
            .put("export_id", exportId)
            .put("created_at_utc", createdAtUtc)
            .put("app_version", appVersion())
            .put("data_bundle_version", observation.sourceVersion)
            .put("observation_ids", JSONArray().put(observation.id))
            .put(
                "target_objects",
                JSONArray().apply {
                    proposal.targetObjects.forEach { target ->
                        put(JSONObject().put("type", target.type).put("id", target.id))
                    }
                },
            )
            .put("street_context", observation.streetContext.orEmpty())
            .put("city_context", observation.cityContext.orEmpty())
            .put("suggested_changeset_comment", "Update maxspeed based on YouSpeed local observation")
            .put("suggested_changeset_source", "YouSpeed local observation")
            .put("confidence_summary", proposal.confidenceSummary)
    }

    private fun appVersion(): String {
        val packageInfo = context.packageManager.getPackageInfo(context.packageName, 0)
        return "${packageInfo.versionName} (${packageInfo.longVersionCode})"
    }

    private fun ensureDevicePseudoId(): String {
        val existing = preferences.getString(DEVICE_PSEUDO_ID_PREFS_KEY, null)?.trim().orEmpty()
        if (existing.isNotEmpty()) {
            return existing
        }
        val generated = UUID.randomUUID().toString().lowercase()
        preferences.edit().putString(DEVICE_PSEUDO_ID_PREFS_KEY, generated).apply()
        return generated
    }

    private fun databaseFile(): File = File(rootDir, "local_observation_store.sqlite")

    private fun exportsDirectory(): File = File(rootDir, "osm-editor-packages").also { it.mkdirs() }

    private fun <T> withDatabase(block: (SQLiteDatabase) -> T): T {
        rootDir.mkdirs()
        val db = SQLiteDatabase.openOrCreateDatabase(databaseFile(), null)
        try {
            ensureSchema(db)
            return block(db)
        } finally {
            db.close()
        }
    }

    private fun ensureSchema(db: SQLiteDatabase) {
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS observations (
              observation_id TEXT PRIMARY KEY,
              modality TEXT NOT NULL,
              intent_type TEXT NOT NULL,
              value TEXT,
              lat REAL,
              lon REAL,
              heading_deg REAL,
              road_candidate_ids TEXT NOT NULL,
              city_context TEXT,
              street_context TEXT,
              captured_at_utc TEXT NOT NULL,
              confidence_calibrated REAL,
              source_version TEXT NOT NULL,
              state TEXT NOT NULL,
              device_pseudo_id TEXT NOT NULL,
              updated_at_utc TEXT NOT NULL,
              export_id TEXT,
              old_speed_kmh INTEGER,
              new_speed_kmh INTEGER
            )
            """.trimIndent(),
        )
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_observations_state ON observations(state)")
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_observations_captured ON observations(captured_at_utc DESC)")
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS exports (
              export_id TEXT PRIMARY KEY,
              created_at_utc TEXT NOT NULL,
              package_path TEXT NOT NULL,
              package_sha256 TEXT NOT NULL,
              observation_ids TEXT NOT NULL,
              returned_changeset_id TEXT
            )
            """.trimIndent(),
        )
        ensureObservationColumn(db, "old_speed_kmh", "INTEGER")
        ensureObservationColumn(db, "new_speed_kmh", "INTEGER")
    }

    private fun ensureObservationColumn(
        db: SQLiteDatabase,
        columnName: String,
        typeDeclaration: String,
    ) {
        db.rawQuery("PRAGMA table_info(observations)", null).use { cursor ->
            while (cursor.moveToNext()) {
                if (cursor.getString(1) == columnName) {
                    return
                }
            }
        }
        db.execSQL("ALTER TABLE observations ADD COLUMN $columnName $typeDeclaration")
    }

    private fun sha256Hex(data: ByteArray): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(data)
        return digest.joinToString("") { byte -> "%02x".format(byte) }
    }

    private fun extractFirstSpeedKmh(text: String): Int? {
        val match = Regex("""\b([1-9][0-9]{0,2})\b""").find(text) ?: return null
        val parsed = match.groupValues.getOrNull(1)?.toIntOrNull() ?: return null
        return parsed.takeIf { it in 5..160 }
    }

    private fun makeOsmChangeXml(
        wayId: String,
        maxspeedValue: String,
    ): String {
        return """
        <?xml version="1.0" encoding="UTF-8"?>
        <osmChange version="0.6" generator="youspeed-export-v1">
          <modify>
            <way id="${xmlEscape(wayId)}">
              <tag k="maxspeed" v="${xmlEscape(maxspeedValue)}"/>
            </way>
          </modify>
        </osmChange>
        """.trimIndent()
    }

    private fun makeBulkOsmChangeXml(observations: List<LocalObservation>): String {
        val body = observations.joinToString("\n") { observation ->
            """
                <way id="${xmlEscape(observation.wayId.orEmpty())}">
                  <tag k="maxspeed" v="${xmlEscape(observation.newSpeedValue.orEmpty())}"/>
                </way>
            """.trimIndent()
        }
        return """
        <?xml version="1.0" encoding="UTF-8"?>
        <osmChange version="0.6" generator="youspeed-export-v1">
          <modify>
        $body
          </modify>
        </osmChange>
        """.trimIndent()
    }

    private fun safeTimestamp(isoValue: String): String {
        return isoValue.replace(":", "").replace("-", "")
    }

    private fun xmlEscape(value: String): String {
        return value
            .replace("&", "&amp;")
            .replace("\"", "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    }

    private fun android.database.Cursor.stringOrNull(index: Int): String? {
        return if (isNull(index)) null else getString(index)?.trim()?.ifEmpty { null }
    }

    private fun android.database.Cursor.doubleOrNull(index: Int): Double? {
        return if (isNull(index)) null else getDouble(index)
    }

    private fun android.database.Cursor.intOrNull(index: Int): Int? {
        return if (isNull(index)) null else getInt(index)
    }

    companion object {
        private const val DEVICE_PSEUDO_ID_PREFS_KEY = "youspeed.local_observation.device_pseudo_id"

        private val README_TEMPLATE = """
        YouSpeed editor export package

        Files:
        - changes.osc
        - review.json
        - README.txt

        JOSM import:
        1. Open JOSM.
        2. File -> Open... and select changes.osc.
        3. Review all tag changes carefully.
        4. Upload using your own OSM account.

        Merkaartor import:
        1. Open Merkaartor.
        2. Import changes.osc.
        3. Review all edited objects and tags.
        4. Upload using your own OSM account.

        Important:
        - Final upload is always user-controlled in the editor.
        - You are responsible for reviewing correctness before upload.
        """.trimIndent()
    }
}
