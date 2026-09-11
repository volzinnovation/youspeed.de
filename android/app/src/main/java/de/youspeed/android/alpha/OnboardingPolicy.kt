package de.youspeed.android.alpha

/** First-run setup is durable and depends on a real downloaded map, never its age. */
internal object OnboardingPolicy {
    const val LAST_STEP = 4
    const val COMPLETED_KEY = "youspeed.onboarding.completed"
    const val STEP_KEY = "youspeed.onboarding.step"

    fun migrateCompletion(stored: Boolean?, hasUsableMap: Boolean): Boolean = stored ?: hasUsableMap

    fun hasUsableMap(bundleVersion: String, databaseExists: Boolean): Boolean =
        databaseExists && bundleVersion.trim().lowercase() !in setOf("", "none", "seed")

    fun requiresSetup(completed: Boolean, hasUsableMap: Boolean): Boolean = !completed || !hasUsableMap

    fun resumedStep(savedStep: Int, hasUsableMap: Boolean): Int =
        if (hasUsableMap) savedStep.coerceIn(0, LAST_STEP) else 0

    fun canAdvance(step: Int, hasUsableMap: Boolean, preciseLocationGranted: Boolean): Boolean = when (step) {
        0 -> hasUsableMap
        1 -> hasUsableMap && preciseLocationGranted
        2, 3 -> hasUsableMap
        LAST_STEP -> hasUsableMap && preciseLocationGranted
        else -> false
    }
}
