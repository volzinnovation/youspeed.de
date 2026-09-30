package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class VisualRoadCalibrationTests {
    private val initial = VisualRoadCalibration.defaults(1600,1200,"rear:rotation:90")

    @Test fun allFiveStepsHaveIndependentControlsAndFixedUpperHeight() {
        var draft = initial.adjust(VisualRoadCalibrationStep.HORIZON, 1, -1)
        assertEquals(.415,draft.horizonY,1e-9)
        assertEquals(initial.leftTopX,draft.leftTopX,0.0)
        draft = draft.adjust(VisualRoadCalibrationStep.LEFT_BOTTOM,1,-1)
        assertEquals(LanePoint(.005,.995),draft.leftBottom)
        draft = draft.adjust(VisualRoadCalibrationStep.LEFT_TOP,-1,1)
        assertEquals(.455,draft.leftTopX,1e-9)
        assertEquals(.415,draft.leftTop.y,1e-9)
        draft = draft.adjust(VisualRoadCalibrationStep.RIGHT_BOTTOM,-1,-1)
        assertEquals(LanePoint(.995,.995),draft.rightBottom)
        draft = draft.adjust(VisualRoadCalibrationStep.RIGHT_TOP,1,-1)
        assertEquals(.545,draft.rightTopX,1e-9)
        assertEquals(.415,draft.rightTop.y,1e-9)
        assertEquals(LanePoint(0.0,1.0),initial.leftBottom) // The saved/draft source is not mutated.
    }

    @Test fun persistsNormalizedReferenceAndRejectsCorruptOrUnknownSchema() {
        val saved = initial.copy(revision="mount-1")
        assertEquals(saved,VisualRoadCalibration.decode(saved.encode()))
        assertNull(VisualRoadCalibration.decode(null))
        assertNull(VisualRoadCalibration.decode("{broken"))
        assertNull(VisualRoadCalibration.decode(saved.encode().replace("\"schemaVersion\":1","\"schemaVersion\":2")))
        assertNull(VisualRoadCalibration.decode(saved.copy(leftTopX=Double.NaN).encode()))
    }

    @Test fun calibrationSurvivesResamplingButNotRotationOrDifferentAspectCrop() {
        assertTrue(initial.compatible(800,600,"rear:rotation:90"))
        assertFalse(initial.compatible(1600,1200,"rear:rotation:270"))
        assertFalse(initial.compatible(1280,720,"rear:rotation:90"))
        assertFalse(initial.compatible(0,0,"rear:rotation:90"))
    }

    @Test fun userCropPreservesFullHeightAndRightBoundaryAndRemapsActualRoundedPixels() {
        val reference = initial.copy(leftTopX=.3333)
        assertEquals(533,reference.cropLeftPixels(1600))
        val cropBox = NormalizedTrafficSignBoundingBox(.1,.2,.3,.4)
        val full = reference.fullFrameBox(cropBox,1600)
        assertEquals((533 + .1*1067)/1600,full.x,1e-12)
        assertEquals(.3*1067/1600,full.width,1e-12)
        assertEquals(.2,full.y,0.0); assertEquals(.4,full.height,0.0)
        val complete = reference.fullFrameBox(NormalizedTrafficSignBoundingBox(0.0,0.0,1.0,1.0),1600)
        assertEquals(1.0,complete.x+complete.width,1e-12)
        assertEquals(1.0,complete.height,0.0)
    }

    @Test fun invalidCrossedAndAboveHorizonReferencesCannotBeSaved() {
        assertTrue(initial.isValid)
        assertFalse(initial.copy(leftBottom=LanePoint(.98,1.0)).isValid)
        assertFalse(initial.copy(leftTopX=.6,rightTopX=.4).isValid)
        assertFalse(initial.copy(rightBottom=LanePoint(1.0,.3)).isValid)
        assertFalse(initial.copy(horizonY=Double.POSITIVE_INFINITY).isValid)
        assertFalse(initial.copy(imageWidth=0).isValid)
    }

    @Test fun arrowsStopAtImageBoundsAndLowerPointsCannotCrossHorizon() {
        var draft = initial
        repeat(500) { draft = draft.adjust(VisualRoadCalibrationStep.LEFT_BOTTOM,-1,-1) }
        assertEquals(0.0,draft.leftBottom.x,0.0)
        assertEquals(draft.horizonY+.05,draft.leftBottom.y,1e-9)
        repeat(500) { draft = draft.adjust(VisualRoadCalibrationStep.HORIZON,0,1) }
        assertEquals(initial.horizonY,draft.horizonY,1e-9)
    }
}
