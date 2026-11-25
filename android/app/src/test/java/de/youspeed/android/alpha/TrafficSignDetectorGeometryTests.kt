package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TrafficSignDetectorGeometryTests {
    @Test fun classifierCropChecksAspectInSourcePixelsAndCentersContent() {
        val boundary = NormalizedTrafficSignBoundingBox(0.25, 0.25, 0.2, 0.5)
        assertNull(TrafficSignClassifierGeometry.from(boundary.copy(width = 79.0 / 400), 400, 200))
        val accepted = requireNotNull(TrafficSignClassifierGeometry.from(boundary, 400, 200))
        assertEquals(100.0, accepted.sourceLeft, 1e-9)
        assertEquals(50.0, accepted.sourceTop, 1e-9)
        assertEquals(2.24, accepted.scale, 1e-9)
        assertEquals(179.2, accepted.scaledWidth, 1e-9)
        assertEquals(224.0, accepted.scaledHeight, 1e-9)
        assertEquals(22.4, accepted.left, 1e-9)
        assertEquals(0.0, accepted.top, 1e-9)

        val wide = requireNotNull(TrafficSignClassifierGeometry.from(boundary.copy(width = 0.5), 400, 200))
        assertEquals(1.12, wide.scale, 1e-9)
        assertEquals(224.0, wide.scaledWidth, 1e-9)
        assertEquals(112.0, wide.scaledHeight, 1e-9)
        assertEquals(0.0, wide.left, 1e-9)
        assertEquals(56.0, wide.top, 1e-9)
    }

    @Test fun townTrialSkipsUndersizedCropsBeforeClassification() {
        val atLeast32 = NormalizedTrafficSignBoundingBox(0.2, 0.3, 64.0 / 1920, 32.0 / 1080)
        assertEquals(true, GermanTownTrialOperatingPoint.readable(atLeast32, 1920, 1080))
        assertEquals(false, GermanTownTrialOperatingPoint.readable(atLeast32.copy(height = 31.0 / 1080), 1920, 1080))
        assertEquals(false, GermanTownTrialOperatingPoint.readable(atLeast32.copy(width = 31.0 / 1920), 1920, 1080))
    }

    @Test fun earlyExitFaceCheckIsLimitedToTheNewDetectorBand() {
        with(GermanTownTrialOperatingPoint) {
            assertEquals(false, requiresExitFaceFirst(0.699999))
            assertEquals(true, requiresExitFaceFirst(0.70))
            assertEquals(true, requiresExitFaceFirst(0.840782))
            assertEquals(false, requiresExitFaceFirst(0.840783))
            assertEquals(false, requiresExitFaceFirst(1.0))
        }
    }

    @Test fun onlyTownExitCanUseTheLowerDetectorFloor() {
        with(GermanTownTrialOperatingPoint) {
            assertEquals(true, admit(0.70, "city:end", 0.45))
            assertEquals(false, admit(0.699, "city:end", 0.99))
            assertEquals(false, admit(0.75, "city:end", 0.449))
            assertEquals(false, admit(0.839, "city:start", 0.99))
            assertEquals(false, admit(0.839, "maxspeed:50", 0.99))
            assertEquals(true, admit(0.840783, "city:start", 0.99))
        }
    }

    @Test fun twoEdgeWindowsMapOverlapToOneSourceBox() {
        val windows = TrafficSignDetectorWindow.twoEdges(1920, 1080)
        assertEquals(listOf(0, 840), windows.map { it.left })
        val leftBox = windows[0].sourceBox(NormalizedTrafficSignBoundingBox(900.0 / 1080, .2, .05, .1), 1920)
        val rightBox = windows[1].sourceBox(NormalizedTrafficSignBoundingBox(60.0 / 1080, .2, .05, .1), 1920)
        assertEquals(leftBox.x, rightBox.x, 1e-9)
        val merged = AndroidYoloSignDecoder.merge(listOf(AndroidYoloProposal(.9f, leftBox), AndroidYoloProposal(.85f, rightBox)))
        assertEquals(1, merged.size)
        assertEquals(.9f, merged.single().score)
    }

    @Test fun portraitUsesOnePassAndUltraWideRetainsCenterCoverage() {
        assertEquals(1, TrafficSignDetectorWindow.twoEdges(1080, 1920).size)
        assertEquals(1, TrafficSignDetectorWindow.twoEdges(1080, 1080).size)
        val wide = TrafficSignDetectorWindow.twoEdges(3000, 1000)
        assertEquals(listOf(0, 2000, 0), wide.map { it.left })
        assertEquals(3000, wide.last().width)
    }

    @Test fun landscapeResolutionsFitTheFullFrame() {
        for ((width, height) in listOf(3840 to 2160, 1920 to 1080, 1280 to 720, 640 to 360)) {
            val geometry = TrafficSignDetectorGeometry(width, height)
            assertEquals(1024.0, geometry.scaledWidth, 1e-9)
            assertEquals(576.0, geometry.scaledHeight, 1e-9)
            assertEquals(0.0, geometry.left, 1e-9)
            assertEquals(224.0, geometry.top, 1e-9)
        }
    }

    @Test fun squareAndPortraitRemainUndistortedAndCentered() {
        assertEquals(0.0, TrafficSignDetectorGeometry(1024, 1024).left, 0.0)
        val portrait = TrafficSignDetectorGeometry(640, 1280)
        assertEquals(0.8, portrait.scale, 0.0)
        assertEquals(512.0, portrait.scaledWidth, 0.0)
        assertEquals(256.0, portrait.left, 0.0)
        assertEquals(0.0, portrait.top, 0.0)
    }

    @Test(expected = IllegalArgumentException::class)
    fun invalidDimensionsAreRejected() { TrafficSignDetectorGeometry(0, 1080) }
}
