package de.youspeed.android.alpha

import java.io.File
import java.time.Instant
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class RoadworksAdvisoryTests {
    private val now = Instant.parse("2026-10-23T10:00:00Z")
    private fun bytes() = File("../../shared/roadworks/snapshot-v1.json").readBytes()
    private fun snapshot() = bytes().let { RoadworksAdvisory.parseSnapshot(it, RoadworksAdvisory.sha256(it)) }
    private fun manifest() = RoadworksAdvisory.Manifest(true, snapshot().id, bytes().size, null, now,
        now.minusSeconds(1200), now.minusSeconds(600), now.minusSeconds(30), RoadworksAdvisory.Freshness.FRESH)
    private fun fix(seconds: Long = 0, latitude: Double = 48.0) = RoadworksRelevance.Fix(RoadworksAdvisory.Point(latitude, 8.0), now.plusSeconds(seconds), 5.0)

    @Test fun sharedSnapshotRetainsIdentityAttributionAndLineMiddleDistance() {
        val snapshot = snapshot()
        assertEquals(3, snapshot.features.size)
        assertEquals("dl-de/by-2-0", snapshot.attributions.single()["license_id"])
        assertEquals(0.0, RoadworksAdvisory.distance(RoadworksAdvisory.Point(48.0,8.0),snapshot.features.first { it.kind == "roadworks" }), 1e-6)
        assertEquals("unknown", snapshot.features.first { it.points.size == 1 }.direction)
    }
    @Test fun freshnessAgesOfflineAndCheckSuccessNeverFreshensPublisher() {
        val manifest = manifest()
        assertEquals(RoadworksAdvisory.Freshness.FRESH, manifest.freshness(100.0,100.0))
        assertEquals(RoadworksAdvisory.Freshness.DELAYED, manifest.freshness(100.0,701.0))
        assertEquals(RoadworksAdvisory.Freshness.UNAVAILABLE, manifest.freshness(100.0,86501.0))
        assertEquals(RoadworksAdvisory.Freshness.UNKNOWN, manifest.freshness(100.0,99.0))
        assertEquals(RoadworksAdvisory.Freshness.UNKNOWN, manifest.copy(sourcePublication=null).freshness(0.0,0.0))
        assertEquals(RoadworksAdvisory.Freshness.DELAYED, manifest.copy(serverTime=now.plusSeconds(7200),lastChecked=now.plusSeconds(7200)).freshness(0.0,0.0))
        assertTrue(runCatching { manifest.validatedHttpClock(now.minusSeconds(301),0.0) }.isFailure)
        assertEquals(RoadworksAdvisory.Freshness.DELAYED, manifest.validatedHttpClock(now,7200.0).freshness(0.0,0.0))
    }
    @Test fun cachePreservesPreviousGenerationAfterChecksumSchemaOrSwappedPointFailure() {
        val cache=RoadworksSnapshotCache(); val data=bytes(); val manifest=manifest()
        cache.install(data,manifest)
        val original=cache.snapshot
        assertTrue(runCatching { cache.install(data+byteArrayOf(10),manifest) }.isFailure)
        for (changed in listOf(data.toString(Charsets.UTF_8).replace("\"schema_version\": 1","\"schema_version\": 2"),
            data.toString(Charsets.UTF_8).replace("8.0,\n          48.001","48.001,\n          8.0"))) {
            assertNotEquals(data.toString(Charsets.UTF_8),changed)
            val bad=changed.toByteArray()
            assertTrue(runCatching { cache.install(bad,manifest.copy(snapshotId=RoadworksAdvisory.sha256(bad),snapshotBytes=bad.size)) }.isFailure)
            assertSame(original,cache.snapshot)
        }
    }
    @Test fun passiveCardRequiresTwoDistinctFixesAndExpiresWithoutNewLocation() {
        val runtime=RoadworksRelevance(); val snapshot=snapshot()
        fun update(fix:RoadworksRelevance.Fix?,at:Instant=fix?.at ?: now,enabled:Boolean=true) = runtime.update(snapshot,RoadworksAdvisory.Freshness.FRESH,fix,at,enabled,true,true)
        assertNull(update(fix()))
        assertNull(update(fix()))
        assertEquals("closure",update(fix(1))?.feature?.kind)
        assertNull(update(fix(1),now.plusSeconds(5)))
        assertNull(update(fix(6)))
        assertNotNull(update(fix(7)))
        assertNull(update(fix(8),enabled=false))
        assertNull(update(fix(9)))
    }
    @Test fun scheduleHalfOpenIntervalsAndUnknownMeaningNeverClaimActivity() {
        val works=snapshot().features.first()
        assertFalse(works.eligible(now.minusNanos(1)))
        assertTrue(works.eligible(now))
        assertFalse(works.eligible(Instant.parse("2026-10-23T12:00:00Z")))
        assertFalse(works.copy(scheduleStatus="unknown").eligible(now))
        assertFalse(works.copy(operatorStatus="unknown").eligible(now))
        assertFalse(works.copy(kind="new_future_type").eligible(now))
    }
    @Test fun diskCacheRestoresCurrentAndRecoversPreviousAfterCorruption() {
        val directory=kotlin.io.path.createTempDirectory("roadworks-cache").toFile()
        try {
            val cache=RoadworksSnapshotCache(directory);val data=bytes();val manifest=manifest()
            cache.install(data,manifest)
            val next=data.toString(Charsets.UTF_8).replace("Synthetic reported worksite","Next synthetic reported worksite").toByteArray()
            val nextId=RoadworksAdvisory.sha256(next)
            cache.install(next,manifest.copy(snapshotId=nextId,snapshotBytes=next.size))
            assertEquals(nextId,RoadworksSnapshotCache(directory).snapshot?.id)
            assertEquals(manifest.snapshotId,RoadworksSnapshotCache(directory).previousSnapshot?.id)
            File(directory,"snapshot-$nextId.json").writeText("truncated")
            val recovered=RoadworksSnapshotCache(directory)
            assertEquals(manifest.snapshotId,recovered.snapshot?.id)
            assertEquals("current_snapshot_invalid_using_previous",recovered.restoreError)
        } finally { directory.deleteRecursively() }
    }
    @Test fun cardRetainsTo750MetersAndSourceGenerationChangeRearmsTwoFixes() {
        val runtime=RoadworksRelevance(); val base=snapshot(); val snapshot=base.copy(features=base.features.filter{it.kind=="roadworks"})
        fun update(latitude:Double,seconds:Long,s:RoadworksAdvisory.Snapshot=snapshot) = runtime.update(s,RoadworksAdvisory.Freshness.DELAYED,fix(seconds,latitude),now.plusSeconds(seconds),true,true,true)
        assertNull(update(48.0,0)); assertNotNull(update(48.0,1))
        assertNotNull(update(48.006,2))
        assertNull(update(48.007,3))
        assertNull(update(48.0,4)); assertNotNull(update(48.0,5))
        assertNull(update(48.0,6,snapshot.copy(id="new-generation")))
        assertNotNull(update(48.0,7,snapshot.copy(id="new-generation")))
    }

    private val v2Now = Instant.parse("2026-10-28T10:00:00Z")
    private fun v2Bytes() = File("../../shared/roadworks/snapshot-v2.json").readBytes()
    private fun v2Manifest() = RoadworksAdvisory.parseManifest(File("../../shared/roadworks/manifest-v2.json").readBytes())
    private fun v2Snapshot() = v2Bytes().let { RoadworksAdvisory.parseSnapshot(it, RoadworksAdvisory.sha256(it)) }

    @Test fun sharedV2PreservesSourceIdentitiesAndInstallsAtomically() {
        val manifest = v2Manifest(); val snapshot = v2Snapshot()
        assertEquals(2, manifest.schemaVersion); assertEquals(2, snapshot.schemaVersion)
        assertEquals(manifest.sources.map { it.id }.toSet(), snapshot.sourceIds)
        assertEquals(setOf("roadworks", "closure", "incident", "hazard", "congestion"), snapshot.features.map { it.kind }.toSet())
        snapshot.features.forEach { feature ->
            assertTrue(feature.id.startsWith("mobidata-bw:${feature.advisorySource}:"))
            assertTrue(feature.publisherRecordId.isNotEmpty()); assertNotNull(feature.sourceVersionTime)
            assertTrue(feature.eligible(v2Now))
        }
        val cache = RoadworksSnapshotCache(); cache.install(bytes(), manifest())
        val original = cache.snapshot
        assertTrue(runCatching { cache.install(v2Bytes(), manifest.copy(sources = manifest.sources.dropLast(1))) }.isFailure)
        assertSame(original, cache.snapshot)
        assertTrue(runCatching { cache.install(v2Bytes(), manifest.copy(schemaVersion = 1)) }.isFailure)
        cache.install(v2Bytes(), manifest)
        assertEquals(snapshot.id, cache.snapshot?.id); assertSame(original, cache.previousSnapshot)
    }

    @Test fun v2FreshnessExpiresIncidentsIndependentlyOfRoadworks() {
        val manifest = v2Manifest()
        fun status(elapsed: Double) = manifest.sourceFreshness(100.0, 100.0 + elapsed)
        assertEquals(RoadworksAdvisory.Freshness.FRESH, status(540.0)["incidents-bw"])
        assertEquals(RoadworksAdvisory.Freshness.DELAYED, status(541.0)["incidents-bw"])
        assertEquals(RoadworksAdvisory.Freshness.DELAYED, status(840.0)["incidents-bw"])
        assertEquals(RoadworksAdvisory.Freshness.UNAVAILABLE, status(841.0)["incidents-bw"])
        assertEquals(RoadworksAdvisory.Freshness.FRESH, status(841.0)["bemas"])
        assertEquals(RoadworksAdvisory.Freshness.FRESH, manifest.freshness(100.0, 941.0))
        assertEquals(RoadworksAdvisory.Freshness.UNAVAILABLE, status(0.0)["autobahn-long-term"])
        fun incident(change: (RoadworksAdvisory.Source) -> RoadworksAdvisory.Source) = manifest.copy(sources = manifest.sources.map { if (it.id == "incidents-bw") change(it) else it }).sourceFreshness(0.0, 0.0)["incidents-bw"]
        assertEquals(RoadworksAdvisory.Freshness.FRESH, incident { it.copy(lastChecked = v2Now.minusSeconds(600)) })
        assertEquals(RoadworksAdvisory.Freshness.DELAYED, incident { it.copy(lastChecked = v2Now.minusSeconds(601)) })
        assertEquals(RoadworksAdvisory.Freshness.UNAVAILABLE, incident { it.copy(lastChecked = v2Now.minusSeconds(901)) })
        assertEquals(RoadworksAdvisory.Freshness.UNKNOWN, incident { it.copy(sourceModified = v2Now.plusSeconds(1)) })
        assertEquals(RoadworksAdvisory.Freshness.UNKNOWN, incident { it.copy(sourcePublication = null) })
        assertEquals(RoadworksAdvisory.Freshness.UNAVAILABLE, incident { it.copy(enabled = false) })
        assertEquals(1L, manifest.sourceAgeMinutes("incidents-bw", 0.0, 0.0))
        assertNull(manifest.sourceAgeMinutes("unknown-source", 0.0, 0.0))
    }

    @Test fun sourceAvailabilityControlsCardsEvenWhenAggregateIsFresh() {
        val snapshot = v2Snapshot()
        val incident = snapshot.features.first { it.kind == "incident" }
        val works = snapshot.features.first { it.advisorySource == "bemas" }
        val subset = snapshot.copy(features = listOf(incident, works))
        val runtime = RoadworksRelevance()
        fun update(second: Long, statuses: Map<String, RoadworksAdvisory.Freshness>, data: RoadworksAdvisory.Snapshot = subset): RoadworksRelevance.Card? {
            val fix = RoadworksRelevance.Fix(RoadworksAdvisory.Point(48.0, 8.0), v2Now.plusSeconds(second), 5.0)
            return runtime.update(data, RoadworksAdvisory.Freshness.FRESH, fix, fix.at, true, true, true, statuses, fix.at)
        }
        val worksOnly = mapOf("bemas" to RoadworksAdvisory.Freshness.FRESH, "incidents-bw" to RoadworksAdvisory.Freshness.UNAVAILABLE)
        assertNull(update(0, worksOnly)); assertEquals("bemas", update(1, worksOnly)?.feature?.advisorySource)
        val incidentOnly = mapOf("incidents-bw" to RoadworksAdvisory.Freshness.DELAYED)
        assertNull(update(2, incidentOnly)); val card = update(3, incidentOnly)
        assertEquals("incidents-bw", card?.feature?.advisorySource); assertEquals(RoadworksAdvisory.Freshness.DELAYED, card?.freshness)
        assertNull(update(4, emptyMap()))
        assertNull(update(5, mapOf("unknown" to RoadworksAdvisory.Freshness.FRESH)))
        assertFalse(incident.copy(advisorySource = "future-source").eligible(v2Now))
        assertFalse(incident.copy(kind = "future-kind").eligible(v2Now))
        assertFalse(works.copy(operatorStatus = "reported").eligible(v2Now))
    }

    @Test fun v2WithoutPerSourceFreshnessNeverUsesAggregateToAdmitCards() {
        val runtime = RoadworksRelevance(); val snapshot = v2Snapshot()
        fun update(second: Long, statuses: Map<String, RoadworksAdvisory.Freshness>?): RoadworksRelevance.Card? {
            val fix = RoadworksRelevance.Fix(RoadworksAdvisory.Point(48.0, 8.0), v2Now.plusSeconds(second), 5.0)
            return runtime.update(snapshot, RoadworksAdvisory.Freshness.FRESH, fix, fix.at, true, true, true, statuses, fix.at)
        }
        assertNull(update(0, null)); assertNull(update(1, null))
        val statuses = mapOf("bemas" to RoadworksAdvisory.Freshness.FRESH)
        assertNull(update(2, statuses)); assertNotNull(update(3, statuses))
        assertNull(update(4, null)); assertNull(update(5, null))
    }

    @Test fun v2ValidatorsRejectUnknownDuplicateAndMismatchedSourceProvenance() {
        val manifestText = File("../../shared/roadworks/manifest-v2.json").readText()
        for (changed in listOf(manifestText.replace("incidents-bw", "unknown-feed"),
            manifestText.replace("incidents-bw", "bemas"),
            manifestText.replace("\"autobahn_included\": true", "\"autobahn_included\": false"),
            manifestText.replace("/youspeed/live/v2/", "/youspeed/live/v1/"))) {
            assertNotEquals(manifestText, changed)
            assertTrue(runCatching { RoadworksAdvisory.parseManifest(changed.toByteArray()) }.isFailure)
        }
        val snapshotText = v2Bytes().toString(Charsets.UTF_8)
        for (changed in listOf(snapshotText.replace("\"advisory_source\": \"incidents-bw\"", "\"advisory_source\": \"future-source\""),
            snapshotText.replace("mobidata-bw:incidents-bw:", "mobidata-bw:bemas:"))) {
            assertNotEquals(snapshotText, changed)
            val data = changed.toByteArray()
            assertTrue(runCatching { RoadworksAdvisory.parseSnapshot(data, RoadworksAdvisory.sha256(data)) }.isFailure)
        }
        // Nullable upstream version time remains valid provenance for a quarantined record.
        val root = Json.parseToJsonElement(snapshotText).jsonObject
        val nullableRows = root.getValue("features").jsonArray.map { raw ->
            val row = raw.jsonObject
            val properties = JsonObject(row.getValue("properties").jsonObject + mapOf(
                "source_version_time" to JsonNull, "schedule_status" to JsonPrimitive("unknown"), "active_intervals" to JsonArray(emptyList())))
            JsonObject(row + ("properties" to properties))
        }
        val nullableBytes = JsonObject(root + ("features" to JsonArray(nullableRows))).toString().toByteArray()
        val nullable = RoadworksAdvisory.parseSnapshot(nullableBytes, RoadworksAdvisory.sha256(nullableBytes))
        assertTrue(nullable.features.all { it.sourceVersionTime == null && !it.eligible(v2Now) })
        val emptySources = JsonObject(root + ("source_ids" to JsonArray(emptyList()))).toString().toByteArray()
        assertTrue(runCatching { RoadworksAdvisory.parseSnapshot(emptySources, RoadworksAdvisory.sha256(emptySources)) }.isFailure)
    }

    private fun activeIncidentBytes(originalStart: JsonElement = JsonNull, originalEnd: JsonElement = JsonNull,
                                    change: (MutableMap<String, JsonElement>) -> Unit = {}): ByteArray {
        val publication = requireNotNull(v2Manifest().sources.first { it.id == "incidents-bw" }.sourcePublication)
        val root = Json.parseToJsonElement(v2Bytes().toString(Charsets.UTF_8)).jsonObject
        val row = root.getValue("features").jsonArray.first { it.jsonObject.getValue("properties").jsonObject.getValue("kind").jsonPrimitive.content == "incident" }.jsonObject
        val properties = row.getValue("properties").jsonObject.toMutableMap()
        properties["validity_basis"] = JsonPrimitive("reported_active")
        properties["source_validity_status"] = JsonPrimitive("active")
        properties["source_validity_start"] = originalStart; properties["source_validity_end"] = originalEnd
        properties["outer_start"] = JsonPrimitive(publication.toString())
        properties["outer_end"] = JsonPrimitive(publication.plusSeconds(900).toString())
        properties["active_intervals"] = JsonArray(listOf(buildJsonObject { put("start", properties.getValue("outer_start")); put("end", properties.getValue("outer_end")) }))
        properties["schedule_status"] = JsonPrimitive("resolved")
        change(properties)
        return JsonObject(root + ("features" to JsonArray(listOf(JsonObject(row + ("properties" to JsonObject(properties))))))).toString().toByteArray()
    }
    private fun installingManifest(bytes: ByteArray, change: (RoadworksAdvisory.Source) -> RoadworksAdvisory.Source = { it }): RoadworksAdvisory.Manifest {
        val manifest = v2Manifest(); val id = RoadworksAdvisory.sha256(bytes)
        return manifest.copy(snapshotId = id, snapshotBytes = bytes.size,
            snapshotPath = "/youspeed/live/v2/regions/DE-BW/snapshots/$id", sources = manifest.sources.map(change))
    }
    private fun parsed(bytes: ByteArray) = RoadworksAdvisory.parseSnapshot(bytes, RoadworksAdvisory.sha256(bytes))

    @Test fun incidentValidityRetainsScheduledAndPastOrFutureActiveSpecifications() {
        val scheduled = v2Snapshot().features.first { it.advisorySource == "incidents-bw" }
        assertEquals("scheduled", scheduled.validityBasis)
        assertEquals("definedByValidityTimeSpec", scheduled.sourceValidityStatus)
        assertNotNull(scheduled.sourceValidityStart); assertNotNull(scheduled.sourceValidityEnd)
        assertTrue(snapshot().features.all { it.validityBasis == "scheduled" && it.sourceValidityStatus == null })
        val publication = requireNotNull(v2Manifest().sources.first { it.id == "incidents-bw" }.sourcePublication)
        for ((start, end) in listOf("2026-10-20T10:00:00Z" to "2026-10-21T10:00:00Z", "2026-11-01T10:00:00Z" to "2026-11-02T10:00:00Z")) {
            val feature = parsed(activeIncidentBytes(JsonPrimitive(start), JsonPrimitive(end))).features.single()
            assertEquals(Instant.parse(start), feature.sourceValidityStart); assertEquals(Instant.parse(end), feature.sourceValidityEnd)
            assertFalse(feature.eligible(publication.minusNanos(1)))
            assertTrue(feature.eligible(publication)); assertTrue(feature.eligible(publication.plusSeconds(900).minusNanos(1)))
            assertFalse(feature.eligible(publication.plusSeconds(900)))
        }
    }

    @Test fun incidentValidityMetadataRejectsMissingMismatchAndOversizedLease() {
        for (key in listOf("validity_basis", "source_validity_status", "source_validity_start", "source_validity_end")) {
            assertTrue(runCatching { parsed(activeIncidentBytes { it.remove(key) }) }.isFailure)
        }
        val invalid = listOf(
            activeIncidentBytes { it["validity_basis"] = JsonPrimitive("unknown") },
            activeIncidentBytes { it["source_validity_status"] = JsonPrimitive("definedByValidityTimeSpec") },
            activeIncidentBytes { it["validity_basis"] = JsonPrimitive("scheduled") },
            activeIncidentBytes { it["schedule_status"] = JsonPrimitive("unknown"); it["active_intervals"] = JsonArray(emptyList()) },
            activeIncidentBytes { properties ->
                val end = Instant.parse(properties.getValue("outer_end").jsonPrimitive.content).plusSeconds(1).toString()
                properties["outer_end"] = JsonPrimitive(end)
                properties["active_intervals"] = JsonArray(listOf(buildJsonObject { put("start", properties.getValue("outer_start")); put("end", end) }))
            },
            activeIncidentBytes { it["source_validity_start"] = JsonPrimitive("2026-10-28T10:00:00") }
        )
        invalid.forEach { assertTrue(runCatching { parsed(it) }.isFailure) }
    }

    @Test fun activeLeaseCacheBindsOnlyItsOwnPublicationAndKeepsPriorOnFailure() {
        val bytes = activeIncidentBytes(); val cache = RoadworksSnapshotCache()
        cache.install(bytes, installingManifest(bytes))
        assertNull(cache.snapshot?.features?.single()?.sourceValidityStart)
        val previous = cache.snapshot
        val publication = requireNotNull(v2Manifest().sources.first { it.id == "incidents-bw" }.sourcePublication)
        for (clock in listOf<Instant?>(null, publication.plusSeconds(1))) {
            assertTrue(runCatching { cache.install(bytes, installingManifest(bytes) { if (it.id == "incidents-bw") it.copy(sourcePublication = clock) else it }) }.isFailure)
            assertSame(previous, cache.snapshot)
        }
        cache.install(bytes, installingManifest(bytes) { if (it.id == "bemas") it.copy(sourcePublication = null) else it })
        assertEquals(previous?.id, cache.snapshot?.id)
    }

    @Test fun activeReportLeaseExpiresHalfOpenWhileSourceIsStillDelayed() {
        val bytes = activeIncidentBytes(); val snapshot = parsed(bytes); val manifest = installingManifest(bytes)
        val runtime = RoadworksRelevance()
        fun update(elapsed: Long): RoadworksRelevance.Card? {
            val at = manifest.serverTime.plusSeconds(elapsed)
            val fix = RoadworksRelevance.Fix(RoadworksAdvisory.Point(48.001, 8.0), at, 5.0)
            return runtime.update(snapshot, RoadworksAdvisory.Freshness.FRESH, fix, at, true, true, true, manifest.sourceFreshness(0.0, elapsed.toDouble()), manifest.trustedNow(0.0, elapsed.toDouble()))
        }
        assertNull(update(541)); assertEquals(RoadworksAdvisory.Freshness.DELAYED, update(542)?.freshness)
        assertNotNull(update(839))
        assertEquals(RoadworksAdvisory.Freshness.DELAYED, manifest.sourceFreshness(0.0,840.0)["incidents-bw"])
        assertNull(update(840))
        assertEquals(RoadworksAdvisory.Freshness.UNAVAILABLE, manifest.sourceFreshness(0.0,841.0)["incidents-bw"])
    }

    @Test fun trustedValidityTimeIgnoresHandsetWallOffsetWhileGPSStillUsesWallAge() {
        val bytes = activeIncidentBytes(); val snapshot = parsed(bytes); val manifest = installingManifest(bytes)
        for (offset in listOf(-7200L, 7200L)) {
            val runtime = RoadworksRelevance()
            fun update(elapsed: Long, fixAge: Long = 0): RoadworksRelevance.Card? {
                val wall = manifest.serverTime.plusSeconds(offset + elapsed)
                val fix = RoadworksRelevance.Fix(RoadworksAdvisory.Point(48.001, 8.0), wall.minusSeconds(fixAge), 5.0)
                return runtime.update(snapshot, RoadworksAdvisory.Freshness.FRESH, fix, wall, true, true, true,
                    manifest.sourceFreshness(100.0, 100.0 + elapsed), manifest.trustedNow(100.0, 100.0 + elapsed))
            }
            assertNull(update(0)); assertNotNull(update(1))
            assertNull("GPS age must compare handset wall timestamps", update(2, fixAge = 4))
            assertNull(update(3)); assertNotNull(update(4))
            assertEquals(RoadworksAdvisory.Freshness.DELAYED, update(600)?.freshness)
            assertNotNull(update(839)); assertNull("The lease expires even when handset wall time is slow", update(840))
        }
    }

    @Test fun v2MissingOrInvalidMonotonicClockCannotFallBackToWallValidity() {
        val bytes = activeIncidentBytes(); val snapshot = parsed(bytes); val manifest = installingManifest(bytes)
        for (uptime in listOf(99.0, Double.NaN, Double.POSITIVE_INFINITY)) {
            val trusted = manifest.trustedNow(100.0, uptime)
            assertNull(trusted)
            val runtime = RoadworksRelevance()
            for (second in 0L..1L) {
                val wall = manifest.serverTime.plusSeconds(second)
                val fix = RoadworksRelevance.Fix(RoadworksAdvisory.Point(48.001, 8.0), wall, 5.0)
                assertNull(runtime.update(snapshot, RoadworksAdvisory.Freshness.FRESH, fix, wall, true, true, true,
                    mapOf("incidents-bw" to RoadworksAdvisory.Freshness.FRESH), trusted))
            }
        }
    }

    @Test fun testCapturedIncidentQualificationArtifactWhenPresent() {
        val directory = File("/private/tmp/youspeed-qualification-20261028/acceptance")
        val receiptFile = File(directory, "receipt.json")
        org.junit.Assume.assumeTrue("Optional captured backend qualification artifact is not present", receiptFile.isFile)
        val receipt = Json.parseToJsonElement(receiptFile.readText()).jsonObject
        val bytes = File(directory, "snapshot.json").readBytes()
        val manifest = RoadworksAdvisory.parseManifest(File(directory, "manifest.json").readBytes())
        val cache = RoadworksSnapshotCache(); cache.install(bytes, manifest)
        val snapshot = requireNotNull(cache.snapshot)
        val checked = Instant.parse(receipt.getValue("checked_at_utc").jsonPrimitive.content)
        val elapsed = java.time.Duration.between(manifest.serverTime, checked).toNanos() / 1e9
        val trusted = requireNotNull(manifest.trustedNow(0.0, elapsed))
        assertEquals(checked.toEpochMilli(), trusted.toEpochMilli())
        assertEquals(setOf("bemas", "incidents-bw", "autobahn-short-term", "autobahn-long-term"), manifest.sourceList().map { it.id }.toSet())
        assertEquals(setOf("incidents-bw"), manifest.sources.filter { it.enabled }.map { it.id }.toSet())
        assertTrue(snapshot.features.all { it.advisorySource == "incidents-bw" })
        assertEquals(receipt.getValue("exported_features").jsonPrimitive.int, snapshot.features.size)
        assertEquals(receipt.getValue("reported_active_features").jsonPrimitive.int, snapshot.features.count { it.validityBasis == "reported_active" })
        val status = manifest.sourceFreshness(0.0, elapsed)["incidents-bw"]
        assertEquals(receipt.getValue("eligible_features").jsonPrimitive.int,
            snapshot.features.count { it.eligible(trusted) && status in setOf(RoadworksAdvisory.Freshness.FRESH, RoadworksAdvisory.Freshness.DELAYED) })
        assertTrue(snapshot.features.filter { it.kind !in setOf("roadworks", "closure", "incident", "hazard", "congestion") }.all { !it.eligible(trusted) })
    }
}
