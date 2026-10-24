package de.youspeed.android.alpha

import androidx.test.platform.app.InstrumentationRegistry
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import org.junit.Assert.*
import org.junit.Test
import org.json.JSONObject
import org.json.JSONArray
import java.io.File
import java.time.Instant
import android.location.Location

class RoadworksServiceInstrumentedTest {
    @Test fun productionPreviousGenerationAndUpdateRequiredSurviveEvaluation() {
        val instrumentation = InstrumentationRegistry.getInstrumentation(); val context = instrumentation.targetContext
        val name = "roadworks-previous-${UUID.randomUUID()}"; val root = File(context.cacheDir, name).apply { mkdirs() }
        val bytes = context.assets.open("roadworks/snapshot-v1.json").use { it.readBytes() }
        val id = RoadworksAdvisory.sha256(bytes); val now = Instant.now().toString()
        File(root, "$id.json").writeBytes(bytes)
        val manifest = JSONObject().put("schema_version", 1).put("region", "DE-BW").put("feature_enabled", true)
            .put("snapshot_id", id).put("snapshot_bytes", bytes.size).put("snapshot_path", "/youspeed/live/v1/regions/DE-BW/snapshots/$id")
            .put("freshness", JSONObject().put("status", "fresh").put("server_time", now).put("source_publication_at", now).put("source_modified_at", now).put("last_checked_at", now))
            .put("coverage", JSONObject().put("region", "DE-BW").put("complete_road_coverage", false).put("autobahn_included", false))
            .put("attributions", JSONArray().put(JSONObject().put("provider", "fixture")))
        File(root, "previous-manifest.json").writeText(manifest.toString()); File(root, "manifest.json").writeText("broken-current")
        context.getSharedPreferences(name, 0).edit().putBoolean("enabled", true).commit()
        lateinit var service: RoadworksService
        instrumentation.runOnMainSync { service = RoadworksService(context, name) { _, _, _, _ -> RoadworksService.Reply(200, "{\"schema_version\":2}".toByteArray(), null, null, 0.0, 0.0) } }
        service.awaitDownloadsForTests(); instrumentation.waitForIdleSync()
        instrumentation.runOnMainSync {
            service.update(Location("gps").apply { latitude = 48.0; longitude = 8.0; time = System.currentTimeMillis(); accuracy = 5f })
            assertFalse(service.nearby.isEmpty()); assertEquals("unknown", service.status)
            service.refresh(explicit = true)
        }
        service.awaitDownloadsForTests(); instrumentation.waitForIdleSync()
        instrumentation.runOnMainSync {
            assertEquals("update_required", service.status)
            service.session(false, true); assertEquals("update_required", service.status)
            service.updateEnabled(false); service.clearCache()
        }
        service.awaitDownloadsForTests(); context.getSharedPreferences(name, 0).edit().clear().commit()
    }
    @Test fun defaultOffSingleFlightDisableRejectsLateResponse() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val requests = AtomicInteger()
        val started = CountDownLatch(1); val release = CountDownLatch(1)
        lateinit var service: RoadworksService
        val name = "roadworks-test-${UUID.randomUUID()}"
        instrumentation.runOnMainSync {
            service = RoadworksService(context, name) { _, _, _, _ ->
                requests.incrementAndGet(); started.countDown(); release.await(5, TimeUnit.SECONDS)
                RoadworksService.Reply(503, ByteArray(0), null, null, 0.0, 0.0)
            }
            service.session(true, true); service.refresh(explicit = true)
            assertFalse(service.enabled); assertEquals(0, requests.get())
            service.updateEnabled(true); service.refresh(explicit = true)
        }
        assertTrue(started.await(3, TimeUnit.SECONDS))
        assertEquals(1, requests.get())
        instrumentation.runOnMainSync { service.updateEnabled(false); assertNull(service.card) }
        release.countDown(); service.awaitDownloadsForTests(); instrumentation.waitForIdleSync()
        instrumentation.runOnMainSync { assertEquals("off", service.status); service.clearCache() }
        context.getSharedPreferences(name, 0).edit().clear().commit()
    }
}
