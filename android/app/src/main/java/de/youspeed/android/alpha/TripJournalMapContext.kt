package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Read-only geographic context from the already installed offline road bundle. */
internal object TripJournalMapContext {
    data class Road(val name:String,val highway:String,val points:List<Pair<Double,Double>>)
    data class Result(val roads:List<Road>,val limited:Boolean=false)
    @Synchronized fun load(path:String?,events:List<JSONObject>):Result {
        if(path.isNullOrBlank() || !File(path).isFile) return Result(emptyList())
        val points=events.filter {it.optString("kind")=="gps"}.map(TripJournalProjection::payload).filter {TripJournalProjection.trackEligible(it)}
        if(points.isEmpty())return Result(emptyList())
        val minLat=points.minOf {it.optDouble("latitude")};val maxLat=points.maxOf {it.optDouble("latitude")}
        val minLon=points.minOf {it.optDouble("longitude")};val maxLon=points.maxOf {it.optDouble("longitude")}
        val latitudePad=maxOf((maxLat-minLat)*0.1,0.001);val longitudePad=maxOf((maxLon-minLon)*0.1,0.001)
        return RuntimeMapDatabase.open(path,SQLiteDatabase.OPEN_READONLY or SQLiteDatabase.NO_LOCALIZED_COLLATORS).use { runtime ->
            val db = runtime.database
            val args=arrayOf((maxLon+longitudePad).toString(),(minLon-longitudePad).toString(),(maxLat+latitudePad).toString(),(minLat-latitudePad).toString())
            val fields=db.rawQuery("PRAGMA table_info(ways)",null).use {c ->buildSet {while(c.moveToNext())add(c.getString(1))}}
            val name=if("street_name" in fields) "w.street_name" else "NULL"
            val reference=if("ref" in fields) "w.ref" else "NULL"
            val query="SELECT COALESCE($name,$reference,''),w.highway,g.points_json FROM ways w JOIN way_geom g ON g.way_id=w.way_id WHERE w.min_lon<=? AND w.max_lon>=? AND w.min_lat<=? AND w.max_lat>=? ORDER BY CASE w.highway WHEN 'motorway' THEN 0 WHEN 'trunk' THEN 1 WHEN 'primary' THEN 2 ELSE 3 END,w.way_id LIMIT 1501"
            db.rawQuery(query,args).use { cursor ->
                val roads=buildList {while(cursor.moveToNext()) {
                    val geometry=JSONArray(cursor.getString(2))
                    val coordinates=buildList {for(i in 0 until geometry.length()) { val p=geometry.optJSONArray(i) ?: continue
                        val lat=p.optDouble(0);val lon=p.optDouble(1)
                        if(lat.isFinite() && lat in -90.0..90.0 && lon.isFinite() && lon in -180.0..180.0) add(lat to lon)
                    }}
                    if(coordinates.size>=2)add(Road(cursor.getString(0),cursor.getString(1).orEmpty(),coordinates))
                }}
                Result(roads.take(1500),roads.size>1500)
            }
        }
    }
}
