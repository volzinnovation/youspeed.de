package de.youspeed.android.alpha

import java.io.File
import java.security.MessageDigest
import java.util.zip.ZipFile
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AndroidTrafficSignRuntimeTests {
    @Test
    fun bundledModelSelectionNormalizesNationalCodes() {
        assertEquals("DE", AndroidTrafficSignModelPackSelection.availableCountryCode("DEU"))
        assertEquals("FR", AndroidTrafficSignModelPackSelection.availableCountryCode("FRA"))
        assertEquals("NL", AndroidTrafficSignModelPackSelection.availableCountryCode("NLD"))
        assertEquals("BE", AndroidTrafficSignModelPackSelection.availableCountryCode("BEL"))
        assertEquals(null, AndroidTrafficSignModelPackSelection.availableCountryCode("LUX"))
    }

    @Test
    fun nationalCatalogsUseTheirOwnClassifierVocabulary() {
        val sharedRoot = listOf(File("../../shared"), File("../shared"), File("shared"))
            .first(File::isDirectory)
        mapOf("DE" to 134, "FR" to 256, "NL" to 160, "BE" to 143).forEach { (country, expectedClassCount) ->
            val file = File(sharedRoot, TrafficSignDisplayCatalog.assetPath(country))
            val catalog = TrafficSignDisplayCatalog.decode(file.readText(), expectedCountryCode = country)
            assertEquals(expectedClassCount, catalog.classLabels.size)
        }
    }

    @Test
    fun bundledPackDeclaresVerifiedAndroidLiteRtArtifacts() {
        val root = assetPackRoot()
        val pack = TrafficSignModelPackJson.decode(File(root, "manifest.json").readText())
        val detector = requireNotNull(pack.androidArtifact(pack.detector))
        val classifier = requireNotNull(pack.classifier?.let(pack::androidArtifact))

        assertEquals(TrafficSignArtifactFormat.TFLITE, detector.format)
        assertEquals(listOf(1, 1280, 1280, 3), detector.inputShape)
        assertEquals("yolo_raw_xywh_class_scores_v1", detector.outputSchema)
        assertEquals("e5490acd60ceb015336bed487b5e247c2728b2b98b6336790bf6ffe02a6f7207", detector.sha256)
        assertEquals(TrafficSignArtifactFormat.TFLITE, classifier.format)
        assertEquals(listOf(1, 224, 224, 3), classifier.inputShape)
        assertEquals("classification_probabilities_v1", classifier.outputSchema)
        assertEquals("28d2ce40455d0f9cac2f7c61a51b5a5f95f17fa57fc5706a56f64fa9f8bd7df0", classifier.sha256)
        assertTrue(File(root, detector.path).isFile)
        assertTrue(File(root, classifier.path).isFile)
        assertEquals(detector.sha256, sha256(File(root, detector.path)))
        assertEquals(classifier.sha256, sha256(File(root, classifier.path)))
        assertTrue(TrafficSignModelPackValidator.validate(pack).isEmpty())
    }

    @Test
    fun detectorDecoderUsesOnlySignChannelAndAppliesNms() {
        val output = FloatArray(AndroidYoloSignDecoder.OUTPUT_CHANNELS * AndroidYoloSignDecoder.OUTPUT_ELEMENTS)
        putBox(output, index = 0, x = 0.5f, y = 0.5f, width = 0.25f, height = 0.25f)
        output[AndroidYoloSignDecoder.SIGN_SCORE_CHANNEL * AndroidYoloSignDecoder.OUTPUT_ELEMENTS] = 0.80f
        putBox(output, index = 1, x = 645f / 1280f, y = 645f / 1280f, width = 0.25f, height = 0.25f)
        output[AndroidYoloSignDecoder.SIGN_SCORE_CHANNEL * AndroidYoloSignDecoder.OUTPUT_ELEMENTS + 1] = 0.70f
        putBox(output, index = 2, x = 300f / 1280f, y = 300f / 1280f, width = 200f / 1280f, height = 200f / 1280f)
        // A high plate score must not become a live proposal.
        output[5 * AndroidYoloSignDecoder.OUTPUT_ELEMENTS + 2] = 0.99f

        val proposals = AndroidYoloSignDecoder.decode(
            output = output,
            sourceWidth = 1280,
            sourceHeight = 720,
            inputSize = 1280,
            minimumScore = 0.25,
        )

        assertEquals(1, proposals.size)
        assertEquals(0.80, proposals.single().score.toDouble(), 1e-6)
        assertEquals(0.375, proposals.single().box.x, 1e-9)
        assertEquals(0.2777777778, proposals.single().box.y, 1e-8)
        assertEquals(0.25, proposals.single().box.width, 1e-9)
        assertEquals(0.4444444444, proposals.single().box.height, 1e-8)
    }

    @Test
    fun detectorDecoderMapsNormalizedBoxesThroughPortraitLetterboxing() {
        val output = FloatArray(AndroidYoloSignDecoder.OUTPUT_CHANNELS * AndroidYoloSignDecoder.OUTPUT_ELEMENTS)
        putBox(output, index = 0, x = 0.5f, y = 0.5f, width = 0.25f, height = 0.125f)
        output[AndroidYoloSignDecoder.SIGN_SCORE_CHANNEL * AndroidYoloSignDecoder.OUTPUT_ELEMENTS] = 0.90f
        // A proposal crossing the left padding must be clipped to the source image.
        putBox(output, index = 1, x = 0.25f, y = 0.25f, width = 0.25f, height = 0.125f)
        output[AndroidYoloSignDecoder.SIGN_SCORE_CHANNEL * AndroidYoloSignDecoder.OUTPUT_ELEMENTS + 1] = 0.80f
        // A proposal entirely inside the left padding has no source-image area.
        putBox(output, index = 2, x = 0.125f, y = 0.75f, width = 0.0625f, height = 0.125f)
        output[AndroidYoloSignDecoder.SIGN_SCORE_CHANNEL * AndroidYoloSignDecoder.OUTPUT_ELEMENTS + 2] = 0.70f

        val proposals = AndroidYoloSignDecoder.decode(
            output = output,
            sourceWidth = 2376,
            sourceHeight = 4224,
            inputSize = 1280,
            minimumScore = 0.25,
        )

        assertEquals(2, proposals.size)
        val centeredBox = proposals[0].box
        assertEquals(200.0 / 720.0, centeredBox.x, 1e-9)
        assertEquals(0.4375, centeredBox.y, 1e-9)
        assertEquals(320.0 / 720.0, centeredBox.width, 1e-9)
        assertEquals(0.125, centeredBox.height, 1e-9)
        val clippedBox = proposals[1].box
        assertEquals(0.0, clippedBox.x, 1e-9)
        assertEquals(0.1875, clippedBox.y, 1e-9)
        assertEquals(200.0 / 720.0, clippedBox.width, 1e-9)
        assertEquals(0.125, clippedBox.height, 1e-9)
    }

    @Test
    fun classifierIndicesMatchAllPinnedModelClassesWithoutInventingCityEntry() {
        val catalog = displayCatalog()
        assertEquals("maxspeed:30", catalog.classId(65))
        assertEquals("maxspeed:70", catalog.classId(70))
        assertEquals("zone:30", catalog.classId(129))
        assertEquals("zone:30:end", catalog.classId(130))
        assertEquals("arrow:red", catalog.classId(0))
        assertEquals("maxspeed:end", catalog.classId(72))
        assertEquals("no:end", catalog.classId(78))

        val root = assetPackRoot()
        assertEquals("sign", embeddedModelNames(File(root, "yolo11n_panoramax_float16.tflite"))["0"])
        assertEquals("plate", embeddedModelNames(File(root, "yolo11n_panoramax_float16.tflite"))["1"])
        assertEquals("face", embeddedModelNames(File(root, "yolo11n_panoramax_float16.tflite"))["2"])
        val names = embeddedModelNames(File(root, "classify_de_road_signs_float16.tflite"))
        assertEquals((0 until 134).map { names.getValue(it.toString()) }, catalog.classLabels)
        assertTrue(catalog.classLabels.none { it.contains("310") || it.contains("city") || it.contains("town") })
        assertEquals("maxspeed:30", embeddedModelNames(File(root, "classify_de_road_signs_float16.tflite"))["65"])
        assertEquals("zone:30", embeddedModelNames(File(root, "classify_de_road_signs_float16.tflite"))["129"])
    }

    private fun displayCatalog(): TrafficSignDisplayCatalog {
        val file = listOf(File("../../shared"), File("../shared"), File("shared"))
            .map { File(it, TrafficSignDisplayCatalog.ASSET_PATH) }.first(File::isFile)
        return TrafficSignDisplayCatalog.decode(file.readText())
    }

    private fun putBox(
        output: FloatArray,
        index: Int,
        x: Float,
        y: Float,
        width: Float,
        height: Float,
    ) {
        val stride = AndroidYoloSignDecoder.OUTPUT_ELEMENTS
        output[index] = x
        output[stride + index] = y
        output[2 * stride + index] = width
        output[3 * stride + index] = height
    }

    private fun assetPackRoot(): File {
        val candidates = listOf(
            File("app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack"),
            File("src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack"),
            File("android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack"),
        )
        return candidates.firstOrNull(File::isDirectory)
            ?: error("Unable to locate bundled Android TSR pack from ${System.getProperty("user.dir")}")
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().buffered().use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { byte -> "%02x".format(byte.toInt() and 0xff) }
    }

    private fun embeddedModelNames(file: File): Map<String, String> = ZipFile(file).use { archive ->
        val raw = archive.getInputStream(requireNotNull(archive.getEntry("metadata.json")))
            .bufferedReader()
            .use { it.readText() }
        Json.parseToJsonElement(raw).jsonObject
            .getValue("names")
            .jsonObject
            .mapValues { (_, value) -> value.jsonPrimitive.content }
    }
}
