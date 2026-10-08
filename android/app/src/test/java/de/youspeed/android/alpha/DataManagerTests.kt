package de.youspeed.android.alpha

import java.io.ByteArrayInputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import org.junit.Assert.*
import org.junit.Test

class DataManagerTests {
    private fun file(path: String): File = listOf(File(path), File("../../$path"), File("../$path"))
        .first { it.isFile }

    @Test fun officialArtworkMatchesEveryDownloadOptionWithoutReplacingRoutingCoverage() {
        val bytes = file("shared/RegionalCoverage/official-regions-v1.json").readBytes()
        val catalog = DataManagerMapCatalog.decode(bytes)
        val targets = ContractJson.decodeBundleTargets(file("android/app/src/main/assets/BundleTargets.top10.json").readText())
        val ids = targets.manifestEndpoints().map { "${it.countryId}|${it.manifestRegion}" }.toSet()
        assertEquals(51, ids.size)
        assertEquals(ids, catalog.regions.map { it.id }.toSet())
        assertTrue(catalog.attribution.contains("EuroGeographics"))
        assertThrows(IllegalArgumentException::class.java) {
            DataManagerMapCatalog.decode(file("shared/RegionalCoverage/catalog-v1.json").readBytes())
        }
        // Berlin is a hole in the Brandenburg artwork, not a competing rectangle.
        assertEquals("germany|berlin", catalog.hit(13.405, 52.52, ids))
        assertNull(catalog.hit(13.405, 52.52, setOf("germany|brandenburg")))
        assertNull(catalog.hit(0.0, 0.0, ids))
    }

    @Test fun hitTestingRespectsHolesIslandsAndAvailableOptions() {
        val outer = listOf(listOf(0.0, 0.0), listOf(4.0, 0.0), listOf(4.0, 4.0), listOf(0.0, 4.0), listOf(0.0, 0.0))
        val hole = listOf(listOf(1.0, 1.0), listOf(2.0, 1.0), listOf(2.0, 2.0), listOf(1.0, 2.0), listOf(1.0, 1.0))
        val island = listOf(listOf(6.0, 6.0), listOf(7.0, 6.0), listOf(7.0, 7.0), listOf(6.0, 7.0), listOf(6.0, 6.0))
        val region = DataManagerRegion("a|a", listOf(0.0, 0.0, 7.0, 7.0), listOf(listOf(outer, hole), listOf(island)))
        val small = DataManagerRegion("b|b", listOf(0.0, 0.0, 4.0, 4.0), listOf(listOf(outer, hole)))
        val catalog = DataManagerMapCatalog(listOf(region, small), "fixture")
        assertFalse(region.contains(1.5, 1.5))
        assertTrue(region.contains(6.5, 6.5))
        assertFalse(region.contains(Double.NaN, 2.0))
        assertEquals("b|b", catalog.hit(3.0, 3.0, setOf("a|a", "b|b")))
        assertNull(catalog.hit(6.5, 6.5, setOf("b|b")))
    }

    @Test fun viewportRoundTripsAndFitsEveryTinyOrOverseasRegion() {
        val catalog = DataManagerMapCatalog.decode(file("shared/RegionalCoverage/official-regions-v1.json").readBytes())
        for (region in catalog.regions) {
            val viewport = DataManagerViewport.fit(region.bounds)
            for ((width, height) in listOf(320.0 to 280.0, 480.0 to 230.0)) {
                val center = viewport.coordinateAt(width / 2, height / 2, width, height)
                assertEquals(viewport.centerX, DataManagerViewport.projectX(center.first), 1e-10)
                assertEquals(viewport.centerY, DataManagerViewport.projectY(center.second), 1e-10)
                val topLeft = viewport.coordinateAt(0.0, 0.0, width, height)
                val bottomRight = viewport.coordinateAt(width, height, width, height)
                assertTrue("${region.id} remains reachable", topLeft.first <= region.bounds[0] && topLeft.second >= region.bounds[3] &&
                    bottomRight.first >= region.bounds[2] && bottomRight.second <= region.bounds[1])
            }
        }
        val viewport = DataManagerViewport.GERMANY
        val oldAnchor = viewport.coordinateAt(120.0, 100.0, 400.0, 300.0)
        val zoomed = viewport.transformed(0.0, 0.0, 2.0, 120.0, 100.0, 400.0, 300.0)
        val newAnchor = zoomed.coordinateAt(120.0, 100.0, 400.0, 300.0)
        assertEquals(oldAnchor.first, newAnchor.first, 1e-10)
        assertEquals(oldAnchor.second, newAnchor.second, 1e-10)
        assertEquals(viewport, viewport.transformed(0.0, 0.0, Double.NaN, 0.0, 0.0, 400.0, 300.0))
    }

    @Test fun initialGermanyFocusFitsAllStatesAndIsTighterThanEurope() {
        val catalog = DataManagerMapCatalog.decode(file("shared/RegionalCoverage/official-regions-v1.json").readBytes())
        val states = catalog.regions.filter { it.id.startsWith("germany|") }
        assertEquals(16, states.size)
        val viewport = DataManagerViewport.GERMANY
        assertEquals(DataManagerViewport.fit(listOf(5.5, 47.0, 15.8, 55.6)), viewport)
        assertTrue("Initial focus is meaningfully tighter than Europe", viewport.span < DataManagerViewport.EUROPE.span / 2)
        for ((width, height) in listOf(320.0 to 230.0, 480.0 to 200.0)) {
            val topLeft = viewport.coordinateAt(0.0, 0.0, width, height)
            val bottomRight = viewport.coordinateAt(width, height, width, height)
            states.forEach { state ->
                assertTrue("${state.id} fits the initial viewport", topLeft.first <= state.bounds[0] &&
                    topLeft.second >= state.bounds[3] && bottomRight.first >= state.bounds[2] &&
                    bottomRight.second <= state.bounds[1])
            }
        }
        assertEquals(viewport, DataManagerViewport(Double.NaN, Double.NaN, Double.NaN).safe())
        assertEquals(51, catalog.regions.size)
    }

    @Test fun legacyCountryCoverageIsExplicitAndExactPackageWins() {
        val legacy = DataManagerScopeResolver.resolve("bayern", "germany", setOf("germany"))
        assertEquals(DataManagerPackageScope("germany", true), legacy)
        val exact = DataManagerScopeResolver.resolve("bayern", "germany", setOf("germany", "bayern"))
        assertEquals(DataManagerPackageScope("bayern", false), exact)
        assertEquals(DataManagerPackageScope("belgium", false), DataManagerScopeResolver.resolve("belgium", "belgium", setOf("belgium")))
        assertNull(DataManagerScopeResolver.resolve("bayern", "germany", emptySet()))
        // A previously confirmed shard must not silently become a whole-country deletion.
        assertNotEquals(exact?.regionKey, legacy?.regionKey)
    }

    @Test fun packageSizeIsTransferBytesAndInvalidDatesStayUnknown() {
        val single = DataManagerPackageMetadata.fromManifest(manifest())
        assertEquals(123L, single.bytes)
        assertEquals("2026-09-15T12:00:00Z", single.createdAtUTC)
        val parts = listOf(artifact(100), artifact(200))
        assertEquals(300L, DataManagerPackageMetadata.fromManifest(manifest(parts)).bytes)
        assertNull(DataManagerPackageMetadata.fromManifest(manifest(listOf(artifact(0)))).bytes)
        assertNull(DataManagerPackageMetadata.fromManifest(manifest(listOf(artifact(Long.MAX_VALUE), artifact(1)))).bytes)
        assertNull(DataManagerPackageMetadata.fromManifest(manifest(createdAt = "not a date")).createdAtUTC)
    }

    @Test fun metadataReadsAreBoundedAndDoNotRequireDatabaseDownloads() {
        assertArrayEquals("{}".toByteArray(), DataManagerManifestReader.readBounded(ByteArrayInputStream("{}".toByteArray())))
        assertThrows(IllegalStateException::class.java) {
            DataManagerManifestReader.readBounded(ByteArrayInputStream(ByteArray(DataManagerManifestReader.MAX_BYTES + 1)))
        }
        assertThrows(IllegalStateException::class.java) {
            DataManagerManifestReader.readBounded(ByteArrayInputStream(ByteArray(1))) { error("deadline") }
        }
    }

    @Test fun installedPrecedesAvailabilityAndFailuresNeverMeanUnavailable() {
        val packageMetadata = DataManagerPackageMetadata("v1", null, 100L)
        DataManagerMetadataStatus.entries.forEach { status ->
            assertEquals(DataManagerDisplayState.INSTALLED, dataManagerDisplayState(true,
                DataManagerMetadataState(status, packageMetadata)))
        }
        assertEquals(DataManagerDisplayState.AVAILABLE, dataManagerDisplayState(false,
            DataManagerMetadataState(DataManagerMetadataStatus.READY, packageMetadata)))
        assertEquals(DataManagerDisplayState.UNAVAILABLE, dataManagerDisplayState(false,
            DataManagerMetadataState(DataManagerMetadataStatus.UNAVAILABLE)))
        listOf(DataManagerMetadataStatus.LOADING, DataManagerMetadataStatus.ERROR).forEach { status ->
            assertEquals(DataManagerDisplayState.UNKNOWN, dataManagerDisplayState(false,
                DataManagerMetadataState(status, packageMetadata)))
        }
        assertEquals(DataManagerDisplayState.UNKNOWN, dataManagerDisplayState(false, null))
    }

    @Test fun releaseIndexProvidesUndownloadedBundleMetadataWithoutClaimingMissingBundlesUnavailable() {
        val payload = """{"format":"youspeed.v3.bundle.metadata","schema_version":1,"bundles":[
            {"id":"germany|berlin","manifest_url":"https://fixture.test/berlin_manifest.json",
             "bundle_version":"v1","created_at_utc":"2026-10-01T10:00:00Z","download_bytes":300}]}"""
        val entries = DataManagerMetadataIndex.decode(payload.toByteArray())
        val berlin = entries.getValue("germany|berlin")
        assertEquals(300L, berlin.metadata.bytes)
        assertEquals("2026-10-01T10:00:00Z", berlin.metadata.createdAtUTC)
        assertEquals(DataManagerDisplayState.AVAILABLE, dataManagerDisplayState(false,
            DataManagerMetadataState(metadata = berlin.metadata)))
        assertEquals(DataManagerDisplayState.UNKNOWN, dataManagerDisplayState(false, null))
        for ((from, to) in listOf("\"schema_version\":1" to "\"schema_version\":2", "\"download_bytes\":300" to "\"download_bytes\":0",
            "2026-10-01T10:00:00Z" to "invalid")) {
            assertThrows(Exception::class.java) { DataManagerMetadataIndex.decode(payload.replace(from, to).toByteArray()) }
        }
    }

    @Test fun releaseIndexCacheSurvivesRestartAndRejectsOtherSourcesAndCorruption() {
        val payload = """{"format":"youspeed.v3.bundle.metadata","schema_version":1,"bundles":[
            {"id":"germany|berlin","manifest_url":"https://fixture.test/berlin_manifest.json",
             "bundle_version":"v1","created_at_utc":"2026-10-01T10:00:00Z","download_bytes":300}]}""".toByteArray()
        val directory = java.nio.file.Files.createTempDirectory("metadata-index-test").toFile()
        try {
            val source = DataManagerMetadataIndex.releaseUrl("volzinnovation", "youspeed.de")
            assertEquals("https://github.com/volzinnovation/youspeed.de/releases/download/bundle-metadata/bundle-metadata.v3.json", source)
            val cache = DataManagerMetadataIndexCache(directory, source)
            assertNull(cache.load())
            cache.save(payload)
            val restored = DataManagerMetadataIndexCache(directory, source).load()!!
            assertEquals(300L, restored.getValue("germany|berlin").metadata.bytes)
            assertEquals(1, DataManagerMetadataIndex.matching(restored, mapOf("germany|berlin" to "https://fixture.test/berlin_manifest.json")).size)
            assertTrue(DataManagerMetadataIndex.matching(restored, mapOf("germany|berlin" to source)).isEmpty())
            assertTrue(DataManagerMetadataIndex.matching(restored, mapOf("germany|bayern" to "https://fixture.test/berlin_manifest.json")).isEmpty())
            assertNull(DataManagerMetadataIndexCache(directory, "https://other.test/index").load())
            assertThrows(Exception::class.java) { cache.save("invalid".toByteArray()) }
            assertEquals(1, cache.load()!!.size)
            cache.save(payload)
            cache.file.writeText("corrupt")
            assertNull(cache.load())
            assertThrows(Exception::class.java) { DataManagerMetadataIndex.decode(ByteArray(DataManagerMetadataIndex.MAX_BYTES + 1)) }
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test fun otherRegionsRemainDownloadableWhileOneTransferRuns() {
        val active = DataManagerTransferState.resolve("belgium", "belgium", listOf("switzerland"), emptyMap())
        val waiting = DataManagerTransferState.resolve("switzerland", "belgium", listOf("switzerland"), emptyMap())
        val another = DataManagerTransferState.resolve("netherlands", "belgium", listOf("switzerland"), emptyMap())
        assertTrue(active.active)
        assertFalse(active.canRequest(null))
        assertTrue(waiting.queued)
        assertFalse(waiting.canRequest(null))
        assertTrue("Another region can be requested independently", another.canRequest(null))
        assertFalse(another.canRequest(DataManagerMetadataState(DataManagerMetadataStatus.UNAVAILABLE)))
        val overlap = DataManagerTransferState.resolve("belgium", "belgium", listOf("belgium"), emptyMap())
        assertFalse("Active progress must never offer queued cancellation", overlap.queued)
    }

    @Test fun perRegionFailuresSurviveOtherDownloadsAndAllowRetry() {
        val errors = mapOf("belgium" to "HTTP 503")
        val failed = DataManagerTransferState.resolve("belgium", "switzerland", emptyList(), errors)
        val active = DataManagerTransferState.resolve("switzerland", "switzerland", emptyList(), errors)
        assertEquals("HTTP 503", failed.error)
        assertTrue(failed.canRequest(null))
        assertNull("An unrelated failure is not assigned to the active region", active.error)
        assertNull("A queued retry takes precedence over previous failure text",
            DataManagerTransferState.resolve("belgium", "switzerland", listOf("belgium"), errors).error)
    }

    @Test fun multipleManagerRequestsKeepExistingQueueOrderAcrossCancellationAndFailure() {
        val queue = BundleDownloadQueue<String> { it }
        listOf("belgium", "netherlands", "switzerland", "netherlands").forEach { queue.enqueue(it, "belgium") }
        assertEquals(listOf("netherlands", "switzerland"), queue.ids)
        assertNull("Downloads wait while the active transfer or bundle removal is busy", queue.next(true))
        queue.remove("netherlands")
        assertEquals(listOf("switzerland"), queue.ids)
        assertEquals("A failure of the active download does not drop the remaining queue", "switzerland", queue.next(false))
        assertNull(queue.next(false))
    }

    @Test fun only404And410BecomeConfirmedUnavailable() {
        val endpoint = V3ManifestEndpoint("germany", "DEU", "germany/bayern", "bayern", "Bayern", "https://fixture.test/manifest.json")
        fun reader(status: Int) = DataManagerManifestReader { url -> object : HttpURLConnection(url) {
            override fun connect() = Unit
            override fun disconnect() = Unit
            override fun usingProxy() = false
            override fun getResponseCode() = status
        } }
        for (status in listOf(404, 410)) assertThrows(DataManagerPackageUnavailable::class.java) { reader(status).read(endpoint) }
        for (status in listOf(401, 403, 429, 500, 503)) assertThrows(IllegalStateException::class.java) { reader(status).read(endpoint) }
    }

    @Test fun regionSearchIgnoresAccentsAndMatchesCountryWords() {
        assertTrue(dataManagerSearchMatches("Réunion France", "reunion"))
        assertTrue(dataManagerSearchMatches("Baden-Württemberg Deutschland", "baden deutsch"))
        assertTrue(dataManagerSearchMatches("Mayotte France", ""))
        assertFalse(dataManagerSearchMatches("Bayern Deutschland", "france"))
    }

    private fun artifact(bytes: Long) = BundleArtifact("map.zlib", bytes, "fixture", null, "zlib", 999L, "fixture")
    private fun manifest(parts: List<BundleArtifact>? = null, createdAt: String = "2026-09-15T12:00:00Z") = V3BundleManifest(
        format = "youspeed.v3.bundle.manifest", schemaVersion = 1, variant = "v3", region = "bayern", countryCode = "DEU",
        bundleVersion = "2026-09-15", createdAtUTC = createdAt, minAppVersion = "1.1", db = artifact(123), dbParts = parts,
        deltaIndex = null, penaltyRules = null, coverage = null,
    )
}
