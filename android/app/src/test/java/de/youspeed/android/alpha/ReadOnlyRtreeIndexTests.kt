package de.youspeed.android.alpha

import java.util.Base64
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class ReadOnlyRtreeIndexTests {
    @Test fun matchesSQLiteAcrossMultiLevelTreeAndOverlappingWindows() {
        val fixture = Json.parseToJsonElement(javaClass.getResource("/rtree-sqlite-reference.json")!!.readText()).jsonObject
        val nodes = fixture.getValue("nodes").jsonObject.mapKeys { it.key.toLong() }.mapValues { Base64.getDecoder().decode(it.value.jsonPrimitive.content) }
        val index = ReadOnlyRtreeIndex { nodes[it] }
        for (item in fixture.getValue("cases").jsonArray) {
            val b = item.jsonObject.getValue("bounds").jsonArray.map { it.jsonPrimitive.double }
            val expected = item.jsonObject.getValue("ids").jsonArray.map { it.jsonPrimitive.long }
            assertEquals("SQLite overlap $b", expected, index.intersect(b[0], b[1], b[2], b[3])?.sorted())
        }
    }
    @Test fun corruptMissingAndUnsupportedNodesRequireSQLFallback() {
        for (bytes in listOf(null, byteArrayOf(0, 0, 0), byteArrayOf(0, 0, 0, 1), byteArrayOf(0, 40, 0, 0))) {
            assertNull(ReadOnlyRtreeIndex { bytes }.intersect(0.0, 1.0, 0.0, 1.0))
        }
        assertNull(ReadOnlyRtreeIndex { byteArrayOf(0, 0, 0, 0) }.intersect(Double.NaN, 1.0, 0.0, 1.0))
    }
}
