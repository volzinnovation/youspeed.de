package de.youspeed.android.alpha

import java.io.File

/** Optional export location for cross-platform contract checks; defaults to this JVM's writable temp root. */
internal fun signCollectionTestOutputDirectory(): File {
    val configured = System.getenv("YOUSPEED_COLLECTION_TEST_OUTPUT")?.takeIf { it.isNotBlank() }
    val output = configured?.let(::File) ?: File(System.getProperty("java.io.tmpdir"), "youspeed-collection-results")
    check(output.isDirectory || output.mkdirs()) { "Cannot create collection test output directory: $output" }
    return output
}
