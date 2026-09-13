package de.youspeed.android.alpha

import java.io.File
import org.junit.Assert.*
import org.junit.Test

class TrafficSignDisplayTests {
    private val catalog = listOf(File("../../shared"), File("../shared"), File("shared"))
        .map { File(it, TrafficSignDisplayCatalog.ASSET_PATH) }.first(File::isFile)
        .readText().let(TrafficSignDisplayCatalog::decode)

    @Test fun latestOtherSignReplacesPreviousWhileEmptyFrameRetainsAndSpeedOrUnmappedClears() {
        val yield = observe("give_way")
        val stop = observe("stop")
        val first = TrafficSignDisplayPolicy.next(null, yield, catalog)
        assertEquals("give_way", first?.classId)
        assertEquals(first, TrafficSignDisplayPolicy.next(first, null, catalog))
        val second = TrafficSignDisplayPolicy.next(first, stop, catalog)
        assertEquals("stop", second?.classId)
        assertNull(TrafficSignDisplayPolicy.next(second, observe("other"), catalog))
        assertNull(TrafficSignDisplayPolicy.next(second, observe("maxspeed:30", TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED, 30)), catalog))
        assertNull(TrafficSignDisplayPolicy.next(second, observe("no:end"), catalog))
        assertNull(TrafficSignDisplayPolicy.next(second, observe("motorway:end"), catalog))
        assertNull(catalog.pictogram("DE:310")) // Reference artwork cannot invent a classifier class.
        val pedestrianCrossing = requireNotNull(catalog.pictogram("pedestrian_crossing"))
        assertEquals("pedestrian_crossing", pedestrianCrossing.classId)
        assertEquals("tsr/sign-pictograms/png/de-350.png", pedestrianCrossing.imagePath)
        assertEquals("pedestrian_crossing", TrafficSignDisplayPolicy.next(second, observe("pedestrian_crossing"), catalog)?.classId)
        val school = requireNotNull(catalog.pictogram("hazard:school"))
        assertEquals("Kinder", school.labels["de"])
        assertNull(school.imagePath)
        assertEquals("hazard:school", TrafficSignDisplayPolicy.next(second, observe("hazard:school"), catalog)?.classId)
        for (classId in listOf("hazard:bicycle", "hazard:wild_animals", "hazard:wind")) {
            assertNotNull(catalog.pictogram(classId))
            assertEquals(classId, TrafficSignDisplayPolicy.next(second, observe(classId), catalog)?.classId)
            assertNull(catalog.pictogram(classId)?.imagePath)
        }
        assertTrue(observe("maxspeed:end").isSpeedLimitEnd)
        assertTrue(observe("zone:end").isSpeedLimitEnd)
        assertTrue(observe("zone:30:end").isSpeedLimitEnd)
    }

    @Test fun independentDisplaySelectsClassifierConfidenceWithExistingDetectorAdmissionFloor() {
        val speed = candidate("maxspeed:30", TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED, 30))
        val stop = candidate("stop").copy(rawScore = 0.30, proposalRawScore = 0.30, classifierRawScore = 0.99)
        val detections = listOf(TrafficSignDetection(speed), TrafficSignDetection(stop))
        assertEquals("maxspeed:30", primaryDetection(detections)?.candidate?.rawClassId)
        assertEquals("stop", TrafficSignDisplayPolicy.accepted(detections)?.rawClassId)
        assertNull(TrafficSignDisplayPolicy.accepted(listOf(TrafficSignDetection(stop.copy(classifierRawScore = 0.899)))))
        assertNull(TrafficSignDisplayPolicy.accepted(listOf(TrafficSignDetection(stop.copy(rawScore = 0.249, proposalRawScore = 0.249)))))
        assertNull(TrafficSignDisplayPolicy.accepted(listOf(TrafficSignDetection(candidate("bad:back")))))
        assertNull(TrafficSignDisplayPolicy.accepted(listOf(TrafficSignDetection(stop.copy(classifierRawScore = 2.0)))))
        assertNull(TrafficSignDisplayPolicy.accepted(listOf(TrafficSignDetection(stop.copy(rawScore = 2.0)))))
        assertThrows(IllegalArgumentException::class.java) { NormalizedTrafficSignBoundingBox(0.9, 0.2, 0.5, 0.2) }
    }

    @Test fun explicitNumberedEndsAndCityAliasesNormalizeWithoutTurning281IntoSpeedEnd() {
        for (speed in listOf(5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130)) {
            val action = candidate("DE:278-$speed").toAction("DE")
            assertEquals(TrafficSignActionKind.MAXIMUM_SPEED_END, action.kind)
            assertEquals(speed, action.valueKmh)
        }
        assertEquals(TrafficSignActionKind.NON_SPEED_RESTRICTION_END, candidate("DE:281").toAction("DE").kind)
        assertEquals(TrafficSignActionKind.ALL_RESTRICTIONS_END, candidate("no:end").toAction("DE").kind)
        assertEquals(TrafficSignActionKind.MOTORWAY_EXIT, candidate("motorway:end").toAction("DE").kind)
        assertEquals(TrafficSignActionKind.MOTORROAD_EXIT, candidate("trunk:end").toAction("DE").kind)
        for (alias in listOf("310", "DE:310", "city:start", "city_limit:start")) {
            val action = candidate(alias).toAction("DE")
            assertEquals(TrafficSignActionKind.CITY_ENTRY, action.kind)
            assertEquals(50, resolveDirectAction(action).speedKmh)
        }
        for (alias in listOf("311", "DE:311", "city:end", "city_limit:end")) {
            assertEquals(TrafficSignActionKind.CITY_EXIT, candidate(alias).toAction("DE").kind)
        }
        for (alias in listOf("DE:280", "DE:281", "no_overtaking:end", "no_overtaking:hgv:end", "no_overtaking:end:hgv")) {
            assertEquals(TrafficSignActionKind.NON_SPEED_RESTRICTION_END, candidate(alias, TrafficSignSemantic(TrafficSignSemanticKind.RESTRICTION_END)).toAction("DE").kind)
        }
        for (alias in listOf("DE:278-0", "DE:278-1", "DE:278-999", "DE:278-abc", "DE:278-1000", "DE:278oops", "DE:278:30", "278foo")) {
            assertEquals(TrafficSignActionKind.UNKNOWN, candidate(alias, TrafficSignSemantic(TrafficSignSemanticKind.RESTRICTION_END, 30)).toAction("DE").kind)
        }
        assertEquals(TrafficSignActionKind.UNKNOWN, candidate("classifier:310").toAction("DE").kind)
    }

    @Test fun publicationClearsPreviousPictogramOnRouteOrCityGenerationChange() {
        val state = ConsumerUiState(trafficSignGeneration = 4, lastTrafficSignPictogram = catalog.pictogram("stop"))
        assertEquals("stop", state.withCurrentTrafficSignDisplayGeneration(4, 4).lastTrafficSignPictogram?.classId)
        val changed = state.copy(trafficSignGeneration = 5).withCurrentTrafficSignDisplayGeneration(4, 5)
        assertNull(changed.lastTrafficSignPictogram)
        assertNull(state.withCurrentTrafficSignDisplayGeneration(4, 5).lastTrafficSignPictogram)
        assertEquals(5L, changed.trafficSignGeneration)
    }

    private fun observe(id: String, semantic: TrafficSignSemantic = TrafficSignSemantic(TrafficSignSemanticKind.UNKNOWN)) =
        TrafficSignDisplayObservation(candidate(id, semantic), 1, "drive-test")

    private fun candidate(id: String, semantic: TrafficSignSemantic = TrafficSignSemantic(TrafficSignSemanticKind.UNKNOWN)) = TrafficSignCandidate(
        rawClassId = id, rawLabel = id, semantic = semantic, rawScore = 0.95, calibratedConfidence = null,
        boundingBox = NormalizedTrafficSignBoundingBox(0.5, 0.2, 0.1, 0.2), proposalRawScore = 0.95, classifierRawScore = 0.95,
    )
}
