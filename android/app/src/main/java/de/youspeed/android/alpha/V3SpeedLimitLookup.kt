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
    val cityPlaceName: String?,
    val cityDistrictName: String?,
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
    countryCode: String? = null,
    private val matchingModel: LookupMatchingModel = LookupMatchingModel.CORRIDOR_HMM,
) : Closeable {
    private val countryCode = normalizedCountryCode(countryCode) ?: inferCountryCodeFromDbPath(dbPath)
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
    private val corridorPairContext: CorridorPairContext by lazy { loadCorridorPairContext() }
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

    private val usesThreeWayGate: Boolean
        get() = matchingModel != LookupMatchingModel.CORRIDOR_HMM_NO_THREE_WAY_GATE

    private val usesSameRefBounceGate: Boolean
        get() = matchingModel != LookupMatchingModel.CORRIDOR_HMM_NO_SAME_REF_BOUNCE_GATE

    private val usesAntiAbaHysteresis: Boolean
        get() = matchingModel == LookupMatchingModel.CORRIDOR_HMM_ANTI_ABA_HYSTERESIS

    private val usesRawMiniHmmSelection: Boolean
        get() = matchingModel == LookupMatchingModel.CORRIDOR_HMM_RAW_MINI_HMM

    private val usesCorridorMatcher: Boolean
        get() = when (matchingModel) {
            LookupMatchingModel.CONNECTED_BASELINE,
            LookupMatchingModel.SIMPLE_SPEED_REF_HEURISTIC,
            LookupMatchingModel.SIMPLE_SPEED_REF_STREET_NAME_GUARD_HEURISTIC,
            LookupMatchingModel.SIMPLE_SPEED_REF_CONNECTED_HEURISTIC -> false
            LookupMatchingModel.CORRIDOR_HMM_RAW_MINI_HMM,
            LookupMatchingModel.CORRIDOR_HMM,
            LookupMatchingModel.CORRIDOR_HMM_NO_THREE_WAY_GATE,
            LookupMatchingModel.CORRIDOR_HMM_NO_SAME_REF_BOUNCE_GATE,
            LookupMatchingModel.CORRIDOR_HMM_ANTI_ABA_HYSTERESIS -> true
        }

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
                cityPlaceName = null,
                cityDistrictName = null,
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
        val polygonCityContext = if (hasCityBoundaryTable && hasCityRingTable) {
            resolveCityContextFromPolygons(
                lat = lat,
                lon = lon,
                hasPlaceTables = hasCityPlaceTable,
            )
        } else {
            null
        }
        val areaCityContext = if (hasAreasTable) {
            resolveCityContextFromAreas(lat = lat, lon = lon, areas = areaCandidates)
        } else {
            null
        }
        val cityContext = when {
            polygonCityContext != null && areaCityContext != null ->
                preferredCityContext(primary = polygonCityContext, fallback = areaCityContext)
            polygonCityContext != null -> polygonCityContext
            areaCityContext != null -> areaCityContext
            else -> CityContext(
                insideCity = false,
                cityName = null,
                cityPlaceName = null,
                cityDistrictName = null,
                citySource = "unavailable",
                candidateBoundaries = 0,
                placeCandidates = 0,
            )
        }
        val wayLinks = loadWayLinksContext(normalizedMatchContext, candidates)
        val corridorProgress = loadCorridorProgressContext(candidates)
        val corridorPairs = corridorPairContext
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
            corridorPairs = corridorPairs,
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
        val resolvedInsideCityDecision = applyGermanLowSpeedInCityHeuristic(
            insideCityDecision = insideCityDecision,
            speedKmh = effectiveSpeed,
        )

        return SpeedLookupResult(
            wayId = best?.wayId,
            highway = best?.highway,
            streetName = best?.streetName,
            streetBaseName = best?.streetBaseName,
            streetRef = best?.streetRef,
            speedLimitKmh = effectiveSpeed,
            isUnlimitedSpeedLimit = best?.isUnlimitedSpeedLimit == true,
            cityName = cityContext.cityName,
            cityPlaceName = cityContext.cityPlaceName,
            cityDistrictName = cityContext.cityDistrictName,
            insideCity = resolvedInsideCityDecision.first,
            citySource = resolvedInsideCityDecision.second,
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

    private fun applyGermanLowSpeedInCityHeuristic(
        insideCityDecision: Pair<Boolean?, String?>,
        speedKmh: Int?,
    ): Pair<Boolean?, String?> {
        if (insideCityDecision.first == true) {
            return insideCityDecision
        }
        if (!germanLowSpeedLimitImpliesInsideCity(countryCode = countryCode, speedKmh = speedKmh)) {
            return insideCityDecision
        }
        return true to "de_speed_limit_lt_50"
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
        corridorPairs: CorridorPairContext,
    ): CandidateSelection {
        if (candidates.isEmpty()) {
            return CandidateSelection()
        }
        val sortedCandidates = candidates.sortedWith(candidateComparator)
        val activeCorridorAnchorState = corridorAnchor(matchContext)?.state ?: CorridorState.SURFACE
        val activeCorridorLabel = matchContext.activeCorridorState?.let {
            "${it.kind}#${it.corridorId}"
        } ?: activeCorridorAnchorState.wireName
        val selectionTrace = mutableListOf(
            MatchSelectionTrace(
                step = "context",
                detail = buildString {
                    append("preferred=").append(matchContext.preferredWayId ?: "nil")
                    append(" corridor=").append(activeCorridorLabel)
                    append(" tunnel_mode=").append(matchContext.isInTunnelMode)
                    append(" gps_loss=").append(matchContext.hadRecentGpsSignalLoss)
                    append(" tunnel_approach=").append(matchContext.tunnelApproachFixCount)
                    append(" corridor_approach=").append(matchContext.approachCorridorFixCount)
                    append(" match_streak=").append(matchContext.matchedFixCount)
                    append(" accuracy_m=").append(formatMetric(accuracyBufferM))
                },
            ),
        )
        val selectableCandidates = if (!usesCorridorMatcher) {
            sortedCandidates
        } else {
            run {
                val corridorBaseCandidates = sortedCandidates.filter {
                    isCorridorCandidateSelectable(
                        candidate = it,
                        matchContext = matchContext,
                        wayLinks = wayLinks,
                        progressContext = corridorProgress,
                        pairContext = corridorPairs,
                        accuracyBufferM = accuracyBufferM,
                        horizontalAccuracyM = horizontalAccuracyM,
                        gpsSignalBars = gpsSignalBars,
                    )
                }
                val corridorSelectableCandidates = suppressAmbiguousSurfaceToTunnelEntries(
                    candidates = corridorBaseCandidates,
                    matchContext = matchContext,
                    wayLinks = wayLinks,
                    progressContext = corridorProgress,
                    accuracyBufferM = accuracyBufferM,
                    horizontalAccuracyM = horizontalAccuracyM,
                    gpsSignalBars = gpsSignalBars,
                )
                when {
                    corridorSelectableCandidates.isNotEmpty() -> {
                        if (corridorSelectableCandidates.size != sortedCandidates.size) {
                            val filteredCount = sortedCandidates.size - corridorSelectableCandidates.size
                            selectionTrace += MatchSelectionTrace(
                                step = "corridor_gate",
                                detail = "filtered $filteredCount candidates incompatible with corridor state $activeCorridorLabel",
                            )
                        }
                        corridorSelectableCandidates
                    }

                    shouldFallbackWhenCorridorGateEmptiesCandidates(matchContext) -> {
                        selectionTrace += MatchSelectionTrace(
                            step = "corridor_gate",
                            detail = "kept full candidate set after empty corridor gate during recent gps loss",
                        )
                        sortedCandidates
                    }

                    else -> {
                        selectionTrace += MatchSelectionTrace(
                            step = "corridor_gate",
                            detail = "rejected all candidates for corridor state $activeCorridorLabel",
                        )
                        corridorSelectableCandidates
                    }
                }
            }
        }
        val nearestAlternativeDistanceCandidate = selectableCandidates
            .filter { normalizedWayId(it.wayId) != normalizedWayId(matchContext.preferredWayId) }
            .minWithOrNull { lhs, rhs ->
                when {
                    isBetterDistanceCandidate(lhs, rhs) -> -1
                    isBetterDistanceCandidate(rhs, lhs) -> 1
                    else -> 0
                }
            }
        val graphSelectableCandidates = if (shouldApplyConnectedTransitionGate(matchContext, wayLinks)) {
            val connectedCandidates = selectableCandidates.filter {
                isConnectedTransitionCandidate(it, matchContext, wayLinks)
            }
            if (connectedCandidates.isNotEmpty()) {
                if (connectedCandidates.size != selectableCandidates.size) {
                    selectionTrace += MatchSelectionTrace(
                        step = "road_graph_gate",
                        detail = "filtered ${selectableCandidates.size - connectedCandidates.size} disconnected candidates after warmup",
                    )
                }
                connectedCandidates
            } else {
                selectableCandidates
            }
        } else {
            selectableCandidates
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
        if (!usesCorridorMatcher) {
            return when (matchingModel) {
                LookupMatchingModel.CONNECTED_BASELINE -> {
                    val baselineSelection = selectConnectedBaselineCandidate(
                        candidates = graphSelectableCandidates,
                        matchContext = matchContext,
                        observedHeadingDeg = observedHeadingDeg,
                        speedKmh = speedKmh,
                        wayLinks = wayLinks,
                        accuracyBufferM = accuracyBufferM,
                    )
                    selectionTrace += baselineSelection.selectionTrace
                    buildNonCorridorCandidateSelection(
                        finalSelected = baselineSelection.selected,
                        traceRankedCandidates = baselineSelection.traceRankedCandidates,
                        selectionTrace = selectionTrace,
                        nearbyTunnelCandidateWayIds = nearbyTunnelCandidateWayIds,
                        nearbyTunnelCandidateRefs = nearbyTunnelCandidateRefs,
                        portalEligibleTunnelWayIds = portalEligibleTunnelWayIds,
                        portalEligibleTunnelRefs = portalEligibleTunnelRefs,
                    )
                }

                LookupMatchingModel.SIMPLE_SPEED_REF_HEURISTIC,
                LookupMatchingModel.SIMPLE_SPEED_REF_STREET_NAME_GUARD_HEURISTIC,
                LookupMatchingModel.SIMPLE_SPEED_REF_CONNECTED_HEURISTIC -> {
                    val simpleCandidates = if (matchingModel == LookupMatchingModel.SIMPLE_SPEED_REF_CONNECTED_HEURISTIC) {
                        graphSelectableCandidates
                    } else {
                        sortedCandidates
                    }
                    val simpleSelection = selectSimpleSpeedRefHeuristicCandidate(
                        candidates = simpleCandidates,
                        matchContext = matchContext,
                        speedKmh = speedKmh,
                        horizontalAccuracyM = horizontalAccuracyM,
                        urbanSameRefReleaseEnabled = matchingModel == LookupMatchingModel.SIMPLE_SPEED_REF_STREET_NAME_GUARD_HEURISTIC,
                        useStreetNameFallbackContinuity = false,
                        useGuardedStreetNameFallbackContinuity = matchingModel == LookupMatchingModel.SIMPLE_SPEED_REF_STREET_NAME_GUARD_HEURISTIC,
                        wayLinks = wayLinks,
                    )
                    selectionTrace += simpleSelection.selectionTrace
                    buildNonCorridorCandidateSelection(
                        finalSelected = simpleSelection.selected,
                        traceRankedCandidates = simpleSelection.traceRankedCandidates,
                        selectionTrace = selectionTrace,
                        nearbyTunnelCandidateWayIds = nearbyTunnelCandidateWayIds,
                        nearbyTunnelCandidateRefs = nearbyTunnelCandidateRefs,
                        portalEligibleTunnelWayIds = portalEligibleTunnelWayIds,
                        portalEligibleTunnelRefs = portalEligibleTunnelRefs,
                        modelTraceName = when (matchingModel) {
                            LookupMatchingModel.SIMPLE_SPEED_REF_CONNECTED_HEURISTIC -> "simple_speed_ref_connected"
                            LookupMatchingModel.SIMPLE_SPEED_REF_STREET_NAME_GUARD_HEURISTIC -> "simple_speed_ref_street_name_guard"
                            else -> "simple_speed_ref"
                        },
                    )
                }

                else -> CandidateSelection()
            }
        }
        val bestGeometric = graphSelectableCandidates.firstOrNull()

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
        var usedWalkingTurnSwitch = false

        var heuristicSelected: WayCandidate? = null
        var lockHeuristicSelection = false
        if (bestGeometric != null &&
            preferredCandidate != null &&
            usesSameRefBounceGate &&
            shouldSuppressImmediateSameRefBounce(bestGeometric, preferredCandidate, matchContext, wayLinks, accuracyBufferM)
        ) {
            heuristicSelected = preferredCandidate
        } else if (bestGeometric != null &&
            preferredCandidate != null &&
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
        } else if (
            preferredCandidate != null &&
            nearestAlternativeDistanceCandidate != null &&
            shouldForceGeometricCandidateAtWalkingSpeed(preferredCandidate, nearestAlternativeDistanceCandidate, speedKmh, accuracyBufferM, matchContext)
        ) {
            heuristicSelected = nearestAlternativeDistanceCandidate
            lockHeuristicSelection = true
            usedWalkingTurnSwitch = true
            selectionTrace += MatchSelectionTrace(
                step = "low_speed_rule",
                detail = "selected geometric turn ${nearestAlternativeDistanceCandidate.wayId ?: "nil"} over preferred ${preferredCandidate.wayId ?: "nil"} at walking speed",
            )
        } else if (
            bestGeometric != null &&
            preferredCandidate != null &&
            shouldKeepContinuityCandidate(preferredCandidate, bestGeometric, radiusM, accuracyBufferM, PREFERRED_WAY_SCORE_SLACK_M, PREFERRED_WAY_DISTANCE_MULTIPLIER, PREFERRED_WAY_DISTANCE_FLOOR_M)
        ) {
            heuristicSelected = preferredCandidate
        } else if (
            bestGeometric != null &&
            sameRefCandidate != null &&
            shouldKeepContinuityCandidate(sameRefCandidate, bestGeometric, radiusM, accuracyBufferM, SAME_REF_SCORE_SLACK_M, SAME_REF_DISTANCE_MULTIPLIER, SAME_REF_DISTANCE_FLOOR_M)
        ) {
            heuristicSelected = sameRefCandidate
        } else if (
            bestGeometric != null &&
            linkedWayCandidate != null &&
            shouldKeepContinuityCandidate(linkedWayCandidate, bestGeometric, radiusM, accuracyBufferM, LINKED_WAY_SCORE_SLACK_M, LINKED_WAY_DISTANCE_MULTIPLIER, LINKED_WAY_DISTANCE_FLOOR_M)
        ) {
            heuristicSelected = linkedWayCandidate
        } else if (
            bestGeometric != null &&
            recentWayCandidate != null &&
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
                horizontalAccuracyM = horizontalAccuracyM,
                gpsSignalBars = gpsSignalBars,
                corridorProgress = corridorProgress,
                corridorPairs = corridorPairs,
            )
        }
        val traceRankedCandidates = buildTraceRankedCandidates(
            candidates = sortedCandidates,
            matchContext = matchContext,
            wayLinks = wayLinks,
            corridorProgress = corridorProgress,
            corridorPairs = corridorPairs,
            accuracyBufferM = accuracyBufferM,
            horizontalAccuracyM = horizontalAccuracyM,
            gpsSignalBars = gpsSignalBars,
        )
        val traceTop2Margin = top2TraceMargin(traceRankedCandidates)
        val signalEvidence = signalQualityEvidence(
            matchContext = matchContext,
            horizontalAccuracyM = horizontalAccuracyM,
            gpsSignalBars = gpsSignalBars,
        )
        val usedMiniHMM = !lockHeuristicSelection && miniHMMSelection.selectedCandidate != null
        val baselineSelected = when {
            lockHeuristicSelection -> heuristicSelected
            miniHMMSelection.selectedCorridorState != null &&
                miniHMMSelection.selectedCandidate != null &&
                candidateCorridorState(
                    candidate = miniHMMSelection.selectedCandidate,
                    matchContext = matchContext,
                    wayLinks = wayLinks,
                    corridorProgress = corridorProgress,
                )?.let { candidateCorridorState ->
                    shouldPromoteMiniHMMCorridorSelection(
                        state = miniHMMSelection.selectedCorridorState,
                        candidate = miniHMMSelection.selectedCandidate,
                        candidateCorridorState = candidateCorridorState,
                        heuristicCandidate = heuristicSelected,
                        matchContext = matchContext,
                        signalEvidence = signalEvidence,
                    )
                } == true -> miniHMMSelection.selectedCandidate

            miniHMMSelection.selectedCorridorState != null &&
                miniHMMSelection.selectedCandidate != null &&
                heuristicSelected != null &&
                shouldKeepSurfaceHeuristicOverUncommittedTunnelCandidate(
                    state = miniHMMSelection.selectedCorridorState,
                    tunnelCandidate = miniHMMSelection.selectedCandidate,
                    heuristicCandidate = heuristicSelected,
                ) -> heuristicSelected

            heuristicSelected != null && miniHMMSelection.selectedCandidate != null -> {
                val heuristicContinuity = continuityClass(heuristicSelected, matchContext, wayLinks)
                val hmmContinuity = continuityClass(miniHMMSelection.selectedCandidate, matchContext, wayLinks)
                if (continuityPriority(heuristicContinuity) > continuityPriority(hmmContinuity)) {
                    heuristicSelected
                } else {
                    miniHMMSelection.selectedCandidate
                }
            }

            miniHMMSelection.selectedCandidate != null -> miniHMMSelection.selectedCandidate
            else -> heuristicSelected
        }
        if (usesRawMiniHmmSelection) {
            val finalSelected = miniHMMSelection.selectedCandidate ?: heuristicSelected
            val finalActiveCorridorState = finalSelected?.let { candidate ->
                val corridorState = candidateCorridorState(
                    candidate = candidate,
                    matchContext = matchContext,
                    wayLinks = wayLinks,
                    corridorProgress = corridorProgress,
                ) ?: return@let null
                if (sameCorridorState(matchContext.activeCorridorState, corridorState.snapshot) ||
                    shouldTriggerActiveCorridorMode(corridorState, matchContext)
                ) {
                    corridorState.snapshot
                } else {
                    null
                }
            }
            val selectedWayId = normalizedWayId(finalSelected?.wayId)
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
            finalSelected?.let {
                selectionTrace += MatchSelectionTrace(
                    step = "final",
                    detail = "selected ${it.wayId ?: "nil"} tunnel=${isTruthyOsmTag(it.tunnel)} corridor=${finalActiveCorridorState?.let { state -> "${state.kind}#${state.corridorId}" } ?: "none"} model=raw_mini_hmm",
                )
            }
            return CandidateSelection(
                selected = finalSelected,
                candidateTraces = candidateTraces,
                nearbyTunnelCandidateWayIds = nearbyTunnelCandidateWayIds,
                nearbyTunnelCandidateRefs = nearbyTunnelCandidateRefs,
                portalEligibleTunnelWayIds = portalEligibleTunnelWayIds,
                portalEligibleTunnelRefs = portalEligibleTunnelRefs,
                activeCorridorState = finalActiveCorridorState,
                approachCorridorStateCandidate = null,
                usedWalkingTurnSwitch = usedWalkingTurnSwitch,
                usedMiniHMM = usedMiniHMM,
                miniHMMCandidateCount = miniHMMSelection.candidateCount,
                matchHypotheses = miniHMMSelection.hypotheses,
                selectionTrace = selectionTrace,
            )
        }

        val shouldApplyThreeWayGate = usesThreeWayGate &&
            !lockHeuristicSelection &&
            (miniHMMSelection.selectedCorridorState == null || miniHMMSelection.selectedCorridorState == CorridorSequenceState.SURFACE) &&
            shouldUseThreeWayGate(baselineSelected, matchContext)
        val threeWayGateSelection = if (shouldApplyThreeWayGate) {
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
                usesSameRefBounceGate &&
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
                detail = "selected ${it.wayId ?: "nil"} state=${miniHMMSelection.selectedCorridorState?.wireName ?: "surface"} beam=${miniHMMSelection.candidateCount}",
            )
        }

        val tunnelContinuityCandidate = preferredCandidate?.takeIf { isTruthyOsmTag(it.tunnel) }
            ?: sameRefCandidate?.takeIf { isTruthyOsmTag(it.tunnel) }
            ?: graphSelectableCandidates.firstOrNull { isTruthyOsmTag(it.tunnel) }
        val activeCorridorLockedCandidate = graphSelectableCandidates.firstOrNull { candidate ->
            val activeCorridorState = matchContext.activeCorridorState ?: return@firstOrNull false
            val corridorState = candidateCorridorState(candidate, matchContext, wayLinks, corridorProgress) ?: return@firstOrNull false
            sameCorridorState(activeCorridorState, corridorState.snapshot)
        }
        val triggeredCorridorEntryCandidate = graphSelectableCandidates.firstOrNull { candidate ->
            val corridorState = candidateCorridorState(candidate, matchContext, wayLinks, corridorProgress) ?: return@firstOrNull false
            shouldTriggerActiveCorridorMode(corridorState, matchContext)
        }
        val preferredHoldCandidate = preferredCandidate
            ?: baselineSelected?.takeIf { normalizedWayId(it.wayId) == matchContext.preferredWayId }
            ?: selectedAfterThreeWay?.takeIf { normalizedWayId(it.wayId) == matchContext.preferredWayId }
            ?: graphSelectableCandidates.firstOrNull { normalizedWayId(it.wayId) == matchContext.preferredWayId }
        var finalSelected: WayCandidate?
        var deferredActiveCorridorState: CorridorMatchState? = null
        if (selectedAfterThreeWay != null &&
            matchContext.activeCorridorState != null &&
            !sameCorridorState(
                matchContext.activeCorridorState,
                candidateCorridorState(
                    candidate = selectedAfterThreeWay,
                    matchContext = matchContext,
                    wayLinks = wayLinks,
                    corridorProgress = corridorProgress,
                )?.snapshot,
            ) &&
            activeCorridorLockedCandidate != null &&
            !isActiveCorridorEntryConnectorCandidate(selectedAfterThreeWay, matchContext, wayLinks) &&
            !isActiveCorridorExitCandidate(selectedAfterThreeWay, matchContext, wayLinks)
        ) {
            finalSelected = activeCorridorLockedCandidate
            selectionTrace += MatchSelectionTrace(
                step = "corridor_mode_lock",
                detail = "kept corridor ${matchContext.activeCorridorState.kind}#${matchContext.activeCorridorState.corridorId} candidate ${activeCorridorLockedCandidate.wayId ?: "nil"} over ${selectedAfterThreeWay.wayId ?: "nil"} until exit zone",
            )
        } else if (
            matchContext.activeCorridorState == null &&
            selectedAfterThreeWay != null &&
            selectedAfterThreeWay.highway.equals("motorway_link", ignoreCase = true) &&
            triggeredCorridorEntryCandidate != null
        ) {
            val corridorState = candidateCorridorState(
                candidate = triggeredCorridorEntryCandidate,
                matchContext = matchContext,
                wayLinks = wayLinks,
                corridorProgress = corridorProgress,
            )
            if (corridorState != null && corridorState.snapshot.kind == "motorway") {
                val entryProgressM = corridorApproachProgressM(corridorState, matchContext)
                val entryProgressNodes = corridorApproachProgressNodes(corridorState, matchContext)
                finalSelected = selectedAfterThreeWay
                deferredActiveCorridorState = corridorState.snapshot
                selectionTrace += MatchSelectionTrace(
                    step = "corridor_entry_arm",
                    detail = "armed motorway mode via ${triggeredCorridorEntryCandidate.wayId ?: "nil"} after ${matchContext.approachCorridorFixCount} entry-zone fixes, ${formatMetric(entryProgressM)} m and $entryProgressNodes corridor nodes while keeping entry connector ${selectedAfterThreeWay.wayId ?: "nil"}",
                )
            } else {
                finalSelected = selectedAfterThreeWay
            }
        } else if (
            matchContext.activeCorridorState == null &&
            selectedAfterThreeWay != null &&
            triggeredCorridorEntryCandidate != null &&
            normalizedWayId(selectedAfterThreeWay.wayId) != normalizedWayId(triggeredCorridorEntryCandidate.wayId)
        ) {
            val corridorState = candidateCorridorState(
                candidate = triggeredCorridorEntryCandidate,
                matchContext = matchContext,
                wayLinks = wayLinks,
                corridorProgress = corridorProgress,
            )
            val entryProgressM = corridorState?.let { corridorApproachProgressM(it, matchContext) } ?: 0.0
            val entryProgressNodes = corridorState?.let { corridorApproachProgressNodes(it, matchContext) } ?: 0
            finalSelected = triggeredCorridorEntryCandidate
            selectionTrace += MatchSelectionTrace(
                step = "corridor_entry_gate",
                detail = "activated ${corridorState?.snapshot?.kind ?: "corridor"} mode via ${triggeredCorridorEntryCandidate.wayId ?: "nil"} after ${matchContext.approachCorridorFixCount} entry-zone fixes, ${formatMetric(entryProgressM)} m and $entryProgressNodes corridor nodes",
            )
        } else if (
            !matchContext.isInTunnelMode &&
            selectedAfterThreeWay != null &&
            !isTruthyOsmTag(selectedAfterThreeWay.tunnel) &&
            tunnelContinuityCandidate != null &&
            shouldPromoteTunnelEntry(
                tunnelCandidate = tunnelContinuityCandidate,
                surfaceCandidate = selectedAfterThreeWay,
                matchContext = matchContext,
                wayLinks = wayLinks,
                corridorProgress = corridorProgress,
                horizontalAccuracyM = horizontalAccuracyM,
                gpsSignalBars = gpsSignalBars,
                accuracyBufferM = accuracyBufferM,
            )
        ) {
            finalSelected = tunnelContinuityCandidate
            selectionTrace += MatchSelectionTrace(
                step = "tunnel_entry_gate",
                detail = "promoted tunnel ${tunnelContinuityCandidate.wayId ?: "nil"} over surface ${selectedAfterThreeWay.wayId ?: "nil"} after repeated portal exposure and degraded signal quality",
            )
        } else if (
            matchContext.isInTunnelMode &&
            selectedAfterThreeWay != null &&
            !isTruthyOsmTag(selectedAfterThreeWay.tunnel) &&
            tunnelContinuityCandidate != null &&
            shouldKeepTunnelContinuity(
                tunnelCandidate = tunnelContinuityCandidate,
                surfaceCandidate = selectedAfterThreeWay,
                matchContext = matchContext,
                wayLinks = wayLinks,
                corridorProgress = corridorProgress,
                pairContext = corridorPairs,
                accuracyBufferM = accuracyBufferM,
                horizontalAccuracyM = horizontalAccuracyM,
                gpsSignalBars = gpsSignalBars,
            )
        ) {
            finalSelected = tunnelContinuityCandidate
            selectionTrace += MatchSelectionTrace(
                step = "tunnel_exit_gate",
                detail = "kept tunnel ${tunnelContinuityCandidate.wayId ?: "nil"} and rejected mid-segment surface exit ${selectedAfterThreeWay.wayId ?: "nil"}",
            )
        } else {
            finalSelected = selectedAfterThreeWay
        }
        if (
            usesAntiAbaHysteresis &&
            finalSelected != null &&
            preferredHoldCandidate != null &&
            shouldApplyAntiAbaHysteresis(
                candidate = finalSelected,
                holdCandidate = preferredHoldCandidate,
                matchContext = matchContext,
                wayLinks = wayLinks,
                corridorProgress = corridorProgress,
                accuracyBufferM = accuracyBufferM,
            )
        ) {
            selectionTrace += MatchSelectionTrace(
                step = "anti_aba_hysteresis",
                detail = "kept ${preferredHoldCandidate.wayId ?: "nil"} over ${finalSelected.wayId ?: "nil"} to avoid immediate A-B-A bounce",
            )
            finalSelected = preferredHoldCandidate
            deferredActiveCorridorState = null
        }
        val finalActiveCorridorState = finalSelected?.let { candidate ->
            val corridorState = candidateCorridorState(
                candidate = candidate,
                matchContext = matchContext,
                wayLinks = wayLinks,
                corridorProgress = corridorProgress,
            ) ?: return@let null
            if (sameCorridorState(matchContext.activeCorridorState, corridorState.snapshot) ||
                shouldTriggerActiveCorridorMode(corridorState, matchContext)
            ) {
                corridorState.snapshot
            } else {
                null
            }
        } ?: deferredActiveCorridorState
        val approachCorridorStateCandidate = sortedCandidates.asSequence()
            .mapNotNull { candidateCorridorState(it, matchContext, wayLinks, corridorProgress) }
            .filter { it.entryZone && (it.snapshot.kind == "tunnel" || it.snapshot.kind == "motorway") }
            .sortedWith(compareBy<CandidateCorridorState> { it.snapshot.depthM }.thenBy { it.snapshot.corridorId })
            .firstOrNull()
            ?.snapshot
        val selectedWayId = normalizedWayId(finalSelected?.wayId)
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
        finalSelected?.let {
            selectionTrace += MatchSelectionTrace(
                step = "final",
                detail = "selected ${it.wayId ?: "nil"} tunnel=${isTruthyOsmTag(it.tunnel)} corridor=${finalActiveCorridorState?.let { state -> "${state.kind}#${state.corridorId}" } ?: "none"}",
            )
        }

        return CandidateSelection(
            selected = finalSelected,
            candidateTraces = candidateTraces,
            nearbyTunnelCandidateWayIds = nearbyTunnelCandidateWayIds,
            nearbyTunnelCandidateRefs = nearbyTunnelCandidateRefs,
            portalEligibleTunnelWayIds = portalEligibleTunnelWayIds,
            portalEligibleTunnelRefs = portalEligibleTunnelRefs,
            activeCorridorState = finalActiveCorridorState,
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

    private fun corridorPairKey(
        kind: String,
        corridorId: Int,
        sideNodeKey: String,
    ): String {
        return "$kind#$corridorId#$sideNodeKey"
    }

    private fun loadCorridorPairContext(): CorridorPairContext {
        if (!tableExists("corridor_pairs")) {
            return CorridorPairContext(available = false)
        }
        val byMainKey = linkedMapOf<String, MutableList<CorridorPairRelation>>()
        val byPairedKey = linkedMapOf<String, MutableList<CorridorPairRelation>>()
        db.rawQuery(
            """
            SELECT corridor_kind, corridor_id, side_node_key, paired_kind, paired_corridor_id
            FROM corridor_pairs
            """.trimIndent(),
            emptyArray(),
        ).use { cursor ->
            while (cursor.moveToNext()) {
                val corridorKind = cursor.stringOrNull(0) ?: continue
                val sideNodeKey = cursor.stringOrNull(2) ?: continue
                val pairedKind = cursor.stringOrNull(3) ?: continue
                if (corridorKind.isEmpty() || sideNodeKey.isEmpty() || pairedKind.isEmpty()) {
                    continue
                }
                val relation = CorridorPairRelation(
                    corridorKind = corridorKind,
                    corridorId = cursor.getInt(1),
                    sideNodeKey = sideNodeKey,
                    pairedKind = pairedKind,
                    pairedCorridorId = cursor.getInt(4),
                )
                val mainKey = corridorPairKey(relation.corridorKind, relation.corridorId, relation.sideNodeKey)
                val pairedKey = corridorPairKey(relation.pairedKind, relation.pairedCorridorId, relation.sideNodeKey)
                byMainKey.getOrPut(mainKey) { mutableListOf() } += relation
                byPairedKey.getOrPut(pairedKey) { mutableListOf() } += relation
            }
        }
        return CorridorPairContext(
            available = true,
            byMainKey = byMainKey.mapValues { it.value.toList() },
            byPairedKey = byPairedKey.mapValues { it.value.toList() },
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
            (candidateRefTokens.any { token -> token in matchContext.recentStreetRefs })
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
        anchors += matchContext.recentHypotheses.mapTo(linkedSetOf()) { it.wayId }
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
        if (usesSameRefBounceGate &&
            shouldSuppressImmediateSameRefBounce(alternativeCandidate, preferredCandidate, matchContext, wayLinks, accuracyBufferM)
        ) {
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
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
        corridorProgress: CorridorProgressContext,
        corridorPairs: CorridorPairContext,
    ): MiniHMMSelection {
        if (!shouldUseMiniHMM(candidates, matchContext, preferredCandidate, sameRefTransitionCandidate)) {
            return MiniHMMSelection()
        }
        val beamCandidates = candidates.take(MINI_HMM_BEAM_WIDTH)
        if (beamCandidates.isEmpty()) {
            return MiniHMMSelection()
        }

        val signalEvidence = signalQualityEvidence(
            matchContext = matchContext,
            horizontalAccuracyM = horizontalAccuracyM,
            gpsSignalBars = gpsSignalBars,
        )
        val accuracyBufferM = scaledAccuracyBufferM(horizontalAccuracyM)
        val hypotheses = mutableListOf<WayMatchHypothesis>()
        for (candidate in beamCandidates) {
            val wayId = normalizedWayId(candidate.wayId) ?: continue
            val candidateCorridorState = candidateCorridorState(
                candidate = candidate,
                matchContext = matchContext,
                wayLinks = wayLinks,
                corridorProgress = corridorProgress,
            )
            for (corridorSequenceState in corridorSequenceStates(candidate)) {
                val emission = candidate.score +
                    miniHMMPriorAdjustment(candidate, matchContext) +
                    corridorEmissionPenalty(
                        candidate = candidate,
                        candidateCorridorState = candidateCorridorState,
                        corridorState = corridorSequenceState,
                        matchContext = matchContext,
                        signalEvidence = signalEvidence,
                    )
                val cumulativeCost = if (matchContext.recentHypotheses.isEmpty()) {
                    emission
                } else {
                    matchContext.recentHypotheses.minOfOrNull { hypothesis ->
                        (hypothesis.cumulativeCost * MINI_HMM_HISTORY_DECAY) +
                            transitionPenalty(
                                hypothesis = hypothesis,
                                candidate = candidate,
                                corridorState = corridorSequenceState,
                                observedHeadingDeg = observedHeadingDeg,
                                speedKmh = speedKmh,
                                matchContext = matchContext,
                                signalEvidence = signalEvidence,
                                wayLinks = wayLinks,
                                accuracyBufferM = accuracyBufferM,
                                candidateCorridorState = candidateCorridorState,
                                pairContext = corridorPairs,
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
                    corridorState = corridorSequenceState.wireName,
                    corridorKind = candidateCorridorState?.snapshot?.kind,
                    corridorId = candidateCorridorState?.snapshot?.corridorId,
                    corridorSideNodeKey = candidateCorridorState?.snapshot?.sideNodeKey,
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
        }
        hypotheses.sortWith(
            compareBy<WayMatchHypothesis> { it.cumulativeCost }
                .thenBy { it.emissionScore }
                .thenBy { it.wayId }
                .thenBy { it.corridorState ?: "~" },
        )
        if (hypotheses.size > MINI_HMM_BEAM_WIDTH) {
            hypotheses.subList(MINI_HMM_BEAM_WIDTH, hypotheses.size).clear()
        }
        val selectedWayId = hypotheses.firstOrNull()?.wayId
        val selectedCorridorState = hypotheses.firstOrNull()?.let(::corridorSequenceStateFrom)
        val selectedCandidate = beamCandidates.firstOrNull { normalizedWayId(it.wayId) == selectedWayId }
        return MiniHMMSelection(
            selectedCandidate = selectedCandidate,
            selectedCorridorState = selectedCorridorState,
            hypotheses = hypotheses,
            used = selectedCandidate != null,
            candidateCount = beamCandidates.size,
        )
    }

    private fun corridorSequenceStateFrom(hypothesis: WayMatchHypothesis): CorridorSequenceState {
        return when (hypothesis.corridorState) {
            CorridorSequenceState.SURFACE.wireName -> CorridorSequenceState.SURFACE
            CorridorSequenceState.TUNNEL_PORTAL.wireName -> CorridorSequenceState.TUNNEL_PORTAL
            CorridorSequenceState.TUNNEL_INSIDE.wireName -> CorridorSequenceState.TUNNEL_INSIDE
            CorridorSequenceState.TUNNEL_EXIT.wireName -> CorridorSequenceState.TUNNEL_EXIT
            CorridorSequenceState.MOTORWAY_PORTAL.wireName -> CorridorSequenceState.MOTORWAY_PORTAL
            CorridorSequenceState.MOTORWAY_INSIDE.wireName -> CorridorSequenceState.MOTORWAY_INSIDE
            CorridorSequenceState.MOTORWAY_EXIT.wireName -> CorridorSequenceState.MOTORWAY_EXIT
            null -> {
                if (hypothesis.isTunnel) {
                    CorridorSequenceState.TUNNEL_INSIDE
                } else if (hypothesis.highway.equals("motorway", ignoreCase = true)) {
                    CorridorSequenceState.MOTORWAY_INSIDE
                } else if (hypothesis.highway.equals("motorway_link", ignoreCase = true)) {
                    CorridorSequenceState.MOTORWAY_PORTAL
                } else {
                    CorridorSequenceState.SURFACE
                }
            }

            else -> CorridorSequenceState.SURFACE
        }
    }

    private fun corridorSequenceStates(candidate: WayCandidate): List<CorridorSequenceState> {
        return when (corridorState(candidate)) {
            CorridorState.SURFACE -> listOf(CorridorSequenceState.SURFACE, CorridorSequenceState.TUNNEL_EXIT)
            CorridorState.TUNNEL -> listOf(CorridorSequenceState.TUNNEL_PORTAL, CorridorSequenceState.TUNNEL_INSIDE)
            CorridorState.MOTORWAY -> listOf(CorridorSequenceState.MOTORWAY_INSIDE)
            CorridorState.MOTORWAY_LINK -> listOf(CorridorSequenceState.MOTORWAY_PORTAL, CorridorSequenceState.MOTORWAY_EXIT)
        }
    }

    private fun isCommittedCorridorSelectionState(corridorState: CorridorSequenceState): Boolean {
        return when (corridorState) {
            CorridorSequenceState.TUNNEL_INSIDE,
            CorridorSequenceState.MOTORWAY_INSIDE -> true

            else -> false
        }
    }

    private fun shouldPromoteMiniHMMCorridorSelection(
        state: CorridorSequenceState,
        candidate: WayCandidate,
        candidateCorridorState: CandidateCorridorState,
        heuristicCandidate: WayCandidate?,
        matchContext: WayMatchContext,
        signalEvidence: SignalQualityEvidence,
    ): Boolean {
        if (!isCommittedCorridorSelectionState(state)) {
            return false
        }
        val scoreSlackM = when (state) {
            CorridorSequenceState.TUNNEL_INSIDE -> {
                val chainCommitScore = corridorChainCommitScore(candidateCorridorState, matchContext)
                val tunnelEvidenceScore = max(
                    signalEvidence.tunnelScore,
                    max(portalCommitProgressScore(candidate, matchContext), chainCommitScore),
                )
                if (!signalEvidence.hadRecentGpsSignalLoss &&
                    chainCommitScore < CORRIDOR_STATE_TUNNEL_CHAIN_COMMIT_MIN_SCORE &&
                    (tunnelEvidenceScore < CORRIDOR_STATE_TUNNEL_OUTPUT_MIN_SCORE ||
                        !matchesTunnelApproachCandidate(candidate, matchContext))
                ) {
                    return false
                }
                CORRIDOR_STATE_TUNNEL_OUTPUT_SCORE_SLACK_M +
                    (chainCommitScore * CORRIDOR_STATE_TUNNEL_CHAIN_SLACK_BONUS_M)
            }

            CorridorSequenceState.MOTORWAY_INSIDE -> CORRIDOR_STATE_MOTORWAY_OUTPUT_SCORE_SLACK_M
            else -> return false
        }
        return heuristicCandidate == null || candidate.score <= heuristicCandidate.score + scoreSlackM
    }

    private fun shouldKeepSurfaceHeuristicOverUncommittedTunnelCandidate(
        state: CorridorSequenceState,
        tunnelCandidate: WayCandidate,
        heuristicCandidate: WayCandidate,
    ): Boolean {
        if (!isTruthyOsmTag(tunnelCandidate.tunnel) || isTruthyOsmTag(heuristicCandidate.tunnel)) {
            return false
        }
        return when (state) {
            CorridorSequenceState.TUNNEL_PORTAL,
            CorridorSequenceState.TUNNEL_INSIDE -> true

            else -> false
        }
    }

    private fun corridorEmissionPenalty(
        candidate: WayCandidate,
        candidateCorridorState: CandidateCorridorState?,
        corridorState: CorridorSequenceState,
        matchContext: WayMatchContext,
        signalEvidence: SignalQualityEvidence,
    ): Double {
        val candidateClass = corridorState(candidate)
        val chainCommitScore = corridorChainCommitScore(candidateCorridorState, matchContext)
        return when (corridorState) {
            CorridorSequenceState.SURFACE -> {
                if (candidateClass != CorridorState.SURFACE) {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                } else {
                    0.0
                }
            }

            CorridorSequenceState.TUNNEL_PORTAL -> {
                if (candidateClass != CorridorState.TUNNEL) {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                } else {
                    var penalty = 6.0
                    if (matchesTunnelApproachCandidate(candidate, matchContext)) {
                        penalty -= 1.5
                    }
                    val portalEvidenceScore = max(signalEvidence.tunnelScore, portalMotionProgressScore(candidate, matchContext))
                    penalty -= portalEvidenceScore * CORRIDOR_STATE_TUNNEL_SIGNAL_REWARD_M
                    penalty -= chainCommitScore * (CORRIDOR_STATE_TUNNEL_CHAIN_REWARD_M * 0.35)
                    penalty
                }
            }

            CorridorSequenceState.TUNNEL_INSIDE -> {
                if (candidateClass != CorridorState.TUNNEL) {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                } else {
                    var penalty = 4.0
                    val candidateWayId = normalizedWayId(candidate.wayId)
                    val candidateRefTokens = normalizedRefTokens(candidate.streetRef).toSet()
                    if (candidateWayId != null && candidateWayId in matchContext.recentTunnelCandidateWayIds) {
                        penalty -= CORRIDOR_STATE_TUNNEL_PERSISTENCE_REWARD_M
                    } else if (candidateRefTokens.isNotEmpty() &&
                        candidateRefTokens.any { token -> token in matchContext.recentTunnelCandidateRefs }
                    ) {
                        penalty -= CORRIDOR_STATE_TUNNEL_PERSISTENCE_REWARD_M * 0.5
                    }
                    val tunnelEvidenceScore = max(
                        signalEvidence.tunnelScore,
                        max(portalCommitProgressScore(candidate, matchContext), chainCommitScore),
                    )
                    penalty -= tunnelEvidenceScore * (CORRIDOR_STATE_TUNNEL_SIGNAL_REWARD_M * 0.5)
                    penalty -= chainCommitScore * CORRIDOR_STATE_TUNNEL_CHAIN_REWARD_M
                    penalty
                }
            }

            CorridorSequenceState.TUNNEL_EXIT -> {
                if (candidateClass != CorridorState.SURFACE) {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                } else {
                    4.0
                }
            }

            CorridorSequenceState.MOTORWAY_PORTAL -> {
                if (candidateClass != CorridorState.MOTORWAY_LINK) {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                } else {
                    -CORRIDOR_STATE_MOTORWAY_REWARD_M
                }
            }

            CorridorSequenceState.MOTORWAY_INSIDE -> {
                if (candidateClass != CorridorState.MOTORWAY) {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                } else {
                    -(CORRIDOR_STATE_MOTORWAY_REWARD_M + 1.0)
                }
            }

            CorridorSequenceState.MOTORWAY_EXIT -> {
                if (candidateClass != CorridorState.MOTORWAY_LINK) {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                } else {
                    -CORRIDOR_STATE_MOTORWAY_REWARD_M
                }
            }
        }
    }

    private fun transitionPenalty(
        hypothesis: WayMatchHypothesis,
        candidate: WayCandidate,
        corridorState: CorridorSequenceState,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        matchContext: WayMatchContext,
        signalEvidence: SignalQualityEvidence,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double,
        candidateCorridorState: CandidateCorridorState?,
        pairContext: CorridorPairContext,
    ): Double {
        val wayPenalty = genericTransitionPenalty(
            hypothesis = hypothesis,
            candidate = candidate,
            observedHeadingDeg = observedHeadingDeg,
            speedKmh = speedKmh,
            matchContext = matchContext,
            wayLinks = wayLinks,
        )
        val statePenalty = corridorStateTransitionPenalty(
            hypothesis = hypothesis,
            candidate = candidate,
            nextState = corridorState,
            matchContext = matchContext,
            signalEvidence = signalEvidence,
            wayLinks = wayLinks,
            accuracyBufferM = accuracyBufferM,
            candidateCorridorState = candidateCorridorState,
            pairContext = pairContext,
        )
        return wayPenalty + statePenalty
    }

    private fun corridorStateTransitionPenalty(
        hypothesis: WayMatchHypothesis,
        candidate: WayCandidate,
        nextState: CorridorSequenceState,
        matchContext: WayMatchContext,
        signalEvidence: SignalQualityEvidence,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double,
        candidateCorridorState: CandidateCorridorState?,
        pairContext: CorridorPairContext,
    ): Double {
        val previousState = corridorSequenceStateFrom(hypothesis)
        val previousCorridorSnapshot = hypothesisCorridorSnapshot(hypothesis)
        val candidateSnapshot = candidateCorridorState?.snapshot
        val previousAnchor = CorridorAnchor(
            wayId = hypothesis.wayId,
            highway = hypothesis.highway,
            endpointProximityM = hypothesis.endpointProximityM,
            isInTunnelMode = previousState == CorridorSequenceState.TUNNEL_PORTAL ||
                previousState == CorridorSequenceState.TUNNEL_INSIDE,
        )
        val candidateWayId = normalizedWayId(candidate.wayId)
        val linkedToPrevious = areLinkedWays(hypothesis.wayId, candidateWayId, wayLinks)
        val sharedRefLinkedToPrevious = areSharedRefLinkedWays(hypothesis.wayId, candidateWayId, wayLinks)
        val candidateRefTokens = normalizedRefTokens(candidate.streetRef).toSet()
        val previousRefTokens = normalizedRefTokens(hypothesis.streetRef).toSet()
        val sharesRefWithPrevious = candidateRefTokens.isNotEmpty() && candidateRefTokens.intersect(previousRefTokens).isNotEmpty()
        val portalMotionScore = portalMotionProgressScore(candidate, matchContext)
        val portalCommitScore = portalCommitProgressScore(candidate, matchContext)
        val tunnelPortalTransition = isTunnelPortalTransition(
            anchor = previousAnchor,
            candidate = candidate,
            matchContext = matchContext,
            wayLinks = wayLinks,
            accuracyBufferM = accuracyBufferM,
            entry = previousState == CorridorSequenceState.SURFACE || previousState == CorridorSequenceState.TUNNEL_PORTAL,
        )
        val motorwayTransition = isMotorwayTransitionCandidate(previousAnchor, candidate, wayLinks, accuracyBufferM)

        if (pairContext.available && previousCorridorSnapshot != null && candidateSnapshot != null) {
            if (previousCorridorSnapshot.kind == candidateSnapshot.kind &&
                previousCorridorSnapshot.corridorId == candidateSnapshot.corridorId &&
                previousCorridorSnapshot.sideNodeKey == candidateSnapshot.sideNodeKey
            ) {
                when {
                    previousState == CorridorSequenceState.SURFACE &&
                        nextState == CorridorSequenceState.SURFACE &&
                        candidateSnapshot.kind == "surface" -> return CORRIDOR_STATE_PERSISTENCE_PENALTY_M

                    (previousState == CorridorSequenceState.MOTORWAY_PORTAL &&
                        nextState == CorridorSequenceState.MOTORWAY_PORTAL &&
                        candidateSnapshot.kind == "motorway_link") ||
                        (previousState == CorridorSequenceState.MOTORWAY_EXIT &&
                            nextState == CorridorSequenceState.MOTORWAY_EXIT &&
                            candidateSnapshot.kind == "motorway_link") -> {
                        return CORRIDOR_STATE_PERSISTENCE_PENALTY_M
                    }

                    (previousState == CorridorSequenceState.TUNNEL_PORTAL &&
                        nextState == CorridorSequenceState.TUNNEL_PORTAL &&
                        candidateSnapshot.kind == "tunnel") ||
                        (previousState == CorridorSequenceState.TUNNEL_INSIDE &&
                            nextState == CorridorSequenceState.TUNNEL_INSIDE &&
                            candidateSnapshot.kind == "tunnel") -> {
                        return CORRIDOR_STATE_PERSISTENCE_PENALTY_M - CORRIDOR_STATE_TUNNEL_PERSISTENCE_REWARD_M
                    }

                    previousState == CorridorSequenceState.MOTORWAY_INSIDE &&
                        nextState == CorridorSequenceState.MOTORWAY_INSIDE &&
                        candidateSnapshot.kind == "motorway" -> {
                        return CORRIDOR_STATE_PERSISTENCE_PENALTY_M - CORRIDOR_STATE_MOTORWAY_REWARD_M
                    }
                }
            }

            if (previousCorridorSnapshot.kind == "surface" &&
                candidateSnapshot.kind == "tunnel" &&
                isPairedWithMainCorridor(previousCorridorSnapshot, candidateSnapshot, pairContext)
            ) {
                when (nextState) {
                    CorridorSequenceState.TUNNEL_PORTAL -> {
                        val tunnelEvidenceScore = max(signalEvidence.tunnelScore, portalMotionScore)
                        return CORRIDOR_STATE_EXPECTED_TRANSITION_PENALTY_M -
                            (tunnelEvidenceScore * CORRIDOR_STATE_TUNNEL_SIGNAL_REWARD_M)
                    }

                    CorridorSequenceState.TUNNEL_INSIDE -> {
                        val tunnelEvidenceScore = max(signalEvidence.tunnelScore, portalCommitScore)
                        return CORRIDOR_STATE_REENTRY_PENALTY_M -
                            (tunnelEvidenceScore * CORRIDOR_STATE_TUNNEL_SIGNAL_REWARD_M)
                    }

                    else -> Unit
                }
            }

            if (previousCorridorSnapshot.kind == "tunnel" &&
                candidateSnapshot.kind == "surface" &&
                isMainCorridorPairedToCandidate(
                    mainSnapshot = previousCorridorSnapshot,
                    candidateSnapshot = candidateSnapshot,
                    pairContext = pairContext,
                    requireOppositeSide = true,
                )
            ) {
                when (nextState) {
                    CorridorSequenceState.TUNNEL_EXIT,
                    CorridorSequenceState.SURFACE -> return CORRIDOR_STATE_EXPECTED_TRANSITION_PENALTY_M

                    else -> Unit
                }
            }

            if (previousCorridorSnapshot.kind == "motorway_link" &&
                candidateSnapshot.kind == "motorway" &&
                isPairedWithMainCorridor(previousCorridorSnapshot, candidateSnapshot, pairContext)
            ) {
                if (nextState == CorridorSequenceState.MOTORWAY_INSIDE) {
                    return CORRIDOR_STATE_EXPECTED_TRANSITION_PENALTY_M - CORRIDOR_STATE_MOTORWAY_REWARD_M
                }
            }

            if (previousCorridorSnapshot.kind == "motorway" &&
                candidateSnapshot.kind == "motorway_link" &&
                isMainCorridorPairedToCandidate(
                    mainSnapshot = previousCorridorSnapshot,
                    candidateSnapshot = candidateSnapshot,
                    pairContext = pairContext,
                    requireOppositeSide = true,
                ) &&
                nextState == CorridorSequenceState.MOTORWAY_EXIT
            ) {
                return CORRIDOR_STATE_EXPECTED_TRANSITION_PENALTY_M
            }
        }

        return when (previousState to nextState) {
            CorridorSequenceState.SURFACE to CorridorSequenceState.SURFACE -> CORRIDOR_STATE_PERSISTENCE_PENALTY_M
            CorridorSequenceState.SURFACE to CorridorSequenceState.TUNNEL_PORTAL -> {
                if (tunnelPortalTransition) {
                    val tunnelEvidenceScore = max(signalEvidence.tunnelScore, portalMotionScore)
                    CORRIDOR_STATE_EXPECTED_TRANSITION_PENALTY_M -
                        (tunnelEvidenceScore * CORRIDOR_STATE_TUNNEL_SIGNAL_REWARD_M)
                } else {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                }
            }

            CorridorSequenceState.SURFACE to CorridorSequenceState.TUNNEL_INSIDE -> {
                if (matchesTunnelApproachCandidate(candidate, matchContext) &&
                    (signalEvidence.hadRecentGpsSignalLoss ||
                        signalEvidence.tunnelScore >= CORRIDOR_STATE_TUNNEL_DIRECT_COMMIT_MIN_SCORE ||
                        portalCommitScore >= CORRIDOR_STATE_TUNNEL_DIRECT_COMMIT_MIN_SCORE)
                ) {
                    val tunnelEvidenceScore = max(signalEvidence.tunnelScore, portalCommitScore)
                    CORRIDOR_STATE_REENTRY_PENALTY_M -
                        (tunnelEvidenceScore * CORRIDOR_STATE_TUNNEL_SIGNAL_REWARD_M)
                } else {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                }
            }

            CorridorSequenceState.SURFACE to CorridorSequenceState.MOTORWAY_PORTAL -> {
                if (motorwayTransition) CORRIDOR_STATE_EXPECTED_TRANSITION_PENALTY_M else CORRIDOR_STATE_ILLEGAL_PENALTY_M
            }

            CorridorSequenceState.SURFACE to CorridorSequenceState.MOTORWAY_INSIDE,
            CorridorSequenceState.SURFACE to CorridorSequenceState.MOTORWAY_EXIT,
            CorridorSequenceState.SURFACE to CorridorSequenceState.TUNNEL_EXIT -> CORRIDOR_STATE_ILLEGAL_PENALTY_M

            CorridorSequenceState.TUNNEL_PORTAL to CorridorSequenceState.SURFACE -> CORRIDOR_STATE_REENTRY_PENALTY_M
            CorridorSequenceState.TUNNEL_PORTAL to CorridorSequenceState.TUNNEL_PORTAL -> {
                if (linkedToPrevious || sharedRefLinkedToPrevious || sharesRefWithPrevious) {
                    CORRIDOR_STATE_PERSISTENCE_PENALTY_M
                } else {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                }
            }

            CorridorSequenceState.TUNNEL_PORTAL to CorridorSequenceState.TUNNEL_INSIDE -> {
                if (linkedToPrevious || sharedRefLinkedToPrevious || sharesRefWithPrevious) {
                    CORRIDOR_STATE_EXPECTED_TRANSITION_PENALTY_M - CORRIDOR_STATE_TUNNEL_PERSISTENCE_REWARD_M
                } else {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                }
            }

            CorridorSequenceState.TUNNEL_PORTAL to CorridorSequenceState.TUNNEL_EXIT,
            CorridorSequenceState.TUNNEL_PORTAL to CorridorSequenceState.MOTORWAY_PORTAL,
            CorridorSequenceState.TUNNEL_PORTAL to CorridorSequenceState.MOTORWAY_INSIDE,
            CorridorSequenceState.TUNNEL_PORTAL to CorridorSequenceState.MOTORWAY_EXIT -> CORRIDOR_STATE_ILLEGAL_PENALTY_M

            CorridorSequenceState.TUNNEL_INSIDE to CorridorSequenceState.TUNNEL_PORTAL -> {
                if (linkedToPrevious || sharedRefLinkedToPrevious || sharesRefWithPrevious) {
                    CORRIDOR_STATE_PERSISTENCE_PENALTY_M
                } else {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                }
            }

            CorridorSequenceState.TUNNEL_INSIDE to CorridorSequenceState.TUNNEL_INSIDE -> {
                if (linkedToPrevious || sharedRefLinkedToPrevious || sharesRefWithPrevious) {
                    CORRIDOR_STATE_PERSISTENCE_PENALTY_M - CORRIDOR_STATE_TUNNEL_PERSISTENCE_REWARD_M
                } else {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                }
            }

            CorridorSequenceState.TUNNEL_INSIDE to CorridorSequenceState.TUNNEL_EXIT -> {
                if (tunnelPortalTransition) CORRIDOR_STATE_EXPECTED_TRANSITION_PENALTY_M else CORRIDOR_STATE_ILLEGAL_PENALTY_M
            }

            CorridorSequenceState.TUNNEL_INSIDE to CorridorSequenceState.SURFACE,
            CorridorSequenceState.TUNNEL_INSIDE to CorridorSequenceState.MOTORWAY_PORTAL,
            CorridorSequenceState.TUNNEL_INSIDE to CorridorSequenceState.MOTORWAY_INSIDE,
            CorridorSequenceState.TUNNEL_INSIDE to CorridorSequenceState.MOTORWAY_EXIT -> CORRIDOR_STATE_ILLEGAL_PENALTY_M

            CorridorSequenceState.TUNNEL_EXIT to CorridorSequenceState.SURFACE -> {
                if (linkedToPrevious || sharesRefWithPrevious || candidateWayId == hypothesis.wayId) {
                    CORRIDOR_STATE_EXPECTED_TRANSITION_PENALTY_M
                } else {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                }
            }

            CorridorSequenceState.TUNNEL_EXIT to CorridorSequenceState.TUNNEL_INSIDE -> CORRIDOR_STATE_REENTRY_PENALTY_M
            CorridorSequenceState.TUNNEL_EXIT to CorridorSequenceState.TUNNEL_PORTAL,
            CorridorSequenceState.TUNNEL_EXIT to CorridorSequenceState.TUNNEL_EXIT,
            CorridorSequenceState.TUNNEL_EXIT to CorridorSequenceState.MOTORWAY_PORTAL,
            CorridorSequenceState.TUNNEL_EXIT to CorridorSequenceState.MOTORWAY_INSIDE,
            CorridorSequenceState.TUNNEL_EXIT to CorridorSequenceState.MOTORWAY_EXIT -> CORRIDOR_STATE_ILLEGAL_PENALTY_M

            CorridorSequenceState.MOTORWAY_PORTAL to CorridorSequenceState.SURFACE -> CORRIDOR_STATE_REENTRY_PENALTY_M
            CorridorSequenceState.MOTORWAY_PORTAL to CorridorSequenceState.MOTORWAY_PORTAL -> {
                if (motorwayTransition) CORRIDOR_STATE_PERSISTENCE_PENALTY_M else CORRIDOR_STATE_ILLEGAL_PENALTY_M
            }

            CorridorSequenceState.MOTORWAY_PORTAL to CorridorSequenceState.MOTORWAY_INSIDE -> {
                if (motorwayTransition) {
                    CORRIDOR_STATE_EXPECTED_TRANSITION_PENALTY_M - CORRIDOR_STATE_MOTORWAY_REWARD_M
                } else {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                }
            }

            CorridorSequenceState.MOTORWAY_PORTAL to CorridorSequenceState.MOTORWAY_EXIT -> {
                if (motorwayTransition) CORRIDOR_STATE_EXPECTED_TRANSITION_PENALTY_M else CORRIDOR_STATE_ILLEGAL_PENALTY_M
            }

            CorridorSequenceState.MOTORWAY_PORTAL to CorridorSequenceState.TUNNEL_PORTAL,
            CorridorSequenceState.MOTORWAY_PORTAL to CorridorSequenceState.TUNNEL_INSIDE,
            CorridorSequenceState.MOTORWAY_PORTAL to CorridorSequenceState.TUNNEL_EXIT -> CORRIDOR_STATE_ILLEGAL_PENALTY_M

            CorridorSequenceState.MOTORWAY_INSIDE to CorridorSequenceState.MOTORWAY_INSIDE -> {
                if (linkedToPrevious || sharesRefWithPrevious) {
                    CORRIDOR_STATE_PERSISTENCE_PENALTY_M - CORRIDOR_STATE_MOTORWAY_REWARD_M
                } else {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                }
            }

            CorridorSequenceState.MOTORWAY_INSIDE to CorridorSequenceState.MOTORWAY_EXIT -> {
                if (motorwayTransition) CORRIDOR_STATE_EXPECTED_TRANSITION_PENALTY_M else CORRIDOR_STATE_ILLEGAL_PENALTY_M
            }

            CorridorSequenceState.MOTORWAY_INSIDE to CorridorSequenceState.SURFACE,
            CorridorSequenceState.MOTORWAY_INSIDE to CorridorSequenceState.MOTORWAY_PORTAL,
            CorridorSequenceState.MOTORWAY_INSIDE to CorridorSequenceState.TUNNEL_PORTAL,
            CorridorSequenceState.MOTORWAY_INSIDE to CorridorSequenceState.TUNNEL_INSIDE,
            CorridorSequenceState.MOTORWAY_INSIDE to CorridorSequenceState.TUNNEL_EXIT -> CORRIDOR_STATE_ILLEGAL_PENALTY_M

            CorridorSequenceState.MOTORWAY_EXIT to CorridorSequenceState.SURFACE -> {
                if (linkedToPrevious || sharesRefWithPrevious || hasEndpointContinuation(hypothesis, candidate)) {
                    CORRIDOR_STATE_EXPECTED_TRANSITION_PENALTY_M
                } else {
                    CORRIDOR_STATE_ILLEGAL_PENALTY_M
                }
            }

            CorridorSequenceState.MOTORWAY_EXIT to CorridorSequenceState.MOTORWAY_EXIT -> {
                if (motorwayTransition) CORRIDOR_STATE_PERSISTENCE_PENALTY_M else CORRIDOR_STATE_ILLEGAL_PENALTY_M
            }

            CorridorSequenceState.MOTORWAY_EXIT to CorridorSequenceState.MOTORWAY_PORTAL,
            CorridorSequenceState.MOTORWAY_EXIT to CorridorSequenceState.MOTORWAY_INSIDE,
            CorridorSequenceState.MOTORWAY_EXIT to CorridorSequenceState.TUNNEL_PORTAL,
            CorridorSequenceState.MOTORWAY_EXIT to CorridorSequenceState.TUNNEL_INSIDE,
            CorridorSequenceState.MOTORWAY_EXIT to CorridorSequenceState.TUNNEL_EXIT -> CORRIDOR_STATE_ILLEGAL_PENALTY_M
            else -> CORRIDOR_STATE_ILLEGAL_PENALTY_M
        }
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
        if (candidateRefTokens.isNotEmpty() && candidateRefTokens.any { token -> token in matchContext.recentStreetRefs }) {
            adjustment -= 3.5
        }
        val recentTunnelWayMatch = candidateWayId?.let { it in matchContext.recentTunnelCandidateWayIds } == true
        if (matchContext.isInTunnelMode) {
            adjustment += if (isTruthyOsmTag(candidate.tunnel)) -6.0 else 10.0
        }
        if (isTruthyOsmTag(candidate.tunnel) &&
            matchContext.hadRecentGpsSignalLoss &&
            (recentTunnelWayMatch || candidateRefTokens.any { token -> token in matchContext.recentTunnelCandidateRefs })
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
        corridorPairs: CorridorPairContext,
        accuracyBufferM: Double,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
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
                val tunnelSelectable = isTunnelCandidateSelectable(
                    candidate = candidate,
                    matchContext = matchContext,
                    wayLinks = wayLinks,
                    progressContext = corridorProgress,
                    pairContext = corridorPairs,
                    accuracyBufferM = accuracyBufferM,
                )
                val corridorSelectable = isCorridorCandidateSelectable(
                    candidate = candidate,
                    matchContext = matchContext,
                    wayLinks = wayLinks,
                    progressContext = corridorProgress,
                    pairContext = corridorPairs,
                    accuracyBufferM = accuracyBufferM,
                    horizontalAccuracyM = horizontalAccuracyM,
                    gpsSignalBars = gpsSignalBars,
                )
                TraceRankedCandidate(
                    candidate = candidate,
                    continuity = continuity,
                    portalEligible = portalEligible,
                    corridorState = corridorState,
                    tunnelSelectable = tunnelSelectable,
                    corridorSelectable = corridorSelectable,
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

    private fun buildBaselineTraceRankedCandidates(
        candidates: List<WayCandidate>,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
    ): List<TraceRankedCandidate> {
        val maxDistance = candidates.maxOfOrNull { it.distanceM } ?: 0.0
        val sorted = candidates
            .map { candidate ->
                val continuity = continuityClass(candidate, matchContext, wayLinks)
                TraceRankedCandidate(
                    candidate = candidate,
                    continuity = continuity,
                    portalEligible = false,
                    corridorState = null,
                    tunnelSelectable = true,
                    corridorSelectable = true,
                    traceScore = candidateTraceScore(
                        geometryScore = candidate.distanceM,
                        continuityClass = continuity.traceName,
                        maxGeometryScore = maxDistance,
                    ),
                    traceRank = 0,
                )
            }
            .sortedWith(
                compareBy<TraceRankedCandidate> { it.traceScore }
                    .thenBy { it.candidate.score }
                    .thenBy { it.candidate.wayId ?: "~" },
            )
        return sorted.mapIndexed { index, entry -> entry.copy(traceRank = index + 1) }
    }

    private fun buildNonCorridorCandidateSelection(
        finalSelected: WayCandidate?,
        traceRankedCandidates: List<TraceRankedCandidate>,
        selectionTrace: List<MatchSelectionTrace>,
        nearbyTunnelCandidateWayIds: Set<String>,
        nearbyTunnelCandidateRefs: Set<String>,
        portalEligibleTunnelWayIds: Set<String>,
        portalEligibleTunnelRefs: Set<String>,
        modelTraceName: String? = null,
    ): CandidateSelection {
        val finalSelectionTrace = selectionTrace.toMutableList()
        finalSelected?.let {
            finalSelectionTrace += MatchSelectionTrace(
                step = "final",
                detail = buildString {
                    append("selected ").append(it.wayId ?: "nil")
                    append(" tunnel=").append(isTruthyOsmTag(it.tunnel))
                    append(" corridor=none")
                    if (modelTraceName != null) {
                        append(" model=").append(modelTraceName)
                    }
                },
            )
        }
        val selectedWayId = normalizedWayId(finalSelected?.wayId)
        val candidateTraces = traceRankedCandidates
            .take(MAX_TRACE_CANDIDATE_COUNT)
            .map { entry ->
                MatcherCandidateTrace(
                    rank = entry.traceRank,
                    wayId = entry.candidate.wayId,
                    score = entry.traceScore,
                    distanceM = entry.candidate.distanceM,
                    geometryScore = entry.candidate.distanceM,
                    endpointProximityM = entry.candidate.endpointProximityM,
                    continuityClass = entry.continuity.traceName,
                    highway = entry.candidate.highway,
                    service = entry.candidate.service,
                    streetName = entry.candidate.streetName,
                    streetRef = entry.candidate.streetRef,
                    tunnel = entry.candidate.tunnel,
                    tunnelSelectable = true,
                    corridorSelectable = true,
                    portalEligible = false,
                    isSelected = normalizedWayId(entry.candidate.wayId) == selectedWayId,
                )
            }
        return CandidateSelection(
            selected = finalSelected,
            candidateTraces = candidateTraces,
            nearbyTunnelCandidateWayIds = nearbyTunnelCandidateWayIds,
            nearbyTunnelCandidateRefs = nearbyTunnelCandidateRefs,
            portalEligibleTunnelWayIds = portalEligibleTunnelWayIds,
            portalEligibleTunnelRefs = portalEligibleTunnelRefs,
            activeCorridorState = null,
            approachCorridorStateCandidate = null,
            usedWalkingTurnSwitch = false,
            usedMiniHMM = false,
            miniHMMCandidateCount = 0,
            matchHypotheses = emptyList(),
            selectionTrace = finalSelectionTrace,
        )
    }

    private fun baselineModeFilteredCandidates(
        candidates: List<WayCandidate>,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
    ): List<WayCandidate> {
        val preferredWayId = matchContext.preferredWayId ?: return candidates
        if (matchContext.isInTunnelMode) {
            val filtered = candidates.filter { candidate ->
                if (isTruthyOsmTag(candidate.tunnel)) {
                    true
                } else {
                    areLinkedWays(preferredWayId, normalizedWayId(candidate.wayId), wayLinks) &&
                        candidate.endpointProximityM <= BASELINE_TUNNEL_EXIT_ENDPOINT_THRESHOLD_M
                }
            }
            return filtered.ifEmpty { candidates }
        }
        if (matchContext.isInMotorwayMode) {
            val preferredHighway = matchContext.preferredHighway?.lowercase().orEmpty()
            val filtered = candidates.filter { candidate ->
                val candidateHighway = candidate.highway?.lowercase().orEmpty()
                val candidateWayId = normalizedWayId(candidate.wayId)
                when (preferredHighway) {
                    "motorway_link" -> {
                        if (candidateHighway == "motorway" || candidateHighway == "motorway_link") {
                            true
                        } else {
                            areLinkedWays(preferredWayId, candidateWayId, wayLinks) &&
                                candidate.endpointProximityM <= BASELINE_MOTORWAY_GATE_ENDPOINT_THRESHOLD_M
                        }
                    }

                    else -> when (candidateHighway) {
                        "motorway" -> true
                        "motorway_link" -> areLinkedWays(preferredWayId, candidateWayId, wayLinks)
                        else -> false
                    }
                }
            }
            return filtered.ifEmpty { candidates }
        }
        return candidates
    }

    private fun bestBaselineContinuityCandidate(
        candidates: List<WayCandidate>,
        continuity: ContinuityClass,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
    ): WayCandidate? {
        return candidates
            .asSequence()
            .filter { continuityClass(it, matchContext, wayLinks) == continuity }
            .minWithOrNull(
                Comparator { lhs, rhs ->
                    when {
                        isBetterDistanceCandidate(lhs, rhs) -> -1
                        isBetterDistanceCandidate(rhs, lhs) -> 1
                        else -> 0
                    }
                },
            )
    }

    private fun shouldKeepBaselineContinuityCandidate(
        continuityCandidate: WayCandidate,
        bestCandidate: WayCandidate,
        accuracyBufferM: Double,
        distanceSlackM: Double,
    ): Boolean {
        val allowedDistanceSlack = max(distanceSlackM, accuracyBufferM * 0.35)
        val allowedGeometrySlack = max(distanceSlackM * 2.0, accuracyBufferM)
        return continuityCandidate.distanceM <= bestCandidate.distanceM + allowedDistanceSlack &&
            continuityCandidate.score <= bestCandidate.score + allowedGeometrySlack
    }

    private fun baselineTurnTransitionCandidate(
        candidates: List<WayCandidate>,
        currentWayId: String?,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        accuracyBufferM: Double,
    ): WayCandidate? {
        val normalizedCurrentWayId = normalizedWayId(currentWayId) ?: return null
        val currentCandidate = candidates.firstOrNull { normalizedWayId(it.wayId) == normalizedCurrentWayId } ?: return null
        val bestCandidate = candidates.minWithOrNull(
            Comparator { lhs, rhs ->
                when {
                    isBetterDistanceCandidate(lhs, rhs) -> -1
                    isBetterDistanceCandidate(rhs, lhs) -> 1
                    else -> 0
                }
            },
        ) ?: return null
        val fromAxisHeading = axisHeadingDeg(currentCandidate)
        return candidates
            .asSequence()
            .filter { normalizedWayId(it.wayId) != normalizedCurrentWayId }
            .sortedWith(
                Comparator { lhs, rhs ->
                    when {
                        isBetterDistanceCandidate(lhs, rhs) -> -1
                        isBetterDistanceCandidate(rhs, lhs) -> 1
                        else -> 0
                    }
                },
            )
            .firstOrNull { candidate ->
                val evidence = transitionHeadingEvidence(
                    fromAxisHeadingDeg = fromAxisHeading,
                    fromEndpointProximityM = currentCandidate.endpointProximityM,
                    candidate = candidate,
                    observedHeadingDeg = observedHeadingDeg,
                    speedKmh = speedKmh,
                ) ?: return@firstOrNull false
                candidate.distanceM <= bestCandidate.distanceM + max(BASELINE_TURN_DISTANCE_SLACK_M, accuracyBufferM * 0.5) &&
                    evidence.nearEndpoint &&
                    evidence.meaningfulTurn &&
                    evidence.candidateClearlyBetterAligned &&
                    evidence.speedKmh <= BASELINE_TURN_TRANSITION_MAX_SPEED_KMH
            }
    }

    private fun selectConnectedBaselineCandidate(
        candidates: List<WayCandidate>,
        matchContext: WayMatchContext,
        observedHeadingDeg: Double?,
        speedKmh: Double?,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double,
    ): NonCorridorMatcherSelection {
        val filteredCandidates = baselineModeFilteredCandidates(candidates, matchContext, wayLinks)
        val rankedCandidates = filteredCandidates.sortedWith(
            Comparator { lhs, rhs ->
                when {
                    isBetterDistanceCandidate(lhs, rhs) -> -1
                    isBetterDistanceCandidate(rhs, lhs) -> 1
                    else -> 0
                }
            },
        )
        val traceRankedCandidates = buildBaselineTraceRankedCandidates(rankedCandidates, matchContext, wayLinks)
        val bestCandidate = rankedCandidates.firstOrNull()
            ?: return NonCorridorMatcherSelection(
                traceRankedCandidates = traceRankedCandidates,
                selectionTrace = listOf(
                    MatchSelectionTrace(step = "baseline", detail = "no selectable candidates"),
                ),
            )
        val selectionTrace = mutableListOf<MatchSelectionTrace>()
        if (filteredCandidates.size != candidates.size) {
            selectionTrace += MatchSelectionTrace(
                step = "baseline_mode_gate",
                detail = "filtered ${candidates.size - filteredCandidates.size} candidates due to tunnel/motorway mode",
            )
        }
        val preferredCandidate = bestBaselineContinuityCandidate(
            candidates = rankedCandidates,
            continuity = ContinuityClass.PREFERRED_WAY,
            matchContext = matchContext,
            wayLinks = wayLinks,
        )
        val sameRefCandidate = bestBaselineContinuityCandidate(
            candidates = rankedCandidates,
            continuity = ContinuityClass.SAME_REF,
            matchContext = matchContext,
            wayLinks = wayLinks,
        )
        val turnCandidate = baselineTurnTransitionCandidate(
            candidates = rankedCandidates,
            currentWayId = matchContext.preferredWayId,
            observedHeadingDeg = observedHeadingDeg,
            speedKmh = speedKmh,
            accuracyBufferM = accuracyBufferM,
        )
        val selected = when {
            turnCandidate != null -> {
                selectionTrace += MatchSelectionTrace(
                    step = "baseline_turn_gate",
                    detail = "selected connected turn ${turnCandidate.wayId ?: "nil"} over ${bestCandidate.wayId ?: "nil"} after low-speed heading change",
                )
                turnCandidate
            }

            preferredCandidate != null &&
                normalizedWayId(preferredCandidate.wayId) != normalizedWayId(bestCandidate.wayId) &&
                shouldKeepBaselineContinuityCandidate(
                    continuityCandidate = preferredCandidate,
                    bestCandidate = bestCandidate,
                    accuracyBufferM = accuracyBufferM,
                    distanceSlackM = BASELINE_PREFERRED_DISTANCE_SLACK_M,
                ) -> {
                selectionTrace += MatchSelectionTrace(
                    step = "baseline_preferred_hold",
                    detail = "kept preferred ${preferredCandidate.wayId ?: "nil"} over nearest ${bestCandidate.wayId ?: "nil"}",
                )
                preferredCandidate
            }

            sameRefCandidate != null &&
                normalizedWayId(sameRefCandidate.wayId) != normalizedWayId(bestCandidate.wayId) &&
                shouldKeepBaselineContinuityCandidate(
                    continuityCandidate = sameRefCandidate,
                    bestCandidate = bestCandidate,
                    accuracyBufferM = accuracyBufferM,
                    distanceSlackM = BASELINE_SAME_REF_DISTANCE_SLACK_M,
                ) -> {
                selectionTrace += MatchSelectionTrace(
                    step = "baseline_same_ref_hold",
                    detail = "kept same-ref ${sameRefCandidate.wayId ?: "nil"} over nearest ${bestCandidate.wayId ?: "nil"}",
                )
                sameRefCandidate
            }

            else -> bestCandidate
        }
        selectionTrace += MatchSelectionTrace(
            step = "baseline",
            detail = "selected ${selected.wayId ?: "nil"} nearest=${bestCandidate.wayId ?: "nil"} model=connected_baseline",
        )
        return NonCorridorMatcherSelection(
            selected = selected,
            traceRankedCandidates = traceRankedCandidates,
            selectionTrace = selectionTrace,
        )
    }

    private fun selectSimpleSpeedRefHeuristicCandidate(
        candidates: List<WayCandidate>,
        matchContext: WayMatchContext,
        speedKmh: Double?,
        horizontalAccuracyM: Double?,
        urbanSameRefReleaseEnabled: Boolean,
        useStreetNameFallbackContinuity: Boolean,
        useGuardedStreetNameFallbackContinuity: Boolean,
        wayLinks: WayLinksContext,
    ): NonCorridorMatcherSelection {
        val poorSignalThresholdM = 10.0
        val lowSpeedThresholdKmh = SIMPLE_SAME_REF_HOLD_SPEED_THRESHOLD_KMH
        val poorSignal = (horizontalAccuracyM ?: Double.POSITIVE_INFINITY) > poorSignalThresholdM
        val lowSpeedAccurateGps = (speedKmh ?: 0.0) < lowSpeedThresholdKmh &&
            (horizontalAccuracyM ?: Double.POSITIVE_INFINITY) < poorSignalThresholdM
        val filteredCandidates = if (matchContext.isInTunnelMode && poorSignal) {
            candidates.filter { isTruthyOsmTag(it.tunnel) }.ifEmpty { candidates }
        } else {
            candidates
        }
        val rankedCandidates = filteredCandidates.sortedWith(
            Comparator { lhs, rhs ->
                when {
                    isBetterDistanceCandidate(lhs, rhs) -> -1
                    isBetterDistanceCandidate(rhs, lhs) -> 1
                    else -> 0
                }
            },
        )
        val traceRankedCandidates = buildBaselineTraceRankedCandidates(rankedCandidates, matchContext, wayLinks)
        val bestCandidate = rankedCandidates.firstOrNull()
            ?: return NonCorridorMatcherSelection(
                traceRankedCandidates = traceRankedCandidates,
                selectionTrace = listOf(
                    MatchSelectionTrace(step = "simple_speed_ref_heuristic", detail = "no selectable candidates"),
                ),
            )
        val selectionTrace = mutableListOf<MatchSelectionTrace>()
        if (filteredCandidates.size != candidates.size) {
            selectionTrace += MatchSelectionTrace(
                step = "simple_tunnel_hold_gate",
                detail = "kept ${filteredCandidates.size} tunnel candidates while horizontal_accuracy_m=${formatMetric(horizontalAccuracyM ?: Double.POSITIVE_INFINITY)} remained above ${formatMetric(poorSignalThresholdM)}",
            )
        }
        val continuityIdentity: Pair<Set<String>, SimpleContinuityIdentitySource>
        val previousContinuityCandidate: WayCandidate?
        if (useGuardedStreetNameFallbackContinuity) {
            val guardedContinuity = preferredGuardedStreetNameContinuityCandidate(
                rankedCandidates = rankedCandidates,
                bestCandidate = bestCandidate,
                matchContext = matchContext,
                horizontalAccuracyM = horizontalAccuracyM,
            )
            if (guardedContinuity != null) {
                continuityIdentity = guardedContinuity.tokens to SimpleContinuityIdentitySource.STREET_NAME
                previousContinuityCandidate = guardedContinuity.candidate
                selectionTrace += guardedContinuity.trace
            } else {
                continuityIdentity = preferredSimpleContinuityIdentity(
                    matchContext = matchContext,
                    useStreetNameFallbackContinuity = useStreetNameFallbackContinuity,
                    ageOutStaleRefContinuity = true,
                )
                previousContinuityCandidate = rankedCandidates.firstOrNull { candidate ->
                    val candidateTokens = continuityTokens(
                        candidate = candidate,
                        source = continuityIdentity.second,
                        useStreetNameFallbackContinuity = useStreetNameFallbackContinuity || useGuardedStreetNameFallbackContinuity,
                    )
                    candidateTokens.isNotEmpty() && candidateTokens.any { token -> token in continuityIdentity.first }
                }
            }
        } else {
            continuityIdentity = preferredSimpleContinuityIdentity(
                matchContext = matchContext,
                useStreetNameFallbackContinuity = useStreetNameFallbackContinuity,
                ageOutStaleRefContinuity = false,
            )
            previousContinuityCandidate = rankedCandidates.firstOrNull { candidate ->
                val candidateTokens = continuityTokens(
                    candidate = candidate,
                    source = continuityIdentity.second,
                    useStreetNameFallbackContinuity = useStreetNameFallbackContinuity,
                )
                candidateTokens.isNotEmpty() && candidateTokens.any { token -> token in continuityIdentity.first }
            }
        }

        val urbanReleasePressureActive = if (
            urbanSameRefReleaseEnabled &&
            speedKmh != null &&
            speedKmh.isFinite() &&
            speedKmh >= lowSpeedThresholdKmh &&
            speedKmh <= SIMPLE_SAME_REF_URBAN_RELEASE_MAX_SPEED_KMH &&
            horizontalAccuracyM != null &&
            horizontalAccuracyM.isFinite() &&
            horizontalAccuracyM <= SIMPLE_SAME_REF_URBAN_RELEASE_MAX_ACCURACY_M &&
            previousContinuityCandidate != null &&
            normalizedWayId(previousContinuityCandidate.wayId) != normalizedWayId(bestCandidate.wayId) &&
            shouldEnableUrbanSameRefRelease(
                sameRefCandidate = previousContinuityCandidate,
                bestCandidate = bestCandidate,
            )
        ) {
            true
        } else {
            false
        }
        val nextUrbanReleaseStreak = if (urbanReleasePressureActive) {
            minOf(matchContext.sameRefUrbanReleaseStreak + 1, 8)
        } else {
            0
        }

        val selected = if (speedKmh != null && speedKmh >= lowSpeedThresholdKmh && previousContinuityCandidate != null) {
            if (
                urbanSameRefReleaseEnabled &&
                urbanReleasePressureActive &&
                nextUrbanReleaseStreak >= SIMPLE_SAME_REF_URBAN_RELEASE_REQUIRED_STREAK
            ) {
                selectionTrace += MatchSelectionTrace(
                    step = "simple_same_ref_urban_release",
                    detail = "released ${continuityIdentity.second.traceLabel} ${previousContinuityCandidate.wayId ?: "nil"} for nearest ${bestCandidate.wayId ?: "nil"} speed_kmh=${formatMetric(speedKmh)} nearest_m=${formatMetric(bestCandidate.distanceM)} continuity_m=${formatMetric(previousContinuityCandidate.distanceM)} streak=$nextUrbanReleaseStreak",
                )
                bestCandidate
            } else {
                if (normalizedWayId(previousContinuityCandidate.wayId) != normalizedWayId(bestCandidate.wayId)) {
                    val step = if (urbanSameRefReleaseEnabled && urbanReleasePressureActive) {
                        if (continuityIdentity.second == SimpleContinuityIdentitySource.STREET_NAME) {
                            "simple_same_name_urban_hold"
                        } else {
                            "simple_same_ref_urban_hold"
                        }
                    } else {
                        if (continuityIdentity.second == SimpleContinuityIdentitySource.STREET_NAME) {
                            "simple_same_name_hold"
                        } else {
                            "simple_same_ref_hold"
                        }
                    }
                    val detail = if (urbanSameRefReleaseEnabled && urbanReleasePressureActive) {
                        "kept ${continuityIdentity.second.traceLabel} ${previousContinuityCandidate.wayId ?: "nil"} over nearest ${bestCandidate.wayId ?: "nil"} at speed_kmh=${formatMetric(speedKmh)} nearest_m=${formatMetric(bestCandidate.distanceM)} continuity_m=${formatMetric(previousContinuityCandidate.distanceM)} streak=$nextUrbanReleaseStreak"
                    } else {
                        "kept ${continuityIdentity.second.traceLabel} ${previousContinuityCandidate.wayId ?: "nil"} over nearest ${bestCandidate.wayId ?: "nil"} at speed_kmh=${formatMetric(speedKmh)}"
                    }
                    selectionTrace += MatchSelectionTrace(step = step, detail = detail)
                }
                previousContinuityCandidate
            }
        } else {
            bestCandidate
        }

        if (urbanSameRefReleaseEnabled) {
            selectionTrace += MatchSelectionTrace(
                step = "simple_same_ref_urban_release_streak",
                detail = nextUrbanReleaseStreak.toString(),
            )
        }

        val reason = when {
            urbanSameRefReleaseEnabled &&
                urbanReleasePressureActive &&
                nextUrbanReleaseStreak >= SIMPLE_SAME_REF_URBAN_RELEASE_REQUIRED_STREAK &&
                normalizedWayId(selected.wayId) == normalizedWayId(bestCandidate.wayId) -> {
                if (continuityIdentity.second == SimpleContinuityIdentitySource.STREET_NAME) {
                    "urban_same_name_distance_gap_release"
                } else {
                    "urban_same_ref_distance_gap_release"
                }
            }

            speedKmh != null && speedKmh >= lowSpeedThresholdKmh && previousContinuityCandidate != null -> {
                if (continuityIdentity.second == SimpleContinuityIdentitySource.STREET_NAME) {
                    "high_speed_same_name"
                } else {
                    "high_speed_same_ref"
                }
            }

            previousContinuityCandidate != null -> {
                if (continuityIdentity.second == SimpleContinuityIdentitySource.STREET_NAME) {
                    "low_speed_same_name_release_distance"
                } else {
                    "low_speed_same_ref_release_distance"
                }
            }

            lowSpeedAccurateGps -> "low_speed_good_gps_distance"
            matchContext.isInTunnelMode && poorSignal -> "tunnel_hold_distance"
            else -> "distance_fallback"
        }
        selectionTrace += MatchSelectionTrace(
            step = "simple_speed_ref_heuristic",
            detail = "selected ${selected.wayId ?: "nil"} nearest=${bestCandidate.wayId ?: "nil"} reason=$reason speed_kmh=${formatMetric(speedKmh ?: 0.0)} hacc_m=${formatMetric(horizontalAccuracyM ?: Double.POSITIVE_INFINITY)}",
        )
        return NonCorridorMatcherSelection(
            selected = selected,
            traceRankedCandidates = traceRankedCandidates,
            selectionTrace = selectionTrace,
        )
    }

    private enum class SimpleContinuityIdentitySource(val traceLabel: String) {
        NONE("continuity"),
        REF("same-ref"),
        STREET_NAME("same-name"),
    }

    private data class GuardedStreetNameContinuity(
        val candidate: WayCandidate,
        val tokens: Set<String>,
        val trace: MatchSelectionTrace,
    )

    private fun preferredSimpleContinuityIdentity(
        matchContext: WayMatchContext,
        useStreetNameFallbackContinuity: Boolean,
        ageOutStaleRefContinuity: Boolean,
    ): Pair<Set<String>, SimpleContinuityIdentitySource> {
        val activeStreetRefTokens = normalizedRefTokens(matchContext.activeStreetRef).toSet()
        if (activeStreetRefTokens.isNotEmpty()) {
            return activeStreetRefTokens to SimpleContinuityIdentitySource.REF
        }
        val activeStreetNameTokens = normalizedStreetNameTokens(matchContext.preferredStreetName).toSet()
        if (
            useStreetNameFallbackContinuity &&
            matchContext.consecutiveNoRefMatchCount >= SIMPLE_STREET_NAME_FALLBACK_MIN_NO_REF_MATCHES &&
            activeStreetNameTokens.isNotEmpty()
        ) {
            return activeStreetNameTokens to SimpleContinuityIdentitySource.STREET_NAME
        }
        val refTokens = preferredSimpleRefContinuityTokens(
            matchContext = matchContext,
            ageOutStaleRefContinuity = ageOutStaleRefContinuity,
        )
        if (refTokens.isNotEmpty()) {
            return refTokens to SimpleContinuityIdentitySource.REF
        }
        return emptySet<String>() to SimpleContinuityIdentitySource.NONE
    }

    private fun preferredGuardedStreetNameContinuityCandidate(
        rankedCandidates: List<WayCandidate>,
        bestCandidate: WayCandidate,
        matchContext: WayMatchContext,
        horizontalAccuracyM: Double?,
    ): GuardedStreetNameContinuity? {
        val activeStreetRefTokens = normalizedRefTokens(matchContext.activeStreetRef).toSet()
        val activeStreetNameTokens = normalizedStreetNameTokens(matchContext.preferredStreetName).toSet()
        if (
            activeStreetRefTokens.isNotEmpty() ||
            matchContext.consecutiveNoRefMatchCount < SIMPLE_STREET_NAME_FALLBACK_MIN_NO_REF_MATCHES ||
            activeStreetNameTokens.isEmpty() ||
            !isUrbanSameRefReleaseTargetHighway(matchContext.preferredHighway) ||
            horizontalAccuracyM == null ||
            !horizontalAccuracyM.isFinite() ||
            horizontalAccuracyM <= 0.0
        ) {
            return null
        }

        val nameCandidate = rankedCandidates.firstOrNull { candidate ->
            val candidateRefTokens = normalizedRefTokens(candidate.streetRef).toSet()
            if (candidateRefTokens.isNotEmpty()) {
                return@firstOrNull false
            }
            val candidateTokens = normalizedStreetNameTokens(candidate.streetBaseName ?: candidate.streetName).toSet()
            candidateTokens.isNotEmpty() && candidateTokens.any { token -> token in activeStreetNameTokens }
        } ?: return null

        if (
            normalizedWayId(nameCandidate.wayId) != normalizedWayId(bestCandidate.wayId) ||
            !isUrbanSameRefReleaseTargetHighway(nameCandidate.highway) ||
            nameCandidate.distanceM > horizontalAccuracyM
        ) {
            return null
        }

        val refTokens = preferredSimpleRefContinuityTokens(
            matchContext = matchContext,
            ageOutStaleRefContinuity = true,
        )
        val staleRefCandidate = rankedCandidates.firstOrNull { candidate ->
            val candidateTokens = normalizedRefTokens(candidate.streetRef).toSet()
            candidateTokens.isNotEmpty() && candidateTokens.any { token -> token in refTokens }
        }
        if (staleRefCandidate != null) {
            val staleRefOutsideAccuracyCap = staleRefCandidate.distanceM > horizontalAccuracyM
            val staleRefDistanceGapM = staleRefCandidate.distanceM - nameCandidate.distanceM
            if (
                !isUrbanSameRefReleaseSourceHighway(staleRefCandidate.highway) ||
                (!staleRefOutsideAccuracyCap && staleRefDistanceGapM < SIMPLE_SAME_REF_URBAN_RELEASE_MIN_DISTANCE_GAP_M)
            ) {
                return null
            }
        }

        return GuardedStreetNameContinuity(
            candidate = nameCandidate,
            tokens = activeStreetNameTokens,
            trace = MatchSelectionTrace(
                step = "simple_same_name_guard",
                detail = "kept same-name ${nameCandidate.wayId ?: "nil"} after ${matchContext.consecutiveNoRefMatchCount} no-ref matches best_m=${formatMetric(nameCandidate.distanceM)} stale_ref_m=${formatMetric(staleRefCandidate?.distanceM ?: Double.POSITIVE_INFINITY)} hacc_m=${formatMetric(horizontalAccuracyM)}",
            ),
        )
    }

    private fun preferredSimpleRefContinuityTokens(
        matchContext: WayMatchContext,
        ageOutStaleRefContinuity: Boolean,
    ): Set<String> {
        val activeStreetRefTokens = normalizedRefTokens(matchContext.activeStreetRef).toSet()
        if (activeStreetRefTokens.isNotEmpty()) {
            return activeStreetRefTokens
        }
        if (
            ageOutStaleRefContinuity &&
            matchContext.consecutiveNoRefMatchCount >= SIMPLE_STREET_NAME_FALLBACK_MIN_NO_REF_MATCHES
        ) {
            return emptySet()
        }
        if (matchContext.recentStreetRefs.isNotEmpty()) {
            return matchContext.recentStreetRefs.toSet()
        }
        return normalizedRefTokens(matchContext.preferredStreetRef).toSet()
    }

    private fun continuityTokens(
        candidate: WayCandidate,
        source: SimpleContinuityIdentitySource,
        useStreetNameFallbackContinuity: Boolean,
    ): Set<String> {
        val refTokens = normalizedRefTokens(candidate.streetRef).toSet()
        if (refTokens.isNotEmpty()) {
            return refTokens
        }
        if (useStreetNameFallbackContinuity && source == SimpleContinuityIdentitySource.STREET_NAME) {
            return normalizedStreetNameTokens(candidate.streetBaseName ?: candidate.streetName).toSet()
        }
        return emptySet()
    }

    private fun isUrbanSameRefReleaseSourceHighway(highway: String?): Boolean {
        return when (highway?.trim()?.lowercase(Locale.ROOT)) {
            "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified", "residential", "living_street" -> true
            else -> false
        }
    }

    private fun isUrbanSameRefReleaseTargetHighway(highway: String?): Boolean {
        return when (highway?.trim()?.lowercase(Locale.ROOT)) {
            "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified", "residential", "living_street" -> true
            else -> false
        }
    }

    private fun shouldEnableUrbanSameRefRelease(
        sameRefCandidate: WayCandidate,
        bestCandidate: WayCandidate,
    ): Boolean {
        if (
            !isUrbanSameRefReleaseSourceHighway(sameRefCandidate.highway) ||
            !isUrbanSameRefReleaseTargetHighway(bestCandidate.highway) ||
            bestCandidate.distanceM > SIMPLE_SAME_REF_URBAN_RELEASE_MAX_BEST_DISTANCE_M
        ) {
            return false
        }
        val distanceGapM = sameRefCandidate.distanceM - bestCandidate.distanceM
        return distanceGapM >= SIMPLE_SAME_REF_URBAN_RELEASE_MIN_DISTANCE_GAP_M
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
        if (usesSameRefBounceGate &&
            shouldSuppressImmediateSameRefBounce(transitionCandidate, preferredCandidate, matchContext, wayLinks, accuracyBufferM)
        ) {
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

    private fun isLegacyPortalTransitionCandidate(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double,
        requireSharedRef: Boolean,
    ): Boolean {
        val endpointThreshold = (if (requireSharedRef) TUNNEL_PORTAL_ENTRY_ENDPOINT_THRESHOLD_M else TUNNEL_PORTAL_EXIT_ENDPOINT_THRESHOLD_M) +
            accuracyBufferM
        if (candidate.endpointProximityM > endpointThreshold) {
            return false
        }
        val candidateWayId = normalizedWayId(candidate.wayId)
        if (requireSharedRef) {
            return wayLinks.available && isLinkedCandidate(candidateWayId, matchContext, wayLinks, requireSharedRef = true)
        }
        if (wayLinks.available && isLinkedCandidate(candidateWayId, matchContext, wayLinks)) {
            return true
        }
        return candidateWayId != null && candidateWayId in matchContext.recentWayIds
    }

    private fun isLegacyTunnelCandidateSelectable(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double,
    ): Boolean {
        if (!isTruthyOsmTag(candidate.tunnel)) {
            return true
        }
        val candidateWayId = normalizedWayId(candidate.wayId)
        val candidateRefTokens = normalizedRefTokens(candidate.streetRef).toSet()
        if (matchContext.isInTunnelMode) {
            if (candidateWayId != null && candidateWayId == matchContext.preferredWayId) {
                return true
            }
            if (candidateWayId != null && candidateWayId in matchContext.recentTunnelCandidateWayIds) {
                return true
            }
            if (candidateRefTokens.isNotEmpty() && candidateRefTokens.any { token -> token in matchContext.recentTunnelCandidateRefs }) {
                return true
            }
            return isLegacyPortalTransitionCandidate(
                candidate = candidate,
                matchContext = matchContext,
                wayLinks = wayLinks,
                accuracyBufferM = accuracyBufferM,
                requireSharedRef = true,
            )
        }
        if (candidateWayId != null && candidateWayId == matchContext.preferredWayId) {
            return true
        }
        if (isLegacyPortalTransitionCandidate(candidate, matchContext, wayLinks, accuracyBufferM, requireSharedRef = true)) {
            return true
        }
        if (matchContext.hadRecentGpsSignalLoss) {
            if (candidateWayId != null && candidateWayId in matchContext.recentTunnelCandidateWayIds) {
                return true
            }
            if (candidateRefTokens.isNotEmpty() && candidateRefTokens.any { token -> token in matchContext.recentTunnelCandidateRefs }) {
                return candidate.endpointProximityM <= TUNNEL_PORTAL_ENTRY_ENDPOINT_THRESHOLD_M + accuracyBufferM
            }
        }
        return false
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

    private fun shouldApplyAntiAbaHysteresis(
        candidate: WayCandidate,
        holdCandidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        corridorProgress: CorridorProgressContext,
        accuracyBufferM: Double,
    ): Boolean {
        val candidateWayId = normalizedWayId(candidate.wayId)
        val holdWayId = normalizedWayId(holdCandidate.wayId)
        val preferredWayId = matchContext.preferredWayId
        val priorWayId = matchContext.recentWayHistory.drop(1).firstOrNull()
        if (candidateWayId == null ||
            holdWayId == null ||
            preferredWayId == null ||
            priorWayId == null ||
            holdWayId != preferredWayId ||
            candidateWayId != priorWayId ||
            candidateWayId == holdWayId
        ) {
            return false
        }
        if (isTruthyOsmTag(candidate.tunnel) != isTruthyOsmTag(holdCandidate.tunnel)) {
            return false
        }

        val candidateCorridorState = candidateCorridorState(candidate, matchContext, wayLinks, corridorProgress)?.snapshot
        val holdCorridorState = candidateCorridorState(holdCandidate, matchContext, wayLinks, corridorProgress)?.snapshot
        val sameCorridor = sameCorridorState(candidateCorridorState, holdCorridorState) ||
            (candidateCorridorState == null && holdCorridorState == null)
        val candidateRefs = normalizedRefTokens(candidate.streetRef).toSet()
        val holdRefs = normalizedRefTokens(holdCandidate.streetRef).toSet()
        val sharesRef = candidateRefs.isNotEmpty() && candidateRefs.intersect(holdRefs).isNotEmpty()
        val linked = wayLinks.available && (
            areLinkedWays(candidateWayId, holdWayId, wayLinks) ||
                areSharedRefLinkedWays(candidateWayId, holdWayId, wayLinks)
            )
        if (!sameCorridor && !sharesRef && !linked) {
            return false
        }

        val requiredScoreImprovement = max(SAME_REF_BOUNCE_MIN_SCORE_IMPROVEMENT_M, accuracyBufferM)
        if (holdCandidate.score - candidate.score >= requiredScoreImprovement) {
            return false
        }
        val requiredDistanceImprovement = SAME_REF_BOUNCE_MIN_DISTANCE_IMPROVEMENT_M + min(accuracyBufferM * 0.25, 4.0)
        if (holdCandidate.distanceM - candidate.distanceM >= requiredDistanceImprovement) {
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
        if (!isTruthyOsmTag(tunnelCandidate.tunnel) ||
            isTruthyOsmTag(surfaceCandidate.tunnel) ||
            (!portalEligible && !hasCommittedTunnelApproachEvidence(tunnelCandidate, matchContext, horizontalAccuracyM, gpsSignalBars))
        ) {
            return false
        }
        val portalCommitScore = portalCommitProgressScore(tunnelCandidate, matchContext)
        val allowedSlack = max(TUNNEL_PORTAL_SCORE_SLACK_M, min(accuracyBufferM, 20.0)) +
            (portalCommitScore * TUNNEL_PORTAL_COMMIT_SLACK_BONUS_M)
        return tunnelCandidate.score <= surfaceCandidate.score + allowedSlack
    }

    private fun shouldKeepTunnelContinuity(
        tunnelCandidate: WayCandidate,
        surfaceCandidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        corridorProgress: CorridorProgressContext,
        pairContext: CorridorPairContext,
        accuracyBufferM: Double,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
    ): Boolean {
        if (!isTruthyOsmTag(tunnelCandidate.tunnel) || isTruthyOsmTag(surfaceCandidate.tunnel) || !matchContext.isInTunnelMode) {
            return false
        }
        if (
            isCorridorCandidateSelectable(
                candidate = surfaceCandidate,
                matchContext = matchContext,
                wayLinks = wayLinks,
                progressContext = corridorProgress,
                pairContext = pairContext,
                accuracyBufferM = accuracyBufferM,
                horizontalAccuracyM = horizontalAccuracyM,
                gpsSignalBars = gpsSignalBars,
            ) &&
            surfaceCandidate.score <= tunnelCandidate.score + TUNNEL_PORTAL_SCORE_SLACK_M
        ) {
            return false
        }
        return tunnelCandidate.score <= surfaceCandidate.score + max(TUNNEL_PORTAL_SCORE_SLACK_M, accuracyBufferM)
    }

    private fun corridorProgressInfos(
        candidate: WayCandidate,
        progressContext: CorridorProgressContext,
    ): List<CorridorProgressInfo> {
        if (!progressContext.available) {
            return emptyList()
        }
        return progressContext.byWayId[normalizedWayId(candidate.wayId)].orEmpty()
    }

    private fun corridorEntryDepthThresholdM(kind: String): Double {
        return when (kind) {
            "motorway" -> MOTORWAY_CORRIDOR_ENTRY_DEPTH_M
            else -> TUNNEL_CORRIDOR_ENTRY_DEPTH_M
        }
    }

    private fun corridorExitRemainingThresholdM(kind: String): Double {
        return when (kind) {
            "motorway" -> MOTORWAY_CORRIDOR_EXIT_REMAINING_M
            else -> TUNNEL_CORRIDOR_EXIT_REMAINING_M
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

    private fun corridorEntryProgressThresholdM(kind: String): Double {
        return when (kind) {
            "motorway" -> MOTORWAY_CORRIDOR_ENTRY_PROGRESS_M
            else -> TUNNEL_CORRIDOR_ENTRY_PROGRESS_M
        }
    }

    private fun corridorEntryProgressThresholdNodes(kind: String): Int {
        return when (kind) {
            "motorway" -> MOTORWAY_CORRIDOR_ENTRY_PROGRESS_NODES
            else -> TUNNEL_CORRIDOR_ENTRY_PROGRESS_NODES
        }
    }

    private fun corridorExitRemainingThresholdNodes(kind: String): Int {
        return when (kind) {
            "motorway" -> MOTORWAY_CORRIDOR_EXIT_REMAINING_NODES
            else -> TUNNEL_CORRIDOR_EXIT_REMAINING_NODES
        }
    }

    private fun corridorUsesNodeProgress(
        spanNodes: Int,
        thresholdNodes: Int,
    ): Boolean {
        return spanNodes >= thresholdNodes + 1
    }

    private fun corridorApproachProgressM(
        candidateCorridorState: CandidateCorridorState,
        matchContext: WayMatchContext,
    ): Double {
        val startDepthM = matchContext.approachCorridorStartDepthM ?: matchContext.approachCorridorState?.depthM ?: return 0.0
        return max(0.0, candidateCorridorState.snapshot.depthM - startDepthM)
    }

    private fun corridorApproachProgressNodes(
        candidateCorridorState: CandidateCorridorState,
        matchContext: WayMatchContext,
    ): Int {
        val startDepthNodes = matchContext.approachCorridorStartDepthNodes ?: matchContext.approachCorridorState?.depthNodes ?: return 0
        return max(0, candidateCorridorState.snapshot.depthNodes - startDepthNodes)
    }

    private fun corridorChainCommitScore(
        candidateCorridorState: CandidateCorridorState?,
        matchContext: WayMatchContext,
    ): Double {
        val corridorState = candidateCorridorState ?: return 0.0
        if (sameCorridorState(matchContext.activeCorridorState, corridorState.snapshot)) {
            return 1.0
        }
        val approachState = matchContext.approachCorridorState ?: return 0.0
        if (!sameCorridorState(approachState, corridorState.snapshot) ||
            matchContext.approachCorridorFixCount < corridorEntryFixCount(corridorState.snapshot.kind) ||
            corridorState.snapshot.depthM + CORRIDOR_PROGRESS_NOISE_TOLERANCE_M < approachState.depthM ||
            corridorState.snapshot.depthM < corridorEntryMinDepthM(corridorState.snapshot.kind)
        ) {
            return 0.0
        }
        val progressThresholdM = max(corridorEntryProgressThresholdM(corridorState.snapshot.kind), 1.0)
        val progressScore = min(1.0, max(0.0, corridorApproachProgressM(corridorState, matchContext) / progressThresholdM))
        val entryDepthWindowM = max(
            corridorEntryDepthThresholdM(corridorState.snapshot.kind) - corridorEntryMinDepthM(corridorState.snapshot.kind),
            1.0,
        )
        val depthScore = min(
            1.0,
            max(
                0.0,
                (corridorState.snapshot.depthM - corridorEntryMinDepthM(corridorState.snapshot.kind)) / entryDepthWindowM,
            ),
        )
        val fixScore = min(
            1.0,
            matchContext.approachCorridorFixCount.toDouble() /
                max(corridorEntryFixCount(corridorState.snapshot.kind) + 1, 1).toDouble(),
        )
        val nodeThreshold = corridorEntryProgressThresholdNodes(corridorState.snapshot.kind)
        val nodeScore = if (corridorUsesNodeProgress(corridorState.snapshot.spanNodes, nodeThreshold)) {
            min(1.0, corridorApproachProgressNodes(corridorState, matchContext).toDouble() / max(nodeThreshold, 1).toDouble())
        } else {
            progressScore
        }
        return max(
            progressScore,
            min(1.0, (0.45 * progressScore) + (0.25 * depthScore) + (0.20 * nodeScore) + (0.10 * fixScore)),
        )
    }

    private fun hasCommittedApproachCorridorEvidence(
        candidateCorridorState: CandidateCorridorState?,
        matchContext: WayMatchContext,
    ): Boolean {
        return corridorChainCommitScore(candidateCorridorState, matchContext) >= CORRIDOR_STATE_TUNNEL_CHAIN_COMMIT_MIN_SCORE
    }

    private fun hasPairedSurfaceApproachEvidence(
        candidateCorridorState: CandidateCorridorState?,
        matchContext: WayMatchContext,
        pairContext: CorridorPairContext,
    ): Boolean {
        val candidateSnapshot = candidateCorridorState?.snapshot ?: return !pairContext.available
        if (!pairContext.available) {
            return true
        }
        return matchContext.recentHypotheses.any { hypothesis ->
            val previousSnapshot = hypothesisCorridorSnapshot(hypothesis) ?: return@any false
            if (previousSnapshot.kind != "surface" && previousSnapshot.kind != "motorway_link") {
                return@any false
            }
            isPairedWithMainCorridor(previousSnapshot, candidateSnapshot, pairContext)
        }
    }

    private fun isContinuingApproachCorridorCandidate(
        candidateCorridorState: CandidateCorridorState?,
        matchContext: WayMatchContext,
    ): Boolean {
        val corridorState = candidateCorridorState ?: return false
        val approachState = matchContext.approachCorridorState ?: return false
        if (!sameCorridorState(approachState, corridorState.snapshot) ||
            corridorState.snapshot.depthM + CORRIDOR_PROGRESS_NOISE_TOLERANCE_M < approachState.depthM
        ) {
            return false
        }
        if (corridorState.progressDeltaNodes != null &&
            corridorState.progressDeltaNodes < -1 &&
            !corridorState.exitZone
        ) {
            return false
        }
        return true
    }

    private fun isTunnelCandidateSelectable(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        progressContext: CorridorProgressContext,
        pairContext: CorridorPairContext,
        accuracyBufferM: Double,
    ): Boolean {
        if (!isTruthyOsmTag(candidate.tunnel)) {
            return true
        }
        if (isLegacyTunnelCandidateSelectable(candidate, matchContext, wayLinks, accuracyBufferM)) {
            return true
        }
        val corridorCandidateState = candidateCorridorState(candidate, matchContext, wayLinks, progressContext) ?: return false
        if (sameCorridorState(matchContext.activeCorridorState, corridorCandidateState.snapshot)) {
            return true
        }
        if (!hasPairedSurfaceApproachEvidence(corridorCandidateState, matchContext, pairContext)) {
            return false
        }
        if (isContinuingApproachCorridorCandidate(corridorCandidateState, matchContext)) {
            return true
        }
        return hasCommittedApproachCorridorEvidence(corridorCandidateState, matchContext)
    }

    private fun corridorDepthM(
        candidate: WayCandidate,
        progressInfo: CorridorProgressInfo,
    ): Double? {
        val distanceToStartM = candidate.distanceToStartM ?: return null
        val distanceToEndM = candidate.distanceToEndM ?: return null
        val viaStart = progressInfo.startDepthM + distanceToStartM
        val viaEnd = progressInfo.endDepthM + distanceToEndM
        return min(viaStart, viaEnd)
    }

    private fun corridorDepthNodes(
        candidate: WayCandidate,
        progressInfo: CorridorProgressInfo,
    ): Int {
        val distanceToStartM = candidate.distanceToStartM
        val distanceToEndM = candidate.distanceToEndM
        if (distanceToStartM == null || distanceToEndM == null) {
            return min(progressInfo.startDepthNodes, progressInfo.endDepthNodes)
        }
        return if (distanceToStartM <= distanceToEndM) progressInfo.startDepthNodes else progressInfo.endDepthNodes
    }

    private fun corridorStateSnapshot(
        candidate: WayCandidate,
        info: CorridorProgressInfo,
    ): CorridorMatchState? {
        val depthM = corridorDepthM(candidate, info) ?: return null
        val depthNodes = corridorDepthNodes(candidate, info)
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

    private fun corridorPairRelationsForMain(
        snapshot: CorridorMatchState?,
        pairContext: CorridorPairContext,
    ): List<CorridorPairRelation> {
        if (!pairContext.available || snapshot == null) {
            return emptyList()
        }
        return pairContext.byMainKey[corridorPairKey(snapshot.kind, snapshot.corridorId, snapshot.sideNodeKey)].orEmpty()
    }

    private fun corridorPairRelationsForPaired(
        snapshot: CorridorMatchState?,
        pairContext: CorridorPairContext,
    ): List<CorridorPairRelation> {
        if (!pairContext.available || snapshot == null) {
            return emptyList()
        }
        return pairContext.byPairedKey[corridorPairKey(snapshot.kind, snapshot.corridorId, snapshot.sideNodeKey)].orEmpty()
    }

    private fun hypothesisCorridorSnapshot(hypothesis: WayMatchHypothesis): CorridorMatchState? {
        val corridorKind = hypothesis.corridorKind ?: return null
        val corridorId = hypothesis.corridorId ?: return null
        val sideNodeKey = hypothesis.corridorSideNodeKey ?: return null
        return CorridorMatchState(
            kind = corridorKind,
            corridorId = corridorId,
            sideNodeKey = sideNodeKey,
            depthM = 0.0,
            spanM = 0.0,
            depthNodes = 0,
            spanNodes = 0,
        )
    }

    private fun isPairedWithMainCorridor(
        pairedSnapshot: CorridorMatchState?,
        mainSnapshot: CorridorMatchState?,
        pairContext: CorridorPairContext,
        requireOppositeSide: Boolean = false,
    ): Boolean {
        val resolvedPairedSnapshot = pairedSnapshot ?: return false
        val resolvedMainSnapshot = mainSnapshot ?: return false
        return corridorPairRelationsForPaired(resolvedPairedSnapshot, pairContext).any { relation ->
            if (relation.corridorKind != resolvedMainSnapshot.kind || relation.corridorId != resolvedMainSnapshot.corridorId) {
                return@any false
            }
            if (requireOppositeSide) {
                relation.sideNodeKey != resolvedMainSnapshot.sideNodeKey
            } else {
                relation.sideNodeKey == resolvedMainSnapshot.sideNodeKey
            }
        }
    }

    private fun isMainCorridorPairedToCandidate(
        mainSnapshot: CorridorMatchState?,
        candidateSnapshot: CorridorMatchState?,
        pairContext: CorridorPairContext,
        requireOppositeSide: Boolean = false,
    ): Boolean {
        val resolvedMainSnapshot = mainSnapshot ?: return false
        val resolvedCandidateSnapshot = candidateSnapshot ?: return false
        return corridorPairRelationsForMain(resolvedMainSnapshot, pairContext).any { relation ->
            if (relation.pairedKind != resolvedCandidateSnapshot.kind || relation.pairedCorridorId != resolvedCandidateSnapshot.corridorId) {
                return@any false
            }
            if (requireOppositeSide) {
                relation.sideNodeKey != resolvedMainSnapshot.sideNodeKey &&
                    relation.sideNodeKey == resolvedCandidateSnapshot.sideNodeKey
            } else {
                relation.sideNodeKey == resolvedCandidateSnapshot.sideNodeKey
            }
        }
    }

    private fun candidateCorridorState(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        corridorProgress: CorridorProgressContext,
    ): CandidateCorridorState? {
        val infos = corridorProgressInfos(candidate, corridorProgress)
        if (infos.isEmpty()) {
            return null
        }
        matchContext.activeCorridorState?.let { activeState ->
            val activeCandidates = infos
                .filter {
                    it.kind == activeState.kind &&
                        it.corridorId == activeState.corridorId &&
                        it.sideNodeKey == activeState.sideNodeKey
                }
                .mapNotNull { info ->
                    val snapshot = corridorStateSnapshot(candidate, info) ?: return@mapNotNull null
                    CandidateCorridorState(
                        snapshot = snapshot,
                        entryZone = snapshot.depthM <= corridorEntryDepthThresholdM(snapshot.kind),
                        exitZone = isCorridorExitZone(snapshot),
                        progressDeltaM = snapshot.depthM - activeState.depthM,
                        progressDeltaNodes = snapshot.depthNodes - activeState.depthNodes,
                    )
                }
                .sortedWith(compareBy<CandidateCorridorState> { it.snapshot.depthM }.thenBy { it.snapshot.corridorId })
            if (activeCandidates.isNotEmpty()) {
                return activeCandidates.first()
            }
        }
        matchContext.approachCorridorState?.let { approachState ->
            val approachCandidates = infos
                .filter {
                    it.kind == approachState.kind &&
                        it.corridorId == approachState.corridorId &&
                        it.sideNodeKey == approachState.sideNodeKey
                }
                .mapNotNull { info ->
                    val snapshot = corridorStateSnapshot(candidate, info) ?: return@mapNotNull null
                    CandidateCorridorState(
                        snapshot = snapshot,
                        entryZone = snapshot.depthM <= corridorEntryDepthThresholdM(snapshot.kind),
                        exitZone = isCorridorExitZone(snapshot),
                        progressDeltaM = snapshot.depthM - approachState.depthM,
                        progressDeltaNodes = snapshot.depthNodes - approachState.depthNodes,
                    )
                }
                .sortedWith(compareBy<CandidateCorridorState> { it.snapshot.depthM }.thenBy { it.snapshot.corridorId })
            if (approachCandidates.isNotEmpty()) {
                return approachCandidates.first()
            }
        }
        val candidateWayId = normalizedWayId(candidate.wayId)
        if (candidateWayId != null && (candidateWayId == matchContext.preferredWayId || candidateWayId in matchContext.recentWayIds)) {
            val preferredCandidates = infos
                .mapNotNull { info ->
                    val snapshot = corridorStateSnapshot(candidate, info) ?: return@mapNotNull null
                    CandidateCorridorState(
                        snapshot = snapshot,
                        entryZone = snapshot.depthM <= corridorEntryDepthThresholdM(snapshot.kind),
                        exitZone = isCorridorExitZone(snapshot),
                    )
                }
                .sortedWith(
                    compareBy<CandidateCorridorState> { it.snapshot.depthM }
                        .thenBy { it.snapshot.depthNodes }
                        .thenBy { it.snapshot.corridorId },
                )
            if (preferredCandidates.isNotEmpty()) {
                return preferredCandidates.first()
            }
        }
        val anchor = corridorAnchor(matchContext) ?: return null
        if (candidateWayId == null) {
            return null
        }
        val sharedNodeKeys = wayLinks.sharedNodeKeys(anchor.wayId, candidateWayId)
        if (sharedNodeKeys.isEmpty()) {
            return null
        }
        return infos
            .filter { it.sideNodeKey in sharedNodeKeys }
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
        if (!sameCorridorState(approachState, candidateCorridorState.snapshot) ||
            matchContext.approachCorridorFixCount < corridorEntryFixCount(candidateCorridorState.snapshot.kind) ||
            candidateCorridorState.snapshot.depthM < corridorEntryMinDepthM(candidateCorridorState.snapshot.kind)
        ) {
            return false
        }
        if (corridorChainCommitScore(candidateCorridorState, matchContext) < CORRIDOR_STATE_TUNNEL_CHAIN_COMMIT_MIN_SCORE) {
            return false
        }
        return candidateCorridorState.snapshot.depthM + CORRIDOR_PROGRESS_NOISE_TOLERANCE_M >= approachState.depthM
    }

    private fun isActiveCorridorExitCandidate(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
    ): Boolean {
        val activeState = matchContext.activeCorridorState ?: return false
        val preferredWayId = matchContext.preferredWayId ?: return false
        val candidateWayId = normalizedWayId(candidate.wayId) ?: return false
        val remainingM = max(0.0, activeState.spanM - activeState.depthM)
        if (remainingM > corridorExitRemainingThresholdM(activeState.kind) + CORRIDOR_PROGRESS_NOISE_TOLERANCE_M) {
            return false
        }
        val remainingThresholdNodes = corridorExitRemainingThresholdNodes(activeState.kind)
        if (corridorUsesNodeProgress(activeState.spanNodes, remainingThresholdNodes)) {
            val remainingNodes = max(0, activeState.spanNodes - activeState.depthNodes)
            if (remainingNodes > remainingThresholdNodes) {
                return false
            }
        }
        val sharedNodeKeys = wayLinks.sharedNodeKeys(preferredWayId, candidateWayId)
        if (sharedNodeKeys.none { it != activeState.sideNodeKey }) {
            return false
        }
        return if (activeState.kind == "motorway") {
            candidate.highway.equals("motorway_link", ignoreCase = true)
        } else {
            !isTruthyOsmTag(candidate.tunnel)
        }
    }

    private fun isActiveCorridorEntryConnectorCandidate(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
    ): Boolean {
        val activeState = matchContext.activeCorridorState ?: return false
        if (activeState.kind != "motorway" ||
            activeState.depthM > corridorEntryDepthThresholdM(activeState.kind) + CORRIDOR_PROGRESS_NOISE_TOLERANCE_M
        ) {
            return false
        }
        val preferredWayId = matchContext.preferredWayId ?: return false
        val candidateWayId = normalizedWayId(candidate.wayId) ?: return false
        if (!candidate.highway.equals("motorway_link", ignoreCase = true)) {
            return false
        }
        val entryThresholdNodes = corridorEntryProgressThresholdNodes(activeState.kind)
        if (corridorUsesNodeProgress(activeState.spanNodes, entryThresholdNodes) &&
            activeState.depthNodes > entryThresholdNodes
        ) {
            return false
        }
        return wayLinks.sharedNodeKeys(preferredWayId, candidateWayId).contains(activeState.sideNodeKey)
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

    private fun signalQualityEvidence(
        matchContext: WayMatchContext,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
    ): SignalQualityEvidence {
        val horizontalAccuracyDeltaM = if (
            matchContext.tunnelApproachBaselineAccuracyM != null &&
            horizontalAccuracyM != null &&
            horizontalAccuracyM.isFinite()
        ) {
            max(0.0, horizontalAccuracyM - matchContext.tunnelApproachBaselineAccuracyM)
        } else {
            0.0
        }
        val gpsSignalBarsDrop = if (matchContext.tunnelApproachBaselineSignalBars != null && gpsSignalBars != null) {
            max(0, matchContext.tunnelApproachBaselineSignalBars - gpsSignalBars)
        } else {
            0
        }
        return SignalQualityEvidence(
            tunnelApproachFixCount = matchContext.tunnelApproachFixCount,
            horizontalAccuracyDeltaM = horizontalAccuracyDeltaM,
            gpsSignalBarsDrop = gpsSignalBarsDrop,
            hadRecentGpsSignalLoss = matchContext.hadRecentGpsSignalLoss,
        )
    }

    private fun shouldFallbackWhenCorridorGateEmptiesCandidates(matchContext: WayMatchContext): Boolean {
        return matchContext.hadRecentGpsSignalLoss
    }

    private fun isCorridorCandidateSelectable(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        progressContext: CorridorProgressContext,
        pairContext: CorridorPairContext,
        accuracyBufferM: Double,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
    ): Boolean {
        val tunnelSelectable = isTunnelCandidateSelectable(candidate, matchContext, wayLinks, progressContext, pairContext, accuracyBufferM)
        if (!tunnelSelectable) {
            return false
        }
        matchContext.activeCorridorState?.let { activeCorridorState ->
            val corridorState = candidateCorridorState(candidate, matchContext, wayLinks, progressContext)
            if (corridorState != null && sameCorridorState(activeCorridorState, corridorState.snapshot)) {
                if (corridorState.progressDeltaM != null &&
                    corridorState.progressDeltaM < -CORRIDOR_PROGRESS_NOISE_TOLERANCE_M &&
                    !corridorState.exitZone
                ) {
                    return false
                }
                if (corridorState.progressDeltaNodes != null &&
                    corridorUsesNodeProgress(activeCorridorState.spanNodes, corridorEntryProgressThresholdNodes(activeCorridorState.kind)) &&
                    corridorState.progressDeltaNodes < -1 &&
                    !corridorState.exitZone
                ) {
                    return false
                }
                return true
            }
            if (isActiveCorridorEntryConnectorCandidate(candidate, matchContext, wayLinks)) {
                return true
            }
            return isActiveCorridorExitCandidate(candidate, matchContext, wayLinks)
        }
        val anchor = corridorAnchor(matchContext) ?: return tunnelSelectable
        val candidateWayId = normalizedWayId(candidate.wayId)
        if (candidateWayId == anchor.wayId) {
            return true
        }
        val candidateState = corridorState(candidate)
        val corridorCandidateState = candidateCorridorState(candidate, matchContext, wayLinks, progressContext)
        return when (anchor.state to candidateState) {
            CorridorState.SURFACE to CorridorState.SURFACE -> true
            CorridorState.SURFACE to CorridorState.TUNNEL -> {
                isContinuingApproachCorridorCandidate(corridorCandidateState, matchContext) ||
                    hasCommittedApproachCorridorEvidence(corridorCandidateState, matchContext) ||
                    isPortalEligibleTunnelCandidate(candidate, matchContext, wayLinks, progressContext, accuracyBufferM) ||
                    hasCommittedTunnelApproachEvidence(candidate, matchContext, horizontalAccuracyM, gpsSignalBars)
            }
            CorridorState.SURFACE to CorridorState.MOTORWAY -> {
                corridorCandidateState != null && shouldTriggerActiveCorridorMode(corridorCandidateState, matchContext)
            }
            CorridorState.SURFACE to CorridorState.MOTORWAY_LINK -> {
                isMotorwayTransitionCandidate(anchor, candidate, wayLinks, accuracyBufferM)
            }
            CorridorState.TUNNEL to CorridorState.SURFACE -> {
                isTunnelPortalTransition(anchor, candidate, matchContext, wayLinks, accuracyBufferM, entry = false)
            }
            CorridorState.TUNNEL to CorridorState.TUNNEL -> {
                (candidateWayId != null && candidateWayId in matchContext.recentTunnelCandidateWayIds) ||
                    normalizedRefTokens(candidate.streetRef).any { token -> token in matchContext.recentTunnelCandidateRefs } ||
                    isEndpointLinkedTransition(anchor, candidate, wayLinks, TUNNEL_PORTAL_ENTRY_ENDPOINT_THRESHOLD_M, accuracyBufferM)
            }
            CorridorState.TUNNEL to CorridorState.MOTORWAY,
            CorridorState.TUNNEL to CorridorState.MOTORWAY_LINK -> false
            CorridorState.MOTORWAY to CorridorState.SURFACE,
            CorridorState.MOTORWAY to CorridorState.TUNNEL -> false
            CorridorState.MOTORWAY to CorridorState.MOTORWAY,
            CorridorState.MOTORWAY to CorridorState.MOTORWAY_LINK -> {
                isMotorwayTransitionCandidate(anchor, candidate, wayLinks, accuracyBufferM)
            }
            CorridorState.MOTORWAY_LINK to CorridorState.TUNNEL -> false
            CorridorState.MOTORWAY_LINK to CorridorState.MOTORWAY -> {
                (corridorCandidateState != null && shouldTriggerActiveCorridorMode(corridorCandidateState, matchContext)) ||
                    isMotorwayTransitionCandidate(anchor, candidate, wayLinks, accuracyBufferM)
            }
            CorridorState.MOTORWAY_LINK to CorridorState.SURFACE,
            CorridorState.MOTORWAY_LINK to CorridorState.MOTORWAY_LINK -> {
                isMotorwayTransitionCandidate(anchor, candidate, wayLinks, accuracyBufferM)
            }
            else -> false
        }
    }

    private fun isSurfacePortalContinuationCandidate(
        candidate: WayCandidate,
        anchor: CorridorAnchor,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double,
    ): Boolean {
        if (corridorState(candidate) != CorridorState.SURFACE || !hasSharedRefWithPreferred(candidate, matchContext)) {
            return false
        }
        return isEndpointLinkedTransition(anchor, candidate, wayLinks, TUNNEL_PORTAL_ENTRY_ENDPOINT_THRESHOLD_M, accuracyBufferM)
    }

    private fun suppressAmbiguousSurfaceToTunnelEntries(
        candidates: List<WayCandidate>,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        progressContext: CorridorProgressContext,
        accuracyBufferM: Double,
        horizontalAccuracyM: Double?,
        gpsSignalBars: Int?,
    ): List<WayCandidate> {
        val anchor = corridorAnchor(matchContext)
        if (!wayLinks.available || matchContext.hadRecentGpsSignalLoss || anchor == null || anchor.state != CorridorState.SURFACE) {
            return candidates
        }
        if (candidates.none { isSurfacePortalContinuationCandidate(it, anchor, matchContext, wayLinks, accuracyBufferM) }) {
            return candidates
        }
        return candidates.filter { candidate ->
            if (corridorState(candidate) != CorridorState.TUNNEL || !hasSharedRefWithPreferred(candidate, matchContext)) {
                return@filter true
            }
            if (matchesTunnelApproachCandidate(candidate, matchContext)) {
                return@filter true
            }
            val corridorState = candidateCorridorState(candidate, matchContext, wayLinks, progressContext)
            if (corridorState != null) {
                if (isContinuingApproachCorridorCandidate(corridorState, matchContext)) {
                    return@filter true
                }
                if (hasCommittedApproachCorridorEvidence(corridorState, matchContext)) {
                    return@filter true
                }
                if (shouldTriggerActiveCorridorMode(corridorState, matchContext)) {
                    return@filter true
                }
            }
            if (hasCommittedTunnelApproachEvidence(candidate, matchContext, horizontalAccuracyM, gpsSignalBars)) {
                return@filter true
            }
            !isTunnelPortalTransition(anchor, candidate, matchContext, wayLinks, accuracyBufferM, entry = true)
        }
    }

    private fun corridorAnchor(matchContext: WayMatchContext): CorridorAnchor? {
        if (matchContext.preferredWayId == null &&
            matchContext.preferredHighway == null &&
            !matchContext.isInTunnelMode
        ) {
            return null
        }
        return CorridorAnchor(
            wayId = matchContext.preferredWayId,
            highway = matchContext.preferredHighway,
            endpointProximityM = matchContext.preferredEndpointProximityM,
            isInTunnelMode = matchContext.isInTunnelMode,
        )
    }

    private fun corridorState(candidate: WayCandidate): CorridorState {
        return when {
            isTruthyOsmTag(candidate.tunnel) -> CorridorState.TUNNEL
            candidate.highway.equals("motorway", ignoreCase = true) -> CorridorState.MOTORWAY
            candidate.highway.equals("motorway_link", ignoreCase = true) -> CorridorState.MOTORWAY_LINK
            else -> CorridorState.SURFACE
        }
    }

    private fun isPortalEligibleTunnelCandidate(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
        wayLinks: WayLinksContext,
        corridorProgress: CorridorProgressContext,
        accuracyBufferM: Double,
    ): Boolean {
        val anchor = corridorAnchor(matchContext)
        if (!isTruthyOsmTag(candidate.tunnel) ||
            !wayLinks.available ||
            anchor == null ||
            anchor.state != CorridorState.SURFACE
        ) {
            return false
        }
        if (!isTunnelPortalTransition(anchor, candidate, matchContext, wayLinks, accuracyBufferM, entry = true)) {
            return false
        }
        val corridorState = candidateCorridorState(candidate, matchContext, wayLinks, corridorProgress)
        if (corridorState != null &&
            (corridorState.snapshot.kind != "tunnel" || !corridorState.entryZone)
        ) {
            return false
        }
        val motionScore = portalMotionProgressScore(candidate, matchContext)
        val endpointDistance = corridorState?.snapshot?.depthM ?: candidate.endpointProximityM
        val portalDistanceThreshold = TUNNEL_PORTAL_ENTRY_ENDPOINT_THRESHOLD_M + accuracyBufferM
        if (!endpointDistance.isFinite() || endpointDistance > portalDistanceThreshold) {
            return false
        }
        val directSnapThreshold = max(4.0, min(accuracyBufferM * 0.35, 10.0))
        if (endpointDistance <= directSnapThreshold) {
            return if (matchContext.recentFixes.isEmpty()) {
                true
            } else {
                motionScore >= TUNNEL_PORTAL_DIRECT_SNAP_MOTION_MIN_SCORE
            }
        }
        return if (matchContext.recentFixes.isEmpty()) {
            true
        } else {
            motionScore >= 0.25
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
        return candidateRefs.any { token -> token in matchContext.recentTunnelApproachRefs }
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

    private fun portalCommitProgressScore(
        candidate: WayCandidate,
        matchContext: WayMatchContext,
    ): Double {
        val metrics = portalMotionMetrics(candidate, matchContext) ?: return 0.0
        if (matchContext.tunnelApproachFixCount < max(TUNNEL_APPROACH_MIN_FIX_COUNT + 1, 3) ||
            metrics.alignmentScore < 0.35 ||
            metrics.currentPortalDistanceM < 4.0
        ) {
            return 0.0
        }
        val interiorComponent = max(0.0, min(metrics.bestInteriorProgressDeltaM / 12.0, 1.0))
        if (interiorComponent <= 0.0) {
            return 0.0
        }
        return (interiorComponent * 0.6) + (metrics.alignmentScore * 0.25) + (metrics.proximityScore * 0.15)
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

    private fun isMotorwayTransitionCandidate(
        anchor: CorridorAnchor,
        candidate: WayCandidate,
        wayLinks: WayLinksContext,
        accuracyBufferM: Double,
    ): Boolean {
        return isEndpointLinkedTransition(
            anchor = anchor,
            candidate = candidate,
            wayLinks = wayLinks,
            endpointThresholdM = MOTORWAY_TRANSITION_ENDPOINT_THRESHOLD_M,
            accuracyBufferM = accuracyBufferM,
        )
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
        return candidateRefs.isNotEmpty() && candidateRefs.any { token -> token in matchContext.recentStreetRefs }
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
              AND b.admin_level IN (6, 8, 9)
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
        val containing = mutableListOf<ContainingAdminBoundary>()
        boundaries.forEach { boundary ->
            val name = boundary.name?.trim().orEmpty()
            if (name.isEmpty()) {
                return@forEach
            }
            if (boundaryContainsPoint(boundaryRowId = boundary.rowId, lon = lon, lat = lat)) {
                val bboxArea = max(boundary.maxLon - boundary.minLon, 0.0) * max(boundary.maxLat - boundary.minLat, 0.0)
                containing += ContainingAdminBoundary(
                    adminLevel = boundary.adminLevel,
                    bboxArea = bboxArea,
                    name = name,
                )
            }
        }
        if (containing.isNotEmpty()) {
            val adminDisplay = buildAdminCityDisplay(containing)
            return CityContext(
                insideCity = true,
                cityName = adminDisplay.cityName,
                cityPlaceName = adminDisplay.cityPlaceName,
                cityDistrictName = adminDisplay.cityDistrictName,
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
                    cityPlaceName = best.third,
                    cityDistrictName = null,
                    citySource = "place_fallback",
                    candidateBoundaries = boundaries.size,
                    placeCandidates = placeCandidates.size,
                )
            }
        }

        return CityContext(
            insideCity = false,
            cityName = null,
            cityPlaceName = null,
            cityDistrictName = null,
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
        val containingAdminExact = mutableListOf<ContainingAdminBoundary>()
        val containingAdminBBox = mutableListOf<ContainingAdminBoundary>()
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
                val adminBoundary = ContainingAdminBoundary(
                    adminLevel = adminLevel ?: return@forEach,
                    bboxArea = areaSize,
                    name = name,
                )
                if (isClosedAreaRing(area.points) && pointInRing(lon = lon, lat = lat, ring = area.points)) {
                    containingAdminExact.add(adminBoundary)
                } else {
                    containingAdminBBox.add(adminBoundary)
                }
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

        if (containingAdminExact.isNotEmpty()) {
            val adminDisplay = buildAdminCityDisplay(containingAdminExact)
            return CityContext(
                insideCity = true,
                cityName = adminDisplay.cityName,
                cityPlaceName = adminDisplay.cityPlaceName,
                cityDistrictName = adminDisplay.cityDistrictName,
                citySource = "admin_polygon",
                candidateBoundaries = containingAdminExact.size,
                placeCandidates = nearbyPlaces.size,
            )
        }
        if (containingAdminBBox.isNotEmpty()) {
            val adminDisplay = buildAdminCityDisplay(containingAdminBBox)
            return CityContext(
                insideCity = true,
                cityName = adminDisplay.cityName,
                cityPlaceName = adminDisplay.cityPlaceName,
                cityDistrictName = adminDisplay.cityDistrictName,
                citySource = "admin_bbox",
                candidateBoundaries = containingAdminBBox.size,
                placeCandidates = nearbyPlaces.size,
            )
        }
        selectContainingPlace(containingPlaces)?.let { best ->
            return CityContext(
                insideCity = true,
                cityName = best.third,
                cityPlaceName = best.third,
                cityDistrictName = null,
                citySource = "place_bbox",
                candidateBoundaries = 0,
                placeCandidates = nearbyPlaces.size,
            )
        }
        selectNearestPlaceFallback(nearbyPlaces)?.let { best ->
            return CityContext(
                insideCity = false,
                cityName = best.third,
                cityPlaceName = best.third,
                cityDistrictName = null,
                citySource = "place_nearest",
                candidateBoundaries = 0,
                placeCandidates = nearbyPlaces.size,
            )
        }
        return CityContext(
            insideCity = false,
            cityName = null,
            cityPlaceName = null,
            cityDistrictName = null,
            citySource = "bbox_no_match",
            candidateBoundaries = 0,
            placeCandidates = 0,
        )
    }

    private fun preferredCityContext(
        primary: CityContext,
        fallback: CityContext,
    ): CityContext {
        val primaryScore = cityContextResolutionScore(primary)
        val fallbackScore = cityContextResolutionScore(fallback)
        return if (fallbackScore > primaryScore) fallback else primary
    }

    private fun cityContextResolutionScore(context: CityContext): Int {
        val baseScore = when (context.citySource) {
            "admin_polygon" -> 50
            "admin_bbox" -> 40
            "place_bbox" -> 30
            "place_fallback", "place_nearest" -> 20
            else -> 0
        }
        val cityNameBonus = if (!context.cityName.isNullOrBlank()) 2 else 0
        val districtBonus = if (!context.cityDistrictName.isNullOrBlank()) 1 else 0
        return baseScore + cityNameBonus + districtBonus
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
        private const val BASELINE_PREFERRED_DISTANCE_SLACK_M = 7.0
        private const val BASELINE_SAME_REF_DISTANCE_SLACK_M = 5.0
        private const val BASELINE_TURN_TRANSITION_MAX_SPEED_KMH = 36.0
        private const val BASELINE_TURN_DISTANCE_SLACK_M = 10.0
        private const val BASELINE_TUNNEL_EXIT_ENDPOINT_THRESHOLD_M = 28.0
        private const val BASELINE_MOTORWAY_GATE_ENDPOINT_THRESHOLD_M = 42.0
        private const val PREFERRED_WAY_SCORE_SLACK_M = 18.0
        private const val PREFERRED_WAY_DISTANCE_MULTIPLIER = 1.9
        private const val PREFERRED_WAY_DISTANCE_FLOOR_M = 85.0
        private const val SAME_REF_BOUNCE_PENALTY_M = 9.0
        private const val SAME_REF_SCORE_SLACK_M = 11.0
        private const val SAME_REF_DISTANCE_MULTIPLIER = 1.55
        private const val SAME_REF_DISTANCE_FLOOR_M = 72.0
        private const val SAME_REF_BOUNCE_MIN_SCORE_IMPROVEMENT_M = 14.0
        private const val SAME_REF_BOUNCE_MIN_DISTANCE_IMPROVEMENT_M = 8.0
        private const val SIMPLE_SAME_REF_HOLD_SPEED_THRESHOLD_KMH = 30.0
        private const val SIMPLE_SAME_REF_URBAN_RELEASE_MAX_SPEED_KMH = 34.0
        private const val SIMPLE_SAME_REF_URBAN_RELEASE_MAX_ACCURACY_M = 10.0
        private const val SIMPLE_SAME_REF_URBAN_RELEASE_MAX_BEST_DISTANCE_M = 2.5
        private const val SIMPLE_SAME_REF_URBAN_RELEASE_MIN_DISTANCE_GAP_M = 25.0
        private const val SIMPLE_SAME_REF_URBAN_RELEASE_REQUIRED_STREAK = 2
        private const val SIMPLE_STREET_NAME_FALLBACK_MIN_NO_REF_MATCHES = 2
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
        private const val TUNNEL_CORRIDOR_ENTRY_PROGRESS_NODES = 1
        private const val TUNNEL_CORRIDOR_EXIT_REMAINING_NODES = 1
        private const val MOTORWAY_CORRIDOR_ENTRY_DEPTH_M = 150.0
        private const val MOTORWAY_CORRIDOR_EXIT_REMAINING_M = 160.0
        private const val MOTORWAY_CORRIDOR_ENTRY_MIN_DEPTH_M = 30.0
        private const val MOTORWAY_CORRIDOR_ENTRY_FIX_COUNT = 2
        private const val MOTORWAY_CORRIDOR_ENTRY_PROGRESS_NODES = 1
        private const val MOTORWAY_CORRIDOR_EXIT_REMAINING_NODES = 1
        private const val MOTORWAY_TRANSITION_ENDPOINT_THRESHOLD_M = 36.0
        private const val TUNNEL_CORRIDOR_ENTRY_PROGRESS_M = 16.0
        private const val MOTORWAY_CORRIDOR_ENTRY_PROGRESS_M = 42.0
        private const val CORRIDOR_PROGRESS_NOISE_TOLERANCE_M = 12.0
        private const val CORRIDOR_STATE_ILLEGAL_PENALTY_M = 80.0
        private const val CORRIDOR_STATE_EXPECTED_TRANSITION_PENALTY_M = 2.0
        private const val CORRIDOR_STATE_PERSISTENCE_PENALTY_M = 0.5
        private const val CORRIDOR_STATE_REENTRY_PENALTY_M = 8.0
        private const val CORRIDOR_STATE_TUNNEL_SIGNAL_REWARD_M = 8.0
        private const val CORRIDOR_STATE_TUNNEL_PERSISTENCE_REWARD_M = 6.0
        private const val CORRIDOR_STATE_TUNNEL_CHAIN_REWARD_M = 10.0
        private const val CORRIDOR_STATE_MOTORWAY_REWARD_M = 4.0
        private const val CORRIDOR_STATE_TUNNEL_DIRECT_COMMIT_MIN_SCORE = 0.75
        private const val CORRIDOR_STATE_TUNNEL_OUTPUT_MIN_SCORE = 0.5
        private const val CORRIDOR_STATE_TUNNEL_CHAIN_COMMIT_MIN_SCORE = 0.7
        private const val CORRIDOR_STATE_TUNNEL_CHAIN_SLACK_BONUS_M = 6.0
        private const val CORRIDOR_STATE_TUNNEL_OUTPUT_SCORE_SLACK_M = 8.0
        private const val CORRIDOR_STATE_MOTORWAY_OUTPUT_SCORE_SLACK_M = 6.0
        private val inCityHighwayClasses = setOf("residential", "service", "crossing", "living_street")

        fun deriveSpeedLimitKmh(
            maxspeed: String?,
            maxspeedType: String?,
            sourceMaxspeed: String?,
            highway: String?,
        ): Int? {
            return deriveSpeedLimitWithSource(maxspeed, maxspeedType, sourceMaxspeed, highway).speed
        }

        internal fun germanLowSpeedLimitImpliesInsideCity(
            countryCode: String?,
            speedKmh: Int?,
        ): Boolean {
            return normalizedCountryCode(countryCode) == "DEU" &&
                speedKmh != null &&
                speedKmh > 0 &&
                speedKmh < 50
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

        private fun normalizedCountryCode(raw: String?): String? {
            val code = raw?.trim()?.uppercase(Locale.US) ?: return null
            return code.takeIf { it.length == 3 }
        }

        private fun inferCountryCodeFromDbPath(dbPath: String): String? {
            val fileName = dbPath.substringAfterLast('/').uppercase(Locale.US)
            if (fileName.length < 3) {
                return null
            }
            val prefix = fileName.take(3)
            return prefix.takeIf { it.all(Char::isLetter) }
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
                9 -> 0
                8 -> 1
                6 -> 2
                else -> null
            }
        }

        private fun selectAdminBoundaryName(
            boundaries: List<ContainingAdminBoundary>,
            adminLevel: Int,
        ): String? {
            return boundaries
                .filter { it.adminLevel == adminLevel }
                .sortedWith(compareBy<ContainingAdminBoundary> { it.bboxArea }.thenBy { it.name })
                .firstOrNull()
                ?.name
        }

        private fun buildAdminCityDisplay(
            boundaries: List<ContainingAdminBoundary>,
        ): AdminCityDisplay {
            val districtName = selectAdminBoundaryName(boundaries, adminLevel = 6)
            val adminLevel8Name = selectAdminBoundaryName(boundaries, adminLevel = 8)
            val adminLevel9Name = selectAdminBoundaryName(boundaries, adminLevel = 9)
            val placeName = when {
                adminLevel9Name != null && adminLevel8Name != null && !sameAdminName(adminLevel8Name, adminLevel9Name) -> {
                    "$adminLevel8Name - $adminLevel9Name"
                }
                adminLevel9Name != null -> adminLevel9Name
                adminLevel8Name != null -> adminLevel8Name
                else -> districtName
            }
            if (placeName == null) {
                return AdminCityDisplay(
                    cityName = null,
                    cityPlaceName = null,
                    cityDistrictName = null,
                )
            }
            val districtLine = districtName?.takeUnless { sameAdminName(placeName, it) }
            return AdminCityDisplay(
                cityName = districtLine?.let { "$placeName ($it)" } ?: placeName,
                cityPlaceName = placeName,
                cityDistrictName = districtLine,
            )
        }

        private fun sameAdminName(
            left: String,
            right: String,
        ): Boolean = left.trim().equals(right.trim(), ignoreCase = true)

        private fun isClosedAreaRing(points: List<LonLatPoint>): Boolean {
            if (points.size < 4) {
                return false
            }
            val first = points.first()
            val last = points.last()
            return abs(first.lon - last.lon) <= 1e-9 && abs(first.lat - last.lat) <= 1e-9
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

        private fun normalizedStreetNameTokens(raw: String?): List<String> {
            val normalized = raw
                ?.trim()
                ?.uppercase()
                ?.replace(Regex("[^A-Z0-9]+"), "")
                .orEmpty()
            return if (normalized.isEmpty()) emptyList() else listOf(normalized)
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
    val cityPlaceName: String?,
    val cityDistrictName: String?,
    val citySource: String?,
    val candidateBoundaries: Int,
    val placeCandidates: Int,
)

private data class AdminCityDisplay(
    val cityName: String?,
    val cityPlaceName: String?,
    val cityDistrictName: String?,
)

private data class ContainingAdminBoundary(
    val adminLevel: Int,
    val bboxArea: Double,
    val name: String,
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

private data class NonCorridorMatcherSelection(
    val selected: WayCandidate? = null,
    val traceRankedCandidates: List<TraceRankedCandidate> = emptyList(),
    val selectionTrace: List<MatchSelectionTrace> = emptyList(),
)

private data class MiniHMMSelection(
    val selectedCandidate: WayCandidate? = null,
    val selectedCorridorState: CorridorSequenceState? = null,
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

private enum class CorridorState(val wireName: String) {
    SURFACE("surface"),
    TUNNEL("tunnel"),
    MOTORWAY("motorway"),
    MOTORWAY_LINK("motorwayLink"),
}

private enum class CorridorSequenceState(val wireName: String) {
    SURFACE("surface"),
    TUNNEL_PORTAL("tunnelPortal"),
    TUNNEL_INSIDE("tunnelInside"),
    TUNNEL_EXIT("tunnelExit"),
    MOTORWAY_PORTAL("motorwayPortal"),
    MOTORWAY_INSIDE("motorwayInside"),
    MOTORWAY_EXIT("motorwayExit"),
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
    val wayId: String?,
    val highway: String?,
    val endpointProximityM: Double?,
    val isInTunnelMode: Boolean,
) {
    val state: CorridorState
        get() = when {
            isInTunnelMode -> CorridorState.TUNNEL
            highway.equals("motorway", ignoreCase = true) -> CorridorState.MOTORWAY
            highway.equals("motorway_link", ignoreCase = true) -> CorridorState.MOTORWAY_LINK
            else -> CorridorState.SURFACE
        }
}

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

private data class CorridorPairRelation(
    val corridorKind: String,
    val corridorId: Int,
    val sideNodeKey: String,
    val pairedKind: String,
    val pairedCorridorId: Int,
)

private data class CorridorPairContext(
    val available: Boolean,
    val byMainKey: Map<String, List<CorridorPairRelation>> = emptyMap(),
    val byPairedKey: Map<String, List<CorridorPairRelation>> = emptyMap(),
)

private data class CandidateCorridorState(
    val snapshot: CorridorMatchState,
    val entryZone: Boolean,
    val exitZone: Boolean,
    val progressDeltaM: Double? = null,
    val progressDeltaNodes: Int? = null,
)

private data class SignalQualityEvidence(
    val tunnelApproachFixCount: Int,
    val horizontalAccuracyDeltaM: Double,
    val gpsSignalBarsDrop: Int,
    val hadRecentGpsSignalLoss: Boolean,
) {
    val tunnelScore: Double
        get() {
            if (hadRecentGpsSignalLoss) {
                return 1.0
            }
            if (tunnelApproachFixCount < 2) {
                return 0.0
            }
            val accuracyComponent = min(max(horizontalAccuracyDeltaM / 8.0, 0.0), 1.0)
            val barsComponent = min(max(gpsSignalBarsDrop.toDouble() / 1.0, 0.0), 1.0)
            return min(1.0, max(accuracyComponent, barsComponent))
        }
}

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
