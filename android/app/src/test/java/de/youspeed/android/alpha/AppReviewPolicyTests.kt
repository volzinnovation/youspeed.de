package de.youspeed.android.alpha

import java.time.Instant
import org.junit.Assert.*
import org.junit.Test

class AppReviewPolicyTests {
    private val start = Instant.ofEpochSecond(1_000_000)
    private fun eligible(count: Int = 10, optedOut: Boolean = false, attempted: Boolean = false,
                         version: String = "2", lastVersion: String? = null, lastRequest: Instant? = null,
                         now: Instant = start.plusSeconds(60)): Boolean =
        AppReviewPolicy.isEligible(count, optedOut, attempted, version, lastVersion, lastRequest, start, now)

    @Test fun thresholdAndSessionDelay() {
        var count = 0
        repeat(9) { count = AppReviewPolicy.nextLaunch(count); assertFalse(eligible(count = count)) }
        assertTrue(eligible(count = AppReviewPolicy.nextLaunch(count)))
        assertFalse(eligible(now = start.plusSeconds(59)))
        assertEquals(10, AppReviewPolicy.nextLaunch(Int.MAX_VALUE))
        assertEquals(1, AppReviewPolicy.nextLaunch(-1))
    }

    @Test fun versionCooldownOptOutAndOneAttemptPerLaunch() {
        assertFalse(eligible(lastVersion = "2"))
        assertFalse(eligible(attempted = true))
        assertFalse(eligible(optedOut = true))
        assertFalse(eligible(version = ""))
        assertFalse(eligible(lastRequest = start, now = start.minusSeconds(1)))
        assertFalse(eligible(lastRequest = start, now = start.plusSeconds(AppReviewPolicy.COOLDOWN_SECONDS - 1)))
        assertTrue(eligible(lastRequest = start, lastVersion = "1", now = start.plusSeconds(AppReviewPolicy.COOLDOWN_SECONDS)))
    }

    @Test fun requiresFreshStandstillVisibleButtonsReadyDashboardAndNoInterruptions() {
        fun safe(speed: Double? = 0.0, fix: Instant? = start, tunnel: Boolean = false,
                 buttons: Boolean = true, ready: Boolean = true, active: Boolean = true, interrupted: Boolean = false) =
            AppReviewPolicy.isSafeToRequest(speed, fix, start, tunnel, buttons, ready, active, interrupted)
        assertTrue(safe())
        assertFalse(safe(speed = 1.0))
        assertFalse(safe(speed = null))
        assertFalse(safe(fix = null))
        assertFalse(safe(fix = start.minusSeconds(4)))
        assertFalse(safe(fix = start.plusSeconds(1)))
        assertFalse(safe(tunnel = true))
        assertFalse(safe(buttons = false))
        assertFalse(safe(ready = false))
        assertFalse(safe(active = false))
        assertFalse(safe(interrupted = true))
    }
}
