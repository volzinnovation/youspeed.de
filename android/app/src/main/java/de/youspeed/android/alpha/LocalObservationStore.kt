package de.youspeed.android.alpha

import android.content.Context
import android.content.SharedPreferences
import android.database.sqlite.SQLiteDatabase
import java.io.File
import java.security.MessageDigest
import java.time.Clock
import java.time.Duration
import java.util.Locale
import java.util.UUID
import org.json.JSONArray
import org.json.JSONObject

enum class LocalObservationModality(val rawValue: String) {
    VOICE_COMMAND("voice_command"),
    LOCK_CURRENT_SPEED("lock_current_speed"),
    COMPUTER_VISION("computer_vision"),
}

enum class LocalObservationIntentType(val rawValue: String) {
    SET_MAXSPEED("set_maxspeed"),
    MAP_INCONSISTENCY("map_inconsistency"),
    LOCK_SPEED_SNAPSHOT("lock_speed_snapshot"),
    TEMPORARY_RESTRICTION("temporary_restriction"),
}

data class LocalRuntimeCorrection(
    val observationId: String,
    val wayId: String,
    val tagKey: String,
    val canonicalValue: String,
    val numericSpeedKmh: Int?,
    val directionScope: TrafficSignTravelDirection,
    val effectiveAtUtc: String,
)

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

private data class FinalizedLocalExport(
    val exportId: String,
    val packageDirectory: File,
    val changesFile: File,
    val reviewFile: File,
    val readmeFile: File,
    val includedCount: Int,
)

internal class LocalObservationStore(
    private val context: Context,
    private val rootDir: File,
    private val preferences: SharedPreferences,
    private val clock: Clock,
) {
    private val serializedStoreGate = Any()

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

    /**
     * Persists one finalized camera passage at most once. The runtime assertion
     * is already committed before this call, so storage failure is deliberately
     * reported to the caller instead of changing live speed state.
     */
    fun recordComputerVisionPassageIfNeeded(
        event: TrafficSignPassageEvent,
        resolvedLimit: TrafficSignResolvedLimit = event.resolution,
        captureContext: LocalObservationCaptureContext,
        writeGate: TrafficSignWriteGate? = null,
        generationIsCurrent: (Long) -> Boolean = { it == event.generation },
        writePermitted: () -> Boolean = { true },
    ): LocalObservation? = synchronized(serializedStoreGate) {
        if (!event.overrideEligible || event.action.kind !in SHARED_PASSAGE_ACTION_KINDS) return@synchronized null
        val activation = event.activationContext ?: return@synchronized null
        val primaryWayId = activation.wayId?.trim()?.takeIf(::isPositiveOsmWayId) ?: return@synchronized null
        if (!activation.hasVerifiedBundle) return@synchronized null
        val firstSeenContext = event.firstSeenContext ?: return@synchronized null
        val firstSeenWayId = firstSeenContext.wayId?.trim()?.takeIf(::isPositiveOsmWayId) ?: return@synchronized null
        val direction = activation.travelDirection
        val canonicalValue = resolvedLimit.maxspeedValue?.takeIf(::isCanonicalMaxspeedValue)
        val permanent = event.action.isPermanentRuntimeAction
        val unconditional = !event.action.isConditional
        val concrete = canonicalValue != null && resolvedLimit.kind != TrafficSignResolvedLimitKind.UNKNOWN
        val recognitionAssociationSafe = primaryWayId == firstSeenWayId || (
            activation.continuityCapable &&
                event.eligibleRouteRelationGroupIds.intersect(activation.routeRelationGroupIds).isNotEmpty()
            )
        val safe = activation.matchedWayStable && activation.hasVerifiedBundle &&
            recognitionAssociationSafe && permanent && unconditional && concrete
        val tagKey = when (direction) {
            TrafficSignTravelDirection.FORWARD -> "maxspeed:forward"
            TrafficSignTravelDirection.REVERSE -> "maxspeed:backward"
            // Unknown direction is represented as a way-wide correction until
            // later GPS evidence can resolve a directional scope.
            TrafficSignTravelDirection.UNKNOWN -> "maxspeed"
        }
        val state = if (safe) LocalObservationState.LOCAL_ONLY else LocalObservationState.NEEDS_REVIEW
        val intentType = when {
            event.action.kind == TrafficSignActionKind.TEMPORARY_MAXIMUM ->
                LocalObservationIntentType.TEMPORARY_RESTRICTION
            concrete -> LocalObservationIntentType.SET_MAXSPEED
            else -> LocalObservationIntentType.MAP_INCONSISTENCY
        }
        val observationId = UUID.randomUUID().toString().lowercase()
        val processedAtUtc = clock.instant().toString()
        val effectiveAtUtc = event.passageBoundary.timestampUtc.toString()
        val evidenceJson = makeComputerVisionEvidenceJson(
            event = event,
            resolvedLimit = resolvedLimit,
            runtimeApplicable = safe,
            reviewState = state,
            intentType = intentType,
            osmTagKey = tagKey,
        ).toString()
        val summary = "${event.action.kind.wireValue}; confidence=%.3f; support=%.3f".format(
            Locale.ROOT,
            event.finalConfidence,
            event.finalAccumulatedSupport,
        )
        val roadIds = buildList {
            activation.wayId?.trim()?.takeIf(String::isNotEmpty)?.let(::add)
            event.lastSeenContext?.wayId?.trim()?.takeIf(String::isNotEmpty)?.takeIf { it !in this }?.let(::add)
        }

        val writeTransaction: () -> LocalObservation? = {
        withDatabase { db ->
            db.beginTransaction()
            try {
                if (!generationIsCurrent(event.generation) || !writePermitted()) {
                    db.setTransactionSuccessful()
                    return@withDatabase null
                }
                val priorReceipt = db.rawQuery(
                    "SELECT observation_id, correction_created FROM cv_event_receipts WHERE finalized_event_id = ? LIMIT 1",
                    arrayOf(event.finalizedEventId),
                ).use { cursor ->
                    if (cursor.moveToFirst()) cursor.stringOrNull(0) to (cursor.getInt(1) != 0) else null
                }
                if (priorReceipt != null) {
                    val prior = priorReceipt.first?.let { fetchObservation(db, it) }
                    db.setTransactionSuccessful()
                    return@withDatabase prior.takeIf { priorReceipt.second }
                }

                val latestCorrection = if (safe) {
                    latestRuntimeApplicableObservation(db, primaryWayId, direction)
                } else {
                    null
                }
                if (latestCorrection?.newSpeedValue == canonicalValue && canonicalValue != null) {
                    db.execSQL(
                        """
                        INSERT INTO cv_event_receipts(
                          finalized_event_id, processed_at_utc, observation_id, evidence_json, correction_created
                        ) VALUES (?, ?, ?, ?, 0)
                        """.trimIndent(),
                        arrayOf(event.finalizedEventId, processedAtUtc, requireNotNull(latestCorrection).id, evidenceJson),
                    )
                    db.setTransactionSuccessful()
                    return@withDatabase null
                }

                if (!generationIsCurrent(event.generation) || !writePermitted()) {
                    db.setTransactionSuccessful()
                    return@withDatabase null
                }
                stalePendingExportsForIncomingTarget(
                    db,
                    primaryWayId,
                    tagKey,
                    direction,
                    incomingEffectiveAtUtc = effectiveAtUtc,
                )
                db.execSQL(
                    """
                    INSERT INTO observations (
                      observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
                      city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
                      device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh,
                      evidence_json, evidence_summary, primary_way_id, effective_at_utc, finalized_event_id,
                      runtime_applicable, action_kind, resolved_limit_kind, direction_scope, permanent,
                      unconditional, osm_tag_key, canonical_value, superseded_for_export
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """.trimIndent(),
                    arrayOf(
                        observationId,
                        LocalObservationModality.COMPUTER_VISION.rawValue,
                        intentType.rawValue,
                        canonicalValue,
                        activation.latitude,
                        activation.longitude,
                        activation.headingDegrees,
                        JSONArray(roadIds).toString(),
                        captureContext.cityContext,
                        captureContext.streetContext,
                        processedAtUtc,
                        event.finalConfidence,
                        captureContext.sourceVersion,
                        state.rawValue,
                        ensureDevicePseudoId(),
                        processedAtUtc,
                        resolvedLimit.speedKmh,
                        evidenceJson,
                        summary,
                        primaryWayId,
                        effectiveAtUtc,
                        event.finalizedEventId,
                        if (safe) 1 else 0,
                        event.action.kind.wireValue,
                        resolvedLimit.kind.wireValue,
                        direction.wireValue,
                        if (permanent) 1 else 0,
                        if (unconditional) 1 else 0,
                        tagKey,
                        canonicalValue,
                    ),
                )
                db.execSQL(
                    """
                    INSERT INTO cv_event_receipts(
                      finalized_event_id, processed_at_utc, observation_id, evidence_json, correction_created
                    ) VALUES (?, ?, ?, ?, 1)
                    """.trimIndent(),
                    arrayOf(event.finalizedEventId, processedAtUtc, observationId, evidenceJson),
                )
                if (safe) {
                    supersedeApprovedForTarget(
                        db = db,
                        exceptObservationId = observationId,
                        wayId = requireNotNull(primaryWayId),
                        tagKey = requireNotNull(tagKey),
                        direction = direction,
                        updatedAtUtc = processedAtUtc,
                        incomingEffectiveAtUtc = effectiveAtUtc,
                        incomingRowId = requireNotNull(observationRowId(db, observationId)),
                    )
                }
                val inserted = fetchObservation(db, observationId)
                db.setTransactionSuccessful()
                inserted
            } finally {
                db.endTransaction()
            }
        }
        }
        if (writeGate != null) {
            writeGate.withPermit(event.generation, writeTransaction)
        } else if (generationIsCurrent(event.generation) && writePermitted()) {
            writeTransaction()
        } else {
            null
        }
    }

    /** Indexed latest applicable correction for this exact OSM way/direction. */
    fun latestRuntimeApplicableCorrection(
        wayId: String,
        direction: TrafficSignTravelDirection,
    ): LocalRuntimeCorrection? = synchronized(serializedStoreGate) {
        val normalizedWayId = wayId.trim()
        if (!isPositiveOsmWayId(normalizedWayId)) return@synchronized null
        withDatabase { db ->
            latestRuntimeApplicableObservation(db, normalizedWayId, direction)?.toRuntimeCorrection()
        }
    }

    /** Resolves the exact correction linked to a finalized passage receipt. */
    fun runtimeApplicableCorrectionForFinalizedEvent(
        finalizedEventId: String,
        currentDirection: TrafficSignTravelDirection,
    ): LocalRuntimeCorrection? = synchronized(serializedStoreGate) {
        withDatabase { db ->
            val observationId = db.rawQuery(
                "SELECT observation_id FROM cv_event_receipts WHERE finalized_event_id = ? LIMIT 1",
                arrayOf(finalizedEventId),
            ).use { cursor ->
                if (cursor.moveToFirst()) cursor.stringOrNull(0) else null
            } ?: return@withDatabase null
            val observation = fetchObservation(db, observationId) ?: return@withDatabase null
            observation.takeIf { isRuntimeApplicableCorrection(it, currentDirection) }?.toRuntimeCorrection()
        }
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
                       device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh,
                       evidence_json, evidence_summary, primary_way_id, effective_at_utc, finalized_event_id,
                       runtime_applicable, action_kind, resolved_limit_kind, direction_scope, permanent,
                       unconditional, osm_tag_key, canonical_value, superseded_for_export
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
                    decodeObservation(cursor)?.let(::add)
                }
            }
        }
    }

    fun deleteObservation(observationId: String) = synchronized(serializedStoreGate) {
        withDatabase { db ->
            reconcilePendingExports(db)
            require(!hasPendingExportMember(db, observationId)) { "Observation $observationId is reserved for export" }
            db.execSQL("DELETE FROM observations WHERE observation_id = ?", arrayOf(observationId))
        }
    }

    fun deleteAllObservations(): Int = synchronized(serializedStoreGate) {
        withDatabase { db ->
            reconcilePendingExports(db)
            require(!hasAnyPendingExportMembers(db)) { "Observations are reserved for export" }
            db.rawQuery("SELECT COUNT(*) FROM observations", null).use { cursor ->
                val existingCount = if (cursor.moveToFirst()) cursor.getInt(0) else 0
                db.execSQL("DELETE FROM observations")
                existingCount
            }
        }
    }

    fun reviewAndApproveProposal(observationId: String): LocalObservation = synchronized(serializedStoreGate) {
        withDatabase { db ->
            db.beginTransaction()
            try {
                val incoming = fetchObservation(db, observationId)
                    ?: error("Observation not found or unsupported: $observationId")
                val incomingWayId = incoming.wayId
                val incomingTagKey = incoming.osmTagKey
                if (incomingWayId != null && incomingTagKey != null) {
                    stalePendingExportsForIncomingTarget(
                        db,
                        incomingWayId,
                        incomingTagKey,
                        incoming.directionScope,
                        incomingEffectiveAtUtc = incoming.effectiveAtUTC,
                        incomingRowId = observationRowId(db, incoming.id),
                    )
                }
                reconcilePendingExports(db)
                val observation = fetchObservation(db, observationId)
                    ?: error("Observation not found or unsupported: $observationId")
                require(observation.state in setOf(LocalObservationState.LOCAL_ONLY, LocalObservationState.NEEDS_REVIEW)) {
                    "Observation $observationId cannot be re-approved from ${observation.state.rawValue}"
                }
                require(isStructurallyExportableCorrection(observation)) {
                    "Observation $observationId is review-only and cannot be approved for OSC export"
                }
                require(isLatestTargetObservation(db, observation)) {
                    "Observation $observationId is not the latest correction for its typed target"
                }
                require(!hasNewerConflictingEvidence(db, observation)) {
                    "Observation $observationId has newer conflicting evidence"
                }
                val updatedAtUtc = clock.instant().toString()
                supersedeApprovedForTarget(
                    db = db,
                    exceptObservationId = observation.id,
                    wayId = requireNotNull(observation.wayId),
                    tagKey = requireNotNull(observation.osmTagKey),
                    direction = observation.directionScope,
                    updatedAtUtc = updatedAtUtc,
                    incomingEffectiveAtUtc = observation.effectiveAtUTC,
                    incomingRowId = requireNotNull(observationRowId(db, observation.id)),
                )
                val updated = db.compileStatement(
                    "UPDATE observations SET state = ?, updated_at_utc = ?, superseded_for_export = 0 WHERE observation_id = ? AND state IN (?, ?)",
                ).use { statement ->
                    statement.bindString(1, LocalObservationState.APPROVED_FOR_EXPORT.rawValue)
                    statement.bindString(2, updatedAtUtc)
                    statement.bindString(3, observation.id)
                    statement.bindString(4, LocalObservationState.LOCAL_ONLY.rawValue)
                    statement.bindString(5, LocalObservationState.NEEDS_REVIEW.rawValue)
                    statement.executeUpdateDelete()
                }
                require(updated == 1) { "Observation $observationId changed during approval" }
                val approved = requireNotNull(fetchObservation(db, observationId))
                db.setTransactionSuccessful()
                approved
            } finally {
                db.endTransaction()
            }
        }
    }

    fun discardObservation(observationId: String): LocalObservation = synchronized(serializedStoreGate) {
        withDatabase { db ->
            reconcilePendingExports(db)
            require(!hasPendingExportMember(db, observationId)) { "Observation $observationId is reserved for export" }
        }
        updateObservationState(observationId, LocalObservationState.DISCARDED)
        fetchObservation(observationId)
    }

    fun buildOsmProposal(observationId: String): LocalObservationProposal {
        val observation = fetchObservation(observationId)
        require(isExportableCorrection(observation)) {
            "Observation $observationId is not exportable in current state ${observation.state.rawValue}"
        }
        val wayId = observation.wayId?.trim().orEmpty()
        require(isPositiveOsmWayId(wayId)) { "Observation $observationId has no positive OSM way id" }
        val rawValue = observation.newSpeedValue?.trim().orEmpty()
        require(isCanonicalMaxspeedValue(rawValue)) { "Observation $observationId has no canonical maxspeed value" }
        withDatabase { db ->
            require(isLatestTargetObservation(db, observation)) {
                "Observation $observationId is not the latest correction for its typed target"
            }
            require(!hasNewerConflictingEvidence(db, observation)) {
                "Observation $observationId has newer conflicting evidence awaiting review"
            }
        }
        return LocalObservationProposal(
            observationId = observation.id,
            targetObjects = listOf(LocalObservationProposalTarget(type = "way", id = wayId)),
            oscXml = makeOsmChangeXml(
                wayId = wayId,
                tagKey = requireNotNull(observation.osmTagKey),
                maxspeedValue = rawValue,
            ),
            confidenceSummary = observation.confidenceCalibrated?.let { "confidence=%.2f".format(it) } ?: "confidence=n/a",
        )
    }

    fun exportProposalAsOscPackage(observationId: String): LocalObservationExportResult = synchronized(serializedStoreGate) {
        val observation = fetchObservation(observationId)
        require(isExportableCorrection(observation)) { "Observation must be approved and structurally exportable" }
        val finalized = reserveWriteAndFinalizeExport(listOf(observation), bulk = false)
        LocalObservationExportResult(
            exportId = finalized.exportId,
            packageDirectory = finalized.packageDirectory,
            changesFile = finalized.changesFile,
            reviewFile = finalized.reviewFile,
            readmeFile = finalized.readmeFile,
        )
    }

    fun exportAllLocalObservationsAsOsc(): LocalObservationBulkExportResult = synchronized(serializedStoreGate) {
        val payload = fetchObservations(
            states = setOf(
                LocalObservationState.LOCAL_ONLY,
                LocalObservationState.NEEDS_REVIEW,
                LocalObservationState.APPROVED_FOR_EXPORT,
            ),
            limit = Int.MAX_VALUE,
        )
            .filter(::isBulkExportableCorrection)
            .filter { observation ->
                withDatabase { db ->
                    isLatestTargetObservation(db, observation) && !hasNewerConflictingEvidence(db, observation)
                }
            }
            .sortedBy { it.effectiveAtUTC }
            .fold(linkedMapOf<String, LocalObservation>()) { partial, observation ->
                val wayId = observation.wayId?.trim().orEmpty()
                val maxspeedValue = observation.newSpeedValue?.trim().orEmpty()
                if (isPositiveOsmWayId(wayId) && isCanonicalMaxspeedValue(maxspeedValue)) {
                    val target = "$wayId|${observation.osmTagKey}|${observation.directionScope.wireValue}"
                    partial[target] = observation
                }
                partial
            }
            .values
            .sortedBy { it.effectiveAtUTC }
        require(payload.isNotEmpty()) { "Keine freigegebenen, exportierbaren Korrekturen vorhanden." }

        val finalized = reserveWriteAndFinalizeExport(payload, bulk = true)
        LocalObservationBulkExportResult(
            exportId = finalized.exportId,
            packageDirectory = finalized.packageDirectory,
            changesFile = finalized.changesFile,
            includedCount = finalized.includedCount,
        )
    }

    /** Reserve -> freeze -> temp-write -> revalidate -> atomic rename/finalize. */
    private fun reserveWriteAndFinalizeExport(
        observations: List<LocalObservation>,
        bulk: Boolean,
    ): FinalizedLocalExport {
        require(observations.isNotEmpty())
        val frozen = observations.sortedWith(compareBy<LocalObservation> { it.effectiveAtUTC }.thenBy { it.id })
        fun isEligible(observation: LocalObservation): Boolean = if (bulk) {
            isBulkExportableCorrection(observation)
        } else {
            isExportableCorrection(observation)
        }
        frozen.forEach { require(isEligible(it)) { "Observation ${it.id} is no longer exportable" } }
        val oscXml = if (bulk) {
            makeBulkOsmChangeXml(frozen)
        } else {
            val one = frozen.single()
            makeOsmChangeXml(requireNotNull(one.wayId), requireNotNull(one.osmTagKey), requireNotNull(one.newSpeedValue))
        }
        val oscData = oscXml.toByteArray()
        val payloadSha256 = sha256Hex(oscData)
        val revisionSnapshot = JSONObject().apply {
            frozen.forEach { put(it.id, it.updatedAtUTC) }
        }.toString()
        val membershipMaterial = frozen.joinToString("\n") {
            "${it.id}|${it.updatedAtUTC}|${it.wayId}|${it.osmTagKey}|${it.newSpeedValue}"
        }.toByteArray()
        val membershipKey = sha256Hex(membershipMaterial)
        val exportId = "local-${membershipKey.take(32)}"
        val createdAtUtc = clock.instant().toString()
        val stem = if (bulk) "osm-export-all-${membershipKey.take(12)}" else "osm-export-${membershipKey.take(12)}"
        val packageDirectory = File(exportsDirectory(), stem)
        val pendingDirectory = File(exportsDirectory(), ".$stem.pending")
        val observationIdsJson = JSONArray(frozen.map(LocalObservation::id)).toString()
        val reviewJson = makeBatchReviewJson(exportId, createdAtUtc, frozen, payloadSha256).toString(2)

        withDatabase { db ->
            db.beginTransaction()
            try {
                reconcilePendingExports(db, excludingBatchId = exportId)
                // A failed attempt intentionally marks its deterministic reservation stale.
                // Remove only that exact abandoned snapshot so an unchanged approved
                // observation can be retried without weakening pending/finalized uniqueness.
                db.execSQL(
                    "DELETE FROM local_observation_export_members WHERE batch_id = ? AND reservation_status = 'stale'",
                    arrayOf(exportId),
                )
                db.execSQL(
                    "DELETE FROM local_observation_export_batches WHERE batch_id = ? AND status = 'stale'",
                    arrayOf(exportId),
                )
                frozen.forEachIndexed { ordinal, observation ->
                    val current = fetchObservation(db, observation.id)
                    require(current != null && current.updatedAtUTC == observation.updatedAtUTC && isEligible(current)) {
                        "Observation ${observation.id} changed before export reservation"
                    }
                    require(isLatestTargetObservation(db, current)) {
                        "Observation ${observation.id} is no longer the latest correction for its typed target"
                    }
                    require(!hasNewerConflictingEvidence(db, current)) {
                        "Observation ${observation.id} has newer conflicting evidence"
                    }
                    require(ordinal >= 0)
                }
                db.execSQL(
                    """
                    INSERT OR IGNORE INTO local_observation_export_batches (
                      batch_id, created_at_utc, status, package_path, payload_sha256,
                      payload_xml, membership_key, finalized_at_utc, export_mode
                    ) VALUES (?, ?, 'pending', ?, ?, ?, ?, NULL, ?)
                    """.trimIndent(),
                    arrayOf(
                        exportId,
                        createdAtUtc,
                        packageDirectory.absolutePath,
                        payloadSha256,
                        oscXml,
                        membershipKey,
                        if (bulk) "bulk" else "single",
                    ),
                )
                val reservationMatches = db.rawQuery(
                    "SELECT payload_sha256, payload_xml, membership_key, export_mode FROM local_observation_export_batches WHERE batch_id = ? AND status IN ('pending', 'finalized') LIMIT 1",
                    arrayOf(exportId),
                ).use { cursor ->
                    cursor.moveToFirst() && cursor.getString(0) == payloadSha256 &&
                        cursor.getString(1) == oscXml && cursor.getString(2) == membershipKey &&
                        cursor.getString(3) == if (bulk) "bulk" else "single"
                }
                require(reservationMatches) { "Export reservation collision for $exportId" }
                frozen.forEachIndexed { ordinal, observation ->
                    db.execSQL(
                        """
                        INSERT OR IGNORE INTO local_observation_export_members (
                          batch_id, observation_id, target_key, observation_revision, ordinal, reservation_status
                        ) VALUES (?, ?, ?, ?, ?, 'pending')
                        """.trimIndent(),
                        arrayOf(
                            exportId,
                            observation.id,
                            exportTargetKey(observation),
                            observation.updatedAtUTC,
                            ordinal,
                        ),
                    )
                    val memberMatches = db.rawQuery(
                        """
                        SELECT 1 FROM local_observation_export_members
                        WHERE batch_id = ? AND observation_id = ? AND target_key = ?
                          AND observation_revision = ? AND ordinal = ?
                          AND reservation_status IN ('pending', 'finalized')
                        LIMIT 1
                        """.trimIndent(),
                        arrayOf(
                            exportId,
                            observation.id,
                            exportTargetKey(observation),
                            observation.updatedAtUTC,
                            ordinal.toString(),
                        ),
                    ).use { it.moveToFirst() }
                    require(memberMatches) {
                        "Observation ${observation.id} or target ${exportTargetKey(observation)} is already reserved"
                    }
                }
                db.setTransactionSuccessful()
            } finally {
                db.endTransaction()
            }
        }

        try {
            pendingDirectory.mkdirs()
            val pendingChanges = File(pendingDirectory, "changes.osc").also { it.writeBytes(oscData) }
            File(pendingDirectory, "review.json").writeText(reviewJson)
            File(pendingDirectory, "README.txt").writeText(README_TEMPLATE)
            require(sha256Hex(pendingChanges.readBytes()) == payloadSha256) { "Frozen OSC payload failed hash verification" }

            withDatabase { db ->
            db.beginTransaction()
            try {
                val batchStatus = db.rawQuery(
                    "SELECT status FROM local_observation_export_batches WHERE batch_id = ? AND payload_sha256 = ? LIMIT 1",
                    arrayOf(exportId, payloadSha256),
                ).use { cursor -> if (cursor.moveToFirst()) cursor.getString(0) else null }
                val reservationPending = batchStatus == "pending"
                val alreadyFinalized = batchStatus == "finalized"
                require(reservationPending || alreadyFinalized) { "Export reservation is no longer current" }
                if (reservationPending) {
                    frozen.forEach { observation ->
                        val current = fetchObservation(db, observation.id)
                        require(current != null && current.updatedAtUTC == observation.updatedAtUTC && isEligible(current)) {
                            "Observation ${observation.id} changed while export was pending"
                        }
                        require(isLatestTargetObservation(db, current)) {
                            "Observation ${observation.id} is no longer the latest correction while export was pending"
                        }
                        require(!hasNewerConflictingEvidence(db, current)) {
                            "Observation ${observation.id} became stale while export was pending"
                        }
                        val memberPending = db.rawQuery(
                            """
                            SELECT 1 FROM local_observation_export_members
                            WHERE batch_id = ? AND observation_id = ? AND target_key = ?
                              AND observation_revision = ? AND reservation_status = 'pending'
                            LIMIT 1
                            """.trimIndent(),
                            arrayOf(exportId, observation.id, exportTargetKey(observation), observation.updatedAtUTC),
                        ).use { it.moveToFirst() }
                        require(memberPending) { "Export member ${observation.id} is no longer reserved" }
                    }
                }
                if (!packageDirectory.exists()) {
                    require(pendingDirectory.renameTo(packageDirectory)) { "Unable to atomically finalize OSC package" }
                } else {
                    require(File(packageDirectory, "changes.osc").takeIf(File::isFile)?.readBytes()?.let(::sha256Hex) == payloadSha256) {
                        "Existing finalized OSC package does not match its reservation"
                    }
                }
                val finalizedAtUtc = clock.instant().toString()
                if (reservationPending) {
                    val batchUpdated = db.compileStatement(
                        "UPDATE local_observation_export_batches SET status = 'finalized', finalized_at_utc = ? WHERE batch_id = ? AND status = 'pending' AND payload_sha256 = ?",
                    ).use { statement ->
                        statement.bindString(1, finalizedAtUtc)
                        statement.bindString(2, exportId)
                        statement.bindString(3, payloadSha256)
                        statement.executeUpdateDelete()
                    }
                    require(batchUpdated == 1) { "Export batch $exportId could not be finalized" }
                    val membersUpdated = db.compileStatement(
                        "UPDATE local_observation_export_members SET reservation_status = 'finalized' WHERE batch_id = ? AND reservation_status = 'pending'",
                    ).use { statement ->
                        statement.bindString(1, exportId)
                        statement.executeUpdateDelete()
                    }
                    require(membersUpdated == frozen.size) { "Not every export member was finalized" }
                }
                if (!alreadyFinalized) frozen.forEach { observation ->
                    val observationUpdated = db.compileStatement(
                        """
                        UPDATE observations SET state = ?, updated_at_utc = ?, export_id = ?
                        WHERE observation_id = ? AND state = ? AND updated_at_utc = ? AND superseded_for_export = 0
                        """.trimIndent(),
                    ).use { statement ->
                        statement.bindString(1, LocalObservationState.EXPORTED_OSC.rawValue)
                        statement.bindString(2, finalizedAtUtc)
                        statement.bindString(3, exportId)
                        statement.bindString(4, observation.id)
                        statement.bindString(5, observation.state.rawValue)
                        statement.bindString(6, observation.updatedAtUTC)
                        statement.executeUpdateDelete()
                    }
                    require(observationUpdated == 1) { "Observation ${observation.id} could not be finalized" }
                }
                db.execSQL(
                    """
                    INSERT OR IGNORE INTO exports (
                      export_id, created_at_utc, package_path, package_sha256, observation_ids,
                      returned_changeset_id, status, payload_xml, membership_key, observation_revisions, finalized_at_utc
                    ) VALUES (?, ?, ?, ?, ?, NULL, 'finalized', ?, ?, ?, ?)
                    """.trimIndent(),
                    arrayOf(
                        exportId,
                        createdAtUtc,
                        packageDirectory.absolutePath,
                        payloadSha256,
                        observationIdsJson,
                        oscXml,
                        membershipKey,
                        revisionSnapshot,
                        finalizedAtUtc,
                    ),
                )
                db.setTransactionSuccessful()
            } finally {
                db.endTransaction()
            }
            }
        } catch (failure: Throwable) {
            abandonPendingExport(exportId)
            throw failure
        }

        return FinalizedLocalExport(
            exportId = exportId,
            packageDirectory = packageDirectory,
            changesFile = File(packageDirectory, "changes.osc"),
            reviewFile = File(packageDirectory, "review.json"),
            readmeFile = File(packageDirectory, "README.txt"),
            includedCount = frozen.size,
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
    ): LocalObservation = synchronized(serializedStoreGate) {
        val observationId = UUID.randomUUID().toString().lowercase()
        val nowUtc = clock.instant().toString()
        val roadIdsJson = JSONArray(captureContext.roadCandidateIds).toString()
        val primaryWayId = captureContext.roadCandidateIds.firstOrNull()?.trim()?.ifBlank { null }
        val canonicalValue = value?.trim()?.ifBlank { null }
        val runtimeApplicable = intentType == LocalObservationIntentType.SET_MAXSPEED &&
            isPositiveOsmWayId(primaryWayId) &&
            isCanonicalMaxspeedValue(canonicalValue)
        withDatabase { db ->
            db.beginTransaction()
            try {
                val tagKey = if (intentType == LocalObservationIntentType.SET_MAXSPEED) "maxspeed" else null
                if (runtimeApplicable && primaryWayId != null && tagKey != null) {
                    // The incoming row is the new serialization winner. Stale an overlapping
                    // crashed reservation before inserting it; do not first recover/publish
                    // the older snapshot.
                    stalePendingExportsForIncomingTarget(
                        db,
                        primaryWayId,
                        tagKey,
                        TrafficSignTravelDirection.UNKNOWN,
                        incomingEffectiveAtUtc = nowUtc,
                    )
                }
                db.execSQL(
                """
                INSERT INTO observations (
                  observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
                  city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
                  device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh,
                  primary_way_id, effective_at_utc, runtime_applicable, action_kind, resolved_limit_kind,
                  direction_scope, permanent, unconditional, osm_tag_key, canonical_value, superseded_for_export
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, 0)
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
                    primaryWayId,
                    nowUtc,
                    if (runtimeApplicable) 1 else 0,
                    if (intentType == LocalObservationIntentType.SET_MAXSPEED) TrafficSignActionKind.POSTED_MAXIMUM.wireValue else null,
                    when {
                        newSpeedKmh != null -> TrafficSignResolvedLimitKind.NUMERIC.wireValue
                        canonicalValue == "walk" -> TrafficSignResolvedLimitKind.WALK.wireValue
                        canonicalValue == "none" -> TrafficSignResolvedLimitKind.UNLIMITED.wireValue
                        else -> null
                    },
                    TrafficSignTravelDirection.UNKNOWN.wireValue,
                    tagKey,
                    canonicalValue,
                ),
            )
                if (runtimeApplicable && primaryWayId != null && tagKey != null) {
                    supersedeApprovedForTarget(
                        db = db,
                        exceptObservationId = observationId,
                        wayId = primaryWayId,
                        tagKey = tagKey,
                        direction = TrafficSignTravelDirection.UNKNOWN,
                        updatedAtUtc = nowUtc,
                        incomingEffectiveAtUtc = nowUtc,
                        incomingRowId = requireNotNull(observationRowId(db, observationId)),
                    )
                }
                db.setTransactionSuccessful()
            } finally {
                db.endTransaction()
            }
        }
        fetchObservation(observationId)
    }

    private fun fetchObservation(observationId: String): LocalObservation = withDatabase { db ->
        db.rawQuery(
            """
            SELECT observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
                   city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
                   device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh,
                   evidence_json, evidence_summary, primary_way_id, effective_at_utc, finalized_event_id,
                   runtime_applicable, action_kind, resolved_limit_kind, direction_scope, permanent,
                   unconditional, osm_tag_key, canonical_value, superseded_for_export
            FROM observations
            WHERE observation_id = ?
            LIMIT 1
            """.trimIndent(),
            arrayOf(observationId),
        ).use { cursor ->
            require(cursor.moveToFirst()) { "Observation not found: $observationId" }
            requireNotNull(decodeObservation(cursor)) {
                "Observation has unsupported future enum data: $observationId"
            }
        }
    }

    private fun fetchObservation(db: SQLiteDatabase, observationId: String): LocalObservation? = db.rawQuery(
        """
        SELECT observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
               city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
               device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh,
               evidence_json, evidence_summary, primary_way_id, effective_at_utc, finalized_event_id,
               runtime_applicable, action_kind, resolved_limit_kind, direction_scope, permanent,
               unconditional, osm_tag_key, canonical_value, superseded_for_export
        FROM observations WHERE observation_id = ? LIMIT 1
        """.trimIndent(),
        arrayOf(observationId),
    ).use { cursor -> if (cursor.moveToFirst()) decodeObservation(cursor) else null }

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

    private fun decodeObservation(cursor: android.database.Cursor): LocalObservation? {
        val modality = LocalObservationModality.entries.firstOrNull { it.rawValue == cursor.getString(1) } ?: return null
        val intentType = LocalObservationIntentType.entries.firstOrNull { it.rawValue == cursor.getString(2) } ?: return null
        val state = LocalObservationState.fromRaw(cursor.getString(13)) ?: return null
        val actionRaw = cursor.stringOrNull(25)
        val actionKind = actionRaw?.let { raw ->
            TrafficSignActionKind.entries.firstOrNull { it.wireValue == raw } ?: return null
        }
        val resolutionRaw = cursor.stringOrNull(26)
        val resolvedLimitKind = resolutionRaw?.let { raw ->
            TrafficSignResolvedLimitKind.entries.firstOrNull { it.wireValue == raw } ?: return null
        }
        val directionRaw = cursor.stringOrNull(27)
        val directionScope = if (directionRaw == null) {
            TrafficSignTravelDirection.UNKNOWN
        } else {
            TrafficSignTravelDirection.entries.firstOrNull { it.wireValue == directionRaw } ?: return null
        }
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
            state = state,
            devicePseudoId = cursor.getString(14),
            updatedAtUTC = cursor.getString(15),
            exportId = cursor.stringOrNull(16),
            oldSpeedKmh = cursor.intOrNull(17),
            newSpeedKmh = cursor.intOrNull(18),
            evidenceJson = cursor.stringOrNull(19),
            evidenceSummary = cursor.stringOrNull(20),
            primaryWayId = cursor.stringOrNull(21),
            effectiveAtUTC = cursor.stringOrNull(22) ?: cursor.getString(10),
            finalizedEventId = cursor.stringOrNull(23),
            runtimeApplicable = cursor.getInt(24) != 0,
            actionKind = actionKind,
            resolvedLimitKind = resolvedLimitKind,
            directionScope = directionScope,
            permanent = cursor.getInt(28) != 0,
            unconditional = cursor.getInt(29) != 0,
            osmTagKey = cursor.stringOrNull(30),
            canonicalValue = cursor.stringOrNull(31),
            supersededForExport = cursor.getInt(32) != 0,
        )
    }

    private fun isRuntimeApplicableCorrection(
        observation: LocalObservation,
        currentDirection: TrafficSignTravelDirection,
    ): Boolean {
        if (!observation.runtimeApplicable) return false
        if (observation.modality == LocalObservationModality.COMPUTER_VISION) {
            if (observation.state !in setOf(
                    LocalObservationState.LOCAL_ONLY,
                    LocalObservationState.APPROVED_FOR_EXPORT,
                    LocalObservationState.EXPORTED_OSC,
                )
            ) return false
        } else if (observation.state == LocalObservationState.DISCARDED) {
            // Legacy voice/manual NEEDS_REVIEW rows remain locally applicable.
            return false
        }
        if (observation.intentType != LocalObservationIntentType.SET_MAXSPEED) return false
        if (!observation.permanent || !observation.unconditional) return false
        if (!isPositiveOsmWayId(observation.wayId)) return false
        if (!isCanonicalMaxspeedValue(observation.newSpeedValue)) return false
        if (observation.actionKind == null || observation.resolvedLimitKind == null) return false
        if (!isTypedSetAction(observation.actionKind)) return false
        if (observation.resolvedLimitKind == TrafficSignResolvedLimitKind.UNKNOWN) return false
        if (observation.modality == LocalObservationModality.COMPUTER_VISION && !hasSafeComputerVisionEvidence(observation)) {
            return false
        }
        if (observation.directionScope != TrafficSignTravelDirection.UNKNOWN &&
            observation.directionScope != currentDirection
        ) return false
        return when (observation.directionScope) {
            TrafficSignTravelDirection.FORWARD -> observation.osmTagKey == "maxspeed:forward"
            TrafficSignTravelDirection.REVERSE -> observation.osmTagKey == "maxspeed:backward"
            TrafficSignTravelDirection.UNKNOWN -> observation.osmTagKey == "maxspeed"
        }
    }

    private fun latestRuntimeApplicableObservation(
        db: SQLiteDatabase,
        wayId: String,
        direction: TrafficSignTravelDirection,
    ): LocalObservation? = db.rawQuery(
        """
        SELECT observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
               city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
               device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh,
               evidence_json, evidence_summary, primary_way_id, effective_at_utc, finalized_event_id,
               runtime_applicable, action_kind, resolved_limit_kind, direction_scope, permanent,
               unconditional, osm_tag_key, canonical_value, superseded_for_export
        FROM observations
        WHERE primary_way_id = ? AND runtime_applicable = 1
          AND direction_scope IN (?, ?)
        ORDER BY julianday(effective_at_utc) DESC, rowid DESC
        """.trimIndent(),
        arrayOf(
            wayId,
            direction.wireValue,
            TrafficSignTravelDirection.UNKNOWN.wireValue,
        ),
    ).use { cursor ->
        while (cursor.moveToNext()) {
            val observation = decodeObservation(cursor) ?: continue
            if (isRuntimeApplicableCorrection(observation, direction)) return@use observation
        }
        null
    }

    private fun LocalObservation.toRuntimeCorrection(): LocalRuntimeCorrection = LocalRuntimeCorrection(
        observationId = id,
        wayId = requireNotNull(wayId),
        tagKey = requireNotNull(osmTagKey),
        canonicalValue = requireNotNull(newSpeedValue),
        numericSpeedKmh = newSpeedKmh ?: newSpeedValue?.toIntOrNull(),
        directionScope = directionScope,
        effectiveAtUtc = effectiveAtUTC,
    )

    private fun isExportableCorrection(observation: LocalObservation): Boolean {
        if (observation.state != LocalObservationState.APPROVED_FOR_EXPORT || observation.supersededForExport) return false
        return isStructurallyExportableCorrection(observation)
    }

    /**
     * Preserves the original direct/manual bulk-export workflow while keeping
     * camera-derived corrections behind explicit review. Single-item export is
     * intentionally still approval-only for every modality.
     */
    private fun isBulkExportableCorrection(observation: LocalObservation): Boolean {
        if (observation.supersededForExport) return false
        val stateEligible = if (observation.modality == LocalObservationModality.COMPUTER_VISION) {
            observation.state == LocalObservationState.APPROVED_FOR_EXPORT
        } else {
            observation.state in setOf(
                LocalObservationState.LOCAL_ONLY,
                LocalObservationState.NEEDS_REVIEW,
                LocalObservationState.APPROVED_FOR_EXPORT,
            )
        }
        return stateEligible && isStructurallyExportableCorrection(observation)
    }

    private fun isStructurallyExportableCorrection(observation: LocalObservation): Boolean {
        if (!observation.runtimeApplicable || observation.intentType != LocalObservationIntentType.SET_MAXSPEED) return false
        if (!observation.permanent || !observation.unconditional) return false
        if (!isPositiveOsmWayId(observation.wayId) || !isCanonicalMaxspeedValue(observation.newSpeedValue)) return false
        if (observation.actionKind == null || observation.resolvedLimitKind == null ||
            observation.resolvedLimitKind == TrafficSignResolvedLimitKind.UNKNOWN
        ) return false
        if (!isTypedSetAction(observation.actionKind)) return false
        return when (observation.directionScope) {
            TrafficSignTravelDirection.FORWARD -> observation.osmTagKey == "maxspeed:forward"
            TrafficSignTravelDirection.REVERSE -> observation.osmTagKey == "maxspeed:backward"
            TrafficSignTravelDirection.UNKNOWN -> observation.osmTagKey == "maxspeed"
        } && (observation.modality != LocalObservationModality.COMPUTER_VISION || hasSafeComputerVisionEvidence(observation))
    }

    private fun hasNewerConflictingEvidence(db: SQLiteDatabase, observation: LocalObservation): Boolean {
        val rowId = observationRowId(db, observation.id) ?: return true
        return db.rawQuery(
            """
            SELECT 1 FROM observations
            WHERE primary_way_id = ? AND ${overlappingTargetSql()} AND observation_id != ?
              AND (
                julianday(effective_at_utc) > julianday(?)
                OR (julianday(effective_at_utc) = julianday(?) AND rowid > ?)
              )
              AND state != ? AND canonical_value IS NOT ?
            LIMIT 1
            """.trimIndent(),
            arrayOf(
                observation.wayId,
                observation.osmTagKey,
                observation.directionScope.wireValue,
                observation.osmTagKey,
                observation.id,
                observation.effectiveAtUTC,
                observation.effectiveAtUTC,
                rowId.toString(),
                LocalObservationState.DISCARDED.rawValue,
                observation.newSpeedValue,
            ),
        ).use { it.moveToFirst() }
    }

    private fun isLatestTargetObservation(db: SQLiteDatabase, observation: LocalObservation): Boolean {
        db.rawQuery(
            """
            SELECT observation_id, modality, intent_type, value, lat, lon, heading_deg, road_candidate_ids,
                   city_context, street_context, captured_at_utc, confidence_calibrated, source_version, state,
                   device_pseudo_id, updated_at_utc, export_id, old_speed_kmh, new_speed_kmh,
                   evidence_json, evidence_summary, primary_way_id, effective_at_utc, finalized_event_id,
                   runtime_applicable, action_kind, resolved_limit_kind, direction_scope, permanent,
                   unconditional, osm_tag_key, canonical_value, superseded_for_export
            FROM observations
            WHERE primary_way_id = ? AND ${overlappingTargetSql()} AND state != ?
            ORDER BY julianday(effective_at_utc) DESC, rowid DESC
            """.trimIndent(),
            arrayOf(
                observation.wayId,
                observation.osmTagKey,
                observation.directionScope.wireValue,
                observation.osmTagKey,
                LocalObservationState.DISCARDED.rawValue,
            ),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val candidate = decodeObservation(cursor) ?: continue
                if (!isStructurallyExportableCorrection(candidate)) continue
                return candidate.id == observation.id
            }
        }
        return false
    }

    /** Generic maxspeed and either directional maxspeed address overlapping OSM state. */
    private fun overlappingTargetSql(): String =
        """(
            (osm_tag_key = ? AND direction_scope = ?)
            OR (osm_tag_key = 'maxspeed' AND direction_scope = 'unknown')
            OR (? = 'maxspeed' AND osm_tag_key IN ('maxspeed:forward', 'maxspeed:backward'))
        )""".trimIndent()

    private fun observationRowId(db: SQLiteDatabase, observationId: String): Long? = db.rawQuery(
        "SELECT rowid FROM observations WHERE observation_id = ? LIMIT 1",
        arrayOf(observationId),
    ).use { cursor -> if (cursor.moveToFirst()) cursor.getLong(0) else null }

    private fun isTypedSetAction(kind: TrafficSignActionKind): Boolean = kind in setOf(
        TrafficSignActionKind.POSTED_MAXIMUM,
        TrafficSignActionKind.ZONE_START,
        TrafficSignActionKind.ZONE_END,
        TrafficSignActionKind.MAXIMUM_SPEED_END,
        TrafficSignActionKind.ALL_RESTRICTIONS_END,
        TrafficSignActionKind.CITY_ENTRY,
        TrafficSignActionKind.CITY_EXIT,
        TrafficSignActionKind.PEDESTRIAN_ZONE_START,
        TrafficSignActionKind.PEDESTRIAN_ZONE_END,
        TrafficSignActionKind.MOTORWAY_EXIT,
        TrafficSignActionKind.MOTORROAD_EXIT,
    )

    private fun exportTargetKey(observation: LocalObservation): String =
        "way:${requireNotNull(observation.wayId).trim()}|tag:${requireNotNull(observation.osmTagKey)}|direction:${observation.directionScope.wireValue}"

    private fun supersedeApprovedForTarget(
        db: SQLiteDatabase,
        exceptObservationId: String,
        wayId: String,
        tagKey: String,
        direction: TrafficSignTravelDirection,
        updatedAtUtc: String,
        incomingEffectiveAtUtc: String,
        incomingRowId: Long,
    ) {
        db.execSQL(
            """
            UPDATE observations SET superseded_for_export = 1, updated_at_utc = ?
            WHERE observation_id != ? AND primary_way_id = ? AND ${overlappingTargetSql()}
              AND state = ?
              AND (
                julianday(effective_at_utc) < julianday(?)
                OR (julianday(effective_at_utc) = julianday(?) AND rowid < ?)
              )
            """.trimIndent(),
            arrayOf(
                updatedAtUtc,
                exceptObservationId,
                wayId,
                tagKey,
                direction.wireValue,
                tagKey,
                LocalObservationState.APPROVED_FOR_EXPORT.rawValue,
                incomingEffectiveAtUtc,
                incomingEffectiveAtUtc,
                incomingRowId,
            ),
        )
    }

    /**
     * A new typed correction wins over any crash-left pending package for the
     * same effective OSM target. This runs inside the writer's DB transaction,
     * so a competing exporter observes either the old or the new state, never
     * a recoverable old snapshot followed by the newer row.
     */
    private fun stalePendingExportsForIncomingTarget(
        db: SQLiteDatabase,
        wayId: String,
        tagKey: String,
        direction: TrafficSignTravelDirection,
        incomingEffectiveAtUtc: String,
        incomingRowId: Long? = null,
    ) {
        val batches = db.rawQuery(
            """
            SELECT DISTINCT b.batch_id, b.package_path, b.payload_sha256, b.export_mode,
                            o.osm_tag_key, o.direction_scope, o.effective_at_utc, o.rowid
            FROM local_observation_export_batches b
            JOIN local_observation_export_members m ON m.batch_id = b.batch_id
            JOIN observations o ON o.observation_id = m.observation_id
            WHERE b.status = 'pending' AND m.reservation_status = 'pending'
              AND o.primary_way_id = ?
            """.trimIndent(),
            arrayOf(wayId),
        ).use { cursor ->
            buildList {
                while (cursor.moveToNext()) {
                    val existingTag = cursor.stringOrNull(4) ?: continue
                    val existingDirection = cursor.stringOrNull(5)?.let { raw ->
                        TrafficSignTravelDirection.entries.firstOrNull { it.wireValue == raw }
                    } ?: continue
                    val existingEffectiveAtUtc = cursor.stringOrNull(6) ?: continue
                    val existingRowId = cursor.getLong(7)
                    if (targetsOverlap(existingTag, existingDirection, tagKey, direction) &&
                        incomingCorrectionIsNewer(
                            incomingEffectiveAtUtc = incomingEffectiveAtUtc,
                            incomingRowId = incomingRowId,
                            existingEffectiveAtUtc = existingEffectiveAtUtc,
                            existingRowId = existingRowId,
                        )
                    ) {
                        add(PendingExportBatch(cursor.getString(0), cursor.getString(1), cursor.getString(2), cursor.getString(3)))
                    }
                }
            }.distinctBy(PendingExportBatch::id)
        }
        batches.forEach { batch ->
            quarantinePendingExportDirectory(batch)
            db.execSQL(
                "UPDATE local_observation_export_members SET reservation_status = 'stale' WHERE batch_id = ? AND reservation_status = 'pending'",
                arrayOf(batch.id),
            )
            db.execSQL(
                "UPDATE local_observation_export_batches SET status = 'stale' WHERE batch_id = ? AND status = 'pending'",
                arrayOf(batch.id),
            )
        }
    }

    private fun incomingCorrectionIsNewer(
        incomingEffectiveAtUtc: String,
        incomingRowId: Long?,
        existingEffectiveAtUtc: String,
        existingRowId: Long,
    ): Boolean {
        val incoming = runCatching { java.time.Instant.parse(incomingEffectiveAtUtc) }.getOrNull() ?: return false
        val existing = runCatching { java.time.Instant.parse(existingEffectiveAtUtc) }.getOrNull() ?: return false
        return incoming > existing || (incoming == existing && (incomingRowId == null || incomingRowId > existingRowId))
    }

    private fun targetsOverlap(
        firstTag: String,
        firstDirection: TrafficSignTravelDirection,
        secondTag: String,
        secondDirection: TrafficSignTravelDirection,
    ): Boolean {
        if (firstTag == secondTag && firstDirection == secondDirection) return true
        val firstGeneric = firstTag == "maxspeed" && firstDirection == TrafficSignTravelDirection.UNKNOWN
        val secondGeneric = secondTag == "maxspeed" && secondDirection == TrafficSignTravelDirection.UNKNOWN
        return firstGeneric || secondGeneric
    }

    private fun hasPendingExportMember(db: SQLiteDatabase, observationId: String): Boolean = db.rawQuery(
        "SELECT 1 FROM local_observation_export_members WHERE observation_id = ? AND reservation_status = 'pending' LIMIT 1",
        arrayOf(observationId),
    ).use { it.moveToFirst() }

    private fun hasAnyPendingExportMembers(db: SQLiteDatabase): Boolean = db.rawQuery(
        "SELECT 1 FROM local_observation_export_members WHERE reservation_status = 'pending' LIMIT 1",
        null,
    ).use { it.moveToFirst() }

    /**
     * Recovers a package renamed before a DB commit, or abandons a reservation
     * whose frozen observation/typed target is no longer current. Abandoning
     * releases both partial unique indexes before a newer winner is approved.
     */
    private fun reconcilePendingExports(db: SQLiteDatabase, excludingBatchId: String? = null) {
        val batches = db.rawQuery(
            "SELECT batch_id, package_path, payload_sha256, export_mode FROM local_observation_export_batches WHERE status = 'pending'",
            null,
        ).use { cursor ->
            buildList {
                while (cursor.moveToNext()) {
                    add(PendingExportBatch(cursor.getString(0), cursor.getString(1), cursor.getString(2), cursor.getString(3)))
                }
            }
        }
        batches.filterNot { it.id == excludingBatchId }.forEach { batch ->
            val members = db.rawQuery(
                "SELECT observation_id, target_key, observation_revision FROM local_observation_export_members WHERE batch_id = ? AND reservation_status = 'pending' ORDER BY ordinal",
                arrayOf(batch.id),
            ).use { cursor ->
                buildList {
                    while (cursor.moveToNext()) add(PendingExportMember(cursor.getString(0), cursor.getString(1), cursor.getString(2)))
                }
            }
            val current = members.mapNotNull { member ->
                fetchObservation(db, member.observationId)?.let { member to it }
            }
            val snapshotCurrent = members.isNotEmpty() && current.size == members.size && current.all { (member, observation) ->
                val exportable = when (batch.exportMode) {
                    "bulk" -> isBulkExportableCorrection(observation)
                    "single" -> isExportableCorrection(observation)
                    else -> false
                }
                observation.updatedAtUTC == member.observationRevision &&
                    exportTargetKeyOrNull(observation) == member.targetKey &&
                    exportable &&
                    isLatestTargetObservation(db, observation) &&
                    !hasNewerConflictingEvidence(db, observation)
            }
            val publishedDirectory = File(batch.packagePath)
            val publishedChanges = File(publishedDirectory, "changes.osc")
            val publishedMatches = publishedChanges.isFile && sha256Hex(publishedChanges.readBytes()) == batch.payloadSha256
            when {
                snapshotCurrent && publishedMatches -> {
                    val finalizedAtUtc = clock.instant().toString()
                    current.forEach { (member, observation) ->
                        val updated = db.compileStatement(
                            """
                            UPDATE observations SET state = ?, updated_at_utc = ?, export_id = ?
                            WHERE observation_id = ? AND state = ? AND updated_at_utc = ? AND superseded_for_export = 0
                            """.trimIndent(),
                        ).use { statement ->
                            statement.bindString(1, LocalObservationState.EXPORTED_OSC.rawValue)
                            statement.bindString(2, finalizedAtUtc)
                            statement.bindString(3, batch.id)
                            statement.bindString(4, observation.id)
                            statement.bindString(5, observation.state.rawValue)
                            statement.bindString(6, member.observationRevision)
                            statement.executeUpdateDelete()
                        }
                        require(updated == 1) { "Unable to recover export member ${observation.id}" }
                    }
                    db.execSQL(
                        "UPDATE local_observation_export_members SET reservation_status = 'finalized' WHERE batch_id = ? AND reservation_status = 'pending'",
                        arrayOf(batch.id),
                    )
                    db.execSQL(
                        "UPDATE local_observation_export_batches SET status = 'finalized', finalized_at_utc = ? WHERE batch_id = ? AND status = 'pending'",
                        arrayOf(finalizedAtUtc, batch.id),
                    )
                }
                else -> {
                    // Only a fully published, hash-matching package is recoverable. A hidden
                    // .pending directory (or no directory at all) means the previous writer
                    // did not reach publication; abandon it so the partial unique target and
                    // observation reservations cannot block the next current correction.
                    quarantinePendingExportDirectory(batch)
                    db.execSQL(
                        "UPDATE local_observation_export_members SET reservation_status = 'stale' WHERE batch_id = ? AND reservation_status = 'pending'",
                        arrayOf(batch.id),
                    )
                    db.execSQL(
                        "UPDATE local_observation_export_batches SET status = 'stale' WHERE batch_id = ? AND status = 'pending'",
                        arrayOf(batch.id),
                    )
                }
            }
        }
    }

    private fun exportTargetKeyOrNull(observation: LocalObservation): String? = runCatching {
        exportTargetKey(observation)
    }.getOrNull()

    private fun quarantinePendingExportDirectory(batch: PendingExportBatch) {
        val published = File(batch.packagePath)
        val pending = File(published.parentFile, ".${published.name}.pending")
        listOf(published, pending).filter(File::exists).forEach { directory ->
            val quarantine = File(directory.parentFile, ".${directory.name}.stale-${batch.id.takeLast(12)}")
            if (!quarantine.exists()) directory.renameTo(quarantine)
        }
    }

    private fun abandonPendingExport(batchId: String) {
        withDatabase { db ->
            db.beginTransaction()
            try {
                val batch = db.rawQuery(
                    "SELECT batch_id, package_path, payload_sha256, export_mode FROM local_observation_export_batches WHERE batch_id = ? AND status = 'pending' LIMIT 1",
                    arrayOf(batchId),
                ).use { cursor ->
                    if (cursor.moveToFirst()) {
                        PendingExportBatch(cursor.getString(0), cursor.getString(1), cursor.getString(2), cursor.getString(3))
                    } else {
                        null
                    }
                }
                if (batch != null) {
                    quarantinePendingExportDirectory(batch)
                    db.execSQL(
                        "UPDATE local_observation_export_members SET reservation_status = 'stale' WHERE batch_id = ? AND reservation_status = 'pending'",
                        arrayOf(batchId),
                    )
                    db.execSQL(
                        "UPDATE local_observation_export_batches SET status = 'stale' WHERE batch_id = ? AND status = 'pending'",
                        arrayOf(batchId),
                    )
                }
                db.setTransactionSuccessful()
            } finally {
                db.endTransaction()
            }
        }
    }

    private data class PendingExportBatch(
        val id: String,
        val packagePath: String,
        val payloadSha256: String,
        val exportMode: String,
    )
    private data class PendingExportMember(val observationId: String, val targetKey: String, val observationRevision: String)

    /**
     * Validates the canonical passage wire event and binds it to every
     * denormalized field used by runtime lookup or OSC export. Treating the
     * JSON as a bag of positive booleans would allow a corrupted temporary,
     * unresolved, wrong-way, or wrong-value event to authorize the row.
     */
    private fun hasSafeComputerVisionEvidence(observation: LocalObservation): Boolean = runCatching {
        fun requiredObject(parent: JSONObject, key: String): JSONObject = requireNotNull(parent.optJSONObject(key))
        fun requiredArray(parent: JSONObject, key: String): JSONArray = requireNotNull(parent.optJSONArray(key))
        fun requiredString(parent: JSONObject, key: String): String = parent.getString(key).also {
            require(it.isNotBlank())
        }
        fun probability(parent: JSONObject, key: String): Double = parent.getDouble(key).also {
            require(it.isFinite() && it in 0.0..1.0)
        }
        fun positiveIds(array: JSONArray): Set<Long> {
            val ids = buildList {
                repeat(array.length()) { index -> add(array.getLong(index).also { require(it > 0L) }) }
            }
            require(ids.distinct().size == ids.size)
            return ids.toSet()
        }

        require(observation.modality == LocalObservationModality.COMPUTER_VISION)
        require(observation.intentType == LocalObservationIntentType.SET_MAXSPEED)
        require(observation.permanent && observation.unconditional)
        val rowEventId = requireNotNull(observation.finalizedEventId).also { require(it.isNotBlank()) }
        val rowWayId = requireNotNull(observation.wayId).also { require(isPositiveOsmWayId(it)) }
        val rowTagKey = requireNotNull(observation.osmTagKey)
        val rowValue = requireNotNull(observation.canonicalValue).also { require(isCanonicalMaxspeedValue(it)) }
        val rowActionKind = requireNotNull(observation.actionKind).also { require(isTypedSetAction(it)) }
        val rowResolutionKind = requireNotNull(observation.resolvedLimitKind).also {
            require(it != TrafficSignResolvedLimitKind.UNKNOWN)
        }
        val evidence = JSONObject(requireNotNull(observation.evidenceJson))
        require(evidence.getInt("schema_version") == 1)
        require(requiredString(evidence, "event_kind") == "traffic_sign_passage")
        require(requiredString(evidence, "finalized_event_id") == rowEventId)
        requiredString(evidence, "drive_session_id")
        require(evidence.getLong("tsr_generation") >= 0L)
        java.time.Instant.parse(requiredString(evidence, "committed_at_utc"))

        val pack = requiredObject(evidence, "pack")
        requiredString(pack, "pack_id")
        require(requiredString(pack, "taxonomy_version") == "tsr-structural-action-v1")
        require(requiredString(pack, "execution_mode") == "live")
        require(pack.getBoolean("override_eligible"))
        require(requiredString(pack, "calibration_status") in setOf("passed", "raw_score"))
        val components = requiredArray(pack, "components")
        require(components.length() > 0)
        val componentRoles = buildList {
            repeat(components.length()) { index ->
                val component = components.getJSONObject(index)
                val role = requiredString(component, "role")
                require(role in setOf("proposal_detector", "semantic_classifier", "direct_detector"))
                require(VERIFIED_SHA256.matches(requiredString(component, "artifact_sha256")))
                requiredString(component, "preprocessing_version")
                requiredString(component, "calibration_id")
                add(role)
            }
        }
        require(componentRoles.distinct().size == componentRoles.size)
        require(
            componentRoles.toSet() == setOf("direct_detector") ||
                componentRoles.toSet() == setOf("proposal_detector", "semantic_classifier"),
        )

        val track = requiredObject(evidence, "track")
        requiredString(track, "physical_track_id")
        require(requiredArray(track, "assembly_ids").length() > 0)
        require(track.getInt("frames_seen") > 0)
        require(track.getInt("peak_consecutive_frames_seen") in 1..track.getInt("frames_seen"))
        val finalConfidence = probability(
            track,
            if (track.has("final_confidence")) "final_confidence" else "final_calibrated_confidence",
        )
        require(observation.confidenceCalibrated == finalConfidence)
        probability(track, "final_accumulated_support")
        require(requiredArray(track, "frame_evidence").length() > 0)
        require(requiredArray(track, "loss_evidence").length() > 0)

        val action = requiredObject(evidence, "action")
        require(requiredString(action, "kind") == rowActionKind.wireValue)
        require(requiredString(action, "permanence") == "permanent")
        require(requiredString(action, "condition_state") == "none")
        require(requiredArray(action, "restrictions").length() == 0)
        when (rowActionKind) {
            TrafficSignActionKind.POSTED_MAXIMUM,
            TrafficSignActionKind.ZONE_START -> require(action.getInt("value_kmh").toString() == rowValue)
            TrafficSignActionKind.CITY_ENTRY -> {
                require(requiredString(action, "country") == "DE")
                require(rowResolutionKind == TrafficSignResolvedLimitKind.NUMERIC && rowValue == "50")
            }
            TrafficSignActionKind.PEDESTRIAN_ZONE_START ->
                require(rowResolutionKind == TrafficSignResolvedLimitKind.WALK && rowValue == "walk")
            TrafficSignActionKind.MAXIMUM_SPEED_END,
            TrafficSignActionKind.ZONE_END -> if (action.has("ended_value_kmh")) {
                require(isSharedTrafficSignSpeedKmh(action.getInt("ended_value_kmh")))
            }
            TrafficSignActionKind.ALL_RESTRICTIONS_END,
            TrafficSignActionKind.CITY_EXIT,
            TrafficSignActionKind.PEDESTRIAN_ZONE_END,
            TrafficSignActionKind.MOTORWAY_EXIT,
            TrafficSignActionKind.MOTORROAD_EXIT -> Unit
            TrafficSignActionKind.TEMPORARY_MAXIMUM,
            TrafficSignActionKind.NON_SPEED_RESTRICTION_END,
            TrafficSignActionKind.UNKNOWN -> error("Review-only action cannot authorize a CV correction")
        }

        val resolution = requiredObject(evidence, "resolution")
        require(requiredString(resolution, "runtime_status") == "resolved")
        require(!resolution.getBoolean("masks_stale_camera_assertion"))
        val presentation = requiredObject(resolution, "presentation")
        require(requiredString(presentation, "kind") == rowResolutionKind.wireValue)
        when (rowResolutionKind) {
            TrafficSignResolvedLimitKind.NUMERIC -> {
                val speed = rowValue.toIntOrNull()
                require(speed != null && isSharedTrafficSignSpeedKmh(speed))
                require(presentation.getInt("value_kmh") == speed)
                require(observation.newSpeedKmh == speed)
            }
            TrafficSignResolvedLimitKind.WALK -> require(rowValue == "walk" && observation.newSpeedKmh == null)
            TrafficSignResolvedLimitKind.UNLIMITED -> require(rowValue == "none" && observation.newSpeedKmh == null)
            TrafficSignResolvedLimitKind.UNKNOWN -> error("Unknown CV resolution cannot be runtime-applicable")
        }
        val operation = requiredObject(resolution, "normalized_operation")
        require(requiredString(operation, "operation") == "set_maxspeed")
        require(requiredString(operation, "tag_key") == rowTagKey)
        require(requiredString(operation, "tag_value") == rowValue)
        val expectedOperationDirection = when (observation.directionScope) {
            TrafficSignTravelDirection.FORWARD -> "forward"
            TrafficSignTravelDirection.REVERSE -> "backward"
            TrafficSignTravelDirection.UNKNOWN -> "way"
        }
        val expectedActivationDirection = when (observation.directionScope) {
            TrafficSignTravelDirection.FORWARD -> "forward"
            TrafficSignTravelDirection.REVERSE -> "reverse"
            TrafficSignTravelDirection.UNKNOWN -> "unknown"
        }
        require(requiredString(operation, "direction_scope") == expectedOperationDirection)
        require(rowTagKey == when (observation.directionScope) {
            TrafficSignTravelDirection.FORWARD -> "maxspeed:forward"
            TrafficSignTravelDirection.REVERSE -> "maxspeed:backward"
            TrafficSignTravelDirection.UNKNOWN -> "maxspeed"
        })

        val boundary = requiredObject(evidence, "boundary")
        require(java.time.Instant.parse(requiredString(boundary, "timestamp_utc")).toString() == observation.effectiveAtUTC)
        val activation = requiredObject(evidence, "activation")
        require(requiredString(activation, "way_id") == rowWayId)
        require(requiredString(activation, "travel_direction") == expectedActivationDirection)
        require(activation.getDouble("latitude") == observation.lat)
        require(activation.getDouble("longitude") == observation.lon)
        require(activation.getDouble("heading_degrees") == observation.headingDeg)
        require(requiredString(activation, "reason") in setOf("boundary_stable_match", "first_stabilized_same_scope_rematch"))
        java.time.Instant.parse(requiredString(activation, "timestamp_utc"))
        requiredString(activation, "source_signature")
        require(activation.getLong("pending_rematch_elapsed_ms") >= 0L)
        require(activation.getDouble("pending_rematch_distance_m").let { it.isFinite() && it >= 0.0 })
        val activationGroups = positiveIds(requiredArray(activation, "route_relation_group_ids"))

        val scope = requiredObject(evidence, "applicability_scope")
        requiredString(scope, "bundle_id")
        require(VERIFIED_SHA256.matches(requiredString(scope, "bundle_sha256")))
        requiredString(scope, "continuity_epoch_id")
        val originalWayId = requiredString(scope, "original_way_id").also { require(isPositiveOsmWayId(it)) }
        scope.getBoolean("continuity_capable_bundle")
        positiveIds(requiredArray(scope, "initial_route_relation_group_ids"))
        val eligibleGroups = positiveIds(requiredArray(scope, "eligible_route_relation_group_ids"))
        positiveIds(requiredArray(scope, "source_relation_ids"))
        require(originalWayId == rowWayId || eligibleGroups.intersect(activationGroups).isNotEmpty())

        val persistence = requiredObject(evidence, "persistence")
        require(requiredString(persistence, "observation_intent") == observation.intentType.rawValue)
        require(requiredString(persistence, "review_state") == LocalObservationState.LOCAL_ONLY.rawValue)
        require(persistence.getBoolean("runtime_applicable"))
        require(!persistence.getBoolean("export_eligible_at_commit"))
        require(persistence.getBoolean("finalized_event_id_is_idempotency_key"))

        val privacy = requiredObject(evidence, "privacy")
        require(!privacy.getBoolean("raw_frame_persisted"))
        require(!privacy.getBoolean("crop_persisted"))
        require(!privacy.getBoolean("image_path_persisted"))
        true
    }.getOrDefault(false)

    private fun makeComputerVisionEvidenceJson(
        event: TrafficSignPassageEvent,
        resolvedLimit: TrafficSignResolvedLimit,
        runtimeApplicable: Boolean,
        reviewState: LocalObservationState,
        intentType: LocalObservationIntentType,
        osmTagKey: String?,
    ): JSONObject {
        val activation = requireNotNull(event.activationContext)
        val original = requireNotNull(event.firstSeenContext)
        val boundaryContext = event.passageBoundary.context ?: event.lastSeenContext ?: original
        val boundaryWayId = event.passageBoundary.context?.wayId?.trim()?.takeIf(::isPositiveOsmWayId)
        val activationWayId = requireNotNull(activation.wayId?.trim()?.takeIf(::isPositiveOsmWayId))
        val originalWayId = requireNotNull(original.wayId?.trim()?.takeIf(::isPositiveOsmWayId))
        val bundleSha256 = requireNotNull(activation.bundleSha256)
        val committedAtUtc = event.lossEvidence.last().timestampUtc
        val calibratedConfidence = event.evidence.mapNotNull { it.calibratedConfidence }.maxOrNull()
        val unresolvedEnd = resolvedLimit.kind == TrafficSignResolvedLimitKind.UNKNOWN && event.action.kind in END_ACTION_KINDS
        val runtimeStatus = when {
            runtimeApplicable -> "resolved"
            unresolvedEnd -> "unresolved_end"
            else -> "review_only"
        }
        val normalizedOperation = if (runtimeApplicable) {
            JSONObject()
                .put("operation", "set_maxspeed")
                .put("tag_key", requireNotNull(osmTagKey))
                .put("tag_value", requireNotNull(resolvedLimit.maxspeedValue))
                .put(
                    "direction_scope",
                    when (activation.travelDirection) {
                        TrafficSignTravelDirection.FORWARD -> "forward"
                        TrafficSignTravelDirection.REVERSE -> "backward"
                        TrafficSignTravelDirection.UNKNOWN -> "way"
                    },
                )
        } else {
            JSONObject.NULL
        }
        val actionJson = JSONObject()
            .put("kind", event.action.kind.wireValue)
            .put("permanence", if (event.action.kind == TrafficSignActionKind.TEMPORARY_MAXIMUM) "temporary" else "permanent")
            .put(
                "condition_state",
                when (event.action.conditionState) {
                    TrafficSignConditionState.NONE -> if (event.action.kind == TrafficSignActionKind.TEMPORARY_MAXIMUM) "resolved" else "none"
                    TrafficSignConditionState.RESOLVED -> "resolved"
                    TrafficSignConditionState.RESOLVING,
                    TrafficSignConditionState.UNRESOLVED -> "unresolved"
                },
            )
            .put(
                "restrictions",
                JSONArray().apply {
                    event.action.restrictions.forEach { restriction ->
                        put(
                            JSONObject()
                                .put("kind", restriction.kind.wireValue)
                                .put("evidence_state", "present_readable")
                                .put("normalized_value", restriction.normalizedValue),
                        )
                    }
                },
            )
        when (event.action.kind) {
            TrafficSignActionKind.POSTED_MAXIMUM,
            TrafficSignActionKind.ZONE_START,
            TrafficSignActionKind.TEMPORARY_MAXIMUM -> actionJson.put("value_kmh", event.action.valueKmh)
            TrafficSignActionKind.ZONE_END,
            TrafficSignActionKind.MAXIMUM_SPEED_END -> event.action.valueKmh?.let { actionJson.put("ended_value_kmh", it) }
            else -> Unit
        }
        if (event.action.kind in setOf(TrafficSignActionKind.CITY_ENTRY, TrafficSignActionKind.CITY_EXIT)) {
            actionJson.put("country", alpha2CountryCode(event.action.countryCode ?: activation.countryCode))
        }

        val resolutionJson = JSONObject()
            .put("runtime_status", runtimeStatus)
            .put("presentation", resolvedLimit.toSharedPresentationJson())
            .put(
                "resolution_basis",
                when {
                    unresolvedEnd || runtimeStatus == "review_only" -> "unresolved"
                    event.action.kind in setOf(TrafficSignActionKind.CITY_ENTRY, TrafficSignActionKind.CITY_EXIT) -> "country_policy"
                    event.action.kind in END_ACTION_KINDS -> "captured_prior_rule"
                    else -> "direct_sign"
                },
            )
            .put("normalized_operation", normalizedOperation)
            .put("masks_stale_camera_assertion", unresolvedEnd)
        if (unresolvedEnd) resolutionJson.put("unresolved_reason", "no_corroborated_surviving_speed_rule")

        val boundarySource = event.passageBoundary.context?.sourceSignature?.toSharedWireValue()
        val activationElapsedMs = Duration.between(event.passageBoundary.timestampUtc, event.activationAtUtc)
            .toMillis()
            .coerceAtLeast(0L)
        val activationAtBoundary = event.activationAtUtc == event.passageBoundary.timestampUtc &&
            boundaryWayId == activationWayId && event.passageBoundary.context?.matchedWayStable == true

        return JSONObject()
            .put("schema_version", 1)
            .put("event_kind", "traffic_sign_passage")
            .put("finalized_event_id", event.finalizedEventId)
            .put("drive_session_id", event.driveSessionId)
            .put("tsr_generation", event.generation)
            .put("committed_at_utc", committedAtUtc.toString())
            .put(
                "pack",
                JSONObject()
                    .put("pack_id", event.packId)
                    .put("taxonomy_version", "tsr-structural-action-v1")
                    .put("execution_mode", "live")
                    .put("override_eligible", true)
                    .put("calibration_status", if (calibratedConfidence == null) "raw_score" else "passed")
                    .put(
                        "components",
                        JSONArray().apply {
                            event.modelComponents.forEach { component ->
                                put(
                                    JSONObject()
                                        .put("role", component.role)
                                        .put("artifact_sha256", component.artifactSha256)
                                        .put("preprocessing_version", component.preprocessingVersion)
                                        .put("calibration_id", component.calibrationId),
                                )
                            }
                        },
                    ),
            )
            .put(
                "track",
                JSONObject()
                    .put("physical_track_id", event.physicalTrackId)
                    .put("assembly_ids", JSONArray(event.assemblyIds))
                    .put("first_seen_timestamp_utc", event.firstSeenAtUtc.toString())
                    .put("last_seen_timestamp_utc", event.lastSeenAtUtc.toString())
                    .put("frames_seen", event.framesSeen)
                    .put("peak_consecutive_frames_seen", event.peakConsecutiveFramesSeen)
                    .put("single_sighting_exception", event.framesSeen == 1)
                    .put("final_confidence", event.finalConfidence)
                    .put("confidence_basis", if (calibratedConfidence == null) "raw_score" else "calibrated_confidence")
                    .apply {
                        calibratedConfidence?.let { put("final_calibrated_confidence", it) }
                    }
                    .put("final_accumulated_support", event.finalAccumulatedSupport)
                    .put("accumulated_support_cap", 1.0)
                    .put("loss_reason", if (event.lossReason == "strong_pass_geometry") "strong_pass_geometry" else "negative_debounce")
                    .put("negative_frames_required", event.negativeFramesToCommit)
                    .put("frame_evidence", event.evidence.toSharedFrameEvidenceJson())
                    .put("loss_evidence", event.lossEvidence.toSharedLossEvidenceJson()),
            )
            .put("action", actionJson)
            .put("resolution", resolutionJson)
            .put(
                "boundary",
                JSONObject()
                    .put("frame_id", event.lossEvidence.first().frameId)
                    .put("timestamp_utc", event.passageBoundary.timestampUtc.toString())
                    .put("latitude", boundaryContext.latitude)
                    .put("longitude", boundaryContext.longitude)
                    .put("heading_degrees", boundaryContext.headingDegrees)
                    .put("speed_mps", boundaryContext.speedMetersPerSecond)
                    .put("travel_direction", boundaryContext.travelDirection.wireValue)
                    .put(
                        "map_match_state",
                        when {
                            boundaryWayId == null -> "no_match"
                            event.passageBoundary.context?.matchedWayStable == true -> "matched"
                            else -> "unstable"
                        },
                    )
                    .put("way_id", boundaryWayId ?: JSONObject.NULL)
                    .put("route_relation_group_ids", JSONArray(event.passageBoundary.context?.routeRelationGroupIds?.sorted().orEmpty()))
                    .put("source_signature", boundarySource ?: JSONObject.NULL),
            )
            .put(
                "activation",
                JSONObject()
                    .put("reason", if (activationAtBoundary) "boundary_stable_match" else "first_stabilized_same_scope_rematch")
                    .put("timestamp_utc", event.activationAtUtc.toString())
                    .put("latitude", activation.latitude)
                    .put("longitude", activation.longitude)
                    .put("heading_degrees", activation.headingDegrees)
                    .put("travel_direction", activation.travelDirection.wireValue)
                    .put("way_id", activationWayId)
                    .put("route_relation_group_ids", JSONArray(activation.routeRelationGroupIds.sorted()))
                    .put("source_signature", activation.sourceSignature.toSharedWireValue())
                    .put("pending_rematch_elapsed_ms", activationElapsedMs)
                    .put("pending_rematch_distance_m", event.pendingRematchDistanceM),
            )
            .put(
                "applicability_scope",
                JSONObject()
                    .put("bundle_id", activation.sourceSignature.bundleRevision)
                    .put("bundle_sha256", bundleSha256)
                    .put("continuity_epoch_id", "${event.driveSessionId}:${activation.traversalEpoch}")
                    .put("original_way_id", originalWayId)
                    .put("original_travel_direction", original.travelDirection.wireValue)
                    .put("continuity_capable_bundle", activation.continuityCapable)
                    .put("initial_route_relation_group_ids", JSONArray(event.initialRouteRelationGroupIds.sorted()))
                    .put("eligible_route_relation_group_ids", JSONArray(event.eligibleRouteRelationGroupIds.sorted()))
                    .put("source_relation_ids", JSONArray(event.sourceRelationIds.sorted())),
            )
            .put(
                "persistence",
                JSONObject()
                    .put("observation_intent", intentType.rawValue)
                    .put("review_state", reviewState.rawValue)
                    .put("runtime_applicable", runtimeApplicable)
                    .put("export_eligible_at_commit", false)
                    .put("finalized_event_id_is_idempotency_key", true),
            )
            .put(
                "privacy",
                JSONObject()
                    .put("raw_frame_persisted", false)
                    .put("crop_persisted", false)
                    .put("image_path_persisted", false),
            )
    }

    private fun List<TrafficSignPassageFrameEvidence>.toSharedFrameEvidenceJson() = JSONArray().apply {
        this@toSharedFrameEvidenceJson.forEach { evidence ->
            put(JSONObject()
                .put("frame_id", evidence.frameId)
                .put("timestamp_utc", evidence.timestampUtc.toString())
                .put("outcome", "seen")
                .put("analysis_eligible", true)
                .put("raw_score", evidence.rawScore)
                .put("accumulated_support", evidence.accumulatedSupport)
                .apply {
                    evidence.calibratedConfidence?.let { put("calibrated_confidence", it) }
                    evidence.proposalRawScore?.let { put("proposal_raw_score", it) }
                    evidence.proposalCalibratedConfidence?.let { put("proposal_calibrated_confidence", it) }
                    evidence.classifierRawScore?.let { put("classifier_raw_score", it) }
                    evidence.classifierCalibratedConfidence?.let { put("classifier_calibrated_confidence", it) }
                    evidence.assemblyConfidence?.let { put("assembly_confidence", it) }
                })
        }
    }

    private fun List<TrafficSignPassageLossEvidence>.toSharedLossEvidenceJson() = JSONArray().apply {
        this@toSharedLossEvidenceJson.forEach { evidence ->
            put(
                JSONObject()
                    .put("frame_id", evidence.frameId)
                    .put("timestamp_utc", evidence.timestampUtc.toString())
                    .put("outcome", "analyzed_missing")
                    .put("analysis_eligible", true)
                    .put("pass_geometry", if (evidence.strongPassGeometry) "strong" else "not_established"),
            )
        }
    }

    private fun TrafficSignResolvedLimit.toSharedPresentationJson(): JSONObject = when (kind) {
        TrafficSignResolvedLimitKind.NUMERIC -> JSONObject().put("kind", "numeric").put("value_kmh", speedKmh)
        TrafficSignResolvedLimitKind.WALK -> JSONObject().put("kind", "walk")
        TrafficSignResolvedLimitKind.UNLIMITED -> JSONObject().put("kind", "unlimited")
        TrafficSignResolvedLimitKind.UNKNOWN -> JSONObject().put("kind", "unknown")
    }

    private fun TrafficSignRuntimeSourceSignature.toSharedWireValue(): String = buildString {
        append(osmRevision)
        localCorrectionRevision?.let { append("|local:").append(it) }
    }

    private fun alpha2CountryCode(raw: String): String = when (val normalized = raw.trim().uppercase(Locale.US)) {
        "DEU" -> "DE"
        "FRA" -> "FR"
        "GBR" -> "GB"
        "USA" -> "US"
        else -> normalized.take(2).padEnd(2, 'X')
    }

    private fun TrafficSignDetectionContext.toEvidenceJson(): JSONObject = JSONObject()
        .put("way_id", wayId)
        .put("latitude", latitude)
        .put("longitude", longitude)
        .put("heading_degrees", headingDegrees)
        .put("travel_direction", travelDirection.wireValue)
        .put("bundle_sha256", bundleSha256)
        .put("country_code", countryCode)
        .put("continuity_capable", continuityCapable)
        .put("matched_way_stable", matchedWayStable)
        .put("traversal_epoch", traversalEpoch)
        .put("route_relation_group_ids", JSONArray(routeRelationGroupIds.sorted()))
        .put("source_relation_ids", JSONArray(sourceRelationIds.sorted()))
        .put(
            "source_signature",
            JSONObject()
                .put("osm_revision", sourceSignature.osmRevision)
                .put("local_correction_revision", sourceSignature.localCorrectionRevision),
        )

    private fun isPositiveOsmWayId(value: String?): Boolean =
        value != null && POSITIVE_OSM_WAY_ID.matches(value.trim())

    private fun isCanonicalMaxspeedValue(value: String?): Boolean {
        val normalized = value?.trim() ?: return false
        if (normalized in setOf("walk", "none")) return true
        val numeric = normalized.toIntOrNull() ?: return false
        return isSharedTrafficSignSpeedKmh(numeric) && normalized == numeric.toString()
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

    private fun makeBatchReviewJson(
        exportId: String,
        createdAtUtc: String,
        observations: List<LocalObservation>,
        payloadSha256: String,
    ): JSONObject = JSONObject()
        .put("export_id", exportId)
        .put("created_at_utc", createdAtUtc)
        .put("status", "pending_until_atomic_finalize")
        .put("payload_sha256", payloadSha256)
        .put("app_version", appVersion())
        .put("observation_ids", JSONArray(observations.map(LocalObservation::id)))
        .put(
            "targets",
            JSONArray().apply {
                observations.forEach { observation ->
                    put(
                        JSONObject()
                            .put("observation_id", observation.id)
                            .put("way_id", observation.wayId)
                            .put("tag_key", observation.osmTagKey)
                            .put("value", observation.newSpeedValue)
                            .put("direction_scope", observation.directionScope.wireValue)
                            .put("approved_revision", observation.updatedAtUTC),
                    )
                }
            },
        )
        .put("suggested_changeset_comment", "Update maxspeed based on reviewed YouSpeed observations")
        .put("suggested_changeset_source", "YouSpeed reviewed local observations")

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
              new_speed_kmh INTEGER,
              evidence_json TEXT,
              evidence_summary TEXT,
              primary_way_id TEXT,
              effective_at_utc TEXT,
              finalized_event_id TEXT,
              runtime_applicable INTEGER NOT NULL DEFAULT 0,
              action_kind TEXT,
              resolved_limit_kind TEXT,
              direction_scope TEXT NOT NULL DEFAULT 'unknown',
              permanent INTEGER NOT NULL DEFAULT 1,
              unconditional INTEGER NOT NULL DEFAULT 1,
              osm_tag_key TEXT,
              canonical_value TEXT,
              superseded_for_export INTEGER NOT NULL DEFAULT 0
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
              returned_changeset_id TEXT,
              status TEXT NOT NULL DEFAULT 'finalized',
              payload_xml TEXT,
              membership_key TEXT,
              observation_revisions TEXT,
              finalized_at_utc TEXT
            )
            """.trimIndent(),
        )
        ensureObservationColumn(db, "old_speed_kmh", "INTEGER")
        ensureObservationColumn(db, "new_speed_kmh", "INTEGER")
        ensureObservationColumn(db, "evidence_json", "TEXT")
        ensureObservationColumn(db, "evidence_summary", "TEXT")
        ensureObservationColumn(db, "primary_way_id", "TEXT")
        ensureObservationColumn(db, "effective_at_utc", "TEXT")
        ensureObservationColumn(db, "finalized_event_id", "TEXT")
        ensureObservationColumn(db, "runtime_applicable", "INTEGER NOT NULL DEFAULT 0")
        ensureObservationColumn(db, "action_kind", "TEXT")
        ensureObservationColumn(db, "resolved_limit_kind", "TEXT")
        ensureObservationColumn(db, "direction_scope", "TEXT NOT NULL DEFAULT 'unknown'")
        ensureObservationColumn(db, "permanent", "INTEGER NOT NULL DEFAULT 1")
        ensureObservationColumn(db, "unconditional", "INTEGER NOT NULL DEFAULT 1")
        ensureObservationColumn(db, "osm_tag_key", "TEXT")
        ensureObservationColumn(db, "canonical_value", "TEXT")
        ensureObservationColumn(db, "superseded_for_export", "INTEGER NOT NULL DEFAULT 0")
        ensureExportColumn(db, "status", "TEXT NOT NULL DEFAULT 'finalized'")
        ensureExportColumn(db, "payload_xml", "TEXT")
        ensureExportColumn(db, "membership_key", "TEXT")
        ensureExportColumn(db, "observation_revisions", "TEXT")
        ensureExportColumn(db, "finalized_at_utc", "TEXT")
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS idx_exports_membership ON exports(membership_key)")
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS idx_observations_finalized_event ON observations(finalized_event_id)")
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_observations_runtime_way_direction ON observations(primary_way_id, direction_scope, runtime_applicable, effective_at_utc DESC, observation_id DESC)")
        db.execSQL("CREATE INDEX IF NOT EXISTS idx_observations_export_target ON observations(primary_way_id, osm_tag_key, direction_scope, state, effective_at_utc DESC)")
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS cv_event_receipts (
              finalized_event_id TEXT PRIMARY KEY,
              processed_at_utc TEXT NOT NULL,
              observation_id TEXT,
              evidence_json TEXT,
              correction_created INTEGER NOT NULL DEFAULT 1
            )
            """.trimIndent(),
        )
        ensureCvReceiptColumn(db, "evidence_json", "TEXT")
        ensureCvReceiptColumn(db, "correction_created", "INTEGER NOT NULL DEFAULT 1")
        db.execSQL("UPDATE cv_event_receipts SET correction_created = 0 WHERE observation_id IS NULL")
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS local_observation_export_batches (
              batch_id TEXT PRIMARY KEY,
              created_at_utc TEXT NOT NULL,
              status TEXT NOT NULL,
              package_path TEXT NOT NULL,
              payload_sha256 TEXT NOT NULL,
              payload_xml TEXT NOT NULL,
              membership_key TEXT NOT NULL UNIQUE,
              finalized_at_utc TEXT,
              export_mode TEXT NOT NULL DEFAULT 'single'
            )
            """.trimIndent(),
        )
        ensureExportBatchColumn(db, "export_mode", "TEXT NOT NULL DEFAULT 'single'")
        db.execSQL(
            """
            CREATE TABLE IF NOT EXISTS local_observation_export_members (
              batch_id TEXT NOT NULL,
              observation_id TEXT NOT NULL,
              target_key TEXT NOT NULL,
              observation_revision TEXT NOT NULL,
              ordinal INTEGER NOT NULL,
              reservation_status TEXT NOT NULL,
              PRIMARY KEY (batch_id, observation_id)
            )
            """.trimIndent(),
        )
        db.execSQL(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_export_members_pending_observation
              ON local_observation_export_members(observation_id)
              WHERE reservation_status = 'pending'
            """.trimIndent(),
        )
        db.execSQL(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_export_members_pending_target
              ON local_observation_export_members(target_key)
              WHERE reservation_status = 'pending'
            """.trimIndent(),
        )
        db.execSQL(
            """
            CREATE INDEX IF NOT EXISTS idx_export_members_batch
              ON local_observation_export_members(batch_id, ordinal)
            """.trimIndent(),
        )
        backfillLegacyObservationShape(db)
    }

    private fun backfillLegacyObservationShape(db: SQLiteDatabase) {
        db.execSQL(
            """
            UPDATE observations
               SET primary_way_id = CASE
                     WHEN primary_way_id IS NOT NULL THEN primary_way_id
                     WHEN road_candidate_ids LIKE '["%' THEN
                       substr(road_candidate_ids, 3, instr(substr(road_candidate_ids, 3), '"') - 1)
                     ELSE primary_way_id
                   END,
                   effective_at_utc = COALESCE(effective_at_utc, captured_at_utc),
                   action_kind = COALESCE(action_kind, CASE WHEN intent_type = 'set_maxspeed' THEN 'posted_maximum' END),
                   resolved_limit_kind = COALESCE(resolved_limit_kind, CASE
                     WHEN new_speed_kmh IS NOT NULL THEN 'numeric'
                     WHEN value = 'walk' THEN 'walk'
                     WHEN value = 'none' THEN 'unlimited'
                   END),
                   osm_tag_key = COALESCE(osm_tag_key, CASE WHEN intent_type = 'set_maxspeed' THEN 'maxspeed' END),
                   canonical_value = COALESCE(canonical_value, CASE WHEN intent_type = 'set_maxspeed' THEN value END),
                   runtime_applicable = CASE
                     WHEN modality != 'computer_vision' AND intent_type = 'set_maxspeed'
                       AND primary_way_id IS NOT NULL
                       AND (
                         value IN ('walk', 'none')
                         OR (
                           CAST(value AS INTEGER) BETWEEN 5 AND 200
                           AND value = CAST(CAST(value AS INTEGER) AS TEXT)
                         )
                       ) THEN 1
                     WHEN modality != 'computer_vision' AND intent_type = 'set_maxspeed' THEN 0
                     ELSE runtime_applicable
                   END
            """.trimIndent(),
        )
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

    private fun ensureExportColumn(
        db: SQLiteDatabase,
        columnName: String,
        typeDeclaration: String,
    ) {
        db.rawQuery("PRAGMA table_info(exports)", null).use { cursor ->
            while (cursor.moveToNext()) {
                if (cursor.getString(1) == columnName) return
            }
        }
        db.execSQL("ALTER TABLE exports ADD COLUMN $columnName $typeDeclaration")
    }

    private fun ensureCvReceiptColumn(
        db: SQLiteDatabase,
        columnName: String,
        typeDeclaration: String,
    ) {
        db.rawQuery("PRAGMA table_info(cv_event_receipts)", null).use { cursor ->
            while (cursor.moveToNext()) {
                if (cursor.getString(1) == columnName) return
            }
        }
        db.execSQL("ALTER TABLE cv_event_receipts ADD COLUMN $columnName $typeDeclaration")
    }

    private fun ensureExportBatchColumn(
        db: SQLiteDatabase,
        columnName: String,
        typeDeclaration: String,
    ) {
        db.rawQuery("PRAGMA table_info(local_observation_export_batches)", null).use { cursor ->
            while (cursor.moveToNext()) {
                if (cursor.getString(1) == columnName) return
            }
        }
        db.execSQL("ALTER TABLE local_observation_export_batches ADD COLUMN $columnName $typeDeclaration")
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
        tagKey: String,
        maxspeedValue: String,
    ): String {
        return """
        <?xml version="1.0" encoding="UTF-8"?>
        <osmChange version="0.6" generator="youspeed-export-v1">
          <modify>
            <way id="${xmlEscape(wayId)}">
              <tag k="${xmlEscape(tagKey)}" v="${xmlEscape(maxspeedValue)}"/>
            </way>
          </modify>
        </osmChange>
        """.trimIndent()
    }

    private fun makeBulkOsmChangeXml(observations: List<LocalObservation>): String {
        val body = observations.joinToString("\n") { observation ->
            """
                <way id="${xmlEscape(observation.wayId.orEmpty())}">
                  <tag k="${xmlEscape(observation.osmTagKey.orEmpty())}" v="${xmlEscape(observation.newSpeedValue.orEmpty())}"/>
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
        private val POSITIVE_OSM_WAY_ID = Regex("[1-9][0-9]*")
        private val VERIFIED_SHA256 = Regex("^[a-f0-9]{64}$")
        private val END_ACTION_KINDS = setOf(
            TrafficSignActionKind.ZONE_END,
            TrafficSignActionKind.MAXIMUM_SPEED_END,
            TrafficSignActionKind.ALL_RESTRICTIONS_END,
            TrafficSignActionKind.PEDESTRIAN_ZONE_END,
            TrafficSignActionKind.CITY_EXIT,
            TrafficSignActionKind.MOTORWAY_EXIT,
            TrafficSignActionKind.MOTORROAD_EXIT,
        )
        private val SHARED_PASSAGE_ACTION_KINDS = setOf(
            TrafficSignActionKind.POSTED_MAXIMUM,
            TrafficSignActionKind.ZONE_START,
            TrafficSignActionKind.PEDESTRIAN_ZONE_START,
            TrafficSignActionKind.CITY_ENTRY,
            TrafficSignActionKind.TEMPORARY_MAXIMUM,
        ) + END_ACTION_KINDS

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
