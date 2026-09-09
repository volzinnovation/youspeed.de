package de.youspeed.android.alpha

import java.io.File
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class RegionalPackDiscoveryTests {
    private fun shared(path: String): File = listOf(File("../../shared/$path"), File("shared/$path"))
        .first { it.isFile }
    private val scenarios get() = Json.parseToJsonElement(shared("tsr/fixtures/country-discovery-scenarios-v1.json").readText()).jsonObject

    @Test fun sharedRegionalAndBorderScenarios() {
        val catalog = RegionalPackCatalog.decode(shared("RegionalCoverage/catalog-v1.json").readBytes())
        scenarios.getValue("regions").jsonArray.forEach { element ->
            val item = element.jsonObject
            val found = catalog.matches(item.getValue("longitude").jsonPrimitive.double, item.getValue("latitude").jsonPrimitive.double).firstOrNull()?.id
            assertEquals(item.getValue("name").jsonPrimitive.content, item["first"]?.jsonPrimitive?.contentOrNull, found)
        }
        val selection = TrafficSignCountrySelection()
        scenarios.getValue("country_transitions").jsonArray.forEach { element ->
            val item = element.jsonObject
            assertEquals(item.toString(), item["expected"]?.jsonPrimitive?.contentOrNull, selection.update(
                item.getValue("countries").jsonArray.map { it.jsonPrimitive.content }.toSet(),
                item.getValue("timestamp").jsonPrimitive.double, item["override"]?.jsonPrimitive?.contentOrNull,
            ))
        }
    }

    @Test fun holesIslandsEdgesAndRepeatedVertices() {
        val outer = listOf(listOf(0.0,0.0),listOf(4.0,0.0),listOf(4.0,4.0),listOf(4.0,4.0),listOf(0.0,4.0),listOf(0.0,0.0))
        val hole = listOf(listOf(1.0,1.0),listOf(2.0,1.0),listOf(2.0,2.0),listOf(1.0,2.0),listOf(1.0,1.0))
        val island = listOf(listOf(6.0,6.0),listOf(7.0,6.0),listOf(7.0,7.0),listOf(6.0,7.0),listOf(6.0,6.0))
        val region = RegionalPackCatalog.Region("test", "DE", "test", listOf(0.0,0.0,7.0,7.0), listOf(listOf(outer,hole),listOf(island)))
        listOf(Triple(0.0,2.0,true),Triple(1.5,1.5,false),Triple(1.0,1.0,false),Triple(3.0,3.0,true),Triple(5.0,5.0,false),Triple(6.5,6.5,true)).forEach {
            assertEquals(it.third, region.contains(it.first,it.second))
        }
        assertFalse(region.contains(Double.NaN,2.0))
        assertThrows(Exception::class.java) { RegionalPackCatalog.decode("{}".toByteArray()) }
    }

    @Test fun onlyFreshAccurateFiniteFirstFixesAreAccepted() {
        assertTrue(FirstLocationPackPolicy.acceptsFix(49.0,8.0,20.0,100.0,101.0))
        listOf(101.0 to 100.0, -1.0 to 100.0, 20.0 to 50.0, 20.0 to 102.0, Double.NaN to 100.0).forEach {
            assertFalse(FirstLocationPackPolicy.acceptsFix(49.0,8.0,it.first,it.second,101.0))
        }
    }

    @Test fun sharedRegistryDecisionsAndTrustRejections() {
        val bytes = shared("tsr/fixtures/country-pack-registry-v1.json").readBytes()
        val pins = setOf(TrafficSignCountryPackRegistry.sha256(bytes))
        val registry = TrafficSignCountryPackRegistry.decodeTrusted(bytes, pins, allowFixtures = true)
        scenarios.getValue("registry_decisions").jsonArray.forEach { element ->
            val item = element.jsonObject
            val scenarioRegistry = if (item["environment"] != null) registry.copy(
                environment = item.getValue("environment").jsonPrimitive.content,
                packs = registry.packs.mapIndexed { i, pack -> if (i != 0) pack else pack.copy(
                    rollout = item.getValue("rollout").jsonPrimitive.content,
                    calibrated = item.getValue("calibrated").jsonPrimitive.boolean,
                ) },
            ) else registry
            listOf("ios", "android").forEach { platform ->
                val decision = scenarioRegistry.decision(item["country"]?.jsonPrimitive?.contentOrNull, platform,
                    item.getValue("app_version").jsonPrimitive.content, item.getValue("runtime_version_$platform").jsonPrimitive.content, now = 1_788_710_400)
                assertEquals(item.toString(), item.getValue("expected").jsonPrimitive.content, decision.state)
                assertFalse(decision.overrideEligible)
            }
        }
        assertEquals("registry_expired", registry.decision("DE", "android", "1.1", "34", now = registry.expiresAt).state)
        assertThrows(Exception::class.java) { TrafficSignCountryPackRegistry.decodeTrusted(bytes, emptySet()) }
        assertThrows(Exception::class.java) { TrafficSignCountryPackRegistry.decodeTrusted(bytes, pins) }
        assertThrows(Exception::class.java) { TrafficSignCountryPackRegistry.decodeTrusted(bytes, pins, minimumGeneration = 2, allowFixtures = true) }
        assertThrows(Exception::class.java) { TrafficSignCountryPackRegistry.decodeTrusted(bytes + " ".toByteArray(), pins, allowFixtures = true) }
        val production = TrafficSignCountryPackRegistry.decodeBundled(shared("tsr/country-pack-registry-v1.json").readBytes())
        listOf("DE", "FR", "BE", "NL").forEach {
            assertEquals("unavailable", production.decision(it, "android", "1.1", "34", now = 1_788_710_400).state)
        }
    }
}
