package de.youspeed.android.alpha

import java.io.File
import org.junit.Assert.*
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test

class AttributionCatalogTests {
    private val shared = listOf(File("../../shared"), File("../shared"), File("shared")).first(File::isDirectory)
    private val raw get() = File(shared, AttributionCatalog.ASSET_PATH).readText()

    @Test fun shippedCatalogCreditsEveryPictogramAndIncludesRequiredOfflineNotices() {
        val catalog = AttributionCatalog.decode(raw)
        val signIds = catalog.entries.filter { it.category == "sign" && it.id.startsWith("sign-DE:") }
        val artworkIds = Json.parseToJsonElement(File(shared, "tsr/sign-pictograms/manifest.json").readText())
            .jsonObject.getValue("artworks").jsonArray.map { "sign-" + it.jsonObject.getValue("sign_code").jsonPrimitive.content }.toSet()
        assertTrue("Every shipped pictogram needs an attribution", artworkIds.isNotEmpty())
        assertEquals(artworkIds, signIds.map { it.id }.toSet())
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
