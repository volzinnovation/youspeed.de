package de.youspeed.android.alpha

import java.io.File
import java.util.Locale

/** Complete immutable generation identity for reviewed amendments. Display
 * versions are shared by overlapping regional bundles and cannot bind edits. */
internal object PackedAmendmentBaseIdentity {
    private val pattern=Regex("ysp-base-v1:[0-9a-f]{64}:[0-9a-f]{64}:([0-9a-f]{64}|absent)")
    fun isCanonical(value:String?)=value?.matches(pattern)==true
    private fun installedSHA(artifact:BundleArtifact):String {
        val compression=artifact.compression?.trim()?.lowercase(Locale.ROOT).orEmpty()
        val sha=if(compression in setOf("","none"))artifact.sha256 else requireNotNull(artifact.uncompressedSha256)
        require(sha.matches(Regex("[0-9a-fA-F]{64}")))
        return sha.lowercase(Locale.ROOT)
    }
    fun fromManifest(manifest:V3BundleManifest):String {
        manifest.validateLaunchContract()
        require(manifest.format=="youspeed.v4.bundle.manifest")
        val base=requireNotNull(manifest.packedBase)
        return "ysp-base-v1:${installedSHA(manifest.db)}:${installedSHA(base.roads)}:${base.nodes?.let(::installedSHA)?:"absent"}"
    }
    fun forDatabase(path:String,db:RuntimeSqlDatabase):String? {
      return try {
        val file=File(path).canonicalFile
        val manifestFile=File(requireNotNull(file.parentFile),"bundle-manifest.v3.json")
        if(!manifestFile.isFile||manifestFile.length() !in 1..1024L*1024)return null
        val manifest=ContractJson.decodeBundleManifest(manifestFile.readText())
        val identity=fromManifest(manifest)
        if(manifest.db.file!=file.name)return null
        fun metadata(key:String)=db.rawQuery("SELECT value FROM metadata WHERE key=?",arrayOf(key)).use {
            if(it.moveToFirst())it.getString(0) else null
        }
        val base=requireNotNull(manifest.packedBase)
        if(metadata("packed_generation")!=manifest.bundleVersion||metadata("packed_geometry_version")!="1"||
            metadata("packed_geometry_file")!=base.roads.file||
            !metadata("packed_geometry_sha256").equals(installedSHA(base.roads),true))return null
        for(artifact in listOfNotNull(manifest.db,base.roads,base.nodes)) {
            val actual=RuntimeMapDatabase.companionFile(requireNotNull(file.parentFile),artifact.file)
            val compression=artifact.compression?.trim()?.lowercase(Locale.ROOT).orEmpty()
            val bytes=if(compression in setOf("","none"))artifact.bytes else requireNotNull(artifact.uncompressedBytes)
            if(actual.length()!=bytes)return null
        }
        identity
      } catch(_:Exception) {null}
    }
}
