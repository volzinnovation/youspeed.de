package de.youspeed.android.alpha

import android.database.Cursor
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteException
import java.io.Closeable
import java.util.Locale
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
    val usedMiniHMM: Boolean,
    val miniHMMCandidateCount: Int,
    val matchHypotheses: List<WayMatchHypothesis>,
    val selectionTrace: List<MatchSelectionTrace>,
)

internal class V3SpeedLimitLookup(
    private val dbPath: String,
) : Closeable {
    private val db: SQLiteDatabase = SQLiteDatabase.openDatabase(dbPath, null, SQLiteDatabase.OPEN_READONLY)
    private val hasWaysTable = tableExists("ways")
    private val hasAreasTable = tableExists("areas")
    private val hasCityBoundaryTable = tableExists("city_boundary")
    private val hasCityBoundaryRtreeTable = tableExists("city_boundary_rtree")
    private val hasCityRingTable = tableExists("city_ring")
    private val hasCityPlaceTable = tableExists("city_place")
    private val hasCityPlaceRtreeTable = tableExists("city_place_rtree")
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
    @Volatile private var allowCityBoundaryRtreeQueries = hasCityBoundaryRtreeTable
    @Volatile private var allowCityPlaceRtreeQueries = hasCityPlaceRtreeTable

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
        val observedHeadingDeg = headingDeg?.takeIf {
            speedKmh != null &&
                speedKmh.isFinite() &&
                speedKmh >= HEADING_MIN_SPEED_KMH &&
                it.isFinite()
        }
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
                usedMiniHMM = false,
                miniHMMCandidateCount = 0,
                matchHypotheses = emptyList(),
                selectionTrace = emptyList(),
            )
        }

        val candidates = queryWayCandidates(
            lat = lat,
            lon = lon,
            radiusM = radiusM,
            maxCandidates = maxCandidates,
            headingDeg = observedHeadingDeg,
        )
        val areaCandidates = queryAreaCandidates(lat = lat, lon = lon)
        val cityContext = if (hasCityBoundaryTable && hasCityRingTable) {
            resolveCityContextFromPolygons(
                lat = lat,
                lon = lon,
                hasPlaceTables = hasCityPlaceTable,
            )
        } else {
            resolveCityContextFromAreas(lat = lat, lon = lon, areas = areaCandidates)
        }
        val wayLinks = loadWayLinksContext(normalizedMatchContext, candidates)
        val corridorProgress = loadCorridorProgressContext(candidates)
        val accuracyBufferM = scaledAccuracyBufferM(horizontalAccuracyM)

        val selection = selectCandidate(
            candidates = candidates,
            radiusM = radiusM,
            observedHeadingDeg = observedHeadingDeg,
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
                if (residential.insideCity != null) {
                    residential.insideCity to "residential_polygon"
                } else {
                    cityContext.insideCity to cityContext.citySource
                }
            }
        }
        val effectiveSpeed = when {
            best?.isUnlimitedSpeedLimit == true -> null
            best?.speedLimitKmh != null && best.speedSource == DerivedSpeedSource.HIGHWAY_CLASS && allowsResidentialAreaFallback(best.highway) -> {
                if (insideCityDecision.first == true) 50 else 100
            }
            best?.speedLimitKmh != null -> best.speedLimitKmh
            best != null && allowsResidentialAreaFallback(best.highway) -> {
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
            usedMiniHMM = selection.usedMiniHMM,
            miniHMMCandidateCount = selection.miniHMMCandidateCount,
            matchHypotheses = selection.matchHypotheses,
            selectionTrace = selection.selectionTrace,
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
        val selectionTrace = mutableListOf(
            MatchSelectionTrace(
                step = "context",
                detail = buildString {
                    append("preferred=").append(matchContext.preferredWayId ?: "nil")
                    append(" tunnel_mode=").append(matchContext.isInTunnelMode)
                    append(" motorway_mode=").append(matchContext.isInMotorwayMode)
                    append(" gps_loss=").append(matchContext.hadRecentGpsSignalLoss)
                    append(" tunnel_approach=").append(matchContext.tunnelApproachFixCount)
                    append(" corridor_approach=").append(matchContext.approachCorridorFixCount)
                    append(" match_streak=").append(matchContext.matchedFixCount)
                    append(" accuracy_m=").append(formatMetric(accuracyBufferM))
                },
            ),
        )
        val graphSelectableCandidates = if (shouldApplyConnectedTransitionGate(matchContext, wayLinks)) {
            val connectedCandidates = sortedCandidates.filter {
                isConnectedTransitionCandidate(it, matchContext, wayLinks)
            }
            if (connectedCandidates.isNotEmpty()) {
                if (connectedCandidates.size != sortedCandidates.size) {
                    selectionTrace += MatchSelectionTrace(
                        step = "road_graph_gate",
                        detail = "filtered ${sortedCandidates.size - connectedCandidates.size} disconnected candidates after warmup",
                    )
                }
                connectedCandidates
            } else {
                sortedCandidates
            }
        } else {
            sortedCandidates
        }
        val bestGeometric = graphSelectableCandidates.firstOrNull() ?: return CandidateSelection(selectionTrace = selectionTrace)

        var preferredCandidate: WayCandidate? = null
        var sameRefCandidate: WayCandidate? = null
        var sameRefTransitionCandidate: WayCandidate? = null
        var linkedWayCandidate: WayCandidate? = null
        var recentWayCandidate: WayCandidate? = null
        for (candidate in graphSelectableCandidates) {
            when (continuityClass(candidate, matchContext, wayLinks)) {
                ContinuityClass.PREFERRED_WAY -> if (preferredCandidate == null || isBetterCandidate(candidate, preferredCandidate!!)) preferredCandidate = candidate
                ContinuityClass.SAME_REF -> {
                    if (sameRefCandidate == null || isBetterCandidate(candidate, sameRefCandidate!!)) {
                        sameRefCandidate = candidate
                    }
                    if (normalizedWayId(candidate.wayId) != matchContext.preferredWayId &&
                        (sameRefTransitionCandidate == null || isBetterCandidate(candidate, sameRefTransitionCandidate!!))
                    ) {
                        sameRefTransitionCandidate = candidate
                    }
                }
                ContinuityClass.LINKED_WAY -> if (linkedWayCandidate == null || isBetterCandidate(candidate, linkedWayCandidate!!)) linkedWayCandidate = candidate
                ContinuityClass.RECENT_WAY -> if (recentWayCandidate == null || isBetterCandidate(candidate, recentWayCandidate!!)) recentWayCandidate = candidate
                ContinuityClass.NONE -> Unit
            }
        }

        val portalEligibleTunnels = graphSelectableCandidates.filter {
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
        var usedWalkingTurnSwitch = false

        val nearestAlternativeDistanceCandidate = graphSelectableCandidates
            .filter { normalizedWayId(it.wayId) != normalizedWayId(matchContext.preferredWayId) }
            .minWithOrNull { lhs, rhs ->
                when {
                    isBetterDistanceCandidate(lhs, rhs) -> -1
                    isBetterDistanceCandidate(rhs, lhs) -> 1
                    else -> 0
                }
            }

        var heuristicSelected: WayCandidate? = null
        var lockHeuristicSelection = false
        if (preferredCandidate != null && shouldSuppressImmediateSameRefBounce(bestGeometric, preferredCandidate, matchContext, wayLinks, accuracyBufferM)) {
            heuristicSelected = preferredCandidate
        } else if (preferredCandidate != null &&
            shouldPreferSameRefAlternative(
                preferredCandidate = preferredCandidate,
                alternativeCandidate = bestGeometric,
                observedHeadingDeg = observedHeadingDeg,
                speedKmh = speedKmh,
                accuracyBufferM = accuracyBufferM,
                wayLinks = wayLinks,
                matchContext = matchContext,
            )
        ) {
            heuristicSelected = bestGeometric
            lockHeuristicSelection = true
        } else if (preferredCandidate != null && sameRefTransitionCandidate != null &&
            shouldPromoteSameRefTransition(preferredCandidate, sameRefTransitionCandidate, observedHeadingDeg, speedKmh, accuracyBufferM, wayLinks, matchContext)
        ) {
            heuristicSelected = sameRefTransitionCandidate
            lockHeuristicSelection = true
        } else if (preferredCandidate != null && linkedWayCandidate != null &&
            shouldPromoteLinkedTransition(preferredCandidate, linkedWayCandidate, observedHeadingDeg, speedKmh, accuracyBufferM, wayLinks)
        ) {
            heuristicSelected = linkedWayCandidate
            lockHeuristicSelection = true
        } else if (preferredCandidate != null && nearestAlternativeDistanceCandidate != null &&
            shouldForceGeometricCandidateAtWalkingSpeed(preferredCandidate, nearestAlternativeDistanceCandidate, speedKmh, accuracyBufferM, matchContext)
        ) {
            heuristicSelected = nearestAlternativeDistanceCandidate
            lockHeuristicSelection = true
            usedWalkingTurnSwitch = true
            selectionTrace += MatchSelectionTrace(
                step = "low_speed_rule",
                detail = "selected geometric turn ${nearestAlternativeDistanceCandidate.wayId ?: "nil"} over preferred ${preferredCandidate.wayId ?: "nil"} at walking speed",
            )
        } else if (preferredCandidate != null &&
            shouldKeepContinuityCandidate(preferredCandidate, bestGeometric, radiusM, accuracyBufferM, PREFERRED_WAY_SCORE_SLACK_M, PREFERRED_WAY_DISTANCE_MULTIPLIER, PREFERRED_WAY_DISTANCE_FLOOR_M)
        ) {
            heuristicSelected = preferredCandidate
        } else if (sameRefCandidate != null &&
            shouldKeepContinuityCandidate(sameRefCandidate, bestGeometric, radiusM, accuracyBufferM, SAME_REF_SCORE_SLACK_M, SAME_REF_DISTANCE_MULTIPLIER, SAME_REF_DISTANCE_FLOOR_M)
        ) {
            heuristicSelected = sameRefCandidate
        } else if (linkedWayCandidate != null &&
            shouldKeepContinuityCandidate(linkedWayCandidate, bestGeometric, radiusM, accuracyBufferM, LINKED_WAY_SCORE_SLACK_M, LINKED_WAY_DISTANCE_MULTIPLIER, LINKED_WAY_DISTANCE_FLOOR_M)
        ) {
            heuristicSelected = linkedWayCandidate
        } else if (recentWayCandidate != null &&
            shouldKeepContinuityCandidate(recentWayCandidate, bestGeometric, radiusM, accuracyBufferM, RECENT_WAY_SCORE_SLACK_M, RECENT_WAY_DISTANCE_MULTIPLIER, RECENT_WAY_DISTANCE_FLOOR_M)
        ) {
            heuristicSelected = recentWayCandidate
        } else {
            heuristicSelected = bestGeometric
        }
        heuristicSelected?.let {
            selectionTrace += MatchSelectionTrace(
                step = "heuristic",
                detail = "selected ${it.wayId ?: "nil"} continuity=${continuityClass(it, matchContext, wayLinks).traceName}",
            )
        }

        val miniHMMSelection = if (lockHeuristicSelection) {
            MiniHMMSelection()
        } else {
            selectMiniHMMCandidate(
                candidates = graphSelectableCandidates,
                matchContext = matchContext,
                preferredCandidate = preferredCandidate,
                sameRefTransitionCandidate = sameRefTransitionCandidate,
                observedHeadingDeg = observedHeadingDeg,
                speedKmh = speedKmh,
                wayLinks = wayLinks,
            )
        }
        val usedMiniHMM = !lockHeuristicSelection && miniHMMSelection.selectedCandidate != null
        val baselineSelected = when {
            lockHeuristicSelection -> heuristicSelected
            heuristicSelected != null && miniHMMSelection.selectedCandidate != null -> {
                val heuristicContinuity = continuityClass(heuristicSelected, matchContext, wayLinks)
                val hmmContinuity = continuityClass(miniHMMSelection.selectedCandidate, matchContext, wayLinks)
                if (continuityPriority(heuristicContinuity) > continuityPriority(hmmContinuity)) heuristicSelected else miniHMMSelection.selectedCandidate
            }
            miniHMMSelection.selectedCandidate != null -> miniHMMSelection.selectedCandidate
            else -> heuristicSelected
        }

        val traceRankedCandidates = buildTraceRankedCandidates(
            candidates = sortedCandidates,
            matchContext = matchContext,
            wayLinks = wayLinks,
            corridorProgress = corridorProgress,
            accuracyBufferM = accuracyBufferM,
        )
        val traceTop2Margin = top2TraceMargin(traceRankedCandidates)
        val threeWayGateSelection = if (!lockHeuristicSelection && shouldUseThreeWayGate(baselineSelected, matchContext)) {
            selectThreeWayGateCandidate(
                candidates = traceRankedCandidates,
                currentSelected = baselineSelected,
                miniHMMSelected = miniHMMSelection.selectedCandidate,
                usedMiniHMM = usedMiniHMM,
                speedKmh = speedKmh,
                horizontalAccuracyM = horizontalAccuracyM,
                gpsSignalBars = gpsSignalBars,
                top2Margin = traceTop2Margin,
            )
        } else {
            null
        }

        val selectedAfterThreeWay = if (threeWayGateSelection != null) {
            if (baselineSelected != null &&
                shouldSuppressImmediateSameRefBounce(threeWayGateSelection.candidate, baselineSelected, matchContext, wayLinks, accuracyBufferM)
            ) {
                selectionTrace += MatchSelectionTrace(
                    step = "same_ref_bounce_gate",
                    detail = "kept ${baselineSelected.wayId ?: "nil"} over ${threeWayGateSelection.candidate.wayId ?: "nil"} to avoid immediate same-ref bounce",
                )
                baselineSelected
            } else if (baselineSelected != null &&
                normalizedWayId(threeWayGateSelection.candidate.wayId) != normalizedWayId(baselineSelected.wayId) &&
                shouldRejectTurnTransition(baselineSelected, threeWayGateSelection.candidate, observedHeadingDeg, speedKmh, baselineSelected.endpointProximityM)
            ) {
                selectionTrace += MatchSelectionTrace(
                    step = "turn_feasibility_gate",
                    detail = "kept ${baselineSelected.wayId ?: "nil"} over ${threeWayGateSelection.candidate.wayId ?: "nil"} due to speed/heading feasibility",
                )
                baselineSelected
            } else {
                selectionTrace += MatchSelectionTrace(
                    step = "three_way_gate",
                    detail = "selected ${threeWayGateSelection.candidate.wayId ?: "nil"} class=${threeWayGateSelection.className} probs=${threeWayGateSelection.probabilitySummary} current=${baselineSelected?.wayId ?: "nil"} distance=${threeWayGateSelection.distanceWayId ?: "nil"} endpoint=${threeWayGateSelection.endpointWayId ?: "nil"} heuristic=${heuristicSelected?.wayId ?: "nil"} mini=${miniHMMSelection.selectedCandidate?.wayId ?: "nil"}",
                )
                threeWayGateSelection.candidate
            }
        } else {
            baselineSelected
        }

        miniHMMSelection.selectedCandidate?.let {
            selectionTrace += MatchSelectionTrace(
                step = "mini_hmm",
                detail = "selected ${it.wayId ?: "nil"} beam=${miniHMMSelection.candidateCount}",
            )
        }

        var selected = selectedAfterThreeWay ?: bestGeometric

        val bestPortalEligibleTunnel = portalEligibleTunnels.firstOrNull()
        if (bestPortalEligibleTunnel != null && bestPortalEligibleTunnel != selected &&
            shouldPromoteTunnelEntry(bestPortalEligibleTunnel, selected, matchContext, wayLinks, corridorProgress, horizontalAccuracyM, gpsSignalBars, accuracyBufferM)
        ) {
            selected = bestPortalEligibleTunnel
            selectionTrace += MatchSelectionTrace(
                step = "tunnel_entry_gate",
                detail = "promoted tunnel ${bestPortalEligibleTunnel.wayId ?: "nil"} over surface ${selectedAfterThreeWay?.wayId ?: "nil"} after repeated portal exposure and degraded signal quality",
            )
        }
        if (!isTruthyOsmTag(selected.tunnel) && matchContext.isInTunnelMode) {
            val tunnelContinuityCandidate = graphSelectableCandidates.firstOrNull { candidate ->
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
                selectionTrace += MatchSelectionTrace(
                    step = "tunnel_exit_gate",
                    detail = "kept tunnel ${tunnelContinuityCandidate.wayId ?: "nil"} and rejected mid-segment surface exit ${selectedAfterThreeWay?.wayId ?: "nil"}",
                )
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
        val candidateTraces = traceRankedCandidates
            .take(MAX_TRACE_CANDIDATE_COUNT)
            .map { entry ->
                MatcherCandidateTrace(
                    rank = entry.traceRank,
                    wayId = entry.candidate.wayId,
                    score = entry.traceScore,
                    distanceM = entry.candidate.distanceM,
                    geometryScore = entry.candidate.score,
                    endpointProximityM = entry.candidate.endpointProximityM,
                    continuityClass = entry.continuity.traceName,
                    highway = entry.candidate.highway,
                    service = entry.candidate.service,
                    streetName = entry.candidate.streetName,
                    streetRef = entry.candidate.streetRef,
                    tunnel = entry.candidate.tunnel,
                    tunnelSelectable = entry.tunnelSelectable,
                    corridorSelectable = entry.corridorSelectable,
                    portalEligible = entry.portalEligible,
                    isSelected = normalizedWayId(entry.candidate.wayId) == selectedWayId,
                )
            }
        selectionTrace += MatchSelectionTrace(
            step = "final",
            detail = "selected ${selected.wayId ?: "nil"} tunnel=${isTruthyOsmTag(selected.tunnel)} corridor=${activeCorridorState?.kind ?: "none"}",
        )

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
            usedMiniHMM = usedMiniHMM,
            miniHMMCandidateCount = miniHMMSelection.candidateCount,
            matchHypotheses = miniHMMSelection.hypotheses,
            selectionTrace = selectionTrace,
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
        wayIds += matchContext.recentHypotheses.mapTo(linkedSetOf()) { it.wayId }
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

    private fun shouldApplyConnectedTransitionGate(
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
    ): Boolean {
        if (!wayLinks.available || matchContext.hadRecentGpsSignalLoss) {
            return false
        }
        if (matchContext.matchedFixCount < CONNECTED_TRANSITION_WARMUP_FIX_COUNT) {
            return false
        }
        return matchContext.preferredWayId != null || matchContext.recentWayIds.isNotEmpty()
    }

    private fun isConnectedTransitionCandidate(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
    ): Boolean {
        val candidateWayId = normalizedWayId(candidate.wayId)
        if (candidateWayId == matchContext.preferredWayId) {
            return true
        }
        if (candidateWayId != null && candidateWayId in matchContext.recentWayIds) {
            return true
        }
        return isLinkedCandidate(candidateWayId, matchContext, wayLinks)
    }

    private fun shouldPreferSameRefAlternative(
        preferredCandidate: WayCandidate,
        alternativeCandidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        accuracyBufferM: Double,
        wayLinks: WayLinksContext,
        matchContext: WayMatchContext,
    ): Boolean {
        if (normalizedWayId(preferredCandidate.wayId) == normalizedWayId(alternativeCandidate.wayId)) {
            return false
        }
        if (shouldSuppressImmediateSameRefBounce(alternativeCandidate, preferredCandidate, matchContext, wayLinks, accuracyBufferM)) {
            return false
        }
        val preferredRefTokens = normalizedRefTokens(preferredCandidate.streetRef).toSet()
        val alternativeRefTokens = normalizedRefTokens(alternativeCandidate.streetRef).toSet()
        if (preferredRefTokens.isEmpty() || preferredRefTokens.intersect(alternativeRefTokens).isEmpty()) {
            return false
        }
        if (wayLinks.available && !isLinkedCandidate(normalizedWayId(alternativeCandidate.wayId), matchContext, wayLinks)) {
            return false
        }
        if (alternativeCandidate.distanceM + accuracyBufferM + 10.0 < preferredCandidate.distanceM) {
            return true
        }
        return shouldPromoteSameRefTransition(
            preferredCandidate = preferredCandidate,
            transitionCandidate = alternativeCandidate,
            observedHeadingDeg = observedHeadingDeg,
            speedKmh = speedKmh,
            accuracyBufferM = accuracyBufferM,
            wayLinks = wayLinks,
            matchContext = matchContext,
        )
    }

    private fun selectMiniHMMCandidate(
        candidates: List<WayCandidate>,
        matchContext: WayMatchContext,
        preferredCandidate: WayCandidate?,
        sameRefTransitionCandidate: WayCandidate?,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        wayLinks: WayLinksContext,
    ): MiniHMMSelection {
        if (!shouldUseMiniHMM(candidates, matchContext, preferredCandidate, sameRefTransitionCandidate)) {
            return MiniHMMSelection()
        }
        val beamCandidates = candidates.take(MINI_HMM_BEAM_WIDTH)
        if (beamCandidates.isEmpty()) {
            return MiniHMMSelection()
        }

        val hypotheses = mutableListOf<WayMatchHypothesis>()
        for (candidate in beamCandidates) {
            val wayId = normalizedWayId(candidate.wayId) ?: continue
            val emission = candidate.score + miniHMMPriorAdjustment(candidate, matchContext)
            val cumulativeCost = if (matchContext.recentHypotheses.isEmpty()) {
                emission
            } else {
                matchContext.recentHypotheses.minOfOrNull { hypothesis ->
                    (hypothesis.cumulativeCost * MINI_HMM_HISTORY_DECAY) +
                        genericTransitionPenalty(
                            hypothesis = hypothesis,
                            candidate = candidate,
                            observedHeadingDeg = observedHeadingDeg,
                            speedKmh = speedKmh,
                            matchContext = matchContext,
                            wayLinks = wayLinks,
                        ) +
                        emission
                } ?: emission
            }
            val startPoint = candidate.points.firstOrNull()
            val endPoint = candidate.points.lastOrNull()
            hypotheses += WayMatchHypothesis(
                wayId = wayId,
                streetRef = candidate.streetRef,
                highway = candidate.highway,
                cumulativeCost = cumulativeCost,
                emissionScore = candidate.score,
                endpointProximityM = candidate.endpointProximityM,
                startLat = startPoint?.lat,
                startLon = startPoint?.lon,
                endLat = endPoint?.lat,
                endLon = endPoint?.lon,
                isTunnel = isTruthyOsmTag(candidate.tunnel),
            )
        }
        hypotheses.sortWith(
            compareBy<WayMatchHypothesis> { it.cumulativeCost }
                .thenBy { it.emissionScore }
                .thenBy { it.wayId },
        )
        if (hypotheses.size > MINI_HMM_BEAM_WIDTH) {
            hypotheses.subList(MINI_HMM_BEAM_WIDTH, hypotheses.size).clear()
        }
        val selectedWayId = hypotheses.firstOrNull()?.wayId
        val selectedCandidate = beamCandidates.firstOrNull { normalizedWayId(it.wayId) == selectedWayId }
        return MiniHMMSelection(
            selectedCandidate = selectedCandidate,
            hypotheses = hypotheses,
            used = selectedCandidate != null,
            candidateCount = beamCandidates.size,
        )
    }

    private fun shouldUseMiniHMM(
        candidates: List<WayCandidate>,
        matchContext: WayMatchContext,
        preferredCandidate: WayCandidate?,
        sameRefTransitionCandidate: WayCandidate?,
    ): Boolean {
        if (matchContext.recentHypotheses.isNotEmpty()) {
            return candidates.size > 1
        }
        if (candidates.size <= 1) {
            return false
        }
        val best = candidates[0]
        val second = candidates[1]
        if (second.score - best.score <= MINI_HMM_AMBIGUOUS_SCORE_GAP_M) {
            return true
        }
        if (preferredCandidate != null && normalizedWayId(preferredCandidate.wayId) != normalizedWayId(best.wayId)) {
            return true
        }
        if (sameRefTransitionCandidate != null) {
            return true
        }
        return candidates.take(MINI_HMM_BEAM_WIDTH).any { isTruthyOsmTag(it.tunnel) }
    }

    private fun miniHMMPriorAdjustment(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
    ): Double {
        var adjustment = 0.0
        val candidateWayId = normalizedWayId(candidate.wayId)
        val candidateRefTokens = normalizedRefTokens(candidate.streetRef).toSet()

        if (candidateWayId == matchContext.preferredWayId) {
            adjustment -= 8.0
        } else if (candidateWayId != null && candidateWayId in matchContext.recentWayIds) {
            adjustment -= 2.5
        }
        if (candidateRefTokens.isNotEmpty() && candidateRefTokens.any(matchContext.recentStreetRefs::contains)) {
            adjustment -= 3.5
        }
        val recentTunnelWayMatch = candidateWayId?.let { it in matchContext.recentTunnelCandidateWayIds } == true
        if (matchContext.isInTunnelMode) {
            adjustment += if (isTruthyOsmTag(candidate.tunnel)) -6.0 else 10.0
        }
        if (isTruthyOsmTag(candidate.tunnel) &&
            matchContext.hadRecentGpsSignalLoss &&
            (recentTunnelWayMatch || candidateRefTokens.any(matchContext.recentTunnelCandidateRefs::contains))
        ) {
            adjustment -= 2.0
        }
        return adjustment
    }

    private fun genericTransitionPenalty(
        hypothesis: WayMatchHypothesis,
        candidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
    ): Double {
        val candidateWayId = normalizedWayId(candidate.wayId) ?: return MINI_HMM_UNRELATED_TRANSITION_PENALTY_M
        if (candidateWayId == hypothesis.wayId) {
            return 0.0
        }

        val basePenalty = when {
            wayLinks.isSharedRefLinked(hypothesis.wayId, candidateWayId) -> MINI_HMM_SHARED_REF_LINKED_TRANSITION_PENALTY_M
            wayLinks.isLinked(hypothesis.wayId, candidateWayId) -> MINI_HMM_LINKED_WAY_TRANSITION_PENALTY_M
            else -> {
                val candidateRefTokens = normalizedRefTokens(candidate.streetRef).toSet()
                val previousRefTokens = normalizedRefTokens(hypothesis.streetRef).toSet()
                when {
                    candidateRefTokens.isNotEmpty() && candidateRefTokens.intersect(previousRefTokens).isNotEmpty() -> {
                        if (wayLinks.available) {
                            MINI_HMM_UNRELATED_TRANSITION_PENALTY_M
                        } else if (hypothesis.endpointProximityM <= SEGMENT_TRANSITION_ENDPOINT_THRESHOLD_M ||
                            candidate.endpointProximityM <= SEGMENT_TRANSITION_ENDPOINT_THRESHOLD_M * 2.0
                        ) {
                            1.5
                        } else {
                            MINI_HMM_SAME_REF_TRANSITION_PENALTY_M
                        }
                    }
                    candidateWayId in matchContext.recentWayIds -> MINI_HMM_RECENT_WAY_TRANSITION_PENALTY_M
                    !wayLinks.available && hasEndpointContinuation(hypothesis, candidate) -> MINI_HMM_ENDPOINT_CONNECTION_PENALTY_M
                    highwayFamily(hypothesis.highway) != null && highwayFamily(hypothesis.highway) == highwayFamily(candidate.highway) -> {
                        MINI_HMM_HIGHWAY_CLASS_TRANSITION_PENALTY_M
                    }
                    else -> MINI_HMM_UNRELATED_TRANSITION_PENALTY_M
                }
            }
        }

        val bouncePenalty = if (isImmediateSameRefBounceTransition(hypothesis, candidate, matchContext, wayLinks)) {
            SAME_REF_BOUNCE_PENALTY_M
        } else {
            0.0
        }
        val headingAdjustment = transitionHeadingPenaltyAdjustment(
            fromAxisHeadingDeg = axisHeadingDeg(hypothesis.startLat, hypothesis.startLon, hypothesis.endLat, hypothesis.endLon),
            fromEndpointProximityM = hypothesis.endpointProximityM,
            candidate = candidate,
            observedHeadingDeg = observedHeadingDeg,
            speedKmh = speedKmh,
        )
        return max(0.0, basePenalty + bouncePenalty + headingAdjustment)
    }

    private fun buildTraceRankedCandidates(
        candidates: List<WayCandidate>,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        corridorProgress: CorridorProgressContext,
        accuracyBufferM: Double,
    ): List<TraceRankedCandidate> {
        val maxGeometryScore = candidates.maxOfOrNull { it.score } ?: 0.0
        val sorted = candidates
            .map { candidate ->
                val continuity = continuityClass(candidate, matchContext, wayLinks)
                val corridorState = candidateCorridorState(candidate, matchContext, wayLinks, corridorProgress)
                val portalEligible = isPortalEligibleTunnelCandidate(
                    candidate = candidate,
                    matchContext = matchContext,
                    wayLinks = wayLinks,
                    corridorProgress = corridorProgress,
                    accuracyBufferM = accuracyBufferM,
                )
                TraceRankedCandidate(
                    candidate = candidate,
                    continuity = continuity,
                    portalEligible = portalEligible,
                    corridorState = corridorState,
                    tunnelSelectable = isTruthyOsmTag(candidate.tunnel) || portalEligible || corridorState != null,
                    corridorSelectable = true,
                    traceScore = traceRankingScore(candidate, continuity, maxGeometryScore),
                    traceRank = 0,
                )
            }
            .sortedWith(
                compareBy<TraceRankedCandidate> { it.traceScore }
                    .thenBy { it.candidate.distanceM }
                    .thenBy { it.candidate.wayId ?: "~" },
            )
        return sorted.mapIndexed { index, entry -> entry.copy(traceRank = index + 1) }
    }

    private fun top2TraceMargin(candidates: List<TraceRankedCandidate>): Double {
        return if (candidates.size >= 2) candidates[1].traceScore - candidates[0].traceScore else 0.0
    }

    private fun selectThreeWayGateCandidate(
        candidates: List<TraceRankedCandidate>,
        currentSelected: WayCandidate?,
        miniHMMSelected: WayCandidate?,
        usedMiniHMM: Boolean,
        speedKmh: Double?,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
        top2Margin: Double,
    ): ThreeWayGateSelection? {
        val eligibleCandidates = candidates.filter { it.corridorSelectable }
        val currentTrace = eligibleCandidates.firstOrNull { normalizedWayId(it.candidate.wayId) == normalizedWayId(currentSelected?.wayId) } ?: return null
        val distanceTrace = eligibleCandidates.minWithOrNull(
            compareBy<TraceRankedCandidate> { it.candidate.distanceM }
                .thenBy { it.traceRank }
                .thenBy { it.traceScore },
        ) ?: return null
        val endpointTrace = eligibleCandidates.minWithOrNull(
            compareBy<TraceRankedCandidate> {
                if (it.candidate.endpointProximityM.isFinite()) it.candidate.endpointProximityM else Double.POSITIVE_INFINITY
            }.thenBy { it.candidate.distanceM }
                .thenBy { it.traceRank }
                .thenBy { it.traceScore },
        ) ?: return null
        val uniqueExpertWayIds = setOfNotNull(
            normalizedWayId(currentTrace.candidate.wayId),
            normalizedWayId(distanceTrace.candidate.wayId),
            normalizedWayId(endpointTrace.candidate.wayId),
        )
        if (uniqueExpertWayIds.size <= 1) {
            return null
        }
        val featureValues = threeWayGateFeatureValues(
            current = currentTrace,
            distance = distanceTrace,
            endpoint = endpointTrace,
            miniHMMSelected = miniHMMSelected,
            usedMiniHMM = usedMiniHMM,
            speedKmh = speedKmh,
            horizontalAccuracyM = horizontalAccuracyM,
            gpsSignalBars = gpsSignalBars,
            top2Margin = top2Margin,
        )
        val probabilities = threeWayGateModelProbabilities(featureValues)
        val predictedIndex = probabilities.indices.maxByOrNull { probabilities[it] } ?: return null
        val chosenTrace = when (predictedIndex) {
            1 -> distanceTrace
            2 -> endpointTrace
            else -> currentTrace
        }
        val probabilitySummary = THREE_WAY_GATE_CLASS_NAMES.mapIndexed { index, name ->
            "$name=${formatProbability(probabilities[index])}"
        }.joinToString(",")
        return ThreeWayGateSelection(
            candidate = chosenTrace.candidate,
            className = THREE_WAY_GATE_CLASS_NAMES[predictedIndex],
            probabilitySummary = probabilitySummary,
            distanceWayId = distanceTrace.candidate.wayId,
            endpointWayId = endpointTrace.candidate.wayId,
        )
    }

    private fun shouldUseThreeWayGate(
        currentSelected: WayCandidate?,
        matchContext: WayMatchContext,
    ): Boolean {
        if (currentSelected == null || matchContext.recentHypotheses.size < 2) {
            return false
        }
        if (matchContext.isInTunnelMode) {
            return false
        }
        return !isTruthyOsmTag(currentSelected.tunnel)
    }

    private fun threeWayGateFeatureValues(
        current: TraceRankedCandidate,
        distance: TraceRankedCandidate,
        endpoint: TraceRankedCandidate,
        miniHMMSelected: WayCandidate?,
        usedMiniHMM: Boolean,
        speedKmh: Double?,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
        top2Margin: Double,
    ): MutableMap<String, Double> {
        val miniWayId = normalizedWayId(miniHMMSelected?.wayId)
        val currentEndpoint = current.candidate.endpointProximityM.takeIf { it.isFinite() } ?: Double.POSITIVE_INFINITY
        val distanceEndpoint = distance.candidate.endpointProximityM.takeIf { it.isFinite() } ?: Double.POSITIVE_INFINITY
        val endpointEndpoint = endpoint.candidate.endpointProximityM.takeIf { it.isFinite() } ?: Double.POSITIVE_INFINITY
        val values = linkedMapOf(
            "bias" to 1.0,
            "speed_kmh" to (speedKmh ?: 0.0),
            "horizontal_acc_m" to (horizontalAccuracyM ?: 0.0),
            "gps_signal_bars" to (gpsSignalBars?.toDouble() ?: 0.0),
            "top2_margin" to top2Margin,
            "used_mini_hmm" to if (usedMiniHMM) 1.0 else 0.0,
            "current_distance_m" to current.candidate.distanceM,
            "distance_distance_m" to distance.candidate.distanceM,
            "endpoint_distance_m" to endpoint.candidate.distanceM,
            "current_endpoint_m" to currentEndpoint,
            "distance_endpoint_m" to distanceEndpoint,
            "endpoint_endpoint_m" to endpointEndpoint,
            "current_score" to current.traceScore,
            "distance_score" to distance.traceScore,
            "endpoint_score" to endpoint.traceScore,
            "current_rank" to current.traceRank.toDouble(),
            "distance_rank" to distance.traceRank.toDouble(),
            "endpoint_rank" to endpoint.traceRank.toDouble(),
            "current_low_endpoint" to if (currentEndpoint <= 12.0) 1.0 else 0.0,
            "distance_low_endpoint" to if (distanceEndpoint <= 12.0) 1.0 else 0.0,
            "endpoint_low_endpoint" to if (endpointEndpoint <= 12.0) 1.0 else 0.0,
            "current_rank1" to if (current.traceRank <= 1) 1.0 else 0.0,
            "distance_rank1" to if (distance.traceRank <= 1) 1.0 else 0.0,
            "endpoint_rank1" to if (endpoint.traceRank <= 1) 1.0 else 0.0,
            "current_mini_match" to if (normalizedWayId(current.candidate.wayId) == miniWayId) 1.0 else 0.0,
            "distance_mini_match" to if (normalizedWayId(distance.candidate.wayId) == miniWayId) 1.0 else 0.0,
            "endpoint_mini_match" to if (normalizedWayId(endpoint.candidate.wayId) == miniWayId) 1.0 else 0.0,
            "current_has_ref" to if (!current.candidate.streetRef.isNullOrEmpty()) 1.0 else 0.0,
            "distance_has_ref" to if (!distance.candidate.streetRef.isNullOrEmpty()) 1.0 else 0.0,
            "endpoint_has_ref" to if (!endpoint.candidate.streetRef.isNullOrEmpty()) 1.0 else 0.0,
            "current_is_service" to if (!current.candidate.service.isNullOrEmpty()) 1.0 else 0.0,
            "distance_is_service" to if (!distance.candidate.service.isNullOrEmpty()) 1.0 else 0.0,
            "endpoint_is_service" to if (!endpoint.candidate.service.isNullOrEmpty()) 1.0 else 0.0,
        )
        threeWayGatePairFeatures(current, distance, "cd", values)
        threeWayGatePairFeatures(current, endpoint, "ce", values)
        threeWayGatePairFeatures(distance, endpoint, "de", values)
        listOf("current" to current, "distance" to distance, "endpoint" to endpoint).forEach { (prefix, traceCandidate) ->
            val continuityName = traceCandidate.continuity.traceName
            listOf("preferredWay", "sameRef", "linkedWay", "recentWay", "none").forEach { name ->
                values["${prefix}_cont_$name"] = if (continuityName == name) 1.0 else 0.0
            }
        }
        return values
    }

    private fun threeWayGatePairFeatures(
        left: TraceRankedCandidate,
        right: TraceRankedCandidate,
        prefix: String,
        values: MutableMap<String, Double>,
    ) {
        val leftEndpoint = left.candidate.endpointProximityM.takeIf { it.isFinite() } ?: Double.POSITIVE_INFINITY
        val rightEndpoint = right.candidate.endpointProximityM.takeIf { it.isFinite() } ?: Double.POSITIVE_INFINITY
        values["${prefix}_distance_advantage_m"] = left.candidate.distanceM - right.candidate.distanceM
        values["${prefix}_score_advantage"] = left.traceScore - right.traceScore
        values["${prefix}_endpoint_advantage_m"] = leftEndpoint - rightEndpoint
        values["${prefix}_rank_advantage"] = (left.traceRank - right.traceRank).toDouble()
        values["${prefix}_band_advantage"] = continuityBand(left.continuity) - continuityBand(right.continuity)
        values["${prefix}_same_ref"] = if (!left.candidate.streetRef.isNullOrEmpty() && left.candidate.streetRef == right.candidate.streetRef) 1.0 else 0.0
        values["${prefix}_same_highway"] = if (threeWayGateHighwayBucket(left.candidate.highway) == threeWayGateHighwayBucket(right.candidate.highway)) 1.0 else 0.0
        values["${prefix}_same_continuity"] = if (left.continuity == right.continuity) 1.0 else 0.0
    }

    private fun threeWayGateModelProbabilities(featureValues: Map<String, Double>): DoubleArray {
        val cdDistanceAdvantage = featureValues["cd_distance_advantage_m"] ?: 0.0
        val currentLowEndpoint = featureValues["current_low_endpoint"] ?: 0.0
        val endpointScore = featureValues["endpoint_score"] ?: 0.0
        val currentDistance = featureValues["current_distance_m"] ?: 0.0
        val ceDistanceAdvantage = featureValues["ce_distance_advantage_m"] ?: 0.0
        val speedKmh = featureValues["speed_kmh"] ?: 0.0
        val cdEndpointAdvantage = featureValues["cd_endpoint_advantage_m"] ?: 0.0
        val currentEndpoint = featureValues["current_endpoint_m"] ?: 0.0
        return if (cdDistanceAdvantage <= 0.031331026678) {
            if (currentLowEndpoint <= 0.5) {
                if (endpointScore <= 83.636764487926) {
                    if (currentDistance <= 10.729136905329) {
                        doubleArrayOf(0.786314873876, 0.0, 0.213685126124)
                    } else {
                        doubleArrayOf(0.115246098439, 0.0, 0.884753901561)
                    }
                } else {
                    doubleArrayOf(1.0, 0.0, 0.0)
                }
            } else if (ceDistanceAdvantage <= -5.659849937512) {
                doubleArrayOf(1.0, 0.0, 0.0)
            } else if (speedKmh <= 79.173) {
                doubleArrayOf(0.003416126966, 0.0, 0.996583873034)
            } else {
                doubleArrayOf(0.0, 0.218181818182, 0.781818181818)
            }
        } else if (speedKmh <= 90.5628) {
            if (cdEndpointAdvantage <= 5.937269380776) {
                if (currentEndpoint <= 43.319029628448) {
                    doubleArrayOf(0.001474900959, 0.998525099041, 0.0)
                } else {
                    doubleArrayOf(0.14896073903, 0.85103926097, 0.0)
                }
            } else if (currentDistance <= 12.14417458337) {
                doubleArrayOf(1.0, 0.0, 0.0)
            } else {
                doubleArrayOf(0.225840336134, 0.774159663866, 0.0)
            }
        } else if (speedKmh <= 98.5264) {
            doubleArrayOf(1.0, 0.0, 0.0)
        } else {
            doubleArrayOf(0.031537450723, 0.0, 0.968462549277)
        }
    }

    private fun transitionHeadingPenaltyAdjustment(
        fromAxisHeadingDeg: Double?,
        fromEndpointProximityM: Double,
        candidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
    ): Double {
        val evidence = transitionHeadingEvidence(
            fromAxisHeadingDeg = fromAxisHeadingDeg,
            fromEndpointProximityM = fromEndpointProximityM,
            candidate = candidate,
            observedHeadingDeg = observedHeadingDeg,
            speedKmh = speedKmh,
        ) ?: return 0.0
        if (evidence.currentAligned && evidence.meaningfulTurn && !evidence.candidateClearlyBetterAligned) {
            if (evidence.serviceLike && evidence.speedKmh >= TRANSITION_SERVICE_ROAD_SPEED_KMH) {
                return TRANSITION_VERY_SHARP_TURN_PENALTY_M
            }
            if (evidence.verySharpTurn && evidence.speedKmh >= TRANSITION_MODERATE_SPEED_KMH) {
                return TRANSITION_VERY_SHARP_TURN_PENALTY_M
            }
            if (evidence.sharpTurn && evidence.speedKmh >= TRANSITION_HIGH_SPEED_KMH) {
                return TRANSITION_SHARP_TURN_PENALTY_M
            }
        }
        if (evidence.nearEndpoint && evidence.candidateClearlyBetterAligned && evidence.meaningfulTurn) {
            return if (evidence.speedKmh <= TRANSITION_HIGH_SPEED_KMH) {
                -TRANSITION_HEADING_BONUS_M
            } else {
                -(TRANSITION_HEADING_BONUS_M * 0.5)
            }
        }
        return 0.0
    }

    private fun transitionHeadingEvidence(
        fromAxisHeadingDeg: Double?,
        fromEndpointProximityM: Double,
        candidate: WayCandidate,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
    ): TransitionHeadingEvidence? {
        if (observedHeadingDeg == null || speedKmh == null || !speedKmh.isFinite() || speedKmh < HEADING_MIN_SPEED_KMH) {
            return null
        }
        val sourceHeading = fromAxisHeadingDeg ?: return null
        val candidateHeading = axisHeadingDeg(candidate) ?: return null
        val currentMismatchDeg = headingMismatchDeg(observedHeadingDeg, sourceHeading)
        val candidateMismatchDeg = headingMismatchDeg(observedHeadingDeg, candidateHeading)
        val turnAngleDeg = headingMismatchDeg(sourceHeading, candidateHeading)
        val nearEndpoint = fromEndpointProximityM <= SEGMENT_TRANSITION_ENDPOINT_THRESHOLD_M &&
            candidate.endpointProximityM <= (SEGMENT_TRANSITION_ENDPOINT_THRESHOLD_M * 2.0)
        val serviceLike = !candidate.service.isNullOrEmpty() || candidate.highway?.lowercase() == "service"
        return TransitionHeadingEvidence(
            currentMismatchDeg = currentMismatchDeg,
            candidateMismatchDeg = candidateMismatchDeg,
            turnAngleDeg = turnAngleDeg,
            speedKmh = speedKmh,
            nearEndpoint = nearEndpoint,
            serviceLike = serviceLike,
        )
    }

    private fun isImmediateSameRefBounceTransition(
        hypothesis: WayMatchHypothesis,
        candidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
    ): Boolean {
        if (hypothesis.wayId != matchContext.preferredWayId) {
            return false
        }
        val candidateWayId = normalizedWayId(candidate.wayId) ?: return false
        if (candidateWayId == hypothesis.wayId) {
            return false
        }
        val pseudoPreferred = WayCandidate(
            wayId = hypothesis.wayId,
            highway = hypothesis.highway,
            service = null,
            tunnel = if (hypothesis.isTunnel) "yes" else null,
            streetName = null,
            streetBaseName = null,
            streetRef = hypothesis.streetRef,
            speedLimitKmh = null,
            speedSource = DerivedSpeedSource.NONE,
            isUnlimitedSpeedLimit = false,
            distanceM = 0.0,
            endpointProximityM = hypothesis.endpointProximityM,
            distanceToStartM = 0.0,
            distanceToEndM = 0.0,
            score = hypothesis.emissionScore,
            queryPoint = LatLonPoint(lat = hypothesis.startLat ?: 0.0, lon = hypothesis.startLon ?: 0.0),
            points = emptyList(),
            localHeadingDeg = axisHeadingDeg(hypothesis.startLat, hypothesis.startLon, hypothesis.endLat, hypothesis.endLon),
            startHeadingDeg = axisHeadingDeg(hypothesis.startLat, hypothesis.startLon, hypothesis.endLat, hypothesis.endLon),
            endHeadingDeg = axisHeadingDeg(hypothesis.startLat, hypothesis.startLon, hypothesis.endLat, hypothesis.endLon),
        )
        return isImmediateSameRefBounceCandidate(candidate, pseudoPreferred, matchContext, wayLinks)
    }

    private fun hasEndpointContinuation(
        hypothesis: WayMatchHypothesis,
        candidate: WayCandidate,
    ): Boolean {
        val previousFamily = highwayFamily(hypothesis.highway)
        val currentFamily = highwayFamily(candidate.highway)
        if (previousFamily == null || currentFamily == null || previousFamily != currentFamily) {
            return false
        }
        if (hypothesis.endpointProximityM > MINI_HMM_ENDPOINT_CANDIDATE_THRESHOLD_M ||
            candidate.endpointProximityM > MINI_HMM_ENDPOINT_CANDIDATE_THRESHOLD_M
        ) {
            return false
        }
        val previousEndpoints = buildList {
            if (hypothesis.startLat != null && hypothesis.startLon != null) add(hypothesis.startLat to hypothesis.startLon)
            if (hypothesis.endLat != null && hypothesis.endLon != null) add(hypothesis.endLat to hypothesis.endLon)
        }
        val currentEndpoints = listOfNotNull(
            candidate.points.firstOrNull()?.let { it.lat to it.lon },
            candidate.points.lastOrNull()?.let { it.lat to it.lon },
        )
        if (previousEndpoints.isEmpty() || currentEndpoints.isEmpty()) {
            return false
        }
        val bestConnection = previousEndpoints.minOf { previous ->
            currentEndpoints.minOf { current ->
                haversineM(previous.first, previous.second, current.first, current.second)
            }
        }
        return bestConnection <= MINI_HMM_ENDPOINT_CONNECTION_THRESHOLD_M
    }

    private fun isBetterCandidate(lhs: WayCandidate, rhs: WayCandidate): Boolean {
        return when {
            lhs.score != rhs.score -> lhs.score < rhs.score
            lhs.distanceM != rhs.distanceM -> lhs.distanceM < rhs.distanceM
            else -> (lhs.wayId ?: "~") < (rhs.wayId ?: "~")
        }
    }

    private fun isBetterDistanceCandidate(lhs: WayCandidate, rhs: WayCandidate): Boolean {
        return when {
            lhs.distanceM != rhs.distanceM -> lhs.distanceM < rhs.distanceM
            lhs.score != rhs.score -> lhs.score < rhs.score
            lhs.endpointProximityM != rhs.endpointProximityM -> lhs.endpointProximityM < rhs.endpointProximityM
            else -> (lhs.wayId ?: "~") < (rhs.wayId ?: "~")
        }
    }

    private fun continuityPriority(continuityClass: ContinuityClass): Int {
        return when (continuityClass) {
            ContinuityClass.PREFERRED_WAY -> 4
            ContinuityClass.SAME_REF -> 3
            ContinuityClass.LINKED_WAY -> 2
            ContinuityClass.RECENT_WAY -> 1
            ContinuityClass.NONE -> 0
        }
    }

    private fun continuityBand(continuityClass: ContinuityClass): Double {
        return when (continuityClass) {
            ContinuityClass.PREFERRED_WAY -> 0.0
            ContinuityClass.SAME_REF -> 1.0
            ContinuityClass.LINKED_WAY -> 2.0
            ContinuityClass.RECENT_WAY -> 3.0
            ContinuityClass.NONE -> 4.0
        }
    }

    private fun traceRankingScore(
        candidate: WayCandidate,
        continuityClass: ContinuityClass,
        maxGeometryScore: Double,
    ): Double {
        return candidateTraceScore(candidate.score, continuityClass.traceName, maxGeometryScore)
    }

    private fun candidateTraceScore(
        geometryScore: Double,
        continuityClass: String,
        maxGeometryScore: Double,
    ): Double {
        val bandWidth = max(maxGeometryScore, geometryScore) + 1.0
        return (candidateTraceContinuityBand(continuityClass) * bandWidth) + geometryScore
    }

    private fun candidateTraceContinuityBand(continuityClass: String): Double {
        return when (continuityClass) {
            "preferredWay" -> 0.0
            "sameRef" -> 1.0
            "linkedWay" -> 2.0
            "recentWay" -> 3.0
            else -> 4.0
        }
    }

    private fun threeWayGateHighwayBucket(highway: String?): String {
        return when (highway?.lowercase()) {
            "primary", "secondary", "residential", "tertiary", "unclassified", "service" -> highway.lowercase()
            else -> "other"
        }
    }

    private fun axisHeadingDeg(candidate: WayCandidate): Double? {
        return candidate.localHeadingDeg ?: candidate.startHeadingDeg ?: candidate.endHeadingDeg
    }

    private fun axisHeadingDeg(
        startLat: Double?,
        startLon: Double?,
        endLat: Double?,
        endLon: Double?,
    ): Double? {
        return computeAxisHeadingDegOrNull(startLat, startLon, endLat, endLon)
    }

    private fun formatMetric(value: Double): String = String.format(Locale.US, "%.1f", value)

    private fun formatProbability(value: Double): String = String.format(Locale.US, "%.3f", value)

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

    private fun queryCityBoundaryCandidates(
        lat: Double,
        lon: Double,
        limitRows: Int = 2048,
    ): List<CityBoundaryCandidate> {
        if (!hasCityBoundaryTable) {
            return emptyList()
        }
        val useRtree = allowCityBoundaryRtreeQueries && hasCityBoundaryRtreeTable
        val fromClause = if (useRtree) {
            "FROM city_boundary_rtree r JOIN city_boundary b ON b.row_id = r.row_id"
        } else {
            "FROM city_boundary b"
        }
        val boundsSource = if (useRtree) "r" else "b"
        val sql = """
            SELECT
              b.row_id, b.admin_level, b.name,
              b.min_lon, b.min_lat, b.max_lon, b.max_lat
            $fromClause
            WHERE
              $boundsSource.min_lon <= ? AND $boundsSource.max_lon >= ?
              AND $boundsSource.min_lat <= ? AND $boundsSource.max_lat >= ?
              AND b.admin_level IN (6, 8)
            LIMIT ?
        """.trimIndent()
        val params = arrayOf(
            lon.toString(),
            lon.toString(),
            lat.toString(),
            lat.toString(),
            limitRows.toString(),
        )
        val out = ArrayList<CityBoundaryCandidate>()
        try {
            db.rawQuery(sql, params).use { cursor ->
                while (cursor.moveToNext()) {
                    out += CityBoundaryCandidate(
                        rowId = cursor.getLong(0),
                        adminLevel = cursor.getInt(1),
                        name = cursor.stringOrNull(2),
                        minLon = cursor.getDouble(3),
                        minLat = cursor.getDouble(4),
                        maxLon = cursor.getDouble(5),
                        maxLat = cursor.getDouble(6),
                    )
                }
            }
        } catch (error: SQLiteException) {
            if (useRtree && isRtreeModuleUnavailable(error)) {
                allowCityBoundaryRtreeQueries = false
                return queryCityBoundaryCandidates(lat = lat, lon = lon, limitRows = limitRows)
            }
            throw error
        }
        return out
    }

    private fun resolveCityContextFromPolygons(
        lat: Double,
        lon: Double,
        hasPlaceTables: Boolean,
        limitRows: Int = 2048,
    ): CityContext {
        val boundaries = queryCityBoundaryCandidates(lat = lat, lon = lon, limitRows = limitRows)
        val containing = mutableListOf<Triple<Int, Double, String>>()
        boundaries.forEach { boundary ->
            val name = boundary.name?.trim().orEmpty()
            if (name.isEmpty()) {
                return@forEach
            }
            if (boundaryContainsPoint(boundaryRowId = boundary.rowId, lon = lon, lat = lat)) {
                val bboxArea = max(boundary.maxLon - boundary.minLon, 0.0) * max(boundary.maxLat - boundary.minLat, 0.0)
                containing += Triple(boundary.adminLevel, bboxArea, name)
            }
        }
        if (containing.isNotEmpty()) {
            val best = containing.sortedWith(compareBy<Triple<Int, Double, String>> { cityBoundaryPriority(it.first) ?: Int.MAX_VALUE }.thenBy { it.second }.thenBy { it.third }).first()
            return CityContext(
                insideCity = true,
                cityName = best.third,
                citySource = "admin_polygon",
                candidateBoundaries = boundaries.size,
                placeCandidates = 0,
            )
        }

        if (hasPlaceTables) {
            val placeCandidates = queryCityPlaceFallbackCandidates(lat = lat, lon = lon)
            selectNearestPlaceFallback(placeCandidates)?.let { best ->
                return CityContext(
                    insideCity = false,
                    cityName = best.third,
                    citySource = "place_fallback",
                    candidateBoundaries = boundaries.size,
                    placeCandidates = placeCandidates.size,
                )
            }
        }

        return CityContext(
            insideCity = false,
            cityName = null,
            citySource = if (hasPlaceTables) "admin_polygons_plus_places" else "admin_polygons",
            candidateBoundaries = boundaries.size,
            placeCandidates = 0,
        )
    }

    private fun queryCityPlaceFallbackCandidates(
        lat: Double,
        lon: Double,
        limitRows: Int = 16,
    ): List<Triple<Int, Double, String>> {
        if (!hasCityPlaceTable) {
            return emptyList()
        }
        val useRtree = allowCityPlaceRtreeQueries && hasCityPlaceRtreeTable
        val placeWindowDeg = 0.3
        val sql = if (useRtree) {
            """
                SELECT p.place, p.name, p.lon, p.lat
                FROM city_place_rtree r
                JOIN city_place p ON p.row_id = r.row_id
                WHERE
                  r.min_lon <= ? AND r.max_lon >= ?
                  AND r.min_lat <= ? AND r.max_lat >= ?
                ORDER BY ((p.lon - ?) * (p.lon - ?) + (p.lat - ?) * (p.lat - ?)) ASC
                LIMIT ?
            """.trimIndent()
        } else {
            """
                SELECT p.place, p.name, p.lon, p.lat
                FROM city_place p
                WHERE
                  p.lon <= ? AND p.lon >= ?
                  AND p.lat <= ? AND p.lat >= ?
                ORDER BY ((p.lon - ?) * (p.lon - ?) + (p.lat - ?) * (p.lat - ?)) ASC
                LIMIT ?
            """.trimIndent()
        }
        val params = arrayOf(
            (lon + placeWindowDeg).toString(),
            (lon - placeWindowDeg).toString(),
            (lat + placeWindowDeg).toString(),
            (lat - placeWindowDeg).toString(),
            lon.toString(),
            lon.toString(),
            lat.toString(),
            lat.toString(),
            limitRows.toString(),
        )
        val out = ArrayList<Triple<Int, Double, String>>()
        try {
            db.rawQuery(sql, params).use { cursor ->
                while (cursor.moveToNext()) {
                    val rank = placeRank(cursor.stringOrNull(0)) ?: continue
                    val name = cursor.stringOrNull(1)?.trim().orEmpty()
                    if (name.isEmpty()) {
                        continue
                    }
                    val placeLon = cursor.getDouble(2)
                    val placeLat = cursor.getDouble(3)
                    val distanceM = haversineM(lat1 = lat, lon1 = lon, lat2 = placeLat, lon2 = placeLon)
                    out += Triple(rank, distanceM, name)
                }
            }
        } catch (error: SQLiteException) {
            if (useRtree && isRtreeModuleUnavailable(error)) {
                allowCityPlaceRtreeQueries = false
                return queryCityPlaceFallbackCandidates(lat = lat, lon = lon, limitRows = limitRows)
            }
            throw error
        }
        return out
    }

    private fun boundaryContainsPoint(
        boundaryRowId: Long,
        lon: Double,
        lat: Double,
    ): Boolean {
        val ringsByOuter = linkedMapOf<Int, MutableList<List<LonLatPoint>>>()
        val sql = """
            SELECT outer_index, is_hole, points_json
            FROM city_ring
            WHERE boundary_row_id = ?
            ORDER BY outer_index, is_hole, ring_index
        """.trimIndent()
        db.rawQuery(sql, arrayOf(boundaryRowId.toString())).use { cursor ->
            while (cursor.moveToNext()) {
                val outerIndex = cursor.getInt(0)
                val isHole = cursor.getInt(1) != 0
                val ring = parseRingPoints(cursor.stringOrNull(2))
                if (ring.size < 4) {
                    continue
                }
                val group = ringsByOuter.getOrPut(outerIndex) { mutableListOf() }
                if (!isHole) {
                    if (group.isEmpty()) {
                        group.add(ring)
                    } else {
                        group[0] = ring
                    }
                } else {
                    if (group.isEmpty()) {
                        group.add(emptyList())
                    }
                    group.add(ring)
                }
            }
        }

        for (group in ringsByOuter.values) {
            val outer = group.firstOrNull().orEmpty()
            if (outer.size < 4 || !pointInRing(lon = lon, lat = lat, ring = outer)) {
                continue
            }
            val inHole = group.drop(1).any { hole -> hole.size >= 4 && pointInRing(lon = lon, lat = lat, ring = hole) }
            if (!inHole) {
                return true
            }
        }
        return false
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
            if (area.boundary == "administrative" && cityBoundaryPriority(adminLevel) != null && insideBbox) {
                containingAdmin.add(Triple(adminLevel ?: return@forEach, areaSize, name))
            }

            val placeRank = placeRank(area.place) ?: return@forEach
            val centerLat = (area.minLat + area.maxLat) / 2.0
            val centerLon = (area.minLon + area.maxLon) / 2.0
            val distanceM = haversineM(lat1 = lat, lon1 = lon, lat2 = centerLat, lon2 = centerLon)
            nearbyPlaces.add(Triple(placeRank, distanceM, name))
            if (insideBbox) {
                containingPlaces.add(Triple(placeRank, distanceM, name))
            }
        }

        if (containingAdmin.isNotEmpty()) {
            val best = containingAdmin.sortedWith(compareBy<Triple<Int, Double, String>> { cityBoundaryPriority(it.first) ?: Int.MAX_VALUE }.thenBy { it.second }.thenBy { it.third }).first()
            return CityContext(
                insideCity = true,
                cityName = best.third,
                citySource = "admin_bbox",
                candidateBoundaries = containingAdmin.size,
                placeCandidates = nearbyPlaces.size,
            )
        }
        selectContainingPlace(containingPlaces)?.let { best ->
            return CityContext(
                insideCity = true,
                cityName = best.third,
                citySource = "place_bbox",
                candidateBoundaries = 0,
                placeCandidates = nearbyPlaces.size,
            )
        }
        selectNearestPlaceFallback(nearbyPlaces)?.let { best ->
            return CityContext(
                insideCity = false,
                cityName = best.third,
                citySource = "place_nearest",
                candidateBoundaries = 0,
                placeCandidates = nearbyPlaces.size,
            )
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
        private val THREE_WAY_GATE_CLASS_NAMES = listOf("current", "lowest_distance", "lowest_endpoint")
        private const val HEADING_MIN_SPEED_KMH = 8.0
        private const val HEADING_WEIGHT_M_PER_DEG = 1.8
        private const val MAX_TRACE_CANDIDATE_COUNT = 16
        private const val CONNECTED_TRANSITION_WARMUP_FIX_COUNT = 3
        private const val MINI_HMM_BEAM_WIDTH = 4
        private const val MINI_HMM_AMBIGUOUS_SCORE_GAP_M = 14.0
        private const val MINI_HMM_HISTORY_DECAY = 0.55
        private const val MINI_HMM_UNRELATED_TRANSITION_PENALTY_M = 18.0
        private const val MINI_HMM_LINKED_WAY_TRANSITION_PENALTY_M = 2.5
        private const val MINI_HMM_SHARED_REF_LINKED_TRANSITION_PENALTY_M = 0.75
        private const val MINI_HMM_SAME_REF_TRANSITION_PENALTY_M = 4.0
        private const val MINI_HMM_RECENT_WAY_TRANSITION_PENALTY_M = 8.0
        private const val MINI_HMM_HIGHWAY_CLASS_TRANSITION_PENALTY_M = 12.0
        private const val MINI_HMM_ENDPOINT_CONNECTION_PENALTY_M = 2.0
        private const val MINI_HMM_ENDPOINT_CONNECTION_THRESHOLD_M = 20.0
        private const val MINI_HMM_ENDPOINT_CANDIDATE_THRESHOLD_M = 24.0
        private const val UNKNOWN_HIGHWAY_PENALTY_M = 30.0
        private const val NEAREST_PLACE_FALLBACK_MAX_DISTANCE_M = 5_000.0
        private const val PRIMARY_PLACE_MAX_RANK = 1
        private const val WALKING_TURN_SWITCH_MAX_SPEED_KMH = 7.0
        private const val WALKING_TURN_SWITCH_PREFERRED_DISTANCE_M = 10.0
        private const val WALKING_TURN_SWITCH_BEST_DISTANCE_M = 5.0
        private const val WALKING_TURN_SWITCH_MIN_GAP_M = 8.0
        private const val WALKING_TURN_SWITCH_ENDPOINT_M = 4.0
        private const val PREFERRED_WAY_SCORE_SLACK_M = 18.0
        private const val PREFERRED_WAY_DISTANCE_MULTIPLIER = 1.9
        private const val PREFERRED_WAY_DISTANCE_FLOOR_M = 85.0
        private const val SAME_REF_BOUNCE_PENALTY_M = 9.0
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
        private const val TRANSITION_HEADING_CURRENT_ALIGNMENT_THRESHOLD_DEG = 18.0
        private const val TRANSITION_HEADING_IMPROVEMENT_MARGIN_DEG = 12.0
        private const val TRANSITION_HEADING_MEANINGFUL_TURN_DEG = 18.0
        private const val TRANSITION_HEADING_SHARP_TURN_DEG = 35.0
        private const val TRANSITION_HEADING_VERY_SHARP_TURN_DEG = 55.0
        private const val TRANSITION_SERVICE_ROAD_SPEED_KMH = 24.0
        private const val TRANSITION_HEADING_BONUS_M = 4.0
        private const val TRANSITION_SHARP_TURN_PENALTY_M = 10.0
        private const val TRANSITION_VERY_SHARP_TURN_PENALTY_M = 16.0
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

        private fun cityBoundaryPriority(adminLevel: Int?): Int? {
            return when (adminLevel) {
                8 -> 0
                6 -> 1
                else -> null
            }
        }

        private fun primaryPlaceCandidates(
            candidates: List<Triple<Int, Double, String>>,
        ): List<Triple<Int, Double, String>> = candidates.filter { it.first <= PRIMARY_PLACE_MAX_RANK }

        private fun selectContainingPlace(
            candidates: List<Triple<Int, Double, String>>,
        ): Triple<Int, Double, String>? {
            val primary = primaryPlaceCandidates(candidates)
            val effective = if (primary.isEmpty()) candidates else primary
            return effective.sortedWith(
                compareBy<Triple<Int, Double, String>> { it.first }.thenBy { it.second }.thenBy { it.third },
            ).firstOrNull()
        }

        private fun selectNearestPlaceFallback(
            candidates: List<Triple<Int, Double, String>>,
        ): Triple<Int, Double, String>? {
            val withinThreshold = candidates.filter { it.second <= NEAREST_PLACE_FALLBACK_MAX_DISTANCE_M }
            if (withinThreshold.isEmpty()) {
                return null
            }
            val primary = primaryPlaceCandidates(withinThreshold)
            return if (primary.isNotEmpty()) {
                primary.sortedWith(
                    compareBy<Triple<Int, Double, String>> { it.second }.thenBy { it.first }.thenBy { it.third },
                ).firstOrNull()
            } else {
                withinThreshold.sortedWith(
                    compareBy<Triple<Int, Double, String>> { it.first }.thenBy { it.second }.thenBy { it.third },
                ).firstOrNull()
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
                    bestHeading = computeAxisHeadingDeg(start.lat, start.lon, end.lat, end.lon)
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

        internal fun computeAxisHeadingDeg(
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

        internal fun computeAxisHeadingDegOrNull(
            lat1: Double?,
            lon1: Double?,
            lat2: Double?,
            lon2: Double?,
        ): Double? {
            if (lat1 == null || lon1 == null || lat2 == null || lon2 == null) {
                return null
            }
            return computeAxisHeadingDeg(lat1, lon1, lat2, lon2)
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
            return computeAxisHeadingDeg(start.lat, start.lon, end.lat, end.lon)
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

private data class CityBoundaryCandidate(
    val rowId: Long,
    val adminLevel: Int,
    val name: String?,
    val minLon: Double,
    val minLat: Double,
    val maxLon: Double,
    val maxLat: Double,
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
    val usedMiniHMM: Boolean = false,
    val miniHMMCandidateCount: Int = 0,
    val matchHypotheses: List<WayMatchHypothesis> = emptyList(),
    val selectionTrace: List<MatchSelectionTrace> = emptyList(),
)

private data class MiniHMMSelection(
    val selectedCandidate: WayCandidate? = null,
    val hypotheses: List<WayMatchHypothesis> = emptyList(),
    val used: Boolean = false,
    val candidateCount: Int = 0,
)

private data class TraceRankedCandidate(
    val candidate: WayCandidate,
    val continuity: ContinuityClass,
    val portalEligible: Boolean,
    val corridorState: CandidateCorridorState?,
    val tunnelSelectable: Boolean,
    val corridorSelectable: Boolean,
    val traceScore: Double,
    val traceRank: Int,
)

private data class ThreeWayGateSelection(
    val candidate: WayCandidate,
    val className: String,
    val probabilitySummary: String,
    val distanceWayId: String?,
    val endpointWayId: String?,
)

private data class TransitionHeadingEvidence(
    val currentMismatchDeg: Double,
    val candidateMismatchDeg: Double,
    val turnAngleDeg: Double,
    val speedKmh: Double,
    val nearEndpoint: Boolean,
    val serviceLike: Boolean,
) {
    val currentAligned: Boolean
        get() = currentMismatchDeg <= 18.0

    val candidateClearlyBetterAligned: Boolean
        get() = candidateMismatchDeg + 12.0 <= currentMismatchDeg

    val meaningfulTurn: Boolean
        get() = turnAngleDeg >= 18.0

    val sharpTurn: Boolean
        get() = turnAngleDeg >= 35.0

    val verySharpTurn: Boolean
        get() = turnAngleDeg >= 55.0
}

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
