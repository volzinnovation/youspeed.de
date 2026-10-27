package de.youspeed.android.alpha

import java.io.ByteArrayOutputStream
import java.io.File
import java.security.MessageDigest
import java.util.zip.GZIPOutputStream
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class PackedBundleContractTests {
    @get:Rule val temporary=TemporaryFolder()
    @Test fun v4CapabilitiesRequireCompatibleAppAndCannotApplyLegacySQLDeltas() {
        val f=Fixture(temporary.newFolder());val parsed=ContractJson.decodeBundleManifest(f.manifest())
        parsed.validateLaunchContract("1.6")
        assertEquals("roads.yspg",parsed.packedBase?.roads?.file)
        assertThrows(IllegalArgumentException::class.java){parsed.validateLaunchContract("1.5")}
        assertThrows(IllegalArgumentException::class.java){parsed.copy(packedBase=parsed.packedBase?.copy(version=2)).validateLaunchContract("1.6")}
        assertThrows(IllegalArgumentException::class.java){parsed.copy(format="youspeed.v3.bundle.manifest",variant="v3").validateLaunchContract("1.6")}
        assertThrows(IllegalArgumentException::class.java){parsed.copy(deltaIndex=parsed.db).validateLaunchContract("1.6")}
        assertThrows(IllegalArgumentException::class.java){parsed.copy(dbParts=listOf(parsed.db)).validateLaunchContract("1.6")}
        val base=requireNotNull(parsed.packedBase)
        assertThrows(IllegalArgumentException::class.java){parsed.copy(packedBase=base.copy(
            roads=base.roads.copy(uncompressedSha256=null))).validateLaunchContract("1.6")}
    }
    @Test fun amendmentBaseIdentitySeparatesOverlappingSourcesAtTheSameDisplayVersion() {
        val f=Fixture(temporary.newFolder())
        val first=ContractJson.decodeBundleManifest(f.manifest()).copy(region="baden-wuerttemberg",bundleVersion="2026-10-27-packed-v1")
        val identity=PackedAmendmentBaseIdentity.fromManifest(first)
        assertTrue(PackedAmendmentBaseIdentity.isCanonical(identity))
        assertFalse(PackedAmendmentBaseIdentity.isCanonical(first.bundleVersion))
        val overlapping=first.copy(region="karlsruhe-regbez",db=first.db.copy(sha256="f".repeat(64)))
        assertNotEquals(identity,PackedAmendmentBaseIdentity.fromManifest(overlapping))
        val base=requireNotNull(first.packedBase);val nodes=requireNotNull(base.nodes)
        assertNotEquals(identity,PackedAmendmentBaseIdentity.fromManifest(first.copy(packedBase=base.copy(
            nodes=nodes.copy(uncompressedSha256="e".repeat(64))))))
        assertEquals(identity,PackedAmendmentBaseIdentity.fromManifest(first.copy(packedBase=base.copy(
            roads=base.roads.copy(sha256="d".repeat(64)))))) // gzip wire identity is not installed identity.
    }
    @Test fun verifiedCatalogSelectsImmutableManifestAndInflatesBothCompanions() {
        val f=Fixture(temporary.newFolder());f.publishCatalog()
        val result=f.manager.syncFromManifestUrl(f.legacy)
        assertEquals(BundleSyncMode.FULL_DOWNLOAD,result.mode)
        assertEquals(f.immutable,f.manager.activeState()?.manifestUrl)
        val directory=File(result.dbPath).parentFile
        assertArrayEquals(f.roads,File(directory,"roads.yspg").readBytes())
        assertArrayEquals(f.nodes,File(directory,"nodes.yspn").readBytes())
        assertEquals(f.context.size.toLong()+f.roads.size+f.nodes.size,f.manager.listDownloadedBundles().single().dbBytes)
        assertFalse(f.requested.contains(f.legacy))
        assertEquals(BundleSyncMode.UP_TO_DATE,f.manager.syncFromManifestUrl(f.legacy).mode)
    }
    @Test fun changedNodesAtSameContextAndVersionInstallANewImmutableGeneration() {
        val f=Fixture(temporary.newFolder());f.publishDirect()
        val first=f.manager.syncFromManifestUrl(f.immutable);val oldNodes=f.nodes.clone()
        f.nodes="updated source nodes with unchanged context".toByteArray();f.publishDirect()
        val second=f.manager.syncFromManifestUrl(f.immutable)
        assertEquals(BundleSyncMode.FULL_DOWNLOAD,second.mode)
        assertNotEquals(first.dbPath,second.dbPath)
        assertArrayEquals(oldNodes,File(File(first.dbPath).parentFile,"nodes.yspn").readBytes())
        assertArrayEquals(f.nodes,File(File(second.dbPath).parentFile,"nodes.yspn").readBytes())
        assertEquals(second.dbPath,f.manager.activeState()?.dbPath)
    }
    @Test fun missingCompanionDisqualifiesOfflineActivationUntilItIsRestored() {
        val f=Fixture(temporary.newFolder());f.publishDirect()
        val first=f.manager.syncFromManifestUrl(f.immutable)
        assertTrue(File(File(first.dbPath).parentFile,"nodes.yspn").delete())
        assertNull(f.manager.activeState())
        assertTrue(f.manager.listDownloadedBundles().isEmpty())
        assertEquals(BundleSyncMode.FULL_DOWNLOAD,f.manager.syncFromManifestUrl(f.immutable).mode)
        assertNotNull(f.manager.activeState())
    }
    @Test fun failedSameVersionReplacementPreservesOldGenerationAndCorrections() {
        val f=Fixture(temporary.newFolder());f.publishDirect()
        val first=f.manager.syncFromManifestUrl(f.immutable);val oldRoads=f.roads.clone()
        val correction=File(f.root,"map_data_amendments.sqlite").apply{writeText("unrelated user correction history")}
        f.roads="new packed geometry".toByteArray();f.nodes="new source nodes".toByteArray();f.publishDirect()
        f.responses[f.nodesUrl]=byteArrayOf(1,2,3)
        assertThrows(IllegalArgumentException::class.java){f.manager.syncFromManifestUrl(f.immutable)}
        assertEquals(first.dbPath,f.manager.activeState()?.dbPath)
        assertArrayEquals(oldRoads,File(File(first.dbPath).parentFile,"roads.yspg").readBytes())
        assertEquals("unrelated user correction history",correction.readText())
    }
    @Test fun catalog404FallsBackButServerFailureAndManifestHashMismatchDoNot() {
        val f=Fixture(temporary.newFolder())
        f.responses[f.legacy]=f.legacyManifest().toByteArray()
        assertEquals("v3",f.manager.fetchManifest(f.legacy).variant)
        val server=Fixture(temporary.newFolder());server.failures[PackedBundleCatalogResolver.DEFAULT_URL]=500
        assertThrows(HttpStatusException::class.java){server.manager.fetchManifest(server.legacy)}
        val bad=Fixture(temporary.newFolder());bad.publishCatalog();bad.responses[bad.immutable]=bad.manifest().replace("fixture-1","fixture-2").toByteArray()
        assertThrows(IllegalArgumentException::class.java){bad.manager.syncFromManifestUrl(bad.legacy)}
        assertNull(bad.manager.activeState())
    }

    private class Fixture(val root:File) {
        val legacy="https://github.com/volzinnovation/youspeed.de/releases/download/fixture/fixture_manifest.json"
        val immutable="https://github.com/volzinnovation/youspeed.de/releases/download/fixture-packed-v1-2026-10-27/fixture_manifest.json"
        val contextUrl="https://packed.test/context";val roadsUrl="https://packed.test/roads.gz";val nodesUrl="https://packed.test/nodes.gz"
        val context="YSPCTX1\u0000test page image".toByteArray()
        var roads="original packed geometry".toByteArray();var nodes="original source nodes".toByteArray()
        val responses=mutableMapOf<String,ByteArray>();val failures=mutableMapOf<String,Int>();val requested=mutableListOf<String>()
        val fetcher=object:HttpFetcher {
            override fun fetch(url:String):ByteArray {requested+=url;failures[url]?.let{throw HttpStatusException(it,url,"")};return responses[url]?:throw HttpStatusException(404,url,"")}
            override fun fetchToFile(url:String,destination:File,onProgress:((Long,Long?)->Unit)?) {val bytes=fetch(url);destination.writeBytes(bytes);onProgress?.invoke(bytes.size.toLong(),bytes.size.toLong())}
        }
        val manager=BundleBootstrapper(root,fetcher,deltaDatabase=ContractTestDatabase)
        fun artifact(name:String,raw:ByteArray,url:String,compressed:Boolean=false):String {
            val transport=if(compressed)gzip(raw) else raw
            val extra=if(compressed)",\"compression\":\"gzip\",\"uncompressed_bytes\":${raw.size},\"uncompressed_sha256\":\"${sha(raw)}\"" else ""
            return "{\"file\":\"$name\",\"bytes\":${transport.size},\"sha256\":\"${sha(transport)}\",\"url\":\"$url\"$extra}"
        }
        fun manifest()="""{"format":"youspeed.v4.bundle.manifest","schema_version":1,"variant":"v4","region":"fixture","country_code":"DEU","bundle_version":"fixture-1","created_at_utc":"2026-10-27T00:00:00Z","min_app_version":"1.6","db":${artifact("context.yspc",context,contextUrl)},"packed_base":{"version":1,"roads":${artifact("roads.yspg",roads,roadsUrl,true)},"nodes":${artifact("nodes.yspn",nodes,nodesUrl,true)}}}"""
        fun legacyManifest()="""{"format":"youspeed.v3.bundle.manifest","schema_version":1,"variant":"v3","region":"fixture","country_code":"DEU","bundle_version":"legacy-1","created_at_utc":"2026-10-27T00:00:00Z","min_app_version":"1.0","db":${artifact("map.sqlite",context,contextUrl)}}"""
        fun publishDirect(){responses[immutable]=manifest().toByteArray();responses[contextUrl]=context;responses[roadsUrl]=gzip(roads);responses[nodesUrl]=gzip(nodes)}
        fun publishCatalog(){publishDirect();val bytes=requireNotNull(responses[immutable]);responses[PackedBundleCatalogResolver.DEFAULT_URL]="""{"format":"youspeed.v4.bundle.catalog","schema_version":1,"variant":"v4","bundles":[{"region":"fixture","bundle_version":"fixture-1","release_tag":"fixture-packed-v1-2026-10-27","manifest":${artifact("fixture_manifest.json",bytes,immutable)}}]}""".toByteArray()}
    }
    companion object {
        fun sha(bytes:ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it)}
        fun gzip(bytes:ByteArray):ByteArray {val out=ByteArrayOutputStream();GZIPOutputStream(out).use{it.write(bytes)};return out.toByteArray()}
    }
}
