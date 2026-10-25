package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Test
import java.io.File

/** Bounded read-only device evidence; never changes or rebuilds a driving map. */
class TurnaroundMapProbeInstrumentedTest {
    @Test fun exportReadOnlyL340PreviewRows() {
        org.junit.Assume.assumeTrue("Explicit installed-map evidence export",InstrumentationRegistry.getArguments().getString("turnaround_map_probe")=="true")
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val state=JSONObject(File(context.filesDir,"bundle/active_bundle.json").readText())
        val path=state.getString("db_path")
        val db=SQLiteDatabase.openDatabase(path,null,SQLiteDatabase.OPEN_READONLY)
        fun query(sql:String):JSONArray=db.rawQuery(sql,null).use {c -> JSONArray().apply {
            while(c.moveToNext()) {put(JSONObject().apply {for(i in 0 until c.columnCount) put(c.getColumnName(i),when(c.getType(i)) {
                android.database.Cursor.FIELD_TYPE_NULL -> JSONObject.NULL
                android.database.Cursor.FIELD_TYPE_INTEGER -> c.getLong(i)
                android.database.Cursor.FIELD_TYPE_FLOAT -> c.getDouble(i)
                android.database.Cursor.FIELD_TYPE_BLOB -> android.util.Base64.encodeToString(c.getBlob(i),android.util.Base64.NO_WRAP)
                else -> c.getString(i)
            })})}
        }}
        try {
            val out=JSONObject().put("active",state)
            val schemas=query("SELECT name,sql FROM sqlite_master WHERE type='table'")
            out.put("schema",schemas)
            val ways="'723493085','313163866','723489307','369347748','723489309','723489308','178845215','935939126'"
            for(i in 0 until schemas.length()) {
                val table=schemas.getJSONObject(i).getString("name")
                if(table.contains("rtree")) continue
                if(!table.matches(Regex("[A-Za-z_][A-Za-z_0-9]*")) || !(table.startsWith("traffic_sign") || table.startsWith("upcoming") || table in setOf("way_geom","ways","way_continuity_membership") || table.startsWith("road_speed"))) continue
                val columns=query("PRAGMA table_info($table)")
                val names=(0 until columns.length()).map {columns.getJSONObject(it).getString("name")}
                if("way_id" in names && (table.startsWith("traffic_sign") || table.startsWith("upcoming") || table in setOf("way_geom","ways","way_continuity_membership") || table.startsWith("road_speed"))) {
                    out.put(table,query("SELECT * FROM $table WHERE way_id IN ($ways) LIMIT 300"))
                }
            }
            if((0 until schemas.length()).any {schemas.getJSONObject(it).getString("name")=="upcoming_path_successor"}) {
                out.put("upcoming_path_successor",query("SELECT * FROM upcoming_path_successor WHERE from_segment_id IN (SELECT segment_id FROM upcoming_path_segment WHERE way_id IN ($ways)) LIMIT 300"))
            }
            for(table in listOf("traffic_sign_capability","upcoming_path_capability","road_speed_capability","traffic_sign_source")) out.put(table,query("SELECT * FROM $table LIMIT 100"))
            out.put("traffic_sign_runtime",query("SELECT * FROM traffic_sign_runtime WHERE sign_id IN (SELECT sign_id FROM traffic_sign_association WHERE way_id IN ($ways)) LIMIT 300"))
            out.put("upcoming_path_node",query("SELECT * FROM upcoming_path_node WHERE node_id IN (SELECT start_node_id FROM upcoming_path_segment WHERE way_id IN ($ways) UNION SELECT end_node_id FROM upcoming_path_segment WHERE way_id IN ($ways))"))
            out.put("way_continuity_group",query("SELECT * FROM way_continuity_group WHERE continuity_group_id IN (SELECT continuity_group_id FROM way_continuity_membership WHERE way_id IN ($ways))"))
            File(context.cacheDir,"turnaround-map-probe.json").writeText(out.toString())
        } finally {db.close()}
    }
}
