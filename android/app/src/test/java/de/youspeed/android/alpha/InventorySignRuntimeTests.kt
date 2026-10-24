package de.youspeed.android.alpha

import java.io.IOException
import java.time.Instant
import kotlin.io.path.createTempDirectory
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class InventorySignRuntimeTests {
    @Test fun cameraTownLocalitySurvivesConflictingMapContextAndKeepsExactNumbers() {
        val latch = CameraTownLocalityLatch()
        val at = Instant.parse("2026-10-23T10:00:00Z")
        latch.observe(true, at, "DEU")
        val rural = townLookup(100, false, DerivedSpeedSource.HIGHWAY_CLASS)
        val entered = latch.applying(rural, "DE")
        assertEquals(true, entered.insideCity)
        assertEquals(50, entered.speedLimitKmh)
        assertEquals(CameraTownLocalityLatch.SOURCE, entered.citySource)
        latch.observe(false, at.plusSeconds(1), "DE")
        val residential = townLookup(50, true, DerivedSpeedSource.HIGHWAY_CLASS, "residential")
        assertEquals(false, latch.applying(residential, "DE").insideCity)
        assertEquals(100, latch.applying(residential, "DE").speedLimitKmh)
        val explicit = residential.copy(speedLimitKmh = 70, speedSource = DerivedSpeedSource.EXPLICIT_TAG)
        assertEquals(70, latch.applying(explicit, "DE").speedLimitKmh)
        assertEquals(false, latch.applying(explicit, "DE").insideCity)
    }
    @Test fun townLocalityRejectsOldBoundariesAndResetsOnlyForNewPassageCountryOrDrive() {
        val latch = CameraTownLocalityLatch()
        val at = Instant.parse("2026-10-23T10:00:00Z")
        latch.observe(true, at, "DE")
        latch.observe(false, at.minusSeconds(1), "DE")
        assertEquals(true, latch.insideCity)
        assertFalse(latch.supersedeByPhysicalBoundary(at))
        assertEquals(true, latch.insideCity)
        latch.selectCountry("DEU")
        assertEquals(true, latch.insideCity)
        assertTrue(latch.supersedeByPhysicalBoundary(at.plusSeconds(1)))
        assertNull(latch.insideCity)
        latch.observe(false, at.plusSeconds(2), "DE")
        latch.selectCountry("FR")
        assertNull(latch.insideCity)
        latch.observe(true, at.plusSeconds(3), "DE")
        latch.reset()
        assertNull(latch.insideCity)
    }
    private fun townLookup(speed: Int, inside: Boolean, source: DerivedSpeedSource, highway: String = "primary") = SpeedLookupResult(
        wayId="10",highway=highway,streetName="road",streetBaseName="road",streetRef=null,
        speedLimitKmh=speed,isUnlimitedSpeedLimit=false,cityName=null,cityPlaceName=null,cityDistrictName=null,insideCity=inside,citySource="settlement:maxspeed_type:high",
        queryTimeMs=0.0,candidateCount=1,speedCandidateCount=1,candidateTraces=emptyList(),nearestCandidateDistanceM=0.0,nearestSpeedCandidateDistanceM=0.0,
        isTunnelSegment=false,matchedEndpointProximityM=null,streetRefTokens=emptyList(),nearbyTunnelCandidateWayIds=emptySet(),nearbyTunnelCandidateRefs=emptySet(),
        portalEligibleTunnelWayIds=emptySet(),portalEligibleTunnelRefs=emptySet(),activeCorridorState=null,approachCorridorStateCandidate=null,usedWalkingTurnSwitch=false,
        usedMiniHMM=false,miniHMMCandidateCount=0,matchHypotheses=emptyList(),selectionTrace=emptyList(),speedSource=source)
    @Test fun futureOrUnknownParameterSemanticsCannotClaimVisualConfirmation() {
        for (status in listOf("unknown", "future_status", "dynamic_unverified", "annotation_unverified")) {
            assertFalse(sign().copy(parameterStatus = status).confirmationEligible)
        }
        for (status in listOf("not_applicable", "parsed_source_value", "missing_value")) {
            assertTrue(sign().copy(parameterStatus = status).confirmationEligible)
        }
    }
    @Test fun governmentInventoryIsExplicitlyScopedToBadenWuerttemberg() {
        assertTrue(InventorySignSourceScope.allowsMobiData("DEU", "/data/baden-wuerttemberg/speeds.sqlite"))
        assertTrue(InventorySignSourceScope.allowsMobiData("DE", "/data/speeds.sqlite", "roads/baden-wuerttemberg-260913.osm.pbf"))
        assertFalse(InventorySignSourceScope.allowsMobiData("FR", "/data/baden-wuerttemberg/speeds.sqlite"))
        assertFalse(InventorySignSourceScope.allowsMobiData("DE", "/data/germany/speeds.sqlite"))
        assertFalse(InventorySignSourceScope.allowsMobiData(null, "/data/unknown.sqlite"))
        assertFalse(InventorySignSourceScope.allowsMobiData("DE", "/data/baden-wuerttemberg/speeds.sqlite", "roads/bavaria.osm.pbf"))
    }
    private val time = Instant.parse("2026-10-21T12:00:00Z")
    private val events = mutableListOf<JsonObject>()
    private val runtime = InventorySignRuntime { events += it }
    private fun sign(id: String = "one", code: String = "DE:205", radius: Double = 10.0,
                     classes: Set<String> = setOf("give_way"), kind: String = "secondary") = InventorySign(
        id,"mobidata-bw-vzk",id,"a".repeat(64),code,kind,null,null,"not_applicable",48.0,8.0,radius,
        "tsr/sign-pictograms/png/de-205.png",classes,"10",1,"accepted")
    private fun fix(meters: Double = 0.0, seconds: Long = 0, direction: Int = 1, way: String? = "10", accuracy: Double = 5.0,
                    bundle: String = "first", stable: Boolean = true) = InventorySignFix(
        48.0 + meters / 111195.0802335329,8.0,time.plusSeconds(seconds),accuracy,way,direction,stable,bundle,if(direction<0) 180.0 else 0.0,5.0)
    private fun evaluation(sign: InventorySign, fix: InventorySignFix = fix(), rules: List<InventoryWayRule> = emptyList(), chainage: Double? = null,
                           camera: Boolean = true, available: Boolean = true): InventorySignDecision {
        val decision=runtime.evaluate(InventorySignSnapshot(true,listOf(sign),rules,chainage,0.0),fix,fix.at,camera,available)
        runtime.acknowledgeBoundary(decision.boundarySignId)
        return decision
    }
    private fun rule(sign: InventorySign, speed: Int? = null, inside: Boolean? = null, direction: Int = 1) =
        InventoryWayRule("rule:${sign.id}",sign,"10",direction,50.0,500.0,50.0,0.0,speed,inside)
    private fun evidence(classId: String = "give_way", frame: String = "one", millis: Long = 0,
                         direction: Int = 1, way: String? = "10", score: Double = .95,
                         box: NormalizedTrafficSignBoundingBox = NormalizedTrafficSignBoundingBox(.1,.1,.2,.2)) =
        InventoryVisionEvidence(classId,score,frame,time.plusMillis(millis),box,"track","DE-pack","b".repeat(64),way,direction,"first")
    private fun outcomes() = events.mapNotNull { it["outcome"]?.jsonPrimitive?.content }

    @Test fun crossingSeveralTownStationsUsesLastContextAndCannotResurrectEarlierEntry() {
        val entry = sign("entry", "DE:310", 30.0, emptySet(), "settlement_boundary")
        val exit = sign("exit", "DE:311", 30.0, emptySet(), "settlement_boundary")
        val entryRule = rule(entry, inside = true).copy(start = 50.0, end = 60.0, station = 50.0)
        val exitRule = rule(exit, inside = false).copy(start = 60.0, end = 500.0, station = 60.0)
        val snapshot = InventorySignSnapshot(true, listOf(entry, exit), listOf(entryRule, exitRule), 40.0, 0.0)
        runtime.evaluate(snapshot, fix(), time, false, false)
        val crossed = runtime.evaluate(snapshot.copy(chainage = 65.0), fix(seconds = 1), time.plusSeconds(1), false, false)
        assertEquals("city_exit", crossed.boundary)
        assertEquals(false, crossed.insideCityContext)
        runtime.acknowledgeBoundary(crossed.boundarySignId)
        val jitter = runtime.evaluate(snapshot.copy(chainage = 49.0), fix(seconds = 2), time.plusSeconds(2), false, false)
        assertNull(jitter.boundary)
        val resumed = runtime.evaluate(snapshot.copy(chainage = 55.0), fix(seconds = 3), time.plusSeconds(3), false, false)
        assertNull(resumed.boundary)
    }

    @Test fun ordinarySpeedEndAfterTownCrossingCannotDiscardTownReset() {
        val entry = sign("entry", "DE:310", 30.0, emptySet(), "settlement_boundary")
        val end = sign("end", "DE:282", 10.0, emptySet(), "speed_limit_end")
        val townRule = rule(entry, inside = true).copy(start = 50.0, end = 60.0, station = 50.0)
        val endRule = rule(end, inside = true).copy(start = 60.0, end = 500.0, station = 60.0)
        val snapshot = InventorySignSnapshot(true, listOf(entry, end), listOf(townRule, endRule), 40.0, 0.0)
        runtime.evaluate(snapshot, fix(), time, false, false)
        val crossed = runtime.evaluate(snapshot.copy(chainage = 65.0), fix(seconds = 1), time.plusSeconds(1), false, false)
        assertEquals("city_entry", crossed.boundary)
        assertEquals(true, crossed.insideCityContext)
    }

    @Test fun ordinaryGeofenceUsesActualTenMeters() {
        assertNull(evaluation(sign(),fix(10.1)).display)
        assertNotNull(evaluation(sign(),fix(9.9)).display)
        assertNotNull(evaluation(sign(),fix(10.0)).display)
    }
    @Test fun townDisplayUsesThirtyMeters() {
        val town = sign(code="DE:310",radius=30.0,classes=emptySet(),kind="settlement_boundary")
        assertNull(evaluation(town,fix(30.1)).display)
        assertNotNull(evaluation(town,fix(29.9)).display)
        assertNotNull(evaluation(town,fix(30.0)).display)
    }
    @Test fun missingCapabilityStaleFixAndPoorAccuracyLeaveLegacyPathEmpty() {
        assertEquals(InventorySignDecision(),runtime.evaluate(InventorySignSnapshot(),fix(),time,true,true))
        assertFalse(InventorySignDecision().masksPostedFallback(null))
        assertFalse(InventorySignDecision().masksPostedFallback("10"))
        assertNull(evaluation(sign(),fix(accuracy=26.0)).display)
        assertNull(runtime.evaluate(InventorySignSnapshot(true,listOf(sign()),localHeading=0.0),fix(),time.plusSeconds(4),true,true).display)
    }
    @Test fun wrongDirectionUnstableAndOutsideIntervalCannotProvideSpeed() {
        val speed = sign(code="DE:274-30",classes=setOf("maxspeed:30"),kind="speed_limit")
        assertNull(evaluation(speed,fix(direction=-1),listOf(rule(speed,30)),100.0).speedRule)
        assertNull(evaluation(speed,fix(stable=false),listOf(rule(speed,30)),100.0).speedRule)
        assertNull(evaluation(speed,fix(),listOf(rule(speed,30)),49.0).speedRule)
        assertEquals(30,evaluation(speed,fix(),listOf(rule(speed,30)),51.0).speedRule?.speedKmh)
    }
    @Test fun boundaryResetsOnceAtStationAndMasksOldSpeedAfterLeavingRadius() {
        val town=sign(code="DE:310",radius=30.0,classes=emptySet(),kind="settlement_boundary")
        val rules=listOf(rule(town,inside=true))
        assertNull(evaluation(town,fix(-5.0),rules,45.0).boundary)
        val crossed=evaluation(town,fix(1.0,1),rules,51.0)
        assertEquals("city_entry",crossed.boundary)
        assertTrue(crossed.speedRule?.insideCity==true); assertNull(crossed.speedRule?.speedKmh)
        assertNull(evaluation(town,fix(5.0,2),rules,55.0).boundary)
        val beyond=evaluation(town,fix(50.0,3),rules,100.0)
        assertEquals(town,beyond.display); assertTrue(beyond.speedRule?.insideCity==true); assertNull(beyond.speedRule?.speedKmh)
    }
    @Test fun sameStationFreshSpeedWinsAndSameContextBoundaryStillResets() {
        val town=sign(code="DE:310",radius=30.0,classes=emptySet(),kind="settlement_boundary")
        val speed=sign("fresh","DE:274-30",classes=setOf("maxspeed:30"),kind="speed_limit")
        val boundary=rule(town,inside=true).copy(end=50.0)
        val fresh=rule(speed,30,true)
        evaluation(town,fix(-1.0),listOf(boundary,fresh),49.0)
        val entered=evaluation(town,fix(1.0,1),listOf(boundary,fresh),51.0)
        assertEquals("city_entry",entered.boundary)
        assertEquals(30,entered.speedRule?.speedKmh)
        assertNull(evaluation(town,fix(2.0,2),listOf(boundary,fresh),52.0).boundary)
    }
    @Test fun reverseIntervalsAreOpenAtStartAndClosedAtEnd() {
        val speed=sign(code="DE:274-30",classes=setOf("maxspeed:30"),kind="speed_limit")
        val reverse=rule(speed,30,direction=-1)
        assertNull(evaluation(speed,fix(direction=-1),listOf(reverse),50.0).speedRule)
        assertNotNull(evaluation(speed,fix(direction=-1),listOf(reverse),500.0).speedRule)
    }
    @Test fun conflictingOverlapsAndUnknownHeadingFailClosed() {
        val speed=sign(code="DE:274-30",classes=setOf("maxspeed:30"),kind="speed_limit")
        val rules=listOf(rule(speed,30),rule(speed,50).copy(id="conflict"))
        assertNull(evaluation(speed,fix(),rules,100.0).speedRule)
        assertNull(evaluation(speed,fix().copy(heading=null),listOf(rule(speed,30)),100.0).speedRule)
        assertNull(evaluation(speed,fix().copy(headingAccuracy=36.0),listOf(rule(speed,30)),100.0).speedRule)
        assertNull(evaluation(speed,fix().copy(heading=90.0),listOf(rule(speed,30)),100.0).speedRule)
    }
    @Test fun noDetectionFramesCanCloseAsNotObservedOnlyWithEnoughEvidence() {
        evaluation(sign())
        runtime.analyzedFrame("empty-a",time,"10",1,time,"first")
        runtime.analyzedFrame("empty-b",time.plusMillis(100),"10",1,time.plusMillis(100),"first")
        evaluation(sign(),fix(20.0,1))
        assertTrue("not_observed" in outcomes())
    }
    @Test fun endCancellationUsesFreshUrbanDefaultInsteadOfOldPostedSeventy() {
        val end=rule(sign(code="DE:278",kind="speed_limit_end"))
        val offer=InventorySignRoadOffer.from(end,true,"secondary","DE")
        assertEquals(50,offer.speedKmh); assertFalse(offer.unlimited)
        assertNull(InventorySignRoadOffer.from(end,null,"secondary","DE").speedKmh)
    }
    @Test fun acceptedEndAtStationUsesExistingApplicableEndBoundaryAndRearmsOnReverse() {
        val end=sign(code="DE:278",kind="speed_limit_end")
        val rules=listOf(rule(end))
        evaluation(end,fix(-1.0),rules,49.0)
        assertEquals("applicable_end",evaluation(end,fix(1.0,1),rules,51.0).boundary)
        assertNull(evaluation(end,fix(2.0,2),rules,52.0).boundary)
        assertNull(evaluation(end,fix(2.0,3,direction=0),rules,52.0).boundary)
        assertEquals(50,InventorySignRoadOffer.from(rules.single(),true,"secondary","DE").speedKmh)
    }
    @Test fun freshFixesMayCrossTownStationWhileSkippingDisplayCircle() {
        val town=sign(code="DE:310",radius=30.0,classes=emptySet(),kind="settlement_boundary")
        val rules=listOf(rule(town,inside=true))
        assertNull(evaluation(town,fix(-40.0),rules,10.0).boundary)
        val crossed=evaluation(town,fix(40.0,1),rules,90.0)
        assertEquals("city_entry",crossed.boundary); assertNull(crossed.display); assertTrue(crossed.captureSignIds.isEmpty())
    }
    @Test fun enteringCancellationIntervalPastGeofenceClearsOldReferenceOnce() {
        val end=sign(code="DE:278",kind="speed_limit_end")
        val rules=listOf(rule(end))
        assertEquals("applicable_end",evaluation(end,fix(40.0),rules,100.0).boundary)
        assertNull(evaluation(end,fix(50.0,1),rules,110.0).boundary)
    }
    @Test fun invalidFixRetainsConsumedBoundaryUntilKnownExitThenRearms() {
        val town=sign(code="DE:310",radius=30.0,classes=emptySet(),kind="settlement_boundary")
        val rules=listOf(rule(town,inside=true))
        assertEquals("city_entry",evaluation(town,fix(),rules,50.0).boundary)
        evaluation(town,fix(seconds=1,accuracy=100.0),rules,51.0)
        assertNull(evaluation(town,fix(2.0,2),rules,52.0).boundary)
        evaluation(town,fix(40.0,3),rules,90.0)
        evaluation(town,fix(-1.0,4),rules,49.0)
        assertEquals("city_entry",evaluation(town,fix(1.0,5),rules,51.0).boundary)
    }
    @Test fun invalidFixCannotBridgeAnUnobservedBoundaryCrossing() {
        val town=sign(code="DE:310",radius=30.0,classes=emptySet(),kind="settlement_boundary")
        val rules=listOf(rule(town,inside=true))
        evaluation(town,fix(-40.0),rules,10.0)
        evaluation(town,fix(0.0,1,accuracy=100.0),rules,50.0)
        assertNull(evaluation(town,fix(40.0,2),rules,90.0).boundary)
    }
    @Test fun childWayContinuationKeepsTownContextWithoutPhysicalBoundaryReset() {
        val town=sign(code="DE:310",radius=30.0,classes=emptySet(),kind="settlement_boundary")
        val sourceRule=rule(town,inside=true)
        assertEquals("city_entry",evaluation(town,fix(),listOf(sourceRule),50.0).boundary)
        val continuation=sourceRule.copy(id="child-rule",wayId="20",start=0.0,station=0.0)
        val child=evaluation(town,fix(seconds=1,way="20"),listOf(continuation),1.0)
        assertNull(child.boundary)
        assertTrue(child.speedRule?.insideCity==true)
        assertTrue(child.insideCityContext==true)
        assertEquals(town,child.display)
    }
    @Test fun parameterWithoutArtworkStillHasTextualDisplayAndLoggedProvenance() {
        val height=sign(code="DE:265-3.8",kind="maximum_height",classes=emptySet()).copy(value=3.8,unit="m",parameterStatus="parsed_source_value",pictogramPath=null)
        val decision=evaluation(height)
        assertEquals("3.8 m",decision.display?.parameterText); assertNull(decision.display?.pictogram())
        assertEquals(3.8,events.single()["numeric_value"]?.jsonPrimitive?.double)
    }
    @Test fun lateFrameFromPriorBundleCannotConfirmNewEncounter() {
        evaluation(sign(),fix(bundle="second"))
        runtime.observe(evidence(),time); runtime.observe(evidence(frame="two",millis=100),time.plusMillis(100))
        assertFalse("camera_confirmed" in outcomes())
    }
    @Test fun cameraOffAndUnsupportedAreLoggedWithoutVisualConfirmation() {
        evaluation(sign(),camera=false)
        assertTrue("camera_off" in outcomes()); assertFalse("camera_confirmed" in outcomes())
        evaluation(sign("unsupported",classes=emptySet()))
        assertTrue("unsupported_model_class" in outcomes())
    }
    @Test fun twoDistinctFramesAndMinimumTimeAreRequired() {
        evaluation(sign()); runtime.observe(evidence(frame="one"),time)
        runtime.observe(evidence(frame="one",millis=200),time.plusMillis(200))
        assertFalse("camera_confirmed" in outcomes())
        runtime.observe(evidence(frame="two",millis=300),time.plusMillis(300))
        assertTrue("camera_confirmed" in outcomes())
        val confirmed=events.first { it["outcome"]?.jsonPrimitive?.content=="camera_confirmed" }
        assertEquals(2,confirmed["frame_ids"]?.jsonArray?.size)
        assertEquals("a".repeat(64),confirmed["snapshot_sha256"]?.jsonPrimitive?.content)
    }
    @Test fun fastFramesAccumulateSpanAndConfirmOnlyOnce() {
        evaluation(sign())
        listOf(0L,33L,66L,100L,133L).forEach { millis ->
            runtime.observe(evidence(frame="frame-$millis",millis=millis),time.plusMillis(millis))
        }
        val confirmed=events.filter { it["outcome"]?.jsonPrimitive?.content=="camera_confirmed" }
        assertEquals(1,confirmed.size)
        assertEquals(listOf("frame-0","frame-100"),confirmed.single()["frame_ids"]?.jsonArray?.map { it.jsonPrimitive.content })
    }
    @Test fun directedEndSignTriggersOnlyInsideTenMetersAndAcceptedDirection() {
        val end=sign(code="DE:278",kind="speed_limit_end")
        assertNull(evaluation(end,fix(10.1)).display)
        assertNull(evaluation(end,fix(direction=-1)).display)
        assertEquals("DE:278",evaluation(end,fix(9.9)).display?.code)
    }
    @Test fun secondaryPersistsBeyondRadiusAndAcrossInvalidFixOrCameraOff() {
        val original=sign()
        val first=evaluation(original)
        assertTrue(first.displayChanged);assertEquals(time,first.displayTriggeredAt)
        val beyond=evaluation(original,fix(100.0,1),camera=false)
        assertEquals(original,beyond.display);assertTrue(beyond.captureSignIds.isEmpty());assertFalse(beyond.displayChanged)
        val stale=runtime.evaluate(InventorySignSnapshot(true),fix(seconds=2),time.plusSeconds(20),false,false)
        assertEquals(original,stale.display);assertEquals(time,stale.displayTriggeredAt);assertTrue(stale.captureSignIds.isEmpty())
    }
    @Test fun knownOppositeSecondaryCannotDisplayCaptureOrConfirm() {
        val opposite=sign().copy(associatedHeadingDeg=180.0)
        val decision=evaluation(opposite)
        assertNull(decision.display);assertTrue(decision.captureSignIds.isEmpty())
        assertNull(runtime.registerCaptureIfEligible(listOf(opposite.id),48.0,8.0,time))
        runtime.observe(evidence(),time);runtime.observe(evidence(frame="second",millis=100),time.plusMillis(100))
        assertFalse("camera_confirmed" in outcomes())
        assertEquals("known_opposite_face",events.first()["face_relation"]?.jsonPrimitive?.content)
    }
    @Test fun secondaryFaceDoesNotRequireTheSameWayAndRotatesSourceDirectionOnce() {
        val sameFaceAcrossSplit=sign().copy(associatedWayId="other-way",associatedHeadingDeg=180.0,associatedDirection=-1)
        val decision=evaluation(sameFaceAcrossSplit)
        assertEquals(sameFaceAcrossSplit,decision.display);assertEquals(listOf(sameFaceAcrossSplit.id),decision.captureSignIds)
        assertEquals(0.0,sameFaceAcrossSplit.sourceTravelHeading!!,0.0001)
    }
    @Test fun secondaryFaceRejectsOnlyQualifiedDifferenceGreaterThanNinety() {
        val source=sign().copy(associatedHeadingDeg=0.0)
        assertEquals(source,evaluation(source,fix().copy(heading=90.0)).display)
        val opposite=evaluation(source,fix(seconds=1).copy(heading=90.1))
        assertNull(opposite.display);assertTrue(opposite.displayChanged);assertEquals("known_opposite_face",opposite.displayChangeReason)
    }
    @Test fun unknownSourceOrVehicleHeadingKeepsProximitySemantics() {
        val source=sign().copy(associatedHeadingDeg=180.0)
        val unknown=fix().copy(headingAccuracy=null)
        assertEquals(source,evaluation(source,unknown).display);assertEquals("face_unknown",source.secondaryFaceRelation(unknown))
        runtime.finish(time.plusSeconds(1))
        val unresolved=source.copy(associationStatus="rejected")
        assertEquals(unresolved,evaluation(unresolved,fix(seconds=2)).display)
        assertEquals("face_unknown",unresolved.secondaryFaceRelation(fix()))
    }
    @Test fun heldSecondarySurvivesDistantHairpinButClearsKnownOppositionInsideOwnFence() {
        val source=sign().copy(associatedHeadingDeg=0.0)
        evaluation(source)
        assertEquals(source,evaluation(source,fix(100.0,1).copy(heading=180.0)).display)
        assertNull(evaluation(source,fix(seconds=2).copy(heading=180.0)).display)
    }
    @Test fun nextSecondaryReplacesButNumericSpeedDoesNot() {
        val original=sign();evaluation(original)
        val speed=sign("speed","DE:274-30",kind="speed_limit")
        assertEquals(original,evaluation(speed,fix(seconds=1)).display)
        val replacement=sign("two","DE:206")
        val next=evaluation(replacement,fix(seconds=2))
        assertEquals(replacement,next.display);assertTrue(next.displayChanged);assertEquals(time.plusSeconds(2),next.displayTriggeredAt)
        val end=sign("end","DE:282",kind="restriction_end")
        assertEquals(end,evaluation(end,fix(seconds=3)).display)
    }
    @Test fun cameraReplacementWaitsForNewInventoryEncounter() {
        val original=sign();evaluation(original);runtime.replaceSecondaryWithCamera()
        assertNull(evaluation(original,fix(seconds=1)).display)
        assertNull(evaluation(original,fix(20.0,2)).display)
        assertEquals(original,evaluation(original,fix(seconds=3)).display)
    }
    @Test fun sessionAndBundleTransitionsClearHeldSecondaryWithoutAffectingLegacyRegions() {
        evaluation(sign());runtime.finish(time.plusSeconds(1))
        assertNull(runtime.evaluate(InventorySignSnapshot(true),fix(seconds=2),time.plusSeconds(2),false,false).display)
        evaluation(sign(),fix(seconds=3))
        assertEquals(InventorySignDecision(),runtime.evaluate(InventorySignSnapshot(),fix(seconds=4,bundle="old-region"),time.plusSeconds(4),false,false))
    }
    @Test fun townAndEndFallbackKeepActualSourceIdentity() {
        val town=sign("town","DE:310",radius=30.0,kind="settlement_boundary")
        val first=evaluation(town,fix(),listOf(rule(town,inside=true)),50.0)
        assertEquals(town,first.cityContextSign)
        val latched=evaluation(town,fix(60.0,1,way="20"))
        assertEquals(town,latched.cityContextSign)
        val end=sign("end","DE:278",kind="speed_limit_end")
        val canceled=evaluation(end,fix(seconds=2),listOf(rule(end)),51.0)
        assertEquals(end,canceled.resetContextSign)
    }
    @Test fun cancellationCarriesTypedSourceAction() {
        val end=sign(code="DE:282",kind="restriction_end")
        val result=evaluation(end,fix(),listOf(rule(end)),100.0)
        assertEquals(TrafficSignActionKind.ALL_RESTRICTIONS_END,result.boundaryAction?.kind)
    }
    @Test fun poorHeadingWithholdsDirectedCardsCaptureAndConfirmation() {
        val town=sign(code="DE:310",radius=30.0,kind="settlement_boundary",classes=setOf("town_begin"))
        val poor=fix().copy(headingAccuracy=null)
        val decision=evaluation(town,poor,listOf(rule(town,inside=true)),51.0)
        assertNull(decision.display); assertNull(decision.speedRule); assertTrue(decision.captureSignIds.isEmpty())
        runtime.observe(evidence(classId="town_begin"),time)
        runtime.observe(evidence(classId="town_begin",frame="two",millis=100),time.plusMillis(100))
        assertFalse("camera_confirmed" in outcomes())
        val ordinary=evaluation(sign("ordinary"),poor)
        assertNotNull(ordinary.display); assertEquals(listOf("ordinary"),ordinary.captureSignIds)
    }
    @Test fun wrongWayDirectionLowScoreAndDifferentBoxCannotConfirm() {
        evaluation(sign()); runtime.observe(evidence(way="20"),time)
        runtime.observe(evidence(direction=-1,millis=100),time.plusMillis(100))
        runtime.observe(evidence(score=.5,millis=200),time.plusMillis(200))
        runtime.observe(evidence(frame="a",millis=300),time.plusMillis(300))
        runtime.observe(evidence(frame="b",millis=500,box=NormalizedTrafficSignBoundingBox(.7,.7,.1,.1)),time.plusMillis(500))
        assertFalse("camera_confirmed" in outcomes())
    }
    @Test fun duplicateClassSignsAreAmbiguous() {
        runtime.evaluate(InventorySignSnapshot(true,listOf(sign(),sign("two")),localHeading=0.0),fix(),time,true,true)
        runtime.observe(evidence(),time)
        assertEquals(2,outcomes().count { it=="ambiguous" }); assertFalse("camera_confirmed" in outcomes())
    }
    @Test fun wrongNumericValueIsMismatch() {
        evaluation(sign(code="DE:274-30",classes=setOf("maxspeed:30"),kind="speed_limit"))
        runtime.observe(evidence("maxspeed:50"),time)
        assertEquals(listOf("camera_mismatch"),outcomes())
    }
    @Test fun failedDurableCommitDoesNotConsumeConfirmation() {
        var fail=true
        val persistent=InventorySignRuntime { if(fail) throw IOException("full"); events+=it }
        persistent.evaluate(InventorySignSnapshot(true,listOf(sign()),localHeading=0.0),fix(),time,true,true)
        persistent.observe(evidence(),time)
        assertThrows(IOException::class.java) { persistent.observe(evidence(frame="two",millis=100),time.plusMillis(100)) }
        fail=false; persistent.observe(evidence(frame="two",millis=100),time.plusMillis(100))
        assertTrue("camera_confirmed" in outcomes())
    }
    @Test fun captureFailureRetriesButSuccessConsumesAndActualRadiusIsRechecked() {
        val ids=evaluation(sign()).captureSignIds
        assertEquals(ids,runtime.captureEligibleIds(ids,48.0,8.0,time))
        assertTrue(runtime.captureEligibleIds(ids,fix(20.0).latitude,8.0,time).isEmpty())
        runtime.captureFailed(ids,"storage",time); assertEquals(ids,evaluation(sign()).captureSignIds)
        runtime.captured(ids,"capture-one",time); assertTrue(evaluation(sign()).captureSignIds.isEmpty())
        assertTrue("capture_failed" in outcomes()); assertTrue("capture_saved" in outcomes())
    }
    @Test fun cameraCanBecomeAvailableWithinAnEncounter() {
        evaluation(sign(),camera=false); evaluation(sign(),camera=true)
        runtime.observe(evidence(),time); runtime.observe(evidence(frame="two",millis=100),time.plusMillis(100))
        assertEquals(listOf("camera_off","camera_confirmed"),outcomes())
    }
    @Test fun cameraToggleRequiresTwoNewFramesAfterReactivation() {
        evaluation(sign()); runtime.observe(evidence(),time)
        evaluation(sign(),camera=false); evaluation(sign(),camera=true)
        runtime.observe(evidence(frame="after-on",millis=200),time.plusMillis(200))
        assertFalse("camera_confirmed" in outcomes())
        runtime.observe(evidence(frame="second-after-on",millis=300),time.plusMillis(300))
        assertTrue("camera_confirmed" in outcomes())
    }
    @Test fun differentActualTracksCannotConfirmTogether() {
        evaluation(sign()); runtime.observe(evidence(),time)
        runtime.observe(evidence(frame="other-track",millis=200).copy(trackId="other"),time.plusMillis(200))
        assertFalse("camera_confirmed" in outcomes())
        runtime.observe(evidence(frame="other-track-two",millis=300).copy(trackId="other"),time.plusMillis(300))
        assertTrue("camera_confirmed" in outcomes())
    }
    @Test fun newRoadContextRearmsEncounterAndRejectsFramesBeforeItsStart() {
        val source=sign().copy(associationStatus=null,associatedWayId=null,associatedDirection=null)
        val first=evaluation(source).captureSignIds
        runtime.captured(first,"first",time)
        val changed=evaluation(source,fix(seconds=1,way="20"))
        assertEquals(listOf(source.id),changed.captureSignIds)
        runtime.observe(evidence(frame="old",way="20",millis=500),time.plusSeconds(1))
        runtime.observe(evidence(frame="new",way="20",millis=1100),time.plusMillis(1100))
        assertFalse("camera_confirmed" in outcomes())
        runtime.observe(evidence(frame="new-two",way="20",millis=1200),time.plusMillis(1200))
        assertTrue("camera_confirmed" in outcomes())
    }
    @Test fun savedPhotoKeepsOriginalEncounterUuidAcrossGeofenceExitAndReentry() {
        val sourceIds=evaluation(sign()).captureSignIds
        val encounterIds=runtime.registerCapture(sourceIds)
        assertEquals(1,encounterIds.size)
        assertNotEquals(sourceIds.single(),encounterIds.single())
        evaluation(sign(),fix(20.0,1)); evaluation(sign(),fix(0.0,2))
        runtime.capturedEncounters(encounterIds,"old-photo",time.plusSeconds(2))
        assertEquals(encounterIds.single(),events.last()["encounter_id"]?.jsonPrimitive?.content)
        assertTrue(evaluation(sign(),fix(0.0,2)).captureSignIds.isNotEmpty())
    }
    @Test fun queueRetainsOptionalEncounterIdsAndReadsLegacyMetadata() {
        val root=createTempDirectory("inventory-photo-queue").toFile()
        try {
            val queue=PanoramaxQueueStore(root); val batch=queue.createBatch("session",time)
            val original=java.io.File(root,"original.jpg").apply { writeBytes(byteArrayOf(-1,-40,1,-1,-39)) }
            val thumb=java.io.File(root,"thumb.jpg").apply { writeBytes(byteArrayOf(-1,-40,2,-1,-39)) }
            val id=java.util.UUID.randomUUID().toString()
            val metadata=PanoramaxCaptureMetadata("capture",batch.captureSessionId,time,PanoramaxLocationSample(48.0,8.0,time,5.0),
                PanoramaxQueueStore.sha256(original),original.length(),"test",captureReason="inventory_sign",inventoryEncounterIds=listOf(id))
            queue.addJpeg(batch.batchId,original,thumb,metadata)
            assertEquals(listOf(id),PanoramaxQueueStore(root).getBatch(batch.batchId)?.items?.single()?.metadata?.inventoryEncounterIds)
            assertTrue(metadata.copy(inventoryEncounterIds=null).validate().isEmpty())
            assertTrue(metadata.copy(inventoryEncounterIds=listOf("source-record-is-not-an-encounter")).validate().isNotEmpty())
        } finally { root.deleteRecursively() }
    }
    @Test fun modelAndPackSwitchCannotConfirmAcrossTwoDifferentClassifiers() {
        evaluation(sign())
        runtime.observe(evidence(),time)
        runtime.observe(evidence(frame="two",millis=100).copy(packId="changed-pack",modelHash="c".repeat(64)),time.plusMillis(100))
        assertFalse("camera_confirmed" in outcomes())
        runtime.observe(evidence(frame="three",millis=200).copy(packId="changed-pack",modelHash="c".repeat(64)),time.plusMillis(200))
        assertTrue("camera_confirmed" in outcomes())
    }
    @Test fun mismatchDoesNotPermanentlyBlockLaterActualCorrectTrack() {
        evaluation(sign(code="DE:274-30",classes=setOf("maxspeed:30"),kind="speed_limit"))
        runtime.observe(evidence("maxspeed:50"),time)
        runtime.observe(evidence("maxspeed:30","right-a",100),time.plusMillis(100))
        runtime.observe(evidence("maxspeed:30","right-b",200),time.plusMillis(200))
        assertEquals(listOf("camera_mismatch","camera_confirmed"),outcomes())
    }
    @Test fun mapRulesContinueWhenJournalIsFullAndMetadataRetriesLater() {
        var fail=true
        val persistent=InventorySignRuntime { if(fail) throw IOException("full"); events+=it }
        val speed=sign(code="DE:274-30",classes=setOf("maxspeed:30"),kind="speed_limit")
        val snapshot=InventorySignSnapshot(true,listOf(speed),listOf(rule(speed,30)),100.0,0.0)
        val decision=persistent.evaluate(snapshot,fix(),time,false,false)
        assertEquals(30,decision.speedRule?.speedKmh); assertNotNull(persistent.takePersistenceFailure())
        assertTrue(events.isEmpty())
        fail=false; persistent.evaluate(snapshot,fix(seconds=1),time.plusSeconds(1),false,false)
        assertEquals(listOf("camera_off"),outcomes())
    }
    @Test fun boundaryIsRetriedUntilControllerCommitsItsReset() {
        val town=sign(code="DE:310",radius=30.0,classes=emptySet(),kind="settlement_boundary")
        val snapshot=InventorySignSnapshot(true,listOf(town),listOf(rule(town,inside=true)),51.0,0.0)
        val pending=runtime.evaluate(snapshot,fix(),time,false,false)
        assertEquals("city_entry",pending.boundary)
        assertEquals("city_entry",runtime.evaluate(snapshot,fix(seconds=1),time.plusSeconds(1),false,false).boundary)
        runtime.acknowledgeBoundary(pending.boundarySignId)
        assertNull(runtime.evaluate(snapshot,fix(seconds=2),time.plusSeconds(2),false,false).boundary)
    }
    @Test fun oppositeFaceAndParallelTargetCannotBeCameraConfirmed() {
        val target=sign(code="DE:274-30",classes=setOf("maxspeed:30"),kind="speed_limit").copy(associatedWayId="other-way",associatedDirection=-1)
        evaluation(target)
        runtime.observe(evidence("maxspeed:30","a"),time)
        runtime.observe(evidence("maxspeed:30","b",100),time.plusMillis(100))
        assertTrue("ambiguous" in outcomes()); assertFalse("camera_confirmed" in outcomes())
        assertTrue(evaluation(target).captureSignIds.isEmpty())
        val town=target.copy(code="DE:310",kind="settlement_boundary",radiusMeters=30.0)
        assertNull(evaluation(town).display)
        assertTrue(evaluation(town).captureSignIds.isEmpty())
    }
    @Test fun acceptedTownContextPersistsOnUnsignedContinuationWithoutRules() {
        val town=sign(code="DE:310",radius=30.0,classes=emptySet(),kind="settlement_boundary")
        assertEquals(true,evaluation(town,fix(),listOf(rule(town,inside=true)),51.0).insideCityContext)
        val next=runtime.evaluate(InventorySignSnapshot(true),fix(seconds=1,way="20"),time.plusSeconds(1),false,false)
        assertEquals(true,next.insideCityContext)
        assertNull(runtime.evaluate(InventorySignSnapshot(),fix(seconds=2,way="30",bundle="other-region"),time.plusSeconds(2),false,false).insideCityContext)
    }
    @Test fun townResetMasksSameWayStalePostedTagWhenActiveIntervalIsUnavailable() {
        val town=sign(code="DE:310",radius=30.0,kind="settlement_boundary")
        val crossed=evaluation(town,fix(),listOf(rule(town,inside=true)),50.0)
        assertFalse(crossed.permitsPostedFallback("10"))
        val noInterval=runtime.evaluate(InventorySignSnapshot(true,localHeading=0.0),fix(seconds=1),time.plusSeconds(1),false,false)
        assertNull(noInterval.speedRule); assertTrue(noInterval.insideCityContext==true)
        assertFalse(noInterval.permitsPostedFallback("10"))
        val newWay=runtime.evaluate(InventorySignSnapshot(true,localHeading=0.0),fix(seconds=2,way="20"),time.plusSeconds(2),false,false)
        assertTrue(newWay.permitsPostedFallback("20"))
        assertFalse(newWay.permitsPostedFallback("10"))
        assertFalse(newWay.permitsPostedFallback(null))
    }
    @Test fun endResetSurvivesHeadingLossButAllowsEstablishedOppositeDirection() {
        val end=sign(code="DE:278",kind="speed_limit_end")
        val result=evaluation(end,fix(),listOf(rule(end)),100.0)
        assertFalse(result.permitsPostedFallback("10"))
        val noHeading=runtime.evaluate(InventorySignSnapshot(true,localHeading=0.0),fix(seconds=1).copy(headingAccuracy=null),time.plusSeconds(1),false,false)
        assertNull(noHeading.speedRule); assertFalse(noHeading.permitsPostedFallback("10"))
        val opposite=runtime.evaluate(InventorySignSnapshot(true,localHeading=0.0),fix(seconds=2,direction=-1),time.plusSeconds(2),false,false)
        assertTrue(opposite.permitsPostedFallback("10"))
        val forward=runtime.evaluate(InventorySignSnapshot(true,localHeading=0.0),fix(seconds=3),time.plusSeconds(3),false,false)
        assertFalse(forward.permitsPostedFallback("10"))
    }
    @Test fun atomicCaptureRegistrationRejectsRemovedOrWronglyRearmedCandidates() {
        val speed=sign(code="DE:274-30",kind="speed_limit",classes=setOf("maxspeed:30"))
        val ids=evaluation(speed).captureSignIds
        val original=runtime.registerCaptureIfEligible(ids,48.0,8.0,time)!!
        runtime.captureFailedEncounters(original,"retry",time)
        evaluation(speed,fix(20.0,1))
        assertNull(runtime.registerCaptureIfEligible(ids,48.0,8.0,time.plusSeconds(1)))
        evaluation(speed,fix(seconds=2,direction=-1))
        assertNull(runtime.registerCaptureIfEligible(ids,48.0,8.0,time.plusSeconds(2)))
        evaluation(speed,fix(seconds=3))
        val current=runtime.registerCaptureIfEligible(ids,48.0,8.0,time.plusSeconds(3))!!
        assertNotEquals(original.single(),current.single())
        runtime.capturedEncounters(current,"real-capture",time.plusSeconds(3))
        assertEquals(current.single(),events.last()["encounter_id"]?.jsonPrimitive?.content)
    }
    @Test fun unverifiedSourceParametersCannotBeConfirmedFromVocabularyCoverage() {
        for(status in listOf("dynamic_unverified","annotation_unverified","invalid_value","malformed_code")) {
            val source=sign(id=status).copy(parameterStatus=status)
            evaluation(source)
            runtime.observe(evidence(frame="$status-a"),time)
            runtime.observe(evidence(frame="$status-b",millis=100),time.plusMillis(100))
        }
        assertEquals(4,outcomes().count { it=="unsupported_model_class" })
        assertFalse("camera_confirmed" in outcomes())
    }
    @Test fun journalPersistsOrdinaryNdjson() {
        val file=createTempDirectory("inventory-log").resolve("encounters.ndjson").toFile()
        try {
            InventorySignJournal(file).append(buildJsonObject { put("outcome","camera_off") })
            assertEquals("camera_off",Json.parseToJsonElement(file.readText().trim()).jsonObject["outcome"]?.jsonPrimitive?.content)
        } finally { requireNotNull(file.parentFile).deleteRecursively() }
    }
}
