package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class DriveCameraGraphPlanTests {
    private fun outputs(plan: DriveCameraGraphPlan) = plan.bindOrder("preview", "analysis", "photo", "movie")

    @Test fun standaloneRecognitionHasARepeatingSurfaceWithoutARecorder() {
        val standalone = DriveCameraGraphPlan.resolve(recorderRequested = false, photosRequested = false)
        assertEquals(listOf("preview", "analysis"), outputs(standalone))
    }

    @Test fun automaticPhotosKeepTheSameRecognitionSourceWithoutAMovie() {
        val photos = DriveCameraGraphPlan.resolve(recorderRequested = false, photosRequested = true)
        assertEquals(listOf("preview", "photo", "analysis"), outputs(photos))
        assertEquals(photos, DriveCameraGraphPlan.resolve(false, false, photos))
    }

    @Test fun manualReadinessReservesStillOutputBeforeMovieStartAndNeverRebindsForATap() {
        val manualOnly = DriveCameraGraphPlan.resolve(recorderRequested = false, photosRequested = true)
        assertEquals(listOf("preview", "photo", "analysis"), outputs(manualOnly))
        val recording = DriveCameraGraphPlan.resolve(true, true, manualOnly)
        assertEquals(recording, DriveCameraGraphPlan.resolve(true, true, recording))
        assertEquals(recording, DriveCameraGraphPlan.resolve(true, false, recording))
    }

    @Test fun unsupportedOptionalStillOutputKeepsMovieAndAnalysisConsumers() {
        val recording = DriveCameraGraphPlan.resolve(true, true)
        val fallback = requireNotNull(recording.withoutOptionalManualPhoto(automaticPhotosEnabled = false))
        assertEquals(listOf("preview", "movie", "analysis"), outputs(fallback))
        assertNull(recording.withoutOptionalManualPhoto(automaticPhotosEnabled = true))
        assertNull(fallback.withoutOptionalManualPhoto(automaticPhotosEnabled = false))
    }

    @Test fun startingAndStoppingMoviesPreservesTheRepeatingAnalysisGraph() {
        val standalone = DriveCameraGraphPlan.resolve(false, false)
        val recording = DriveCameraGraphPlan.resolve(true, false, standalone)
        assertEquals(listOf("preview", "photo", "movie", "analysis"), outputs(recording))
        assertEquals(recording, DriveCameraGraphPlan.resolve(false, false, recording))
        assertEquals(recording, DriveCameraGraphPlan.resolve(false, true, recording))
        // A fresh session must not inherit the previous session's encoder/stills.
        assertEquals(listOf("preview", "analysis"), outputs(DriveCameraGraphPlan.resolve(false, false)))
    }
}
