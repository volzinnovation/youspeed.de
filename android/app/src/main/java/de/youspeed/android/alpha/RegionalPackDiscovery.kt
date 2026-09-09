package de.youspeed.android.alpha

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.math.abs

/** Buffered PBF coverage is a download candidate, not an administrative border. */
data class RegionalPackCatalog(val regions: List<Region>) {
    data class Region(
        val id: String, val country: String, val region: String,
        val bbox: List<Double>, val polygons: List<List<List<List<Double>>>>,
    ) {
        val area: Double get() = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])

        fun contains(longitude: Double, latitude: Double): Boolean {
            if (!longitude.isFinite() || !latitude.isFinite() || longitude !in -180.0..180.0 ||
                latitude !in -90.0..90.0 || longitude !in bbox[0]..bbox[2] || latitude !in bbox[1]..bbox[3]) return false
            return polygons.any { polygon ->
                inRing(longitude, latitude, polygon.first()) &&
                    polygon.drop(1).none { inRing(longitude, latitude, it) }
            }
        }

        private fun inRing(x: Double, y: Double, ring: List<List<Double>>): Boolean {
            var inside = false
            for (i in 0 until ring.size - 1) {
                val a = ring[i]; val b = ring[i + 1]
                val dx = b[0] - a[0]; val dy = b[1] - a[1]
                if (dx == 0.0 && dy == 0.0) continue
                val cross = (x - a[0]) * dy - (y - a[1]) * dx
                if (abs(cross) <= 1e-12 && x in minOf(a[0], b[0])..maxOf(a[0], b[0]) &&
                    y in minOf(a[1], b[1])..maxOf(a[1], b[1])) return true
                if ((a[1] > y) != (b[1] > y) && x < dx * (y - a[1]) / dy + a[0]) inside = !inside
            }
            return inside
        }
    }

    fun matches(longitude: Double, latitude: Double): List<Region> =
        regions.filter { it.contains(longitude, latitude) }.sortedWith(compareBy<Region> { it.area }.thenBy { it.id })

    companion object {
        fun decode(bytes: ByteArray): RegionalPackCatalog {
            require(bytes.size <= 8_000_000)
            val root = Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
            require(root.getValue("schema_version").jsonPrimitive.int == 1)
            require(root.getValue("boundary_kind").jsonPrimitive.content == "buffered_extract_coverage")
            val regions = root.getValue("regions").jsonArray.map { value ->
                val item = value.jsonObject
                Region(
                    item.getValue("id").jsonPrimitive.content,
                    item.getValue("country").jsonPrimitive.content,
                    item.getValue("region").jsonPrimitive.content,
                    item.getValue("bbox").jsonArray.map { it.jsonPrimitive.double },
                    item.getValue("polygons").jsonArray.map { polygon -> polygon.jsonArray.map { ring ->
                        ring.jsonArray.map { point -> point.jsonArray.map { it.jsonPrimitive.double } }
                    } },
                ).also { region ->
                    require(Regex("[A-Z]{2}").matches(region.country))
                    require(region.bbox.size == 4 && region.bbox.all { it.isFinite() })
                    require(region.bbox[0] < region.bbox[2] && region.bbox[1] < region.bbox[3])
                    require(region.polygons.isNotEmpty())
                    region.polygons.forEach { polygon ->
                        require(polygon.isNotEmpty())
                        polygon.forEach { ring ->
                            require(ring.size >= 4 && ring.first() == ring.last())
                            ring.forEach { point ->
                                require(point.size == 2 && point.all { it.isFinite() })
                                require(point[0] in -180.0..180.0 && point[1] in -90.0..90.0)
                                require(point[0] in region.bbox[0]..region.bbox[2] && point[1] in region.bbox[1]..region.bbox[3])
                            }
                        }
                    }
                }
            }
            require(regions.size in 1..1000 && regions.map { it.id }.toSet().size == regions.size)
            return RegionalPackCatalog(regions)
        }
    }
}

class TrafficSignCountrySelection {
    var activeCountry: String? = null
        private set
    private var pendingCountry: String? = null
    private var pendingSince = 0.0
    private var pendingFixes = 0
    private var lastTimestamp = Double.NEGATIVE_INFINITY

    fun suspendPendingTransition() {
        pendingCountry = null
        pendingFixes = 0
    }

    fun update(countries: Set<String>, timestamp: Double, override: String? = null): String? {
        if (!timestamp.isFinite() || timestamp <= lastTimestamp) return null
        lastTimestamp = timestamp
        if (override != null) {
            if (!Regex("[A-Z]{2}").matches(override)) return null
            activeCountry = override
            pendingCountry = null
            return override
        }
        val country = countries.singleOrNull()
        if (country == null || !Regex("[A-Z]{2}").matches(country)) {
            pendingCountry = null
            return null
        }
        if (activeCountry == null || activeCountry == country) {
            activeCountry = country
            pendingCountry = null
            return country
        }
        if (pendingCountry != country) {
            pendingCountry = country
            pendingSince = timestamp
            pendingFixes = 1
        } else pendingFixes++
        if (pendingFixes >= 3 && timestamp - pendingSince >= 15) {
            activeCountry = country
            pendingCountry = null
            return country
        }
        return null
    }
}

object FirstLocationPackPolicy {
    fun acceptsFix(latitude: Double, longitude: Double, accuracy: Double, timestamp: Double, now: Double): Boolean =
        listOf(latitude, longitude, accuracy, timestamp, now).all { it.isFinite() } &&
            latitude in -90.0..90.0 && longitude in -180.0..180.0 && accuracy in 0.0..100.0 && now - timestamp in 0.0..30.0
}
