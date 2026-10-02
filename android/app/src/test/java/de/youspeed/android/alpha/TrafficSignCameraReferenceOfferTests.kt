package de.youspeed.android.alpha

import java.io.File
import org.junit.Assert.*
import org.junit.Test

class TrafficSignCameraReferenceOfferTests {
    private fun runtime(): SpeedReferenceRuntime {
        val root = sequenceOf(File("../../shared/speed-limit-reference"), File("../shared/speed-limit-reference"), File("shared/speed-limit-reference"))
            .first { it.isDirectory }
        return SpeedReferenceRuntime(SpeedLimitReferenceModel.load { File(root, it).readBytes() }, now = { 0.0 })
    }
    private fun immediate(speed: Int, oldEnclosing: Boolean = false, id: String? = "new-sign", presented: Int? = speed) =
        TrafficSignCameraReferenceOffer.select("camera_confirmed_frames", presented, id, speed,
            "old-passage", "old-resolver", oldEnclosing)

    @Test fun freshImmediate80Replaces70UsingItsOwnEvidenceIdentity() {
        val reference = runtime()
        reference.camera("old-resolver", SpeedReferenceValue("numeric", 70))
        val offer = requireNotNull(immediate(80))
        reference.camera(offer.evidenceId, SpeedReferenceValue("numeric", 80), offer.enclosing)
        assertEquals("new-sign", reference.output()?.evidenceId)
        assertEquals(80, reference.output()?.baselineKmh)
    }

    @Test fun ordinaryImmediate30DoesNotBorrowAnExistingZonesEnclosingType() {
        val reference = runtime()
        reference.camera("old-road", SpeedReferenceValue("numeric", 70))
        reference.camera("old-resolver:enclosing", SpeedReferenceValue("numeric", 30), true)
        val offer = requireNotNull(immediate(30, oldEnclosing = true))
        reference.camera(offer.evidenceId, SpeedReferenceValue("numeric", 30), offer.enclosing)
        assertFalse(offer.enclosing)
        assertEquals("new-sign", reference.output()?.evidenceId)
        assertEquals(30, reference.output()?.baselineKmh)
    }

    @Test fun unmatchedImmediateValueCannotBorrowAnOlderAssertionsIdentity() {
        assertNull(immediate(80, presented = 70))
        assertNull(immediate(80, id = null))
        assertNull(immediate(80, id = " "))
        assertNull(immediate(80, presented = null))
    }

    @Test fun finalizedPassageAndResolverKeepTheirExistingIdentityAndType() {
        val passage = TrafficSignCameraReferenceOffer.select("camera_zone_start", 30, "immediate", 80, "zone-passage", "resolver", true)
        assertEquals(TrafficSignCameraReferenceOffer("zone-passage", true, "passage"), passage)
        val resolver = TrafficSignCameraReferenceOffer.select("camera_posted_maximum", 70, "immediate", 80, null, "resolver", false)
        assertEquals(TrafficSignCameraReferenceOffer("resolver", false, "resolver"), resolver)
    }

    @Test fun recognizedZoneKeepsNumericPreviewUntilItsFinalizedEnclosingPassage() {
        var now = 0.0
        val root = sequenceOf(File("../../shared/speed-limit-reference"), File("../shared/speed-limit-reference"), File("shared/speed-limit-reference"))
            .first { it.isDirectory }
        val reference = SpeedReferenceRuntime(SpeedLimitReferenceModel.load { File(root, it).readBytes() }, now = { now })
        val preview = requireNotNull(immediate(30, id = "zone-sign"))
        assertFalse(preview.enclosing)
        assertEquals("camera", reference.camera(preview.evidenceId, SpeedReferenceValue("numeric", 30), preview.enclosing)?.offeredKind)
        val passage = requireNotNull(TrafficSignCameraReferenceOffer.select("camera_zone_start", 30,
            "zone-sign", 30, "zone-sign", "zone-sign", true))
        val receipt = requireNotNull(reference.camera(passage.evidenceId, SpeedReferenceValue("numeric", 30), passage.enclosing))
        assertEquals("camera_context", receipt.offeredKind)
        assertEquals("T12", receipt.after.transition)
        assertEquals("zone-sign", reference.output()?.evidenceId)
        // Existing policy priority and expiry remain intact: the enclosing claim survives the preview.
        now = 301.0
        reference.tick()
        assertEquals("zone-sign:enclosing", reference.output()?.evidenceId)
        assertEquals(30, reference.output()?.baselineKmh)
    }
}
