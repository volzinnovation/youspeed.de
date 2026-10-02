package de.youspeed.android.alpha

/** Switching off waits for active writes and invalidates queued log work. */
internal class DebugLogPersistence(initiallyEnabled: Boolean = true) {
    private val lock = Any()
    private var enabled = initiallyEnabled
    private var generation = 0L

    fun setEnabled(value: Boolean) = withLock {
        if (enabled != value) {
            enabled = value
            generation++
        }
    }

    fun ticket(): Long? = withLock { generation.takeIf { enabled } }

    fun <T> withLock(action: () -> T): T = synchronized(lock) { action() }

    fun <T> write(ticket: Long? = ticket(), action: () -> T): T? = withLock {
        if (enabled && ticket == generation) action() else null
    }

    companion object { const val PREFERENCE_KEY = "youspeed.debug.logging_enabled" }
}
