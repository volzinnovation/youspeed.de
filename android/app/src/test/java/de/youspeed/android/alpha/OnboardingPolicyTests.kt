package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class OnboardingPolicyTests {
    @Test fun migrationOnlyCompletesExistingUsableMapInstallations() {
        assertTrue(OnboardingPolicy.migrateCompletion(null, hasUsableMap = true))
        assertFalse(OnboardingPolicy.migrateCompletion(null, hasUsableMap = false))
        // A new installation's first successful download must not become a migration.
        assertFalse(OnboardingPolicy.migrateCompletion(false, hasUsableMap = true))
        assertTrue(OnboardingPolicy.migrateCompletion(true, hasUsableMap = true))
    }

    @Test fun seedAndMissingDatabaseCannotSatisfyTheRequiredDownload() {
        for (version in listOf("", "none", "seed", " SEED ")) {
            assertFalse(version, OnboardingPolicy.hasUsableMap(version, databaseExists = true))
        }
        assertFalse(OnboardingPolicy.hasUsableMap("2026-09-11", databaseExists = false))
        assertTrue(OnboardingPolicy.hasUsableMap("2026-09-11", databaseExists = true))
    }

    @Test fun existingMapAgeDoesNotRepeatSetup() {
        val usableOldMap = OnboardingPolicy.hasUsableMap("2020-01-01", databaseExists = true)
        assertFalse(OnboardingPolicy.requiresSetup(completed = true, hasUsableMap = usableOldMap))
        assertTrue(OnboardingPolicy.requiresSetup(completed = false, hasUsableMap = usableOldMap))
        assertTrue(OnboardingPolicy.requiresSetup(completed = true, hasUsableMap = false))
    }

    @Test fun resumePreservesProgressButMapRemovalReturnsToDownload() {
        assertEquals(3, OnboardingPolicy.resumedStep(3, hasUsableMap = true))
        assertEquals(0, OnboardingPolicy.resumedStep(4, hasUsableMap = false))
        assertEquals(0, OnboardingPolicy.resumedStep(-10, hasUsableMap = true))
        assertEquals(4, OnboardingPolicy.resumedStep(999, hasUsableMap = true))
    }

    @Test fun everyStepRequiresAMapAndDrivingAndFinishRequirePreciseLocation() {
        for (step in 0..4) {
            assertFalse("step $step without a map", OnboardingPolicy.canAdvance(step, false, true))
            assertTrue("step $step with required setup", OnboardingPolicy.canAdvance(step, true, true))
        }
        assertTrue(OnboardingPolicy.canAdvance(0, true, false))
        assertFalse(OnboardingPolicy.canAdvance(1, true, false))
        assertTrue(OnboardingPolicy.canAdvance(2, true, false))
        assertTrue(OnboardingPolicy.canAdvance(3, true, false))
        assertFalse(OnboardingPolicy.canAdvance(4, true, false))
        assertFalse(OnboardingPolicy.canAdvance(5, true, true))
    }

    @Test fun onboardingKeepsCurrentOptionalFeatureDefaults() {
        val state = ConsumerUiState()
        assertTrue(state.audioAlertsEnabled)
        assertEquals(8, state.audioAlertThresholdKmh)
        assertFalse(state.trafficSignRecognitionEnabled)
        assertFalse(state.trafficSignRecognitionIndependentEnabled)
        assertTrue(state.panoramaxCaptureEnabled)
        assertFalse(state.onboardingCompleted)
        assertEquals(0, state.onboardingStep)
    }
}
