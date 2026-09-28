package de.youspeed.android.alpha

import java.io.File
import org.junit.Assert.*
import org.junit.Test

class SpeedLimitReferenceModelTests {
    private val root = File("../../shared/speed-limit-reference")
    private fun bytes(name: String) = root.resolve(name).readBytes()
    private fun model() = SpeedLimitReferenceModel.load(::bytes)
    private fun normalized(value: Any?): Any? = when(value) {
        is Number -> value.toDouble()
        is Map<*, *> -> value.mapValues { normalized(it.value) }
        is List<*> -> value.map(::normalized)
        else -> value
    }
    @Test fun packagedPolicyIsTheSharedRuntimePolicy() {
        val model = model()
        assertEquals("1.1.0", model.version)
        assertEquals(listOf("voice", "camera", "bundle"), model.policy["priority"])
    }
    @Test fun frozenScenariosThroughNativeInterpreter() {
        val corpus = SpeedLimitReferenceModel.decode(bytes("scenarios-v1.1.0.json"))
        for (scenario in corpus["scenarios"] as List<Map<String, Any?>>) {
            val machine = SpeedReferenceMachine(model())
            for ((index, row) in (scenario["steps"] as List<Map<String, Any?>>).withIndex()) {
                val result = machine.step(row["event"] as Map<String, Any?>)
                val actual = mapOf("state" to result.state, "value" to result.value?.json,
                    "violation_reference_kmh" to result.baselineKmh, "penalty_reference_kmh" to result.baselineKmh,
                    "display_stale" to (result.state == "LAST_KNOWN"), "current" to result.current,
                    "generation" to result.generation, "applicability_revision" to result.applicabilityRevision,
                    "transition_id" to result.transition, "expiry_reasons" to result.expiryReasons, "rejection" to result.rejection)
                for ((key, expected) in row["expect"] as Map<String, Any?>) assertEquals("${scenario["id"]} step $index $key", normalized(expected), normalized(actual[key]))
            }
        }
    }
    @Test fun runtimePreservesBriefRampExcursionButExpiresSustainedDeparture() {
        var now = 0.0
        val runtime = SpeedReferenceRuntime(model()) { now }
        runtime.context("a8", "ref:A8", setOf("A8"), "forward", true)
        runtime.bundle("map", SpeedReferenceValue("numeric", 130))
        runtime.voice("speech", SpeedReferenceValue("numeric", 130))
        now = 137.302
        runtime.context("ramp", "ref:A57:ramp", emptySet(), "forward", true)
        runtime.tick(250.0)
        now = 143.751
        runtime.context("a8-next", "ref:A8", setOf("A8"), "forward", true)
        assertEquals("VOICE", runtime.output()?.state)
        now = 150.0
        runtime.context("ramp", "ref:A57:ramp", emptySet(), "forward", true)
        now = 158.0
        runtime.context("ramp", "ref:A57:ramp", emptySet(), "forward", true)
        assertEquals("LAST_KNOWN", runtime.output()?.state)
        assertNull(runtime.output()?.baselineKmh)
    }
    @Test fun repeatedCameraWithdrawalDoesNotEraseFreshRoadEvidence() {
        val runtime = SpeedReferenceRuntime(model()) { 0.0 }
        runtime.bundle("map", SpeedReferenceValue("numeric", 80))
        runtime.camera("sign", SpeedReferenceValue("numeric", 30))
        runtime.pipelineAuthorityWithdrawn("end-sign")
        assertEquals("LAST_KNOWN", runtime.output()?.state)
        runtime.bundle("fresh-map", SpeedReferenceValue("numeric", 80))
        repeat(100) { runtime.pipelineAuthorityWithdrawn("end-sign") }
        assertEquals("BUNDLE", runtime.output()?.state)
        assertEquals(80, runtime.output()?.baselineKmh)
        runtime.pipelineAuthorityWithdrawn("different-end-sign")
        assertEquals("LAST_KNOWN", runtime.output()?.state)
        assertNull(runtime.output()?.baselineKmh)
    }
    @Test fun dismissalRejectsDelayedEvidenceButAllowsNewSigns() {
        val gate = VisionDismissalGate()
        val now = java.time.Instant.ofEpochSecond(100)
        gate.dismiss(now, listOf("active"))
        assertFalse(gate.permits("active", now.plusSeconds(1)))
        assertFalse(gate.permits("queued", now.minusSeconds(1)))
        assertFalse(gate.permits("queued", now.plusSeconds(2)))
        assertTrue(gate.permits("new-sign", now.plusSeconds(3)))
    }
    @Test fun rejectsChangedPolicyAndApprovalLock() {
        for (changed in listOf("policy-v1.1.0.json", "approval-lock.json")) {
            assertTrue(runCatching { SpeedLimitReferenceModel.load { name -> if (name == changed) bytes(name) + byteArrayOf(32) else bytes(name) } }.isFailure)
        }
        assertTrue(runCatching { SpeedLimitReferenceModel.load { error("missing resource") } }.isFailure)
    }
    @Test fun distanceExpiryRemovesViolationAndPenaltyBaselineAtPresentationBoundary() {
        var now = 0.0
        val runtime = SpeedReferenceRuntime(model()) { now }
        runtime.camera("accepted-pipeline-passage", SpeedReferenceValue("numeric", 30))
        val current = runtime.output()!!.effective()
        val state = ConsumerUiState(speedLimitKmh = current.resolution?.speedKmh,
            currentSpeedKmh = 80.0, effectiveSpeedLimitSource = current.source)
        assertEquals(50, ConsumerMainScreenLogic.currentOverspeedKmh(state))
        now = 100.0
        runtime.tick(5_000.0)
        val stale = runtime.output()!!.effective()
        val after = state.copy(speedLimitKmh = stale.resolution?.speedKmh, effectiveSpeedLimitSource = stale.source)
        assertEquals(30, after.speedLimitKmh)
        assertEquals(EffectiveSpeedLimitSource.LAST_KNOWN, after.effectiveSpeedLimitSource)
        assertEquals(0, ConsumerMainScreenLogic.currentOverspeedKmh(after))
        assertNull(ConsumerMainScreenLogic.currentPenaltyNotice(after))
    }
}
