package de.youspeed.android.alpha

import java.io.File
import org.junit.Assert.*
import org.junit.Test

class AttributionCatalogTests {
    private val shared = listOf(File("../../shared"), File("../shared"), File("shared")).first(File::isDirectory)
    private val raw get() = File(shared, AttributionCatalog.ASSET_PATH).readText()

    @Test fun shippedCatalogCreditsEveryPictogramAndIncludesRequiredOfflineNotices() {
        val catalog = AttributionCatalog.decode(raw)
        val signIds = catalog.entries.filter { it.category == "sign" && it.id.startsWith("sign-DE:") }
        assertEquals(104, signIds.size)
        assertTrue(catalog.entries.any { it.category == "data" })
        assertTrue(catalog.entries.any { it.category == "model" })
        assertTrue(catalog.entries.any { it.category == "software" })
        val localAssets = listOf(File("src/main/assets"), File("app/src/main/assets"), File("android/app/src/main/assets")).first(File::isDirectory)
        for (path in AttributionCatalog.NOTICE_PATHS) {
            val file = listOf(File(shared, path), File(localAssets, path)).first(File::isFile)
            assertTrue("Empty notice: $path", file.readText().isNotBlank())
        }
    }

    @Test fun invalidSchemaAndDuplicateEntriesCannotSilentlyHideCredits() {
        assertThrows(IllegalArgumentException::class.java) { AttributionCatalog.decode(fixture(schema = 2)) }
        assertThrows(IllegalArgumentException::class.java) { AttributionCatalog.decode(fixture(duplicate = true)) }
        assertThrows(IllegalArgumentException::class.java) { AttributionCatalog.decode(fixture(source = "file:///private/source")) }
    }

    private fun fixture(schema: Int = 1, duplicate: Boolean = false, source: String = "https://example.org/source"): String {
        val entry = """{"id":"test","title":"Test","attribution":"Author","license":"MIT","source_url":"$source","license_url":"https://example.org/license","changes":"None","category":"software"}"""
        return """{"schema_version":$schema,"reviewed_at":"2026-09-10","entries":[$entry${if (duplicate) ",$entry" else ""}]}"""
    }
}
