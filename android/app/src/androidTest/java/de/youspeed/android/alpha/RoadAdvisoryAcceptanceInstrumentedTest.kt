package de.youspeed.android.alpha

import android.content.Context
import android.content.Intent
import android.location.Location
import android.graphics.Bitmap
import android.os.SystemClock
import android.os.Handler
import android.os.Looper
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.text.TextLayoutResult
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import java.io.File
import java.time.Instant
import java.util.Locale
import java.util.UUID
import java.util.concurrent.atomic.AtomicInteger
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test

/** No live transport or driver data. Captured assets, when supplied, are inert test APK assets. */
class RoadAdvisoryAcceptanceInstrumentedTest {
    @get:Rule val compose = createEmptyComposeRule()
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext.also {
        check(it.packageName.endsWith(".testhost")) { "Acceptance requires the isolated test host" }
    }

    private data class Fixture(val bytes: ByteArray, val manifest: JSONObject) {
        val parsed get() = RoadworksAdvisory.parseManifest(manifest.toString().toByteArray())
        val snapshot get() = RoadworksAdvisory.parseSnapshot(bytes, RoadworksAdvisory.sha256(bytes))
    }
    private fun asset(name: String) = context.assets.open("roadworks/$name").use { it.readBytes() }
    private fun activeFixture(): Fixture {
        val manifest = JSONObject(asset("manifest-v2.json").toString(Charsets.UTF_8))
        val root = JSONObject(asset("snapshot-v2.json").toString(Charsets.UTF_8))
        val rows = root.getJSONArray("features")
        val row = (0 until rows.length()).map { rows.getJSONObject(it) }
            .first { it.getJSONObject("properties").getString("kind") == "incident" }
        val publication = Instant.parse(manifest.getJSONArray("sources").getJSONObject(1)
            .getJSONObject("freshness").getString("source_publication_at"))
        val properties = row.getJSONObject("properties")
        properties.put("validity_basis", "reported_active").put("source_validity_status", "active")
            .put("source_validity_start", "2026-10-20T10:00:00Z").put("source_validity_end", "2026-10-21T10:00:00Z")
            .put("outer_start", publication.toString()).put("outer_end", publication.plusSeconds(900).toString())
            .put("schedule_status", "resolved").put("active_intervals", JSONArray().put(JSONObject()
                .put("start", publication.toString()).put("end", publication.plusSeconds(900).toString())))
        root.put("features", JSONArray().put(row))
        val bytes = root.toString().toByteArray(); val id = RoadworksAdvisory.sha256(bytes)
        manifest.put("snapshot_id", id).put("snapshot_bytes", bytes.size)
            .put("snapshot_path", "/youspeed/live/v2/regions/DE-BW/snapshots/$id")
        val sources = manifest.getJSONArray("sources")
        for (index in 0 until sources.length()) {
            val source = sources.getJSONObject(index); val enabled = source.getString("source_id") == "incidents-bw"
            source.put("enabled", enabled).getJSONObject("freshness").put("status", if (enabled) "fresh" else "unavailable")
        }
        manifest.getJSONObject("coverage").put("autobahn_included", false)
        return Fixture(bytes, manifest)
    }
    private fun capturedFixture(): Pair<Fixture, JSONObject> {
        val assets = instrumentation.context.assets
        val available = runCatching { assets.open("incident-acceptance/receipt.json").close() }.isSuccess
        assumeTrue("Supply private incident-acceptance assets for captured publication acceptance", available)
        fun read(name: String) = assets.open("incident-acceptance/$name").use { it.readBytes() }
        return Fixture(read("snapshot.json"), JSONObject(read("manifest.json").toString(Charsets.UTF_8))) to
            JSONObject(read("receipt.json").toString(Charsets.UTF_8))
    }
    private inner class Harness(val fixture: Fixture, val name: String = "incident-acceptance-${UUID.randomUUID()}") : AutoCloseable {
        lateinit var service: RoadworksService
        var code = 200
        var manifest = fixture.manifest
        val requests = AtomicInteger()
        val validators = mutableListOf<String?>()
        init { instrumentation.runOnMainSync {
            service = RoadworksService(context, name) { path, validator, _, _ ->
                requests.incrementAndGet()
                synchronized(validators) { validators += validator }
                RoadworksService.Reply(if (path.contains("/snapshots/")) 200 else code,
                    if (path.contains("/snapshots/")) fixture.bytes else manifest.toString().toByteArray(),
                    "acceptance-etag", fixture.parsed.serverTime, 0.0, 0.0)
            }
        }; settle() }
        fun settle() { service.awaitDownloadsForTests(); instrumentation.waitForIdleSync() }
        fun enable() { instrumentation.runOnMainSync { service.updateEnabled(true) }; settle() }
        fun refresh() { instrumentation.runOnMainSync { service.refresh(explicit = true) }; settle() }
        fun fix(point: RoadworksAdvisory.Point = fixture.snapshot.features.single().points.first()) {
            instrumentation.runOnMainSync { service.update(Location("gps").apply {
                latitude = point.latitude; longitude = point.longitude; accuracy = 5f; time = System.currentTimeMillis()
            }) }
        }
        fun confirm(point: RoadworksAdvisory.Point = fixture.snapshot.features.single().points.first()) {
            instrumentation.runOnMainSync { service.session(true, true) }
            settle()
            fix(point); SystemClock.sleep(20); fix(point)
        }
        fun clock() = RoadworksService::class.java.getDeclaredField("receivedUptime").apply { isAccessible = true }
        fun advance(seconds: Double) { instrumentation.runOnMainSync { clock().setDouble(service, clock().getDouble(service) - seconds) } }
        fun whileFreshFixes(point: RoadworksAdvisory.Point, block: () -> Unit) {
            val handler = Handler(Looper.getMainLooper())
            val pulse = object : Runnable { override fun run() {
                service.update(Location("gps").apply {
                    latitude = point.latitude; longitude = point.longitude; accuracy = 5f; time = System.currentTimeMillis()
                })
                handler.postDelayed(this, 250)
            } }
            handler.post(pulse)
            try { block() } finally { instrumentation.runOnMainSync { handler.removeCallbacks(pulse) } }
        }
        override fun close() {
            instrumentation.runOnMainSync { service.session(false, false); service.updateEnabled(false); service.clearCache() }
            settle(); context.deleteSharedPreferences(name)
        }
    }

    @Test fun capturedPublicationMatchesBackendReceiptOnDevice() {
        val (fixture, receipt) = capturedFixture(); val cache = RoadworksSnapshotCache()
        cache.install(fixture.bytes, fixture.parsed)
        val snapshot = requireNotNull(cache.snapshot); val checked = Instant.parse(receipt.getString("checked_at_utc"))
        assertEquals(receipt.getString("snapshot_sha256"), snapshot.id)
        assertEquals(receipt.getInt("exported_features"), snapshot.features.size)
        assertEquals(receipt.getInt("reported_active_features"), snapshot.features.count { it.validityBasis == "reported_active" })
        assertEquals(setOf("incidents-bw"), fixture.parsed.sources.filter { it.enabled }.map { it.id }.toSet())
        assertTrue(snapshot.features.all { it.advisorySource == "incidents-bw" })
        val elapsed = java.time.Duration.between(fixture.parsed.serverTime, checked).toNanos() / 1e9
        val trusted = requireNotNull(fixture.parsed.trustedNow(0.0, elapsed))
        assertEquals(checked, trusted)
        val source = fixture.parsed.sourceFreshness(0.0, elapsed)["incidents-bw"]
        assertEquals(receipt.getInt("eligible_features"), snapshot.features.count {
            it.eligible(trusted) && source in setOf(RoadworksAdvisory.Freshness.FRESH, RoadworksAdvisory.Freshness.DELAYED)
        })
    }

    @Test fun sourceActiveUsesTrustedClockAnd304CannotExtendItsLease() = Harness(activeFixture()).use { h ->
        h.enable(); h.confirm()
        instrumentation.runOnMainSync {
            assertNotNull("Recorded publication clock must be separate from current GPS wall time", h.service.card)
            assertEquals("reported_active", h.service.card!!.feature.validityBasis)
            assertEquals(Instant.parse("2026-10-21T10:00:00Z"), h.service.card!!.feature.sourceValidityEnd)
            assertEquals("off", h.service.sourceStatus("bemas")); assertEquals("off", h.service.sourceStatus("autobahn-short-term"))
        }
        val original = h.clock().getDouble(h.service)
        h.code = 304; h.refresh()
        assertEquals(original, h.clock().getDouble(h.service), 0.0)
        assertTrue(h.validators.any { it == "acceptance-etag" })
        h.advance(841.0); h.fix()
        instrumentation.runOnMainSync { assertNull(h.service.card); assertEquals("unavailable", h.service.sourceStatus("incidents-bw")) }
    }

    @Test fun rejectedPublicationBindingAndHttpFailureKeepAcceptedCache() = Harness(activeFixture()).use { h ->
        h.enable(); h.confirm(); val id = h.service.card!!.feature.id
        val changed = JSONObject(h.fixture.manifest.toString())
        val freshness = changed.getJSONArray("sources").getJSONObject(1).getJSONObject("freshness")
        freshness.put("source_publication_at", Instant.parse(freshness.getString("source_publication_at")).plusSeconds(1).toString())
        h.manifest = changed; h.refresh(); h.confirm()
        instrumentation.runOnMainSync { assertEquals("offline", h.service.status); assertEquals(id, h.service.card?.feature?.id) }
        h.code = 503; h.refresh(); h.confirm()
        instrumentation.runOnMainSync { assertEquals("offline", h.service.status); assertEquals(id, h.service.card?.feature?.id) }
        h.advance(1800.0); h.fix()
        instrumentation.runOnMainSync { assertNull(h.service.card) }
    }

    @Test fun restoredCacheRequiresNewClockBindingEvenAfter304() {
        val fixture = activeFixture(); val name = "incident-restored-${UUID.randomUUID()}"
        val directory = File(context.cacheDir, name).apply { mkdirs() }
        File(directory, "manifest.json").writeText(fixture.manifest.toString())
        File(directory, "${RoadworksAdvisory.sha256(fixture.bytes)}.json").writeBytes(fixture.bytes)
        context.getSharedPreferences(name, Context.MODE_PRIVATE).edit().putBoolean("enabled", true).commit()
        Harness(fixture, name).use { h ->
            h.code = 304; h.refresh(); h.confirm()
            instrumentation.runOnMainSync { assertNull(h.service.card); assertEquals("unknown", h.service.sourceStatus("incidents-bw")) }
            h.code = 200; h.refresh(); h.confirm()
            instrumentation.runOnMainSync { assertNotNull(h.service.card); assertEquals("fresh", h.service.sourceStatus("incidents-bw")) }
        }
    }

    @Test fun oldSourceModifiedTimeSuppressesOtherwiseActiveReport() {
        val fixture = activeFixture()
        fixture.manifest.getJSONArray("sources").getJSONObject(1).getJSONObject("freshness")
            .put("source_modified_at", fixture.parsed.serverTime.minusSeconds(1800).toString())
        Harness(fixture).use { h ->
            h.enable(); h.confirm()
            instrumentation.runOnMainSync {
                assertNull(h.service.card); assertEquals("unavailable", h.service.sourceStatus("incidents-bw"))
                assertEquals(1, h.service.nearby.size)
            }
        }
    }

    @Test fun capturedIncidentRendersExistingDashboardAndParkedDetails() {
        val (fixture, _) = capturedFixture()
        val at = fixture.parsed.serverTime
        val feature = fixture.snapshot.features.first { it.kind in setOf("incident", "congestion", "hazard") && it.validityBasis == "reported_active" && it.eligible(at) &&
            fixture.snapshot.features.none { other -> other.kind == "closure" && other.eligible(at) && RoadworksAdvisory.distance(it.points.first(), other) <= 500 } }
        val singleton = RoadworksService::class.java.getDeclaredField("instance").apply { isAccessible = true }
        val previous = singleton.get(null); val locale = Locale.getDefault()
        Locale.setDefault(Locale.GERMANY)
        Harness(fixture).use { h ->
            singleton.set(null, h.service); h.enable()
            try {
                ActivityScenario.launch<MainActivity>(Intent(context, MainActivity::class.java)
                    .putExtra("screenshot_state", "camera-limit-active").putExtra("screenshot_speed", 0)).use { scenario ->
                    scenario.onActivity { it.applyManualOrientation(ManualOrientation.PORTRAIT) }
                    h.confirm(feature.points.first())
                    h.whileFreshFixes(feature.points.first()) {
                    compose.waitUntil(10_000) { h.service.card?.feature?.kind in setOf("incident", "congestion", "hazard") }
                    val shown = requireNotNull(h.service.card).feature
                    val summary = compose.onNodeWithTag("dashboard-roadworks-summary").assertIsDisplayed().assertTextContains("0 m", substring = true)
                    val metadata = compose.onNodeWithTag("dashboard-roadworks-metadata").assertIsDisplayed()
                        .assertTextContains("BW-Verkehrsmeldungen", substring = true)
                        .assertTextContains("Alter der Quelldaten: ${h.service.sourceAgeMinutes("incidents-bw")} min", substring = true)
                    val layouts = mutableListOf<TextLayoutResult>()
                    metadata.performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
                    assertEquals(1, layouts.size)
                    val layout = layouts.single()
                    File(context.filesDir, "incident-testdata-metadata-layout.json").writeText(JSONObject()
                        .put("text", layout.layoutInput.text.text).put("line_count", layout.lineCount)
                        .put("overflow_height", layout.didOverflowHeight).put("overflow_width", layout.didOverflowWidth)
                        .put("constraints", layout.layoutInput.constraints.toString()).put("size", layout.size.toString())
                        .put("paragraph_width", layout.multiParagraph.width)
                        .put("lines", JSONArray((0 until layout.lineCount).map { line -> JSONObject().put("end", layout.getLineEnd(line))
                            .put("visible_end", layout.getLineEnd(line, visibleEnd = true)).put("ellipsized", layout.isLineEllipsized(line)) }))
                        .toString(2))
                    assertTrue(UiDevice.getInstance(instrumentation).takeScreenshot(File(context.filesDir, "incident-testdata-layout-debug.png")))
                    // didOverflowWidth compares an integer intrinsic size with a
                    // fractional paragraph width. Check actual truncation and
                    // full visible character range rather than that proxy.
                    assertFalse("Source and age must fit vertically", layout.didOverflowHeight)
                    assertTrue("Source and age must fit the available dashboard width", layout.multiParagraph.width <= layout.layoutInput.constraints.maxWidth.toFloat())
                    assertTrue("A long road name must not ellipsize source or age", (0 until layout.lineCount).none { layout.isLineEllipsized(it) })
                    assertEquals(layout.layoutInput.text.length, layout.getLineEnd(layout.lineCount - 1, visibleEnd = true))
                    assertTrue(layouts.single().lineCount <= 2)
                    val metadataBounds = metadata.fetchSemanticsNode().boundsInWindow
                    val summaryBounds = summary.fetchSemanticsNode().boundsInWindow
                    val roadBounds = compose.onNodeWithTag("dashboard-roadworks-road").assertIsDisplayed().fetchSemanticsNode().boundsInWindow
                    val mainBounds = compose.onNodeWithTag("main-root").fetchSemanticsNode().boundsInWindow
                    assertTrue(summaryBounds.bottom <= metadataBounds.top && metadataBounds.bottom <= roadBounds.top)
                    assertTrue(metadataBounds.top >= mainBounds.top && metadataBounds.bottom <= mainBounds.bottom)
                    val metadataBitmap = metadata.captureToImage().asAndroidBitmap()
                    var metadataLightPixels = 0
                    for (y in 0 until metadataBitmap.height) for (x in 0 until metadataBitmap.width) {
                        val pixel = metadataBitmap.getPixel(x, y)
                        if (android.graphics.Color.red(pixel) > 180 && android.graphics.Color.green(pixel) > 180 && android.graphics.Color.blue(pixel) > 180) metadataLightPixels++
                    }
                    assertTrue("Source and age must be visible pixels on the rendered dashboard", metadataLightPixels > 100)
                    File(context.filesDir, "incident-testdata-metadata.png").outputStream().use { metadataBitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
                    val caption = compose.onNodeWithTag("dashboard-roadworks").assertIsDisplayed()
                    val bitmap = caption.captureToImage().asAndroidBitmap()
                    var visiblePixels = 0
                    for (y in 0 until bitmap.height) for (x in 0 until bitmap.width) {
                        val pixel = bitmap.getPixel(x, y)
                        if (android.graphics.Color.red(pixel) > 180 && android.graphics.Color.green(pixel) > 180 && android.graphics.Color.blue(pixel) > 180) visiblePixels++
                    }
                    assertTrue("Caption must contain visible light text against the actual dark dashboard", visiblePixels > 100)
                    File(context.filesDir, "incident-testdata-caption.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
                    val captionBounds = caption.fetchSemanticsNode().boundsInWindow.toString()
                    compose.onNodeWithTag("primary-metric").assertTextEquals("0")
                    val device = UiDevice.getInstance(instrumentation)
                    assertTrue(device.takeScreenshot(File(context.filesDir, "incident-testdata-dashboard.png")))
                    compose.onNodeWithTag("settings-button").performClick()
                    compose.onNodeWithTag("settings-list").performScrollToNode(hasText("Live-Verkehrshinweise"))
                    compose.onNodeWithText("Live-Verkehrshinweise").assertIsDisplayed()
                    assertTrue(device.takeScreenshot(File(context.filesDir, "incident-testdata-settings.png")))
                    compose.onNodeWithTag("settings-list").performScrollToNode(hasText(shown.publisherRecordId, substring = true))
                    compose.onNodeWithText("Quelle meldet aktiv; Meldung verfällt", substring = true).assertExists()
                    assertTrue(device.takeScreenshot(File(context.filesDir, "incident-testdata-details.png")))
                    File(context.filesDir, "incident-testdata-receipt.json").writeText(JSONObject()
                        .put("test_data", true).put("transport", "injected; no live requests")
                        .put("snapshot_sha256", fixture.parsed.snapshotId).put("shown_feature_id", shown.id)
                        .put("caption_bounds", captionBounds).put("caption_light_pixels", visiblePixels)
                        .put("metadata_bounds", metadataBounds.toString()).put("metadata_light_pixels", metadataLightPixels)
                        .put("metadata_ellipsized", (0 until layout.lineCount).any { layout.isLineEllipsized(it) })
                        .put("metadata_full_text_visible", layout.getLineEnd(layout.lineCount - 1, visibleEnd = true) == layout.layoutInput.text.length)
                        .put("recorded_server_time", at.toString()).put("gps", "synthetic point on recorded feature; stationary dashboard")
                        .toString(2))
                    }
                }
            } finally { singleton.set(null, previous); Locale.setDefault(locale) }
        }
    }
}
