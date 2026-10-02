package de.youspeed.android.alpha

import java.io.File
import java.nio.file.Files
import org.junit.Assert.*
import org.junit.Test

class DebugLogPersistenceTests {
    @Test fun enabledByDefaultAndOffSkipsCreationAndPreservesExistingLogs() {
        val root = Files.createTempDirectory("debug-logging").toFile()
        try {
            val gate = DebugLogPersistence()
            val log = File(root, "debug.log")
            gate.write { log.appendText("enabled\n") }
            gate.setEnabled(false)
            gate.write { log.appendText("disabled\n") }
            gate.write { File(root, "new.log").writeText("disabled") }
            assertEquals("enabled\n", log.readText())
            assertFalse(File(root, "new.log").exists())
            gate.setEnabled(true)
            gate.write { log.appendText("resumed\n") }
            assertEquals("enabled\nresumed\n", log.readText())
        } finally { root.deleteRecursively() }
    }

    @Test fun queuedWritesCannotResumeAfterSwitchingOffAndBackOn() {
        val gate = DebugLogPersistence()
        val queued = gate.ticket()
        gate.setEnabled(false)
        assertNull(gate.ticket())
        gate.write(queued) { fail("Persisted a queued log while disabled") }
        gate.setEnabled(true)
        gate.write(queued) { fail("Replayed an obsolete log after re-enabling") }
        var wrote = false
        gate.write { wrote = true }
        assertTrue(wrote)
    }

    @Test fun savedOffStatePreventsStartupLogCreation() {
        val gate = DebugLogPersistence(initiallyEnabled = false)
        gate.write { fail("Created startup logs with logging disabled") }
        assertNull(gate.ticket())
    }
}
