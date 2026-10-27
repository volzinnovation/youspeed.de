package de.youspeed.android.alpha

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.Cursor
import java.io.File
import java.util.UUID
import java.security.MessageDigest
import org.json.JSONArray
import org.json.JSONObject

data class MapDataAmendment(
    val id: String, val sourceNamespace: String, val entity: String, val sourceId: String,
    val basisBundle: String, val originalBundle: String, val sourceRevision: String,
    val rulesJSON: String, val rawSourceTags: Map<String, String>, val author: String,
    val evidenceId: String, val schemaVersion: Int = 1, val revision: Long = 0,
    val operation: String = "upsert", val direction: Int = 0,
    val validFromUTC: Double? = null, val validUntilUTC: Double? = null,
    val reviewState: String = "confirmed", val nodeJSON: String? = null,
    val boundWayId: String? = null, val bindingVerified: Boolean = false,
    val passageEvidenceId: String? = null,
    val stationChainageM:Double?=null,val scopeStartM:Double?=null,val scopeEndM:Double?=null,
    val displayRadiusM:Double?=null,
) {
    fun json(): JSONObject = JSONObject().apply {
        put("schema_version",schemaVersion);put("id",id);put("revision",revision);put("operation",operation)
        put("source_namespace",sourceNamespace);put("entity",entity);put("source_id",sourceId)
        put("direction",direction);put("basis_bundle",basisBundle);put("original_bundle",originalBundle)
        put("source_revision",sourceRevision);put("rules_json",rulesJSON);put("raw_source_tags",JSONObject(rawSourceTags))
        put("review_state",reviewState);put("author",author);put("evidence_id",evidenceId)
        put("binding_verified",bindingVerified)
        validFromUTC?.let { put("valid_from_utc",it) }; validUntilUTC?.let { put("valid_until_utc",it) }
        nodeJSON?.let { put("node_json",it) };boundWayId?.let { put("bound_way_id",it) }
        passageEvidenceId?.let { put("passage_evidence_id",it) }
        stationChainageM?.let{put("station_chainage_m",it)};scopeStartM?.let{put("scope_start_m",it)}
        scopeEndM?.let{put("scope_end_m",it)};displayRadiusM?.let{put("display_radius_m",it)}
    }
    companion object {
        fun decode(raw: String): MapDataAmendment {
            require(raw.toByteArray(Charsets.UTF_8).size<=512*1024) { "Amendment revision is oversized" }
            val o=JSONObject(raw)
            fun string(key:String):String { val value=o.get(key);require(value is String);return value }
            fun optionalString(key:String)=if(o.has(key)&&!o.isNull(key))string(key) else null
            fun optionalDouble(key:String)=if(o.has(key)&&!o.isNull(key))o.getDouble(key) else null
            val tags=o.getJSONObject("raw_source_tags");val source=buildMap { for(key in tags.keys()) {
                val value=tags.get(key);require(value is String);put(key,value)
            } }
            return MapDataAmendment(string("id"),string("source_namespace"),string("entity"),string("source_id"),
                string("basis_bundle"),string("original_bundle"),string("source_revision"),string("rules_json"),source,
                string("author"),string("evidence_id"),o.getInt("schema_version"),o.getLong("revision"),string("operation"),
                o.getInt("direction"),optionalDouble("valid_from_utc"),optionalDouble("valid_until_utc"),string("review_state"),
                optionalString("node_json"),optionalString("bound_way_id"),o.getBoolean("binding_verified"),optionalString("passage_evidence_id"),
                optionalDouble("station_chainage_m"),optionalDouble("scope_start_m"),optionalDouble("scope_end_m"),optionalDouble("display_radius_m"))
        }
    }
}

/** Separate writable, append-only correction data. Bundle removal/activation
 * never modifies it; CAS and SQLite transactions preserve concurrent history. */
class MapDataAmendmentStore(directory: File) {
    private val file=File(directory,"map_data_amendments.sqlite")
    class Conflict(val actualRevision:Long):IllegalStateException("Amendment revision conflict: $actualRevision")
    private fun <T> database(write:Boolean,body:(SQLiteDatabase)->T):T {
        if(write)require(file.parentFile?.let { it.isDirectory||it.mkdirs() }==true) { "Cannot create amendment directory" }
        val flags=if(write)SQLiteDatabase.CREATE_IF_NECESSARY else SQLiteDatabase.OPEN_READONLY
        return SQLiteDatabase.openDatabase(file.path,null,flags or SQLiteDatabase.NO_LOCALIZED_COLLATORS).use { db ->
            db.rawQuery("PRAGMA busy_timeout=2000",null).use { while(it.moveToNext())Unit }
            if(write) {
                db.enableWriteAheadLogging();db.execSQL("PRAGMA synchronous=FULL")
                db.beginTransaction()
                try {
                    db.execSQL("CREATE TABLE IF NOT EXISTS revisions(id TEXT NOT NULL,revision INTEGER NOT NULL,"+
                        "source_namespace TEXT NOT NULL,entity TEXT NOT NULL,source_id TEXT NOT NULL,body_json TEXT NOT NULL,bound_way_id TEXT,PRIMARY KEY(id,revision))")
                    if(!hasBindingColumn(db)) {
                        db.execSQL("ALTER TABLE revisions ADD COLUMN bound_way_id TEXT")
                        db.rawQuery("SELECT * FROM revisions",null).use {rows->while(rows.moveToNext()) {
                            val record=decode(rows.getString(rows.getColumnIndexOrThrow("body_json")))
                            require(record.id==rows.getString(rows.getColumnIndexOrThrow("id"))&&record.revision==rows.getLong(rows.getColumnIndexOrThrow("revision")))
                            db.execSQL("UPDATE revisions SET bound_way_id=? WHERE id=? AND revision=?",arrayOf(record.boundWayId,record.id,record.revision))
                        }}
                    }
                    db.execSQL("CREATE INDEX IF NOT EXISTS revisions_target ON revisions(source_namespace,entity,source_id)")
                    db.execSQL("CREATE INDEX IF NOT EXISTS revisions_binding ON revisions(entity,bound_way_id)")
                    db.setTransactionSuccessful()
                } finally {db.endTransaction()}
            }
            body(db)
        }
    }
    private fun decode(raw:String)=MapDataAmendment.decode(raw).also(::validate)
    private fun hasBindingColumn(db:SQLiteDatabase)=db.rawQuery("PRAGMA table_info(revisions)",null).use {rows->
        var found=false;while(rows.moveToNext())if(rows.getString(1)=="bound_way_id")found=true;found
    }
    private fun decodeRow(rows:Cursor):MapDataAmendment {
        val record=decode(rows.getString(rows.getColumnIndexOrThrow("body_json")))
        require(record.id==rows.getString(rows.getColumnIndexOrThrow("id"))&&record.revision==rows.getLong(rows.getColumnIndexOrThrow("revision"))&&
            record.sourceNamespace==rows.getString(rows.getColumnIndexOrThrow("source_namespace"))&&record.entity==rows.getString(rows.getColumnIndexOrThrow("entity"))&&
            record.sourceId==rows.getString(rows.getColumnIndexOrThrow("source_id"))) {"Amendment row identity mismatch"}
        val binding=rows.getColumnIndex("bound_way_id")
        if(binding>=0)require(record.boundWayId==if(rows.isNull(binding))null else rows.getString(binding)) {"Amendment binding index mismatch"}
        return record
    }
    private fun latest(id:String,db:SQLiteDatabase):MapDataAmendment?=
        db.rawQuery("SELECT * FROM revisions WHERE id=? ORDER BY revision DESC LIMIT 1",arrayOf(id)).use {
            if(it.moveToFirst())decodeRow(it) else null
        }
    fun latest(id:String):MapDataAmendment?=if(!file.isFile)null else database(false){latest(id,it)}
    fun history(id:String):List<MapDataAmendment> = if(!file.isFile) emptyList() else database(false) { db ->
        db.rawQuery("SELECT * FROM revisions WHERE id=? ORDER BY revision",arrayOf(id)).use { rows ->
            buildList { while(rows.moveToNext())add(decodeRow(rows)) }
        }
    }
    fun put(incoming:MapDataAmendment,expectedRevision:Long):MapDataAmendment {
        validate(incoming)
        return database(true) { db ->
            db.beginTransactionNonExclusive()
            try {
                val old=latest(incoming.id,db);val current=old?.revision?:0L
                if(current!=expectedRevision)throw Conflict(current)
                require(current<Long.MAX_VALUE) { "Amendment revision capacity reached" }
                if(old!=null)require(old.originalBundle==incoming.originalBundle&&old.sourceNamespace==incoming.sourceNamespace&&
                    old.entity==incoming.entity&&old.sourceId==incoming.sourceId) { "Retargeting requires a separate reviewed source record" }
                val saved=incoming.copy(revision=current+1);val raw=saved.json().toString()
                require(raw.toByteArray(Charsets.UTF_8).size<=512*1024) { "Amendment exceeds size limit" }
                db.insertOrThrow("revisions",null,ContentValues().apply {
                    put("id",saved.id);put("revision",saved.revision);put("source_namespace",saved.sourceNamespace)
                    put("entity",saved.entity);put("source_id",saved.sourceId);put("body_json",raw)
                    put("bound_way_id",saved.boundWayId)
                })
                db.setTransactionSuccessful();saved
            } finally { db.endTransaction() }
        }
    }
    fun tombstone(id:String,expectedRevision:Long)=put(requireNotNull(latest(id)){"Missing amendment"}.copy(operation="tombstone"),expectedRevision)
    fun createLocalNode(latitude:Double,longitude:Double,tags:Map<String,String>,rulesJSON:String,
        bundle:String,author:String,evidenceId:String):MapDataAmendment {
        val sourceId=newLocalNodeSourceId()
        val node=JSONObject().put("source_id",sourceId).put("latitude",latitude).put("longitude",longitude)
            .put("tags",JSONObject(tags)).put("memberships",JSONArray()).put("binding_status","local_reviewed")
        return put(MapDataAmendment(sourceId,"local","node",sourceId,bundle,bundle,"local-survey:$sourceId",
            rulesJSON,tags,author,evidenceId,nodeJSON=node.toString()),0)
    }
    fun amendNumericLimit(id:String,expectedRevision:Long,tagKey:String,clauseIndex:Int,kmh:Int):MapDataAmendment {
        val record=requireNotNull(latest(id)){"Missing amendment"}
        require(record.operation=="upsert"&&kmh in 1..400&&clauseIndex>=0)
        val rules=JSONObject(record.rulesJSON);val tags=rules.getJSONArray("tags")
        val index=(0 until tags.length()).firstOrNull { tags.getJSONObject(it).optString("key")==tagKey }
            ?: throw IllegalArgumentException("Missing typed speed tag")
        val clauses=tags.getJSONObject(index).getJSONArray("clauses")
        require(clauseIndex<clauses.length()) { "Missing typed speed clause" }
        clauses.getJSONObject(clauseIndex).put("limit",JSONObject().put("kind","numeric").put("kmh",kmh))
        return put(record.copy(rulesJSON=rules.toString()),expectedRevision)
    }
    private fun validate(r:MapDataAmendment) {
        require(r.schemaVersion==1&&r.id.isNotEmpty()&&r.id.toByteArray().size<=1024&&r.revision>=0&&
            r.operation in setOf("upsert","tombstone")&&r.entity in setOf("way","node","inventory_sign")&&
            r.sourceNamespace.isNotEmpty()&&r.basisBundle.isNotEmpty()&&r.originalBundle.isNotEmpty()&&
            r.sourceRevision.isNotEmpty()&&r.author.isNotEmpty()&&
            (if(r.sourceNamespace=="local")r.entity=="node"&&isLocalNodeSourceId(r.sourceId) else (r.sourceId.toLongOrNull()?:0)>0)&&
            r.direction in setOf(-1,0,1,2)&&r.reviewState in setOf("confirmed","needs_review","rebase_required")) { "Invalid amendment anchor/revision" }
        require(r.rulesJSON.toByteArray().size<=262144&&r.rawSourceTags.size<=128&&
            r.rawSourceTags.entries.sumOf { it.key.toByteArray().size+it.value.toByteArray().size }<=131072&&
            (r.nodeJSON?.toByteArray()?.size?:0)<=262144) { "Oversized amendment payload" }
        val rules=JSONObject(r.rulesJSON);val tags=rules.optJSONArray("tags")
        require(rules.optInt("version")==1&&rules.optString("grammar")=="youspeed-osm-speed-1"&&tags!=null&&tags.length() in 1..128) { "Unsupported conditional grammar" }
        if(r.sourceRevision.startsWith("node-json-sha256:"))require(r.entity=="node"&&r.nodeJSON!=null&&
            r.sourceRevision=="node-json-sha256:"+sourceSHA256(r.nodeJSON)) {"Node source revision differs from saved source snapshot"}
        if(r.sourceRevision.startsWith("way-rule-set-sha256:"))require(r.entity=="way"&&
            r.sourceRevision.removePrefix("way-rule-set-sha256:").matches(Regex("[0-9a-f]{64}"))) {"Invalid way source revision scheme"}
        for(at in listOfNotNull(r.validFromUTC,r.validUntilUTC))require(at.isFinite()&&at>=0) { "Invalid amendment validity" }
        require(r.validFromUTC==null||r.validUntilUTC==null||r.validFromUTC<r.validUntilUTC) { "Empty amendment validity" }
        if(r.entity!="way"&&r.bindingVerified)require((r.boundWayId?.toLongOrNull()?:0)>0&&r.direction in setOf(-1,1)&&!r.passageEvidenceId.isNullOrEmpty()) { "Node edit lacks verified directed passage evidence" }
        require(listOfNotNull(r.stationChainageM,r.scopeStartM,r.scopeEndM).all{it.isFinite()&&it>=0}&&
            (r.displayRadiusM==null||r.displayRadiusM in setOf(10.0,30.0))&&
            (r.scopeStartM==null||r.scopeEndM==null||r.scopeStartM<r.scopeEndM)) {"Invalid node scope"}
        if(r.sourceNamespace=="local") {
            val node=JSONObject(requireNotNull(r.nodeJSON){"Local node source is missing"})
            val latitude=node.optDouble("latitude",Double.NaN);val longitude=node.optDouble("longitude",Double.NaN)
            val tags=node.optJSONObject("tags")
            require(node.optString("source_id")==r.sourceId&&!node.has("osm_node_id")&&
                latitude.isFinite()&&latitude in -90.0..90.0&&longitude.isFinite()&&longitude in -180.0..180.0&&
                node.optString("binding_status")=="local_reviewed"&&node.optJSONArray("memberships")?.length()==0&&
                tags!=null&&tags.keys().asSequence().all{tags.get(it) is String}&&
                tags.keys().asSequence().associateWith{tags.getString(it)}==r.rawSourceTags) {"Invalid local node source"}
            if(r.bindingVerified)require(r.stationChainageM!=null&&r.scopeStartM!=null&&r.scopeEndM!=null) {"Local node requires an explicit reviewed scope"}
        }
    }
    internal fun confirmedNodeAmendments(wayId:String,bundle:String):List<MapDataAmendment> =
        if(!PackedAmendmentBaseIdentity.isCanonical(bundle)||!file.isFile)emptyList() else database(false) { db ->
            val boundFilter=if(hasBindingColumn(db))" AND r.bound_way_id=?" else ""
            db.rawQuery("SELECT r.* FROM revisions r WHERE r.entity='node'"+boundFilter+" AND r.revision="+
                "(SELECT MAX(n.revision) FROM revisions n WHERE n.id=r.id) ORDER BY r.id",if(boundFilter.isEmpty())null else arrayOf(wayId)).use { rows ->
                buildList {while(rows.moveToNext()) {
                    val record=decodeRow(rows)
                    if(record.operation=="upsert"&&record.sourceNamespace in setOf("osm","local")&&record.reviewState=="confirmed"&&
                        record.basisBundle==bundle&&record.boundWayId==wayId&&record.bindingVerified&&
                        record.direction in setOf(-1,1)&&!record.passageEvidenceId.isNullOrEmpty()&&
                        (record.sourceNamespace!="local"||record.stationChainageM!=null&&record.scopeStartM!=null&&record.scopeEndM!=null))add(record)
                }}
            }
        }
    fun resolve(wayId:String,bundle:String,direction:Int?,context:ConditionalSpeedRules.Context,
        baseKmh:Int?,baseUnlimited:Boolean,passedNodeIds:Set<String> = emptySet(),
        baselineResult:ConditionalSpeedRules.Result?=null,sourceWayRulesJSON:String?=null):ConditionalSpeedRules.Result? {
        if(!PackedAmendmentBaseIdentity.isCanonical(bundle)||!file.isFile)return null
        return database(false) { db ->
            val boundFilter=if(hasBindingColumn(db))" AND r.bound_way_id=?" else ""
            db.rawQuery("SELECT r.* FROM revisions r WHERE r.revision=(SELECT MAX(n.revision) FROM revisions n WHERE n.id=r.id) "+
                "AND (r.entity='way' AND r.source_id=? OR r.entity IN ('node','inventory_sign')"+boundFilter+") ORDER BY r.id",
                if(boundFilter.isEmpty())arrayOf(wayId) else arrayOf(wayId,wayId)).use { rows ->
                var selected:ConditionalSpeedRules.Result?=null
                while(rows.moveToNext()) {
                    val r=decodeRow(rows)
                    if(r.operation!="upsert"||r.sourceNamespace !in setOf("osm","local"))continue
                    if(r.entity=="way"&&r.sourceRevision.startsWith("way-rule-set-sha256:")&&
                        (sourceWayRulesJSON==null||r.sourceRevision!="way-rule-set-sha256:"+sourceSHA256(sourceWayRulesJSON)))continue
                    if(r.sourceNamespace=="local"&&(r.entity!="node"||r.stationChainageM==null||r.scopeStartM==null||r.scopeEndM==null))continue
                    if(r.entity!="way"&&(r.boundWayId!=wayId||!r.bindingVerified||r.passageEvidenceId.isNullOrEmpty()||r.sourceId !in passedNodeIds))continue
                    if(r.reviewState!="confirmed"||r.basisBundle!=bundle)continue
                    if(r.direction!=0) {
                        if(direction==null||r.direction==2)return@use ConditionalSpeedRules.Result(null,false,true,"map_amendment_direction_unresolved")
                        if(r.direction!=direction)continue
                    }
                    if((r.validFromUTC!=null||r.validUntilUTC!=null)&&!context.clockTrusted)
                        return@use ConditionalSpeedRules.Result(null,false,true,"map_amendment_validity_unresolved")
                    val now=context.atMs/1000.0
                    if(r.validFromUTC?.let { now<it }==true||r.validUntilUTC?.let { now>=it }==true)continue
                    val nodeBaseline=baselineResult.takeIf{r.entity!="way"}
                    val currentBaseKmh=if(nodeBaseline==null)baseKmh else nodeBaseline.kmh
                    val currentBaseUnlimited=nodeBaseline?.unlimited?:baseUnlimited
                    val result=ConditionalSpeedRules.evaluate(JSONObject(r.rulesJSON),context,currentBaseKmh,currentBaseUnlimited)
                        .copy(reevaluation=ConditionalSpeedRules.Reevaluation(r.rulesJSON,currentBaseKmh,currentBaseUnlimited,direction,
                            context.countryCode,context.timeZoneId,validFromUTC=r.validFromUTC,validUntilUTC=r.validUntilUTC,
                            baselineReevaluations=if(r.entity=="way")null else baselineResult?.reevaluation?.let{listOf(it)},
                            fallbackReevaluations=baselineResult?.reevaluation?.let{listOf(it)},
                            fallbackUnresolved=baselineResult?.unresolved,fallbackReason=baselineResult?.reason))
                    if(selected!=null)return@use ConditionalSpeedRules.Result(null,false,true,"map_amendment_conflict")
                    selected=result
                }
                selected
            }
        }
    }
    companion object {
        @Volatile private var directory:File?=null
        fun initialize(context:Context) { directory=context.applicationContext.filesDir }
        fun applicationStore():MapDataAmendmentStore?=directory?.let(::MapDataAmendmentStore)
        fun newLocalNodeSourceId():String="local-node:"+UUID.randomUUID().toString()
        internal fun isLocalNodeSourceId(id:String):Boolean=id.matches(Regex("local-node:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"))
        internal fun sourceSHA256(raw:String)=MessageDigest.getInstance("SHA-256").digest(raw.toByteArray(Charsets.UTF_8))
            .joinToString(""){"%02x".format(it.toInt() and 255)}
        fun waySourceRevision(rulesJSON:String)="way-rule-set-sha256:"+sourceSHA256(rulesJSON)
        fun nodeSourceRevision(sourceJSON:String)="node-json-sha256:"+sourceSHA256(sourceJSON)
    }
}
