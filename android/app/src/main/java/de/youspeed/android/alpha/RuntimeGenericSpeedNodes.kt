package de.youspeed.android.alpha

import java.io.Closeable
import java.io.File
import org.json.JSONArray
import org.json.JSONObject

/** Source inventory for querying/editing. A way membership or nearby coordinate
 * never grants a node legal direction, passage, or speed-reference authority. */
internal class RuntimeGenericSpeedNodes private constructor(path: String) : Closeable {
    private var handle = RuntimePackedNative.nodesOpen(path)
    @Synchronized fun sourceJSON(decimalNodeId:String):String? {
        check(handle != 0L) { "Generic speed nodes are closed" }
        return RuntimePackedNative.nodeJson(handle, decimalNodeId)?.toString(Charsets.UTF_8)
    }
    @Synchronized fun node(decimalNodeId: String): JSONObject? = sourceJSON(decimalNodeId)?.let(::JSONObject)
    @Synchronized fun nearby(latitude: Double, longitude: Double, radiusM: Double): List<JSONObject> {
        check(handle != 0L) { "Generic speed nodes are closed" }
        val raw = RuntimePackedNative.nodesQueryJson(handle, latitude, longitude, radiusM)
            ?: return emptyList()
        val rows = JSONArray(raw.toString(Charsets.UTF_8))
        return (0 until rows.length()).map { rows.getJSONObject(it) }
    }
    @Synchronized fun diagnostics(): JSONObject? = if (handle == 0L) null else
        RuntimePackedNative.nodesStats(handle)?.toString(Charsets.UTF_8)?.let(::JSONObject)
    @Synchronized override fun close() {
        if (handle != 0L) { RuntimePackedNative.nodesClose(handle); handle = 0 }
    }

    companion object {
        fun openForDatabase(dbPath: String): RuntimeGenericSpeedNodes? {
            val directory = File(dbPath).absoluteFile.parentFile ?: return null
            val manifestFile = File(directory, "bundle-manifest.v3.json")
            if (!manifestFile.isFile) return null
            val manifest = ContractJson.decodeBundleManifest(manifestFile.readText())
            val artifact = manifest.packedBase?.nodes ?: return null
            val file = RuntimeMapDatabase.companionFile(directory, artifact.file)
            val compression = artifact.compression?.trim()?.lowercase().orEmpty()
            val expected = if (compression.isEmpty() || compression == "none") artifact.sha256
                else requireNotNull(artifact.uncompressedSha256) { "Node installed checksum is missing" }
            RuntimeMapDatabase.verifyGeometry(file, expected)
            return RuntimeGenericSpeedNodes(file.path)
        }
    }
}
