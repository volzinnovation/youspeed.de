package de.youspeed.android.alpha

import java.io.File
import java.time.Instant
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import kotlin.math.*

class SignCollectionCaptureMetadataTests {
    private val root = File("../../shared/tsr/collection-contract-v1")
    private fun fixture(name: String) = SignCollectionJson.parse(File(root,"fixtures/$name.json").readText()).jsonObject
    private fun gate() = SignCollectionContractGate { File(root,it).readBytes() }
    @Test fun physicalCameraAxisIsIndependentOfPhoneMountingRotation() {
        val at = Instant.parse("2026-10-02T10:00:01Z")
        SignCollectionJson.parse(File(root,"fixtures/camera-axis-v1.json").readText()).jsonArray.forEach { value ->
            val v = value.jsonObject
            val matrix = v.getValue("android_device_to_enu").jsonArray.map { it.jsonPrimitive.float }.toFloatArray()
            val sample = SignCollectionCameraSample.rotationMatrix(matrix,at,"high")!!
            val difference = abs(sample.azimuth-v.getValue("bearing").jsonPrimitive.double)
            assertTrue(min(difference,360-difference) < 0.0001)
            assertEquals(v.getValue("elevation").jsonPrimitive.double,sample.elevation,0.0001)
        }
        assertNull(SignCollectionCameraSample.opticalAxis(0.0,0.0,1.0,at,"high"))
        assertNull(SignCollectionCameraSample.opticalAxis(1.0,0.0,0.0,at,"unreliable"))
        val history = SignCollectionCameraHistory()
        history.append(SignCollectionCameraSample.opticalAxis(1.0,0.0,0.0,at,"high")!!)
        history.append(SignCollectionCameraSample.opticalAxis(0.0,1.0,0.0,at.plusSeconds(1),"high")!!)
        assertEquals(5.0,history.direction(at,5.0)!!.getValue("azimuth_degrees").jsonPrimitive.double,0.0001)
        assertNull(history.direction(at.plusSeconds(2),5.0))
        history.clear(); assertNull(history.direction(at,5.0))
    }
    @Test fun completeMetadataAndDeviceIdentityAreMandatoryForNewRecords() {
        val gate = gate()
        val batch = fixture("capture-sighting-batch-v1")
        val event = batch.getValue("events").jsonArray[0].jsonObject
        gate.validate(batch,"batch"); gate.validate(event,"sighting")
        for (field in listOf("capture_metadata_version","device_id","vehicle_position","camera_viewing_direction")) {
            assertThrows(Exception::class.java) { gate.validate(JsonObject(event-field),"sighting") }
        }
        val invalid = JsonObject(event + ("device_id" to JsonPrimitive(SignCollectionJson.uuid())))
        assertThrows(Exception::class.java) { gate.validate(JsonObject(batch + ("events" to JsonArray(listOf(invalid)))),"batch") }
        val direction = JsonObject(event.getValue("camera_viewing_direction").jsonObject + ("frame_measurement_delta_ms" to JsonPrimitive(400)))
        assertThrows(Exception::class.java) { gate.validate(JsonObject(event + ("camera_viewing_direction" to direction)),"sighting") }
        val crop = fixture("capture-crop-v1"); gate.validate(crop,"crop")
        assertThrows(Exception::class.java) { gate.validate(JsonObject(crop + ("device_id" to JsonPrimitive(SignCollectionJson.uuid()))),"crop") }
    }
}
