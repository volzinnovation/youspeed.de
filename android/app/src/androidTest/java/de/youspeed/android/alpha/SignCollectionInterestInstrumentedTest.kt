package de.youspeed.android.alpha

import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

/** Exercises the packaged plan contract and cache on Android, using a private test directory. */
class SignCollectionInterestInstrumentedTest {
    @Test fun packagedHttpsPlanAndActivationKeepBadEligibleAfterExpiry() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val schema = context.assets.open("tsr/collection-contract-v1/crop-interest-v1.schema.json").use {
            SignCollectionJson.parse(it.readBytes().toString(Charsets.UTF_8)).jsonObject
        }
        val bytes = context.assets.open("tsr/collection-contract-v1/fixtures/crop-interest-daily-maximum-v1.json").use { it.readBytes() }
        val plan = SignCollectionInterestPlan(bytes, schema)
        var now = plan.generated.plusSeconds(1)
        var uptime = 1_000_000_000L
        val root = File(context.cacheDir, "interest-device-${SignCollectionJson.uuid()}").apply { mkdirs() }
        try {
            val path = File(root, "plan.json")
            val store = SignCollectionInterestStore(path, schema, { now }, { uptime })
            val identity = plan.rules.keys.first()
            val observation = "00000000-0000-4000-8000-000000000001"
            assertEquals("no_valid_plan", store.select(identity, observation).decision)
            store.install(bytes)
            assertEquals("selected", store.select(identity, observation).decision)
            assertEquals("not_interested", store.select(identity.copy(classifier = "wrong"), observation).decision)
            assertEquals(plan.revision, SignCollectionInterestStore(path, schema, { now }, { uptime }).select(identity, observation).revision)
            now = plan.expires; uptime += 172_799_000_000_000L
            assertEquals("no_valid_plan", store.select(identity, observation).decision)
            assertTrue(store.select(identity.copy(pack = "missing", label = "bad:future"), observation).permits(now))
            assertFalse(store.select(identity.copy(label = "465bad98-c093-404b-9a47-8f19c833f988"), observation).collects)
            val activation = SignCollectionInterestActivation()
            assertFalse(activation.update(false)); assertTrue(activation.update(true))
            assertFalse(activation.update(true)); assertFalse(activation.update(false)); assertTrue(activation.update(true))
        } finally { root.deleteRecursively() }
    }
}
