package de.youspeed.android.alpha

import java.time.Instant
import org.junit.Assert.*
import org.junit.Test

class SignCaptureFilterTests {
    @Test fun stableAllClassEncountersAreDistinctAndGloballyThrottled() {
        val filter = SignCaptureFilter(); val at = Instant.parse("2026-10-05T10:00:00Z")
        val signs = listOf(SignCaptureFilter.Detection("white", "white", listOf(.1,.1,.2,.2), .8), SignCaptureFilter.Detection("white", "white", listOf(.7,.1,.2,.2), .9))
        assertTrue(filter.observe(at, signs).isEmpty())
        val evidence = filter.observe(at.plusMillis(100), signs)
        assertEquals(2, evidence.size); assertEquals(2, evidence.map { it.trackId }.distinct().size)
        filter.captured(evidence, at.plusMillis(100))
        assertTrue(filter.observe(at.plusMillis(200), signs).isEmpty())
        val next = SignCaptureFilter.Detection("arrow", "arrow", listOf(.4,.4,.1,.1), .9)
        assertTrue(filter.observe(at.plusMillis(300), listOf(next)).isEmpty())
        assertTrue(filter.observe(at.plusMillis(400), listOf(next)).isEmpty())
        assertEquals(1, filter.observe(at.plusMillis(2100), listOf(next)).size)
        filter.observe(at.plusMillis(4201), emptyList())
        filter.observe(at.plusMillis(4301), signs)
        assertEquals(2, filter.observe(at.plusMillis(4401), signs).size)
    }
}
