package de.youspeed.android.alpha

import kotlinx.serialization.json.*

/** Explicit OSM source signs feed presentation only, never speed rules or boundaries. */
internal object InventoryOsmSpeedEndPresentation {
    fun sign(rawNode: String, wayId: String, direction: Int, localHeading: Double,
             catalog: TrafficSignDisplayCatalog, sourceGeneration: String): InventorySign? = runCatching {
        if (direction !in setOf(-1, 1) || !localHeading.isFinite() || localHeading !in 0.0..<360.0) return null
        if (!PackedAmendmentBaseIdentity.isCanonical(sourceGeneration)) return null
        val snapshotSHA256 = sourceGeneration.substringAfterLast(':').takeIf { it != "absent" } ?: return null
        val node = Json.parseToJsonElement(rawNode).jsonObject
        val id = node["osm_node_id"]?.jsonPrimitive?.content?.takeIf { it.toLongOrNull()?.let { value -> value > 0 } == true }
            ?: return null
        val latitude = node["latitude"]?.jsonPrimitive?.doubleOrNull?.takeIf { it.isFinite() && it in -90.0..90.0 } ?: return null
        val longitude = node["longitude"]?.jsonPrimitive?.doubleOrNull?.takeIf { it.isFinite() && it in -180.0..180.0 } ?: return null
        val memberships = node["memberships"]?.jsonArray.orEmpty().mapNotNull { it as? JsonObject }
        if (memberships.none { member ->
            member["way_id"]?.jsonPrimitive?.content == wayId &&
                member["proof"]?.jsonPrimitive?.content == "explicit_source_way_node_membership" &&
                member["coordinate_verified"]?.jsonPrimitive?.takeUnless { it.isString }?.booleanOrNull == true
        }) return null
        val tags = node["tags"]?.jsonObject ?: return null
        // Membership alone does not establish which traffic direction sees a sign.
        val sourceTag = tags[if (direction == 1) "traffic_sign:forward" else "traffic_sign:backward"]
            ?.jsonPrimitive?.contentOrNull ?: return null
        var country: String? = null
        val numbers = mutableSetOf<Int>()
        for (raw in sourceTag.split(';')) {
            val token = raw.trim()
            if (':' in token) country = token.substringBefore(':')
            val qualified = if (':' in token) token else country?.let { "$it:$token" } ?: continue
            if (!qualified.startsWith("DE:278")) continue
            numbers += InventorySpeedEndCode.number(qualified) ?: return null
        }
        val speed = numbers.singleOrNull() ?: return null
        val code = "DE:278-$speed"
        val artwork = catalog.inventorySpeedEnd(code, speed.toDouble(), "km/h", "parsed_source_value") ?: return null
        InventorySign("osm:$id:$direction:$code", "osm-traffic-sign", id, snapshotSHA256,
            code, "speed_limit_end", speed.toDouble(), "km/h", "parsed_source_value",
            latitude, longitude, 10.0, artwork.imagePath, emptySet(), wayId, direction, "accepted", localHeading)
    }.getOrNull()
}
