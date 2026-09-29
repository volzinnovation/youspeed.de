package de.youspeed.android.alpha

import java.io.File
import java.io.RandomAccessFile
import java.nio.file.Files
import org.junit.Assert.*
import org.junit.Test

class StartupLogStoreTests {
    @Test fun thresholdUsesCombinedBytesAndRequiresStrictlyMoreThan100MB() = withDirectory { root ->
        val gps = File(root, "gps_fix_log.csv")
        val archived = File(root, "20260928_120000_drive_match_log.ndjson")
        RandomAccessFile(gps, "rw").use { it.setLength(60_000_000) }
        RandomAccessFile(archived, "rw").use { it.setLength(39_999_999) }
        assertFalse(StartupLogStore.requiresReview(StartupLogStore.totalBytes(root)))
        archived.appendText("x")
        assertEquals(100_000_000L, StartupLogStore.totalBytes(root))
        assertFalse(StartupLogStore.requiresReview(StartupLogStore.totalBytes(root)))
        archived.appendText("x")
        assertTrue(StartupLogStore.requiresReview(StartupLogStore.totalBytes(root)))
        // Checking (and choosing to keep) must preserve every byte.
        assertEquals(60_000_000L, gps.length())
        assertEquals(40_000_001L, archived.length())
    }

    @Test fun clearIncludesAllLogSessionsAndPreservesOtherFilesAndSymlinks() = withDirectory { root ->
        listOf("gps_fix_log.csv", "drive_match_log.ndjson", "runtime_diagnostics.ndjson",
            "tsr_log.ndjson", "20260928_120000_drive_match_log.ndjson", "20260928_120000_tsr_log.ndjson")
            .forEach { File(root, it).writeText("saved log") }
        val map = File(root, "speeds_v3.sqlite").apply { writeText("map") }
        val photos = File(root, "photos").apply { mkdir() }
        File(photos, "photo.jpg").writeText("photo")
        val link = File(root, "linked_tsr_log.ndjson")
        Files.createSymbolicLink(link.toPath(), map.toPath())
        assertEquals(54L, StartupLogStore.totalBytes(root))
        StartupLogStore.clear(root)
        assertEquals(0L, StartupLogStore.totalBytes(root))
        assertEquals("map", map.readText())
        assertEquals("photo", File(photos, "photo.jpg").readText())
        assertTrue(Files.isSymbolicLink(link.toPath()))
        ConsumerSessionController.prepareDrivingLogFiles(File(root, "gps_fix_log.csv"), File(root, "drive_match_log.ndjson"))
        assertTrue(File(root, "gps_fix_log.csv").readText().startsWith("fix_id,timestamp_utc,"))
    }

    @Test fun absentDirectoryIsEmptyButInvalidDirectoryReportsFailure() = withDirectory { root ->
        assertEquals(0L, StartupLogStore.totalBytes(File(root, "missing")))
        val invalid = File(root, "invalid").apply { writeText("file") }
        assertThrows(java.io.IOException::class.java) { StartupLogStore.totalBytes(invalid) }
        assertThrows(java.io.IOException::class.java) { StartupLogStore.clear(invalid) }
    }

    private fun withDirectory(test: (File) -> Unit) {
        val root = Files.createTempDirectory("startup-logs").toFile()
        try { test(root) } finally { root.deleteRecursively() }
    }
}
