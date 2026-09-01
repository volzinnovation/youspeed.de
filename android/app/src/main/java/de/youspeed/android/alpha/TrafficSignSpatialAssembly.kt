package de.youspeed.android.alpha

import kotlin.math.abs

data class TrafficSignAssembly(
    val assemblyId: String,
    val primary: TrafficSignDetection,
    val supplementaryPlates: List<TrafficSignDetection>,
    val restrictions: List<TrafficSignRestriction>,
    val conditionState: TrafficSignConditionState,
)

data class TrafficSignAssemblyBatch(
    val assemblies: List<TrafficSignAssembly>,
    val unassignedSupplementaryPlates: List<TrafficSignDetection>,
)

data class TrafficSignAssemblyGeometry(
    val maximumVerticalGap: Double = 0.18,
    val permittedBoxOverlap: Double = 0.03,
    val minimumHorizontalOverlapFraction: Double = 0.25,
) {
    init {
        require(maximumVerticalGap.isFinite() && maximumVerticalGap in 0.0..1.0)
        require(permittedBoxOverlap.isFinite() && permittedBoxOverlap in 0.0..1.0)
        require(minimumHorizontalOverlapFraction.isFinite() && minimumHorizontalOverlapFraction in 0.0..1.0)
    }
}

/**
 * Links white supplementary plates to the closest plausible primary sign
 * above them. The result carries typed restrictions on the primary candidate,
 * while keeping each physical sign/plate as a separate detection object.
 */
object TrafficSignSpatialAssembly {
    fun assemble(
        detections: List<TrafficSignDetection>,
        modelPack: TrafficSignModelPack,
        assemblyIdPrefix: String,
        geometry: TrafficSignAssemblyGeometry = TrafficSignAssemblyGeometry(),
    ): TrafficSignAssemblyBatch {
        require(assemblyIdPrefix.isNotBlank()) { "Assembly ID prefix must not be blank" }
        val classified = detections.mapNotNull { detection ->
            modelPack.classFor(detection.candidate.rawClassId)?.let { mapping -> Classified(detection, mapping) }
        }
        val primaries = classified.filter { it.mapping.signRole == TrafficSignRole.PRIMARY_SIGN }
        val plates = classified.filter { it.mapping.signRole == TrafficSignRole.SUPPLEMENTARY_PLATE }
        val assignments = mutableMapOf<Int, MutableList<Classified>>()
        val unassigned = mutableListOf<TrafficSignDetection>()

        plates.forEach { plate ->
            val primaryIndex = primaries.indices
                .mapNotNull { index ->
                    associationCost(primaries[index].detection, plate.detection, geometry)?.let { cost -> index to cost }
                }
                .minWithOrNull(compareBy<Pair<Int, Double>> { it.second }.thenBy { it.first })
                ?.first
            if (primaryIndex == null) {
                unassigned += plate.detection
            } else {
                assignments.getOrPut(primaryIndex, ::mutableListOf) += plate
            }
        }

        val assemblies = primaries.mapIndexed { index, primary ->
            val assemblyId = "$assemblyIdPrefix-assembly-${index + 1}"
            val assignedPlates = assignments[index]
                .orEmpty()
                .sortedBy { it.detection.candidate.boundingBox.y }
            val restrictions = assignedPlates.map { requireNotNull(it.mapping.restriction) }.distinct()
            val conditionState = if (assignedPlates.isEmpty()) {
                // A recognized supplementary plate that narrowly misses the
                // association gate is still evidence that a visible numeric
                // sign may be conditional. Fail closed until a later frame
                // resolves the plate-to-primary relationship.
                if (unassigned.isEmpty()) {
                    TrafficSignConditionState.NONE
                } else {
                    TrafficSignConditionState.UNRESOLVED
                }
            } else if (restrictions.any { it.kind == TrafficSignRestrictionKind.UNKNOWN }) {
                TrafficSignConditionState.UNRESOLVED
            } else {
                TrafficSignConditionState.RESOLVED
            }
            val decoratedPlates = assignedPlates.map { classifiedPlate ->
                classifiedPlate.detection.copy(
                    candidate = classifiedPlate.detection.candidate.copy(
                        assemblyId = assemblyId,
                        conditionState = conditionState,
                        restrictions = listOf(requireNotNull(classifiedPlate.mapping.restriction)),
                    ),
                )
            }
            val decoratedPrimary = primary.detection.copy(
                candidate = primary.detection.candidate.copy(
                    assemblyId = assemblyId,
                    conditionState = conditionState,
                    restrictions = restrictions,
                ),
            )
            TrafficSignAssembly(
                assemblyId = assemblyId,
                primary = decoratedPrimary,
                supplementaryPlates = decoratedPlates,
                restrictions = restrictions,
                conditionState = conditionState,
            )
        }

        return TrafficSignAssemblyBatch(
            assemblies = assemblies,
            unassignedSupplementaryPlates = unassigned,
        )
    }

    private fun associationCost(
        primary: TrafficSignDetection,
        plate: TrafficSignDetection,
        geometry: TrafficSignAssemblyGeometry,
    ): Double? {
        val primaryBox = primary.candidate.boundingBox
        val plateBox = plate.candidate.boundingBox
        val verticalGap = plateBox.y - (primaryBox.y + primaryBox.height)
        if (verticalGap < -geometry.permittedBoxOverlap || verticalGap > geometry.maximumVerticalGap) return null

        val overlap = (
            minOf(primaryBox.x + primaryBox.width, plateBox.x + plateBox.width) -
                maxOf(primaryBox.x, plateBox.x)
            ).coerceAtLeast(0.0)
        val overlapFraction = overlap / minOf(primaryBox.width, plateBox.width)
        if (overlapFraction < geometry.minimumHorizontalOverlapFraction) return null

        val primaryCenter = primaryBox.x + primaryBox.width / 2.0
        val plateCenter = plateBox.x + plateBox.width / 2.0
        return verticalGap.coerceAtLeast(0.0) + abs(primaryCenter - plateCenter)
    }

    private data class Classified(
        val detection: TrafficSignDetection,
        val mapping: TrafficSignClassMapping,
    )
}
