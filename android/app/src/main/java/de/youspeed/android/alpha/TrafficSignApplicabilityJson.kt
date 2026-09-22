package de.youspeed.android.alpha

import kotlinx.serialization.json.*

/** Explicit versioned wire adapter; no reflection and no changes to frozen event codecs. */
object TSRApplicabilityJson {
    fun decodeScope(o: JsonObject): TSRApplicabilityScope {
        require(o.keys.all { it in setOf("sessionId", "bundleId", "cameraGeometryId", "generation", "contextGeneration", "traversalEpoch") } && o.keys.containsAll(setOf("sessionId", "bundleId", "cameraGeometryId", "generation", "contextGeneration", "traversalEpoch"))) { "Invalid scope fields" }
        return TSRApplicabilityScope(
            sessionId = o.getValue("sessionId").jsonPrimitive.content,
            bundleId = o.getValue("bundleId").jsonPrimitive.content,
            cameraGeometryId = o.getValue("cameraGeometryId").jsonPrimitive.content,
            generation = o.getValue("generation").jsonPrimitive.long,
            contextGeneration = o.getValue("contextGeneration").jsonPrimitive.long,
            traversalEpoch = o.getValue("traversalEpoch").jsonPrimitive.long
        )
    }
    fun encodeScope(v: TSRApplicabilityScope): JsonObject = buildJsonObject {
        put("sessionId", JsonPrimitive(v.sessionId))
        put("bundleId", JsonPrimitive(v.bundleId))
        put("cameraGeometryId", JsonPrimitive(v.cameraGeometryId))
        put("generation", JsonPrimitive(v.generation))
        put("contextGeneration", JsonPrimitive(v.contextGeneration))
        put("traversalEpoch", JsonPrimitive(v.traversalEpoch))
    }
    fun decodeBox(o: JsonObject): TSRApplicabilityBox {
        require(o.keys.all { it in setOf("x", "y", "width", "height") } && o.keys.containsAll(setOf("x", "y", "width", "height"))) { "Invalid box fields" }
        return TSRApplicabilityBox(
            x = o.getValue("x").jsonPrimitive.double,
            y = o.getValue("y").jsonPrimitive.double,
            width = o.getValue("width").jsonPrimitive.double,
            height = o.getValue("height").jsonPrimitive.double
        )
    }
    fun encodeBox(v: TSRApplicabilityBox): JsonObject = buildJsonObject {
        put("x", JsonPrimitive(v.x))
        put("y", JsonPrimitive(v.y))
        put("width", JsonPrimitive(v.width))
        put("height", JsonPrimitive(v.height))
    }
    fun decodeCandidate(o: JsonObject): TSRApplicabilityCandidate {
        require(o.keys.all { it in setOf("candidateId", "semanticKey", "box", "rawScore", "recognitionEligible", "assemblyId", "recognitionScore", "calibratedConfidence") } && o.keys.containsAll(setOf("candidateId", "semanticKey", "box", "rawScore", "recognitionEligible"))) { "Invalid candidate fields" }
        return TSRApplicabilityCandidate(
            candidateId = o.getValue("candidateId").jsonPrimitive.content,
            semanticKey = o.getValue("semanticKey").jsonPrimitive.content,
            box = decodeBox(o.getValue("box").jsonObject),
            rawScore = o.getValue("rawScore").jsonPrimitive.double,
            recognitionEligible = o.getValue("recognitionEligible").jsonPrimitive.boolean,
            assemblyId = o["assemblyId"]?.takeUnless { it is JsonNull }?.let { it.jsonPrimitive.content },
            recognitionScore = o["recognitionScore"]?.takeUnless { it is JsonNull }?.let { it.jsonPrimitive.double },
            calibratedConfidence = o["calibratedConfidence"]?.takeUnless { it is JsonNull }?.let { it.jsonPrimitive.double }
        )
    }
    fun encodeCandidate(v: TSRApplicabilityCandidate): JsonObject = buildJsonObject {
        put("candidateId", JsonPrimitive(v.candidateId))
        put("semanticKey", JsonPrimitive(v.semanticKey))
        put("box", encodeBox(v.box))
        put("rawScore", JsonPrimitive(v.rawScore))
        put("recognitionEligible", JsonPrimitive(v.recognitionEligible))
        put("assemblyId", v.assemblyId?.let { JsonPrimitive(it) } ?: JsonNull)
        put("recognitionScore", v.recognitionScore?.let { JsonPrimitive(it) } ?: JsonNull)
        put("calibratedConfidence", v.calibratedConfidence?.let { JsonPrimitive(it) } ?: JsonNull)
    }
    fun decodeCorridor(o: JsonObject): TSRApplicabilityCorridor {
        require(o.keys.all { it in setOf("wayId", "headingDeg", "distanceM", "roadClass", "endpointLinked", "turnAngleDeg") } && o.keys.containsAll(setOf("wayId", "endpointLinked"))) { "Invalid corridor fields" }
        return TSRApplicabilityCorridor(
            wayId = o.getValue("wayId").jsonPrimitive.content,
            headingDeg = o["headingDeg"]?.takeUnless { it is JsonNull }?.let { it.jsonPrimitive.double },
            distanceM = o["distanceM"]?.takeUnless { it is JsonNull }?.let { it.jsonPrimitive.double },
            roadClass = o["roadClass"]?.takeUnless { it is JsonNull }?.let { it.jsonPrimitive.content },
            endpointLinked = o.getValue("endpointLinked").jsonPrimitive.boolean,
            turnAngleDeg = o["turnAngleDeg"]?.takeUnless { it is JsonNull }?.let { it.jsonPrimitive.double }
        )
    }
    fun encodeCorridor(v: TSRApplicabilityCorridor): JsonObject = buildJsonObject {
        put("wayId", JsonPrimitive(v.wayId))
        put("headingDeg", v.headingDeg?.let { JsonPrimitive(it) } ?: JsonNull)
        put("distanceM", v.distanceM?.let { JsonPrimitive(it) } ?: JsonNull)
        put("roadClass", v.roadClass?.let { JsonPrimitive(it) } ?: JsonNull)
        put("endpointLinked", JsonPrimitive(v.endpointLinked))
        put("turnAngleDeg", v.turnAngleDeg?.let { JsonPrimitive(it) } ?: JsonNull)
    }
    fun decodeRoad(o: JsonObject): TrafficSignMapContextSnapshot {
        require(o.keys.all { it in setOf("snapshotId", "capturedAtMs", "scope", "wayId", "horizontalAccuracyM", "courseAccuracyDeg", "courseDeg", "localTangentDeg", "matchedStable", "roadClass", "hypotheses", "branches", "capabilities", "cameraHorizontalFovDeg", "cameraYawDeg", "postedSpeedKmh") } && o.keys.containsAll(setOf("snapshotId", "capturedAtMs", "scope", "matchedStable", "hypotheses", "branches", "capabilities"))) { "Invalid road fields" }
        return TrafficSignMapContextSnapshot(
            snapshotId = o.getValue("snapshotId").jsonPrimitive.content,
            capturedAtMs = o.getValue("capturedAtMs").jsonPrimitive.double,
            scope = decodeScope(o.getValue("scope").jsonObject),
            wayId = o["wayId"]?.takeUnless { it is JsonNull }?.let { it.jsonPrimitive.content },
            horizontalAccuracyM = o["horizontalAccuracyM"]?.takeUnless { it is JsonNull }?.let { it.jsonPrimitive.double },
            courseAccuracyDeg = o["courseAccuracyDeg"]?.takeUnless { it is JsonNull }?.let { it.jsonPrimitive.double },
            courseDeg = o["courseDeg"]?.takeUnless { it is JsonNull }?.let { it.jsonPrimitive.double },
            localTangentDeg = o["localTangentDeg"]?.takeUnless { it is JsonNull }?.let { it.jsonPrimitive.double },
            matchedStable = o.getValue("matchedStable").jsonPrimitive.boolean,
            roadClass = o["roadClass"]?.takeUnless { it is JsonNull }?.let { it.jsonPrimitive.content },
            hypotheses = o.getValue("hypotheses").jsonArray.map { decodeCorridor(it.jsonObject) },
            branches = o.getValue("branches").jsonArray.map { decodeCorridor(it.jsonObject) },
            capabilities = o.getValue("capabilities").jsonArray.map { it.jsonPrimitive.content },
            cameraHorizontalFovDeg = o["cameraHorizontalFovDeg"]?.takeUnless { it is JsonNull }?.let { it.jsonPrimitive.double },
            cameraYawDeg = o["cameraYawDeg"]?.takeUnless { it is JsonNull }?.let { it.jsonPrimitive.double },
            postedSpeedKmh = o["postedSpeedKmh"]?.takeUnless { it is JsonNull }?.jsonPrimitive?.int
        )
    }
    fun encodeRoad(v: TrafficSignMapContextSnapshot): JsonObject = buildJsonObject {
        put("snapshotId", JsonPrimitive(v.snapshotId))
        put("capturedAtMs", JsonPrimitive(v.capturedAtMs))
        put("scope", encodeScope(v.scope))
        put("wayId", v.wayId?.let { JsonPrimitive(it) } ?: JsonNull)
        put("horizontalAccuracyM", v.horizontalAccuracyM?.let { JsonPrimitive(it) } ?: JsonNull)
        put("courseAccuracyDeg", v.courseAccuracyDeg?.let { JsonPrimitive(it) } ?: JsonNull)
        put("courseDeg", v.courseDeg?.let { JsonPrimitive(it) } ?: JsonNull)
        put("localTangentDeg", v.localTangentDeg?.let { JsonPrimitive(it) } ?: JsonNull)
        put("matchedStable", JsonPrimitive(v.matchedStable))
        put("roadClass", v.roadClass?.let { JsonPrimitive(it) } ?: JsonNull)
        put("hypotheses", JsonArray(v.hypotheses.map { encodeCorridor(it) }))
        put("branches", JsonArray(v.branches.map { encodeCorridor(it) }))
        put("capabilities", JsonArray(v.capabilities.map { JsonPrimitive(it) }))
        put("cameraHorizontalFovDeg", v.cameraHorizontalFovDeg?.let { JsonPrimitive(it) } ?: JsonNull)
        put("cameraYawDeg", v.cameraYawDeg?.let { JsonPrimitive(it) } ?: JsonNull)
        v.postedSpeedKmh?.let { put("postedSpeedKmh", it) }
    }
    fun decodeBatch(o: JsonObject): TSRFrameCandidateBatch {
        require(o.keys.all { it in setOf("schemaVersion", "frameId", "capturedAtMs", "scope", "status", "candidates", "truncated", "rawCandidateCount", "modelId", "preprocessingId", "road") } && o.keys.containsAll(setOf("schemaVersion", "frameId", "capturedAtMs", "scope", "status", "candidates", "truncated", "rawCandidateCount", "modelId", "preprocessingId"))) { "Invalid batch fields" }
        return TSRFrameCandidateBatch(
            schemaVersion = o.getValue("schemaVersion").jsonPrimitive.int,
            frameId = o.getValue("frameId").jsonPrimitive.content,
            capturedAtMs = o.getValue("capturedAtMs").jsonPrimitive.double,
            scope = decodeScope(o.getValue("scope").jsonObject),
            status = o.getValue("status").jsonPrimitive.content,
            candidates = o.getValue("candidates").jsonArray.map { decodeCandidate(it.jsonObject) },
            truncated = o.getValue("truncated").jsonPrimitive.boolean,
            rawCandidateCount = o.getValue("rawCandidateCount").jsonPrimitive.int,
            modelId = o.getValue("modelId").jsonPrimitive.content,
            preprocessingId = o.getValue("preprocessingId").jsonPrimitive.content,
            road = o["road"]?.takeUnless { it is JsonNull }?.let { decodeRoad(it.jsonObject) }
        )
    }
    fun encodeBatch(v: TSRFrameCandidateBatch): JsonObject = buildJsonObject {
        put("schemaVersion", JsonPrimitive(v.schemaVersion))
        put("frameId", JsonPrimitive(v.frameId))
        put("capturedAtMs", JsonPrimitive(v.capturedAtMs))
        put("scope", encodeScope(v.scope))
        put("status", JsonPrimitive(v.status))
        put("candidates", JsonArray(v.candidates.map { encodeCandidate(it) }))
        put("truncated", JsonPrimitive(v.truncated))
        put("rawCandidateCount", JsonPrimitive(v.rawCandidateCount))
        put("modelId", JsonPrimitive(v.modelId))
        put("preprocessingId", JsonPrimitive(v.preprocessingId))
        put("road", v.road?.let { encodeRoad(it) } ?: JsonNull)
    }
    fun decodeSample(o: JsonObject): TSRTrackSample {
        require(o.keys.all { it in setOf("frameId", "capturedAtMs", "candidate") } && o.keys.containsAll(setOf("frameId", "capturedAtMs", "candidate"))) { "Invalid sample fields" }
        return TSRTrackSample(
            frameId = o.getValue("frameId").jsonPrimitive.content,
            capturedAtMs = o.getValue("capturedAtMs").jsonPrimitive.double,
            candidate = decodeCandidate(o.getValue("candidate").jsonObject)
        )
    }
    fun encodeSample(v: TSRTrackSample): JsonObject = buildJsonObject {
        put("frameId", JsonPrimitive(v.frameId))
        put("capturedAtMs", JsonPrimitive(v.capturedAtMs))
        put("candidate", encodeCandidate(v.candidate))
    }
    fun decodeTrack(o: JsonObject): TSRPhysicalTrackSnapshot {
        require(o.keys.all { it in setOf("trackId", "scope", "samples", "visibility", "associationAmbiguous") } && o.keys.containsAll(setOf("trackId", "scope", "samples", "visibility", "associationAmbiguous"))) { "Invalid track fields" }
        return TSRPhysicalTrackSnapshot(
            trackId = o.getValue("trackId").jsonPrimitive.content,
            scope = decodeScope(o.getValue("scope").jsonObject),
            samples = o.getValue("samples").jsonArray.map { decodeSample(it.jsonObject) },
            visibility = o.getValue("visibility").jsonPrimitive.content,
            associationAmbiguous = o.getValue("associationAmbiguous").jsonPrimitive.boolean
        )
    }
    fun encodeTrack(v: TSRPhysicalTrackSnapshot): JsonObject = buildJsonObject {
        put("trackId", JsonPrimitive(v.trackId))
        put("scope", encodeScope(v.scope))
        put("samples", JsonArray(v.samples.map { encodeSample(it) }))
        put("visibility", JsonPrimitive(v.visibility))
        put("associationAmbiguous", JsonPrimitive(v.associationAmbiguous))
    }
    fun decodeDecision(o: JsonObject): TSRApplicabilityDecision {
        require(o.keys.all { it in setOf("schemaVersion", "policyVersion", "configHash", "frameId", "trackId", "scope", "roadSnapshotId", "classification", "reasons", "evidence", "imageSupport", "displayEligible", "immediateEligible", "passageEligible") } && o.keys.containsAll(setOf("schemaVersion", "policyVersion", "configHash", "frameId", "trackId", "scope", "classification", "reasons", "evidence", "imageSupport", "displayEligible", "immediateEligible", "passageEligible"))) { "Invalid decision fields" }
        return TSRApplicabilityDecision(
            schemaVersion = o.getValue("schemaVersion").jsonPrimitive.int,
            policyVersion = o.getValue("policyVersion").jsonPrimitive.content,
            configHash = o.getValue("configHash").jsonPrimitive.content,
            frameId = o.getValue("frameId").jsonPrimitive.content,
            trackId = o.getValue("trackId").jsonPrimitive.content,
            scope = decodeScope(o.getValue("scope").jsonObject),
            roadSnapshotId = o["roadSnapshotId"]?.takeUnless { it is JsonNull }?.let { it.jsonPrimitive.content },
            classification = o.getValue("classification").jsonPrimitive.content,
            reasons = o.getValue("reasons").jsonArray.map { it.jsonPrimitive.content },
            evidence = o.getValue("evidence").jsonArray.map { it.jsonPrimitive.content },
            imageSupport = o.getValue("imageSupport").jsonPrimitive.double,
            displayEligible = o.getValue("displayEligible").jsonPrimitive.boolean,
            immediateEligible = o.getValue("immediateEligible").jsonPrimitive.boolean,
            passageEligible = o.getValue("passageEligible").jsonPrimitive.boolean
        )
    }
    fun encodeDecision(v: TSRApplicabilityDecision): JsonObject = buildJsonObject {
        put("schemaVersion", JsonPrimitive(v.schemaVersion))
        put("policyVersion", JsonPrimitive(v.policyVersion))
        put("configHash", JsonPrimitive(v.configHash))
        put("frameId", JsonPrimitive(v.frameId))
        put("trackId", JsonPrimitive(v.trackId))
        put("scope", encodeScope(v.scope))
        put("roadSnapshotId", v.roadSnapshotId?.let { JsonPrimitive(it) } ?: JsonNull)
        put("classification", JsonPrimitive(v.classification))
        put("reasons", JsonArray(v.reasons.map { JsonPrimitive(it) }))
        put("evidence", JsonArray(v.evidence.map { JsonPrimitive(it) }))
        put("imageSupport", JsonPrimitive(v.imageSupport))
        put("displayEligible", JsonPrimitive(v.displayEligible))
        put("immediateEligible", JsonPrimitive(v.immediateEligible))
        put("passageEligible", JsonPrimitive(v.passageEligible))
    }
    fun decodeDiagnostic(o: JsonObject): TSRApplicabilityDiagnostic {
        require(o.keys.all { it in setOf("schemaVersion", "batch", "tracks", "decisions") } && o.keys.containsAll(setOf("schemaVersion", "batch", "tracks", "decisions"))) { "Invalid diagnostic fields" }
        return TSRApplicabilityDiagnostic(
            schemaVersion = o.getValue("schemaVersion").jsonPrimitive.int,
            batch = decodeBatch(o.getValue("batch").jsonObject),
            tracks = o.getValue("tracks").jsonArray.map { decodeTrack(it.jsonObject) },
            decisions = o.getValue("decisions").jsonArray.map { decodeDecision(it.jsonObject) }
        )
    }
    fun encodeDiagnostic(v: TSRApplicabilityDiagnostic): JsonObject = buildJsonObject {
        put("schemaVersion", JsonPrimitive(v.schemaVersion))
        put("batch", encodeBatch(v.batch))
        put("tracks", JsonArray(v.tracks.map { encodeTrack(it) }))
        put("decisions", JsonArray(v.decisions.map { encodeDecision(it) }))
    }
}
