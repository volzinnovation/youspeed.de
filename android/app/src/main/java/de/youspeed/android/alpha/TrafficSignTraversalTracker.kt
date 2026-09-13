package de.youspeed.android.alpha

/**
 * Android counterpart of the iPhone traffic-sign traversal tracker.
 *
 * A new OSM way does not automatically mean a new physical drive scope. If
 * adjacent matched ways share a route-continuity group, delayed camera
 * evidence may safely remain in the same traversal epoch. A way change without
 * that evidence starts a new epoch and invalidates the old camera scope.
 */
internal data class TrafficSignTraversalUpdate(
    val epoch: Long,
    val continuouslyRelated: Boolean,
)

internal class TrafficSignTraversalTracker {
    var epoch: Long = 1L
        private set

    private var previousWayId: String? = null
    private var previousDirection = TrafficSignTravelDirection.UNKNOWN
    private var previousContinuityGroups: Set<Long> = emptySet()

    fun reset() {
        epoch += 1L
        previousWayId = null
        previousDirection = TrafficSignTravelDirection.UNKNOWN
        previousContinuityGroups = emptySet()
    }

    fun update(
        wayId: String?,
        direction: TrafficSignTravelDirection,
        continuityAvailable: Boolean,
        continuityGroups: Set<Long>,
    ): TrafficSignTraversalUpdate {
        val normalizedWayId = normalizeWayId(wayId) ?: return TrafficSignTraversalUpdate(
            epoch = epoch,
            continuouslyRelated = false,
        )
        val normalizedGroups = continuityGroups.filter { it > 0L }.toSet()
        val previousWay = previousWayId

        if (previousWay == null) {
            previousWayId = normalizedWayId
            previousDirection = direction
            previousContinuityGroups = normalizedGroups.takeIf { continuityAvailable }.orEmpty()
            return TrafficSignTraversalUpdate(epoch, continuouslyRelated = true)
        }

        if (previousWay == normalizedWayId &&
            previousDirection != TrafficSignTravelDirection.UNKNOWN &&
            direction != TrafficSignTravelDirection.UNKNOWN &&
            previousDirection != direction
        ) {
            epoch += 1L
            previousWayId = normalizedWayId
            previousDirection = direction
            previousContinuityGroups = normalizedGroups.takeIf { continuityAvailable }.orEmpty()
            return TrafficSignTraversalUpdate(epoch, continuouslyRelated = false)
        }

        if (previousWay == normalizedWayId) {
            previousDirection = direction
            if (continuityAvailable && normalizedGroups.isNotEmpty()) {
                previousContinuityGroups = normalizedGroups
            }
            return TrafficSignTraversalUpdate(epoch, continuouslyRelated = true)
        }

        val sharedGroups = previousContinuityGroups.intersect(normalizedGroups)
        if (continuityAvailable && previousContinuityGroups.isNotEmpty() && sharedGroups.isNotEmpty()) {
            previousWayId = normalizedWayId
            previousDirection = direction
            previousContinuityGroups = normalizedGroups
            return TrafficSignTraversalUpdate(epoch, continuouslyRelated = true)
        }

        epoch += 1L
        previousWayId = normalizedWayId
        previousDirection = direction
        previousContinuityGroups = normalizedGroups.takeIf { continuityAvailable }.orEmpty()
        return TrafficSignTraversalUpdate(epoch, continuouslyRelated = false)
    }

    private fun normalizeWayId(raw: String?): String? = raw
        ?.trim()
        ?.takeIf { it.isNotEmpty() }
        ?.let { value ->
            value.toLongOrNull()?.toString()
                ?: value.toDoubleOrNull()
                    ?.takeIf { it.isFinite() && it % 1.0 == 0.0 }
                    ?.toLong()
                    ?.toString()
                ?: value
        }
}
