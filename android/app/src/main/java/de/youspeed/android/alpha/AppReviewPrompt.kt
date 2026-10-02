package de.youspeed.android.alpha

import android.content.SharedPreferences
import androidx.activity.ComponentActivity
import androidx.lifecycle.Lifecycle
import com.google.android.play.core.review.ReviewManagerFactory
import java.time.Instant

internal object AppReviewPolicy {
    const val COOLDOWN_SECONDS = 180L * 24 * 60 * 60
    fun isSafeToRequest(speedKmh: Double?, stationaryObservedAt: Instant?, now: Instant,
                        inTunnel: Boolean, buttonsVisible: Boolean, dashboardReady: Boolean,
                        active: Boolean, interrupted: Boolean): Boolean =
        active && dashboardReady && buttonsVisible && !interrupted &&
            GravityAlignmentVisibility.isFreshStationary(speedKmh, stationaryObservedAt, now, inTunnel)
    fun nextLaunch(count: Int): Int = count.coerceIn(0, 10).let { if (it < 10) it + 1 else 10 }
    fun isEligible(count: Int, optedOut: Boolean, attempted: Boolean, version: String,
                   lastVersion: String?, lastRequest: Instant?, startedAt: Instant, now: Instant): Boolean =
        count >= 10 && !optedOut && !attempted && version.isNotEmpty() && version != lastVersion &&
            !now.isBefore(startedAt.plusSeconds(60)) &&
            (lastRequest == null || !now.isBefore(lastRequest.plusSeconds(COOLDOWN_SECONDS)))
}

/** Survives Activity recreation; native completion cannot prove a submitted rating. */
internal class AppReviewPrompt private constructor(private val preferences: SharedPreferences) {
    private val startedAt = Instant.now()
    private var attemptedThisLaunch = false
    init { preferences.edit().putInt(LAUNCH_COUNT, AppReviewPolicy.nextLaunch(preferences.getInt(LAUNCH_COUNT, 0))).apply() }

    fun isEligible(now: Instant): Boolean = AppReviewPolicy.isEligible(
        preferences.getInt(LAUNCH_COUNT, 0), preferences.getBoolean(RATED, false), attemptedThisLaunch,
        BuildConfig.VERSION_NAME, preferences.getString(LAST_VERSION, null),
        if (preferences.contains(LAST_REQUEST)) Instant.ofEpochMilli(preferences.getLong(LAST_REQUEST, 0)) else null,
        startedAt, now,
    )

    fun request(activity: ComponentActivity, isSafe: () -> Boolean) {
        if (!isEligible(Instant.now()) || !isSafe()) return
        attemptedThisLaunch = true
        val manager = ReviewManagerFactory.create(activity)
        manager.requestReviewFlow().addOnCompleteListener { task ->
            // Recheck after asynchronous Play preparation: the car may have moved,
            // a sheet may have opened or the Activity may have been backgrounded.
            if (!task.isSuccessful || activity.isFinishing || activity.isDestroyed ||
                !activity.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED) || !isSafe()) return@addOnCompleteListener
            preferences.edit().putString(LAST_VERSION, BuildConfig.VERSION_NAME)
                .putLong(LAST_REQUEST, Instant.now().toEpochMilli()).apply()
            manager.launchReviewFlow(activity, task.result)
            // No rating flag and no store-link fallback: errors/quota are silent.
        }
    }

    companion object {
        private const val LAUNCH_COUNT = "youspeed.review.launch_count"
        private const val RATED = "youspeed.review.user_confirmed_rated"
        private const val LAST_VERSION = "youspeed.review.last_requested_version"
        private const val LAST_REQUEST = "youspeed.review.last_requested_at"
        private var currentLaunch: AppReviewPrompt? = null
        fun forLaunch(preferences: SharedPreferences): AppReviewPrompt =
            currentLaunch ?: AppReviewPrompt(preferences).also { currentLaunch = it }
    }
}
