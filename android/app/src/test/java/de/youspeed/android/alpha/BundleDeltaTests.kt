package de.youspeed.android.alpha

import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.zip.DeflaterOutputStream
import org.junit.Assert.*
import org.junit.Test

class BundleDeltaTests {
    @Test fun endpointSyncProcessesAllPreferredCountryShardsAndReturnsLastSuccess() = scenario { fixture ->
        val french = fixture.endpoint("france", "FRA")
        val first = fixture.endpoint("north", "DEU")
        val failed = fixture.endpoint("failed", "DEU", available = false)
        val last = fixture.endpoint("south", "DEU")
        val progress = mutableListOf<BundleSyncProgress>()
        val result = fixture.bootstrapper.syncFromManifestEndpoints(listOf(french, first, failed, last), " deu ", progress::add)
        assertEquals("south", fixture.bootstrapper.activeState()?.region)
        assertEquals("south", File(result.dbPath).readText())
        assertEquals(listOf(first.manifestUrl, failed.manifestUrl, last.manifestUrl), fixture.requests.filter { it.endsWith("manifest.json") })
        assertTrue(progress.any { it.detail.startsWith("[3/3] DEU south:") })
    }

    @Test fun endpointSyncThrowsFirstFailureWithoutDownloadingDifferentCountry() = scenario { fixture ->
        val first = fixture.endpoint("failed1", "DEU", available = false)
        val second = fixture.endpoint("failed2", "DEU", available = false)
        val french = fixture.endpoint("france", "FRA")
        val error = assertThrows(IOException::class.java) {
            fixture.bootstrapper.syncFromManifestEndpoints(listOf(first, second, french), "DEU")
        }
        assertTrue(error.message.orEmpty().contains(first.manifestUrl))
        assertEquals(listOf(first.manifestUrl, second.manifestUrl), fixture.requests)
    }

    @Test fun endpointSyncUsesAllEndpointsWhenPreferredCountryHasNoEndpoint() = scenario { fixture ->
        val first = fixture.endpoint("france", "FRA")
        val last = fixture.endpoint("germany", "DEU")
        val result = fixture.bootstrapper.syncFromManifestEndpoints(listOf(first, last), "CHE")
        assertEquals("germany", File(result.dbPath).readText())
        assertEquals(listOf(first.manifestUrl, last.manifestUrl), fixture.requests.filter { it.endsWith("manifest.json") })
    }

    @Test fun deltaPathIsShortestDeterministicAndRegionScoped() {
        val entries = listOf(V3DeltaEntry("a", "b", "other", "wrong.json"), V3DeltaEntry("a", "b", "region", "b.json"),
            V3DeltaEntry("b", "c", null, "c.json"), V3DeltaEntry("b", "a", null, "cycle.json"))
        assertEquals(listOf("b", "c"), DeltaUpdatePolicy.path(entries, "a", "c", "region")!!.map { it.toBundleVersion })
        assertNull(DeltaUpdatePolicy.path(entries, "a", "missing", "region"))
        assertEquals(listOf("c"), DeltaUpdatePolicy.path(entries + V3DeltaEntry("a", "c", null, "direct.json"), "a", "c", "region")!!.map { it.toBundleVersion })
    }

    @Test fun staleAndUnparseableVersionsForceFullWhileSeedAndThirtyDaysAllowDelta() {
        assertFalse(DeltaUpdatePolicy.forceFullReload("seed", "2026-09-01"))
        assertFalse(DeltaUpdatePolicy.forceFullReload("2026-08-01", "2026-08-31"))
        assertTrue(DeltaUpdatePolicy.forceFullReload("2026-08-01", "2026-09-01"))
        assertTrue(DeltaUpdatePolicy.forceFullReload("unknown", "2026-09-01"))
    }

    @Test fun scriptSplittingPreservesQuotedSemicolonsAndIgnoresComments() {
        assertEquals(listOf("BEGIN IMMEDIATE", "INSERT INTO ways VALUES ('Rue de l''Église; south')", "COMMIT"),
            DeltaUpdatePolicy.sqlStatements("-- semicolon;\nBEGIN IMMEDIATE; /* ; */ INSERT INTO ways VALUES ('Rue de l''Église; south'); COMMIT;"))
        assertThrows(IllegalArgumentException::class.java) { DeltaUpdatePolicy.sqlStatements("INSERT INTO ways VALUES ('unterminated)") }
    }

    @Test fun appliesCompressedDeltaChainWithoutDownloadingFullDatabase() = scenario { fixture ->
        fixture.install("2026-09-01", "old")
        fixture.offerDelta("new", compressed = true)
        val result = fixture.bootstrapper.syncFromManifestUrl(fixture.manifestUrl)
        assertEquals(BundleSyncMode.DELTA_PATCH, result.mode)
        assertEquals("new", File(result.dbPath).readText())
        assertEquals("2026-09-02", fixture.bootstrapper.activeState()?.bundleVersion)
        assertFalse(fixture.requests.contains(fixture.fullUrl))
        assertEquals(listOf("replace:new"), fixture.applied)
    }

    @Test fun missingDeltaPathFallsBackToFullBundle() = scenario { fixture ->
        fixture.install("2026-09-01", "old")
        fixture.offerDelta("new", fromVersion = "unrelated")
        val result = fixture.bootstrapper.syncFromManifestUrl(fixture.manifestUrl)
        assertEquals(BundleSyncMode.FULL_DOWNLOAD, result.mode)
        assertTrue(fixture.requests.contains(fixture.fullUrl))
        assertTrue(fixture.applied.isEmpty())
    }

    @Test fun badPatchHashDoesNotMutateOrReplaceActiveDatabase() = scenario { fixture ->
        val original = fixture.install("2026-09-01", "old")
        fixture.offerDelta("new", badHash = true)
        assertThrows(IllegalArgumentException::class.java) { fixture.bootstrapper.syncFromManifestUrl(fixture.manifestUrl) }
        assertEquals("old", File(original.dbPath).readText())
        assertEquals("2026-09-01", fixture.bootstrapper.activeState()?.bundleVersion)
        assertTrue(fixture.applied.isEmpty())
        assertFalse(fixture.requests.contains(fixture.fullUrl))
    }

    @Test fun failedSqlAndWrongMaterializedHashKeepActiveBundle() = scenario { fixture ->
        val original = fixture.install("2026-09-01", "old")
        fixture.offerDelta("new")
        fixture.failApply = true
        assertThrows(IOException::class.java) { fixture.bootstrapper.syncFromManifestUrl(fixture.manifestUrl) }
        fixture.failApply = false
        fixture.wrongOutput = true
        assertThrows(IllegalArgumentException::class.java) { fixture.bootstrapper.syncFromManifestUrl(fixture.manifestUrl) }
        assertEquals("old", File(original.dbPath).readText())
        assertEquals("2026-09-01", fixture.bootstrapper.activeState()?.bundleVersion)
        assertTrue(File(fixture.root, "staging").listFiles().orEmpty().isEmpty())
    }

    @Test fun staleBundleSkipsDeltaIndex() = scenario { fixture ->
        fixture.install("2026-07-01", "old")
        fixture.offerDelta("new", fromVersion = "2026-07-01")
        assertEquals(BundleSyncMode.FULL_DOWNLOAD, fixture.bootstrapper.syncFromManifestUrl(fixture.manifestUrl).mode)
        assertFalse(fixture.requests.contains("https://fixture/index.json"))
    }

    private fun scenario(body: (Fixture) -> Unit) {
        val root = kotlin.io.path.createTempDirectory("delta-parity").toFile()
        try { body(Fixture(root)) } finally { root.deleteRecursively() }
    }

    private class Fixture(val root: File) {
        val manifestUrl = "https://fixture/manifest.json"
        val fullUrl = "https://fixture/speeds.sqlite"
        val responses = mutableMapOf<String, ByteArray>()
        val requests = mutableListOf<String>()
        val applied = mutableListOf<String>()
        var failApply = false
        var wrongOutput = false
        val bootstrapper = BundleBootstrapper(root, object : HttpFetcher {
            override fun fetch(url: String): ByteArray { requests += url; return responses[url] ?: throw IOException("Unavailable $url") }
            override fun fetchToFile(url: String, destination: File, onProgress: ((Long, Long?) -> Unit)?) { destination.writeBytes(fetch(url)) }
        }, deltaDatabase = object : BundleDeltaDatabase {
            override fun validateSettlementCapability(database: File) = Unit
            override fun applyPatch(database: File, sql: String) {
                if (failApply) throw IOException("synthetic SQL failure")
                applied += sql
                database.writeText(if (wrongOutput) "wrong" else sql.removePrefix("replace:"))
            }
            override fun validate(database: File) { assertTrue(database.length() > 0) }
        })
        fun endpoint(region: String, country: String, available: Boolean = true): V3ManifestEndpoint {
            val url = "https://fixture/$region/manifest.json"
            if (available) {
                responses[url] = manifest("2026-09-01", region).replace("\"region\":\"region\"", "\"region\":\"$region\"")
                    .replace("\"country_code\":\"DEU\"", "\"country_code\":\"$country\"").toByteArray()
                responses["https://fixture/$region/speeds.sqlite"] = region.toByteArray()
            }
            return V3ManifestEndpoint(country.lowercase(), country, region, region, region, url)
        }
        fun install(version: String, contents: String): BundleSyncResult {
            responses[manifestUrl] = manifest(version, contents).toByteArray()
            responses[fullUrl] = contents.toByteArray()
            val result = bootstrapper.syncFromManifestUrl(manifestUrl)
            requests.clear()
            return result
        }
        fun offerDelta(contents: String, compressed: Boolean = false, badHash: Boolean = false, fromVersion: String = "2026-09-01") {
            val raw = "replace:$contents".toByteArray()
            val patch = if (compressed) java.io.ByteArrayOutputStream().also { stream -> DeflaterOutputStream(stream).use { it.write(raw) } }.toByteArray() else raw
            val patchName = if (compressed) "patch.sqlz" else "patch.sql"
            responses["https://fixture/$patchName"] = patch
            val index = """{"format":"youspeed.v3.delta.index","schema_version":1,"count":1,"entries":[{"from_bundle_version":"$fromVersion","to_bundle_version":"2026-09-02","region":"region","delta_manifest_file":"delta.json"}]}"""
            responses["https://fixture/index.json"] = index.toByteArray()
            responses["https://fixture/delta.json"] = """{"format":"youspeed.v3.delta.manifest","schema_version":1,"region":"region","from_bundle_version":"$fromVersion","to_bundle_version":"2026-09-02","patch":${artifact(patchName, patch, if (badHash) "0".repeat(64) else hash(patch))}}""".toByteArray()
            responses[manifestUrl] = manifest("2026-09-02", contents, artifact("index.json", index.toByteArray())).toByteArray()
            responses[fullUrl] = contents.toByteArray()
        }
        private fun manifest(version: String, contents: String, delta: String = "null") = """{"format":"youspeed.v3.bundle.manifest","schema_version":1,"variant":"v3","region":"region","country_code":"DEU","bundle_version":"$version","created_at_utc":"2026-09-02T00:00:00Z","min_app_version":"1.0","db":${artifact("speeds.sqlite", contents.toByteArray())},"delta_index":$delta}"""
        private fun artifact(name: String, bytes: ByteArray, sha: String = hash(bytes)) = """{"file":"$name","bytes":${bytes.size},"sha256":"$sha"}"""
        private fun hash(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    }
}
