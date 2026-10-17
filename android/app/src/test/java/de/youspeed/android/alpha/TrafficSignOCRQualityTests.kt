package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class TrafficSignOCRQualityTests {
    @Test fun numericDisagreementCannotBecomePresentation() {
        assertEquals("numeric_disagreement", TrafficSignOCRQuality.decision(listOf(
            TrafficSignOCRPass("22-6 h",1.0,1),TrafficSignOCRPass("22-8 h",1.0,2)),120))
        assertEquals("accepted", TrafficSignOCRQuality.decision(listOf(
            TrafficSignOCRPass("22-6h.",.5,1),TrafficSignOCRPass("22-6 h",.5,2)),120))
    }
    @Test fun symbolAndArrowConfusionsStayOutOfSpeech() {
        for (text in listOf("r>","O","ZONE","T 1.3km T")) {
            assertNotEquals(text,"accepted",TrafficSignOCRQuality.decision(listOf(
                TrafficSignOCRPass(text,1.0,1),TrafficSignOCRPass(text,1.0,2)),120))
        }
    }
    @Test fun insufficientNativeDigitsCannotBeRecoveredByUpscaling() {
        val text = "Mo-Fr 630-1730 h"
        assertEquals("insufficient_native_detail",TrafficSignOCRQuality.decision(listOf(
            TrafficSignOCRPass(text,1.0,1),TrafficSignOCRPass(text,1.0,2)),70))
    }
    @Test fun nativeDiacriticIsRetainedWithoutChangingRawCharacters() {
        val native = TrafficSignOCRPass("Lärmschutz",.75,1)
        assertEquals(native,TrafficSignOCRQuality.selected(listOf(native,TrafficSignOCRPass("Larmschutz",.76,2))))
        assertEquals("incomplete_plate",TrafficSignOCRQuality.decision(listOf(TrafficSignOCRPass("Unfall",.9,2,true)),180))
        assertEquals("lost_numeric_clause",TrafficSignOCRQuality.decision(listOf(TrafficSignOCRPass("5km\nUnfall",.9,1),TrafficSignOCRPass("Unfall",.9,2)),180))
    }
    @Test fun hourRangeWithoutUnitIsStillPresentationEvidence() {
        assertEquals("accepted",TrafficSignOCRQuality.decision(listOf(TrafficSignOCRPass("22-6",.5,1),TrafficSignOCRPass("22–6",.5,2)),120))
        assertNotEquals("accepted",TrafficSignOCRQuality.decision(listOf(TrafficSignOCRPass("30",1.0,1),TrafficSignOCRPass("30",1.0,2)),120))
    }
    @Test fun plainWhiteBoardIsNotASeparatePlate() {
        assertNull(TrafficSignPlateDetector.select(120,240,IntArray(120*240) { -1 }))
    }
}
