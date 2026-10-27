package de.youspeed.android.alpha

import java.time.Duration
import java.time.Instant
import kotlin.math.abs
import org.json.JSONObject

internal data class AmendedNodeStation(val sourceId:String,val wayId:String,val direction:Int,
    val latitude:Double,val longitude:Double,val station:Double,val start:Double,val end:Double,val radius:Double,val recordId:String="",
    val bindingIdentity:String="")

/** A map-data producer using the existing inventory's directed station passage
 * gates. Historical edits and undirected OSM memberships never count as passage. */
internal class AmendedNodePassageRuntime {
    private var bundle:String?=null
    private var way:String?=null
    private var direction=0
    private var priorChainage:Double?=null
    private var priorAt:Instant?=null
    private val admitted=linkedSetOf<String>()
    private val activated=linkedSetOf<String>()
    private var associationSignature=emptyList<AmendedNodeStation>()
    fun reset() {bundle=null;way=null;direction=0;priorChainage=null;priorAt=null;admitted.clear();activated.clear();associationSignature=emptyList()}
    fun evaluate(stations:List<AmendedNodeStation>,fix:InventorySignFix,now:Instant,
        chainage:Double?,localHeading:Double?):Set<String> {
        if(bundle!=fix.bundle){reset();bundle=fix.bundle}
        if(way!=null&&way==fix.wayId&&direction!=0) {
            val current=stations.filter{it.wayId==way&&it.direction==direction}
                .sortedWith(compareBy<AmendedNodeStation>{it.recordId}.thenBy{it.sourceId})
            if(current!=associationSignature){admitted.clear();activated.clear();priorChainage=null;priorAt=null;associationSignature=current}
        }
        val age=Duration.between(fix.at,now).toMillis()
        val usable=fix.latitude.isFinite()&&fix.latitude in -90.0..90.0&&fix.longitude.isFinite()&&fix.longitude in -180.0..180.0&&
            fix.accuracy.isFinite()&&fix.accuracy in 0.0..25.0&&age in -1000..3000
        val heading=fix.heading;val headingAccuracy=fix.headingAccuracy
        val expected=localHeading?.let{(it+if(fix.direction<0)180.0 else 0.0)%360.0}
        val directed=usable&&fix.stable&&fix.wayId!=null&&fix.direction in setOf(-1,1)&&chainage!=null&&
            heading!=null&&heading.isFinite()&&headingAccuracy?.let{it.isFinite()&&it in 0.0..35.0}==true&&
            expected!=null&&abs(((heading-expected+540)%360)-180)<=35
        // An uncertain fix cannot establish a crossing or erase an established
        // scope. Never interpolate across that gap on the following valid fix.
        if(!directed){
            priorChainage=null;priorAt=null
            if(fix.wayId!=null&&fix.wayId!=way||fix.direction in setOf(-1,1)&&direction!=0&&fix.direction!=direction){admitted.clear();activated.clear()}
            return if(fix.wayId==way)activated.toSet() else emptySet()
        }
        if(way!=fix.wayId||direction!=fix.direction){admitted.clear();activated.clear();priorChainage=null;priorAt=null}
        way=fix.wayId;direction=fix.direction
        val current=requireNotNull(chainage)
        val scoped=stations.filter {it.wayId==way&&it.direction==direction}.sortedWith(compareBy<AmendedNodeStation>{it.recordId}.thenBy{it.sourceId})
        if(associationSignature!=scoped){admitted.clear();activated.clear();priorChainage=null;priorAt=null;associationSignature=scoped}
        scoped.forEach { station ->
            val sameTraversal=priorAt?.let{Duration.between(it,fix.at).toMillis() in 1..3000}==true
            val crossed=sameTraversal&&priorChainage?.let{
                if(direction>0)it<station.station&&current>=station.station else it>station.station&&current<=station.station
            }==true
            val nearby=InventorySignRuntime.distance(fix.latitude,fix.longitude,station.latitude,station.longitude)<=station.radius+1e-6
            val initialize=nearby&&priorChainage==null&&if(direction>0)current>=station.station else current<=station.station
            if(crossed||initialize)admitted+=station.sourceId
        }
        val stillApplicable=scoped.filter{if(direction>0)current>=it.start&&current<it.end else current>it.start&&current<=it.end}.map{it.sourceId}.toSet()
        val notEnded=scoped.filter{if(direction>0)current<it.end else current>it.start}.map{it.sourceId}.toSet()
        admitted.retainAll(notEnded);activated.addAll(admitted.intersect(stillApplicable));activated.retainAll(notEnded)
        priorChainage=current;priorAt=fix.at
        return activated.toSet()
    }

    companion object {
        fun station(record:MapDataAmendment,source:JSONObject?,wayLength:Double):AmendedNodeStation? {
            val node=source?:record.nodeJSON?.let(::JSONObject)?:return null
            if(record.sourceNamespace=="local") {
                if(!MapDataAmendmentStore.isLocalNodeSourceId(record.sourceId)||node.optString("source_id")!=record.sourceId||
                    node.has("osm_node_id")||node.optString("binding_status")!="local_reviewed"||
                    node.optJSONArray("memberships")?.length()!=0||record.stationChainageM==null||record.scopeStartM==null||record.scopeEndM==null)return null
            } else if(record.sourceNamespace!="osm"||node.opt("osm_node_id")?.toString()!=record.sourceId)return null
            val lat=node.optDouble("latitude",Double.NaN);val lon=node.optDouble("longitude",Double.NaN)
            if(!lat.isFinite()||lat !in -90.0..90.0||!lon.isFinite()||lon !in -180.0..180.0||!wayLength.isFinite()||wayLength<=0)return null
            val memberships=node.optJSONArray("memberships")
            val candidates=buildList {if(memberships!=null)for(i in 0 until memberships.length()) {
                val item=memberships.optJSONObject(i)?:continue
                if(item.opt("way_id")?.toString()==record.boundWayId&&item.optBoolean("coordinate_verified")) {
                    val station=item.optDouble("chainage_m",Double.NaN);if(station.isFinite()&&station>=0)add(station)
                }
            }}
            val station=record.stationChainageM?:candidates.distinct().singleOrNull()?:return null
            val start=record.scopeStartM?:if(record.direction>0)station else 0.0
            val end=record.scopeEndM?:if(record.direction>0)wayLength else station
            if(station !in 0.0..wayLength||start<0||end>wayLength||start>=end)return null
            val binding=org.json.JSONArray(listOf(record.sourceNamespace,record.basisBundle,record.sourceRevision,
                record.nodeJSON,record.passageEvidenceId,record.reviewState,record.bindingVerified,record.operation)).toString()
            return AmendedNodeStation(record.sourceId,record.boundWayId?:return null,record.direction,
                lat,lon,station,start,end,record.displayRadiusM?:30.0,record.id,MapDataAmendmentStore.sourceSHA256(binding))
        }
    }
}
