package de.youspeed.android.alpha

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Read-only views retain original event identities and never rewrite the source log. */
internal object TripJournalProjection {
    fun payload(event:JSONObject):JSONObject=runCatching { JSONObject(event.optString("payload")) }.getOrDefault(JSONObject())
    fun trackEligible(payload:JSONObject)=payload.optBoolean("track_eligible",payload.optBoolean("valid")) && payload.optDouble("latitude").let {it.isFinite() && it in -90.0..90.0} && payload.optDouble("longitude").let {it.isFinite() && it in -180.0..180.0}
    fun endpointPlaces(trip:JSONObject,events:List<JSONObject>):Pair<String?,String?> {
        fun name(p:JSONObject):String? {
            fun text(vararg keys:String)=keys.firstNotNullOfOrNull {key->p.optString(key).trim().takeIf {it.isNotEmpty() && it!="null"}}
            val street=text("street_name","streetName");val city=text("city_name","cityName")
            return listOfNotNull(street,city?.takeUnless {it==street}).takeIf {it.isNotEmpty()}?.joinToString("\n")
        }
        val points=events.filter {it.optString("kind")=="gps" && trackEligible(payload(it))}.sortedBy {it.optDouble("time")}
        val contexts=events.filter {it.optString("kind")=="place" || it.optString("kind")=="gps" && trackEligible(payload(it))}
        fun endpoint(point:JSONObject?):String? {
            if(point==null) return null
            val p=payload(point);val t=point.optDouble("time")
            return contexts.mapNotNull {event ->
                val context=payload(event);val label=name(context) ?: return@mapNotNull null
                val eventTime=event.optDouble("time");val delta=kotlin.math.abs(eventTime-t)
                if(!delta.isFinite() || delta>15 || !context.optDouble("latitude").isFinite() || !context.optDouble("longitude").isFinite()) return@mapNotNull null
                val radius=maxOf(50.0,p.optDouble("accuracy",0.0),context.optDouble("accuracy",0.0))
                val distance=InventorySignRuntime.distance(p.optDouble("latitude"),p.optDouble("longitude"),context.optDouble("latitude"),context.optDouble("longitude"))
                if(!radius.isFinite() || !distance.isFinite() || distance>radius || events.any {it.optString("kind")=="gap" && it.optDouble("time")>minOf(t,eventTime) && it.optDouble("time")<=maxOf(t,eventTime)}) return@mapNotNull null
                Triple(delta,distance,label)
            }.minWithOrNull(compareBy<Triple<Double,Double,String>> {it.first}.thenBy {it.second})?.third
        }
        return (trip.optString("start_place").trim().takeIf {it.isNotEmpty()} ?: endpoint(points.firstOrNull())) to (trip.optString("end_place").trim().takeIf {it.isNotEmpty()} ?: endpoint(points.lastOrNull()))
    }
    fun discoveries(events:List<JSONObject>):List<JSONObject> {
        val groups=linkedMapOf<String,JSONObject>()
        events.filter { it.optString("kind")=="sign" }.forEach { event ->
            val p=payload(event);val identity=p.optString("evidence_id",event.optLong("seq").toString())
            val key="${p.optString("source","unknown")}|$identity"
            val prior=groups[key]
            if(prior==null) groups[key]=JSONObject(p.toString()).put("event_id",event.optLong("seq")).put("time",event.optDouble("time")).put("original_event_ids",JSONArray().put(event.optLong("seq")))
            else prior.getJSONArray("original_event_ids").put(event.optLong("seq"))
        }
        return groups.values.sortedBy { it.optDouble("time") }
    }
    fun media(events:List<JSONObject>):List<JSONObject> {
        val values=linkedMapOf<String,JSONObject>()
        events.filter { it.optString("kind")=="media" }.forEach { event ->
            val p=payload(event)
            // Keep the local original and actual remote picture as separate available actions.
            val key="${p.optString("type")}|${p.optString("id")}|${p.optString("path") }"
            val merged=values.getOrPut(key) { JSONObject().put("time",event.optDouble("time")) }
            p.keys().forEach { merged.put(it,p.opt(it)) }
            val path=p.optString("path")
            merged.put("availability",when { path.startsWith("https://") -> "remote_reference"; File(path).isFile -> "local_original"; else -> "local_missing" })
        }
        return values.values.sortedBy { it.optDouble("started_at",it.optDouble("time")) }
    }
    data class Seek(val path:String,val seconds:Double,val approximate:Boolean)
    fun seek(events:List<JSONObject>,time:Double):Seek?=media(events).filter { it.optString("type")=="video" && it.optString("availability")=="local_original" && it.optString("timing_quality")!="clock_alignment_uncertain" }.mapNotNull { item ->
        val start=item.optDouble("started_at",Double.NaN);val duration=item.optDouble("duration_s",Double.NaN)
        TripMediaClock.offset(time,start,duration,item.optDouble("presentation_start_s",0.0))?.let { Seek(item.optString("path"),it,item.optString("timing_quality")!="presentation_clock") }
    }.firstOrNull()
}

internal object TripMediaClock {
    /** Never select a different clip simply because it is geographically/temporally nearby. */
    fun offset(event:Double,start:Double,duration:Double,presentationStart:Double=0.0):Double? {
        if(!listOf(event,start,duration,presentationStart).all { it.isFinite() } || duration<=0 || presentationStart<0) return null
        val elapsed=event-start
        if(elapsed<0 || elapsed>=duration) return null
        return presentationStart+elapsed
    }
}

internal object TripJournalPresentation {
    fun distanceKilometres(metres:Double,locale:java.util.Locale=java.util.Locale.getDefault()):String=java.text.NumberFormat.getNumberInstance(locale).apply {minimumFractionDigits=1;maximumFractionDigits=1}.format(metres/1000)
    fun odometerKilometres(kilometres:Double,locale:java.util.Locale=java.util.Locale.getDefault()):String=java.text.NumberFormat.getNumberInstance(locale).apply {maximumFractionDigits=3}.format(kilometres)
    fun endingKilometres(input:String,startingKilometres:Double):Double?=input.trim().replace(',','.').toDoubleOrNull()?.takeIf {it.isFinite() && it>=0 && it>=startingKilometres}
}

/** Whole trips are selected by their start, using inclusive local calendar dates. */
internal object TripJournalPeriod {
    fun validCustom(from:String,to:String):Boolean {
        if(from.isBlank() && to.isBlank()) return true
        val lower=runCatching {java.time.LocalDate.parse(from.trim())}.getOrNull() ?: return false
        val upper=runCatching {java.time.LocalDate.parse(to.trim())}.getOrNull() ?: return false
        return !upper.isBefore(lower) && runCatching {upper.plusDays(1)}.isSuccess
    }
    fun bounds(today:java.time.LocalDate,zone:java.time.ZoneId,days:Int,from:String="",to:String=""):Pair<Double,Double> {
        val custom=from.isNotBlank() || to.isNotBlank()
        if(!validCustom(from,to)) return Double.POSITIVE_INFINITY to Double.NEGATIVE_INFINITY
        val lower=if(custom) java.time.LocalDate.parse(from.trim()) else days.takeIf {it>0}?.let {today.minusDays((it-1).toLong())}
        val upper=if(custom) java.time.LocalDate.parse(to.trim()).plusDays(1) else days.takeIf {it>0}?.let {today.plusDays(1)}
        return (lower?.atStartOfDay(zone)?.toEpochSecond()?.toDouble() ?: 0.0) to (upper?.atStartOfDay(zone)?.toEpochSecond()?.toDouble() ?: Double.POSITIVE_INFINITY)
    }
}
