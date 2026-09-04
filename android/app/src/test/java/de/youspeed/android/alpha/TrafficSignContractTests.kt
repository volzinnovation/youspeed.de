package de.youspeed.android.alpha

import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class TrafficSignContractTests {
    @Test
    fun decodesAndValidatesSharedDirectPack() {
        val pack = fixture("de-direct-pack-v1.json").readText().let(TrafficSignModelPackJson::decode)

        assertEquals(1, pack.schemaVersion)
        assertEquals("de-speed-signs-fixture-v1", pack.packId)
        assertEquals(listOf("DE"), pack.countries)
        assertEquals(TrafficSignPipeline.DIRECT_DETECTION, pack.pipeline)
        assertEquals(TrafficSignArtifactFormat.TFLITE, requireNotNull(pack.androidArtifact()).format)
        assertEquals("yolo_nms_xyxy_scores_classes_v1", pack.androidArtifact()?.outputSchema)
        assertNull(pack.classifier)
        assertEquals(
            "5555555555555555555555555555555555555555555555555555555555555555",
            pack.lineage.sourceManifestSha256,
        )
        assertEquals(listOf("6666666666666666666666666666666666666666666666666666666666666666"), pack.lineage.datasetInventorySha256s)
        assertEquals("fixture-training-run-v1", pack.lineage.trainingRunId)
        assertTrue(TrafficSignModelPackValidator.validate(pack).isEmpty())
        assertTrue(TrafficSignRuntimeFoundation.state is TrafficSignRuntimeState.Unavailable)
    }

    @Test
    fun everyLineageFieldAndTheLineageObjectAreRequired() {
        val root = Json.parseToJsonElement(fixture("de-direct-pack-v1.json").readText()).jsonObject
        val withoutLineage = JsonObject(root - "lineage").toString()

        val missingLineageFailure = assertThrows(IllegalStateException::class.java) {
            TrafficSignModelPackJson.decode(withoutLineage)
        }
        assertTrue(missingLineageFailure.message.orEmpty().contains("lineage"))

        val lineage = requireNotNull(root["lineage"]).jsonObject
        val requiredFields = listOf(
            "source_manifest_sha256",
            "dataset_inventory_sha256s",
            "training_run_id",
            "training_run_sha256",
            "evaluation_report_sha256",
            "parity_report_sha256",
        )
        requiredFields.forEach { field ->
            val missingFieldRoot = JsonObject(
                root + ("lineage" to JsonObject(lineage - field)),
            ).toString()

            val failure = assertThrows(IllegalStateException::class.java) {
                TrafficSignModelPackJson.decode(missingFieldRoot)
            }
            assertTrue("Expected failure to name $field: ${failure.message}", failure.message.orEmpty().contains(field))
        }
    }

    @Test
    fun lineageRejectsMalformedHashesEmptyOrDuplicateInventoriesAndUnknownFields() {
        val pack = fixture("de-direct-pack-v1.json").readText().let(TrafficSignModelPackJson::decode)
        val validInventoryHash = pack.lineage.datasetInventorySha256s.single()
        val errors = TrafficSignModelPackValidator.validate(
            pack.copy(
                lineage = pack.lineage.copy(
                    sourceManifestSha256 = "not-a-sha256",
                    datasetInventorySha256s = listOf(validInventoryHash, validInventoryHash, "INVALID"),
                    trainingRunId = " ",
                    trainingRunSha256 = "bad",
                    evaluationReportSha256 = "bad",
                    parityReportSha256 = "bad",
                ),
            ),
        )

        assertTrue(errors.any { it.contains("source_manifest_sha256 is invalid") })
        assertTrue(errors.any { it.contains("dataset_inventory_sha256s must be unique") })
        assertTrue(errors.any { it.contains("dataset_inventory_sha256s contains an invalid hash") })
        assertTrue(errors.any { it.contains("training_run_id is missing") })
        assertTrue(errors.any { it.contains("training_run_sha256 is invalid") })
        assertTrue(errors.any { it.contains("evaluation_report_sha256 is invalid") })
        assertTrue(errors.any { it.contains("parity_report_sha256 is invalid") })
        assertTrue(
            TrafficSignModelPackValidator.validate(
                pack.copy(lineage = pack.lineage.copy(datasetInventorySha256s = emptyList())),
            ).any { it.contains("dataset_inventory_sha256s is empty") },
        )

        val root = Json.parseToJsonElement(fixture("de-direct-pack-v1.json").readText()).jsonObject
        val lineage = requireNotNull(root["lineage"]).jsonObject
        val unexpectedFieldRoot = JsonObject(
            root + ("lineage" to JsonObject(lineage + ("untracked_source" to JsonPrimitive("value")))),
        ).toString()
        val unexpectedFieldFailure = assertThrows(IllegalArgumentException::class.java) {
            TrafficSignModelPackJson.decode(unexpectedFieldRoot)
        }
        assertTrue(unexpectedFieldFailure.message.orEmpty().contains("unsupported fields"))

        val nonStringInventoryRoot = JsonObject(
            root + (
                "lineage" to JsonObject(
                    lineage + ("dataset_inventory_sha256s" to JsonArray(listOf(JsonPrimitive(42)))),
                )
            ),
        ).toString()
        val nonStringInventoryFailure = assertThrows(IllegalArgumentException::class.java) {
            TrafficSignModelPackJson.decode(nonStringInventoryRoot)
        }
        assertTrue(nonStringInventoryFailure.message.orEmpty().contains("dataset_inventory_sha256s[0]"))
    }

    @Test
    fun decodesSharedRecognitionEventsIntoOneNormalizedContract() {
        val pack = fixture("de-direct-pack-v1.json").readText().let(TrafficSignModelPackJson::decode)
        val events = fixture("recognition-events-v1.json").readText().let(TrafficSignRecognitionJson::decodeList)

        assertEquals(listOf(TrafficSignRecognitionState.PROVISIONAL, TrafficSignRecognitionState.CONFIRMED), events.map { it.state })
        assertTrue(events.all { TrafficSignRecognitionJson.validate(it, pack).isEmpty() })
        val candidate = requireNotNull(events.last().candidate)
        assertEquals(TrafficSignSemanticKind.MAXIMUM_SPEED, candidate.semantic.kind)
        assertEquals(30, candidate.semantic.value)
        assertEquals(TrafficSignConditionState.RESOLVED, candidate.conditionState)
        assertEquals(TrafficSignRestrictionKind.WEATHER, candidate.restrictions.single().kind)
        assertEquals("wet", candidate.restrictions.single().normalizedValue)
        assertEquals("fixture-assembly-1", candidate.assemblyId)
        assertEquals("123456", events.last().roadContext?.wayId)
        assertEquals(TrafficSignTravelDirection.FORWARD, events.last().roadContext?.travelDirection)
    }

    @Test
    fun proposalPipelineRequiresClassifier() {
        val invalid = fixture("de-direct-pack-v1.json").readText()
            .replace("\"pipeline\": \"direct_detection\"", "\"pipeline\": \"proposal_classification\"")

        val failure = assertThrows(IllegalArgumentException::class.java) {
            TrafficSignModelPackJson.decode(invalid)
        }

        assertTrue(failure.message.orEmpty().contains("requires a classifier"))
    }

    @Test
    fun maximumSpeedRequiresValueAndUnit() {
        val invalid = fixture("de-direct-pack-v1.json").readText()
            .replace("\"unit\": \"km/h\"", "\"unit\": null")

        val failure = assertThrows(IllegalArgumentException::class.java) {
            TrafficSignModelPackJson.decode(invalid)
        }

        assertTrue(failure.message.orEmpty().contains("maximum_speed requires km/h or mph"))
    }

    @Test
    fun assemblyAndRoadContextSurviveSharedJsonDecoding() {
        val event = TrafficSignRecognitionJson.decodeList(fixture("recognition-events-v1.json").readText()).first()
        val candidate = requireNotNull(event.candidate)

        assertEquals("fixture-assembly-1", candidate.assemblyId)
        assertEquals(TrafficSignConditionState.RESOLVING, candidate.conditionState)
        assertTrue(candidate.restrictions.isEmpty())
        assertEquals("123456", event.roadContext?.wayId)
        assertEquals(82.0, event.roadContext?.headingDegrees)
        assertEquals("bundle:fixture-v1|way:123456|maxspeed:50", event.roadContext?.sourceSignature?.osmRevision)
    }

    @Test
    fun recognitionEventEnforcesStateCandidateAndRequiredSnapshotFields() {
        val event = Json.parseToJsonElement(fixture("recognition-events-v1.json").readText())
            .jsonArray
            .first()
            .jsonObject

        val nullCandidate = JsonObject(event + ("candidate" to JsonNull)).toString()
        val nullCandidateFailure = assertThrows(IllegalArgumentException::class.java) {
            TrafficSignRecognitionJson.decode(nullCandidate)
        }
        assertTrue(nullCandidateFailure.message.orEmpty().contains("provisional requires a candidate"))

        val noRecognitionWithCandidate = JsonObject(
            event + ("state" to JsonPrimitive("no_recognition")),
        ).toString()
        val unexpectedCandidateFailure = assertThrows(IllegalArgumentException::class.java) {
            TrafficSignRecognitionJson.decode(noRecognitionWithCandidate)
        }
        assertTrue(unexpectedCandidateFailure.message.orEmpty().contains("must not include a candidate"))

        val missingRoadContext = JsonObject(event - "road_context").toString()
        val missingRoadContextFailure = assertThrows(IllegalStateException::class.java) {
            TrafficSignRecognitionJson.decode(missingRoadContext)
        }
        assertTrue(missingRoadContextFailure.message.orEmpty().contains("road_context"))

        val candidate = requireNotNull(event["candidate"]).jsonObject
        val missingConditionState = JsonObject(
            event + ("candidate" to JsonObject(candidate - "condition_state")),
        ).toString()
        val missingConditionFailure = assertThrows(IllegalStateException::class.java) {
            TrafficSignRecognitionJson.decode(missingConditionState)
        }
        assertTrue(missingConditionFailure.message.orEmpty().contains("condition_state"))
    }

    @Test
    fun classMappingDefaultsToPrimaryAndDecodesTypedSupplementaryRestriction() {
        val raw = fixture("de-direct-pack-v1.json").readText()
        val plateMapping = """
            {
              "class_id": "plate_wet",
              "label": "When wet",
              "sign_role": "supplementary_plate",
              "semantic": { "kind": "unknown" },
              "restriction": {
                "kind": "weather",
                "normalized_value": "wet",
                "raw_text": "bei Nässe",
                "country_sign_code": "DE:1053-35"
              },
              "threshold": 0.65
            },
        """.trimIndent()
        val pack = TrafficSignModelPackJson.decode(
            raw.replace("\"class_mapping\": [", "\"class_mapping\": [$plateMapping"),
        )

        assertEquals(TrafficSignRole.PRIMARY_SIGN, pack.classFor("speed_limit_30")?.signRole)
        val plate = requireNotNull(pack.classFor("plate_wet"))
        assertEquals(TrafficSignRole.SUPPLEMENTARY_PLATE, plate.signRole)
        assertEquals(TrafficSignRestrictionKind.WEATHER, plate.restriction?.kind)
        assertEquals("wet", plate.restriction?.normalizedValue)
        assertEquals("DE:1053-35", plate.restriction?.countrySignCode)
    }

    @Test
    fun supplementaryMappingRequiresUnknownSemanticAndRestriction() {
        val base = fixture("de-direct-pack-v1.json").readText().let(TrafficSignModelPackJson::decode)
        val speed = requireNotNull(base.classFor("speed_limit_30"))

        val errors = TrafficSignModelPackValidator.validate(
            base.copy(
                classMapping = base.classMapping + speed.copy(
                    classId = "invalid_plate",
                    signRole = TrafficSignRole.SUPPLEMENTARY_PLATE,
                ),
            ),
        )

        assertTrue(errors.any { it.contains("supplementary_plate must use an unknown semantic") })
        assertTrue(errors.any { it.contains("supplementary_plate requires a restriction") })

        val unsupportedRestriction = fixture("de-direct-pack-v1.json").readText()
            .replace("\"kind\": \"weather\"", "\"kind\": \"future_kind\"")
        val failure = assertThrows(IllegalArgumentException::class.java) {
            TrafficSignModelPackJson.decode(unsupportedRestriction)
        }
        assertTrue(failure.message.orEmpty().contains("restriction.kind is unsupported"))

        val nullRole = fixture("de-direct-pack-v1.json").readText()
            .replace(
                "\"label\": \"Maximum speed 30\",",
                "\"label\": \"Maximum speed 30\", \"sign_role\": null,",
            )
        val nullRoleFailure = assertThrows(IllegalArgumentException::class.java) {
            TrafficSignModelPackJson.decode(nullRole)
        }
        assertTrue(nullRoleFailure.message.orEmpty().contains("sign_role"))

        val nullRestrictionMetadata = fixture("de-direct-pack-v1.json").readText()
            .replace("\"raw_text\": \"Bei Nässe\"", "\"raw_text\": null")
        val nullMetadataFailure = assertThrows(IllegalArgumentException::class.java) {
            TrafficSignModelPackJson.decode(nullRestrictionMetadata)
        }
        assertTrue(nullMetadataFailure.message.orEmpty().contains("raw_text"))
    }

    @Test
    fun normalizedBoundingBoxIouUsesTopLeftUnitCoordinates() {
        val left = NormalizedTrafficSignBoundingBox(x = 0.1, y = 0.1, width = 0.4, height = 0.4)
        val right = NormalizedTrafficSignBoundingBox(x = 0.3, y = 0.1, width = 0.4, height = 0.4)
        val separate = NormalizedTrafficSignBoundingBox(x = 0.8, y = 0.8, width = 0.1, height = 0.1)

        assertEquals(1.0 / 3.0, left.intersectionOverUnion(right), 1e-9)
        assertEquals(0.0, left.intersectionOverUnion(separate), 0.0)
        assertFalse(left.intersectionOverUnion(right).isNaN())
        assertThrows(IllegalArgumentException::class.java) {
            NormalizedTrafficSignBoundingBox(x = 0.9, y = 0.9, width = 0.2, height = 0.2)
        }
    }

    private fun fixture(name: String): File {
        val candidates = listOf(
            File("shared/tsr/fixtures/$name"),
            File("../shared/tsr/fixtures/$name"),
            File("../../shared/tsr/fixtures/$name"),
        )
        return candidates.firstOrNull { it.exists() }
            ?: error("Unable to locate shared TSR fixture $name from ${System.getProperty("user.dir")}")
    }
}
