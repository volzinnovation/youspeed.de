package de.youspeed.android.alpha

import java.io.Closeable
import java.io.File
import org.junit.Assert.*
import org.junit.Test

class LookupCountrySourceTests {
    private class Reader(val country: String?) : Closeable {
        override fun close() = Unit
    }

    @Test fun crossingCountriesKeepsGpsAndCoarseQueriesOnTheSameReader() {
        val installed = LookupCountrySource("/de.sqlite", "DEU")
        val selected = LookupCountrySource("/fr.sqlite", "FRA")
        val identity = LookupFileIdentity("fixed", 4096, 1, 1)
        val pool = LookupSessionResources { key -> Reader(key.countryCode) }
        fun read(path: String, country: String?) = pool.withReader(
            LookupConnectionKey(path, country, MatcherDebugProfile.M7, identity)
        ) { assertEquals(country, it.country) }
        try {
            read(installed.dbPath, "DEU")
            repeat(100) {
                read(selected.dbPath, "FRA") // GPS route selection.
                read(selected.dbPath, lookupCountryForDatabase(selected.dbPath, selected, installed, null))
            }
            assertEquals(LookupPoolStats(2, 199, 0, 0, 2), pool.stats())
            // A route callback can precede its active-path UI update. Never mix the
            // newly selected country with the still-published previous database.
            read(installed.dbPath, lookupCountryForDatabase(installed.dbPath, selected, installed, null))
            assertEquals(2, pool.stats().opens)
        } finally { pool.close() }
    }

    @Test fun metadataFromAnotherPathCannotOverrideTheDatabaseCountry() {
        val old = LookupCountrySource("/de.sqlite", "DEU")
        assertEquals("FRA", lookupCountryForDatabase("/fr.sqlite", old, old, "FR"))
        assertNull(lookupCountryForDatabase("/unknown.sqlite", old, old, null))
        assertEquals("FRA", lookupCountryForDatabase("/fr.sqlite", LookupCountrySource("/fr.sqlite", "FR"), old, null))
    }

    @Test fun removalScopeDistinguishesActiveRegionSeedAndUnrelatedPaths() {
        val root = File("/test/source-lifecycle")
        val bootstrapper = BundleBootstrapper(root, object : HttpFetcher {
            override fun fetch(url: String): ByteArray = error("No network expected")
            override fun fetchToFile(url: String, destination: File, onProgress: ((Long, Long?) -> Unit)?) = error("No network expected")
        })
        val active = File(root, "bundles/france-paca/v1/FRA.sqlite").path
        assertTrue(bootstrapper.removalIncludesDatabase(active, "france/paca"))
        assertTrue(bootstrapper.removalIncludesDatabase(active))
        assertFalse(bootstrapper.removalIncludesDatabase(active, "germany"))
        assertFalse(bootstrapper.removalIncludesDatabase(File(root, "bundles/seed/seed.sqlite").path))
        assertFalse(bootstrapper.removalIncludesDatabase(File(root, "bundles-other/france-paca/db.sqlite").path))
        assertFalse(bootstrapper.removalIncludesDatabase(""))
    }
}
