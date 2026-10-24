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

/** Retains mapped plates as unresolved collection evidence. Only native pixel/OCR proof can resolve authority. */
object TrafficSignSpatialAssembly {
    fun assemble(detections:List<TrafficSignDetection>,modelPack:TrafficSignModelPack,assemblyIdPrefix:String,
        geometry:TrafficSignAssemblyGeometry=TrafficSignAssemblyGeometry()):TrafficSignAssemblyBatch {
        require(assemblyIdPrefix.isNotBlank())
        val primaries=detections.filter {modelPack.classFor(it.candidate.rawClassId)?.signRole==TrafficSignRole.PRIMARY_SIGN}
        val plates=detections.filter {modelPack.classFor(it.candidate.rawClassId)?.signRole==TrafficSignRole.SUPPLEMENTARY_PLATE}
        val assigned=Array(primaries.size){mutableListOf<TrafficSignDetection>()};val ambiguous=mutableSetOf<Int>();val unassigned=mutableListOf<TrafficSignDetection>()
        for(plate in plates.sortedBy {it.candidate.boundingBox.y}) {
            val p=plate.candidate.boundingBox
            val eligible=primaries.indices.mapNotNull {index ->val parent=primaries[index].candidate.boundingBox
                val last=assigned[index].lastOrNull()?.candidate?.boundingBox ?: parent
                val gap=p.y-(last.y+last.height)
                val overlap=minOf(parent.x+parent.width,p.x+p.width)-maxOf(parent.x,p.x)
                if(gap>=-geometry.permittedBoxOverlap && gap<=geometry.maximumVerticalGap &&
                    overlap>=geometry.minimumHorizontalOverlapFraction*minOf(parent.width,p.width)) index to gap else null
            }.sortedBy {it.second}
            if(eligible.isEmpty()) unassigned+=plate
            else if(eligible.size>1 && eligible[1].second-eligible[0].second<geometry.permittedBoxOverlap) {
                eligible.forEach {ambiguous+=it.first};unassigned+=plate
            } else assigned[eligible.first().first]+=plate
        }
        val assemblies=primaries.mapIndexed {index,primary ->
            val id="$assemblyIdPrefix-assembly-${index+1}";val attached=assigned[index]
            val restrictions=attached.mapNotNull {modelPack.classFor(it.candidate.rawClassId)?.restriction}
            val state=if(attached.isNotEmpty() || index in ambiguous) TrafficSignConditionState.UNRESOLVED else TrafficSignConditionState.NONE
            TrafficSignAssembly(id,primary.copy(candidate=primary.candidate.copy(assemblyId=id,conditionState=state,restrictions=restrictions)),
                attached.toList(),restrictions,state)
        }
        return TrafficSignAssemblyBatch(assemblies,unassigned)
    }
}
