package de.youspeed.android.alpha

import java.io.File
import org.junit.Assert.*
import org.junit.Test

class ConditionalCameraReferenceTests {
    private fun model()=SpeedLimitReferenceModel.load {File("../../shared/speed-limit-reference/$it").readBytes()}
    @Test fun evaluatedBundleMetadataSurvivesCachedReplayAndConditionalCameraRevision() {
        val runtime=SpeedReferenceRuntime(model()) {0.0}
        val rule=ConditionalSpeedRules.Reevaluation("{opaque_rule_set}",50,false,1,"DE")
        val evidence=conditionalBundleApplicability(rule,ConditionalSpeedRules.Result(50,false,false,"conditional_rules_evaluated"),0)
        runtime.bundle("same-road",SpeedReferenceValue("numeric",50),evidence)
        runtime.reevaluateCamera("camera",SpeedReferenceValue("numeric",30),0.0,0.0,mapOf("kind" to "schedule"))
        runtime.reevaluateCamera("camera",null,0.0,0.0)
        runtime.bundle("same-road",SpeedReferenceValue("numeric",50))
        assertEquals(evidence["conditions"],runtime.bundleApplicability()?.get("conditions"))
        assertEquals(runtime.output()?.applicabilityRevision,runtime.bundleApplicability()?.get("context_revision"))
        assertEquals("same-road",runtime.output()?.evidenceId)
    }
    @Test fun repeatedReevaluationPreservesIndependentZoneAndOriginalOrdinaryOrigin() {
        var now=0.0;val runtime=SpeedReferenceRuntime(model()) {now}
        runtime.context("road","road",emptySet(),"forward",true)
        runtime.bundle("osm",SpeedReferenceValue("numeric",50))
        runtime.camera("independent-zone",SpeedReferenceValue("numeric",30),enclosing=true)
        val originElapsed=runtime.elapsedSeconds;val originDistance=runtime.traveledMeters
        now=60.0
        repeat(2) {
            runtime.reevaluateCamera("condition",SpeedReferenceValue("numeric",10),originElapsed,originDistance,mapOf("kind" to "schedule"))
            assertEquals(10,runtime.output()?.value?.kmh)
            assertEquals(originElapsed to originDistance,runtime.ordinaryCameraOrigin())
            now+=1
            runtime.reevaluateCamera("condition",null,originElapsed,originDistance)
            assertEquals("independent-zone",runtime.output()?.evidenceId)
            assertEquals(30,runtime.output()?.value?.kmh)
            now+=1
        }
        now=300.0
        runtime.reevaluateCamera("condition",SpeedReferenceValue("numeric",10),originElapsed,originDistance)
        assertEquals("No reactivation may renew the original five-minute cap","independent-zone",runtime.output()?.evidenceId)
    }
    @Test fun inactiveFirstDoesNotCreateNewOriginAndVoiceNeverRestoresHistoricalCamera() {
        var now=0.0;val runtime=SpeedReferenceRuntime(model()) {now}
        runtime.context("road","road",emptySet(),"forward",true);runtime.bundle("government:BW",SpeedReferenceValue("numeric",50))
        val original=runtime.elapsedSeconds to runtime.traveledMeters
        now=299.0;runtime.tick(4999.0)
        runtime.reevaluateCamera("condition",SpeedReferenceValue("numeric",30),original.first,original.second)
        assertEquals(original,runtime.ordinaryCameraOrigin());assertEquals(30,runtime.output()?.value?.kmh)
        runtime.tick(1.0)
        assertNotEquals("condition",runtime.output()?.evidenceId)
        runtime.voice("own",SpeedReferenceValue("numeric",70))
        runtime.reevaluateCamera("condition",null,original.first,original.second)
        runtime.reevaluateCamera("condition",SpeedReferenceValue("numeric",30),original.first,original.second)
        assertEquals("voice",runtime.output()?.source);assertEquals(70,runtime.output()?.value?.kmh)
        runtime.boundary("applicable_end");runtime.tick()
        assertFalse(runtime.cameraEvidenceIds().contains("condition"))
    }
}
