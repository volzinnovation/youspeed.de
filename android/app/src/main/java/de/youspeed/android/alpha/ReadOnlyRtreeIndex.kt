package de.youspeed.android.alpha

import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Reads SQLite's immutable two-dimensional float R-tree nodes when Android
 * omits the virtual-table module. Node layout follows SQLite ext/rtree/rtree.c.
 * Never writes shadow tables. Any malformed/oversized search falls back to SQL.
 */
internal class ReadOnlyRtreeIndex(private val load: (Long) -> ByteArray?) {
    private val nodes = object : LinkedHashMap<Long, ByteArray>(64, .75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<Long, ByteArray>?) = size > 256
    }
    fun intersect(minLon: Double, maxLon: Double, minLat: Double, maxLat: Double): List<Long>? = runCatching {
        require(listOf(minLon, maxLon, minLat, maxLat).all(Double::isFinite) && minLon <= maxLon && minLat <= maxLat)
        fun node(id: Long): ByteBuffer {
            val bytes = nodes[id] ?: (load(id) ?: error("missing_rtree_node")).also {
                require(it.size in 4..65536); nodes[id] = it
            }
            return ByteBuffer.wrap(bytes).order(ByteOrder.BIG_ENDIAN)
        }
        val root = node(1)
        val depth = root.getShort(0).toInt() and 65535
        require(depth < 40)
        val result = linkedSetOf<Long>()
        val visited = hashSetOf<Long>()
        fun visit(id: Long, level: Int) {
            require(visited.add(id) && visited.size <= 4096)
            val data = if (id == 1L) root else node(id)
            val count = data.getShort(2).toInt() and 65535
            require(4 + count * 24 <= data.limit())
            repeat(count) { i ->
                val offset = 4 + i * 24
                val entry = data.getLong(offset)
                val left = data.getFloat(offset + 8).toDouble()
                val right = data.getFloat(offset + 12).toDouble()
                val bottom = data.getFloat(offset + 16).toDouble()
                val top = data.getFloat(offset + 20).toDouble()
                require(listOf(left, right, bottom, top).all(Double::isFinite) && left <= right && bottom <= top)
                if (left <= maxLon && right >= minLon && bottom <= maxLat && top >= minLat) {
                    if (level == 0) { result.add(entry); require(result.size <= 10000) }
                    else { require(entry > 0); visit(entry, level - 1) }
                }
            }
        }
        visit(1, depth)
        result.toList()
    }.getOrNull()
}
