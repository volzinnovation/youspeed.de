package de.youspeed.android.alpha

import java.io.File
import java.util.Locale
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.*
import org.junit.Test

/** The deployed vocabulary and mappings must agree on the actual 142 outputs. */
class ExpandedDEClassifierTests {
    private val root = listOf(File("../.."), File(".."), File(".")).first { File(it, "shared/tsr").isDirectory }
    private val source = Json.parseToJsonElement(File(root, "shared/tsr/prolix-de-class-catalog-v1.json").readText()).jsonObject

    @Test fun exactCurveBoardUsesSharedInventoryArtworkWithoutInferringCameraDirection() {
        val catalog = TrafficSignDisplayCatalog.decode(source.toString(), "DE")
        val record = source.getValue("signs").jsonArray.map { it.jsonObject }
            .first { it.getValue("class_id").jsonPrimitive.content == "DE:625-20" }
        val path = record.getValue("image_path").jsonPrimitive.content
        assertEquals("tsr/sign-pictograms/png/de-625-20.png", path)
        assertTrue(File(root, "shared/$path").isFile)
        assertEquals("Richtungstafel in Kurven – rechtsweisend",
            record.getValue("label").jsonObject.getValue("de").jsonPrimitive.content)
        assertFalse(catalog.classLabels.contains("DE:625-20"))
        assertNull(catalog.pictogram("DE:625-20"))
        assertNull(catalog.pictogram("arrow:red"))
        val inventory = InventorySign("curve", "mobidata-bw-vzk", "curve", "a".repeat(64),
            "DE:625-20", "secondary", null, null, "not_applicable", 48.0, 8.0, 30.0, path, emptySet())
        assertEquals(path, inventory.pictogram(catalog)?.imagePath)
    }

    @Test fun bundledClassifierSupportsNewArtworkAndKeepsPlateContentUnresolved() {
        val candidate = TrafficSignDisplayCatalog.decode(source.toString(), "DE")
        assertEquals(142, candidate.classLabels.size)
        assertEquals(listOf("city:start", "city:end", "bus:stop", "supplementary:plate", "maxspeed:90",
            "DE:156-10", "DE:325.1", "DE:325.2"), candidate.classLabels.drop(134))
        assertEquals("bus:stop", candidate.classId(136))
        assertEquals("supplementary:plate", candidate.classId(137))
        assertEquals("tsr/sign-pictograms/png/de-224.png", candidate.pictogram("bus:stop")?.imagePath)
        assertEquals("Haltestelle", candidate.pictogram("bus:stop")?.label(Locale.GERMAN))
        assertEquals("tsr/sign-pictograms/png/de-274-90.png", candidate.pictogram("maxspeed:90")?.imagePath)
        assertNull(candidate.pictogram("supplementary:plate"))
        assertNull(candidate.pictogram("exit")) // A diversion family does not determine its arrow.
        assertNull(candidate.pictogram("lanes")) // A lane family does not determine shoulder permission.
    }

    @Test fun genericPlateMappingUsesExistingSupplementaryRoleWithoutInventingRestriction() {
        val pack = TrafficSignModelPackJson.decode(File(root,
            "android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/manifest.json").readText())
        assertTrue(TrafficSignModelPackValidator.validate(pack).isEmpty())
        assertEquals(142, pack.classMapping.size)
        val mapping = pack.classMapping.single { it.classId == "supplementary:plate" }
        assertEquals(TrafficSignRole.SUPPLEMENTARY_PLATE, mapping.signRole)
        assertEquals(TrafficSignSemanticKind.UNKNOWN, mapping.semantic.kind)
        assertNull(mapping.semantic.value)
        assertEquals("unknown", mapping.restriction?.kind?.wireValue)
        assertEquals("unresolved", mapping.restriction?.normalizedValue)
        assertNull(mapping.restriction?.rawText)
        assertNull(mapping.restriction?.countrySignCode)
    }
}
