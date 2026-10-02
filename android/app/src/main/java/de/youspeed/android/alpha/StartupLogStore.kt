package de.youspeed.android.alpha

import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS

enum class StartupLogReviewState { CHECKING, CHOICE, CLEARING, FAILED, COMPLETE }

/** Only app-owned logs are cleared; maps, observations and captures are excluded. */
internal object StartupLogStore {
    const val THRESHOLD_BYTES = 100_000_000L

    fun requiresReview(bytes: Long) = bytes > THRESHOLD_BYTES

    fun files(directory: File): List<File> {
        if (!directory.exists()) return emptyList()
        return (directory.listFiles() ?: throw IOException("Cannot list log directory")).filter { file ->
            val name = file.name
            (name == "gps_fix_log.csv" || name == "drive_match_log.ndjson" ||
                name == "runtime_diagnostics.ndjson" || name == "tsr_log.ndjson" ||
                name.endsWith("_drive_match_log.ndjson") || name.endsWith("_tsr_log.ndjson")) &&
                Files.isRegularFile(file.toPath(), NOFOLLOW_LINKS)
        }
    }

    fun totalBytes(directory: File): Long = files(directory).sumOf { Files.size(it.toPath()) }

    fun clear(directory: File) {
        files(directory).forEach { Files.delete(it.toPath()) }
    }
}
