package de.youspeed.android.alpha

import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteException
import java.io.Closeable
import kotlin.math.abs
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import org.json.JSONArray
import org.json.JSONException

internal data class SpeedLookupResult(
    val wayId: String?,
    val highway: String?,
    val streetName: String?,
    val streetBaseName: String?,
    val streetRef: String?,
    val speedLimitKmh: Int?,
    val isUnlimitedSpeedLimit: Boolean,
    val cityName: String?,
    val insideCity: Boolean?,
    val citySource: String?,
    val queryTimeMs: Double,
    val candidateCount: Int,
    val speedCandidateCount: Int,
    val candidateTraces: List<MatcherCandidateTrace>,
    val nearestCandidateDistanceM: Double?,
    val nearestSpeedCandidateDistanceM: Double?,
    val isTunnelSegment: Boolean,
    val matchedEndpointProximityM: Double?,
    val streetRefTokens: List<String>,
    val nearbyTunnelCandidateWayIds: Set<String>,
    val nearbyTunnelCandidateRefs: Set<String>,
    val portalEligibleTunnelWayIds: Set<String>,
    val portalEligibleTunnelRefs: Set<String>,
    val activeCorridorState: CorridorMatchState?,
    val approachCorridorStateCandidate: CorridorMatchState?,
    val usedWalkingTurnSwitch: Boolean,
)

internal class V3SpeedLimitLookup(
    private val dbPath: String,
) : Closeable {
    private val db: SQLiteDatabase = SQLiteDatabase.openDatabase(dbPath, null, SQLiteDatabase.OPEN_READONLY)
    private val hasWaysTable = tableExists("ways")
    private val hasAreasTable = tableExists("areas")
    private val hasWaysRtreeTable = tableExists("ways_rtree")
    private val hasAreasRtreeTable = tableExists("areas_rtree")
    private val hasWayGeomTable = tableExists("way_geom")
    private val hasWayLinksTable = tableExists("way_links")
    private val hasCorridorProgressTable = tableExists("corridor_progress")
    private val hasWayBoundsColumns = hasBoundsColumns("ways")
    private val hasAreaBoundsColumns = hasBoundsColumns("areas")
    private val hasStreetNameColumn = columnExists("ways", "street_name")
    private val hasRefColumn = columnExists("ways", "ref")
    private val hasServiceColumn = columnExists("ways", "service")
    private val hasTunnelColumn = columnExists("ways", "tunnel")
    private val hasAreaResidentialColumn = columnExists("areas", "residential")
    private val hasAreaPointsColumn = columnExists("areas", "points_json")
    @Volatile private var allowWaysRtreeQueries = hasWaysRtreeTable
    @Volatile private var allowAreasRtreeQueries = hasAreasRtreeTable

    fun lookup(
        lat: Double,
        lon: Double,
        radiusM: Double,
        maxCandidates: Int,
        headingDeg: Double?,
        speedKmh: Double? = null,
        horizontalAccuracyM: Double? = null,
        gpsSignalBars: Int? = null,
        matchContext: WayMatchContext? = null,
    ): SpeedLookupResult {
        val startedAtNs = System.nanoTime()
        val normalizedMatchContext = matchContext ?: WayMatchContext()
        if (!hasWaysTable) {
            return SpeedLookupResult(
                wayId = null,
                highway = null,
                streetName = null,
                streetBaseName = null,
                streetRef = null,
                speedLimitKmh = null,
                isUnlimitedSpeedLimit = false,
                cityName = null,
                insideCity = null,
                citySource = null,
                queryTimeMs = elapsedMs(startedAtNs),
                candidateCount = 0,
                speedCandidateCount = 0,
                candidateTraces = emptyList(),
                nearestCandidateDistanceM = null,
                nearestSpeedCandidateDistanceM = null,
                isTunnelSegment = false,
                matchedEndpointProximityM = null,
                streetRefTokens = emptyList(),
                nearbyTunnelCandidateWayIds = emptySet(),
                nearbyTunnelCandidateRefs = emptySet(),
                portalEligibleTunnelWayIds = emptySet(),
                portalEligibleTunnelRefs = emptySet(),
                activeCorridorState = null,
                approachCorridorStateCandidate = null,
                usedWalkingTurnSwitch = false,
            )
        }

        val candidates = queryWayCandidates(
            lat = lat,
            lon = lon,
            radiusM = radiusM,
            maxCandidates = maxCandidates,
            headingDeg = headingDeg,
        )
        val areaCandidates = queryAreaCandidates(lat = lat, lon = lon)
        val cityContext = resolveCityContextFromAreas(lat = lat, lon = lon, areas = areaCandidates)
        val wayLinks = loadWayLinksContext(normalizedMatchContext, candidates)
        val corridorProgress = loadCorridorProgressContext(candidates)
        val accuracyBufferM = scaledAccuracyBufferM(horizontalAccuracyM)

        val selection = selectCandidate(
            candidates = candidates,
            radiusM = radiusM,
            observedHeadingDeg = headingDeg,
            speedKmh = speedKmh,
            accuracyBufferM = accuracyBufferM,
            horizontalAccuracyM = horizontalAccuracyM,
            gpsSignalBars = gpsSignalBars,
            matchContext = normalizedMatchContext,
            wayLinks = wayLinks,
            corridorProgress = corridorProgress,
        )
        val best = selection.selected
        val insideCityDecision = when {
            highwayImpliesInsideCity(best?.highway) -> true to "highway_class_in_city"
            else -> {
                val residential = resolveResidentialContext(lat = lat, lon = lon, areas = areaCandidates)
                residential.insideCity to if (residential.insideCity != null) "residential_polygon" else cityContext.citySource
            }
        }
        val effectiveSpeed = when {
            best?.isUnlimitedSpeedLimit == true -> null
            best?.speedLimitKmh != null && best.speedSource == DerivedSpeedSource.HIGHWAY_CLASS && allowsResidentialAreaFallback(best.highway) && insideCityDecision.first != null -> {
                if (insideCityDecision.first == true) 50 else 100
            }
            best?.speedLimitKmh != null -> best.speedLimitKmh
            best != null && allowsResidentialAreaFallback(best.highway) && insideCityDecision.first != null -> {
                if (insideCityDecision.first == true) 50 else 100
            }
            insideCityDecision.first == true -> 50
            else -> null
        }

        return SpeedLookupResult(
            wayId = best?.wayId,
            highway = best?.highway,
            streetName = best?.streetName,
            streetBaseName = best?.streetBaseName,
            streetRef = best?.streetRef,
            speedLimitKmh = effectiveSpeed,
            isUnlimitedSpeedLimit = best?.isUnlimitedSpeedLimit == true,
            cityName = cityContext.cityName,
            insideCity = insideCityDecision.first,
            citySource = insideCityDecision.second,
            queryTimeMs = elapsedMs(startedAtNs),
            candidateCount = candidates.size,
            speedCandidateCount = candidates.count { it.speedLimitKmh != null || it.isUnlimitedSpeedLimit },
            candidateTraces = selection.candidateTraces,
            nearestCandidateDistanceM = candidates.minOfOrNull { it.distanceM }?.takeIf { it.isFinite() },
            nearestSpeedCandidateDistanceM = candidates.filter { it.speedLimitKmh != null || it.isUnlimitedSpeedLimit }.minOfOrNull { it.distanceM }?.takeIf { it.isFinite() },
            isTunnelSegment = isTruthyOsmTag(best?.tunnel),
            matchedEndpointProximityM = best?.endpointProximityM,
            streetRefTokens = normalizedRefTokens(best?.streetRef),
            nearbyTunnelCandidateWayIds = selection.nearbyTunnelCandidateWayIds,
            nearbyTunnelCandidateRefs = selection.nearbyTunnelCandidateRefs,
            portalEligibleTunnelWayIds = selection.portalEligibleTunnelWayIds,
            portalEligibleTunnelRefs = selection.portalEligibleTunnelRefs,
            activeCorridorState = selection.activeCorridorState,
            approachCorridorStateCandidate = selection.approachCorridorStateCandidate,
            usedWalkingTurnSwitch = selection.usedWalkingTurnSwitch,
        )
    }

    fun lookupStreetNames(wayIds: List<String>): Map<String, String> {
        if (!hasWaysTable || (!hasStreetNameColumn && !hasRefColumn)) {
            return emptyMap()
        }
        val uniqueWayIds = wayIds.map { it.trim() }.filter { it.isNotEmpty() }.toSet().sorted()
        if (uniqueWayIds.isEmpty()) {
            return emptyMap()
        }

        val streetSelect = if (hasStreetNameColumn) "street_name" else "NULL"
        val refSelect = if (hasRefColumn) "ref" else "NULL"
        val resolved = linkedMapOf<String, String>()
        var cursorStart = 0
        val chunkSize = 200
        while (cursorStart < uniqueWayIds.size) {
            val cursorEnd = min(cursorStart + chunkSize, uniqueWayIds.size)
            val chunk = uniqueWayIds.subList(cursorStart, cursorEnd)
            val placeholders = chunk.indices.joinToString(",") { "?" }
            val sql = """
                SELECT way_id, $streetSelect AS street_name, $refSelect AS ref
                FROM ways
                WHERE way_id IN ($placeholders)
            """.trimIndent()
            db.rawQuery(sql, chunk.toTypedArray()).use { cursor ->
                while (cursor.moveToNext()) {
                    val wayId = cursor.stringOrNull(0) ?: continue
                    val streetName = cursor.stringOrNull(1)
                    val ref = cursor.stringOrNull(2)
                    val display = formattedStreetDisplay(streetName = streetName, ref = ref) ?: continue
                    resolved[wayId] = display
                }
            }
            cursorStart = cursorEnd
        }
        return resolved
    }

    override fun close() {
        if (db.isOpen) {
            db.close()
        }
    }

    private fun selectCandidate(
        candidates: List<WayCandidate>,
        radiusM: Double,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        accuracyBufferM: Double,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        corridorProgress: CorridorProgressContext,
    ): CandidateSelection {
        if (candidates.isEmpty()) {
            return CandidateSelection()
        }
        val sortedCandidates = candidates.sortedWith(candidateComparator)
        val bestGeometric = sortedCandidates.first()

        var preferredCandidate: WayCandidate? = null
        var sameRefCandidate: WayCandidate? = null
        var linkedWayCandidate: WayCandidate? = null
        var recentWayCandidate: WayCandidate? = null
        for (candidate in sortedCandidates) {
            when (continuityClass(candidate, matchContext, wayLinks)) {
                ContinuityClass.PREFERRED_WAY -> if (preferredCandidate == null) preferredCandidate = candidate
                ContinuityClass.SAME_REF -> if (sameRefCandidate == null) sameRefCandidate = candidate
                ContinuityClass.LINKED_WAY -> if (linkedWayCandidate == null) linkedWayCandidate = candidate
                ContinuityClass.RECENT_WAY -> if (recentWayCandidate == null) recentWayCandidate = candidate
                ContinuityClass.NONE -> Unit
            }
        }

        val portalEligibleTunnels = sortedCandidates.filter {
            isPortalEligibleTunnelCandidate(
                candidate = it,
                matchContext = matchContext,
                wayLinks = wayLinks,
                corridorProgress = corridorProgress,
                accuracyBufferM = accuracyBufferM,
            )
        }
        val nearbyTunnelCandidateWayIds = sortedCandidates.asSequence()
            .filter { isTruthyOsmTag(it.tunnel) }
            .mapNotNull { normalizedWayId(it.wayId) }
            .toCollection(linkedSetOf())
        val nearbyTunnelCandidateRefs = sortedCandidates.asSequence()
            .filter { isTruthyOsmTag(it.tunnel) }
            .flatMap { normalizedRefTokens(it.streetRef).asSequence() }
            .toCollection(linkedSetOf())
        val portalEligibleTunnelWayIds = portalEligibleTunnels.mapNotNullTo(linkedSetOf()) { normalizedWayId(it.wayId) }
        val portalEligibleTunnelRefs = portalEligibleTunnels.flatMapTo(linkedSetOf()) { normalizedRefTokens(it.streetRef) }

        var selected = bestGeometric
        var usedWalkingTurnSwitch = false

        preferredCandidate?.let { preferred ->
            if (shouldKeepContinuityCandidate(preferred, bestGeometric, radiusM, accuracyBufferM, PREFERRED_WAY_SCORE_SLACK_M, PREFERRED_WAY_DISTANCE_MULTIPLIER, PREFERRED_WAY_DISTANCE_FLOOR_M)) {
                selected = preferred
            }
        }
        sameRefCandidate?.let { sameRef ->
            val preferred = preferredCandidate
            val shouldPromote = if (preferred != null) {
                shouldPromoteSameRefTransition(preferred, sameRef, observedHeadingDeg, speedKmh, accuracyBufferM, wayLinks, matchContext)
            } else {
                shouldKeepContinuityCandidate(sameRef, selected, radiusM, accuracyBufferM, SAME_REF_SCORE_SLACK_M, SAME_REF_DISTANCE_MULTIPLIER, SAME_REF_DISTANCE_FLOOR_M)
            }
            if (shouldPromote || shouldKeepContinuityCandidate(sameRef, selected, radiusM, accuracyBufferM, SAME_REF_SCORE_SLACK_M, SAME_REF_DISTANCE_MULTIPLIER, SAME_REF_DISTANCE_FLOOR_M)) {
                selected = sameRef
            }
        }
        linkedWayCandidate?.let { linked ->
            val preferred = preferredCandidate
            val shouldPromote = preferred != null && shouldPromoteLinkedTransition(preferred, linked, observedHeadingDeg, speedKmh, accuracyBufferM, wayLinks)
            if (shouldPromote || shouldKeepContinuityCandidate(linked, selected, radiusM, accuracyBufferM, LINKED_WAY_SCORE_SLACK_M, LINKED_WAY_DISTANCE_MULTIPLIER, LINKED_WAY_DISTANCE_FLOOR_M)) {
                selected = linked
            }
        }
        recentWayCandidate?.let { recent ->
            if (shouldKeepContinuityCandidate(recent, selected, radiusM, accuracyBufferM, RECENT_WAY_SCORE_SLACK_M, RECENT_WAY_DISTANCE_MULTIPLIER, RECENT_WAY_DISTANCE_FLOOR_M)) {
                selected = recent
            }
        }
        preferredCandidate?.let { preferred ->
            if (shouldForceGeometricCandidateAtWalkingSpeed(preferred, bestGeometric, speedKmh, accuracyBufferM, matchContext)) {
                selected = bestGeometric
                usedWalkingTurnSwitch = true
            }
        }

        val bestPortalEligibleTunnel = portalEligibleTunnels.firstOrNull()
        if (bestPortalEligibleTunnel != null && bestPortalEligibleTunnel != selected) {
            if (shouldPromoteTunnelEntry(bestPortalEligibleTunnel, selected, matchContext, wayLinks, corridorProgress, horizontalAccuracyM, gpsSignalBars, accuracyBufferM)) {
                selected = bestPortalEligibleTunnel
            }
        }
        if (!isTruthyOsmTag(selected.tunnel) && matchContext.isInTunnelMode) {
            val tunnelContinuityCandidate = sortedCandidates.firstOrNull { candidate ->
                isTruthyOsmTag(candidate.tunnel) &&
                    (
                        normalizedWayId(candidate.wayId) in matchContext.recentTunnelCandidateWayIds ||
                            normalizedRefTokens(candidate.streetRef).any(matchContext.recentTunnelCandidateRefs::contains)
                        )
            }
            if (tunnelContinuityCandidate != null &&
                shouldKeepTunnelContinuity(
                    tunnelCandidate = tunnelContinuityCandidate,
                    surfaceCandidate = selected,
                    matchContext = matchContext,
                    wayLinks = wayLinks,
                    corridorProgress = corridorProgress,
                    accuracyBufferM = accuracyBufferM,
                    horizontalAccuracyM = horizontalAccuracyM,
                    gpsSignalBars = gpsSignalBars,
                )
            ) {
                selected = tunnelContinuityCandidate
            }
        }

        val selectedCorridorState = candidateCorridorState(selected, matchContext, wayLinks, corridorProgress)
        val activeCorridorState = when {
            selectedCorridorState != null && shouldTriggerActiveCorridorMode(selectedCorridorState, matchContext) -> selectedCorridorState.snapshot
            sameCorridorState(matchContext.activeCorridorState, selectedCorridorState?.snapshot) -> selectedCorridorState?.snapshot
            matchContext.activeCorridorState != null &&
                normalizedWayId(selected.wayId) == matchContext.preferredWayId &&
                isTruthyOsmTag(selected.tunnel) -> matchContext.activeCorridorState
            else -> null
        }
        val approachCorridorStateCandidate = sortedCandidates.asSequence()
            .mapNotNull { candidateCorridorState(it, matchContext, wayLinks, corridorProgress) }
            .filter { it.entryZone && (it.snapshot.kind == "tunnel" || it.snapshot.kind == "motorway") }
            .sortedWith(compareBy<CandidateCorridorState> { it.snapshot.depthM }.thenBy { it.snapshot.corridorId })
            .firstOrNull()
            ?.snapshot
        val selectedWayId = normalizedWayId(selected.wayId)
        val candidateTraces = sortedCandidates
            .take(MAX_TRACE_CANDIDATE_COUNT)
            .mapIndexed { index, candidate ->
                val continuity = continuityClass(candidate, matchContext, wayLinks)
                val corridorSelectable = candidateCorridorState(candidate, matchContext, wayLinks, corridorProgress) != null
                val portalEligible = isPortalEligibleTunnelCandidate(
                    candidate = candidate,
                    matchContext = matchContext,
                    wayLinks = wayLinks,
                    corridorProgress = corridorProgress,
                    accuracyBufferM = accuracyBufferM,
                )
                MatcherCandidateTrace(
                    rank = index + 1,
                    wayId = candidate.wayId,
                    score = candidate.score,
                    distanceM = candidate.distanceM,
                    geometryScore = candidate.score,
                    endpointProximityM = candidate.endpointProximityM,
                    continuityClass = continuity.traceName,
                    highway = candidate.highway,
                    service = candidate.service,
                    streetName = candidate.streetName,
                    streetRef = candidate.streetRef,
                    tunnel = candidate.tunnel,
                    tunnelSelectable = isTruthyOsmTag(candidate.tunnel) || portalEligible || corridorSelectable,
                    corridorSelectable = corridorSelectable,
                    portalEligible = portalEligible,
                    isSelected = normalizedWayId(candidate.wayId) == selectedWayId,
                )
            }

        return CandidateSelection(
            selected = selected,
            candidateTraces = candidateTraces,
            nearbyTunnelCandidateWayIds = nearbyTunnelCandidateWayIds,
            nearbyTunnelCandidateRefs = nearbyTunnelCandidateRefs,
            portalEligibleTunnelWayIds = portalEligibleTunnelWayIds,
            portalEligibleTunnelRefs = portalEligibleTunnelRefs,
            activeCorridorState = activeCorridorState,
            approachCorridorStateCandidate = approachCorridorStateCandidate,
            usedWalkingTurnSwitch = usedWalkingTurnSwitch,
        )
    }

    private fun loadWayLinksContext(
        matchContext: WayMatchContext,
        candidates: List<WayCandidate>,
    ): WayLinksContext {
        if (!hasWayLinksTable) {
            return WayLinksContext(available = false)
        }
        val wayIds = linkedSetOf<String>()
        candidates.mapNotNullTo(wayIds) { normalizedWayId(it.wayId) }
        matchContext.preferredWayId?.let(wayIds::add)
        wayIds += matchContext.recentWayIds
        if (wayIds.isEmpty()) {
            return WayLinksContext(available = true)
        }
        val placeholders = wayIds.joinToString(",") { "?" }
        val linkedByFrom = linkedMapOf<String, MutableSet<String>>()
        val sharedRefByFrom = linkedMapOf<String, MutableSet<String>>()
        val sharedNodeKeysByPair = linkedMapOf<Pair<String, String>, MutableSet<String>>()
        db.rawQuery(
            """
            SELECT way_id, linked_way_id, shared_ref, shared_node_key
            FROM way_links
            WHERE way_id IN ($placeholders) OR linked_way_id IN ($placeholders)
            """.trimIndent(),
            (wayIds + wayIds).toTypedArray(),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val from = cursor.stringOrNull(0) ?: continue
                val to = cursor.stringOrNull(1) ?: continue
                linkedByFrom.getOrPut(from) { linkedSetOf() } += to
                if (cursor.getInt(2) == 1) {
                    sharedRefByFrom.getOrPut(from) { linkedSetOf() } += to
                }
                cursor.stringOrNull(3)?.let { nodeKey ->
                    sharedNodeKeysByPair.getOrPut(from to to) { linkedSetOf() } += nodeKey
                }
            }
        }
        return WayLinksContext(
            available = true,
            linkedByFrom = linkedByFrom.mapValues { it.value.toSet() },
            sharedRefByFrom = sharedRefByFrom.mapValues { it.value.toSet() },
            sharedNodeKeysByPair = sharedNodeKeysByPair.mapValues { it.value.toSet() },
        )
    }

    private fun loadCorridorProgressContext(candidates: List<WayCandidate>): CorridorProgressContext {
        if (!hasCorridorProgressTable) {
            return CorridorProgressContext(available = false)
        }
        val wayIds = candidates.mapNotNull { normalizedWayId(it.wayId) }.distinct()
        if (wayIds.isEmpty()) {
            return CorridorProgressContext(available = true)
        }
        val placeholders = wayIds.joinToString(",") { "?" }
        val byWayId = linkedMapOf<String, MutableList<CorridorProgressInfo>>()
        db.rawQuery(
            """
            SELECT corridor_kind, corridor_id, side_node_key, way_id, start_depth_m, end_depth_m,
                   start_depth_nodes, end_depth_nodes, corridor_span_m, corridor_span_nodes
            FROM corridor_progress
            WHERE way_id IN ($placeholders)
            """.trimIndent(),
            wayIds.toTypedArray(),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val wayId = cursor.stringOrNull(3) ?: continue
                byWayId.getOrPut(wayId) { mutableListOf() } += CorridorProgressInfo(
                    kind = cursor.getString(0),
                    corridorId = cursor.getInt(1),
                    sideNodeKey = cursor.getString(2),
                    wayId = wayId,
                    startDepthM = cursor.getDouble(4),
                    endDepthM = cursor.getDouble(5),
                    startDepthNodes = cursor.getInt(6),
                    endDepthNodes = cursor.getInt(7),
                    spanM = cursor.getDouble(8),
                    spanNodes = cursor.getInt(9),
                )
            }
        }
        return CorridorProgressContext(
            available = true,
            byWayId = byWayId.mapValues { it.value.toList() },
        )
    }

    private fun continuityClass(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
    ): ContinuityClass {
        val candidateWayId = normalizedWayId(candidate.wayId)
        if (candidateWayId != null && candidateWayId == matchContext.preferredWayId) {
            return ContinuityClass.PREFERRED_WAY
        }
        val candidateRefTokens = normalizedRefTokens(candidate.streetRef).toSet()
        if (
            candidateRefTokens.isNotEmpty() &&
            (candidateRefTokens.any(matchContext.recentStreetRefs::contains))
        ) {
            if (wayLinks.available && !isLinkedCandidate(candidateWayId, matchContext, wayLinks)) {
                return ContinuityClass.NONE
            }
            return ContinuityClass.SAME_REF
        }
        if (isLinkedCandidate(candidateWayId, matchContext, wayLinks)) {
            return ContinuityClass.LINKED_WAY
        }
        if (candidateWayId != null && candidateWayId in matchContext.recentWayIds) {
            return ContinuityClass.RECENT_WAY
        }
        return ContinuityClass.NONE
    }

    private fun isLinkedCandidate(
        candidateWayId: String?,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        requireSharedRef: Boolean = false,
    ): Boolean {
        if (!wayLinks.available || candidateWayId == null) {
            return false
        }
        val anchors = linkedSetOf<String>()
        matchContext.preferredWayId?.let(anchors::add)
        anchors += matchContext.recentWayIds
        for (anchor in anchors) {
            if (anchor == candidateWayId) {
                continue
            }
            val linked = if (requireSharedRef) {
                wayLinks.isSharedRefLinked(anchor, candidateWayId)
            } else {
                wayLinks.isLinked(anchor, candidateWayId)
            }
            if (linked) {
                return true
            }
        }
        return false
    }

    private fun shouldKeepContinuityCandidate(
        continuityCandidate: WayCandidate,
        bestCandidate: WayCandidate,
        radiusM: Double,
        accuracyBufferM: Double,
        scoreSlackM: Double,
        distanceMultiplier: Double,
        distanceFloorM: Double,
    ): Boolean {
        val maxDistance = max(radiusM * distanceMultiplier, distanceFloorM) + accuracyBufferM
        return continuityCandidate.distanceM <= maxDistance &&
            continuityCandidate.score <= bestCandidate.score + scoreSlackM
    }

    private fun shouldForceGeometricCandidateAtWalkingSpeed(
        preferredCandidate: WayCandidate,
        geometricCandidate: WayCandidate,
        speedKmh: Double?,
        accuracyBufferM: Double,
        matchContext: WayMatchContext,
    ): Boolean {
        if (speedKmh == null || !speedKmh.isFinite() || speedKmh > WALKING_TURN_SWITCH_MAX_SPEED_KMH || matchContext.matchedFixCount < 3) {
            return false
        }
        if (normalizedWayId(preferredCandidate.wayId) == normalizedWayId(geometricCandidate.wayId)) {
            return false
        }
        if (geometricCandidate.service == "driveway") {
            return false
        }
        val requiredEndpointProximity = max(WALKING_TURN_SWITCH_ENDPOINT_M, min(accuracyBufferM, 6.0))
        val requiredPreferredDistance = max(WALKING_TURN_SWITCH_PREFERRED_DISTANCE_M, accuracyBufferM + 4.0)
        val allowedBestDistance = max(WALKING_TURN_SWITCH_BEST_DISTANCE_M, min(accuracyBufferM + 1.0, 6.0))
        val requiredGap = max(WALKING_TURN_SWITCH_MIN_GAP_M, accuracyBufferM + 1.5)
        return preferredCandidate.endpointProximityM <= requiredEndpointProximity &&
            preferredCandidate.distanceM >= requiredPreferredDistance &&
            geometricCandidate.distanceM <= allowedBestDistance &&
            preferredCandidate.distanceM >= geometricCandidate.distanceM + requiredGap &&
            preferredCandidate.distanceM >= geometricCandidate.distanceM * 2.5
    }

    private fun shouldPromoteSameRefTransition(
        preferredCandidate: WayCandidate,
        transitionCandidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        accuracyBufferM: Double,
        wayLinks: WayLinksContext,
        matchContext: WayMatchContext,
    ): Boolean {
        if (normalizedWayId(preferredCandidate.wayId) == normalizedWayId(transitionCandidate.wayId)) {
            return false
        }
        if (shouldSuppressImmediateSameRefBounce(transitionCandidate, preferredCandidate, matchContext, wayLinks, accuracyBufferM)) {
            return false
        }
        val preferredRefTokens = normalizedRefTokens(preferredCandidate.streetRef).toSet()
        val transitionRefTokens = normalizedRefTokens(transitionCandidate.streetRef).toSet()
        if (preferredRefTokens.isEmpty() || preferredRefTokens.intersect(transitionRefTokens).isEmpty()) {
            return false
        }
        val endpointThreshold = SEGMENT_TRANSITION_ENDPOINT_THRESHOLD_M + accuracyBufferM
        val preferredAtEndpoint = preferredCandidate.endpointProximityM <= endpointThreshold
        val transitionNearEndpoint = transitionCandidate.endpointProximityM <= (endpointThreshold * 2.0)
        val transitionNotFarther = transitionCandidate.distanceM <= preferredCandidate.distanceM + SEGMENT_TRANSITION_DISTANCE_SLACK_M + accuracyBufferM
        if (wayLinks.available && !isLinkedCandidate(normalizedWayId(transitionCandidate.wayId), matchContext, wayLinks)) {
            return false
        }
        if (shouldRejectTurnTransition(preferredCandidate, transitionCandidate, observedHeadingDeg, speedKmh, preferredCandidate.endpointProximityM)) {
            return false
        }
        return preferredAtEndpoint && transitionNearEndpoint && transitionNotFarther
    }

    private fun shouldPromoteLinkedTransition(
        preferredCandidate: WayCandidate,
        transitionCandidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        accuracyBufferM: Double,
        wayLinks: WayLinksContext,
    ): Boolean {
        val preferredWayId = normalizedWayId(preferredCandidate.wayId)
        val transitionWayId = normalizedWayId(transitionCandidate.wayId)
        if (
            !wayLinks.available ||
            preferredWayId == null ||
            transitionWayId == null ||
            preferredWayId == transitionWayId ||
            (!wayLinks.isLinked(preferredWayId, transitionWayId) && !wayLinks.isLinked(transitionWayId, preferredWayId))
        ) {
            return false
        }
        if (highwayFamily(preferredCandidate.highway) != highwayFamily(transitionCandidate.highway)) {
            return false
        }
        val endpointThreshold = SEGMENT_TRANSITION_ENDPOINT_THRESHOLD_M + accuracyBufferM
        val preferredAtEndpoint = preferredCandidate.endpointProximityM <= endpointThreshold
        val transitionNearEndpoint = transitionCandidate.endpointProximityM <= (endpointThreshold * 2.0)
        val transitionNotFarther = transitionCandidate.distanceM <= preferredCandidate.distanceM + SEGMENT_TRANSITION_DISTANCE_SLACK_M + accuracyBufferM
        val transitionScoreCompetitive = transitionCandidate.score <= preferredCandidate.score + LINKED_WAY_SCORE_SLACK_M + accuracyBufferM
        if (shouldRejectTurnTransition(preferredCandidate, transitionCandidate, observedHeadingDeg, speedKmh, preferredCandidate.endpointProximityM)) {
            return false
        }
        return preferredAtEndpoint && transitionNearEndpoint && transitionNotFarther && transitionScoreCompetitive
    }

    private fun shouldRejectTurnTransition(
        preferredCandidate: WayCandidate,
        transitionCandidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        fromEndpointProximityM: Double,
    ): Boolean {
        if (observedHeadingDeg == null || speedKmh == null || !observedHeadingDeg.isFinite() || !speedKmh.isFinite()) {
            return false
        }
        val preferredHeading = preferredCandidate.localHeadingDeg ?: preferredCandidate.startHeadingDeg ?: preferredCandidate.endHeadingDeg ?: return false
        val transitionHeading = transitionCandidate.localHeadingDeg ?: transitionCandidate.startHeadingDeg ?: transitionCandidate.endHeadingDeg ?: return false
        val currentMismatchDeg = directedHeadingMismatchDeg(observedHeadingDeg, preferredHeading)
        val candidateMismatchDeg = directedHeadingMismatchDeg(observedHeadingDeg, transitionHeading)
        val meaningfulTurn = candidateMismatchDeg >= TRANSITION_HEADING_MEANINGFUL_TURN_DEG
        if (!meaningfulTurn) {
            return false
        }
        if (candidateMismatchDeg + 12.0 >= currentMismatchDeg) {
            return false
        }
        val endpointThreshold = SEGMENT_TRANSITION_ENDPOINT_THRESHOLD_M
        if (fromEndpointProximityM > endpointThreshold) {
            return true
        }
        if (speedKmh >= TRANSITION_HIGH_SPEED_KMH) {
            return candidateMismatchDeg >= TRANSITION_HEADING_SHARP_TURN_DEG
        }
        if (speedKmh >= TRANSITION_MODERATE_SPEED_KMH) {
            return candidateMismatchDeg >= TRANSITION_HEADING_VERY_SHARP_TURN_DEG
        }
        return false
    }

    private fun shouldSuppressImmediateSameRefBounce(
        candidate: WayCandidate,
        preferredCandidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double,
    ): Boolean {
        if (!isImmediateSameRefBounceCandidate(candidate, preferredCandidate, matchContext, wayLinks)) {
            return false
        }
        val requiredScoreImprovement = max(SAME_REF_BOUNCE_MIN_SCORE_IMPROVEMENT_M, accuracyBufferM)
        if (preferredCandidate.score - candidate.score >= requiredScoreImprovement) {
            return false
        }
        val requiredDistanceImprovement = SAME_REF_BOUNCE_MIN_DISTANCE_IMPROVEMENT_M + min(accuracyBufferM * 0.25, 4.0)
        if (preferredCandidate.distanceM - candidate.distanceM >= requiredDistanceImprovement) {
            return false
        }
        return true
    }

    private fun isImmediateSameRefBounceCandidate(
        candidate: WayCandidate,
        preferredCandidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
    ): Boolean {
        val candidateWayId = normalizedWayId(candidate.wayId)
        val preferredWayId = normalizedWayId(preferredCandidate.wayId)
        val priorWayId = matchContext.recentWayHistory.drop(1).firstOrNull()
        if (candidateWayId == null || preferredWayId == null || candidateWayId == preferredWayId || candidateWayId != priorWayId) {
            return false
        }
        val candidateRefs = normalizedRefTokens(candidate.streetRef).toSet()
        val preferredRefs = normalizedRefTokens(preferredCandidate.streetRef).toSet()
        if (candidateRefs.isEmpty() || candidateRefs.intersect(preferredRefs).isEmpty() || !wayLinks.available) {
            return false
        }
        return areLinkedWays(candidateWayId, preferredWayId, wayLinks) || areSharedRefLinkedWays(candidateWayId, preferredWayId, wayLinks)
    }

    private fun shouldPromoteTunnelEntry(
        tunnelCandidate: WayCandidate,
        surfaceCandidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        corridorProgress: CorridorProgressContext,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
        accuracyBufferM: Double,
    ): Boolean {
        val portalEligible = isPortalEligibleTunnelCandidate(tunnelCandidate, matchContext, wayLinks, corridorProgress, accuracyBufferM)
        if (
            !isTruthyOsmTag(tunnelCandidate.tunnel) ||
            isTruthyOsmTag(surfaceCandidate.tunnel) ||
            (!portalEligible && !hasCommittedTunnelApproachEvidence(tunnelCandidate, matchContext, horizontalAccuracyM, gpsSignalBars))
        ) {
            return false
        }
        val motionScore = portalMotionProgressScore(tunnelCandidate, matchContext)
        val allowedSlack = max(TUNNEL_PORTAL_SCORE_SLACK_M, min(accuracyBufferM, 20.0)) + (motionScore * TUNNEL_PORTAL_COMMIT_SLACK_BONUS_M)
        return tunnelCandidate.score <= surfaceCandidate.score + allowedSlack
    }

    private fun shouldKeepTunnelContinuity(
        tunnelCandidate: WayCandidate,
        surfaceCandidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        corridorProgress: CorridorProgressContext,
        accuracyBufferM: Double,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
    ): Boolean {
        if (!isTruthyOsmTag(tunnelCandidate.tunnel) || isTruthyOsmTag(surfaceCandidate.tunnel) || !matchContext.isInTunnelMode) {
            return false
        }
        val surfaceCorridorState = candidateCorridorState(surfaceCandidate, matchContext, wayLinks, corridorProgress)
        if (surfaceCorridorState != null && surfaceCandidate.score <= tunnelCandidate.score + TUNNEL_PORTAL_SCORE_SLACK_M) {
            return false
        }
        if (hasCommittedTunnelApproachEvidence(tunnelCandidate, matchContext, horizontalAccuracyM, gpsSignalBars)) {
            return true
        }
        return tunnelCandidate.score <= surfaceCandidate.score + max(TUNNEL_PORTAL_SCORE_SLACK_M, accuracyBufferM)
    }

    private fun candidateCorridorState(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        corridorProgress: CorridorProgressContext,
    ): CandidateCorridorState? {
        val infos = corridorProgress.byWayId[normalizedWayId(candidate.wayId)].orEmpty()
        if (infos.isEmpty()) {
            return null
        }
        val anchorSideNodeKeys = if (matchContext.preferredWayId != null) {
            wayLinks.sharedNodeKeys(matchContext.preferredWayId, normalizedWayId(candidate.wayId))
        } else {
            emptySet()
        }
        return infos.asSequence()
            .filter { info ->
                anchorSideNodeKeys.isEmpty() || info.sideNodeKey in anchorSideNodeKeys ||
                    sameCorridorState(matchContext.activeCorridorState, corridorStateSnapshot(candidate, info)) ||
                    sameCorridorState(matchContext.approachCorridorState, corridorStateSnapshot(candidate, info))
            }
            .mapNotNull { info ->
                val snapshot = corridorStateSnapshot(candidate, info) ?: return@mapNotNull null
                CandidateCorridorState(
                    snapshot = snapshot,
                    entryZone = snapshot.depthM <= corridorEntryDepthThresholdM(snapshot.kind),
                    exitZone = isCorridorExitZone(snapshot),
                )
            }
            .sortedWith(compareBy<CandidateCorridorState> { it.snapshot.depthM }.thenBy { it.snapshot.corridorId })
            .firstOrNull()
    }

    private fun shouldTriggerActiveCorridorMode(
        candidateCorridorState: CandidateCorridorState,
        matchContext: WayMatchContext,
    ): Boolean {
        if (sameCorridorState(matchContext.activeCorridorState, candidateCorridorState.snapshot)) {
            return true
        }
        val approachState = matchContext.approachCorridorState ?: return false
        if (!sameCorridorState(approachState, candidateCorridorState.snapshot)) {
            return false
        }
        if (matchContext.approachCorridorFixCount < corridorEntryFixCount(candidateCorridorState.snapshot.kind)) {
            return false
        }
        if (candidateCorridorState.snapshot.depthM < corridorEntryMinDepthM(candidateCorridorState.snapshot.kind)) {
            return false
        }
        return candidateCorridorState.snapshot.depthM + CORRIDOR_PROGRESS_NOISE_TOLERANCE_M >= approachState.depthM
    }

    private fun corridorStateSnapshot(
        candidate: WayCandidate,
        info: CorridorProgressInfo,
    ): CorridorMatchState? {
        val distanceToStartM = candidate.distanceToStartM ?: return null
        val distanceToEndM = candidate.distanceToEndM ?: return null
        val useStart = distanceToStartM <= distanceToEndM
        val depthM = if (useStart) info.startDepthM else info.endDepthM
        val depthNodes = if (useStart) info.startDepthNodes else info.endDepthNodes
        return CorridorMatchState(
            kind = info.kind,
            corridorId = info.corridorId,
            sideNodeKey = info.sideNodeKey,
            depthM = depthM,
            spanM = info.spanM,
            depthNodes = depthNodes,
            spanNodes = info.spanNodes,
        )
    }

    private fun isCorridorExitZone(snapshot: CorridorMatchState): Boolean {
        val remainingM = max(0.0, snapshot.spanM - snapshot.depthM)
        if (remainingM > corridorExitRemainingThresholdM(snapshot.kind)) {
            return false
        }
        val thresholdNodes = corridorExitRemainingThresholdNodes(snapshot.kind)
        if (!corridorUsesNodeProgress(snapshot.spanNodes, thresholdNodes)) {
            return true
        }
        val remainingNodes = max(0, snapshot.spanNodes - snapshot.depthNodes)
        return remainingNodes <= thresholdNodes
    }

    private fun corridorEntryDepthThresholdM(kind: String): Double {
        return when (kind) {
            "motorway" -> MOTORWAY_CORRIDOR_ENTRY_DEPTH_M
            else -> TUNNEL_CORRIDOR_ENTRY_DEPTH_M
        }
    }

    private fun corridorEntryMinDepthM(kind: String): Double {
        return when (kind) {
            "motorway" -> MOTORWAY_CORRIDOR_ENTRY_MIN_DEPTH_M
            else -> TUNNEL_CORRIDOR_ENTRY_MIN_DEPTH_M
        }
    }

    private fun corridorEntryFixCount(kind: String): Int {
        return when (kind) {
            "motorway" -> MOTORWAY_CORRIDOR_ENTRY_FIX_COUNT
            else -> TUNNEL_CORRIDOR_ENTRY_FIX_COUNT
        }
    }

    private fun corridorExitRemainingThresholdM(kind: String): Double {
        return when (kind) {
            "motorway" -> MOTORWAY_CORRIDOR_EXIT_REMAINING_M
            else -> TUNNEL_CORRIDOR_EXIT_REMAINING_M
        }
    }

    private fun corridorExitRemainingThresholdNodes(kind: String): Int {
        return when (kind) {
            "motorway" -> MOTORWAY_CORRIDOR_EXIT_REMAINING_NODES
            else -> TUNNEL_CORRIDOR_EXIT_REMAINING_NODES
        }
    }

    private fun corridorUsesNodeProgress(spanNodes: Int, thresholdNodes: Int): Boolean {
        return spanNodes > 0 && thresholdNodes > 0
    }

    private fun sameCorridorState(
        lhs: CorridorMatchState?,
        rhs: CorridorMatchState?,
    ): Boolean {
        return lhs != null &&
            rhs != null &&
            lhs.kind == rhs.kind &&
            lhs.corridorId == rhs.corridorId &&
            lhs.sideNodeKey == rhs.sideNodeKey
    }

    private fun isPortalEligibleTunnelCandidate(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        corridorProgress: CorridorProgressContext,
        accuracyBufferM: Double,
    ): Boolean {
        if (!isTruthyOsmTag(candidate.tunnel) || !wayLinks.available || matchContext.isInTunnelMode) {
            return false
        }
        val anchorWayId = matchContext.preferredWayId ?: return false
        val anchor = CorridorAnchor(
            wayId = anchorWayId,
            highway = matchContext.preferredHighway,
            endpointProximityM = matchContext.preferredEndpointProximityM,
        )
        if (!isTunnelPortalTransition(anchor, candidate, matchContext, wayLinks, accuracyBufferM, entry = true)) {
            return false
        }
        val corridorState = candidateCorridorState(candidate, matchContext, wayLinks, corridorProgress)
        if (corridorState != null && (!corridorState.entryZone || corridorState.snapshot.kind != "tunnel")) {
            return false
        }
        val endpointDistance = corridorState?.snapshot?.depthM ?: candidate.endpointProximityM
        if (!endpointDistance.isFinite() || endpointDistance > TUNNEL_PORTAL_ENTRY_ENDPOINT_THRESHOLD_M + accuracyBufferM) {
            return false
        }
        if (matchContext.recentFixes.isEmpty()) {
            return true
        }
        return portalMotionProgressScore(candidate, matchContext) >= if (endpointDistance <= max(4.0, min(accuracyBufferM * 0.35, 10.0))) {
            TUNNEL_PORTAL_DIRECT_SNAP_MOTION_MIN_SCORE
        } else {
            0.25
        }
    }

    private fun hasCommittedTunnelApproachEvidence(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
    ): Boolean {
        if (
            !isTruthyOsmTag(candidate.tunnel) ||
            matchContext.tunnelApproachFixCount < TUNNEL_APPROACH_MIN_FIX_COUNT ||
            !matchesTunnelApproachCandidate(candidate, matchContext)
        ) {
            return false
        }
        if (matchContext.hadRecentGpsSignalLoss) {
            return true
        }
        if (
            matchContext.tunnelApproachBaselineAccuracyM != null &&
            horizontalAccuracyM != null &&
            horizontalAccuracyM.isFinite() &&
            horizontalAccuracyM >= matchContext.tunnelApproachBaselineAccuracyM + TUNNEL_APPROACH_ACCURACY_DELTA_M
        ) {
            return true
        }
        if (
            matchContext.tunnelApproachBaselineSignalBars != null &&
            gpsSignalBars != null &&
            gpsSignalBars <= matchContext.tunnelApproachBaselineSignalBars - TUNNEL_APPROACH_SIGNAL_DROP_BARS
        ) {
            return true
        }
        return portalMotionProgressScore(candidate, matchContext) >= CORRIDOR_STATE_TUNNEL_DIRECT_COMMIT_MIN_SCORE
    }

    private fun matchesTunnelApproachCandidate(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
    ): Boolean {
        val candidateWayId = normalizedWayId(candidate.wayId)
        if (candidateWayId != null && candidateWayId in matchContext.recentTunnelApproachWayIds) {
            return true
        }
        val candidateRefs = normalizedRefTokens(candidate.streetRef)
        return candidateRefs.any(matchContext.recentTunnelApproachRefs::contains)
    }

    private fun portalMotionProgressScore(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
    ): Double {
        val metrics = portalMotionMetrics(candidate, matchContext) ?: return 0.0
        val rawApproach = max(0.0, min(metrics.bestApproachDeltaM / 12.0, 1.0))
        val approachComponent = if (metrics.alignmentScore >= 0.35) rawApproach else 0.0
        return max(
            approachComponent,
            (approachComponent * 0.6) + (metrics.alignmentScore * 0.25) + (metrics.proximityScore * 0.15),
        )
    }

    private fun portalMotionMetrics(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
    ): PortalMotionMetrics? {
        val currentDistanceToStartM = candidate.distanceToStartM ?: return null
        val currentDistanceToEndM = candidate.distanceToEndM ?: return null
        if (matchContext.recentFixes.isEmpty() || candidate.points.isEmpty()) {
            return null
        }
        val enteringFromStart = currentDistanceToStartM <= currentDistanceToEndM
        val currentPortalDistance = if (enteringFromStart) currentDistanceToStartM else currentDistanceToEndM
        var bestApproachDeltaM = 0.0
        var bestInteriorProgressDeltaM = 0.0
        for (fix in matchContext.recentFixes.take(2)) {
            val priorDistanceToStart = candidate.points.firstOrNull()?.let { haversineM(fix.lat, fix.lon, it.lat, it.lon) } ?: continue
            val priorDistanceToEnd = candidate.points.lastOrNull()?.let { haversineM(fix.lat, fix.lon, it.lat, it.lon) } ?: continue
            val priorPortalDistance = if (enteringFromStart) priorDistanceToStart else priorDistanceToEnd
            bestApproachDeltaM = max(bestApproachDeltaM, priorPortalDistance - currentPortalDistance)
            bestInteriorProgressDeltaM = max(bestInteriorProgressDeltaM, currentPortalDistance - priorPortalDistance)
        }
        val proximityScore = max(0.0, min((18.0 - currentPortalDistance) / 18.0, 1.0))
        val alignmentScore = matchContext.recentFixes.firstOrNull()?.let { priorFix ->
            val motionHeading = axisHeadingDeg(priorFix.lat, priorFix.lon, candidate.queryPoint.lat, candidate.queryPoint.lon)
            val portalHeading = portalInteriorHeadingDeg(candidate, enteringFromStart)
            if (motionHeading != null && portalHeading != null) {
                max(0.0, 1.0 - (directedHeadingMismatchDeg(motionHeading, portalHeading) / 55.0))
            } else {
                0.0
            }
        } ?: 0.0
        return PortalMotionMetrics(
            currentPortalDistanceM = currentPortalDistance,
            bestApproachDeltaM = bestApproachDeltaM,
            bestInteriorProgressDeltaM = bestInteriorProgressDeltaM,
            alignmentScore = alignmentScore,
            proximityScore = proximityScore,
        )
    }

    private fun portalInteriorHeadingDeg(
        candidate: WayCandidate,
        enteringFromStart: Boolean,
    ): Double? {
        return if (enteringFromStart) {
            candidate.startHeadingDeg
        } else {
            candidate.endHeadingDeg?.let { normalizedHeadingDegrees(it + 180.0) }
        }
    }

    private fun isTunnelPortalTransition(
        anchor: CorridorAnchor,
        candidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double,
        entry: Boolean,
    ): Boolean {
        val endpointThresholdM = if (entry) TUNNEL_PORTAL_ENTRY_ENDPOINT_THRESHOLD_M else TUNNEL_PORTAL_EXIT_ENDPOINT_THRESHOLD_M
        if (!isEndpointLinkedTransition(anchor, candidate, wayLinks, endpointThresholdM, accuracyBufferM)) {
            return false
        }
        return if (entry) {
            areSharedRefLinkedWays(anchor.wayId, normalizedWayId(candidate.wayId), wayLinks) || hasSharedRefWithPreferred(candidate, matchContext)
        } else {
            true
        }
    }

    private fun isEndpointLinkedTransition(
        anchor: CorridorAnchor,
        candidate: WayCandidate,
        wayLinks: WayLinksContext,
        endpointThresholdM: Double,
        accuracyBufferM: Double,
    ): Boolean {
        val candidateWayId = normalizedWayId(candidate.wayId)
        if (!areLinkedWays(anchor.wayId, candidateWayId, wayLinks)) {
            return false
        }
        val threshold = endpointThresholdM + accuracyBufferM
        val sourceNearEndpoint = anchor.endpointProximityM?.let { it <= threshold } ?: true
        val candidateNearEndpoint = candidate.endpointProximityM <= (threshold * 2.0)
        return sourceNearEndpoint && candidateNearEndpoint
    }

    private fun hasSharedRefWithPreferred(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
    ): Boolean {
        val candidateRefs = normalizedRefTokens(candidate.streetRef)
        return candidateRefs.isNotEmpty() && candidateRefs.any(matchContext.recentStreetRefs::contains)
    }

    private fun areLinkedWays(
        sourceWayId: String?,
        targetWayId: String?,
        wayLinks: WayLinksContext,
    ): Boolean {
        return wayLinks.isLinked(sourceWayId, targetWayId) || wayLinks.isLinked(targetWayId, sourceWayId)
    }

    private fun areSharedRefLinkedWays(
        sourceWayId: String?,
        targetWayId: String?,
        wayLinks: WayLinksContext,
    ): Boolean {
        return wayLinks.isSharedRefLinked(sourceWayId, targetWayId) || wayLinks.isSharedRefLinked(targetWayId, sourceWayId)
    }

    private fun highwayFamily(raw: String?): String? {
        val normalized = raw?.trim()?.lowercase().orEmpty()
        return when {
            normalized.isEmpty() -> null
            normalized.endsWith("_link") -> normalized.dropLast(5)
            else -> normalized
        }
    }

    private fun normalizedWayId(raw: String?): String? = raw?.trim()?.ifBlank { null }

    private fun queryWayCandidates(
        lat: Double,
        lon: Double,
        radiusM: Double,
        maxCandidates: Int,
        headingDeg: Double?,
    ): List<WayCandidate> {
        if (!hasWaysTable || !hasWayBoundsColumns) {
            return emptyList()
        }
        val bounds = queryBounds(lat = lat, lon = lon, radiusM = radiusM)
        val streetNameSelect = if (hasStreetNameColumn) "w.street_name" else "NULL"
        val refSelect = if (hasRefColumn) "w.ref" else "NULL"
        val serviceSelect = if (hasServiceColumn) "w.service" else "NULL"
        val tunnelSelect = if (hasTunnelColumn) "w.tunnel" else "NULL"
        val wayGeomJoin = if (hasWayGeomTable) "LEFT JOIN way_geom g ON g.way_id = w.way_id" else ""
        val wayGeomSelect = if (hasWayGeomTable) "g.points_json" else "NULL"
        val useRtree = allowWaysRtreeQueries && hasWaysRtreeTable
        val fromClause = if (useRtree) {
            "FROM ways_rtree r JOIN ways w ON w.way_id = r.way_id"
        } else {
            "FROM ways w"
        }
        val boundsSource = if (useRtree) "r" else "w"
        val sql = """
            SELECT
              w.way_id,
              w.highway,
              $streetNameSelect AS street_name,
              $refSelect AS ref,
              w.maxspeed,
              w.maxspeed_type,
              w.source_maxspeed,
              w.approx_heading_deg,
              $serviceSelect AS service,
              $tunnelSelect AS tunnel,
              w.min_lon,
              w.min_lat,
              w.max_lon,
              w.max_lat,
              $wayGeomSelect AS points_json
            $fromClause
            $wayGeomJoin
            WHERE $boundsSource.min_lon <= ? AND $boundsSource.max_lon >= ?
              AND $boundsSource.min_lat <= ? AND $boundsSource.max_lat >= ?
            ORDER BY
              (
                CASE
                  WHEN ? < w.min_lon THEN (w.min_lon - ?)
                  WHEN ? > w.max_lon THEN (? - w.max_lon)
                  ELSE 0
                END
              ) * (
                CASE
                  WHEN ? < w.min_lon THEN (w.min_lon - ?)
                  WHEN ? > w.max_lon THEN (? - w.max_lon)
                  ELSE 0
                END
              ) +
              (
                CASE
                  WHEN ? < w.min_lat THEN (w.min_lat - ?)
                  WHEN ? > w.max_lat THEN (? - w.max_lat)
                  ELSE 0
                END
              ) * (
                CASE
                  WHEN ? < w.min_lat THEN (w.min_lat - ?)
                  WHEN ? > w.max_lat THEN (? - w.max_lat)
                  ELSE 0
                END
              )
            LIMIT ?
        """.trimIndent()
        val params = arrayOf(
            bounds.maxLon.toString(),
            bounds.minLon.toString(),
            bounds.maxLat.toString(),
            bounds.minLat.toString(),
            lon.toString(),
            lon.toString(),
            lon.toString(),
            lon.toString(),
            lon.toString(),
            lon.toString(),
            lon.toString(),
            lon.toString(),
            lat.toString(),
            lat.toString(),
            lat.toString(),
            lat.toString(),
            lat.toString(),
            lat.toString(),
            lat.toString(),
            lat.toString(),
            maxCandidates.toString(),
        )

        val out = ArrayList<WayCandidate>()
        try {
            db.rawQuery(sql, params).use { cursor ->
                while (cursor.moveToNext()) {
                    val wayId = cursor.stringOrNull(0)
                    val highway = cursor.stringOrNull(1)
                    val streetBaseName = cursor.stringOrNull(2)
                    val streetRef = cursor.stringOrNull(3)
                    val derived = deriveSpeedLimitWithSource(
                        maxspeed = cursor.stringOrNull(4),
                        maxspeedType = cursor.stringOrNull(5),
                        sourceMaxspeed = cursor.stringOrNull(6),
                        highway = highway,
                    )
                    val approxHeading = cursor.doubleOrNull(7)
                    val service = cursor.stringOrNull(8)
                    val tunnel = cursor.stringOrNull(9)
                    val minLon = cursor.getDouble(10)
                    val minLat = cursor.getDouble(11)
                    val maxLon = cursor.getDouble(12)
                    val maxLat = cursor.getDouble(13)
                    val points = parseWayPoints(cursor.stringOrNull(14))
                    val bboxDistance = distanceToBBoxM(
                        lat = lat,
                        lon = lon,
                        minLon = minLon,
                        minLat = minLat,
                        maxLon = maxLon,
                        maxLat = maxLat,
                    )
                    val polylineDistance = polylineDistanceM(lat = lat, lon = lon, points = points)
                    val distanceToStartM = points.firstOrNull()?.let { haversineM(lat1 = lat, lon1 = lon, lat2 = it.lat, lon2 = it.lon) }
                    val distanceToEndM = points.lastOrNull()?.let { haversineM(lat1 = lat, lon1 = lon, lat2 = it.lat, lon2 = it.lon) }
                    val endpointProximityM = min(distanceToStartM ?: Double.POSITIVE_INFINITY, distanceToEndM ?: Double.POSITIVE_INFINITY)
                    val distance = min(bboxDistance, polylineDistance ?: Double.POSITIVE_INFINITY)
                    val localHeading = polylineHeadingDeg(lat = lat, lon = lon, points = points)
                    val headingPenalty = if (headingDeg != null) {
                        val candidateHeading = localHeading ?: approxHeading
                        if (candidateHeading != null) {
                            headingMismatchDeg(headingDeg, candidateHeading) * HEADING_WEIGHT_M_PER_DEG
                        } else {
                            0.0
                        }
                    } else {
                        0.0
                    }
                    val unknownHighwayPenalty = if (highway == null) UNKNOWN_HIGHWAY_PENALTY_M else 0.0
                    out += WayCandidate(
                        wayId = wayId,
                        highway = highway,
                        service = service,
                        tunnel = tunnel,
                        streetName = formattedStreetDisplay(streetName = streetBaseName, ref = streetRef),
                        streetBaseName = streetBaseName,
                        streetRef = streetRef,
                        speedLimitKmh = derived.speed,
                        speedSource = derived.source,
                        isUnlimitedSpeedLimit = derived.isUnlimited,
                        distanceM = distance,
                        endpointProximityM = endpointProximityM,
                        distanceToStartM = distanceToStartM,
                        distanceToEndM = distanceToEndM,
                        score = distance + headingPenalty + unknownHighwayPenalty,
                        queryPoint = LatLonPoint(lat = lat, lon = lon),
                        points = points,
                        localHeadingDeg = localHeading,
                        startHeadingDeg = endpointHeadingDeg(points, fromStart = true),
                        endHeadingDeg = endpointHeadingDeg(points, fromStart = false),
                    )
                }
            }
        } catch (error: SQLiteException) {
            if (useRtree && isRtreeModuleUnavailable(error)) {
                allowWaysRtreeQueries = false
                return queryWayCandidates(lat = lat, lon = lon, radiusM = radiusM, maxCandidates = maxCandidates, headingDeg = headingDeg)
            }
            throw error
        }
        return out
    }

    private fun queryAreaCandidates(
        lat: Double,
        lon: Double,
    ): List<AreaCandidate> {
        if (!hasAreasTable || !hasAreaBoundsColumns) {
            return emptyList()
        }
        val residentialSelect = if (hasAreaResidentialColumn) "a.residential" else "NULL"
        val pointsSelect = if (hasAreaPointsColumn) "a.points_json" else "NULL"
        val useRtree = allowAreasRtreeQueries && hasAreasRtreeTable
        val fromClause = if (useRtree) {
            "FROM areas_rtree r JOIN areas a ON a.row_id = r.row_id"
        } else {
            "FROM areas a"
        }
        val boundsSource = if (useRtree) "r" else "a"
        val sql = """
            SELECT
              a.area_id, a.geometry_type, a.name, a.place, a.boundary, a.admin_level,
              a.min_lon, a.min_lat, a.max_lon, a.max_lat,
              $residentialSelect AS residential,
              $pointsSelect AS points_json
            $fromClause
            WHERE
              (
                $boundsSource.min_lon <= ? AND $boundsSource.max_lon >= ?
                AND $boundsSource.min_lat <= ? AND $boundsSource.max_lat >= ?
              )
              OR
              (
                a.place IN ('city','town','village','hamlet')
                AND $boundsSource.min_lon <= ? AND $boundsSource.max_lon >= ?
                AND $boundsSource.min_lat <= ? AND $boundsSource.max_lat >= ?
              )
            LIMIT ?
        """.trimIndent()
        val placeWindowDeg = 0.3
        val params = arrayOf(
            lon.toString(),
            lon.toString(),
            lat.toString(),
            lat.toString(),
            (lon + placeWindowDeg).toString(),
            (lon - placeWindowDeg).toString(),
            (lat + placeWindowDeg).toString(),
            (lat - placeWindowDeg).toString(),
            "512",
        )
        val out = ArrayList<AreaCandidate>()
        try {
            db.rawQuery(sql, params).use { cursor ->
                while (cursor.moveToNext()) {
                    out += AreaCandidate(
                        areaId = cursor.stringOrNull(0).orEmpty(),
                        geometryType = cursor.stringOrNull(1),
                        name = cursor.stringOrNull(2),
                        place = cursor.stringOrNull(3),
                        boundary = cursor.stringOrNull(4),
                        adminLevel = cursor.stringOrNull(5),
                        minLon = cursor.getDouble(6),
                        minLat = cursor.getDouble(7),
                        maxLon = cursor.getDouble(8),
                        maxLat = cursor.getDouble(9),
                        residential = cursor.stringOrNull(10),
                        points = parseRingPoints(cursor.stringOrNull(11)),
                    )
                }
            }
        } catch (error: SQLiteException) {
            if (useRtree && isRtreeModuleUnavailable(error)) {
                allowAreasRtreeQueries = false
                return queryAreaCandidates(lat = lat, lon = lon)
            }
            throw error
        }
        return out
    }

    private fun hasBoundsColumns(table: String): Boolean {
        return columnExists(table, "min_lon") &&
            columnExists(table, "min_lat") &&
            columnExists(table, "max_lon") &&
            columnExists(table, "max_lat")
    }

    private fun isRtreeModuleUnavailable(error: SQLiteException): Boolean {
        return generateSequence(error as Throwable?) { it.cause }
            .mapNotNull { it.message }
            .any { message -> message.contains("no such module: rtree", ignoreCase = true) }
    }

    private fun resolveResidentialContext(
        lat: Double,
        lon: Double,
        areas: List<AreaCandidate>,
    ): ResidentialContext {
        if (!hasAreaResidentialColumn || !hasAreaPointsColumn) {
            return ResidentialContext(insideCity = null, candidatePolygons = 0, containingPolygons = 0)
        }
        var candidatePolygons = 0
        var containingPolygons = 0
        for (area in areas) {
            if (area.residential.isNullOrBlank() || area.points.size < 4) {
                continue
            }
            candidatePolygons += 1
            if (pointInRing(lon = lon, lat = lat, ring = area.points)) {
                containingPolygons += 1
            }
        }
        val insideCity = if (candidatePolygons > 0) containingPolygons > 0 else null
        return ResidentialContext(
            insideCity = insideCity,
            candidatePolygons = candidatePolygons,
            containingPolygons = containingPolygons,
        )
    }

    private fun resolveCityContextFromAreas(
        lat: Double,
        lon: Double,
        areas: List<AreaCandidate>,
    ): CityContext {
        val containingAdmin = mutableListOf<Triple<Int, Double, String>>()
        val containingPlaces = mutableListOf<Triple<Int, Double, String>>()
        val nearbyPlaces = mutableListOf<Triple<Int, Double, String>>()

        areas.forEach { area ->
            val name = area.name?.trim().orEmpty()
            if (name.isEmpty()) {
                return@forEach
            }
            val insideBbox = pointInBBox(
                lat = lat,
                lon = lon,
                minLon = area.minLon,
                minLat = area.minLat,
                maxLon = area.maxLon,
                maxLat = area.maxLat,
            )
            val areaSize = bboxArea(area)
            val adminLevel = area.adminLevel?.toIntOrNull()
            if (area.boundary == "administrative" && (adminLevel == 8 || adminLevel == 9) && insideBbox) {
                containingAdmin += Triple(adminLevel, areaSize, name)
            }

            val placeRank = placeRank(area.place) ?: return@forEach
            val centerLat = (area.minLat + area.maxLat) / 2.0
            val centerLon = (area.minLon + area.maxLon) / 2.0
            val distanceM = haversineM(lat1 = lat, lon1 = lon, lat2 = centerLat, lon2 = centerLon)
            nearbyPlaces += Triple(placeRank, distanceM, name)
            if (insideBbox) {
                containingPlaces += Triple(placeRank, distanceM, name)
            }
        }

        if (containingAdmin.isNotEmpty()) {
            val best = containingAdmin.sortedWith(compareBy<Triple<Int, Double, String>> { it.first }.thenBy { it.second }.thenBy { it.third }).first()
            return CityContext(
                insideCity = true,
                cityName = best.third,
                citySource = "admin_bbox",
                candidateBoundaries = containingAdmin.size,
                placeCandidates = nearbyPlaces.size,
            )
        }
        if (containingPlaces.isNotEmpty()) {
            val best = containingPlaces.sortedWith(compareBy<Triple<Int, Double, String>> { it.first }.thenBy { it.second }.thenBy { it.third }).first()
            return CityContext(
                insideCity = true,
                cityName = best.third,
                citySource = "place_bbox",
                candidateBoundaries = 0,
                placeCandidates = nearbyPlaces.size,
            )
        }
        if (nearbyPlaces.isNotEmpty()) {
            val best = nearbyPlaces.sortedWith(compareBy<Triple<Int, Double, String>> { it.second }.thenBy { it.first }.thenBy { it.third }).first()
            if (best.second <= NEAREST_PLACE_FALLBACK_MAX_DISTANCE_M) {
                return CityContext(
                    insideCity = false,
                    cityName = best.third,
                    citySource = "place_nearest",
                    candidateBoundaries = 0,
                    placeCandidates = nearbyPlaces.size,
                )
            }
        }
        return CityContext(
            insideCity = false,
            cityName = null,
            citySource = "bbox_no_match",
            candidateBoundaries = 0,
            placeCandidates = 0,
        )
    }

    private fun tableExists(name: String): Boolean {
        db.rawQuery(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
            arrayOf(name),
        ).use { cursor ->
            return cursor.moveToFirst()
        }
    }

    private fun columnExists(table: String, column: String): Boolean {
        if (!tableExists(table)) {
            return false
        }
        db.rawQuery("PRAGMA table_info($table)", null).use { cursor ->
            while (cursor.moveToNext()) {
                if (cursor.stringOrNull(1) == column) {
                    return true
                }
            }
        }
        return false
    }

    companion object {
        private const val HEADING_WEIGHT_M_PER_DEG = 1.8
        private const val MAX_TRACE_CANDIDATE_COUNT = 16
        private const val UNKNOWN_HIGHWAY_PENALTY_M = 30.0
        private const val NEAREST_PLACE_FALLBACK_MAX_DISTANCE_M = 5_000.0
        private const val WALKING_TURN_SWITCH_MAX_SPEED_KMH = 7.0
        private const val WALKING_TURN_SWITCH_PREFERRED_DISTANCE_M = 10.0
        private const val WALKING_TURN_SWITCH_BEST_DISTANCE_M = 5.0
        private const val WALKING_TURN_SWITCH_MIN_GAP_M = 8.0
        private const val WALKING_TURN_SWITCH_ENDPOINT_M = 4.0
        private const val PREFERRED_WAY_SCORE_SLACK_M = 18.0
        private const val PREFERRED_WAY_DISTANCE_MULTIPLIER = 1.9
        private const val PREFERRED_WAY_DISTANCE_FLOOR_M = 85.0
        private const val SAME_REF_SCORE_SLACK_M = 11.0
        private const val SAME_REF_DISTANCE_MULTIPLIER = 1.55
        private const val SAME_REF_DISTANCE_FLOOR_M = 72.0
        private const val SAME_REF_BOUNCE_MIN_SCORE_IMPROVEMENT_M = 14.0
        private const val SAME_REF_BOUNCE_MIN_DISTANCE_IMPROVEMENT_M = 8.0
        private const val RECENT_WAY_SCORE_SLACK_M = 6.0
        private const val RECENT_WAY_DISTANCE_MULTIPLIER = 1.35
        private const val RECENT_WAY_DISTANCE_FLOOR_M = 55.0
        private const val LINKED_WAY_SCORE_SLACK_M = 8.0
        private const val LINKED_WAY_DISTANCE_MULTIPLIER = 1.45
        private const val LINKED_WAY_DISTANCE_FLOOR_M = 64.0
        private const val SEGMENT_TRANSITION_ENDPOINT_THRESHOLD_M = 12.0
        private const val SEGMENT_TRANSITION_DISTANCE_SLACK_M = 12.0
        private const val TRANSITION_HEADING_MEANINGFUL_TURN_DEG = 18.0
        private const val TRANSITION_HEADING_SHARP_TURN_DEG = 35.0
        private const val TRANSITION_HEADING_VERY_SHARP_TURN_DEG = 55.0
        private const val TRANSITION_MODERATE_SPEED_KMH = 32.0
        private const val TRANSITION_HIGH_SPEED_KMH = 48.0
        private const val TUNNEL_PORTAL_ENTRY_ENDPOINT_THRESHOLD_M = 24.0
        private const val TUNNEL_PORTAL_EXIT_ENDPOINT_THRESHOLD_M = 28.0
        private const val TUNNEL_PORTAL_SCORE_SLACK_M = 12.0
        private const val TUNNEL_PORTAL_DIRECT_SNAP_MOTION_MIN_SCORE = 0.2
        private const val TUNNEL_PORTAL_COMMIT_SLACK_BONUS_M = 18.0
        private const val TUNNEL_APPROACH_MIN_FIX_COUNT = 2
        private const val TUNNEL_APPROACH_ACCURACY_DELTA_M = 8.0
        private const val TUNNEL_APPROACH_SIGNAL_DROP_BARS = 1
        private const val TUNNEL_CORRIDOR_ENTRY_DEPTH_M = 42.0
        private const val TUNNEL_CORRIDOR_EXIT_REMAINING_M = 42.0
        private const val TUNNEL_CORRIDOR_ENTRY_MIN_DEPTH_M = 12.0
        private const val TUNNEL_CORRIDOR_ENTRY_FIX_COUNT = 2
        private const val TUNNEL_CORRIDOR_EXIT_REMAINING_NODES = 1
        private const val MOTORWAY_CORRIDOR_ENTRY_DEPTH_M = 150.0
        private const val MOTORWAY_CORRIDOR_EXIT_REMAINING_M = 160.0
        private const val MOTORWAY_CORRIDOR_ENTRY_MIN_DEPTH_M = 30.0
        private const val MOTORWAY_CORRIDOR_ENTRY_FIX_COUNT = 2
        private const val MOTORWAY_CORRIDOR_EXIT_REMAINING_NODES = 1
        private const val CORRIDOR_PROGRESS_NOISE_TOLERANCE_M = 12.0
        private const val CORRIDOR_STATE_TUNNEL_DIRECT_COMMIT_MIN_SCORE = 0.75
        private val inCityHighwayClasses = setOf("residential", "service", "crossing", "living_street")

        fun deriveSpeedLimitKmh(
            maxspeed: String?,
            maxspeedType: String?,
            sourceMaxspeed: String?,
            highway: String?,
        ): Int? {
            return deriveSpeedLimitWithSource(maxspeed, maxspeedType, sourceMaxspeed, highway).speed
        }

        internal fun deriveSpeedLimitWithSource(
            maxspeed: String?,
            maxspeedType: String?,
            sourceMaxspeed: String?,
            highway: String?,
        ): DerivedSpeedResult {
            if (isUnlimitedSpeedTag(maxspeed)) {
                return DerivedSpeedResult(speed = null, source = DerivedSpeedSource.EXPLICIT_UNLIMITED_TAG, isUnlimited = true)
            }
            parseExplicitSpeed(maxspeed)?.let { explicit ->
                return DerivedSpeedResult(speed = explicit, source = DerivedSpeedSource.EXPLICIT_TAG, isUnlimited = false)
            }

            val inherited = listOfNotNull(maxspeedType, sourceMaxspeed).joinToString(" ").lowercase()
            if ("urban" in inherited) {
                return DerivedSpeedResult(speed = 50, source = DerivedSpeedSource.INHERITED_TAG, isUnlimited = false)
            }
            if ("rural" in inherited) {
                return DerivedSpeedResult(speed = 100, source = DerivedSpeedSource.INHERITED_TAG, isUnlimited = false)
            }
            if ("motorway" in inherited) {
                return DerivedSpeedResult(speed = null, source = DerivedSpeedSource.INHERITED_TAG, isUnlimited = false)
            }

            return when (highway?.trim()?.lowercase()) {
                "motorway", "motorway_link" -> DerivedSpeedResult(speed = null, source = DerivedSpeedSource.HIGHWAY_CLASS, isUnlimited = false)
                "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link", "tertiary", "tertiary_link" -> {
                    DerivedSpeedResult(speed = 100, source = DerivedSpeedSource.HIGHWAY_CLASS, isUnlimited = false)
                }
                "living_street" -> DerivedSpeedResult(speed = 10, source = DerivedSpeedSource.HIGHWAY_CLASS, isUnlimited = false)
                "residential", "service", "unclassified", "road" -> {
                    DerivedSpeedResult(speed = 50, source = DerivedSpeedSource.HIGHWAY_CLASS, isUnlimited = false)
                }
                else -> DerivedSpeedResult(speed = null, source = DerivedSpeedSource.NONE, isUnlimited = false)
            }
        }

        internal fun parseExplicitSpeed(raw: String?): Int? {
            val digits = raw?.filter(Char::isDigit).orEmpty()
            val value = digits.toIntOrNull() ?: return null
            return value.takeIf { it > 0 }
        }

        internal fun isUnlimitedSpeedTag(raw: String?): Boolean {
            return raw?.trim()?.lowercase() == "none"
        }

        private fun allowsResidentialAreaFallback(highway: String?): Boolean {
            return when (highway?.trim()?.lowercase()) {
                "motorway", "motorway_link" -> false
                else -> true
            }
        }

        private fun highwayImpliesInsideCity(highway: String?): Boolean {
            return highway?.trim()?.lowercase() in inCityHighwayClasses
        }

        private fun formattedStreetDisplay(streetName: String?, ref: String?): String? {
            val normalizedStreet = streetName?.trim().orEmpty()
            val normalizedRef = ref?.trim().orEmpty()
            return when {
                normalizedStreet.isNotEmpty() && normalizedRef.isNotEmpty() -> "$normalizedStreet ($normalizedRef)"
                normalizedStreet.isNotEmpty() -> normalizedStreet
                normalizedRef.isNotEmpty() -> normalizedRef
                else -> null
            }
        }

        private fun queryBounds(lat: Double, lon: Double, radiusM: Double): QueryBounds {
            val degLat = radiusM / 111_132.0
            val cosLat = max(0.173648, abs(cos(Math.toRadians(lat))))
            val degLon = radiusM / (111_320.0 * cosLat)
            return QueryBounds(
                minLon = lon - degLon,
                minLat = lat - degLat,
                maxLon = lon + degLon,
                maxLat = lat + degLat,
            )
        }

        private fun bboxArea(area: AreaCandidate): Double {
            return max(area.maxLon - area.minLon, 0.0) * max(area.maxLat - area.minLat, 0.0)
        }

        private fun placeRank(place: String?): Int? {
            return when (place?.trim()?.lowercase()) {
                "city" -> 0
                "town" -> 1
                "village" -> 2
                "hamlet" -> 3
                else -> null
            }
        }

        private fun distanceToBBoxM(
            lat: Double,
            lon: Double,
            minLon: Double,
            minLat: Double,
            maxLon: Double,
            maxLat: Double,
        ): Double {
            val clampedLon = min(max(lon, minLon), maxLon)
            val clampedLat = min(max(lat, minLat), maxLat)
            return haversineM(lat1 = lat, lon1 = lon, lat2 = clampedLat, lon2 = clampedLon)
        }

        private fun polylineDistanceM(
            lat: Double,
            lon: Double,
            points: List<LatLonPoint>,
        ): Double? {
            if (points.isEmpty()) {
                return null
            }
            if (points.size == 1) {
                return haversineM(lat1 = lat, lon1 = lon, lat2 = points.first().lat, lon2 = points.first().lon)
            }
            var best = Double.POSITIVE_INFINITY
            for (index in 0 until points.lastIndex) {
                val start = points[index]
                val end = points[index + 1]
                val projection = pointToSegmentProjection(
                    lat = lat,
                    lon = lon,
                    lat1 = start.lat,
                    lon1 = start.lon,
                    lat2 = end.lat,
                    lon2 = end.lon,
                )
                if (projection.distanceM < best) {
                    best = projection.distanceM
                }
            }
            return best.takeIf { it.isFinite() }
        }

        private fun polylineHeadingDeg(
            lat: Double,
            lon: Double,
            points: List<LatLonPoint>,
        ): Double? {
            if (points.size < 2) {
                return null
            }
            var bestDistance = Double.POSITIVE_INFINITY
            var bestHeading: Double? = null
            for (index in 0 until points.lastIndex) {
                val start = points[index]
                val end = points[index + 1]
                val projection = pointToSegmentProjection(
                    lat = lat,
                    lon = lon,
                    lat1 = start.lat,
                    lon1 = start.lon,
                    lat2 = end.lat,
                    lon2 = end.lon,
                )
                if (projection.distanceM < bestDistance) {
                    bestDistance = projection.distanceM
                    bestHeading = axisHeadingDeg(start.lat, start.lon, end.lat, end.lon)
                }
            }
            return bestHeading
        }

        private fun pointToSegmentProjection(
            lat: Double,
            lon: Double,
            lat1: Double,
            lon1: Double,
            lat2: Double,
            lon2: Double,
        ): ProjectionResult {
            val start = toXYMeters(lat = lat1, lon = lon1, originLat = lat, originLon = lon)
            val end = toXYMeters(lat = lat2, lon = lon2, originLat = lat, originLon = lon)
            val dx = end.x - start.x
            val dy = end.y - start.y
            if (dx == 0.0 && dy == 0.0) {
                return ProjectionResult(distanceM = hypot(start.x, start.y))
            }
            val tNumerator = ((0.0 - start.x) * dx) + ((0.0 - start.y) * dy)
            val tDenominator = (dx * dx) + (dy * dy)
            val t = (tNumerator / tDenominator).coerceIn(0.0, 1.0)
            val projectionX = start.x + (t * dx)
            val projectionY = start.y + (t * dy)
            return ProjectionResult(distanceM = hypot(projectionX, projectionY))
        }

        private fun toXYMeters(
            lat: Double,
            lon: Double,
            originLat: Double,
            originLon: Double,
        ): XYPoint {
            val metersPerDegLat = 111_132.0
            val metersPerDegLon = 111_320.0 * cos(Math.toRadians(originLat))
            return XYPoint(
                x = (lon - originLon) * metersPerDegLon,
                y = (lat - originLat) * metersPerDegLat,
            )
        }

        private fun axisHeadingDeg(
            lat1: Double,
            lon1: Double,
            lat2: Double,
            lon2: Double,
        ): Double? {
            val dLon = Math.toRadians(lon2 - lon1)
            val startLat = Math.toRadians(lat1)
            val endLat = Math.toRadians(lat2)
            val y = kotlin.math.sin(dLon) * kotlin.math.cos(endLat)
            val x = (kotlin.math.cos(startLat) * kotlin.math.sin(endLat)) - (kotlin.math.sin(startLat) * kotlin.math.cos(endLat) * kotlin.math.cos(dLon))
            if (x == 0.0 && y == 0.0) {
                return null
            }
            return (Math.toDegrees(kotlin.math.atan2(y, x)) + 360.0) % 360.0
        }

        private fun endpointHeadingDeg(
            points: List<LatLonPoint>,
            fromStart: Boolean,
        ): Double? {
            if (points.size < 2) {
                return null
            }
            val (start, end) = if (fromStart) {
                points[0] to points[1]
            } else {
                points[points.lastIndex - 1] to points[points.lastIndex]
            }
            return axisHeadingDeg(start.lat, start.lon, end.lat, end.lon)
        }

        private fun headingMismatchDeg(headingDeg: Double, approxHeadingDeg: Double): Double {
            val raw = abs((headingDeg - approxHeadingDeg) % 360.0)
            val wrapped = min(raw, 360.0 - raw)
            return min(wrapped, abs(180.0 - wrapped))
        }

        private fun directedHeadingMismatchDeg(headingDeg: Double, approxHeadingDeg: Double): Double {
            val normalized = normalizedHeadingDegrees(headingDeg - approxHeadingDeg)
            return min(normalized, 360.0 - normalized)
        }

        private fun normalizedHeadingDegrees(value: Double): Double {
            val normalized = value % 360.0
            return if (normalized < 0.0) normalized + 360.0 else normalized
        }

        private fun haversineM(
            lat1: Double,
            lon1: Double,
            lat2: Double,
            lon2: Double,
        ): Double {
            val earthRadiusM = 6_371_008.8
            val phi1 = Math.toRadians(lat1)
            val phi2 = Math.toRadians(lat2)
            val deltaLat = Math.toRadians(lat2 - lat1)
            val deltaLon = Math.toRadians(lon2 - lon1)
            val a = kotlin.math.sin(deltaLat / 2.0) * kotlin.math.sin(deltaLat / 2.0) +
                kotlin.math.cos(phi1) * kotlin.math.cos(phi2) *
                kotlin.math.sin(deltaLon / 2.0) * kotlin.math.sin(deltaLon / 2.0)
            return 2.0 * earthRadiusM * asin(kotlin.math.sqrt(a))
        }

        private fun pointInRing(
            lon: Double,
            lat: Double,
            ring: List<LonLatPoint>,
        ): Boolean {
            if (ring.size < 4) {
                return false
            }
            var inside = false
            for (index in 0 until ring.lastIndex) {
                val current = ring[index]
                val next = ring[index + 1]
                if (pointOnSegment(px = lon, py = lat, x1 = current.lon, y1 = current.lat, x2 = next.lon, y2 = next.lat)) {
                    return true
                }
                val crossesLatitude = (current.lat > lat) != (next.lat > lat)
                val denominator = if ((next.lat - current.lat) == 0.0) 1e-30 else (next.lat - current.lat)
                val xAtLat = ((next.lon - current.lon) * (lat - current.lat) / denominator) + current.lon
                if (crossesLatitude && lon < xAtLat) {
                    inside = !inside
                }
            }
            return inside
        }

        private fun pointOnSegment(
            px: Double,
            py: Double,
            x1: Double,
            y1: Double,
            x2: Double,
            y2: Double,
        ): Boolean {
            val epsilon = 1e-12
            val cross = ((px - x1) * (y2 - y1)) - ((py - y1) * (x2 - x1))
            if (abs(cross) > epsilon) {
                return false
            }
            val dot = ((px - x1) * (x2 - x1)) + ((py - y1) * (y2 - y1))
            if (dot < -epsilon) {
                return false
            }
            val squaredLength = ((x2 - x1) * (x2 - x1)) + ((y2 - y1) * (y2 - y1))
            return dot - squaredLength <= epsilon
        }

        private fun pointInBBox(
            lat: Double,
            lon: Double,
            minLon: Double,
            minLat: Double,
            maxLon: Double,
            maxLat: Double,
        ): Boolean {
            return minLat <= lat && lat <= maxLat && minLon <= lon && lon <= maxLon
        }

        private fun parseWayPoints(raw: String?): List<LatLonPoint> {
            if (raw.isNullOrBlank()) {
                return emptyList()
            }
            return try {
                val arr = JSONArray(raw)
                buildList(arr.length()) {
                    for (index in 0 until arr.length()) {
                        val pair = arr.optJSONArray(index) ?: continue
                        if (pair.length() < 2) {
                            continue
                        }
                        add(LatLonPoint(lat = pair.optDouble(0), lon = pair.optDouble(1)))
                    }
                }
            } catch (_: JSONException) {
                emptyList()
            }
        }

        private fun parseRingPoints(raw: String?): List<LonLatPoint> {
            if (raw.isNullOrBlank()) {
                return emptyList()
            }
            return try {
                val arr = JSONArray(raw)
                buildList(arr.length()) {
                    for (index in 0 until arr.length()) {
                        val pair = arr.optJSONArray(index) ?: continue
                        if (pair.length() < 2) {
                            continue
                        }
                        add(LonLatPoint(lon = pair.optDouble(0), lat = pair.optDouble(1)))
                    }
                }.takeIf { it.size >= 4 }.orEmpty()
            } catch (_: JSONException) {
                emptyList()
            }
        }

        private fun isTruthyOsmTag(raw: String?): Boolean {
            return when (raw?.trim()?.lowercase()) {
                "1", "true", "yes" -> true
                else -> false
            }
        }

        private fun normalizedRefTokens(raw: String?): List<String> {
            return raw
                ?.trim()
                ?.uppercase()
                ?.split(Regex("[^A-Z0-9]+"))
                ?.map(String::trim)
                ?.filter(String::isNotEmpty)
                .orEmpty()
        }

        private fun scaledAccuracyBufferM(horizontalAccuracyM: Double?): Double {
            if (horizontalAccuracyM == null || !horizontalAccuracyM.isFinite() || horizontalAccuracyM < 0.0) {
                return 0.0
            }
            return min(max(horizontalAccuracyM * 1.35, 0.0), 60.0)
        }

        private fun elapsedMs(startedAtNs: Long): Double {
            return (System.nanoTime() - startedAtNs) / 1_000_000.0
        }

        private val candidateComparator = compareBy<WayCandidate> { it.score }
            .thenBy { it.distanceM }
            .thenBy { it.wayId ?: "~" }
    }
}

internal enum class DerivedSpeedSource {
    NONE,
    EXPLICIT_TAG,
    INHERITED_TAG,
    HIGHWAY_CLASS,
    EXPLICIT_UNLIMITED_TAG,
}

internal data class DerivedSpeedResult(
    val speed: Int?,
    val source: DerivedSpeedSource,
    val isUnlimited: Boolean,
)

private data class WayCandidate(
    val wayId: String?,
    val highway: String?,
    val service: String?,
    val tunnel: String?,
    val streetName: String?,
    val streetBaseName: String?,
    val streetRef: String?,
    val speedLimitKmh: Int?,
    val speedSource: DerivedSpeedSource,
    val isUnlimitedSpeedLimit: Boolean,
    val distanceM: Double,
    val endpointProximityM: Double,
    val distanceToStartM: Double?,
    val distanceToEndM: Double?,
    val score: Double,
    val queryPoint: LatLonPoint,
    val points: List<LatLonPoint>,
    val localHeadingDeg: Double?,
    val startHeadingDeg: Double?,
    val endHeadingDeg: Double?,
)

private data class AreaCandidate(
    val areaId: String,
    val geometryType: String?,
    val name: String?,
    val place: String?,
    val boundary: String?,
    val adminLevel: String?,
    val minLon: Double,
    val minLat: Double,
    val maxLon: Double,
    val maxLat: Double,
    val residential: String?,
    val points: List<LonLatPoint>,
)

private data class ResidentialContext(
    val insideCity: Boolean?,
    val candidatePolygons: Int,
    val containingPolygons: Int,
)

private data class CityContext(
    val insideCity: Boolean,
    val cityName: String?,
    val citySource: String?,
    val candidateBoundaries: Int,
    val placeCandidates: Int,
)

private data class QueryBounds(
    val minLon: Double,
    val minLat: Double,
    val maxLon: Double,
    val maxLat: Double,
)

private data class XYPoint(
    val x: Double,
    val y: Double,
)

private data class ProjectionResult(
    val distanceM: Double,
)

private data class LatLonPoint(
    val lat: Double,
    val lon: Double,
)

private data class LonLatPoint(
    val lon: Double,
    val lat: Double,
)

private fun Cursor.stringOrNull(index: Int): String? {
    return if (isNull(index)) null else getString(index)
}

private fun Cursor.doubleOrNull(index: Int): Double? {
    return if (isNull(index)) null else getDouble(index)
}

private data class CandidateSelection(
    val selected: WayCandidate? = null,
    val candidateTraces: List<MatcherCandidateTrace> = emptyList(),
    val nearbyTunnelCandidateWayIds: Set<String> = emptySet(),
    val nearbyTunnelCandidateRefs: Set<String> = emptySet(),
    val portalEligibleTunnelWayIds: Set<String> = emptySet(),
    val portalEligibleTunnelRefs: Set<String> = emptySet(),
    val activeCorridorState: CorridorMatchState? = null,
    val approachCorridorStateCandidate: CorridorMatchState? = null,
    val usedWalkingTurnSwitch: Boolean = false,
)

private enum class ContinuityClass {
    PREFERRED_WAY,
    SAME_REF,
    LINKED_WAY,
    RECENT_WAY,
    NONE,
}

private val ContinuityClass.traceName: String
    get() = when (this) {
        ContinuityClass.PREFERRED_WAY -> "preferredWay"
        ContinuityClass.SAME_REF -> "sameRef"
        ContinuityClass.LINKED_WAY -> "linkedWay"
        ContinuityClass.RECENT_WAY -> "recentWay"
        ContinuityClass.NONE -> "none"
    }

private data class CorridorAnchor(
    val wayId: String,
    val highway: String?,
    val endpointProximityM: Double?,
)

private data class CorridorProgressInfo(
    val kind: String,
    val corridorId: Int,
    val sideNodeKey: String,
    val wayId: String,
    val startDepthM: Double,
    val endDepthM: Double,
    val startDepthNodes: Int,
    val endDepthNodes: Int,
    val spanM: Double,
    val spanNodes: Int,
)

private data class CorridorProgressContext(
    val available: Boolean,
    val byWayId: Map<String?, List<CorridorProgressInfo>> = emptyMap(),
)

private data class CandidateCorridorState(
    val snapshot: CorridorMatchState,
    val entryZone: Boolean,
    val exitZone: Boolean,
)

private data class PortalMotionMetrics(
    val currentPortalDistanceM: Double,
    val bestApproachDeltaM: Double,
    val bestInteriorProgressDeltaM: Double,
    val alignmentScore: Double,
    val proximityScore: Double,
)

private data class WayLinksContext(
    val available: Boolean,
    val linkedByFrom: Map<String, Set<String>> = emptyMap(),
    val sharedRefByFrom: Map<String, Set<String>> = emptyMap(),
    val sharedNodeKeysByPair: Map<Pair<String, String>, Set<String>> = emptyMap(),
) {
    fun isLinked(fromWayId: String?, toWayId: String?): Boolean {
        return fromWayId != null && toWayId != null && (linkedByFrom[fromWayId]?.contains(toWayId) == true)
    }

    fun isSharedRefLinked(fromWayId: String?, toWayId: String?): Boolean {
        return fromWayId != null && toWayId != null && (sharedRefByFrom[fromWayId]?.contains(toWayId) == true)
    }

    fun sharedNodeKeys(fromWayId: String?, toWayId: String?): Set<String> {
        return if (fromWayId != null && toWayId != null) sharedNodeKeysByPair[fromWayId to toWayId].orEmpty() else emptySet()
    }
}

internal data class MatcherCandidateTrace(
    val rank: Int,
    val wayId: String?,
    val score: Double,
    val distanceM: Double,
    val geometryScore: Double?,
    val endpointProximityM: Double,
    val continuityClass: String,
    val highway: String?,
    val service: String?,
    val streetName: String?,
    val streetRef: String?,
    val tunnel: String?,
    val tunnelSelectable: Boolean,
    val corridorSelectable: Boolean,
    val portalEligible: Boolean,
    val isSelected: Boolean,
)
