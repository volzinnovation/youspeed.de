package de.youspeed.android.alpha

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

class RoadPathSessionTests {

    @Test fun previewExperimentsCannotChangeTSRPathEvidence() {
        val baseline=RoadPathSession(nowNanos={1_000_000})
        val requested=RoadPathSession(detectionOptions=RoadBoundaryDetectionOptions(useSearchBands=true,groupFragments=true),
            fragmentTracking=true,retainTentativeIdentity=true,jointSelection=true,nowNanos={1_000_000})
        for(i in 0..<8) {
            val a=baseline.prepare(paintedFrame(i),"a-$i",scope)
            val b=requested.prepare(paintedFrame(i),"b-$i",scope)
            assertEquals(a.geometry.boundaries,b.geometry.boundaries)
            assertEquals(a.presentation.visibleBoundaryIndices,b.presentation.visibleBoundaryIndices)
            assertFalse(b.diagnostics.fragmentTrackingEnabled)
            assertFalse(b.diagnostics.tentativeIdentityEnabled)
            assertFalse(b.diagnostics.jointSelectionEnabled)
            assertEquals("baseline",b.diagnostics.detectionVariant)
        }
    }

    @Test fun preparationDiagnosticsIdentifyComponentAndCurrentIntrinsicsWithoutDriftResets() {
        val session=RoadPathSession(previewMode=true,nowNanos={1_000_000})
        fun input(i:Int,cx:Double=.5,geometry:String="geometry")=paintedFrame(i).copy(calibration=camera.copy(cx=cx),geometryId=geometry)
        val first=session.prepare(input(0),"0",scope)
        assertEquals(listOf("initial"),first.diagnostics.resetComponents)
        val drift=session.prepare(input(1,.50001),"1",scope)
        assertEquals(first.diagnostics.calibrationGeneration,drift.diagnostics.calibrationGeneration)
        assertEquals(.50001,requireNotNull(drift.diagnostics.calibration).cx,1e-12)
        assertTrue(drift.diagnostics.resetComponents.isEmpty())
        assertEquals(setOf("luma","queueAndAdmission","filter","prediction","detector","fusion","presentation","total"),drift.diagnostics.stageMs.keys)
        assertEquals(listOf("calibration"),session.prepare(input(2,.502),"2",scope).diagnostics.resetComponents)
        assertEquals(listOf("geometry"),session.prepare(input(3,.502,"crop"),"3",scope).diagnostics.resetComponents)
        session.invalidateOverlay()
        assertEquals(listOf("lifecycle"),session.prepare(input(4,.502,"crop"),"4",scope).diagnostics.resetComponents)
    }
    @Test fun weakSavedGuidesCannotCropAwayObservedPaintOrMutateSavedCalibration() {
        val session=RoadPathSession(previewMode=true,nowNanos={1_000_000})
        val saved=VisualRoadCalibration("shifted",128,72,"test",.75,LanePoint(.03,1.0),.03,LanePoint(.54,1.0),.54)
        val input=paintedFrame(0).copy(visualCalibration=saved,orientationKey="test")
        val result=session.prepare(input,"weak",scope)
        assertEquals("weak",result.diagnostics.guideTrust.state)
        assertEquals("observed_border_conflict",result.diagnostics.guideTrust.reason)
        assertEquals("none_independent_audit",result.diagnostics.guidePriorUsed)
        assertEquals(2,result.geometry.boundaries.size)
        assertTrue(result.geometry.boundaries.all { it.points.first().y < saved.horizonY })
        assertEquals(saved,result.frame.visualCalibration)
    }
    @Test fun guideTrustRequiresIndependentBothSideEvidenceAndExpiresOrRejectsConflict() {
        val validator=RoadVisualGuideValidator()
        val saved=VisualRoadCalibration("saved",128,72,"test",.42,LanePoint(.23,1.0),.23,LanePoint(.75,1.0),.75)
        fun borders(shift:Double=0.0,provenance:RoadBoundaryProvenance=RoadBoundaryProvenance.FRESH)=listOf(.23,.75).map {
            RoadBoundaryEvidence(listOf(LanePoint(it+shift,.55),LanePoint(it+shift,.9)),.95,RoadBoundaryCue.PAINT,12,provenance=provenance)
        }
        for(i in 0..<5) {
            val time=i*.1; val plan=validator.begin(saved,saved,time,"camera")
            assertEquals(if(i == 4) "trusted" else "weak",validator.observe(borders(),saved,time,plan).state)
        }
        val expiry=validator.begin(saved,saved,2.0,"camera")
        assertFalse(expiry.trusted); assertEquals("independent_evidence_expired",expiry.reason)
        val conflictPlan=RoadVisualGuidePlan(true,false,"audit")
        assertEquals("observed_border_conflict",validator.observe(borders(.15),saved,2.1,conflictPlan).reason)
        for(i in 0..<5) {
            val time=3+i*.1; val plan=validator.begin(saved,saved,time,"new-camera")
            assertEquals("weak",validator.observe(borders(provenance=RoadBoundaryProvenance.TRACKED),saved,time,plan).state)
        }
        val onlyLeft=validator.observe(borders().take(1),saved,4.0,conflictPlan)
        assertEquals(1,onlyLeft.matchedSides); assertEquals("weak",onlyLeft.state)
    }

    @Test fun previewCalibrationIdentityAnchorsDriftAndResetsRealChanges() {
        val identity = RoadPreviewCalibrationIdentity()
        val first = identity.key(camera)
        for (i in 0..<10) assertEquals(first,identity.key(camera.copy(cx=.5+i*.00001)))
        val drifted = identity.key(camera.copy(cx=.5011))
        assertNotEquals(first,drifted)
        val zoomed = identity.key(camera.copy(cx=.5011,fx=.82))
        assertNotEquals(drifted,zoomed)
        val mounted = identity.key(camera.copy(cx=.5011,fx=.82,revision="new-mount"))
        assertNotEquals(zoomed,mounted)
        val missing = identity.key(null)
        assertNotEquals(mounted,missing)
        assertNotEquals(missing,identity.key(camera))
    }
    @Test fun previewMaturesWithTinyIntrinsicsDriftAndResetsOnZoomAndCrop() {
        val session = RoadPathSession(previewMode=true,nowNanos={1_000_000})
        val gray = ByteArray(128*72) { 55 }
        for(y in 0..<72) for(x in listOf(29,30,31,94,95,96)) gray[y*128+x]=230.toByte()
        fun prepare(i:Int,fx:Double=.8,geometry:String="geometry"): RoadPathPreparedFrame {
            val input = frame(10+i*.1).copy(grayscale=gray,calibration=camera.copy(cx=.5+i*.00001,fx=fx),
                geometryId=geometry,rawWidth=128,rawHeight=72,sourceTimestampSeconds=100+i*.1)
            return session.prepare(input,"drift-$i",scope)
        }
        for(i in 0..<10) {
            val result = prepare(i)
            assertEquals(2,result.geometry.boundaries.size)
            if(i>=4) assertEquals(2,result.presentation.visibleBoundaryIndices.size)
        }
        assertTrue(prepare(10,fx=.82).presentation.visibleBoundaryIndices.isEmpty())
        for(i in 11..<16) prepare(i,fx=.82)
        assertEquals(2,prepare(16,fx=.82).presentation.visibleBoundaryIndices.size)
        assertTrue(prepare(17,fx=.82,geometry="new-crop").presentation.visibleBoundaryIndices.isEmpty())
    }

    private val scope = TSRApplicabilityScope("drive", "bundle", "camera", 1, 1, 1)
    private fun diagnostic(time: Double) = TSRApplicabilityDiagnostic(1,
        TSRFrameCandidateBatch(1, "frame-$time", time*1000, scope, "analyzed", emptyList(), false, 0, "model", "preprocess", null), emptyList(), emptyList())
    private fun frame(time: Double, known: Boolean = true, start: Long = 0) = RoadPathCameraFrame(
        ByteArray(128*72), 128, 72, time, "geometry", null, known, 0.0, start)
    private val camera = RoadPathCalibration("mount", true, .8, .8, .5, .5, 0.0, 0.0, 0.0, 1.6, -.08)
    private fun signDiagnostic(time: Double): TSRApplicabilityDiagnostic {
        val forward = 30 - (time-10)*10
        val x = .5 + .8*3.08/forward
        val y = .5 + .8*(1.6-2)/forward
        val candidate = TSRApplicabilityCandidate("candidate-$time", "maximum_speed:50:",
            TSRApplicabilityBox(x-.01, y-.01, .02, .02), .99, true, null)
        val batch = diagnostic(time).batch.copy(candidates=listOf(candidate), rawCandidateCount=1)
        return TSRApplicabilityDiagnostic(1, batch, listOf(TSRPhysicalTrackSnapshot("physical-sign", scope,
            listOf(TSRTrackSample(batch.frameId, time*1000, candidate)), "observed", false)), emptyList())
    }
    private fun recordFix(session: RoadPathSession, time: Double) = session.recordLocation(time,
        48.0 + Math.toDegrees((time-10)*10/6_371_000), 8.0, 0.0, 10.0, .02, .02)
    private fun evaluateSign(session: RoadPathSession, time: Double, sourceTime: Double? = null) = Json.parseToJsonElement(
        session.evaluate(frame(time).copy(calibration=camera, sourceTimestampSeconds=sourceTime), signDiagnostic(time))).jsonObject

    @Test fun futureFixIsNotExposedAsCausalTrajectory() {
        val session = RoadPathSession { 1_000_000 }
        session.recordLocation(11.0, 48.0, 8.0, 0.0, 10.0, .1, .1)
        val result = Json.parseToJsonElement(session.evaluate(frame(10.0), diagnostic(10.0))).jsonObject
        assertEquals(0, result.getValue("trajectorySamples").jsonPrimitive.int)
        assertEquals("shadow", result.getValue("mode").jsonPrimitive.content)
        assertFalse(result.getValue("calibrationAvailable").jsonPrimitive.boolean)
    }

    private fun paintedFrame(i: Int): RoadPathCameraFrame {
        val gray = ByteArray(128*72) { 55 }
        for(y in 0..<72) for(x in listOf(29,30,31,94,95,96)) gray[y*128+x]=230.toByte()
        return frame(10+i*.1).copy(grayscale=gray, sourceTimestampSeconds=100+i*.1)
    }

    @Test fun slowPreparationKeepsMatureGeometryAndReportsPerformanceTargetOnly() {
        for (preview in listOf(false,true)) {
            val session = RoadPathSession(previewMode=preview,nowNanos={60_000_000})
            for(i in 0..10) {
                val prepared = session.prepare(paintedFrame(i),"slow-$i",scope)
                assertFalse(prepared.geometry.budgetExceeded)
                assertEquals(2,prepared.geometry.boundaries.size)
                assertTrue(prepared.performanceTargetExceeded)
                assertTrue(prepared.presentation.accepted)
                if(i>=4) assertEquals(2,prepared.presentation.visibleBoundaryIndices.size)
                assertNotNull(session.overlay())
            }
        }
        val session = RoadPathSession { 60_000_000 }
        val result = Json.parseToJsonElement(session.evaluate(frame(10.0),diagnostic(10.0))).jsonObject
        assertFalse(result.getValue("geometryDeadlineExceeded").jsonPrimitive.boolean)
        assertTrue(result.getValue("preparationPerformanceTargetExceeded").jsonPrimitive.boolean)
    }

    @Test fun crossingPerformanceTargetAfterSelectionNeverInvalidatesGeometryOrPresentation() {
        for (preview in listOf(false,true)) {
            var calls=0
            var crossingAt: Int?=null
            var elapsed=50_000_000L
            val session=RoadPathSession(previewMode=preview,nowNanos={
                calls++
                if(crossingAt!=null && calls>=crossingAt!!) elapsed else 1_000_000L
            })
            for(i in 0..10) { calls=0; session.prepare(paintedFrame(i),"warm-$i",scope) }
            crossingAt=calls // The final preparation clock read, after mature side selection.
            for((offset,time) in listOf(50_000_000L,60_000_000L).withIndex()) {
                calls=0; elapsed=time
                val prepared=session.prepare(paintedFrame(11+offset),"crossing-$offset",scope)
                assertEquals(time/1e6,prepared.preparationAddedMs,0.0)
                assertEquals(time>50_000_000L,prepared.performanceTargetExceeded)
                assertFalse(prepared.geometry.budgetExceeded)
                assertTrue(prepared.presentation.accepted)
                assertEquals(listOf(0,1),prepared.presentation.visibleBoundaryIndices)
                // The exact formerly crashing diagnostic lookup must also remain safe.
                assertEquals(2,prepared.presentation.visibleBoundaryIndices.map { prepared.geometry.boundaries[it].points }.size)
                assertEquals(2,session.overlay()?.boundaries?.size)
            }
            crossingAt=null; calls=0
            val recovered=session.prepare(paintedFrame(13),"timely-again",scope)
            assertEquals(2,recovered.presentation.visibleBoundaryIndices.size)
            assertFalse(recovered.performanceTargetExceeded)
        }
    }

    @Test fun realOperationExhaustionStillRejectsGeometryAndPresentationTogether() {
        for(preview in listOf(false,true)) {
            val session=RoadPathSession(previewMode=preview,maximumGeometryOperations=100,nowNanos={60_000_000})
            val prepared=session.prepare(paintedFrame(0),"operation-limit",scope)
            assertTrue(prepared.geometry.budgetExceeded)
            assertTrue(prepared.geometry.boundaries.isEmpty())
            assertFalse(prepared.presentation.accepted)
            assertTrue(prepared.presentation.visibleBoundaryIndices.isEmpty())
            assertEquals("geometry_budget",prepared.presentation.reason)
            assertEquals(0,prepared.presentation.rawCount)
            assertNull(session.overlay())
        }
    }

    @Test fun independentPreviewDoesNotInheritSignAssociationDeadline() {
        val session=RoadPathSession(previewMode=true,nowNanos={250_000_000})
        for(i in 0..10) session.prepare(paintedFrame(i),"slow-preview-$i",scope)
        assertEquals(2,session.overlay()?.boundaries?.size)
    }

    @Test fun totalDeadlineDiscardsAllAssociationsAfterSerialization() {
        val session = RoadPathSession { 201_000_000 }
        val result = Json.parseToJsonElement(session.evaluate(frame(10.0), diagnostic(10.0))).jsonObject
        assertTrue(result.getValue("deadlineExceeded").jsonPrimitive.boolean)
        assertEquals("added_processing_deadline", result.getValue("reason").jsonPrimitive.content)
        assertTrue(result.getValue("associations").jsonArray.isEmpty())
        assertNull(session.overlay())
    }

    @Test fun unknownCaptureClockCannotPublishLiveGeometry() {
        val session = RoadPathSession { 1_000_000 }
        val result = Json.parseToJsonElement(session.evaluate(frame(10.0, false), diagnostic(10.0))).jsonObject
        assertFalse(result.getValue("captureClockKnown").jsonPrimitive.boolean)
        assertNull(session.overlay())
    }

    @Test fun dualProviderDuplicateAndOlderFixesPreserveThreeObservationTriangulation() {
        val session = RoadPathSession { 1_000_000 }
        for ((index, time) in listOf(10.0, 11.0, 12.0).withIndex()) {
            recordFix(session, time)
            // A fused re-delivery and delayed provider fix must not rewrite the accepted pose.
            session.recordLocation(time, 49.0, 9.0, 90.0, 20.0, .01, .01)
            session.recordLocation(time-.2, 49.0, 9.0, 90.0, 20.0, .01, .01)
            val result = evaluateSign(session, time)
            assertEquals(index+1, result.getValue("trajectorySamples").jsonPrimitive.int)
            assertEquals(48.0, result.getValue("localOrigin").jsonObject.getValue("latitude").jsonPrimitive.double, 0.0)
            val ingestion = result.getValue("locationIngestion").jsonObject
            assertEquals(index+1, ingestion.getValue("duplicateFixesDropped").jsonPrimitive.int)
            assertEquals(index+1, ingestion.getValue("outOfOrderFixesDropped").jsonPrimitive.int)
            assertEquals(0, ingestion.getValue("resetCount").jsonPrimitive.int)
            val association = result.getValue("associations").jsonArray.single().jsonObject
            assertEquals(index+1, association.getValue("observations").jsonArray.size)
            if (index == 2) {
                assertEquals(3, association.getValue("supportingObservations").jsonPrimitive.int)
                assertEquals("current_path_unavailable", association.getValue("reason").jsonPrimitive.content)
                assertEquals(3.0, association.getValue("eastMeters").jsonPrimitive.double, 1e-6)
                assertEquals(30.0, association.getValue("northMeters").jsonPrimitive.double, 1e-6)
                assertEquals("unknown", association.getValue("classification").jsonPrimitive.content)
                assertTrue(association.getValue("shadowOnly").jsonPrimitive.boolean)
            }
        }
    }

    @Test fun explicitResetStartsNewOriginAndObservationHistory() {
        val session = RoadPathSession { 1_000_000 }
        recordFix(session, 10.0); evaluateSign(session, 10.0)
        recordFix(session, 11.0); evaluateSign(session, 11.0)
        session.resetTrajectory()
        assertNull(session.overlay())
        session.recordLocation(11.2, 49.0, 9.0, 0.0, 10.0, .02, .02)
        val result = evaluateSign(session, 11.2)
        assertEquals(1, result.getValue("trajectorySamples").jsonPrimitive.int)
        assertEquals(49.0, result.getValue("localOrigin").jsonObject.getValue("latitude").jsonPrimitive.double, 0.0)
        assertEquals(1, result.getValue("locationIngestion").jsonObject.getValue("resetCount").jsonPrimitive.int)
        assertEquals(1, result.getValue("associations").jsonArray.single().jsonObject.getValue("observations").jsonArray.size)
        session.resetTrajectory()
        recordFix(session, 5.0) // Only the explicit reset permits a new, earlier clock epoch.
        val next = Json.parseToJsonElement(session.evaluate(frame(5.0), diagnostic(5.0))).jsonObject
        assertEquals(5.0, next.getValue("trajectory").jsonArray.single().jsonObject.getValue("timeSeconds").jsonPrimitive.double, 0.0)
        assertEquals(2, next.getValue("locationIngestion").jsonObject.getValue("resetCount").jsonPrimitive.int)
    }

    @Test fun duplicateAndOlderFramesPublishNoEvidenceAndPreserveTrackHistoryAndOverlay() {
        val session = RoadPathSession { 1_000_000 }
        recordFix(session, 10.0); evaluateSign(session, 10.0)
        recordFix(session, 11.0); evaluateSign(session, 11.0)
        val overlay = session.overlay()
        assertNotNull(overlay)
        for ((time, reason) in listOf(11.0 to "duplicate_frame", 10.5 to "out_of_order_frame")) {
            val skipped = evaluateSign(session, time)
            assertEquals(reason, skipped.getValue("reason").jsonPrimitive.content)
            assertTrue(skipped.getValue("associations").jsonArray.isEmpty())
            assertFalse(skipped.containsKey("boundaries"))
            assertSame(overlay, session.overlay())
        }
        recordFix(session, 12.0)
        val result = evaluateSign(session, 12.0)
        val association = result.getValue("associations").jsonArray.single().jsonObject
        assertEquals(listOf(10.0, 11.0, 12.0), association.getValue("observations").jsonArray.map {
            it.jsonObject.getValue("timeSeconds").jsonPrimitive.double })
        assertEquals(3, association.getValue("supportingObservations").jsonPrimitive.int)
    }

    @Test fun changedScopeAcceptsEarlierExposureWithoutReusingHistory() {
        val session = RoadPathSession { 1_000_000 }
        recordFix(session, 10.0); evaluateSign(session, 10.0)
        val next = signDiagnostic(9.0)
        val changed = next.copy(batch=next.batch.copy(scope=scope.copy(generation=2)))
        val result = Json.parseToJsonElement(session.evaluate(frame(9.0).copy(calibration=camera), changed)).jsonObject
        assertFalse(result.containsKey("reason"))
        assertEquals(1, result.getValue("associations").jsonArray.single().jsonObject.getValue("observations").jsonArray.size)
    }

    @Test fun rawExposureOrderingRejectsRedeliveryDespiteNewerMappedUtc() {
        val session = RoadPathSession { 1_000_000 }
        recordFix(session, 10.0); evaluateSign(session, 10.0, 100.0)
        recordFix(session, 11.0); evaluateSign(session, 11.0, 101.0)
        val overlay = session.overlay()
        val duplicate = evaluateSign(session, 11.1, 101.0)
        val older = evaluateSign(session, 11.2, 100.5)
        assertEquals("duplicate_frame", duplicate.getValue("reason").jsonPrimitive.content)
        assertEquals("out_of_order_frame", older.getValue("reason").jsonPrimitive.content)
        for (skipped in listOf(duplicate, older)) {
            assertEquals("source_exposure", skipped.getValue("frameOrderingClock").jsonPrimitive.content)
            assertTrue(skipped.getValue("associations").jsonArray.isEmpty())
        }
        assertSame(overlay, session.overlay())
        recordFix(session, 12.0)
        val result = evaluateSign(session, 12.0, 102.0)
        val association = result.getValue("associations").jsonArray.single().jsonObject
        assertEquals(listOf(10.0, 11.0, 12.0), association.getValue("observations").jsonArray.map {
            it.jsonObject.getValue("timeSeconds").jsonPrimitive.double })
        assertEquals(3, association.getValue("supportingObservations").jsonPrimitive.int)
        session.resetTrajectory(); recordFix(session, 5.0)
        val reset = evaluateSign(session, 5.0, 1.0)
        assertFalse(reset.containsKey("reason"))
        assertEquals(1, reset.getValue("associations").jsonArray.single().jsonObject.getValue("observations").jsonArray.size)
    }

    private class PausedClock {
        val entered = CountDownLatch(1)
        val resume = CountDownLatch(1)
        private val first = AtomicBoolean(true)
        fun now(): Long {
            if (first.compareAndSet(true, false)) {
                entered.countDown()
                check(resume.await(5, TimeUnit.SECONDS)) { "Test evaluator was not resumed" }
            }
            return 1_000_000L
        }
    }

    @Test fun overlayAndLocationCallbacksDoNotWaitForImageAnalysisAndSnapshotStaysFrozen() {
        val clock = PausedClock()
        val session = RoadPathSession(clock::now)
        session.recordLocation(10.0, 48.0, 8.0, 0.0, 10.0, .1, .1)
        val evaluator = Executors.newSingleThreadExecutor()
        val callbacks = Executors.newSingleThreadExecutor()
        try {
            val evaluation = evaluator.submit<String> { session.evaluate(frame(10.0), diagnostic(10.0)) }
            assertTrue(clock.entered.await(2, TimeUnit.SECONDS))
            // The evaluator remains deliberately blocked. These callbacks must complete before
            // its latch opens; an implementation holding the data lock for analysis deadlocks here.
            callbacks.submit {
                assertNull(session.overlay())
                session.recordLocation(11.0, 48.0001, 8.0, 0.0, 10.0, .1, .1)
            }.get(2, TimeUnit.SECONDS)
            assertFalse(evaluation.isDone)
            clock.resume.countDown()
            val result = Json.parseToJsonElement(evaluation.get(2, TimeUnit.SECONDS)).jsonObject
            assertEquals(listOf(10.0), result.getValue("trajectory").jsonArray.map { it.jsonObject.getValue("timeSeconds").jsonPrimitive.double })
            val next = Json.parseToJsonElement(session.evaluate(frame(11.0), diagnostic(11.0))).jsonObject
            assertEquals(listOf(10.0,11.0), next.getValue("trajectory").jsonArray.map { it.jsonObject.getValue("timeSeconds").jsonPrimitive.double })
        } finally {
            clock.resume.countDown(); evaluator.shutdownNow(); callbacks.shutdownNow()
        }
    }

    @Test fun duplicateAndOlderLocationCallbacksDoNotInvalidateAnEvaluationAlreadyInFlight() {
        val clock = PausedClock()
        val session = RoadPathSession(clock::now)
        recordFix(session, 10.0)
        val evaluator = Executors.newSingleThreadExecutor()
        val callbacks = Executors.newSingleThreadExecutor()
        try {
            val evaluation = evaluator.submit<String> { session.evaluate(frame(10.0), diagnostic(10.0)) }
            assertTrue(clock.entered.await(2, TimeUnit.SECONDS))
            callbacks.submit { recordFix(session, 10.0); recordFix(session, 9.0) }.get(2, TimeUnit.SECONDS)
            clock.resume.countDown()
            val result = Json.parseToJsonElement(evaluation.get(2, TimeUnit.SECONDS)).jsonObject
            assertFalse(result.containsKey("reason"))
            assertEquals(1, result.getValue("trajectorySamples").jsonPrimitive.int)
            assertNotNull(session.overlay())
            val next = Json.parseToJsonElement(session.evaluate(frame(10.1), diagnostic(10.1))).jsonObject
            val ingestion = next.getValue("locationIngestion").jsonObject
            assertEquals(1, ingestion.getValue("duplicateFixesDropped").jsonPrimitive.int)
            assertEquals(1, ingestion.getValue("outOfOrderFixesDropped").jsonPrimitive.int)
            assertEquals(0, ingestion.getValue("resetCount").jsonPrimitive.int)
        } finally {
            clock.resume.countDown(); evaluator.shutdownNow(); callbacks.shutdownNow()
        }
    }

    @Test fun explicitResetDiscardsAnEvaluationAlreadyInFlight() {
        val clock = PausedClock()
        val session = RoadPathSession(clock::now)
        session.recordLocation(10.0, 48.0, 8.0, 0.0, 10.0, .1, .1)
        val evaluator = Executors.newSingleThreadExecutor()
        val callbacks = Executors.newSingleThreadExecutor()
        try {
            val evaluation = evaluator.submit<String> { session.evaluate(frame(10.0), diagnostic(10.0)) }
            assertTrue(clock.entered.await(2, TimeUnit.SECONDS))
            callbacks.submit { session.resetTrajectory() }.get(2, TimeUnit.SECONDS)
            clock.resume.countDown()
            val result = Json.parseToJsonElement(evaluation.get(2, TimeUnit.SECONDS)).jsonObject
            assertEquals("trajectory_reset", result.getValue("reason").jsonPrimitive.content)
            assertTrue(result.getValue("associations").jsonArray.isEmpty())
            assertFalse(result.getValue("deadlineExceeded").jsonPrimitive.boolean)
            assertNull(session.overlay())
        } finally {
            clock.resume.countDown(); evaluator.shutdownNow(); callbacks.shutdownNow()
        }
    }

    @Test fun overlayInvalidationCannotBeUndoneByAnEvaluationAlreadyInFlight() {
        val clock = PausedClock()
        val session = RoadPathSession(clock::now)
        val evaluator = Executors.newSingleThreadExecutor()
        val callbacks = Executors.newSingleThreadExecutor()
        try {
            val evaluation = evaluator.submit<String> { session.evaluate(frame(10.0), diagnostic(10.0)) }
            assertTrue(clock.entered.await(2, TimeUnit.SECONDS))
            callbacks.submit { session.invalidateOverlay() }.get(2, TimeUnit.SECONDS)
            clock.resume.countDown()
            val result = Json.parseToJsonElement(evaluation.get(2, TimeUnit.SECONDS)).jsonObject
            assertFalse(result.getValue("deadlineExceeded").jsonPrimitive.boolean)
            assertNull(session.overlay())
            session.evaluate(frame(10.1), diagnostic(10.1))
            assertNotNull(session.overlay())
        } finally {
            clock.resume.countDown(); evaluator.shutdownNow(); callbacks.shutdownNow()
        }
    }
}
