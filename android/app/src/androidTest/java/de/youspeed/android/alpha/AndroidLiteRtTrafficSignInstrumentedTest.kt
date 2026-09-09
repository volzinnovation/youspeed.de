package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.filters.LargeTest
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@LargeTest
@RunWith(AndroidJUnit4::class)
class AndroidLiteRtTrafficSignInstrumentedTest {
    @Test
    fun cityEntryReferenceReportsActualFullFrameAndCropPredictions() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val pack = AndroidTrafficSignModelPackLoader.load(instrumentation.targetContext)
        val bitmap = instrumentation.context.assets.open("tsr-city310-bernbach.jpg").use(BitmapFactory::decodeStream)
        requireNotNull(bitmap)
        val crop = Bitmap.createBitmap(bitmap, 1827, 2244, 2039 - 1827, 2392 - 2244)
        val prolixCrop = Bitmap.createBitmap(bitmap, 1795, 2221, 2071 - 1795, 2415 - 2221)
        val engine = AndroidLiteRtTrafficSignInferenceEngine(pack)
        fun detectionJson(detection: TrafficSignDetection) = JSONObject().apply {
            val candidate = detection.candidate
            put("class_id", candidate.rawClassId)
            put("class_index", pack.displayCatalog.classLabels.indexOf(candidate.rawClassId))
            put("bounding_box_xywh", JSONArray(listOf(candidate.boundingBox.x, candidate.boundingBox.y, candidate.boundingBox.width, candidate.boundingBox.height)))
            put("semantic", candidate.semantic.kind.wireValue)
            put("proposal_score", candidate.proposalRawScore)
            put("classifier_score", candidate.classifierRawScore)
            put("display_accepted", TrafficSignDisplayPolicy.accepted(listOf(detection)) != null)
        }
        try {
            val full = engine.recognizeAll(bitmap)
            val classifiedCrop = engine.classifyCropForDiagnostic(crop)
            val classifiedProlixCrop = engine.classifyCropForDiagnostic(prolixCrop)
            assertTrue("Pinned classifier has no city-entry class", pack.displayCatalog.classLabels.none { it.contains("310") || it.contains("city") })
            assertTrue(full.none { it.candidate.semantic.kind == TrafficSignSemanticKind.CITY_ENTRY })
            assertTrue(classifiedCrop?.candidate?.semantic?.kind != TrafficSignSemanticKind.CITY_ENTRY)
            val evidence = JSONObject().apply {
                put("ground_truth", "User-identified DE:310 Bernbach city entry; source annotation provides generic sign bounds")
                put("fixture_sha256", "11c4eb3729167234ec35474192e301b0e74b9f4fd68582d4ccc959e80b43e9ae")
                put("model_has_city_entry_class", false)
                put("classifier_artifact_sha256", pack.classifierArtifact.sha256)
                put("detector_artifact_sha256", pack.detectorArtifact.sha256)
                put("crop_probe_note", "Crop probes call the classifier directly; proposal_score=1 is synthetic admission, not a detector result.")
                put("full_frame", JSONArray(full.map(::detectionJson)))
                put("annotation_crop_classifier", classifiedCrop?.let(::detectionJson) ?: JSONObject.NULL)
                put("prolix_15_percent_crop_classifier", classifiedProlixCrop?.let(::detectionJson) ?: JSONObject.NULL)
                put("prolix_crop_xyxy", JSONArray(listOf(1795, 2221, 2071, 2415)))
                put("crop_xyxy", JSONArray(listOf(1827, 2244, 2039, 2392)))
            }
            File(instrumentation.targetContext.getExternalFilesDir(null), "tsr-city310-probe.json").writeText(evidence.toString(2))
            Log.i("YouSpeedTSRProbe", evidence.toString())
        } finally {
            engine.close()
            crop.recycle()
            prolixCrop.recycle()
            bitmap.recycle()
        }
    }

    @Test
    fun verifiedLiteRtPackRecognizesPinnedPanoramaxFixture() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val pack = AndroidTrafficSignModelPackLoader.load(instrumentation.targetContext)
        val bitmap = instrumentation.context.assets
            .open("tsr-panoramax-0906fc23.jpg")
            .use(BitmapFactory::decodeStream)
        assertNotNull(bitmap)
        val engine = AndroidLiteRtTrafficSignInferenceEngine(pack)

        try {
            val detection = requireNotNull(engine.recognize(bitmap))
            assertEquals("maxspeed:70", detection.candidate.rawClassId)
            assertEquals(TrafficSignSemanticKind.MAXIMUM_SPEED, detection.candidate.semantic.kind)
            assertEquals(70, detection.candidate.semantic.value)
            assertTrue(requireNotNull(detection.candidate.proposalRawScore) > 0.80)
            assertTrue(requireNotNull(detection.candidate.classifierRawScore) > 0.95)
            assertTrue(detection.candidate.restrictions.isEmpty())
            assertEquals(TrafficSignConditionState.NONE, detection.candidate.conditionState)
        } finally {
            engine.close()
            bitmap.recycle()
        }
    }
}
