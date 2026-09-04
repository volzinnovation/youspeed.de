package de.youspeed.android.alpha

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import java.util.UUID
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LocalObservationStoreInstrumentedTest {
    @Test
    fun localRuntimeAndExportRangeMatchesSharedTrafficSignContract() {
        val store = createStore()
        listOf(4, 201).forEachIndexed { index, value ->
            val observation = store.recordSpeedLimitChange(
                oldSpeedKmh = null,
                newMaxspeedValue = value.toString(),
                captureContext = captureContext("40${index + 1}", "Boundary", "Karlsruhe"),
            )
            assertFalse(observation.runtimeApplicable)
            assertTrue(runCatching { store.reviewAndApproveProposal(observation.id) }.isFailure)
        }
        listOf(5, 200).forEachIndexed { index, value ->
            val observation = store.recordSpeedLimitChange(
                oldSpeedKmh = null,
                newMaxspeedValue = value.toString(),
                captureContext = captureContext("50${index + 1}", "Boundary", "Karlsruhe"),
            )
            assertTrue(observation.runtimeApplicable)
            assertEquals(LocalObservationState.APPROVED_FOR_EXPORT, store.reviewAndApproveProposal(observation.id).state)
        }
    }

    @Test
    fun approveAndSingleExportWritesReviewPackage() {
        val store = createStore()
        val captured = store.captureVoiceCommand(
            command = "hier gilt 50",
            captureContext = captureContext(wayId = "7102", street = "Tunnel Section", city = "Karlsruhe"),
        )

        assertEquals(LocalObservationState.NEEDS_REVIEW, captured.state)

        val approved = store.reviewAndApproveProposal(captured.id)
        assertEquals(LocalObservationState.APPROVED_FOR_EXPORT, approved.state)

        val export = store.exportProposalAsOscPackage(captured.id)
        assertTrue(export.changesFile.exists())
        assertTrue(export.reviewFile.exists())
        assertTrue(export.readmeFile.exists())
        assertTrue(export.reviewFile.readText().contains(captured.id))

        val exported = store.fetchObservations(limit = 10).first { it.id == captured.id }
        assertEquals(LocalObservationState.EXPORTED_OSC, exported.state)
    }

    @Test
    fun bulkExportSupportsWalkValueAndKeepsLatestPerWay() {
        val store = createStore()
        val first = store.recordSpeedLimitChange(
            oldSpeedKmh = 30,
            newMaxspeedValue = "walk",
            captureContext = captureContext(wayId = "5001", street = "Innenstadt", city = "Karlsruhe"),
            initialState = LocalObservationState.LOCAL_ONLY,
        )
        val second = store.recordSpeedLimitChange(
            oldSpeedKmh = 50,
            newMaxspeedValue = "30",
            captureContext = captureContext(wayId = "5001", street = "Innenstadt", city = "Karlsruhe"),
            initialState = LocalObservationState.LOCAL_ONLY,
        )
        val third = store.recordSpeedLimitChange(
            oldSpeedKmh = 70,
            newMaxspeedValue = "80",
            captureContext = captureContext(wayId = "5002", street = "B 10", city = "Karlsruhe"),
            initialState = LocalObservationState.LOCAL_ONLY,
        )
        listOf(second, third).forEach { store.reviewAndApproveProposal(it.id) }

        val bulk = store.exportAllLocalObservationsAsOsc()
        val xml = bulk.changesFile.readText()

        assertEquals(2, bulk.includedCount)
        assertTrue(xml.contains("""way id="5001""""))
        assertTrue(xml.contains("""way id="5002""""))
        assertTrue(xml.contains("""maxspeed" v="30""""))
        assertTrue(xml.contains("""maxspeed" v="80""""))
        assertEquals(LocalObservationState.LOCAL_ONLY, store.fetchObservations().first { it.id == first.id }.state)
    }

    @Test
    fun bulkPreservesManualLocalOnlyExportButExcludesUnapprovedComputerVision() {
        val store = createStore()
        val manualWalk = store.recordSpeedLimitChange(
            oldSpeedKmh = 30,
            newMaxspeedValue = "walk",
            captureContext = captureContext("6001", "Fußgängerzone", "Karlsruhe"),
        )
        val manualNumeric = store.recordSpeedLimitChange(
            oldSpeedKmh = 50,
            newMaxspeedValue = "70",
            captureContext = captureContext("6002", "Landstraße", "Karlsruhe"),
        )
        val unapprovedCv = requireNotNull(
            store.recordComputerVisionPassageIfNeeded(
                event = passage("cv-unapproved-bulk", "50", TrafficSignTravelDirection.FORWARD),
                captureContext = captureContext("5001", "B 10", "Karlsruhe"),
            ),
        )
        assertEquals(LocalObservationState.LOCAL_ONLY, unapprovedCv.state)

        val export = store.exportAllLocalObservationsAsOsc()
        val xml = export.changesFile.readText()
        assertEquals(2, export.includedCount)
        assertTrue(xml.contains("way id=\"6001\""))
        assertTrue(xml.contains("way id=\"6002\""))
        assertFalse(xml.contains("way id=\"5001\""))
        val observations = store.fetchObservations()
        assertEquals(LocalObservationState.EXPORTED_OSC, observations.first { it.id == manualWalk.id }.state)
        assertEquals(LocalObservationState.EXPORTED_OSC, observations.first { it.id == manualNumeric.id }.state)
        assertEquals(LocalObservationState.LOCAL_ONLY, observations.first { it.id == unapprovedCv.id }.state)
    }

    @Test
    fun newerLocalCorrectionBlocksOlderApprovedExportAndExportedRowsCannotBeReapproved() {
        val store = createStore()
        val older = store.recordSpeedLimitChange(
            oldSpeedKmh = null,
            newMaxspeedValue = "50",
            captureContext = captureContext("5001", "Innenstadt", "Karlsruhe"),
        )
        store.reviewAndApproveProposal(older.id)
        val newer = store.recordSpeedLimitChange(
            oldSpeedKmh = 50,
            newMaxspeedValue = "70",
            captureContext = captureContext("5001", "Innenstadt", "Karlsruhe"),
        )

        assertTrue(runCatching { store.exportProposalAsOscPackage(older.id) }.isFailure)
        store.reviewAndApproveProposal(newer.id)
        val exported = store.exportProposalAsOscPackage(newer.id)
        assertTrue(exported.changesFile.readText().contains("""maxspeed" v="70""""))
        assertTrue(runCatching { store.reviewAndApproveProposal(newer.id) }.isFailure)
    }

    @Test
    fun cvDirectionsCoexistInDurableFinalizedBatchAndEvidenceKeepsBundleChecksum() {
        val fixture = createFixture()
        val store = fixture.store
        val forward = requireNotNull(store.recordComputerVisionPassageIfNeeded(
            event = passage("cv-forward", "50", TrafficSignTravelDirection.FORWARD),
            captureContext = captureContext("5001", "B 10", "Karlsruhe"),
        ))
        val reverse = requireNotNull(store.recordComputerVisionPassageIfNeeded(
            event = passage("cv-reverse", "70", TrafficSignTravelDirection.REVERSE),
            captureContext = captureContext("5001", "B 10", "Karlsruhe"),
        ))
        store.reviewAndApproveProposal(forward.id)
        store.reviewAndApproveProposal(reverse.id)

        val export = store.exportAllLocalObservationsAsOsc()
        val xml = export.changesFile.readText()
        assertTrue(xml.contains("maxspeed:forward"))
        assertTrue(xml.contains("maxspeed:backward"))
        val evidence = JSONObject(requireNotNull(forward.evidenceJson))
        assertEquals(
            setOf(
                "schema_version", "event_kind", "finalized_event_id", "drive_session_id", "tsr_generation",
                "committed_at_utc", "pack", "track", "action", "resolution", "boundary", "activation",
                "applicability_scope", "persistence", "privacy",
            ),
            evidence.keys().asSequence().toSet(),
        )
        assertEquals("traffic_sign_passage", evidence.getString("event_kind"))
        assertEquals("live", evidence.getJSONObject("pack").getString("execution_mode"))
        assertEquals("analyzed_missing", evidence.getJSONObject("track").getJSONArray("loss_evidence").getJSONObject(0).getString("outcome"))
        assertEquals("5001", evidence.getJSONObject("activation").getString("way_id"))
        assertEquals("a".repeat(64), evidence.getJSONObject("applicability_scope").getString("bundle_sha256"))
        assertTrue(evidence.getJSONObject("persistence").getBoolean("runtime_applicable"))
        assertFalse(evidence.getJSONObject("privacy").getBoolean("raw_frame_persisted"))
        assertEquals(
            "backward",
            JSONObject(requireNotNull(reverse.evidenceJson))
                .getJSONObject("resolution")
                .getJSONObject("normalized_operation")
                .getString("direction_scope"),
        )

        SQLiteDatabase.openDatabase(
            File(fixture.rootDir, "local_observation_store.sqlite").absolutePath,
            null,
            SQLiteDatabase.OPEN_READONLY,
        ).use { db ->
            val status = db.rawQuery(
                "SELECT status FROM local_observation_export_batches WHERE batch_id = ?",
                arrayOf(export.exportId),
            ).use { cursor -> require(cursor.moveToFirst()); cursor.getString(0) }
            val members = db.rawQuery(
                "SELECT COUNT(DISTINCT target_key) FROM local_observation_export_members WHERE batch_id = ? AND reservation_status = 'finalized'",
                arrayOf(export.exportId),
            ).use { cursor -> require(cursor.moveToFirst()); cursor.getInt(0) }
            assertEquals("finalized", status)
            assertEquals(2, members)
        }
    }

    @Test
    fun safelyResolvedEndPersistsAsTypedSetAndExports() {
        val store = createStore()
        val event = passage("cv-end", "50", TrafficSignTravelDirection.FORWARD).copy(
            action = TrafficSignAction(TrafficSignActionKind.MAXIMUM_SPEED_END, valueKmh = 70),
        )
        val observation = requireNotNull(
            store.recordComputerVisionPassageIfNeeded(
                event = event,
                resolvedLimit = TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, 50),
                captureContext = captureContext("5001", "B 10", "Karlsruhe"),
            ),
        )

        assertEquals(LocalObservationIntentType.SET_MAXSPEED, observation.intentType)
        assertTrue(observation.runtimeApplicable)
        store.reviewAndApproveProposal(observation.id)
        val exported = store.exportProposalAsOscPackage(observation.id)
        assertTrue(exported.changesFile.readText().contains("maxspeed:forward"))
        assertTrue(exported.changesFile.readText().contains("v=\"50\""))
    }

    @Test
    fun equivalentManualCorrectionKeepsCanonicalCvEvidenceWithoutDuplicateRow() {
        val fixture = createFixture()
        val manual = fixture.store.recordSpeedLimitChange(
            oldSpeedKmh = null,
            newMaxspeedValue = "50",
            captureContext = captureContext("5001", "B 10", "Karlsruhe"),
        )
        val event = passage("cv-equivalent", "50", TrafficSignTravelDirection.FORWARD)

        assertEquals(
            null,
            fixture.store.recordComputerVisionPassageIfNeeded(
                event,
                captureContext = captureContext("5001", "B 10", "Karlsruhe"),
            ),
        )
        assertEquals(1, fixture.store.fetchObservations().size)
        SQLiteDatabase.openDatabase(
            File(fixture.rootDir, "local_observation_store.sqlite").absolutePath,
            null,
            SQLiteDatabase.OPEN_READONLY,
        ).use { db ->
            val receipt = db.rawQuery(
                "SELECT observation_id, evidence_json, correction_created FROM cv_event_receipts WHERE finalized_event_id = ?",
                arrayOf(event.finalizedEventId),
            ).use { cursor ->
                require(cursor.moveToFirst())
                Triple(cursor.getString(0), cursor.getString(1), cursor.getInt(2))
            }
            assertEquals(manual.id, receipt.first)
            assertEquals("traffic_sign_passage", JSONObject(receipt.second).getString("event_kind"))
            assertEquals(0, receipt.third)
        }
        assertEquals(
            null,
            fixture.store.recordComputerVisionPassageIfNeeded(
                event,
                captureContext = captureContext("5001", "B 10", "Karlsruhe"),
            ),
        )
    }

    @Test
    fun newerUnknownDirectionCvEvidenceBlocksOlderApprovedTarget() {
        val store = createStore()
        val older = requireNotNull(
            store.recordComputerVisionPassageIfNeeded(
                passage("cv-known-old", "50", TrafficSignTravelDirection.FORWARD),
                captureContext = captureContext("5001", "B 10", "Karlsruhe"),
            ),
        )
        store.reviewAndApproveProposal(older.id)
        val unknown = requireNotNull(
            store.recordComputerVisionPassageIfNeeded(
                passage("cv-unknown-new", "70", TrafficSignTravelDirection.UNKNOWN),
                captureContext = captureContext("5001", "B 10", "Karlsruhe"),
            ),
        )

        assertEquals(LocalObservationState.NEEDS_REVIEW, unknown.state)
        assertFalse(unknown.runtimeApplicable)
        assertTrue(runCatching { store.exportProposalAsOscPackage(older.id) }.isFailure)
    }

    @Test
    fun returningToEarlierValueAfterInterveningCorrectionIsNotDeduplicated() {
        val store = createStore()
        val capture = captureContext("5001", "B 10", "Karlsruhe")
        val first50 = store.recordComputerVisionPassageIfNeeded(
            passage("cv-50-first", "50", TrafficSignTravelDirection.FORWARD),
            captureContext = capture,
        )
        val seventy = store.recordComputerVisionPassageIfNeeded(
            passage("cv-70", "70", TrafficSignTravelDirection.FORWARD),
            captureContext = capture,
        )
        val final50 = store.recordComputerVisionPassageIfNeeded(
            passage("cv-50-final", "50", TrafficSignTravelDirection.FORWARD),
            captureContext = capture,
        )

        assertTrue(first50 != null && seventy != null && final50 != null)
        assertEquals(
            "50",
            store.latestRuntimeApplicableCorrection("5001", TrafficSignTravelDirection.FORWARD)?.canonicalValue,
        )
    }

    @Test
    fun corruptCvNeedsReviewRowCannotDriveOrHideOlderEquivalentCorrection() {
        val fixture = createFixture()
        val capture = captureContext("5001", "B 10", "Karlsruhe")
        val older = requireNotNull(
            fixture.store.recordComputerVisionPassageIfNeeded(
                passage(
                    "cv-valid-50",
                    "50",
                    TrafficSignTravelDirection.FORWARD,
                    timestamp = Instant.parse("2026-03-12T10:15:30Z"),
                ),
                captureContext = capture,
            ),
        )
        val corruptNewer = requireNotNull(
            fixture.store.recordComputerVisionPassageIfNeeded(
                passage(
                    "cv-corrupt-70",
                    "70",
                    TrafficSignTravelDirection.FORWARD,
                    timestamp = Instant.parse("2026-03-12T10:15:31Z"),
                ),
                captureContext = capture,
            ),
        )
        SQLiteDatabase.openDatabase(
            File(fixture.rootDir, "local_observation_store.sqlite").absolutePath,
            null,
            SQLiteDatabase.OPEN_READWRITE,
        ).use { db ->
            db.execSQL(
                "UPDATE observations SET state = ?, runtime_applicable = 1 WHERE observation_id = ?",
                arrayOf(LocalObservationState.NEEDS_REVIEW.rawValue, corruptNewer.id),
            )
        }

        assertEquals(
            older.id,
            fixture.store.latestRuntimeApplicableCorrection(
                "5001",
                TrafficSignTravelDirection.FORWARD,
            )?.observationId,
        )
        assertEquals(
            null,
            fixture.store.recordComputerVisionPassageIfNeeded(
                passage(
                    "cv-equivalent-after-corrupt-review",
                    "50",
                    TrafficSignTravelDirection.FORWARD,
                    timestamp = Instant.parse("2026-03-12T10:15:32Z"),
                ),
                captureContext = capture,
            ),
        )
        assertEquals(2, fixture.store.fetchObservations().size)
    }

    @Test
    fun canonicalCvEvidenceMustMatchSafePolicyAndEveryIndexedTargetField() {
        val mutations: List<Pair<String, (JSONObject) -> Unit>> = listOf(
            "temporary" to { root ->
                root.getJSONObject("action").put("permanence", "temporary")
            },
            "unresolved" to { root ->
                root.getJSONObject("resolution").put("runtime_status", "unresolved_end")
            },
            "wrong-way" to { root ->
                root.getJSONObject("activation").put("way_id", "5002")
            },
            "wrong-value" to { root ->
                root.getJSONObject("resolution").getJSONObject("normalized_operation").put("tag_value", "70")
            },
            "wrong-event" to { root ->
                root.put("finalized_event_id", "different-finalized-event")
            },
            "shadow-pack" to { root ->
                root.getJSONObject("pack").put("override_eligible", false)
            },
            "unverified-component" to { root ->
                root.getJSONObject("pack").getJSONArray("components").getJSONObject(0)
                    .put("artifact_sha256", "not-a-sha256")
            },
        )

        mutations.forEachIndexed { index, (label, mutate) ->
            val fixture = createFixture()
            val observation = requireNotNull(
                fixture.store.recordComputerVisionPassageIfNeeded(
                    passage("cv-corrupt-$index-$label", "50", TrafficSignTravelDirection.FORWARD),
                    captureContext = captureContext("5001", "B 10", "Karlsruhe"),
                ),
            )
            val corrupted = JSONObject(requireNotNull(observation.evidenceJson))
            mutate(corrupted)
            replaceObservationEvidence(fixture, observation.id, corrupted)

            assertNull(
                "$label evidence must not drive",
                fixture.store.latestRuntimeApplicableCorrection("5001", TrafficSignTravelDirection.FORWARD),
            )
            assertTrue(
                "$label evidence must not be approvable",
                runCatching { fixture.store.reviewAndApproveProposal(observation.id) }.isFailure,
            )
        }
    }

    @Test
    fun approvedCvWithCorruptCanonicalTargetCannotEnterOscExport() {
        val fixture = createFixture()
        val observation = requireNotNull(
            fixture.store.recordComputerVisionPassageIfNeeded(
                passage("cv-corrupt-after-approval", "50", TrafficSignTravelDirection.FORWARD),
                captureContext = captureContext("5001", "B 10", "Karlsruhe"),
            ),
        )
        fixture.store.reviewAndApproveProposal(observation.id)
        val corrupted = JSONObject(requireNotNull(observation.evidenceJson)).apply {
            getJSONObject("resolution").getJSONObject("normalized_operation")
                .put("tag_key", "maxspeed:backward")
                .put("direction_scope", "backward")
        }
        replaceObservationEvidence(fixture, observation.id, corrupted)

        assertNull(
            fixture.store.latestRuntimeApplicableCorrection("5001", TrafficSignTravelDirection.FORWARD),
        )
        assertTrue(runCatching { fixture.store.exportProposalAsOscPackage(observation.id) }.isFailure)
    }

    @Test
    fun delayedOlderCvCannotSupersedeNewerApprovalOrStaleItsPendingBatch() {
        val fixture = createFixture()
        val capture = captureContext("5001", "B 10", "Karlsruhe")
        val newer = requireNotNull(
            fixture.store.recordComputerVisionPassageIfNeeded(
                passage(
                    "cv-newer-70",
                    "70",
                    TrafficSignTravelDirection.FORWARD,
                    timestamp = Instant.parse("2026-03-12T10:15:31Z"),
                ),
                captureContext = capture,
            ),
        ).let { fixture.store.reviewAndApproveProposal(it.id) }
        val batchId = "pending-newer-batch"
        SQLiteDatabase.openDatabase(
            File(fixture.rootDir, "local_observation_store.sqlite").absolutePath,
            null,
            SQLiteDatabase.OPEN_READWRITE,
        ).use { db ->
            db.execSQL(
                """
                INSERT INTO local_observation_export_batches(
                  batch_id, created_at_utc, status, package_path, payload_sha256,
                  payload_xml, membership_key, finalized_at_utc, export_mode
                ) VALUES (?, ?, 'pending', ?, ?, ?, ?, NULL, 'single')
                """.trimIndent(),
                arrayOf(
                    batchId,
                    "2026-03-12T10:15:32Z",
                    File(fixture.rootDir, "exports/$batchId").absolutePath,
                    "0".repeat(64),
                    "<osmChange version=\"0.6\"/>",
                    "pending-newer-membership",
                ),
            )
            db.execSQL(
                """
                INSERT INTO local_observation_export_members(
                  batch_id, observation_id, target_key, observation_revision, ordinal, reservation_status
                ) VALUES (?, ?, ?, ?, 0, 'pending')
                """.trimIndent(),
                arrayOf(
                    batchId,
                    newer.id,
                    "way:5001|tag:maxspeed:forward|direction:forward",
                    newer.updatedAtUTC,
                ),
            )
        }

        requireNotNull(
            fixture.store.recordComputerVisionPassageIfNeeded(
                passage(
                    "cv-delayed-older-60",
                    "60",
                    TrafficSignTravelDirection.FORWARD,
                    timestamp = Instant.parse("2026-03-12T10:15:30Z"),
                ),
                captureContext = capture,
            ),
        )

        val refreshedNewer = fixture.store.fetchObservations().first { it.id == newer.id }
        assertEquals(LocalObservationState.APPROVED_FOR_EXPORT, refreshedNewer.state)
        assertFalse(refreshedNewer.supersededForExport)
        assertEquals(
            newer.id,
            fixture.store.latestRuntimeApplicableCorrection(
                "5001",
                TrafficSignTravelDirection.FORWARD,
            )?.observationId,
        )
        SQLiteDatabase.openDatabase(
            File(fixture.rootDir, "local_observation_store.sqlite").absolutePath,
            null,
            SQLiteDatabase.OPEN_READONLY,
        ).use { db ->
            assertEquals(
                "pending",
                db.rawQuery(
                    "SELECT status FROM local_observation_export_batches WHERE batch_id = ?",
                    arrayOf(batchId),
                ).use { cursor -> require(cursor.moveToFirst()); cursor.getString(0) },
            )
            assertEquals(
                "pending",
                db.rawQuery(
                    "SELECT reservation_status FROM local_observation_export_members WHERE batch_id = ?",
                    arrayOf(batchId),
                ).use { cursor -> require(cursor.moveToFirst()); cursor.getString(0) },
            )
        }
    }

    @Test
    fun unknownFutureDirectionRowIsSkippedFailClosed() {
        val fixture = createFixture()
        val observation = fixture.store.recordSpeedLimitChange(
            oldSpeedKmh = null,
            newMaxspeedValue = "50",
            captureContext = captureContext("5001", "B 10", "Karlsruhe"),
        )
        SQLiteDatabase.openDatabase(
            File(fixture.rootDir, "local_observation_store.sqlite").absolutePath,
            null,
            SQLiteDatabase.OPEN_READWRITE,
        ).use { db ->
            db.execSQL(
                "UPDATE observations SET direction_scope = 'future_direction' WHERE observation_id = ?",
                arrayOf(observation.id),
            )
        }

        assertTrue(fixture.store.fetchObservations().none { it.id == observation.id })
        assertEquals(null, fixture.store.latestRuntimeApplicableCorrection("5001", TrafficSignTravelDirection.FORWARD))
    }

    private fun createStore(): LocalObservationStore {
        return createFixture().store
    }

    private data class StoreFixture(val store: LocalObservationStore, val rootDir: File)

    private fun createFixture(): StoreFixture {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val rootDir = File(context.cacheDir, "local-observation-store-${UUID.randomUUID()}").apply { mkdirs() }
        val prefs = context.getSharedPreferences("local-observation-store-${UUID.randomUUID()}", Context.MODE_PRIVATE)
        val clock = Clock.fixed(Instant.parse("2026-03-12T10:15:30Z"), ZoneOffset.UTC)
        return StoreFixture(LocalObservationStore(context, rootDir, prefs, clock), rootDir)
    }

    private fun replaceObservationEvidence(
        fixture: StoreFixture,
        observationId: String,
        evidence: JSONObject,
    ) {
        SQLiteDatabase.openDatabase(
            File(fixture.rootDir, "local_observation_store.sqlite").absolutePath,
            null,
            SQLiteDatabase.OPEN_READWRITE,
        ).use { db ->
            db.execSQL(
                "UPDATE observations SET evidence_json = ? WHERE observation_id = ?",
                arrayOf(evidence.toString(), observationId),
            )
        }
    }

    private fun passage(
        id: String,
        value: String,
        direction: TrafficSignTravelDirection,
        timestamp: Instant = Instant.parse("2026-03-12T10:15:30Z"),
    ): TrafficSignPassageEvent {
        val context = TrafficSignDetectionContext(
            wayId = "5001",
            latitude = 49.0101,
            longitude = 8.4255,
            headingDegrees = 90.0,
            travelDirection = direction,
            sourceSignature = TrafficSignRuntimeSourceSignature("bundle:2026-03-12|way:5001", null),
            bundleSha256 = "a".repeat(64),
            routeRelationGroupIds = setOf(1L),
            sourceRelationIds = setOf(10L),
            continuityCapable = true,
            matchedWayStable = true,
        )
        val speed = value.toInt()
        return TrafficSignPassageEvent(
            finalizedEventId = id,
            driveSessionId = "drive-test",
            generation = 1,
            packId = "pack-v1",
            artifactSha256 = "b".repeat(64),
            preprocessingVersion = "rgb-v1",
            calibrationId = "calibration-test",
            componentRole = "direct_detector",
            modelComponents = listOf(
                TrafficSignModelComponentLineage(
                    role = "direct_detector",
                    artifactSha256 = "b".repeat(64),
                    preprocessingVersion = "rgb-v1",
                    calibrationId = "calibration-test",
                ),
            ),
            physicalTrackId = "track-$id",
            assemblyId = "assembly-$id",
            assemblyIds = listOf("assembly-$id"),
            action = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, speed),
            resolution = TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, speed),
            firstSeenAtUtc = timestamp.minusSeconds(1),
            lastSeenAtUtc = timestamp.minusMillis(100),
            firstSeenContext = context,
            lastSeenContext = context,
            passageBoundary = TrafficSignPassageBoundary(timestamp, context),
            activationContext = context,
            initialRouteRelationGroupIds = context.routeRelationGroupIds,
            eligibleRouteRelationGroupIds = context.routeRelationGroupIds,
            sourceRelationIds = context.sourceRelationIds,
            evidence = listOf(
                TrafficSignPassageFrameEvidence(
                    frameId = "frame-$id",
                    timestampUtc = timestamp.minusMillis(500),
                    rawScore = 0.9,
                    calibratedConfidence = 0.88,
                    accumulatedSupport = 0.91,
                    boundingBox = NormalizedTrafficSignBoundingBox(0.7, 0.1, 0.1, 0.2),
                    proposalRawScore = 0.92,
                    proposalCalibratedConfidence = 0.89,
                    classifierRawScore = 0.90,
                    classifierCalibratedConfidence = 0.88,
                    assemblyConfidence = 0.87,
                ),
            ),
            lossEvidence = listOf(
                TrafficSignPassageLossEvidence(
                    frameId = "missing-$id",
                    timestampUtc = timestamp,
                    strongPassGeometry = false,
                ),
            ),
            framesSeen = 1,
            finalConfidence = 0.88,
            finalAccumulatedSupport = 0.91,
            peakConsecutiveFramesSeen = 1,
            lossReason = "negative_debounce",
            negativeFramesToCommit = 2,
            overrideEligible = true,
        )
    }

    private fun captureContext(
        wayId: String,
        street: String,
        city: String,
    ): LocalObservationCaptureContext {
        return LocalObservationCaptureContext(
            lat = 49.0101,
            lon = 8.4255,
            headingDeg = 90.0,
            roadCandidateIds = listOf(wayId),
            cityContext = city,
            streetContext = street,
            confidenceCalibrated = 0.85,
            sourceVersion = "2026-03-12",
        )
    }
}
