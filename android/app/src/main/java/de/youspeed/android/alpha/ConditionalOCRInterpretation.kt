package de.youspeed.android.alpha

import java.time.Instant
import java.time.ZoneId
import kotlinx.serialization.json.*

/** A parser match is candidate evidence, never proof of a complete sign assembly. */
internal object ConditionalOCRInterpretation {
    /** Existing collection DTOs have no complete-assembly verification authority. */
    class AuthorityGate {
        private var scope = ""
        private val blocked = mutableSetOf<String>()
        private val restricted = mutableSetOf<String>()
        private val plain = mutableSetOf<String>()
        fun pending(parentId:String,primaryClassId:String,speedKmh:Int?,scope:String,knownPlate:Boolean=false):Boolean {
            select(scope)
            if(speedKmh==null || primaryClassId !in setOf("maxspeed:$speedKmh","zone:$speedKmh") || parentId.isEmpty()) return false
            if(knownPlate) {restricted.add(parentId);plain.remove(parentId)}
            return if(parentId in plain && parentId !in restricted) false else blocked.add(parentId)
        }
        fun admitPlain(parentId:String,scope:String):Boolean {
            select(scope);if(parentId in restricted) return false
            plain.add(parentId);blocked.remove(parentId);return true
        }
        fun observe(parentId: String, primaryClassId: String, speedKmh: Int?, rawText: String?, scope: String): Boolean {
            select(scope)
            // Failed/no-text attempts cannot prove that the complete assembly
            // is unconditional. The caller verifies the exact physical parent.
            if (speedKmh == null || primaryClassId !in setOf("maxspeed:$speedKmh","zone:$speedKmh") || parentId.isEmpty()) return false
            restricted.add(parentId);plain.remove(parentId)
            return blocked.add(parentId)
        }
        fun permitsPlain(parentId:String?,scope:String):Boolean {select(scope);return parentId in plain && parentId !in restricted}
        fun blocks(parentId: String?, scope: String): Boolean { select(scope); return parentId in blocked }
        private fun select(next: String) { if (scope != next) { scope = next; blocked.clear();restricted.clear();plain.clear() } }
    }
    sealed interface Condition {
        data object Informational : Condition
        data object Wet : Condition
        data class Schedule(val weekdays: List<Int>, val startMinute: Int, val endMinute: Int) : Condition
    }
    data class Parsed(val condition: Condition, val informationalText: List<String>, val normalizedText: String) {
        val parserRevision = "de-complete-plate-v1"
        fun ruleSet(speedKmh: Int): JsonObject = buildJsonObject {
            put("version",1);put("grammar","youspeed-osm-speed-1")
            put("tags",buildJsonArray { add(buildJsonObject {
                put("role","speed");put("vehicle","all");put("direction",0);put("priority",1);put("conditional",true);put("status","supported")
                put("clauses",buildJsonArray { add(buildJsonObject {
                    put("limit",buildJsonObject { put("kind","numeric");put("kmh",speedKmh) })
                    put("condition",buildJsonObject { when(val value=condition) {
                        Condition.Informational -> put("kind","true")
                        Condition.Wet -> { put("kind","context");put("field","road_surface_wet") }
                        is Condition.Schedule -> {
                            put("kind","schedule");put("weekdays",buildJsonArray { value.weekdays.forEach { add(it) } })
                            put("windows",buildJsonArray { add(buildJsonArray { add(value.startMinute);add(value.endMinute) }) })
                            put("weekday_anchor","window_start_date")
                        }
                    } })
                }) })
            }) })
        }
    }
    enum class Verification { CANDIDATE, VERIFIED, REJECTED }
    enum class Verdict { APPLICABLE, INAPPLICABLE, UNRESOLVED }
    data class Observation(val physicalSignId:String,val parentId:String,val primaryClassId:String,val primarySpeedKmh:Int,
        val plateIds:List<String>,val frameId:String,val rawText:String,val capturedAt:Instant,val evidenceOriginAt:Instant,
        val evidenceOriginDistanceM:Double,val countryCode:String,val scopeId:String,val scopeGeneration:Long,
        val pipelineId:String,val modelHash:String,val sourceEvaluationEnabled:Boolean?=null,val reviewedExport:Boolean=false,
        val reviewedRuntimeEligible:Boolean=false,val verifierId:String?=null,
        val assemblyEvidence:TrafficSignConditionalAssemblyEvidence?=null)
    data class Record(val observation:Observation,val parsed:Parsed?,val verification:Verification,val reason:String,
        val supportingFrameIds:List<String>,val originalEvidenceAt:Instant,val originalEvidenceDistanceM:Double) {
        fun verdict(at:Instant,distanceM:Double,scopeId:String,generation:Long,clockTrusted:Boolean=true,
            uncertaintySeconds:Double=0.0,timeZoneId:String?="Europe/Berlin",roadSurfaceWet:Boolean?=null):Verdict {
            if(verification!=Verification.VERIFIED || parsed==null || scopeId!=observation.scopeId || generation!=observation.scopeGeneration ||
                at<originalEvidenceAt || java.time.Duration.between(originalEvidenceAt,at).toMillis()>300000 ||
                !distanceM.isFinite() || distanceM<originalEvidenceDistanceM || distanceM-originalEvidenceDistanceM>5000) return Verdict.UNRESOLVED
            return when(val condition=parsed.condition) {
                Condition.Informational -> Verdict.APPLICABLE
                Condition.Wet -> when(roadSurfaceWet) { true->Verdict.APPLICABLE;false->Verdict.INAPPLICABLE;null->Verdict.UNRESOLVED }
                is Condition.Schedule -> {
                    if(!clockTrusted || !uncertaintySeconds.isFinite() || uncertaintySeconds !in 0.0..3600.0 || timeZoneId!="Europe/Berlin") return Verdict.UNRESOLVED
                    fun active(instant:Instant):Boolean {
                        val local=instant.atZone(ZoneId.of("Europe/Berlin"));val minute=local.hour*60+local.minute
                        val inside=if(condition.startMinute<condition.endMinute) minute>=condition.startMinute && minute<condition.endMinute else minute>=condition.startMinute || minute<condition.endMinute
                        if(!inside) return false
                        val anchor=if(condition.startMinute>condition.endMinute && minute<condition.endMinute) local.minusDays(1) else local
                        return condition.weekdays.isEmpty() || anchor.dayOfWeek.value in condition.weekdays
                    }
                    val nanos=(uncertaintySeconds*1e9).toLong();val lower=at.minusNanos(nanos);val upper=at.plusNanos(nanos)
                    val result=active(lower);var instant=lower
                    while(instant<upper) { if(active(instant)!=result) return Verdict.UNRESOLVED;instant=instant.plusSeconds(60) }
                    if(active(upper)!=result) Verdict.UNRESOLVED else if(result) Verdict.APPLICABLE else Verdict.INAPPLICABLE
                }
            }
        }
    }
    fun parse(raw:String):Parsed? {
        if(raw.isEmpty() || raw.length>4096) return null
        val normalized=raw.lowercase().replace('–','-').replace('—','-').replace('/',' ').trim().split(Regex("\\s+")).joinToString(" ")
        if(normalized in setOf("lärmschutz","schule")) return Parsed(Condition.Informational,listOf(normalized),normalized)
        if(normalized=="bei nässe") return Parsed(Condition.Wet,emptyList(),normalized)
        val match=Regex("^(?:(lärmschutz|schule) )?(?:(mo|di|mi|do|fr|sa|so)(?:-(mo|di|mi|do|fr|sa|so))? )?([0-9]{1,4}(?::[0-9]{2})?)\\s*-\\s*([0-9]{1,4}(?::[0-9]{2})?)(?:\\s*(?:h|uhr))?(?: (lärmschutz|schule))?$").matchEntire(normalized) ?: return null
        fun clock(raw:String,end:Boolean):Int? {
            val pieces=raw.split(':')
            val hour=if(pieces.size==2) pieces[0].toIntOrNull() else if(raw.length<=2) raw.toIntOrNull() else raw.dropLast(2).toIntOrNull()
            val minute=if(pieces.size==2) pieces[1].toIntOrNull() else if(raw.length<=2) 0 else raw.takeLast(2).toIntOrNull()
            if(hour==null || minute==null || minute !in 0..59 || hour<0 || !(hour<24 || end && hour==24 && minute==0)) return null
            return hour*60+minute
        }
        val start=clock(match.groupValues[4],false) ?: return null;val end=clock(match.groupValues[5],true) ?: return null
        if(start==end) return null
        val names=listOf("mo","di","mi","do","fr","sa","so")
        val days=if(match.groupValues[2].isEmpty()) emptyList() else {
            val lower=names.indexOf(match.groupValues[2]);val upper=if(match.groupValues[3].isEmpty()) lower else names.indexOf(match.groupValues[3])
            if(lower>upper) return null
            ((lower+1)..(upper+1)).toList()
        }
        return Parsed(Condition.Schedule(days,start,end),listOf(match.groupValues[1],match.groupValues[6]).filter { it.isNotEmpty() },normalized)
    }
    class Tracker {
        private var first:Observation?=null
        private var interpretation:Parsed?=null
        fun reset() { first=null;interpretation=null }
        fun consume(observation:Observation):Record {
            val parsed=parse(observation.rawText)
            fun record(verification:Verification,reason:String,frames:List<String> = emptyList()):Record {
                val origin=first?.takeIf { it.physicalSignId==observation.physicalSignId } ?: observation
                return Record(observation,parsed,verification,reason,frames,origin.evidenceOriginAt,origin.evidenceOriginDistanceM)
            }
            if(observation.countryCode.uppercase() !in setOf("DE","DEU") || observation.primaryClassId!="maxspeed:${observation.primarySpeedKmh}" ||
                observation.primarySpeedKmh !in 1..300 || observation.frameId.isEmpty() || observation.scopeId.isEmpty() ||
                observation.modelHash.isEmpty() || observation.pipelineId.isEmpty() || observation.plateIds.isEmpty() || observation.plateIds.any{it.isEmpty()} ||
                observation.evidenceOriginAt>observation.capturedAt || !observation.evidenceOriginDistanceM.isFinite()) {
                reset();return record(Verification.REJECTED,"invalid_primary_or_provenance")
            }
            if(observation.sourceEvaluationEnabled==false && !(observation.reviewedExport && observation.reviewedRuntimeEligible && observation.verifierId?.isNotEmpty()==true)) {
                reset();return record(Verification.REJECTED,"source_evaluation_disabled")
            }
            if(parsed==null) { reset();return record(Verification.REJECTED,"unsupported_or_residual_text") }
            val evidence=observation.assemblyEvidence
            if(evidence?.validate(evidence.primaryBox,observation.rawText,observation.frameId,observation.capturedAt,observation.parentId)?.kind!=TrafficSignConditionalAssemblyEvidence.Kind.CONDITIONAL) {
                reset();return record(Verification.CANDIDATE,"assembly_not_verified")
            }
            val prior=first
            if(prior!=null && prior.physicalSignId==observation.physicalSignId && prior.scopeId==observation.scopeId && prior.scopeGeneration==observation.scopeGeneration &&
                prior.parentId==observation.parentId && prior.primarySpeedKmh==observation.primarySpeedKmh && prior.plateIds.sorted()==observation.plateIds.sorted() &&
                prior.pipelineId==observation.pipelineId && prior.modelHash==observation.modelHash && interpretation==parsed) {
                val span=java.time.Duration.between(prior.capturedAt,observation.capturedAt).toMillis()
                if(prior.frameId!=observation.frameId && span in 100..2000) return record(Verification.VERIFIED,"two_distinct_complete_frames",listOf(prior.frameId,observation.frameId))
                if(span in 0..99) return record(Verification.CANDIDATE,"distinct_frame_agreement_pending",listOf(prior.frameId))
            }
            first=observation;interpretation=parsed
            return record(Verification.CANDIDATE,"distinct_frame_agreement_pending",listOf(observation.frameId))
        }
    }
}
