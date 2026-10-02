package de.youspeed.android.alpha

import java.io.Closeable
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test

class LookupSessionResourcesTests {
    private class Reader : Closeable {
        var closes = 0
        override fun close() { closes++ }
    }

    private fun key(path: String = "a", revision: Long = 1) = LookupConnectionKey(path, "DE",
        MatcherDebugProfile.M7, LookupFileIdentity("inode-$revision", 4096, revision, revision))

    @Test fun repeatedPrimaryProbeAndCityUsesShareReaders() {
        val pool = LookupSessionResources { Reader() }
        repeat(100) {
            // Two overlap probes, followed by selected-road and coarse-city lookups.
            pool.withReader(key("a")) { assertEquals(0, it.closes) }
            pool.withReader(key("b")) { assertEquals(0, it.closes) }
            pool.withReader(key("a")) { assertEquals(0, it.closes) }
            pool.withReader(key("a")) { assertEquals(0, it.closes) }
        }
        assertEquals(LookupPoolStats(2, 398, 0, 0, 2), pool.stats())
        pool.close()
        assertEquals(0, pool.stats().liveConnections)
    }

    @Test fun leastRecentlyUsedReaderIsClosedBeforeCapacityIsExceeded() {
        val pool = LookupSessionResources(capacity = 2) { Reader() }
        val a = pool.withReader(key("a")) { it }
        val b = pool.withReader(key("b")) { it }
        assertSame(a, pool.withReader(key("a")) { it })
        pool.withReader(key("c")) { }
        assertEquals(0, a.closes)
        assertEquals(1, b.closes)
        assertEquals(LookupPoolStats(3, 1, 1, 0, 2), pool.stats())
        pool.close()
        pool.close()
        assertEquals(1, a.closes)
        assertEquals(1, b.closes)
    }

    @Test fun bundleReplacementCountryProfileAndExplicitSyncInvalidateOldReader() {
        val pool = LookupSessionResources { Reader() }
        var previous = pool.withReader(key()) { it }
        val keys = listOf(key(revision = 2), key(revision = 2).copy(countryCode = "FR"),
            key(revision = 2).copy(countryCode = "FR", matcherProfile = MatcherDebugProfile.M12))
        for (next in keys) {
            val current = pool.withReader(next) { it }
            assertEquals(1, previous.closes)
            assertNotSame(previous, current)
            previous = current
        }
        pool.invalidateAll()
        assertEquals(1, previous.closes)
        assertNotSame(previous, pool.withReader(keys.last()) { it })
        assertEquals(LookupPoolStats(5, 0, 0, 4, 1), pool.stats())
        pool.close()
    }

    @Test fun samePathAtomicReplacementIsDetectedEvenWithSameSizeAndModificationTime() {
        val directory = Files.createTempDirectory("lookup-identity")
        val active = directory.resolve("bundle.sqlite")
        val incoming = directory.resolve("new.sqlite")
        try {
            Files.write(active, byteArrayOf(1, 2, 3))
            val before = LookupFileIdentity.read(active.toString())
            Files.write(incoming, byteArrayOf(3, 2, 1))
            Files.setLastModifiedTime(incoming, Files.getLastModifiedTime(active))
            Files.move(incoming, active, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
            val after = LookupFileIdentity.read(active.toString())
            assertEquals(before.bytes, after.bytes)
            assertEquals(before.modifiedNs, after.modifiedNs)
            assertNotEquals(before, after)
        } finally {
            Files.deleteIfExists(incoming)
            Files.deleteIfExists(active)
            Files.deleteIfExists(directory)
        }
    }

    @Test fun disposalWaitsForInFlightUseAndPreventsLateReopening() {
        val pool = LookupSessionResources { Reader() }
        val executor = Executors.newFixedThreadPool(2)
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val closeStarted = CountDownLatch(1)
        try {
            val use = executor.submit<Reader> {
                pool.withReader(key()) { reader ->
                    entered.countDown()
                    assertTrue(release.await(5, TimeUnit.SECONDS))
                    assertEquals(0, reader.closes)
                    reader
                }
            }
            assertTrue(entered.await(5, TimeUnit.SECONDS))
            val close = executor.submit {
                closeStarted.countDown()
                pool.close()
            }
            assertTrue(closeStarted.await(5, TimeUnit.SECONDS))
            assertFalse(close.isDone)
            release.countDown()
            close.get(5, TimeUnit.SECONDS)
            assertEquals(1, use.get(5, TimeUnit.SECONDS).closes)
            assertThrows(IllegalStateException::class.java) { pool.withReader(key()) { } }
            assertEquals(1, pool.stats().opens)
        } finally {
            release.countDown()
            executor.shutdownNow()
        }
    }

    @Test fun geometryCacheBoundsVerticesAndEntriesAndBypassesOversizedWays() {
        val cache = DecodedGeometryCache<String, Int>(maxEntries = 2, maxPoints = 4)
        val first = cache.getOrDecode("a") { listOf(1, 2) }
        cache.getOrDecode("b") { listOf(3, 4) }
        assertSame(first, cache.getOrDecode("a") { error("Must not decode a warm way") })
        cache.getOrDecode("c") { listOf(5, 6, 7) }
        assertEquals(2, cache.stats().evictions)
        assertEquals(1, cache.stats().entries)
        assertEquals(3, cache.stats().retainedPoints)
        repeat(2) { cache.getOrDecode("huge") { List(5) { it } } }
        assertEquals(GeometryCacheStats(1, 5, 2, 1, 3), cache.stats())
        cache.getOrDecode("empty") { emptyList() }
        cache.getOrDecode("other-empty") { emptyList() }
        assertEquals(2, cache.stats().entries)
        assertEquals(0, cache.stats().retainedPoints)
        cache.clear()
        assertEquals(0, cache.stats().entries)
    }
}
