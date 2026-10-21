package de.youspeed.android.alpha

import java.io.File
import java.time.Instant
import org.json.JSONObject

/** Make synthetic installed maps discoverable by the same GPS router as release maps. */
internal fun writeCoverageFixtureManifest(database: File, region: String, version: String,
    minLon: Double, minLat: Double, maxLon: Double, maxLat: Double) {
    val manifest = JSONObject()
        .put("format", "youspeed.v3.bundle.manifest").put("schema_version", 1).put("variant", "v3")
        .put("region", region).put("country_code", "DEU").put("bundle_version", version)
        .put("created_at_utc", Instant.now().toString()).put("min_app_version", "1.0.0")
        .put("db", JSONObject().put("file", database.name).put("bytes", database.length())
            .put("sha256", PanoramaxQueueStore.sha256(database)))
        .put("coverage", JSONObject().put("bbox", JSONObject()
            .put("min_lon", minLon).put("min_lat", minLat).put("max_lon", maxLon).put("max_lat", maxLat)))
    File(database.parentFile, "bundle-manifest.v3.json").writeText(manifest.toString())
}
