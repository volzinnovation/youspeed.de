package de.youspeed.android.alpha

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
 * Produces primary-only live assemblies. Supplementary signs are deliberately
 * ignored on device and belong to offline Panoramax/manual post-processing.
 */
object TrafficSignSpatialAssembly {
    fun assemble(
        detections: List<TrafficSignDetection>,
        modelPack: TrafficSignModelPack,
        assemblyIdPrefix: String,
        @Suppress("UNUSED_PARAMETER") geometry: TrafficSignAssemblyGeometry = TrafficSignAssemblyGeometry(),
    ): TrafficSignAssemblyBatch {
        require(assemblyIdPrefix.isNotBlank()) { "Assembly ID prefix must not be blank" }
        val primaries = detections.mapNotNull { detection ->
            modelPack.classFor(detection.candidate.rawClassId)
                ?.takeIf { it.signRole == TrafficSignRole.PRIMARY_SIGN }
                ?.let { detection }
        }
        val assemblies = primaries.mapIndexed { index, primary ->
            val assemblyId = "$assemblyIdPrefix-assembly-${index + 1}"
            val decoratedPrimary = primary.copy(
                candidate = primary.candidate.copy(
                    assemblyId = assemblyId,
                    conditionState = TrafficSignConditionState.NONE,
                    restrictions = emptyList(),
                ),
            )
            TrafficSignAssembly(
                assemblyId = assemblyId,
                primary = decoratedPrimary,
                supplementaryPlates = emptyList(),
                restrictions = emptyList(),
                conditionState = TrafficSignConditionState.NONE,
            )
        }

        return TrafficSignAssemblyBatch(
            assemblies = assemblies,
            unassignedSupplementaryPlates = emptyList(),
        )
    }
}
