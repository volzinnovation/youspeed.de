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

    @Test fun unsafeManifestPathsFailBeforeDownloadsAndPreserveSiblingJournalAndActiveState() = scenario { fixture ->
        val installed = fixture.install("2026-09-01", "old")
        val state = File(fixture.root, "active_bundle.json").readBytes()
        val journal = File(fixture.root, "trip-journal/journal.sqlite").also {
            it.parentFile!!.mkdirs(); it.writeText("private journal sentinel")
        }
        fixture.offerDelta("replacement")
        val valid = fixture.responses.getValue(fixture.manifestUrl).toString(Charsets.UTF_8)
        val attacks = listOf(
            valid.replace("\"file\":\"speeds.sqlite\"", "\"file\":\"../../../trip-journal/journal.sqlite\""),
            valid.replace("\"region\":\"region\"", "\"region\":\"../trip-journal\""),
            valid.replace("\"bundle_version\":\"2026-09-02\"", "\"bundle_version\":\"..\""),
        )
        for (attack in attacks) {
            fixture.requests.clear()
            fixture.responses[fixture.manifestUrl] = attack.toByteArray()
            assertThrows(IOException::class.java) { fixture.bootstrapper.syncFromManifestUrl(fixture.manifestUrl) }
            assertEquals(listOf(fixture.manifestUrl), fixture.requests)
            assertArrayEquals(state, File(fixture.root, "active_bundle.json").readBytes())
            assertEquals("old", File(installed.dbPath).readText())
            assertEquals("private journal sentinel", journal.readText())
        }
        // Old poisoned manifests are ignored by inventory/recovery reads too.
        File(File(installed.dbPath).parentFile, "bundle-manifest.v3.json").writeText(attacks.first())
        assertTrue(fixture.bootstrapper.listDownloadedBundles().isEmpty())
    }

    @Test fun everyLocalArtifactRejectsTraversalAndHierarchicalRegionIdentifiersRemainValid() = scenario { fixture ->
        fixture.install("2026-09-01", "old")
        val manifest = ContractJson.decodeBundleManifest(fixture.responses.getValue(fixture.manifestUrl).toString(Charsets.UTF_8))
        val escaped = manifest.db.copy(file = "../journal.sqlite")
        for (invalid in listOf(manifest.copy(db = escaped), manifest.copy(dbParts = listOf(escaped)),
            manifest.copy(deltaIndex = escaped), manifest.copy(penaltyRules = escaped),
            manifest.copy(coverage = BundleCoverage(BundleCoverageBBox(0.0, 0.0, 1.0, 1.0), escaped)),
            manifest.copy(packedBase = PackedBundleBase(1, escaped)))) {
            assertThrows(IllegalArgumentException::class.java) { invalid.validateLocalPaths() }
        }
        for (name in listOf("", ".", "..", "a/b", "a\\b", "a\u0000b", " a.sqlite")) {
            assertThrows(IllegalArgumentException::class.java) { BundlePathSafety.validateFileName(name) }
        }
        manifest.copy(region = "germany/baden-wuerttemberg").validateLocalPaths()
        val escapedDirectory = File(fixture.root, "bundles/../trip-journal")
        assertThrows(IllegalArgumentException::class.java) {
            BundlePathSafety.descendant(escapedDirectory, File(fixture.root, "bundles"))
        }
        // Filename-safe quote characters must be encoded as data in local state.
        val state = fixture.bootstrapper.activeState()!!.copy(bundleVersion = """v1","db_file_name":"journal.sqlite""")
        val roundTrip = ContractJson.decodeActiveBundleState(ContractJson.encodeActiveBundleState(state))
        assertEquals(state.bundleVersion, roundTrip.bundleVersion)
        assertEquals("speeds.sqlite", roundTrip.dbFileName)
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

    @Test fun changingRegionsAlwaysDownloadsTheirDatabaseEvenWithSharedReleaseDates() = scenario { fixture ->
        for (version in listOf("2026-09-01", "2026-09-02")) {
            val original = fixture.install("2026-09-01", "old region data")
            fixture.offerDelta("new region data")
            fixture.responses[fixture.manifestUrl] = fixture.responses.getValue(fixture.manifestUrl)
                .toString(Charsets.UTF_8).replace("\"region\":\"region\"", "\"region\":\"other-region\"")
                .replace("\"bundle_version\":\"2026-09-02\"", "\"bundle_version\":\"$version\"").toByteArray()
            fixture.responses.remove("https://fixture/index.json")
            val selected = fixture.bootstrapper.syncFromManifestUrl(fixture.manifestUrl)
            assertEquals(BundleSyncMode.FULL_DOWNLOAD, selected.mode)
            assertEquals("new region data", File(selected.dbPath).readText())
            assertEquals("old region data", File(original.dbPath).readText())
            assertFalse(fixture.requests.contains("https://fixture/index.json"))
            assertEquals("other-region", fixture.bootstrapper.activeState()?.region)
        }
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
