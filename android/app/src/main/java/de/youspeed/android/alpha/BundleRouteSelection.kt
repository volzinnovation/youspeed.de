package de.youspeed.android.alpha

data class BundleRouteProbe(
    val route: LocalBundleRoute,
    val hasWayMatch: Boolean,
    val hasSpeedMatch: Boolean,
    val nearestCandidateDistanceM: Double?,
    val nearestSpeedCandidateDistanceM: Double?,
) {
    val score: Double
        get() = (if (hasWayMatch) 1_000.0 else 0.0) +
            (if (hasSpeedMatch) 500.0 else 0.0) +
            (nearestCandidateDistanceM?.takeIf { it.isFinite() }?.let { (250.0 - it).coerceAtLeast(0.0) } ?: 0.0) +
            (nearestSpeedCandidateDistanceM?.takeIf { it.isFinite() }?.let { (250.0 - it).coerceAtLeast(0.0) } ?: 0.0)
}

/**
 * The identity used to decide whether a traffic-sign generation really needs
 * to be invalidated. A missing digest is unknown metadata, not evidence that
 * the selected database changed.
 */
data class BundleRouteIdentity(
    val dbPath: String?,
    val bundleVersion: String?,
    val countryCode: String?,
    val dbSha256: String?,
) {
    fun differsFrom(previous: BundleRouteIdentity): Boolean =
        dbPath != previous.dbPath ||
            bundleVersion != previous.bundleVersion ||
            countryCode != previous.countryCode ||
            (dbSha256 != null && previous.dbSha256 != null &&
                !dbSha256.equals(previous.dbSha256, ignoreCase = true))
}

object BundleRouteSelection {
    const val SWITCH_SCORE_MARGIN = 120.0

    fun choose(probes: List<BundleRouteProbe>, currentDBPath: String?): LocalBundleRoute? {
        if (probes.isEmpty()) return null
        val best = probes.sortedWith(
            compareByDescending<BundleRouteProbe> { it.score }
                .thenBy { it.route.region },
        ).first()
        val current = currentDBPath?.let { path -> probes.firstOrNull { it.route.dbPath == path } }
            ?: return best.route
        if (best.route.dbPath == current.route.dbPath) return current.route
        if ((!current.hasWayMatch && best.hasWayMatch) ||
            (current.hasWayMatch && !current.hasSpeedMatch && best.hasSpeedMatch)
        ) return best.route
        return if (best.score >= current.score + SWITCH_SCORE_MARGIN) best.route else current.route
    }
}
