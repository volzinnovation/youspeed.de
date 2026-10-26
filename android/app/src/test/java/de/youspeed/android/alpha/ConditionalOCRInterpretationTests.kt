package de.youspeed.android.alpha

import java.io.File
import java.time.Instant
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class ConditionalOCRInterpretationTests {
    @Test fun unverifiedPlateCannotRenewNumericParentAndIsScopedToPhysicalGeneration() {
        val gate = ConditionalOCRInterpretation.AuthorityGate()
        for (text in listOf("Mo-Fr 6-17h", "bei Nässe", "Lärmschu", "Lärmschutz")) {
            assertTrue(gate.observe(text, "maxspeed:30", 30, text, "1:1"))
            assertTrue(gate.blocks(text, "1:1"))
            assertFalse(gate.observe(text, "maxspeed:30", 30, null, "1:1"))
            assertTrue("A later unread frame must not renew the numeric parent", gate.blocks(text, "1:1"))
        }
        assertFalse(gate.blocks("unrelated", "1:1"))
        assertTrue(gate.observe("unread-first", "maxspeed:30", 30, null, "1:1"))
        assertTrue("No text/failure cannot prove an unconditional parent", gate.blocks("unread-first", "1:1"))
        assertFalse(gate.blocks("bei Nässe", "1:2"))
        assertFalse(gate.observe("secondary", "warning:children", null, "Schule", "1:2"))
    }
    @Test fun pendingAndUnresolvedNoPlateEvidenceNeverBlocksQualifiedNumericParent() {
        val gate = ConditionalOCRInterpretation.AuthorityGate()
        assertTrue(gate.permitsPlain("primary", "1:1"))
        assertFalse(gate.pending("primary", "maxspeed:60", 60, "1:1"))
        assertTrue(gate.permitsPlain("primary", "1:1"))
        assertFalse(gate.blocks("primary", "1:1"))
        assertTrue(gate.pending("primary", "maxspeed:60", 60, "1:1", knownPlate = true))
        assertTrue(gate.blocks("primary", "1:1"))
        assertFalse(gate.permitsPlain("primary", "1:1"))
        assertFalse(gate.pending("primary", "maxspeed:60", 60, "1:1"))
        assertFalse(gate.admitPlain("primary", "1:1"))
        assertTrue(gate.blocks("primary", "1:1"))
        assertTrue(gate.permitsPlain("newer-parent", "1:1"))
        assertTrue(gate.permitsPlain("primary", "1:2"))
    }
    private val now=Instant.parse("2026-10-23T10:00:00Z")
    // Temporal unit fixtures derive geometry from rasterized framed panels. The
    // Android instrumentation suite separately proves actual bundled OCR output.
    private fun evidence(raw:String,frame:String,at:Instant):TrafficSignConditionalAssemblyEvidence {
        val width=240;val height=400;val pixels=IntArray(width*height){0xff777777.toInt()}
        for(y in 220 until 305) for(x in 25 until 215) pixels[y*width+x]=if(x<30 || x>=210 || y<225 || y>=300) 0xff111111.toInt() else 0xffeeeeee.toInt()
        for(y in 245 until 272) for(x in 50 until 185) if(x%16<4) pixels[y*width+x]=0xff111111.toInt()
        val scan=TrafficSignPlateDetector.scan(width,height,pixels)
        assertEquals("complete",scan.status)
        val box=NormalizedTrafficSignBoundingBox(.1,.05,.8,1.0/3.0)
        return TrafficSignConditionalAssemblyEvidence("parent",frame,at,300,600,requireNotNull(supplementaryOCRContextPixelRect(box,300,600)),box,
            scan.plates,scan.status,"accepted",scan.lowerLumaStd,scan.lowerEdgeFraction,
            listOf(TrafficSignOCRPass(raw,.95,1),TrafficSignOCRPass(raw,.95,2)),emptyList())
    }
    private fun observation(raw:String="Mo-Fr / 630-1730h",frame:String="first",at:Instant=now,origin:Instant=at) = ConditionalOCRInterpretation.Observation(
        "physical","parent","maxspeed:30",30,listOf("plate"),frame,raw,at,origin,100.0,"DE","road:10:forward",1,"plate-ocr-v1","a".repeat(64),
        assemblyEvidence=evidence(raw,frame,at))
    private fun verified(raw:String,at:Instant=now):ConditionalOCRInterpretation.Record {
        val tracker=ConditionalOCRInterpretation.Tracker()
        tracker.consume(observation(raw,at=at))
        return tracker.consume(observation(raw,"second",at.plusMillis(100),at))
    }
    @Test fun sharedTemplatesNeverDiscardResidualOrTruncatedText() {
        val corpus=Json.parseToJsonElement(File("../../shared/conditional-ocr/templates-v1.json").readText()).jsonObject
        for(raw in corpus.getValue("cases").jsonArray) {
            val item=raw.jsonObject;val text=item.getValue("raw").jsonPrimitive.content
            val parsed=ConditionalOCRInterpretation.parse(text)
            when(item["kind"]?.takeUnless{it==JsonNull}?.jsonPrimitive?.content) {
                null -> assertNull(text,parsed)
                "wet" -> assertEquals(text,ConditionalOCRInterpretation.Condition.Wet,parsed?.condition)
                "informational" -> assertEquals(text,ConditionalOCRInterpretation.Condition.Informational,parsed?.condition)
                "schedule" -> assertEquals(text,ConditionalOCRInterpretation.Condition.Schedule(
                    item.getValue("weekdays").jsonArray.map{it.jsonPrimitive.int},item.getValue("start_minute").jsonPrimitive.int,item.getValue("end_minute").jsonPrimitive.int),parsed?.condition)
            }
        }
    }
    @Test fun admissionRequiresCompleteAssemblyQualityAndTwoActualSourceFrames() {
        val tracker=ConditionalOCRInterpretation.Tracker();val first=observation()
        assertEquals(ConditionalOCRInterpretation.Verification.CANDIDATE,tracker.consume(first.copy(assemblyEvidence=null)).verification)
        assertEquals(ConditionalOCRInterpretation.Verification.CANDIDATE,tracker.consume(first).verification)
        assertEquals(ConditionalOCRInterpretation.Verification.CANDIDATE,tracker.consume(observation(at=now.plusMillis(100),origin=now)).verification)
        val accepted=tracker.consume(observation(frame="second",at=now.plusMillis(200),origin=now))
        assertEquals(ConditionalOCRInterpretation.Verification.VERIFIED,accepted.verification)
        assertEquals(listOf("first","second"),accepted.supportingFrameIds)
        assertEquals(now,accepted.originalEvidenceAt)
        assertEquals(ConditionalOCRInterpretation.Verification.REJECTED,tracker.consume(first.copy(sourceEvaluationEnabled=false)).verification)
        assertEquals("unsupported_or_residual_text",tracker.consume(first.copy(rawText="6-17h frei")).reason)
    }
    @Test fun wetnessIsUnknownByDefaultAndScopeOrOrdinaryExpiryCannotBeRenewed() {
        val record=verified("bei Nässe")
        assertEquals(ConditionalOCRInterpretation.Verdict.UNRESOLVED,record.verdict(now.plusSeconds(1),101.0,"road:10:forward",1))
        assertEquals(ConditionalOCRInterpretation.Verdict.APPLICABLE,record.verdict(now.plusSeconds(1),101.0,"road:10:forward",1,roadSurfaceWet=true))
        assertEquals(ConditionalOCRInterpretation.Verdict.INAPPLICABLE,record.verdict(now.plusSeconds(1),101.0,"road:10:forward",1,roadSurfaceWet=false))
        assertEquals(ConditionalOCRInterpretation.Verdict.UNRESOLVED,record.verdict(now.plusSeconds(301),101.0,"road:10:forward",1,roadSurfaceWet=true))
        assertEquals(ConditionalOCRInterpretation.Verdict.UNRESOLVED,record.verdict(now.plusSeconds(1),5101.0,"road:10:forward",1,roadSurfaceWet=true))
        assertEquals(ConditionalOCRInterpretation.Verdict.UNRESOLVED,record.verdict(now.plusSeconds(1),101.0,"road:10:forward",2,roadSurfaceWet=true))
    }
    @Test fun weekdayOvernightAndDstRepeatUseBerlinCivilTime() {
        val saturday=Instant.parse("2026-10-24T03:00:00Z")
        assertEquals(ConditionalOCRInterpretation.Verdict.APPLICABLE,verified("Mo-Fr 22-6h",saturday).verdict(saturday.plusSeconds(1),101.0,"road:10:forward",1))
        val monday=Instant.parse("2026-10-26T04:00:00Z")
        assertEquals(ConditionalOCRInterpretation.Verdict.INAPPLICABLE,verified("Mo-Fr 22-6h",monday).verdict(monday.plusSeconds(1),101.0,"road:10:forward",1))
        for(instant in listOf("2026-10-25T00:30:00Z","2026-10-25T01:30:00Z").map(Instant::parse)) {
            assertEquals(ConditionalOCRInterpretation.Verdict.APPLICABLE,verified("So 2-3h",instant).verdict(instant.plusSeconds(1),101.0,"road:10:forward",1))
        }
        val boundary=Instant.parse("2026-10-23T15:30:00Z")
        val record=verified("Mo-Fr 630-1730h",boundary.minusSeconds(30))
        assertEquals(ConditionalOCRInterpretation.Verdict.INAPPLICABLE,record.verdict(boundary,101.0,"road:10:forward",1))
        assertEquals(ConditionalOCRInterpretation.Verdict.UNRESOLVED,record.verdict(boundary,101.0,"road:10:forward",1,uncertaintySeconds=30.0))
    }
}
