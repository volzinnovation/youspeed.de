package de.youspeed.android.alpha

import java.io.File
import java.time.Instant
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class SignCollectionInterestTests {
    private val root = File("../../shared/tsr/collection-contract-v1")
    private val schema = SignCollectionJson.parse(File(root, "crop-interest-v1.schema.json").readText()).jsonObject
    private val bytes = File(root, "fixtures/crop-interest-v1.json").readBytes()
    private val plan = SignCollectionInterestPlan(bytes, schema)

    @Test fun productionMaximumSelectsEveryRequestedEncounter() {
        val maximum = SignCollectionInterestPlan(File(root, "fixtures/crop-interest-daily-maximum-v1.json").readBytes(), schema)
        assertEquals("daily-maximum-v1", maximum.document.getValue("algorithm_version").jsonPrimitive.content)
        assertTrue(maximum.rules.isNotEmpty())
        assertTrue(maximum.rules.values.all { it.numerator == it.denominator })
        assertTrue(maximum.rules.keys.none { SignCollectionInterestPlan.isAlways(it.label) })
    }

    @Test fun httpsCacheExactMatchingExpiryAndRevisionFloor() {
        var now = plan.generated.plusSeconds(60)
        var uptime = 1000000000L
        val directory = java.nio.file.Files.createTempDirectory("interest-test").toFile()
        try {
            val path = File(directory, "plan.json")
            val store = SignCollectionInterestStore(path, schema, { now }, { uptime })
            val identity = plan.rules.keys.first()
            val observation = "00000000-0000-4000-8000-000000000001"
            assertEquals("no_valid_plan", store.select(identity, observation).decision)
            for (label in listOf("bad", "bad:round", "bad:future")) {
                assertTrue(store.select(identity.copy(pack = "missing", label = label), observation).permits(now))
            }
            for (label in listOf("badger", "Bad", "465bad98-c093-404b-9a47-8f19c833f988")) assertFalse(SignCollectionInterestPlan.isAlways(label))
            store.install(bytes)
            assertEquals("\"crop-interest-1\"", store.etag())
            val chosen = store.select(identity, observation)
            assertEquals("selected", chosen.decision)
            assertEquals("not_interested", store.select(identity.copy(classifier = "wrong"), observation).decision)
            val newer = JsonObject(plan.document + ("revision" to JsonPrimitive(2)))
            store.install(SignCollectionJson.canonical(newer, maximumCollectionCount = 10000).toByteArray())
            assertThrows(Exception::class.java) { store.install(bytes) }
            val conflict = JsonObject(newer + ("registry_revision" to JsonPrimitive("conflict")))
            assertThrows(Exception::class.java) { store.install(SignCollectionJson.canonical(conflict, maximumCollectionCount = 10000).toByteArray()) }
            val obsolete = JsonObject(newer + ("signature" to JsonPrimitive("obsolete")))
            assertThrows(Exception::class.java) { SignCollectionInterestPlan(SignCollectionJson.canonical(obsolete, maximumCollectionCount = 10000).toByteArray(), schema) }
            val restarted = SignCollectionInterestStore(path, schema, { now }, { uptime })
            assertEquals(2L, restarted.select(identity, observation).revision)
            now = plan.expires; uptime += 172740000000000L
            assertNull(restarted.etag())
            assertFalse(chosen.permits(now))
            assertEquals("no_valid_plan", restarted.select(identity, observation).decision)
        } finally { directory.deleteRecursively() }
    }

    @Test fun onlyEnabledStartupAndSettingActivationRequestPlans() {
        val gate = SignCollectionInterestActivation()
        assertFalse(gate.update(false)); assertFalse(gate.update(false))
        assertTrue(gate.update(true)); assertFalse(gate.update(true))
        assertFalse(gate.update(false)); assertTrue(gate.update(true)); assertFalse(gate.update(true))
        assertTrue(SignCollectionInterestActivation().update(true))
    }

    @Test fun sharedSelectionUsesUuidArithmeticWithoutCrypto() {
        val vectors = SignCollectionJson.parse(File(root, "fixtures/crop-interest-sampling-v1.json").readText()).jsonObject
        for (row in vectors.getValue("vectors").jsonArray.map { it.jsonObject }) {
            assertEquals(row.getValue("selected").jsonPrimitive.boolean, SignCollectionInterestPlan.sample(
                row.getValue("revision").jsonPrimitive.long, row.getValue("collection_key").jsonPrimitive.content,
                row.getValue("observation_id").jsonPrimitive.content, row.getValue("numerator").jsonPrimitive.long,
                row.getValue("denominator").jsonPrimitive.long))
        }
    }

    @Test fun cropSelectionNeverGatesSightingsAndFreezesPerEncounter() {
        val fixture = SignCollectionJson.parse(File(root, "fixtures/sighting-batch-v1.json").readText()).jsonObject.getValue("events").jsonArray[0].jsonObject
        for (decision in listOf("no_valid_plan", "not_interested", "sampled_out", "always", "selected")) {
            val observer = SignCollectionObserver()
            val selection = SignCollectionInterestSelection(if (decision == "no_valid_plan") null else 1,
                if (decision in listOf("selected", "sampled_out")) "DE:DE:278-10" else null, decision, 1, 1, plan.expires)
            var sightings = 0; var crops = 0; var decisions = 0
            for (ms in listOf(0L, 100, 600, 1100)) {
                observer.observe(plan.generated.plusMillis(ms), listOf(SignCollectionObserver.Detection("sign", listOf(.1, .1, .2, .2), fixture, null)),
                    captureCrop = { crops++; SignCollectionObserver.CropCaptureResult.STORED },
                    selectCrop = { _, _ -> decisions++; selection }) { event ->
                    sightings++
                    assertEquals(decision, event.getValue("collection_selection").jsonObject.getValue("decision").jsonPrimitive.content)
                }
            }
            assertEquals(1, sightings); assertEquals(1, decisions)
            assertEquals(if (selection.collects) 3 else 0, crops)
        }
    }
}
