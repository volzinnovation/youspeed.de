package de.youspeed.android.alpha

import java.time.Instant
import kotlinx.serialization.json.*

/** Original committed lookup provenance; separate from recognition gates and sign applicability. */
class SignCollectionPhoneRoadMatch private constructor(
    val osmWayId: String, val bundleVersion: String, val bundleDbSha256: String,
    val matchedFixMilliseconds: Long, val travelDirection: String, val matchedWayStable: Boolean,
) {
    companion object {
        private fun milliseconds(at: Instant): Long? = runCatching { at.toEpochMilli() }.getOrNull()
            ?.takeIf { it in 0L..253_402_300_799_999L }
        fun capture(osmWayId: String?, bundleVersion: String?, bundleDbSha256: String?, matchedFixAt: Instant?,
                    travelDirection: String, matchedWayStable: Boolean): SignCollectionPhoneRoadMatch? {
            val id = osmWayId?.toLongOrNull()?.takeIf { it > 0 && it.toString() == osmWayId } ?: return null
            if (bundleVersion == null || bundleVersion.codePointCount(0, bundleVersion.length) !in 1..160 ||
                bundleDbSha256 == null || !Regex("^[a-f0-9]{64}$").matches(bundleDbSha256) ||
                travelDirection !in setOf("forward", "reverse", "unknown")) return null
            val fix = matchedFixAt?.let(::milliseconds) ?: return null
            return SignCollectionPhoneRoadMatch(id.toString(), bundleVersion, bundleDbSha256, fix, travelDirection, matchedWayStable)
        }
    }
    /** Signed age preserves stale/future diagnostics; this does not assert freshness. */
    fun metadata(frameAt: Instant): JsonElement {
        val frame = milliseconds(frameAt) ?: return JsonNull
        val delta = frame - matchedFixMilliseconds
        if (delta !in -86_400_000L..86_400_000L) return JsonNull
        return buildJsonObject {
            put("schema_version", 1); put("source", "on_device_bundle_matcher"); put("osm_way_id", osmWayId)
            put("bundle_version", bundleVersion); put("bundle_db_sha256", bundleDbSha256)
            put("matched_fix_at", Instant.ofEpochMilli(matchedFixMilliseconds).toString()); put("frame_match_delta_ms", delta)
            put("travel_direction", travelDirection); put("matched_way_stable", matchedWayStable)
        }
    }
}
