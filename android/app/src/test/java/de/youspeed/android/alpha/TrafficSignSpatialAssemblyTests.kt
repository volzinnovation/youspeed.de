package de.youspeed.android.alpha

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TrafficSignSpatialAssemblyTests {
    @Test
    fun plateBelowPrimaryBecomesTypedRestrictionOnOneAssembly() {
        val pack = packWithWetPlate()
        val primary = detection("speed_limit_30", box(0.45, 0.20, 0.10, 0.12))
        val wetPlate = detection("plate_wet", box(0.44, 0.34, 0.12, 0.05))

        val result = TrafficSignSpatialAssembly.assemble(
            detections = listOf(primary, wetPlate),
            modelPack = pack,
            assemblyIdPrefix = "frame-42",
        )

        val assembly = result.assemblies.single()
        assertEquals("frame-42-assembly-1", assembly.assemblyId)
        assertEquals(TrafficSignConditionState.RESOLVED, assembly.conditionState)
        assertEquals("wet", assembly.restrictions.single().normalizedValue)
        assertEquals("DE:1053-35", assembly.restrictions.single().countrySignCode)
        assertEquals(assembly.assemblyId, assembly.primary.candidate.assemblyId)
        assertEquals(assembly.restrictions, assembly.primary.candidate.restrictions)
        assertEquals(assembly.assemblyId, assembly.supplementaryPlates.single().candidate.assemblyId)
        assertTrue(result.unassignedSupplementaryPlates.isEmpty())
    }

    @Test
    fun unassignedSidePlateConservativelyMarksPrimaryUnresolved() {
        val pack = packWithWetPlate()
        val primary = detection("speed_limit_30", box(0.70, 0.20, 0.10, 0.12))
        val sidePlate = detection("plate_wet", box(0.10, 0.34, 0.12, 0.05))

        val result = TrafficSignSpatialAssembly.assemble(
            detections = listOf(primary, sidePlate),
            modelPack = pack,
            assemblyIdPrefix = "frame-43",
        )

        val assembly = result.assemblies.single()
        assertEquals(TrafficSignConditionState.UNRESOLVED, assembly.conditionState)
        assertEquals(TrafficSignConditionState.UNRESOLVED, assembly.primary.candidate.conditionState)
        assertTrue(assembly.restrictions.isEmpty())
        assertTrue(assembly.primary.candidate.restrictions.isEmpty())
        assertEquals(listOf(sidePlate), result.unassignedSupplementaryPlates)
    }

    @Test
    fun plateSelectsNearestPlausiblePrimaryWhenTwoAreVisible() {
        val pack = packWithWetPlate()
        val left = detection("speed_limit_30", box(0.25, 0.15, 0.10, 0.12))
        val right = detection("speed_limit_30", box(0.55, 0.18, 0.10, 0.12))
        val plate = detection("plate_wet", box(0.54, 0.32, 0.12, 0.05))

        val assemblies = TrafficSignSpatialAssembly.assemble(
            detections = listOf(left, right, plate),
            modelPack = pack,
            assemblyIdPrefix = "frame-44",
        ).assemblies

        assertTrue(assemblies[0].restrictions.isEmpty())
        assertEquals("wet", assemblies[1].restrictions.single().normalizedValue)
    }

    private fun packWithWetPlate(): TrafficSignModelPack {
        val base = fixture("de-direct-pack-v1.json").readText().let(TrafficSignModelPackJson::decode)
        val restriction = TrafficSignRestriction(
            kind = TrafficSignRestrictionKind.WEATHER,
            normalizedValue = "wet",
            rawText = "bei Nässe",
            countrySignCode = "DE:1053-35",
        )
        return base.copy(
            classMapping = base.classMapping + TrafficSignClassMapping(
                classId = "plate_wet",
                label = "When wet",
                semantic = TrafficSignSemantic(TrafficSignSemanticKind.UNKNOWN),
                threshold = 0.65,
                signRole = TrafficSignRole.SUPPLEMENTARY_PLATE,
                restriction = restriction,
            ),
        ).also(TrafficSignModelPackValidator::requireValid)
    }

    private fun detection(classId: String, box: NormalizedTrafficSignBoundingBox) = TrafficSignDetection(
        candidate = TrafficSignCandidate(
            rawClassId = classId,
            rawLabel = classId,
            semantic = if (classId == "speed_limit_30") {
                TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED, 30, "km/h")
            } else {
                TrafficSignSemantic(TrafficSignSemanticKind.UNKNOWN)
            },
            rawScore = 0.9,
            calibratedConfidence = 0.85,
            boundingBox = box,
        ),
    )

    private fun box(x: Double, y: Double, width: Double, height: Double) =
        NormalizedTrafficSignBoundingBox(x, y, width, height)

    private fun fixture(name: String): File {
        val candidates = listOf(
            File("shared/tsr/fixtures/$name"),
            File("../shared/tsr/fixtures/$name"),
            File("../../shared/tsr/fixtures/$name"),
        )
        return candidates.firstOrNull(File::exists)
            ?: error("Unable to locate shared TSR fixture $name from ${System.getProperty("user.dir")}")
    }
}
