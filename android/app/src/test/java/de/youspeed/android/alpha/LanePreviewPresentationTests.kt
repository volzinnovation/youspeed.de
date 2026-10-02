package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class LanePreviewPresentationTests {
    private val matrix = listOf(1.0,0.0,0.0,0.0,1.0,0.0,0.0,0.0,1.0)
    private val source = LanePreviewSourceGeometry(7, LaneImageGeometry(1600,1200,180,matrix),10_000_000_000L,false)
    private val calibration = VisualRoadCalibration("saved",1920,1440,"rear:rotation:180",.525,
        LanePoint(0.0,.915),.43,LanePoint(.8,.965),.47)
    private fun decision(source: LanePreviewSourceGeometry? = this.source, scope: Long = 7,
        calibration: VisualRoadCalibration? = this.calibration, count: Int = 0, stale: Boolean = false,
        now: Long = 10_100_000_000L, enabled: Boolean = true, visible: Boolean = true, active: Boolean = true) =
        LanePreviewPresentationPolicy.decide(enabled,visible,active,scope,source,calibration,count,stale,now)

    @Test fun contextGapUsesExactlyTwoFaintSavedGuidesWithoutHorizonOrInventedEvidence() {
        val result = decision(stale = true)
        assertEquals(LanePreviewPresentationMode.CALIBRATION_REFERENCE,result.mode)
        assertEquals("stale_context",result.reason)
        assertEquals(.28f,result.referenceOpacity)
        assertEquals(listOf(listOf(calibration.leftBottom,calibration.leftTop),
            listOf(calibration.rightBottom,calibration.rightTop)),result.referenceLines)
    }

    @Test fun TentativeOrEmptyCurrentFrameFallsBackButMatureObservationWins() {
        assertEquals(LanePreviewPresentationMode.CALIBRATION_REFERENCE,decision().mode)
        val detected = decision(count = 1)
        assertEquals(LanePreviewPresentationMode.OBSERVED,detected.mode)
        assertTrue(detected.referenceLines.isEmpty())
        assertEquals(LanePreviewPresentationMode.OBSERVED,decision(count = 1,calibration = null).mode)
    }

    @Test fun realFourByThreeCalibrationScalesButRejectsVideoCropAndRotationMismatch() {
        assertEquals(LanePreviewPresentationMode.CALIBRATION_REFERENCE,decision().mode)
        assertEquals("calibration_geometry_incompatible",decision(source.copy(geometry = source.geometry.copy(width=1280,height=720))).reason)
        assertEquals("calibration_geometry_incompatible",decision(source.copy(geometry = source.geometry.copy(rotationDegrees=0))).reason)
        assertEquals("calibration_unavailable",decision(calibration = null).reason)
    }

    @Test fun sourceExpiryScopeAndLifecycleHideAllOverlaysIncludingMatureDetections() {
        val hidden = listOf(decision(source = null,count = 2),decision(scope = 8,count = 2),
            decision(now = 10_750_000_001L,count = 2),decision(now = 9_999_999_999L,count = 2),
            decision(source.copy(thermalPaused = true),count = 2),decision(enabled = false,count = 2),
            decision(visible = false,count = 2),decision(active = false,count = 2))
        hidden.forEach { assertEquals(LanePreviewPresentationMode.HIDDEN,it.mode); assertTrue(it.referenceLines.isEmpty()) }
    }

    @Test fun fallbackUsesRealSensorToPreviewCropRatherThanVideoAspectAssumption() {
        val src = source.copy(geometry = source.geometry.copy(rotationDegrees=0))
        val profile = calibration.copy(orientationKey="rear:rotation:0")
        val preview = LanePreviewGeometry(1600,900,0,0,1600,900,0,false,
            listOf(1.0,0.0,0.0,0.0,1.0,-150.0,0.0,0.0,1.0),1600,900)
        val point = decision(src,calibration=profile).referenceLines[0][1]
        val projected = requireNotNull(LaneOverlayGeometry.project(point,src.geometry,preview))
        assertEquals(688.0,projected.x,1e-9)
        assertEquals(480.0,projected.y,1e-9)
    }
    @Test fun referenceWaitsAfterObservedLossAndResetsWithCameraScope() {
        val h=LaneReferenceHysteresis()
        val reference=LanePreviewPresentationDecision(LanePreviewPresentationMode.CALIBRATION_REFERENCE,"fixture",emptyList())
        val observed=LanePreviewPresentationDecision(LanePreviewPresentationMode.OBSERVED,"fixture",emptyList())
        assertEquals(LanePreviewPresentationMode.HIDDEN,h.apply(reference,"a",10.0).mode)
        assertEquals(LanePreviewPresentationMode.CALIBRATION_REFERENCE,h.apply(reference,"a",11.1).mode)
        assertEquals(LanePreviewPresentationMode.OBSERVED,h.apply(observed,"a",11.2).mode)
        assertEquals(LanePreviewPresentationMode.HIDDEN,h.apply(reference,"a",12.9).mode)
        assertEquals(LanePreviewPresentationMode.CALIBRATION_REFERENCE,h.apply(reference,"a",13.3).mode)
        assertEquals(LanePreviewPresentationMode.HIDDEN,h.apply(reference,"b",13.4).mode)
    }
}
