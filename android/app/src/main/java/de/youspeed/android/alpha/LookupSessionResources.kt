package de.youspeed.android.alpha

import java.io.Closeable
import java.nio.file.Files
import java.nio.file.Paths
import java.nio.file.attribute.BasicFileAttributes
import java.util.concurrent.TimeUnit

/** Identifies an immutable installed bundle, including an atomic replacement at the same path. */
internal data class LookupFileIdentity(
    val fileKey: String?,
    val bytes: Long,
    val modifiedNs: Long,
    val createdNs: Long,
) {
    companion object {
        fun read(path: String): LookupFileIdentity {
            val attributes = Files.readAttributes(Paths.get(path), BasicFileAttributes::class.java)
            return LookupFileIdentity(attributes.fileKey()?.toString(), attributes.size(),
                attributes.lastModifiedTime().to(TimeUnit.NANOSECONDS),
                attributes.creationTime().to(TimeUnit.NANOSECONDS))
        }
    }
}

internal data class LookupConnectionKey(
    val dbPath: String,
    val countryCode: String?,
    val matcherProfile: MatcherDebugProfile,
    val fileIdentity: LookupFileIdentity = LookupFileIdentity.read(dbPath),
)

internal data class LookupPoolStats(
    val opens: Long,
    val hits: Long,
    val evictions: Long,
    val invalidations: Long,
    val liveConnections: Int,
)

/**
 * Owns all primary, bundle-probe and coarse-city readers for one controller.
 * The lock covers use as well as eviction/close: callers never borrow an escaping reader.
 */
internal class LookupSessionResources<T : Closeable>(
    private val capacity: Int = 4,
    private val open: (LookupConnectionKey) -> T,
) : Closeable {
    private val lock = Any()
    private val readers = LinkedHashMap<LookupConnectionKey, T>(capacity, 0.75f, true)
    private var closed = false
    private var opens = 0L
    private var hits = 0L
    private var evictions = 0L
    private var invalidations = 0L

    init { require(capacity > 0) }

    fun <R> withReader(key: LookupConnectionKey, block: (T) -> R): R = synchronized(lock) {
        check(!closed) { "Lookup session is closed" }
        // Do not retain an old inode, country or matcher for a replaced bundle.
        val obsolete = readers.keys.filter { it.dbPath == key.dbPath && it != key }
        obsolete.forEach { old -> readers.remove(old)?.close(); invalidations++ }
        val reader = readers[key]?.also { hits++ } ?: run {
            // Evict before opening so even the transient number of handles is bounded.
            if (readers.size >= capacity) {
                val oldest = readers.entries.iterator()
                val entry = oldest.next()
                oldest.remove()
                entry.value.close()
                evictions++
            }
            open(key).also { readers[key] = it; opens++ }
        }
        block(reader)
    }

    /** Also called after a completed sync: content may have changed without a path change. */
    fun invalidateAll(): Unit = synchronized(lock) {
        val old = readers.values.toList()
        readers.clear()
        invalidations += old.size
        var failure: Exception? = null
        old.forEach { reader ->
            try { reader.close() } catch (error: Exception) {
                if (failure == null) failure = error else failure?.addSuppressed(error)
            }
        }
        failure?.let { throw it }
    }

    fun stats(): LookupPoolStats = synchronized(lock) {
        LookupPoolStats(opens, hits, evictions, invalidations, readers.size)
    }

    override fun close(): Unit = synchronized(lock) {
        closed = true
        invalidateAll()
    }
}

internal data class GeometryCacheStats(val hits: Long, val decodes: Long, val evictions: Long,
    val entries: Int, val retainedPoints: Int)

/** Bounded by both entries and vertices; one very large geometry cannot occupy the cache. */
internal class DecodedGeometryCache<K, P>(
    private val maxEntries: Int,
    private val maxPoints: Int,
) {
    private val entries = LinkedHashMap<K, List<P>>(16, 0.75f, true)
    private var points = 0
    private var hits = 0L
    private var decodes = 0L
    private var evictions = 0L

    init { require(maxEntries > 0 && maxPoints > 0) }

    fun getOrDecode(key: K, decode: () -> List<P>): List<P> {
        entries[key]?.let { hits++; return it }
        val decoded = decode()
        decodes++
        if (decoded.size > maxPoints) return decoded
        while (entries.size >= maxEntries || points + decoded.size > maxPoints) {
            val oldest = entries.entries.iterator()
            val entry = oldest.next()
            points -= entry.value.size
            oldest.remove()
            evictions++
        }
        entries[key] = decoded
        points += decoded.size
        return decoded
    }

    fun stats() = GeometryCacheStats(hits, decodes, evictions, entries.size, points)

    fun clear() { entries.clear(); points = 0 }
}
