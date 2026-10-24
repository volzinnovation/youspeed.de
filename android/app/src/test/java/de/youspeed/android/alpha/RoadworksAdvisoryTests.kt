package de.youspeed.android.alpha

import java.io.File
import java.time.Instant
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
}
