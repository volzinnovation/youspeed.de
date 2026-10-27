package de.youspeed.android.alpha

import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import java.io.Closeable
import java.io.File
import java.io.FileOutputStream
import java.time.Duration
import java.time.Instant
import java.util.UUID
import kotlin.math.*
import kotlinx.serialization.json.*
import org.json.JSONArray

internal object InventorySignSourceScope {
    fun allowsMobiData(countryCode: String?, dbPath: String, sourceInputPbf: String? = null): Boolean {
        if (countryCode != null && countryCode.uppercase() !in setOf("DE", "DEU")) return false
        val identity = (sourceInputPbf ?: dbPath).lowercase().replace('_', '-')
        return "baden-wuerttemberg" in identity || "baden-württemberg" in identity
    }
    fun allowsMobiData(db: RuntimeSqlDatabase, path: String, countryCode: String? = null): Boolean {
        fun metadata(key: String): String? = runCatching {
            db.rawQuery("SELECT value FROM metadata WHERE key=? LIMIT 1", arrayOf(key)).use { if (it.moveToFirst()) it.getString(0) else null }
        }.getOrNull()
        return allowsMobiData(countryCode ?: metadata("country_code"), path, metadata("source_input_pbf"))
    }
}

internal class CameraTownLocalityLatch {
    var insideCity: Boolean? = null; private set
    var observedAt: Instant? = null; private set
    private var country: String? = null
    fun reset() { insideCity = null; observedAt = null; country = null }
    fun observe(insideCity: Boolean, at: Instant, countryCode: String?) {
        if (observedAt?.let { at < it } == true) return
        this.insideCity = insideCity; observedAt = at; country = countryCode?.let(RoadSpeedDefaults::country)
    }
    fun selectCountry(countryCode: String?) {
        if (countryCode != null && country != null && RoadSpeedDefaults.country(countryCode) != country) reset()
    }
    fun supersedeByPhysicalBoundary(at: Instant): Boolean {
        val previous = observedAt ?: return true
        if (at <= previous) return false
        reset(); return true
    }
    fun applying(original: SpeedLookupResult, countryCode: String?, region: String? = null): SpeedLookupResult {
        val inside = insideCity ?: return original
        val exact = original.speedSource in setOf(DerivedSpeedSource.EXPLICIT_TAG, DerivedSpeedSource.EXPLICIT_UNLIMITED_TAG, DerivedSpeedSource.DIRECTIONAL_UNRESOLVED) || original.conditionalRuleContext != null
        if (original.wayId == null || exact) return original.copy(insideCity = inside, citySource = SOURCE)
        val unlimited = !inside && original.highway == "motorway" && RoadSpeedDefaults.country(countryCode) == "DE"
        return original.copy(insideCity = inside, citySource = SOURCE,
            speedLimitKmh = if (unlimited) null else TrafficSignRoadDefaultPolicy.speedKmh(countryCode, region, original.highway, inside),
            isUnlimitedSpeedLimit = unlimited, speedSource = DerivedSpeedSource.HIGHWAY_CLASS,
            bundleSpeedProvenance = DriveEvidencePresentation.mapProvenance(DerivedSpeedSource.HIGHWAY_CLASS, original.wayId, original.travelDirection))
    }
    companion object { const val SOURCE = "settlement:camera_town:high" }
}

/** Optional v1.5 evidence. Missing capability/tables is exactly the legacy path. */
internal data class InventorySign(
    val id: String, val sourceId: String, val recordKey: String, val snapshotSha256: String,
    val code: String, val kind: String, val value: Double?, val unit: String?, val parameterStatus: String,
    val latitude: Double, val longitude: Double, val radiusMeters: Double,
    val pictogramPath: String?, val modelClasses: Set<String>,
    val associatedWayId: String? = null, val associatedDirection: Int? = null, val associationStatus: String? = null,
    val associatedHeadingDeg: Double? = null,
) {
    val confirmationEligible: Boolean get() = parameterStatus in setOf("not_applicable", "parsed_source_value", "missing_value")
    val requiresWayAssociation: Boolean get() = kind in setOf("speed_limit", "speed_limit_end", "settlement_boundary") || code == "DE:282"
    val sourceTravelHeading: Double? get() = associatedHeadingDeg?.takeIf {
        associationStatus == "accepted" && associatedDirection in setOf(-1,1) && it.isFinite() && it >= 0.0 && it < 360.0
    }?.let { (it + if (associatedDirection == -1) 180.0 else 0.0) % 360.0 }
    fun secondaryFaceRelation(fix: InventorySignFix): String {
        if (requiresWayAssociation) return "directed_target"
        val source = sourceTravelHeading ?: return "face_unknown"
        val heading = fix.heading?.takeIf { it.isFinite() && it >= 0.0 && it < 360.0 } ?: return "face_unknown"
        if (fix.headingAccuracy?.let { it.isFinite() && it in 0.0..35.0 } != true) return "face_unknown"
        val delta = abs(((heading-source+540.0)%360.0)-180.0)
        return if (delta > 90.0) "known_opposite_face" else "face_compatible"
    }
    fun isKnownOppositeFace(fix: InventorySignFix): Boolean = secondaryFaceRelation(fix) == "known_opposite_face"
    val parameterText: String? get() = value?.let { "${if (it == it.toLong().toDouble()) it.toLong().toString() else it.toString()} ${unit.orEmpty()}".trim() }
    fun pictogram(): TrafficSignPictogram? = pictogramPath?.takeIf {
        it.startsWith("tsr/sign-pictograms/") && it.endsWith(".png") && ".." !in it.split('/')
    }?.let { TrafficSignPictogram("inventory:$id", it, mapOf("en" to code, "de" to code)) }
}
internal data class InventoryWayRule(
    val id: String, val sign: InventorySign, val wayId: String, val direction: Int,
    val start: Double, val end: Double, val station: Double, val heading: Double,
    val speedKmh: Int?, val insideCity: Boolean?,
)
internal data class InventorySignSnapshot(
    val supported: Boolean = false, val signs: List<InventorySign> = emptyList(),
    val rules: List<InventoryWayRule> = emptyList(), val chainage: Double? = null, val localHeading: Double? = null,
    val amendedNodes:List<AmendedNodeStation> = emptyList(),
)
internal data class InventorySignFix(
    val latitude: Double, val longitude: Double, val at: Instant, val accuracy: Double,
    val wayId: String?, val direction: Int, val stable: Boolean, val bundle: String,
    val heading: Double? = null, val headingAccuracy: Double? = null,
    val bundleSha256: String? = null, val bundleVersion: String? = null,
)
internal data class InventorySignDecision(
    val display: InventorySign? = null, val speedRule: InventoryWayRule? = null,
    val boundary: String? = null, val boundarySignId: String? = null,
    val captureSignIds: List<String> = emptyList(), val insideCityContext: Boolean? = null,
    val boundaryAction: TrafficSignAction? = null, val townResetWayId: String? = null,
    val endResetWayId: String? = null, val endResetDirection: Int = 0, val direction: Int = 0,
    val cityContextSign: InventorySign? = null, val resetContextSign: InventorySign? = null,
    val displayTriggeredAt: Instant? = null, val displayChanged: Boolean = false,
    val displayChangeReason: String? = null,
    val passedAmendedNodeIds:Set<String> = emptySet(),
) {
    fun masksPostedFallback(wayId: String?): Boolean = wayId != null && (wayId == townResetWayId ||
        (wayId == endResetWayId && (direction == 0 || direction == endResetDirection)))
    fun permitsPostedFallback(wayId: String?): Boolean = wayId != null && !masksPostedFallback(wayId)
}
internal data class InventoryVisionEvidence(
    val classId: String, val score: Double, val frameId: String, val at: Instant,
    val box: NormalizedTrafficSignBoundingBox, val trackId: String?, val packId: String,
    val modelHash: String, val wayId: String?, val direction: Int, val bundleRevision: String?,
)

/** Recomputes null-speed cancellations from context; a pre-sign posted OSM value is never reused. */
internal data class InventorySignRoadOffer(val speedKmh: Int?, val insideCity: Boolean?, val unlimited: Boolean) {
    companion object {
        fun from(rule: InventoryWayRule, baseInsideCity: Boolean?, highway: String?, country: String?): InventorySignRoadOffer {
            val inside = rule.insideCity ?: baseInsideCity
            val speed = rule.speedKmh ?: inside?.let {
                TrafficSignRoadDefaultPolicy.speedKmh(country, null, highway.takeUnless { inside == true }, inside)
            }
            val unlimited = rule.speedKmh == null && inside == false && highway == "motorway" && PenaltyCountryCodes.alpha2(country) == "DE"
            return InventorySignRoadOffer(if (unlimited) null else speed, inside, unlimited)
        }
    }
}

/** Separate append-only local journal. No image or upload payload is manufactured. */
internal class InventorySignJournal(private val path: File) {
    @Synchronized fun append(value: JsonObject) {
        path.parentFile?.mkdirs()
        FileOutputStream(path, true).use { output ->
            output.write((value.toString() + "\n").toByteArray(Charsets.UTF_8))
            output.fd.sync()
        }
    }
}

/** Shared with the iPhone adapter: measured radii, directional rules, real frames only. */
internal class InventorySignRuntime(private val persist: (JsonObject) -> Unit) {
    private val amendedNodePassages=AmendedNodePassageRuntime()
    private fun persistEvent(value: JsonObject) {
        persist(value)
        val confirmed = value["outcome"]?.jsonPrimitive?.contentOrNull == "camera_confirmed"
        val payload = value.mapValues { (_, element) -> journalValue(element) }.toMutableMap()
        payload["event_kind"] = if (confirmed) "inventory_camera_confirmation" else "inventory_encounter"
        payload["class_code"] = payload["observed_class"] ?: payload["expected_code"]
        payload["evidence_id"] = payload["event_id"]
        payload["source"] = if (confirmed) "camera" else when (payload["source_id"]) {
            "mobidata-bw-vzk" -> "government"
            "osm-settlement" -> "osm"
            else -> "inventory"
        }
        payload["confidence"] = payload["classifier_score"]
        payload["value"] = payload["observed_value"] ?: payload["numeric_value"]
        payload["units"] = payload["unit"]
        payload["accuracy"] = payload["accuracy_m"]
        payload["media_id"] = payload["capture_id"]
        TripJournal.existing()?.signEvent(payload, (payload["at"] as? Number)?.toDouble() ?: System.currentTimeMillis() / 1000.0)
    }
    private fun journalValue(value: JsonElement): Any? = when (value) {
        JsonNull -> null
        is JsonObject -> value.mapValues { journalValue(it.value) }
        is JsonArray -> value.map(::journalValue)
        is JsonPrimitive -> if (value.isString) value.content else value.booleanOrNull ?: value.longOrNull ?: value.doubleOrNull ?: value.content
    }
    private data class Encounter(val sign: InventorySign, val fix: InventorySignFix, val id: String = UUID.randomUUID().toString(),
        var lastFix: InventorySignFix = fix, var evidence: InventoryVisionEvidence? = null,
        var outcome: String? = null, var captured: Boolean = false, var analyzedFrames: Int = 0, var firstAnalyzedAt: Instant? = null, var lastAnalyzedAt: Instant? = null, val reportedOutcomes: MutableSet<String> = mutableSetOf(), val frameIds: MutableSet<String> = linkedSetOf())
    private var revision: String? = null
    private val encounters = linkedMapOf<String, Encounter>()
    private val pendingCaptures = linkedMapOf<String, Encounter>()
    private val boundaryApplied = mutableSetOf<String>()
    private val boundarySources = mutableMapOf<String, InventorySign>()
    private val knownDirections = linkedMapOf<String, Int>()
    private var priorWay: String? = null
    private var priorDirection = 0
    private var priorChainage: Double? = null
    private var priorAt: Instant? = null
    private var activeCancellation: String? = null
    private data class PendingBoundary(val sign: InventorySign, val event: String, val wayId: String?, val direction: Int) { val signId: String get() = sign.id }
    private var pendingBoundary: PendingBoundary? = null
    private var acceptedInsideCity: Boolean? = null
    private var acceptedCitySign: InventorySign? = null
    private var acceptedEndSign: InventorySign? = null
    private var selectedSecondary: InventorySign? = null
    private var secondaryTriggeredAt: Instant? = null
    private val cameraReplacedSecondaryIds = mutableSetOf<String>()
    private var acceptedTownResetWayId: String? = null
    private var endResetWayId: String? = null
    private var endResetDirection = 0
    private data class DeferredOutcome(val encounter: Encounter, val outcome: String, val event: JsonObject)
    private val deferredOutcomes = linkedMapOf<String, DeferredOutcome>()
    private var persistenceFailure: Throwable? = null

    @Synchronized fun evaluate(snapshot: InventorySignSnapshot, rawFix: InventorySignFix, now: Instant,
                               cameraEnabled: Boolean, cameraAvailable: Boolean): InventorySignDecision {
        val directed = rawFix.stable && rawFix.wayId != null && rawFix.direction in setOf(-1,1) &&
            snapshot.localHeading?.let { directionalHeadingAccepted(rawFix,rawFix.direction,it) } == true
        val fix = if (directed) rawFix else rawFix.copy(direction=0)
        flushDeferredOutcomes()
        if (revision != fix.bundle) { closeEncounters("camera_unavailable", "bundle_changed", now); reset(); revision = fix.bundle }
        val age = Duration.between(fix.at, now).toMillis()
        val usable = fix.latitude.isFinite() && fix.latitude in -90.0..90.0 && fix.longitude.isFinite() && fix.longitude in -180.0..180.0 && fix.accuracy.isFinite() && fix.accuracy in 0.0..25.0 && age in -1000..3000
        if (!snapshot.supported || !usable) {
            closeEncounters("camera_unavailable", if (!snapshot.supported) "no_sign_capability" else "invalid_fix", now)
            priorChainage = null; priorAt = null
            return InventorySignDecision(display = selectedSecondary, displayTriggeredAt = secondaryTriggeredAt,
                passedAmendedNodeIds=amendedNodePassages.evaluate(snapshot.amendedNodes,rawFix,now,null,null))
        }
        val departedBoundaries = boundarySources.filterValues { distance(fix.latitude, fix.longitude, it.latitude, it.longitude) > it.radiusMeters + 1e-6 }.keys.toList()
        boundaryApplied.removeAll(departedBoundaries.toSet())
        departedBoundaries.forEach(boundarySources::remove)
        val nearby = snapshot.signs.filter { distance(fix.latitude, fix.longitude, it.latitude, it.longitude) <= it.radiusMeters + 1e-6 }
        val nearbyIds = nearby.map { it.id }.toSet()
        cameraReplacedSecondaryIds.retainAll(nearbyIds)
        encounters.keys.filter { it !in nearbyIds }.toList().forEach { key ->
            val encounter = encounters.getValue(key)
            if (encounter.outcome == null) recordBestEffort(encounter, if (encounter.analyzedFrames >= 2 && encounter.firstAnalyzedAt?.let { first -> encounter.lastAnalyzedAt?.let { Duration.between(first, it).toMillis() >= 100 } } == true) "not_observed" else "camera_unavailable", now, "encounter_ended")
            encounters.remove(key)
            boundaryApplied.remove(key)
        }
        nearby.forEach { sign ->
            val previous = encounters[sign.id]
            if (previous != null && (previous.lastFix.wayId != fix.wayId || previous.lastFix.direction != fix.direction)) {
                if (previous.outcome == null) recordBestEffort(previous,"camera_unavailable",now,"road_context_changed")
                encounters.remove(sign.id)
            }
            val encounter = encounters.getOrPut(sign.id) { Encounter(sign, fix) }
            if (!cameraEnabled || !cameraAvailable) resetFrameEvidence(encounter)
            encounter.lastFix = fix
            if (cameraEnabled && cameraAvailable && encounter.outcome in setOf("camera_off", "camera_unavailable")) encounter.outcome = null
            if (encounter.outcome == null) when {
                !cameraEnabled -> recordBestEffort(encounter, "camera_off", now)
                !cameraAvailable -> recordBestEffort(encounter, "camera_unavailable", now)
                !sign.confirmationEligible -> recordBestEffort(encounter,"unsupported_model_class",now,"unverified_source_parameter")
                sign.isKnownOppositeFace(fix) -> recordBestEffort(encounter,"ambiguous",now,"known_opposite_face")
                sign.modelClasses.isEmpty() -> recordBestEffort(encounter, "unsupported_model_class", now)
                sign.requiresWayAssociation && (!fix.stable || sign.associationStatus != "accepted" || sign.associatedWayId != fix.wayId || sign.associatedDirection != fix.direction) ->
                    recordBestEffort(encounter, "ambiguous", now, "target_way_direction_unresolved")
            }
        }
        val rule = if (fix.stable && fix.wayId != null && fix.direction != 0 && snapshot.chainage != null) {
            val candidates = snapshot.rules.filter { it.wayId == fix.wayId && it.direction == fix.direction && headingAccepted(fix, it, snapshot.localHeading) &&
                if (fix.direction > 0) snapshot.chainage >= it.start && snapshot.chainage < it.end
                else snapshot.chainage > it.start && snapshot.chainage <= it.end }
            if (candidates.map { it.speedKmh to it.insideCity }.distinct().size > 1) null
            else candidates.sortedWith(compareBy<InventoryWayRule> { if (fix.direction > 0) -it.station else it.station }.thenBy { it.id }).firstOrNull()
        } else null
        if (fix.wayId != null && fix.direction != 0 && fix.stable) {
            if (knownDirections[fix.wayId]?.let { it != fix.direction } == true) { boundaryApplied.clear(); boundarySources.clear() }
            knownDirections[fix.wayId] = fix.direction
            if (knownDirections.size > 256) knownDirections.remove(knownDirections.keys.first())
        }
        var boundary: String? = null
        var boundarySign: String? = null
        val chainage = snapshot.chainage
        if (fix.stable && chainage != null && fix.direction != 0) {
            val boundaries = snapshot.rules.filter { (it.sign.code in setOf("DE:310", "DE:311", "DE:282") || it.sign.kind == "speed_limit_end") &&
                it.sign.associationStatus == "accepted" && it.sign.associatedWayId == fix.wayId && it.sign.associatedDirection == fix.direction &&
                it.wayId == fix.wayId && it.direction == fix.direction &&
                it.sign.id !in boundaryApplied && headingAccepted(fix, it, snapshot.localHeading) && run {
                    val sameTraversal = priorWay == fix.wayId && priorDirection == fix.direction && priorAt?.let { at -> Duration.between(at, fix.at).toMillis() in 1..3000 } == true
                    val crossed = sameTraversal && priorChainage?.let { previous ->
                        if (fix.direction > 0) previous < it.station && chainage >= it.station else previous > it.station && chainage <= it.station
                    } == true
                    val initialize = it.sign.id in nearbyIds && (priorWay != fix.wayId || priorDirection != fix.direction || priorChainage == null) &&
                        if (fix.direction > 0) chainage >= it.station else chainage <= it.station
                    crossed || initialize
                } }
            // One fix can cross several stations. Consume every crossed source
            // once and retain the final town context in travel order, even when
            // an ordinary speed-end station follows it within the same fix.
            val crossed = boundaries.distinctBy { it.sign.id }
            boundaryApplied += crossed.map { it.sign.id }
            val town = crossed.filter { it.sign.code in setOf("DE:310", "DE:311") }
            (if (town.isNotEmpty()) town else crossed).minByOrNull { abs(chainage - it.station) }?.let {
                boundary = when (it.sign.code) { "DE:310" -> "city_entry"; "DE:311" -> "city_exit"; else -> "applicable_end" }; boundarySign = it.sign.id
            }
        }
        val cancellation = rule?.takeIf { it.sign.kind == "speed_limit_end" || it.sign.code == "DE:282" }
        val cancellationIdentity = cancellation?.let { "${it.id}|${it.wayId}|${it.direction}" }
        if (cancellationIdentity != null && cancellationIdentity != activeCancellation && boundary !in setOf("city_entry", "city_exit")) {
            boundary = "applicable_end"; boundarySign = cancellation.sign.id; boundaryApplied += cancellation.sign.id
        }
        if (fix.stable && fix.direction != 0 && chainage != null && fix.heading != null && fix.headingAccuracy?.let { it in 0.0..35.0 } == true) activeCancellation = cancellationIdentity
        if (boundary != null && boundarySign != null) {
            val source = snapshot.rules.firstOrNull { it.sign.id == boundarySign }?.sign
                ?: snapshot.signs.firstOrNull { it.id == boundarySign }
            if (source != null) {
                boundarySources[source.id] = source
                pendingBoundary = PendingBoundary(source, requireNotNull(boundary), fix.wayId, fix.direction)
            }
        }
        else pendingBoundary?.takeIf { it.wayId == fix.wayId && it.direction == fix.direction }?.let {
            boundary = it.event; boundarySign = it.signId
        }
        if (boundarySign != null && boundarySign !in nearbyIds) {
            snapshot.rules.firstOrNull { it.sign.id == boundarySign }?.sign?.let { sign ->
                recordBestEffort(Encounter(sign, fix), if (!cameraEnabled) "camera_off" else "camera_unavailable", now, "crossed_without_geofence_fix")
            }
        }
        if (rule?.insideCity != null) {
            acceptedInsideCity = rule.insideCity
            if (rule.sign.kind == "settlement_boundary") acceptedCitySign = rule.sign
            if (rule.sign.kind == "settlement_boundary" && acceptedTownResetWayId == null) acceptedTownResetWayId = rule.sign.associatedWayId
        }
        if (boundary in setOf("city_entry", "city_exit")) {
            acceptedInsideCity = boundary == "city_entry"
            acceptedTownResetWayId = fix.wayId
            acceptedCitySign = boundarySign?.let { id -> snapshot.rules.firstOrNull { it.sign.id == id }?.sign }
            acceptedEndSign = null
            endResetWayId = null; endResetDirection = 0
        } else if (boundary == "applicable_end") {
            endResetWayId = fix.wayId; endResetDirection = fix.direction
            acceptedEndSign = boundarySign?.let { id -> snapshot.rules.firstOrNull { it.sign.id == id }?.sign }
        }
        priorWay = fix.wayId; priorDirection = fix.direction; priorChainage = chainage; priorAt = fix.at
        val eligibleSigns = nearby.filter { !it.isKnownOppositeFace(fix) && (!it.requiresWayAssociation || (fix.stable && it.associationStatus == "accepted" &&
            it.associatedWayId == fix.wayId && it.associatedDirection == fix.direction && fix.direction != 0)) }
        val previousSecondaryId = selectedSecondary?.id
        val heldOpposite = nearby.firstOrNull { it.id == previousSecondaryId && it.isKnownOppositeFace(fix) } != null
        if (heldOpposite) { selectedSecondary = null; secondaryTriggeredAt = null }
        val candidate = eligibleSigns.filter { it.kind != "speed_limit" && it.id !in cameraReplacedSecondaryIds }
            .sortedWith(compareBy<InventorySign> { distance(fix.latitude, fix.longitude, it.latitude, it.longitude) }.thenBy { it.id }).firstOrNull()
        if (candidate != null && candidate.id != selectedSecondary?.id) { selectedSecondary = candidate; secondaryTriggeredAt = fix.at }
        val displayChanged = selectedSecondary?.id != previousSecondaryId
        val passedNodes=amendedNodePassages.evaluate(snapshot.amendedNodes,rawFix,now,snapshot.chainage,snapshot.localHeading)
        return InventorySignDecision(selectedSecondary, rule, boundary, boundarySign,
            encounters.values.filter { !it.captured && it.sign.id in eligibleSigns.map { sign -> sign.id }.toSet() }.map { it.sign.id }, acceptedInsideCity,
            pendingBoundary?.takeIf { boundary == "applicable_end" && it.signId == boundarySign }?.sign?.let { source ->
                TrafficSignAction(if (source.code == "DE:282") TrafficSignActionKind.ALL_RESTRICTIONS_END else TrafficSignActionKind.MAXIMUM_SPEED_END,
                    valueKmh = source.value?.takeIf { source.unit == "km/h" }?.toInt())
            }, acceptedTownResetWayId, endResetWayId, endResetDirection, fix.direction,
            acceptedCitySign, acceptedEndSign, secondaryTriggeredAt, displayChanged,
            if (heldOpposite) "known_opposite_face" else if (displayChanged) "geofence_trigger" else null,passedNodes)
    }

    @Synchronized fun analyzedFrame(frameId: String, at: Instant, wayId: String?, direction: Int, now: Instant, bundleRevision: String?) {
        if (Duration.between(at, now).toMillis() !in -1000..3000) return
        encounters.values.filter { it.outcome in setOf(null, "camera_mismatch", "ambiguous") && it.lastFix.bundle == bundleRevision && it.lastFix.wayId == wayId && it.lastFix.direction != 0 && it.lastFix.direction == direction && it.lastFix.stable && at >= it.fix.at &&
            Duration.between(it.lastFix.at,now).toMillis() in -1000..3000 && Duration.between(it.lastFix.at, at).abs().toMillis() <= 3000 }.forEach {
            if (it.frameIds.add(frameId)) {
                it.analyzedFrames++
                if (it.firstAnalyzedAt == null || at < it.firstAnalyzedAt) it.firstAnalyzedAt = at
                if (it.lastAnalyzedAt == null || at > it.lastAnalyzedAt) it.lastAnalyzedAt = at
            }
            if (it.frameIds.size > 128) it.frameIds.remove(it.frameIds.first())
        }
    }

    @Synchronized fun observe(evidence: InventoryVisionEvidence, now: Instant) {
        if (!evidence.score.isFinite() || evidence.score < 0.9 || evidence.packId.isBlank() ||
            !evidence.modelHash.matches(Regex("[0-9a-fA-F]{64}")) ||
            Duration.between(evidence.at, now).toMillis() !in -1000..3000) return
        val eligible = encounters.values.filter { it.sign.confirmationEligible && !it.sign.isKnownOppositeFace(it.lastFix) && it.outcome in setOf(null, "camera_mismatch", "ambiguous") && evidence.bundleRevision == it.lastFix.bundle && evidence.wayId == it.lastFix.wayId &&
            evidence.direction != 0 && evidence.direction == it.lastFix.direction && it.lastFix.stable &&
            (if (it.sign.requiresWayAssociation || it.sign.associationStatus == "accepted")
                it.sign.associationStatus == "accepted" && it.sign.associatedWayId == evidence.wayId && it.sign.associatedDirection == evidence.direction else true) &&
            evidence.at >= it.fix.at && Duration.between(it.lastFix.at,now).toMillis() in -1000..3000 &&
            Duration.between(it.lastFix.at, evidence.at).abs().toMillis() <= 3000 }
        analyzedFrame(evidence.frameId, evidence.at, evidence.wayId, evidence.direction, now, evidence.bundleRevision)
        val matching = eligible.filter { evidence.classId in it.sign.modelClasses }
        if (matching.size > 1) { matching.forEach { record(it, "ambiguous", now, "multiple_inventory_candidates", evidence) }; return }
        if (matching.size == 1) {
            val encounter = matching.single()
            val previous = encounter.evidence
            val compatible = previous != null && previous.packId == evidence.packId && previous.modelHash == evidence.modelHash &&
                previous.classId == evidence.classId && (previous.trackId == null || evidence.trackId == null || previous.trackId == evidence.trackId) &&
                iou(previous.box, evidence.box) >= 0.3
            val span = previous?.let { Duration.between(it.at, evidence.at).toMillis() }
            if (compatible && previous!!.frameId != evidence.frameId && span != null && span in 100L..2000L) {
                record(encounter, "camera_confirmed", now, evidence = evidence, supporting = previous)
            } else if (previous == null || (evidence.at > previous.at && (!compatible || span!! > 2000))) {
                encounter.evidence = evidence
            }
            // Keep the first compatible frame while waiting: at 30fps consecutive frames
            // are only 33ms apart, but their accumulated span still reaches 100ms.
        } else if (evidence.classId.startsWith("maxspeed:")) {
            eligible.filter { it.sign.kind == "speed_limit" }.forEach { record(it, "camera_mismatch", now, "numeric_class_mismatch", evidence) }
        }
    }

    @Synchronized fun captureEligibleIds(ids: List<String>, latitude: Double, longitude: Double, at: Instant): List<String> =
        ids.mapNotNull(encounters::get).filter { !it.captured &&
            !it.sign.isKnownOppositeFace(it.lastFix) &&
            Duration.between(it.lastFix.at, at).toMillis() in -1000..3000 &&
            distance(latitude, longitude, it.sign.latitude, it.sign.longitude) <= it.sign.radiusMeters + 1e-6 }.map { it.sign.id }

    /** Validate the current encounter and freeze its UUID under the same runtime lock. */
    @Synchronized fun registerCaptureIfEligible(ids: List<String>, latitude: Double, longitude: Double, at: Instant): List<String>? {
        if (ids.isEmpty() || ids.size > 64 || ids.distinct().size != ids.size ||
            captureEligibleIds(ids,latitude,longitude,at).toSet() != ids.toSet()) return null
        val current=ids.map { encounters[it] ?: return null }
        if (current.any { it.sign.requiresWayAssociation && (!it.lastFix.stable || it.lastFix.direction == 0 ||
                it.sign.associationStatus != "accepted" || it.sign.associatedWayId != it.lastFix.wayId || it.sign.associatedDirection != it.lastFix.direction) }) return null
        return current.map { pendingCaptures[it.id]=it; it.id }
    }
    @Synchronized fun registerCapture(ids: List<String>): List<String> = ids.take(64).mapNotNull(encounters::get).map {
        pendingCaptures[it.id] = it; it.id
    }
    @Synchronized fun capturedEncounters(ids: List<String>, captureId: String, at: Instant) {
        ids.mapNotNull(pendingCaptures::get).forEach { encounter ->
            persistEvent(event(encounter, "capture_saved", at, "inventory_sign", captureId = captureId))
            encounter.captured = true; pendingCaptures.remove(encounter.id)
        }
    }
    @Synchronized fun captureFailedEncounters(ids: List<String>, reason: String, at: Instant) {
        ids.mapNotNull(pendingCaptures::get).forEach { encounter ->
            persistEvent(event(encounter, "capture_failed", at, reason)); pendingCaptures.remove(encounter.id)
        }
    }

    @Synchronized fun captured(ids: List<String>, captureId: String, at: Instant) {
        ids.mapNotNull(encounters::get).forEach { encounter ->
            persistEvent(event(encounter, "capture_saved", at, "inventory_sign", captureId = captureId)); encounter.captured = true
        }
    }
    @Synchronized fun captureFailed(ids: List<String>, reason: String, at: Instant) {
        ids.mapNotNull(encounters::get).forEach { persistEvent(event(it, "capture_failed", at, reason)) }
    }
    @Synchronized fun finish(at: Instant) { closeEncounters("camera_unavailable", "session_ended", at); reset() }
    @Synchronized fun replaceSecondaryWithCamera() { selectedSecondary?.id?.let(cameraReplacedSecondaryIds::add); selectedSecondary = null; secondaryTriggeredAt = null }
    @Synchronized fun isCurrentSecondary(id: String?, triggeredAt: Instant?): Boolean = selectedSecondary?.id == id && secondaryTriggeredAt == triggeredAt
    private fun reset() { amendedNodePassages.reset(); encounters.clear(); boundaryApplied.clear(); boundarySources.clear(); knownDirections.clear(); priorWay = null; priorDirection = 0; priorChainage = null; priorAt = null; activeCancellation = null; pendingBoundary = null; acceptedInsideCity = null; acceptedCitySign = null; acceptedEndSign = null; selectedSecondary = null; secondaryTriggeredAt = null; cameraReplacedSecondaryIds.clear(); acceptedTownResetWayId = null; endResetWayId = null; endResetDirection = 0 }
    private fun closeEncounters(outcome: String, reason: String, at: Instant) {
        encounters.values.filter { it.outcome == null }.forEach { recordBestEffort(it, outcome, at, reason) }; encounters.clear()
    }
    @Synchronized fun acknowledgeBoundary(signId: String?) {
        if (signId != null && pendingBoundary?.signId == signId) pendingBoundary = null
    }
    @Synchronized fun takePersistenceFailure(): Throwable? = persistenceFailure.also { persistenceFailure = null }
    private fun flushDeferredOutcomes() {
        val iterator = deferredOutcomes.iterator()
        while (iterator.hasNext()) {
            val (_, pending) = iterator.next()
            try {
                persistEvent(pending.event)
                if (pending.encounter.outcome == null) pending.encounter.outcome = pending.outcome
                iterator.remove()
            } catch (error: Exception) { persistenceFailure = error; break }
        }
    }
    private fun recordBestEffort(encounter: Encounter, outcome: String, at: Instant, reason: String? = null) {
        val key = "${encounter.id}|$outcome"
        if (key in deferredOutcomes) return
        val value = event(encounter, outcome, at, reason)
        try { persistEvent(value); encounter.outcome = outcome }
        catch (error: Exception) {
            persistenceFailure = error
            if (deferredOutcomes.size >= 256) deferredOutcomes.remove(deferredOutcomes.keys.first())
            deferredOutcomes[key] = DeferredOutcome(encounter, outcome, value)
        }
    }

    private fun resetFrameEvidence(encounter: Encounter) {
        encounter.evidence = null; encounter.analyzedFrames = 0; encounter.firstAnalyzedAt = null; encounter.lastAnalyzedAt = null; encounter.frameIds.clear()
    }
    private fun record(encounter: Encounter, outcome: String, at: Instant, reason: String? = null,
                       evidence: InventoryVisionEvidence? = null, supporting: InventoryVisionEvidence? = null) {
        if (outcome in setOf("camera_mismatch", "ambiguous") && outcome in encounter.reportedOutcomes) { encounter.evidence = null; return }
        // Commit first: a failed append cannot claim a durable confirmation.
        persistEvent(event(encounter, outcome, at, reason, evidence, supporting)); encounter.outcome = outcome
        if (outcome in setOf("camera_mismatch", "ambiguous")) { encounter.reportedOutcomes += outcome; encounter.evidence = null }
    }
    private fun event(encounter: Encounter, outcome: String, at: Instant, reason: String?, evidence: InventoryVisionEvidence? = null,
                      supporting: InventoryVisionEvidence? = null, captureId: String? = null) = buildJsonObject {
        put("schema_version", 1); put("event_id", UUID.randomUUID().toString()); put("encounter_id", encounter.id)
        put("source_id", encounter.sign.sourceId); put("record_key", encounter.sign.recordKey); put("snapshot_sha256", encounter.sign.snapshotSha256)
        put("bundle_revision", encounter.fix.bundle); put("bundle_sha256", encounter.fix.bundleSha256); put("bundle_version", encounter.fix.bundleVersion)
        put("phase", if (outcome.startsWith("capture_")) "capture" else "confirmation"); put("sign_id", encounter.sign.id); put("expected_code", encounter.sign.code)
        put("numeric_value", encounter.sign.value); put("unit", encounter.sign.unit); put("parameter_status", encounter.sign.parameterStatus)
        put("sign_latitude", encounter.sign.latitude); put("sign_longitude", encounter.sign.longitude)
        put("target_way_id", encounter.sign.associatedWayId); put("target_direction", encounter.sign.associatedDirection); put("association_status", encounter.sign.associationStatus)
        put("outcome", outcome); put("at", at.epochSecond + at.nano / 1e9); put("started_at", encounter.fix.at.epochSecond + encounter.fix.at.nano / 1e9); put("last_fix_at", encounter.lastFix.at.epochSecond + encounter.lastFix.at.nano / 1e9)
        put("latitude", encounter.lastFix.latitude); put("longitude", encounter.lastFix.longitude); put("accuracy_m", encounter.lastFix.accuracy)
        put("way_id", encounter.lastFix.wayId); put("direction", encounter.lastFix.direction.takeIf { it != 0 }); put("analyzed_frames", encounter.analyzedFrames)
        put("heading_deg", encounter.lastFix.heading); put("heading_accuracy_deg", encounter.lastFix.headingAccuracy)
        put("source_heading_deg", encounter.sign.sourceTravelHeading); put("face_relation", encounter.sign.secondaryFaceRelation(encounter.lastFix))
        reason?.let { put("reason", it) }; captureId?.let { put("capture_id", it) }
        evidence?.let {
            put("observed_class", it.classId); put("classifier_score", it.score); put("pack_id", it.packId); put("model_sha256", it.modelHash)
            put("frame_ids", buildJsonArray { supporting?.let { p -> add(p.frameId) }; add(it.frameId) }); put("track_id", it.trackId)
        }
    }
    companion object {
        private fun headingAccepted(fix: InventorySignFix, rule: InventoryWayRule, projectedHeading: Double? = null): Boolean =
            directionalHeadingAccepted(fix,rule.direction,projectedHeading ?: rule.heading)
        private fun directionalHeadingAccepted(fix: InventorySignFix, direction: Int, localHeading: Double): Boolean {
            val heading = fix.heading?.takeIf { it.isFinite() } ?: return false
            val accuracy = fix.headingAccuracy?.takeIf { it.isFinite() && it in 0.0..35.0 } ?: return false
            val expected = (localHeading + if (direction < 0) 180.0 else 0.0) % 360
            val difference = abs(((heading - expected + 540) % 360) - 180)
            return difference <= 35 && accuracy <= 35
        }
        fun distance(lat: Double, lon: Double, lat2: Double, lon2: Double): Double {
            val dy = Math.toRadians(lat2 - lat); val dx = Math.toRadians(lon2 - lon)
            return 6371008.8 * 2 * asin(sqrt((sin(dy / 2).pow(2) + cos(Math.toRadians(lat)) * cos(Math.toRadians(lat2)) * sin(dx / 2).pow(2)).coerceIn(0.0, 1.0)))
        }
        private fun iou(a: NormalizedTrafficSignBoundingBox, b: NormalizedTrafficSignBoundingBox): Double {
            val intersection = max(0.0, min(a.x + a.width, b.x + b.width) - max(a.x, b.x)) * max(0.0, min(a.y + a.height, b.y + b.height) - max(a.y, b.y))
            return intersection / (a.width * a.height + b.width * b.height - intersection).coerceAtLeast(1e-12)
        }
    }
}

/** Named optional columns only; old and non-BW databases have no side effects. */
internal class InventorySignDatabase(private val path: String,
    private val amendmentStore:MapDataAmendmentStore?=MapDataAmendmentStore.applicationStore(),
    baseIdentityOverride:String?=null) : Closeable {
    private val runtimeDatabase = RuntimeMapDatabase.open(path)
    private val db = runtimeDatabase.database
    private val genericNodes=RuntimeGenericSpeedNodes.openForDatabase(path)
    private val generation=baseIdentityOverride?:db.amendmentBaseIdentity
    private val sourceFilter = if (InventorySignSourceScope.allowsMobiData(db, path)) "" else " AND s.source_id <> 'mobidata-bw-vzk'"
    private val supported = runCatching { db.rawQuery("SELECT value FROM traffic_sign_capability WHERE key='version'", null).use { it.moveToFirst() && it.getString(0) == "1" } }.getOrDefault(false)
    private fun amendmentNode(record:MapDataAmendment):org.json.JSONObject? {
        val current=if(record.sourceNamespace=="osm")genericNodes?.sourceJSON(record.sourceId) else record.nodeJSON
        if(record.sourceRevision.startsWith("node-json-sha256:")&&
            (current==null||record.sourceRevision!="node-json-sha256:"+MapDataAmendmentStore.sourceSHA256(current)))return null
        return (current?:record.nodeJSON)?.let{org.json.JSONObject(it)}
    }
    fun read(latitude: Double, longitude: Double, wayId: String?, direction: Int): InventorySignSnapshot {
        val amendments=if(wayId!=null&&generation!=null)amendmentStore?.confirmedNodeAmendments(wayId,generation).orEmpty() else emptyList()
        if (!supported&&amendments.isEmpty()) return InventorySignSnapshot()
        val signs = if(!supported)emptyList() else db.rawQuery("SELECT s.*,a.way_id AS target_way_id,a.direction AS target_direction,a.status AS target_association_status,a.local_heading_deg AS target_heading_deg FROM traffic_sign_runtime s LEFT JOIN traffic_sign_association a ON a.sign_id=s.sign_id WHERE s.lat BETWEEN ? AND ? AND s.lon BETWEEN ? AND ?" + sourceFilter,
            arrayOf((latitude - .00065).toString(), (latitude + .00065).toString(), (longitude - .001).toString(), (longitude + .001).toString())).use { cursor -> buildList { while (cursor.moveToNext()) add(cursor.sign()) } }
        if (wayId == null) return InventorySignSnapshot(true, signs)
        val rules = if(!supported||direction==0)emptyList() else db.rawQuery("SELECT s.*,a.way_id AS target_way_id,a.direction AS target_direction,a.status AS target_association_status,a.local_heading_deg AS target_heading_deg,r.rule_id,r.way_id,r.direction,r.start_chainage_m,r.end_chainage_m,r.station_chainage_m,r.local_heading_deg,r.speed_kmh,r.inside_city FROM traffic_sign_way_rule r JOIN traffic_sign_runtime s ON s.sign_id=r.sign_id LEFT JOIN traffic_sign_association a ON a.sign_id=s.sign_id WHERE r.way_id=? AND r.direction=? AND r.association_status='accepted' AND r.lane_scope='all' AND a.status='accepted'" + sourceFilter,
            arrayOf(wayId, direction.toString())).use { cursor -> buildList { while (cursor.moveToNext()) add(InventoryWayRule(cursor.string("rule_id"), cursor.sign(), cursor.string("way_id"), cursor.int("direction"), cursor.double("start_chainage_m"), cursor.double("end_chainage_m"), cursor.double("station_chainage_m"), cursor.double("local_heading_deg"), cursor.nullInt("speed_kmh"), cursor.nullInt("inside_city")?.let { it != 0 })) } }
        val boundaryStations = if(!supported||direction==0)emptyList() else db.rawQuery("SELECT s.*,a.way_id AS target_way_id,a.direction AS target_direction,a.status AS target_association_status,a.local_heading_deg AS target_heading_deg,a.way_id,a.direction,a.station_chainage_m,a.local_heading_deg FROM traffic_sign_association a JOIN traffic_sign_runtime s ON s.sign_id=a.sign_id WHERE a.way_id=? AND a.direction=? AND a.status='accepted' AND (s.kind IN ('settlement_boundary','speed_limit_end') OR s.sign_code='DE:282')" + sourceFilter,
            arrayOf(wayId, direction.toString())).use { cursor -> buildList { while (cursor.moveToNext()) {
                val sign = cursor.sign(); val station = cursor.double("station_chainage_m")
                add(InventoryWayRule("boundary:${sign.id}", sign, wayId, direction, station, station, station,
                    cursor.double("local_heading_deg"), null, when (sign.code) { "DE:310" -> true; "DE:311" -> false; else -> null }))
            } } }
        val points = db.rawQuery("SELECT points_json FROM way_geom WHERE way_id=?", arrayOf(wayId)).use { if (it.moveToFirst()) JSONArray(it.getString(0)) else null }
        var bestDistance = Double.POSITIVE_INFINITY; var bestChainage: Double? = null; var bestHeading: Double? = null; var chainage = 0.0
        if (points != null) for (i in 0 until points.length() - 1) {
            val a = points.getJSONArray(i); val b = points.getJSONArray(i + 1)
            val scale = Math.PI / 180 * 6371008.8; val xScale = scale * cos(Math.toRadians(latitude))
            val ax = (a.getDouble(1) - longitude) * xScale; val ay = (a.getDouble(0) - latitude) * scale
            val dx = (b.getDouble(1) - a.getDouble(1)) * xScale; val dy = (b.getDouble(0) - a.getDouble(0)) * scale
            val length = hypot(dx, dy); if (length <= 0) continue
            val geodesicLength = InventorySignRuntime.distance(a.getDouble(0),a.getDouble(1),b.getDouble(0),b.getDouble(1)) * (6371000.0 / 6371008.8)
            val fraction = (-(ax * dx + ay * dy) / (length * length)).coerceIn(0.0, 1.0)
            val distance = hypot(ax + fraction * dx, ay + fraction * dy)
            if (distance < bestDistance) { bestDistance = distance; bestChainage = chainage + fraction * geodesicLength; bestHeading = (Math.toDegrees(atan2(dx,dy)) + 360) % 360 }
            chainage += geodesicLength
        }
        val stations=amendments.mapNotNull {AmendedNodePassageRuntime.station(it,amendmentNode(it),chainage)}
        val amendedSigns=stations.mapNotNull { station ->
            if(InventorySignRuntime.distance(latitude,longitude,station.latitude,station.longitude)>station.radius)return@mapNotNull null
            val record=amendments.firstOrNull{it.id==station.recordId}?:return@mapNotNull null
            val source=amendmentNode(record)?:return@mapNotNull null
            val tags=source.optJSONObject("tags")
            InventorySign(station.sourceId,"local-map-amendment",record.id,record.sourceRevision,
                tags?.optString("traffic_sign")?.takeIf{it.isNotBlank()}?:"maxspeed","speed_limit",
                tags?.optString("maxspeed")?.toDoubleOrNull(),"km/h","parsed_source_value",
                station.latitude,station.longitude,station.radius,null,emptySet(),station.wayId,station.direction,"accepted",bestHeading)
        }
        return InventorySignSnapshot(true, signs+amendedSigns, rules + boundaryStations, bestChainage.takeIf { bestDistance <= 30 }, bestHeading.takeIf { bestDistance <= 30 },stations)
    }
    fun applyNodeAmendments(result:SpeedLookupResult,fix:InventorySignFix,decision:InventorySignDecision,country:String?,atMs:Long=System.currentTimeMillis()):SpeedLookupResult {
        val way=result.wayId?:return result
        // The independent government/inventory producer keeps its existing priority.
        if(result.bundleSpeedProvenance?.kind?.startsWith("inventory")==true||generation==null||decision.passedAmendedNodeIds.isEmpty())return result
        val store=amendmentStore?:return result
        val sourceWayRules=runCatching {db.rawQuery("SELECT rules_json FROM road_speed_rule_set WHERE way_id=?",arrayOf(way)).use {
            if(it.moveToFirst())it.getString(0) else null
        }}.getOrNull()
        val offer=store.resolve(way,generation,fix.direction.takeIf{it!=0},
            ConditionalSpeedRules.Context(atMs,countryCode=country,direction=fix.direction.takeIf{it!=0}),
            result.speedLimitKmh,result.isUnlimitedSpeedLimit,decision.passedAmendedNodeIds,
            baselineResult=ConditionalSpeedRules.Result(result.speedLimitKmh,result.isUnlimitedSpeedLimit,
                result.speedLimitKmh==null&&!result.isUnlimitedSpeedLimit,"map_baseline_unresolved",result.conditionalRuleContext),
            sourceWayRulesJSON=sourceWayRules)?:return result
        val rule=offer.reevaluation
        return result.copy(speedLimitKmh=offer.kmh,isUnlimitedSpeedLimit=offer.unlimited,conditionalRuleContext=rule)
    }
    override fun close() {try{genericNodes?.close()}finally{runtimeDatabase.close()}}
    private fun Cursor.index(name: String) = getColumnIndexOrThrow(name)
    private fun Cursor.string(name: String) = getString(index(name))
    private fun Cursor.double(name: String) = getDouble(index(name))
    private fun Cursor.int(name: String) = getInt(index(name))
    private fun Cursor.nullInt(name: String): Int? = if (isNull(index(name))) null else int(name)
    private fun Cursor.nullString(name: String): String? = if (isNull(index(name))) null else string(name)
    private fun Cursor.sign(): InventorySign {
        val classes = JSONArray(string("model_classes_json"))
        return InventorySign(string("sign_id"), string("source_id"), string("record_key"), string("snapshot_sha256"), string("sign_code"), string("kind"),
            if (isNull(index("numeric_value"))) null else double("numeric_value"), nullString("unit"), string("parameter_status"), double("lat"), double("lon"), double("display_radius_m"), nullString("pictogram_path"),
            (0 until classes.length()).map { classes.getString(it) }.toSet(),
            nullString("target_way_id"), nullInt("target_direction"), nullString("target_association_status"),
            if (isNull(index("target_heading_deg"))) null else double("target_heading_deg"))
    }
}
