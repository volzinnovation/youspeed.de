package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class DashcamButtonActionGateTests {
    @Test
    fun actionWithoutMovieRunsImmediatelyWithoutStoppingVideo() {
        val gate = DashcamButtonActionGate()
        val events = mutableListOf<String>()

        gate.submit(null, { events += "stop" }, { events += "action" })

        assertEquals(listOf("action"), events)
        assertFalse(gate.isWaiting)
    }

    @Test
    fun repeatedTapsWaitForMatchingFinalizationAndRunOnlyFirstAction() {
        val gate = DashcamButtonActionGate()
        val events = mutableListOf<String>()

        gate.submit("first.mp4", { events += "stop" }, { events += "first" })
        gate.submit("first.mp4", { events += "extra stop" }, { events += "extra" })
        gate.submit(null, { events += "unexpected stop" }, { events += "immediate" })
        assertTrue(gate.isWaiting)
        assertEquals(listOf("stop"), events)

        gate.onFinalized("old.mp4", success = true)
        gate.onFinalized("old.mp4", success = false)
        assertTrue(gate.isWaiting)
        assertEquals(listOf("stop"), events)

        gate.onFinalized("first.mp4", success = true)
        gate.onFinalized("first.mp4", success = true)
        assertEquals(listOf("stop", "first"), events)
        assertFalse(gate.isWaiting)
    }

    @Test
    fun failedFinalizationDropsActionAndAllowsAnotherTap() {
        val gate = DashcamButtonActionGate()
        val events = mutableListOf<String>()
        gate.submit("failed.mp4", {}, { events += "failed action" })

        gate.onFinalized("failed.mp4", success = false)
        assertFalse(gate.isWaiting)
        gate.onFinalized("failed.mp4", success = true)
        gate.submit(null, {}, { events += "next action" })

        assertEquals(listOf("next action"), events)
    }

    @Test
    fun cancelDropsPendingActionAndStaleCallbackCannotCompleteNextMovie() {
        val gate = DashcamButtonActionGate()
        val events = mutableListOf<String>()
        gate.submit("cancelled.mp4", {}, { events += "cancelled action" })
        gate.cancel()
        gate.cancel()
        assertFalse(gate.isWaiting)

        gate.submit("next.mp4", {}, { events += "next action" })
        gate.onFinalized("cancelled.mp4", success = true)
        assertTrue(gate.isWaiting)
        assertTrue(events.isEmpty())
        gate.onFinalized("next.mp4", success = true)

        assertEquals(listOf("next action"), events)
        assertFalse(gate.isWaiting)
    }

    @Test
    fun synchronousStopCompletionCanSubmitAnotherActionWithoutLosingIt() {
        val gate = DashcamButtonActionGate()
        val events = mutableListOf<String>()

        gate.submit(
            "first.mp4",
            stopVideo = {
                assertTrue(gate.isWaiting)
                gate.submit(null, {}, { events += "reentrant tap" })
                events += "first stop"
                gate.onFinalized("first.mp4", success = true)
            },
            action = {
                assertFalse(gate.isWaiting)
                events += "first action"
                gate.submit("second.mp4", { events += "second stop" }, { events += "second action" })
            },
        )

        assertTrue(gate.isWaiting)
        gate.onFinalized("first.mp4", success = true)
        assertTrue(gate.isWaiting)
        gate.onFinalized("second.mp4", success = true)

        assertEquals(listOf("first stop", "first action", "second stop", "second action"), events)
        assertFalse(gate.isWaiting)
    }

    @Test
    fun explicitStopIntentIsPreservedAfterRecordingFlagChanges() {
        val gate = DashcamButtonActionGate()
        var isRecording = true
        var starts = 0
        val shouldStart = !isRecording

        gate.submit(
            "movie.mp4",
            stopVideo = { isRecording = false },
            action = { if (shouldStart) { starts += 1; isRecording = true } },
        )
        gate.onFinalized("movie.mp4", success = true)

        assertFalse(isRecording)
        assertEquals(0, starts)
    }

    @Test
    fun throwingStopClearsPendingActionAndPropagatesFailure() {
        val gate = DashcamButtonActionGate()
        val failure = IllegalStateException("stop failed")
        var actions = 0

        try {
            gate.submit("movie.mp4", { throw failure }, { actions += 1 })
            throw AssertionError("Expected stop failure")
        } catch (error: IllegalStateException) {
            assertSame(failure, error)
        }

        assertFalse(gate.isWaiting)
        gate.onFinalized("movie.mp4", success = true)
        assertEquals(0, actions)
        gate.submit(null, {}, { actions += 1 })
        assertEquals(1, actions)
    }
}
