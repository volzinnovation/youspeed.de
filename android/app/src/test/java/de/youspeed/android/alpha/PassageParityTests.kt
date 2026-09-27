package de.youspeed.android.alpha

import java.io.File
import java.time.Instant
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class PassageParityTests {
    // Shared completed prefixes establish valid map scope before loss. Android
    // emits raw evidence here; its resolver performs the later activation check.
    @Test fun sharedPassageSuppressionCorpus() {
        val corpus = Json.parseToJsonElement(File("../../shared/tsr/passage/suppression-v1.json").readText()).jsonObject
        assertEquals(1, corpus.getValue("schemaVersion").jsonPrimitive.int)
        val prefixes = corpus.getValue("prefixes").jsonObject
        val scenarios = corpus.getValue("scenarios").jsonArray
        assertTrue(scenarios.isNotEmpty())
        for (raw in scenarios) {
            val scenario = raw.jsonObject
            val id = scenario.getValue("id").jsonPrimitive.content
            val frames = prefixes.getValue(scenario.getValue("prefix").jsonPrimitive.content).jsonArray + scenario.getValue("frames").jsonArray
            val finalizer = TrafficSignPassageFinalizer()
            for (value in frames) {
                val frame = value.jsonObject
                val event = event(frame)
                val result = finalizer.observe(event, event.candidate?.calibratedConfidence, 1, true, true)
                val label = "$id at ${frame.getValue("atMs")}ms"
                assertEquals(label, frame.getValue("expectActive").jsonPrimitive.boolean, finalizer.hasActiveTrack())
                assertEquals(label, frame["expectCommit"]?.jsonPrimitive?.int, result?.action?.valueKmh)
            }
        }
    }

    @Test fun rawPassageWithoutRecognitionOriginCannotActivateAfterContextReturnsAtLoss() {
        val finalizer = TrafficSignPassageFinalizer()
        val frames = Json.parseToJsonElement("""
            [
              {"atMs":0,"track":"track-30","position":null},
              {"atMs":100,"track":"track-30","position":null},
              {"atMs":200,"track":null,"position":[0,0]},
              {"atMs":300,"track":null,"position":[0,0]}
            ]
        """).jsonArray
        var rawPassage: TrafficSignPassageEvent? = null
        for (frame in frames) {
            val recognition = event(frame.jsonObject)
            rawPassage = finalizer.observe(recognition, recognition.candidate?.calibratedConfidence, 1, true, true)
                ?: rawPassage
        }
        // iPhone rejects before emitting a committed passage; Android's native
        // resolver must reject the same unmatched evidence before camera activation.
        val passage = requireNotNull(rawPassage)
        assertNull(passage.firstSeenContext)
        val resolver = TrafficSignRuntimeSourceResolver()
        val base = TrafficSignBaseLimit(TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, 50), EffectiveSpeedLimitSource.BUNDLE, "test")
        val effective = resolver.commit(passage, base)
        assertEquals(50, effective.resolution?.speedKmh)
        assertEquals(EffectiveSpeedLimitSource.BUNDLE, effective.source)
        assertNull(resolver.activeAssertion())
    }

    private fun event(frame: JsonObject): TrafficSignRecognitionEvent {
        val sha = "a".repeat(64)
        val atMs = frame.getValue("atMs").jsonPrimitive.long
        val position = frame["position"]?.takeUnless { it == JsonNull }?.jsonArray
        val context = position?.let {
            TrafficSignDetectionContext("100", it[0].jsonPrimitive.double, it[1].jsonPrimitive.double,
                90.0, TrafficSignTravelDirection.FORWARD, TrafficSignRuntimeSourceSignature("bundle:test|way:100", null),
                bundleSha256 = sha, countryCode = "DEU", routeRelationGroupIds = setOf(1), sourceRelationIds = setOf(1001),
                continuityCapable = true, traversalEpoch = 1, matchedWayStable = true, speedMetersPerSecond = 50.0 / 3.6)
        }
        val candidate = frame["track"]?.takeUnless { it == JsonNull }?.jsonPrimitive?.content?.let { track ->
            TrafficSignCandidate("speed_limit_30", "30", TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED, 30, "km/h"),
                0.95, 0.95, NormalizedTrafficSignBoundingBox(0.7, 0.1, 0.1, 0.2), trackId = track, evidenceFrames = 2,
                assemblyId = "assembly-$track")
        }
        return TrafficSignRecognitionEvent(1, "parity-pack", sha, "rgb-v1", TrafficSignInputSource.LIVE_FRAME,
            Instant.ofEpochSecond(1_788_279_200).plusMillis(atMs),
            if (candidate == null) TrafficSignRecognitionState.NO_RECOGNITION else TrafficSignRecognitionState.CONFIRMED,
            candidate, context, 1.0, null, frameId = "frame-$atMs", driveSessionId = "parity-drive",
            calibrationId = "test", componentRole = "direct_detector",
            modelComponents = listOf(TrafficSignModelComponentLineage("direct_detector", sha, "rgb-v1", "test")))
    }
}
