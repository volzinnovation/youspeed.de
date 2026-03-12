package de.youspeed.android.alpha

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LocalObservationStoreInstrumentedTest {
    @Test
    fun approveAndSingleExportWritesReviewPackage() {
        val store = createStore()
        val captured = store.captureVoiceCommand(
            command = "hier gilt 50",
            captureContext = captureContext(wayId = "7102", street = "Tunnel Section", city = "Karlsruhe"),
        )

        assertEquals(LocalObservationState.NEEDS_REVIEW, captured.state)

        val approved = store.reviewAndApproveProposal(captured.id)
        assertEquals(LocalObservationState.APPROVED_FOR_EXPORT, approved.state)

        val export = store.exportProposalAsOscPackage(captured.id)
        assertTrue(export.changesFile.exists())
        assertTrue(export.reviewFile.exists())
        assertTrue(export.readmeFile.exists())
        assertTrue(export.reviewFile.readText().contains(captured.id))

        val exported = store.fetchObservations(limit = 10).first { it.id == captured.id }
        assertEquals(LocalObservationState.EXPORTED_OSC, exported.state)
    }

    @Test
    fun bulkExportSupportsWalkValueAndKeepsLatestPerWay() {
        val store = createStore()
        store.recordSpeedLimitChange(
            oldSpeedKmh = 30,
            newMaxspeedValue = "walk",
            captureContext = captureContext(wayId = "5001", street = "Innenstadt", city = "Karlsruhe"),
            initialState = LocalObservationState.LOCAL_ONLY,
        )
        store.recordSpeedLimitChange(
            oldSpeedKmh = 50,
            newMaxspeedValue = "30",
            captureContext = captureContext(wayId = "5001", street = "Innenstadt", city = "Karlsruhe"),
            initialState = LocalObservationState.LOCAL_ONLY,
        )
        store.recordSpeedLimitChange(
            oldSpeedKmh = 70,
            newMaxspeedValue = "80",
            captureContext = captureContext(wayId = "5002", street = "B 10", city = "Karlsruhe"),
            initialState = LocalObservationState.LOCAL_ONLY,
        )

        val bulk = store.exportAllLocalObservationsAsOsc()
        val xml = bulk.changesFile.readText()

        assertEquals(2, bulk.includedCount)
        assertTrue(xml.contains("""way id="5001""""))
        assertTrue(xml.contains("""way id="5002""""))
        assertTrue(xml.contains("""maxspeed" v="30""""))
        assertTrue(xml.contains("""maxspeed" v="80""""))
    }

    private fun createStore(): LocalObservationStore {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val rootDir = File(context.cacheDir, "local-observation-store-${UUID.randomUUID()}").apply { mkdirs() }
        val prefs = context.getSharedPreferences("local-observation-store-${UUID.randomUUID()}", Context.MODE_PRIVATE)
        val clock = Clock.fixed(Instant.parse("2026-03-12T10:15:30Z"), ZoneOffset.UTC)
        return LocalObservationStore(context, rootDir, prefs, clock)
    }

    private fun captureContext(
        wayId: String,
        street: String,
        city: String,
    ): LocalObservationCaptureContext {
        return LocalObservationCaptureContext(
            lat = 49.0101,
            lon = 8.4255,
            headingDeg = 90.0,
            roadCandidateIds = listOf(wayId),
            cityContext = city,
            streetContext = street,
            confidenceCalibrated = 0.85,
            sourceVersion = "2026-03-12",
        )
    }
}
