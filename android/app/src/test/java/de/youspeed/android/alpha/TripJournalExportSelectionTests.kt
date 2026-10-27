package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class TripJournalExportSelectionTests {
    private data class Event(val seq:Long,val kind:String,val payload:Map<String,Any?>)
    private fun select(events:List<Event>,raw:Boolean=false)=TripJournalExportSelection.select(events,raw,Event::kind,Event::payload)

    @Test fun compactOmitsOnlyMessageOnlyTsrDiagnosticsAndPreservesTypedEvidence() {
        val events=listOf(
            Event(1,"tsr",mapOf("message" to "verbose diagnostic","received_at" to 1000.0)),
            Event(2,"tsr",mapOf("message" to "verbose message without receive timestamp")),
            Event(3,"tsr",mapOf("message" to "OCR contextual text","event" to "traffic_sign_inference","details" to mapOf("frame_id" to "frame-3","supplementary_ocr_only" to true,"ocr" to "22–6 h","parent_annotation" to "main-sign"))),
            Event(4,"sign",mapOf("source" to "camera","class_code" to "DE:274-30","ocr" to "22–6 h","parent_annotation" to "main-sign")),
            Event(5,"gps",mapOf("latitude" to 48.0,"longitude" to 8.0,"track_eligible" to true)),
            Event(6,"gap",mapOf("reason" to "sampling_gap")),
            Event(7,"media",mapOf("id" to "crop-7","local_frame_token" to "frame-3")),
            Event(8,"place",mapOf("street_name" to "Sample street")))
        val original=events.map {it.copy(payload=it.payload.toMap())}
        val selected=select(events)
        assertEquals(listOf(3L,4L,5L,6L,7L,8L),selected.map {it.seq})
        assertEquals("22–6 h",selected.single {it.kind=="sign"}.payload["ocr"])
        val frame=selected.single {it.seq==3L}.payload
        assertEquals("OCR contextual text",frame["message"])
        val details=frame["details"] as Map<*,*>
        assertEquals("22–6 h",details["ocr"]);assertEquals(true,details["supplementary_ocr_only"]);assertEquals("main-sign",details["parent_annotation"])
        assertEquals(events,original)
        selected.forEach {assertSame(events.single {source ->source.seq==it.seq},it)}
    }

    @Test fun additionalUnknownFieldsOrNonStringMessagesAreEvidenceNotTextDiagnostics() {
        val payloads=listOf(
            mapOf("message" to "OCR text","frame_id" to "frame-1"),
            mapOf("message" to "future evidence","future_evidence" to mapOf("opaque" to true)),
            mapOf("message" to 30,"received_at" to 1000.0),
            mapOf("message" to null),
            mapOf("event" to "frame","details" to mapOf("message" to "embedded OCR")))
        val events=payloads.mapIndexed {i,payload->Event(i.toLong()+1,"tsr",payload)}+Event(6,"sign",mapOf("message" to "Keep non-TSR evidence"))
        assertEquals(events,select(events))
    }

    @Test fun explicitDiagnosticOptInReturnsEveryOriginalEventUnchanged() {
        val events=listOf(Event(1,"tsr",mapOf("message" to "verbose")),Event(2,"tsr",mapOf("frame_id" to "frame-2")))
        assertSame(events,select(events,true))
        assertEquals(listOf(2L),select(events).map {it.seq})
        assertEquals("verbose",events[0].payload["message"])
    }
}
