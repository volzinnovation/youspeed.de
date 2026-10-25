package de.youspeed.android.alpha

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.location.Location
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Private journal. Its evidence never participates in live driving-rule interpretation. */
class TripJournal internal constructor(private val context: Context, heartbeat: Boolean = true, private val wallClock:()->Double={System.currentTimeMillis()/1000.0}, private val elapsedClock:()->Long={SystemClock.elapsedRealtime()}) : AutoCloseable {
    companion object {
        @Volatile private var instance: TripJournal? = null
        fun existing(): TripJournal? = instance
        fun get(context: Context): TripJournal = instance ?: synchronized(this) {
            instance ?: TripJournal(context.applicationContext).also { instance = it }
        }
    }
    private val worker = Executors.newSingleThreadScheduledExecutor()
    private val backlog=java.util.concurrent.atomic.AtomicInteger()
    private val dropped=java.util.concurrent.atomic.AtomicInteger()
    private fun submit(body: () -> Unit) {
        if(backlog.incrementAndGet()>4096) { backlog.decrementAndGet(); dropped.incrementAndGet(); return }
        worker.execute { try {
            attempt {
                val lost=dropped.getAndSet(0)
                if(lost>0) { previous=null; record("gap",JSONObject().put("reason","journal_queue_overflow").put("events_lost",lost)); error="Trip log coverage gap: queue overflow" }
                body()
            }
        } finally { backlog.decrementAndGet() } }
    }
    private val prefs=context.getSharedPreferences("trip-journal",Context.MODE_PRIVATE)
    private lateinit var db: SQLiteDatabase
    private var databaseReady=false
    @Volatile var error: String?=null; private set
    val configured get()=prefs.contains("enabled")
    val enabled get()=prefs.getBoolean("enabled",false)
    internal fun observeEnabled(observer: (Boolean) -> Unit): () -> Unit {
        val listener = android.content.SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
            if (key == "enabled" || key == null) observer(enabled)
        }
        prefs.registerOnSharedPreferenceChangeListener(listener)
        observer(enabled)
        return { prefs.unregisterOnSharedPreferenceChangeListener(listener) }
    }
    private var active: String?=null
    private data class Finalizing(val id:String,val start:Double,val end:Double,val deadline:Long)
    private var finalizing:Finalizing?=null
    private var requested=false
    private var endedLatch=false
    private var stopPrompt=TripStopPromptPolicy()
    private var resumeOnMovement=false
    private var foreground=true
    private var previous: Location?=null
    private var lastFixNanos=0L
    private var lastFixTime=0L
    private var usageAnchor=elapsedClock()
    private var tripAnchor=usageAnchor
    private var backgroundAt=0L
    private data class VideoAnchor(val wall:Double,val elapsed:Long)
    private val videoAnchors=mutableMapOf<String,VideoAnchor>()
    init {
        worker.execute { attempt {} }
        if(heartbeat) worker.scheduleAtFixedRate({ attempt { checkpoint() } },5,5,TimeUnit.SECONDS)
    }
    private fun now()=wallClock()
    private fun jsonValue(value:Any?):Any=when(value) {
        null -> JSONObject.NULL
        is Double -> if(value.isFinite()) value else JSONObject.NULL
        is Float -> if(value.isFinite()) value.toDouble() else JSONObject.NULL
        is Map<*,*> -> JSONObject().apply {value.forEach {(key,item)->put(key.toString(),jsonValue(item))}}
        is Iterable<*> -> JSONArray().apply {value.forEach {put(jsonValue(it))}}
        else -> if(value.javaClass.isArray) JSONArray().apply {for(i in 0 until java.lang.reflect.Array.getLength(value)) put(jsonValue(java.lang.reflect.Array.get(value,i)))} else value
    }
    private fun objectJSON(value:Map<String,Any?>)=jsonValue(value) as JSONObject

    private fun ensureDatabase() {
        if(databaseReady) return
        val root=File(context.filesDir,"trip-journal")
        check(root.isDirectory || root.mkdirs()) { "Unable to open trip journal directory" }
        val opened=SQLiteDatabase.openOrCreateDatabase(File(root,"trips.sqlite"),null)
        try {
            opened.enableWriteAheadLogging()
            opened.rawQuery("PRAGMA secure_delete=ON",null).use { check(it.moveToFirst() && it.getInt(0)==1) { "Unable to protect deleted trip data" } }
            opened.beginTransaction()
            try {
                opened.execSQL("CREATE TABLE IF NOT EXISTS trips(id TEXT PRIMARY KEY,start REAL,end REAL,state TEXT,distance REAL DEFAULT 0,duration REAL DEFAULT 0,odo_start REAL,odo_end REAL)")
                val columns=opened.rawQuery("PRAGMA table_info(trips)",null).use { c -> buildSet { while(c.moveToNext()) add(c.getString(1)) } }
                mapOf("last_observed" to "REAL", "end_reason" to "TEXT", "timezone_seconds" to "REAL", "vehicle" to "TEXT", "observed" to "REAL DEFAULT 0", "start_place" to "TEXT", "end_place" to "TEXT", "history_version" to "INTEGER DEFAULT 0", "counter_distance_end" to "REAL").forEach { (name,type) ->
                    if(name !in columns) opened.execSQL("ALTER TABLE trips ADD COLUMN $name $type")
                }
                opened.execSQL("CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,trip TEXT,kind TEXT,time REAL,payload TEXT)")
                opened.execSQL("CREATE INDEX IF NOT EXISTS events_trip ON events(trip,seq)")
                opened.execSQL("CREATE INDEX IF NOT EXISTS events_trip_kind_time ON events(trip,kind,time,seq)")
                opened.execSQL("CREATE TABLE IF NOT EXISTS bindings(session TEXT PRIMARY KEY,trip TEXT)")
                opened.execSQL("CREATE TABLE IF NOT EXISTS counters(id INTEGER PRIMARY KEY CHECK(id=1),origin REAL,distance REAL,usage REAL)")
                opened.execSQL("INSERT OR IGNORE INTO counters VALUES(1,?,0,0)",arrayOf(now()))
                opened.execSQL("UPDATE trips SET state='interrupted',end_reason='process_recovery',last_observed=COALESCE(last_observed,end) WHERE state IN ('active','finalizing')")
                opened.setTransactionSuccessful()
            } finally { opened.endTransaction() }
            db=opened
            transaction {backfillHistoryMetadata()}
            databaseReady=true; error=null
        } catch(failure:Exception) { opened.close(); throw failure }
    }
    private fun <T> withDatabase(block:()->T):T {
        try { ensureDatabase(); return block() }
        catch(failure:Exception) { error=failure.message ?: "Journal storage failure"; throw failure }
    }
    private fun attempt(block:()->Unit) { try { withDatabase(block) } catch(_:Exception) { /* Original failure is visible to the user. */ } }
    private fun <T> transaction(block:()->T):T {
        db.beginTransaction(); try { return block().also { db.setTransactionSuccessful() } } finally { db.endTransaction() }
    }
    private fun rows(query:String,args:Array<String> = emptyArray()):List<JSONObject> = db.rawQuery(query,args).use { c ->
        buildList { while(c.moveToNext()) add(JSONObject().apply {
            for(i in 0 until c.columnCount) if(!c.isNull(i)) put(c.getColumnName(i),when(c.getType(i)) {
                android.database.Cursor.FIELD_TYPE_INTEGER -> c.getLong(i)
                android.database.Cursor.FIELD_TYPE_FLOAT -> c.getDouble(i)
                else -> c.getString(i)
            })
        }) }
    }
    fun snapshot():Pair<List<JSONObject>,JSONObject> = worker.submit<Pair<List<JSONObject>,JSONObject>> { withDatabase {
        checkpoint()
        val trips=rows("SELECT t.*,(SELECT COUNT(*) FROM events e WHERE e.trip=t.id AND e.kind='gps') gps_count,(SELECT COUNT(*) FROM events e WHERE e.trip=t.id AND e.kind='gps' AND e.payload LIKE '%\"valid\":true%') valid_gps_count,(SELECT COUNT(*) FROM events e WHERE e.trip=t.id AND e.kind='sign') sign_count,(SELECT COUNT(*) FROM events e WHERE e.trip=t.id AND e.kind='gap') gap_count,(SELECT COUNT(*) FROM events e WHERE e.trip=t.id AND e.kind='media') media_count,(SELECT COUNT(*) FROM events e WHERE e.trip=t.id AND e.kind='media' AND REPLACE(e.payload,' ','') LIKE '%\"type\":\"photo%') photo_count,(SELECT COUNT(*) FROM events e WHERE e.trip=t.id AND e.kind='media' AND REPLACE(e.payload,' ','') LIKE '%\"type\":\"video%') video_count,(SELECT GROUP_CONCAT(payload) FROM events e WHERE e.trip=t.id AND e.kind='sign') sign_classes FROM trips t ORDER BY start DESC")
        val projections=rows("SELECT * FROM events WHERE kind IN ('sign','media','gps','place','tsr','gap') ORDER BY time,seq").groupBy {it.optString("trip")}
        trips.forEach {trip ->
            val signs=mutableSetOf<String>();val photos=mutableSetOf<String>();val videos=mutableSetOf<String>()
            projections[trip.optString("id")].orEmpty().forEach {event ->
                val payload=TripJournalProjection.payload(event)
                val identity=payload.optString("id",event.optLong("seq").toString())
                if(event.optString("kind")=="sign") signs+="${payload.optString("source")}|${payload.optString("evidence_id",event.optLong("seq").toString())}"
                else when(payload.optString("type")) {"photo","photo_remote" -> photos+=identity;"video" -> videos+=identity}
            }
            trip.put("sign_count",signs.size).put("photo_count",photos.size).put("video_count",videos.size).put("media_count",photos.size+videos.size)
        }
        trips to (rows("SELECT * FROM counters").firstOrNull() ?: JSONObject())
    } }.get()
    fun events(id:String):List<JSONObject> = worker.submit<List<JSONObject>> { withDatabase { rows("SELECT * FROM events WHERE trip=? ORDER BY time,seq",arrayOf(id)) } }.get()
    /** The history table reads saved facts only, independent of the number/size of events. */
    fun history():List<JSONObject> = worker.submit<List<JSONObject>> {withDatabase {rows("SELECT * FROM trips ORDER BY start DESC")}}.get()
    private fun storeHistoryMetadata(id:String) {
        val trip=rows("SELECT * FROM trips WHERE id=? AND COALESCE(history_version,0)=0",arrayOf(id)).firstOrNull() ?: return
        val points=rows("SELECT * FROM events WHERE trip=? AND kind='gps' ORDER BY time,seq",arrayOf(id)).filter {TripJournalProjection.trackEligible(TripJournalProjection.payload(it))}
        fun label(point:JSONObject?):String? {
            if(point==null) return null
            val t=point.optDouble("time")
            val context=rows("SELECT * FROM events WHERE trip=? AND kind IN ('gps','place','gap') AND time>=? AND time<=? ORDER BY time,seq",arrayOf(id,(t-15).toString(),(t+15).toString()))
                .map {if(it.optString("kind")=="gps") JSONObject(it.toString()).put("kind","place") else it}
            return TripJournalProjection.endpointPlaces(JSONObject(),listOf(point)+context).first
        }
        db.execSQL("UPDATE trips SET start_place=?,end_place=?,history_version=1 WHERE id=?",arrayOf(trip.optString("start_place").takeIf {it.isNotBlank()} ?: label(points.firstOrNull()),trip.optString("end_place").takeIf {it.isNotBlank()} ?: label(points.lastOrNull()),id))
    }
    private fun backfillHistoryMetadata() {
        rows("SELECT id FROM trips WHERE state NOT IN ('active','finalizing') AND COALESCE(history_version,0)=0").forEach {storeHistoryMetadata(it.getString("id"))}
    }
    fun storageBytes():Long=File(context.filesDir,"trip-journal").walkTopDown().filter { it.isFile }.sumOf { it.length() }
    fun setEnabled(value:Boolean) { prefs.edit().putBoolean("enabled",value).apply(); worker.execute { attempt {
        if(value && requested) {endedLatch=false;begin()} else if(!value) finish("disabled")
    } } }
    fun start() { worker.execute { attempt { requested=true; if(enabled && foreground) begin() } } }
    fun newTrip() { worker.execute { attempt { endedLatch=false; requested=true; if(enabled && foreground) begin() } } }
    private fun begin() {
        if(active!=null || endedLatch) return
        checkpoint()
        val id=UUID.randomUUID().toString(); val t=now()
        db.execSQL("INSERT INTO trips(id,start,end,state,last_observed,timezone_seconds) VALUES(?,?,?,'active',?,?)",arrayOf(id,t,t,t,java.util.TimeZone.getDefault().getOffset((t*1000).toLong())/1000))
        stopPrompt=TripStopPromptPolicy();resumeOnMovement=false
        active=id; previous=null; lastFixTime=0; lastFixNanos=0; tripAnchor=elapsedClock()
        record("coverage",JSONObject().put("gps","awaiting_location").put("tsr","existing_camera_setting").put("measurement_policy",1))
    }
    fun stop() {
        val intent=now();val intentElapsed=elapsedClock()
        worker.execute { attempt {
            requested=false;endedLatch=true
            val id=active
            val start=id?.let {rows("SELECT start FROM trips WHERE id=?",arrayOf(it)).firstOrNull()?.optDouble("start")}
            if(id!=null && start!=null) {
                finalizing?.let {completeFinalizer(it.id)}
                finish("finalizing")
                db.execSQL("UPDATE trips SET end=MIN(end,?),duration=?,end_reason='user_ended' WHERE id=?",arrayOf(intent,((intentElapsed-tripAnchor)/1000.0).coerceAtLeast(0.0),id))
                finalizing=Finalizing(id,start,intent,elapsedClock()+5000)
                worker.schedule({attempt {completeFinalizer(id)}},5,TimeUnit.SECONDS)
            }
        } }
    }
    internal fun completeFinalizerForTesting() {worker.submit {withDatabase {finalizing?.let {completeFinalizer(it.id)}}}.get()}
    private fun completeFinalizer(id:String) {
        if(finalizing?.id!=id) return
        record("coverage",JSONObject().put("state","sign_finalizer_closed").put("window_s",5),id)
        db.execSQL("UPDATE trips SET state='ended' WHERE id=? AND state='finalizing'",arrayOf(id));finalizing=null
        storeHistoryMetadata(id)
    }
    private fun eventOwner(time:Double):String? {
        active?.let {id -> val trip=rows("SELECT start,end FROM trips WHERE id=?",arrayOf(id)).firstOrNull()
            if(trip!=null && time>=trip.optDouble("start") && time<=now()+1 && (foreground || time<=trip.optDouble("end"))) return id }
        return finalizing?.takeIf {elapsedClock()<=it.deadline && time>=it.start && time<=it.end}?.id
    }
    private fun finish(state:String) {
        checkpoint()
        active?.let {
            db.execSQL("UPDATE trips SET state=?,end_reason=? WHERE id=?",arrayOf(if(state=="disabled") "ended" else state,state,it))
            storeHistoryMetadata(it)
        }
        active=null; previous=null
    }
    private fun checkpoint() {
        val t=elapsedClock(); val delta=(t-usageAnchor).coerceAtLeast(0)/1000.0; usageAnchor=t
        transaction {
            if(foreground) db.execSQL("UPDATE counters SET usage=usage+? WHERE id=1",arrayOf(delta))
            if(foreground) active?.let { db.execSQL("UPDATE trips SET end=?,last_observed=?,duration=?,observed=observed+? WHERE id=?",arrayOf(now(),now(),(t-tripAnchor)/1000.0,delta,it)) }
        }
    }
    fun lifecycle(value:Boolean) { worker.execute { attempt {
        if(value==foreground) return@attempt
        checkpoint()
        if(!value) { backgroundAt=elapsedClock(); previous=null; record("gap",JSONObject().put("reason","background")) }
        else {
            // Finish while still backgrounded: do not move the last durable endpoint to the resume time.
            if(elapsedClock()-backgroundAt>300000) finish("interrupted")
            else record("gap_end",JSONObject().put("reason","foreground_resumed").put("duration_s",(elapsedClock()-backgroundAt)/1000.0))
            if(!resumeOnMovement) endedLatch=false
        }
        foreground=value; usageAnchor=elapsedClock()
        if(value && requested && enabled) begin()
    } } }
    private fun record(kind:String,data:JSONObject,trip:String?=active,time:Double=now()) {
        if(trip==null || rows("SELECT id FROM trips WHERE id=?",arrayOf(trip)).isEmpty()) return
        db.execSQL("INSERT INTO events(trip,kind,time,payload) VALUES(?,?,?,?)",arrayOf(trip,kind,time,data.toString()))
    }
    fun tsr(event:String,details:Map<String,Any?>) { submit {
        val time=(details["frame_timestamp"] as? String)?.let {runCatching {java.time.Instant.parse(it).toEpochMilli()/1000.0}.getOrNull()} ?: now()
        eventOwner(time)?.let {id -> record("tsr",JSONObject().put("event",event).put("details",objectJSON(details)),id,time)}
    } }
    fun signEvent(payload:Map<String,Any?>,time:Double=System.currentTimeMillis()/1000.0) { submit {
        eventOwner(time)?.let { id -> if(time<=now()+1) record("sign",objectJSON(payload),id,time) }
    } }
    /** Offline matcher context is evidence at the original fix, never a reverse-geocoding guess. */
    fun matchedPlace(timeSeconds:Double,streetName:String?,cityName:String?,latitude:Double,longitude:Double,accuracy:Double) { submit {
        if(!enabled || !requested || !foreground || endedLatch || active==null || !timeSeconds.isFinite() || timeSeconds>now()+1 || !latitude.isFinite() || latitude !in -90.0..90.0 || !longitude.isFinite() || longitude !in -180.0..180.0 || !accuracy.isFinite() || accuracy !in 0.0..50.0) return@submit
        val street=streetName?.trim()?.takeIf {it.isNotEmpty()};val city=cityName?.trim()?.takeIf {it.isNotEmpty()}
        if(street==null && city==null) return@submit
        eventOwner(timeSeconds)?.let {id ->record("place",JSONObject().put("source","offline_matcher").put("street_name",street ?: JSONObject.NULL).put("city_name",city ?: JSONObject.NULL).put("latitude",latitude).put("longitude",longitude).put("accuracy",accuracy),id,timeSeconds)}
    } }
    fun location(source:Location) { val fix=Location(source); val receivedAt=now(); submit {
        if(resumeOnMovement && requested && foreground && enabled && fix.hasSpeed() && fix.speed>=1 && fix.hasAccuracy() && fix.accuracy in 0f..20f && kotlin.math.abs(receivedAt*1000-fix.time)<=3000) {
            endedLatch=false;begin()
        }
        if(!requested || !foreground || endedLatch) return@submit
        // Two platform listeners may deliver the same sample. A retry must never add the increment twice.
        val duplicate=if(fix.elapsedRealtimeNanos>0) fix.elapsedRealtimeNanos<=lastFixNanos else fix.time<=lastFixTime
        val valid=fix.provider!=android.location.LocationManager.NETWORK_PROVIDER && fix.latitude.isFinite() && fix.longitude.isFinite() && fix.latitude in -90.0..90.0 && fix.longitude in -180.0..180.0 && fix.hasAccuracy() && fix.accuracy in 0f..50f && kotlin.math.abs(receivedAt*1000-fix.time)<=10000 && !duplicate
        if(!duplicate) stopPrompt.observe(if(fix.hasSpeed()) fix.speed.toDouble() else -1.0, elapsedClock()/1000.0,
            valid && fix.accuracy<=20 && kotlin.math.abs(receivedAt*1000-fix.time)<=3000, enabled && active!=null)
        var distance=0.0; var reason=if(duplicate) "duplicate_or_out_of_order" else if(fix.provider==android.location.LocationManager.NETWORK_PROVIDER) "network_only" else if(valid) "segment_start" else "invalid_or_stale"
        previous?.takeIf { valid }?.let { prior ->
            val dt=if(fix.elapsedRealtimeNanos>0 && prior.elapsedRealtimeNanos>0) (fix.elapsedRealtimeNanos-prior.elapsedRealtimeNanos)/1e9 else (fix.time-prior.time)/1000.0
            distance=TripMeasurement.acceptedDistance(dt,prior.distanceTo(fix).toDouble(),fix.accuracy.toDouble(),prior.accuracy.toDouble(),if(fix.hasSpeed()) fix.speed.toDouble() else -1.0)
            reason=when { distance>0 -> "accepted"; dt>15 -> "sampling_gap"; else -> "jitter_jump_or_gap" }
        }
        transaction {
            val data=JSONObject().put("latitude",fix.latitude.takeIf { it.isFinite() } ?: JSONObject.NULL).put("longitude",fix.longitude.takeIf { it.isFinite() } ?: JSONObject.NULL)
                .put("accuracy",if(fix.hasAccuracy()) jsonValue(fix.accuracy.toDouble()) else JSONObject.NULL).put("speed",if(fix.hasSpeed()) jsonValue(fix.speed.toDouble()) else JSONObject.NULL)
                .put("altitude",if(fix.hasAltitude()) jsonValue(fix.altitude) else JSONObject.NULL).put("course",if(fix.hasBearing()) jsonValue(fix.bearing.toDouble()) else JSONObject.NULL)
                .put("received_at",receivedAt).put("invalid_fields",JSONArray(listOfNotNull("latitude".takeUnless {fix.latitude.isFinite()},"longitude".takeUnless {fix.longitude.isFinite()},"accuracy".takeIf {fix.hasAccuracy() && !fix.accuracy.isFinite()},"speed".takeIf {fix.hasSpeed() && !fix.speed.isFinite()},"altitude".takeIf {fix.hasAltitude() && !fix.altitude.isFinite()},"course".takeIf {fix.hasBearing() && !fix.bearing.isFinite()}))).put("elapsed_realtime_ns",fix.elapsedRealtimeNanos).put("valid",valid).put("track_eligible",valid && reason in listOf("segment_start","accepted","sampling_gap")).put("distance_m",distance).put("reason",reason).put("measurement_policy_version",1)
            record("gps",data,time=fix.time/1000.0)
            if(reason=="sampling_gap") record("gap",JSONObject().put("reason",reason),time=fix.time/1000.0)
            active?.let { db.execSQL("UPDATE trips SET distance=distance+?,end=MAX(end,?),last_observed=MAX(last_observed,?) WHERE id=?",arrayOf(distance,fix.time/1000.0,fix.time/1000.0,it)) }
            db.execSQL("UPDATE counters SET distance=distance+? WHERE id=1",arrayOf(distance))
        }
        if(!duplicate) {
            lastFixTime=maxOf(lastFixTime,fix.time); lastFixNanos=maxOf(lastFixNanos,fix.elapsedRealtimeNanos)
            if(!valid) previous=null else if(previous==null || distance>0 || fix.time-previous!!.time>15000) previous=fix
        }
    } }
    internal fun stoppedTripSnapshot(at:Double=now()):TripStopPromptSnapshot?=worker.submit<TripStopPromptSnapshot?> {withDatabase {
        val id=active
        if(!enabled || !foreground || id==null || !stopPrompt.canStop(elapsedClock()/1000.0)) return@withDatabase null
        val distance=rows("SELECT distance FROM trips WHERE id=?",arrayOf(id)).firstOrNull()?.optDouble("distance") ?: 0.0
        val total=rows("SELECT distance FROM counters WHERE id=1").firstOrNull()?.optDouble("distance") ?: 0.0
        val last=if(prefs.contains("odometer_km")) prefs.getFloat("odometer_km",0f).toDouble() else rows("SELECT odo_end FROM trips WHERE odo_end IS NOT NULL ORDER BY end DESC LIMIT 1").firstOrNull()?.optDouble("odo_end")
        val anchor=if(prefs.contains("odometer_distance_m")) java.lang.Double.longBitsToDouble(prefs.getLong("odometer_distance_m",0)) else (total-distance).coerceAtLeast(0.0)
        TripStopPromptSnapshot(id,TripOdometer.estimate(last,(total-anchor).coerceAtLeast(0.0)),last!=null)
    }}.get()
    internal fun continueStoppedTrip(id:String) {worker.submit {if(active==id) stopPrompt.continueTrip()}.get()}
    internal fun endStoppedTrip(id:String,at:Double=now()) {worker.submit {withDatabase {
        check(enabled && foreground && active==id && stopPrompt.canStop(elapsedClock()/1000.0)) {"Stop the car before ending the trip"}
        checkpoint()
        transaction {
            db.execSQL("UPDATE trips SET state='ended',end_reason='user_stopped',end=MIN(end,?),counter_distance_end=(SELECT distance FROM counters WHERE id=1) WHERE id=?",arrayOf(at,id))
            storeHistoryMetadata(id)
        }
        active=null;previous=null;stopPrompt=TripStopPromptPolicy();endedLatch=true;resumeOnMovement=true
    }}.get()}
    internal fun saveEndedTripOdometer(id:String,odometer:Int) {
        require(odometer in 0..999999)
        check(setEndingOdometer(id,odometer.toDouble())) {"Ending odometer is already saved"}
        worker.submit {withDatabase {
            if(rows("SELECT id FROM trips WHERE odo_end IS NOT NULL ORDER BY end DESC LIMIT 1").firstOrNull()?.optString("id")==id) {
                val total=rows("SELECT counter_distance_end FROM trips WHERE id=?",arrayOf(id)).first().optDouble("counter_distance_end",0.0)
                prefs.edit().putFloat("odometer_km",odometer.toFloat()).putLong("odometer_distance_m",java.lang.Double.doubleToRawLongBits(total)).apply()
            }
        }}.get()
    }
    internal fun saveStoppedTrip(id:String,odometer:Int,at:Double=now()) {worker.submit {withDatabase {
        check(enabled && foreground && active==id && stopPrompt.visible(elapsedClock()/1000.0)) {"Car must remain stopped with a fresh GPS fix"}
        require(odometer in 0..999999)
        val trip=rows("SELECT * FROM trips WHERE id=?",arrayOf(id)).first()
        check(!trip.has("odo_end") && odometer>=trip.optDouble("odo_start",0.0)) {"Invalid ending odometer"}
        checkpoint()
        transaction {
            db.execSQL("UPDATE trips SET odo_end=? WHERE id=? AND odo_end IS NULL",arrayOf(odometer,id))
            record("odometer_entry",JSONObject().put("position","end").put("entered_value",odometer).put("entered_unit","km").put("normalized_km",odometer).put("source","standstill_confirmation"),id,at)
            db.execSQL("UPDATE trips SET state='ended',end_reason='standstill_saved' WHERE id=?",arrayOf(id))
            storeHistoryMetadata(id)
        }
        val total=rows("SELECT distance FROM counters WHERE id=1").first().optDouble("distance")
        prefs.edit().putFloat("odometer_km",odometer.toFloat()).putLong("odometer_distance_m",java.lang.Double.doubleToRawLongBits(total)).apply()
        active=null;previous=null
        stopPrompt=TripStopPromptPolicy();endedLatch=true;resumeOnMovement=true
    }}.get()}
    fun bind(session:String) { worker.execute { attempt { active?.let { db.execSQL("INSERT OR IGNORE INTO bindings VALUES(?,?)",arrayOf(session,it)) } } } }
    fun media(session:String,id:String,path:String,kind:String,time:Double=System.currentTimeMillis()/1000.0,binding:String?=null,metadata:Map<String,Any?> = emptyMap()) { submit {
        val trip=rows("SELECT trip FROM bindings WHERE session=?",arrayOf(binding ?: session)).firstOrNull()?.optString("trip") ?: return@submit
        val payload=objectJSON(metadata).put("id",id).put("session",session).put("path",path).put("type",kind)
        record("media",payload,trip,time)
    } }
    fun video(event:String,path:String,duration:Double,session:String) {
        if(!duration.isFinite() || duration<0) return
        val observed=now();val observedElapsed=elapsedClock()
        submit {
            val anchor=videoAnchors.getOrPut(path) { VideoAnchor(observed-duration,observedElapsed-(duration*1000).toLong()) }
            val uncertain=kotlin.math.abs((observedElapsed-anchor.elapsed)/1000.0-duration)>2 || kotlin.math.abs(observed-(anchor.wall+duration))>2
            active?.let { db.execSQL("INSERT OR IGNORE INTO bindings VALUES(?,?)",arrayOf(path,it)) }
            val trip=rows("SELECT trip FROM bindings WHERE session=?",arrayOf(path)).firstOrNull()?.optString("trip") ?: return@submit
            record("media",JSONObject().put("id",File(path).name).put("session",session).put("path",path).put("type","video")
                .put("started_at",anchor.wall).put("ended_at",anchor.wall+duration).put("duration_s",duration).put("presentation_start_s",0)
                .put("first_frame_monotonic_s",anchor.elapsed/1000.0).put("timing_quality",if(uncertain) "clock_alignment_uncertain" else "callback_duration_anchor").put("timing_tolerance_s",2).put("finalized",event=="stop"),trip,anchor.wall)
            if(event=="stop") videoAnchors.remove(path)
        }
    }
    fun vehicle(id:String,label:String) { worker.execute { attempt {
        if(id==active && label.length<=120) db.execSQL("UPDATE trips SET vehicle=? WHERE id=? AND vehicle IS NULL AND distance=0",arrayOf(label.trim(),id))
    } } }
    fun odometer(id:String,start:Double?,end:Double?,unit:String="km") { worker.execute { attempt {
        if(id!=active || unit !in listOf("km","mi")) return@attempt
        val trip=rows("SELECT * FROM trips WHERE id=?",arrayOf(id)).firstOrNull() ?: return@attempt
        val factor=if(unit=="mi") 1.609344 else 1.0
        if(start!=null && start.isFinite() && start>=0 && start*factor<=trip.optDouble("odo_end",Double.POSITIVE_INFINITY) && !trip.has("odo_start") && trip.optDouble("distance")==0.0) transaction {
            val km=start*factor
            if(km.isFinite()) {db.execSQL("UPDATE trips SET odo_start=? WHERE id=? AND odo_start IS NULL AND distance=0",arrayOf(km,id));record("odometer_entry",JSONObject().put("position","start").put("entered_value",start).put("entered_unit",unit).put("normalized_km",km),id)}
        }
        if(end!=null && end.isFinite() && end>=0 && !trip.has("odo_end") && end*factor>=trip.optDouble("odo_start",0.0)) transaction {
            val km=end*factor
            if(km.isFinite()) {db.execSQL("UPDATE trips SET odo_end=? WHERE id=? AND odo_end IS NULL",arrayOf(km,id));record("odometer_entry",JSONObject().put("position","end").put("entered_value",end).put("entered_unit",unit).put("normalized_km",km),id)}
        }
    } } }
    /** Optional ending fact may be supplied once after a trip has ended; counters never change. */
    fun setEndingOdometer(id:String,kilometres:Double):Boolean=worker.submit<Boolean> {withDatabase {
        require(kilometres.isFinite() && kilometres>=0) {"Invalid odometer"}
        val trip=rows("SELECT * FROM trips WHERE id=?",arrayOf(id)).firstOrNull() ?: error("Trip no longer exists")
        require(trip.optString("state") in listOf("active","finalizing","ended","interrupted")) {"Trip state does not accept an ending odometer"}
        if(trip.has("odo_end")) return@withDatabase false
        require(kilometres>=trip.optDouble("odo_start",0.0)) {"Ending odometer is below starting odometer"}
        transaction {db.execSQL("UPDATE trips SET odo_end=? WHERE id=? AND odo_end IS NULL",arrayOf(kilometres,id));record("odometer_entry",JSONObject().put("position","end").put("entered_value",kilometres).put("entered_unit","km").put("normalized_km",kilometres),id)}
        true
    }}.get()
    /** Media ownership/cleanup remains in the library; deleting a trip never deletes a public upload. */
    fun delete(id:String) { worker.execute { attempt {
        if(id==active) { requested=false; endedLatch=true; finish("ended") }
        if(finalizing?.id==id) finalizing=null
        transaction { db.execSQL("DELETE FROM events WHERE trip=?",arrayOf(id)); db.execSQL("DELETE FROM bindings WHERE trip=?",arrayOf(id)); db.execSQL("DELETE FROM trips WHERE id=?",arrayOf(id)) }
        File(context.cacheDir,"trip-$id").deleteRecursively(); File(context.filesDir,"trip-exports/$id").deleteRecursively()
        File(context.filesDir,"trip-exports/backups").deleteRecursively()
        db.rawQuery("PRAGMA wal_checkpoint(TRUNCATE)",null).use { while(it.moveToNext()) {} }
    } } }
    fun clearAll() { worker.submit { withDatabase {
        requested=false; endedLatch=true; active=null; finalizing=null; previous=null; videoAnchors.clear()
        transaction { db.execSQL("DELETE FROM events"); db.execSQL("DELETE FROM bindings"); db.execSQL("DELETE FROM trips"); db.execSQL("UPDATE counters SET origin=?,distance=0,usage=0 WHERE id=1",arrayOf(now())) }
        usageAnchor=elapsedClock()
        File(context.filesDir,"trip-exports").deleteRecursively()
        context.cacheDir.listFiles()?.filter { it.name.startsWith("trip-") }?.forEach { it.deleteRecursively() }
        db.rawQuery("PRAGMA wal_checkpoint(TRUNCATE)",null).use { while(it.moveToNext()) {} }
    } }.get() }
    internal fun backupPayload():JSONObject=worker.submit<JSONObject> { withDatabase {
        checkpoint()
        JSONObject().put("schema_version",1).put("kind","youspeed-journal-backup").put("generated_at",now())
            .put("counters",JSONArray(rows("SELECT * FROM counters"))).put("trips",JSONArray(rows("SELECT * FROM trips")))
            .put("events",JSONArray(rows("SELECT * FROM events ORDER BY seq"))).put("bindings",JSONArray(rows("SELECT * FROM bindings")))
    } }.get()
    internal fun replaceBackup(payload:JSONObject) { worker.submit { withDatabase {
        TripJournalFiles.validateBackup(payload)
        transaction {
            listOf("events","bindings","trips","counters").forEach { db.execSQL("DELETE FROM $it") }
            mapOf("counters" to listOf("id","origin","distance","usage"),"trips" to listOf("id","start","end","state","distance","duration","odo_start","odo_end","last_observed","end_reason","timezone_seconds","vehicle","observed","start_place","end_place","history_version","counter_distance_end"),"events" to listOf("seq","trip","kind","time","payload"),"bindings" to listOf("session","trip")).forEach { (table,columns) ->
                val values=payload.getJSONArray(table)
                for(i in 0 until values.length()) {
                    val row=values.getJSONObject(i)
                    db.execSQL("INSERT INTO $table(${columns.joinToString(",")}) VALUES(${columns.joinToString(",") { "?" }})",columns.map { column -> row.opt(column).takeUnless { it==JSONObject.NULL } }.toTypedArray())
                }
            }
            db.execSQL("UPDATE trips SET state='interrupted',end_reason='backup_restore' WHERE state IN ('active','finalizing')")
            backfillHistoryMetadata()
        }
        active=null; finalizing=null; requested=false; endedLatch=true; previous=null; lastFixNanos=0; lastFixTime=0; usageAnchor=elapsedClock(); videoAnchors.clear()
        // Keep explicitly selected backup snapshots so a user may restore the same archive again.
        File(context.filesDir,"trip-exports").listFiles()?.filter {it.name!="backups"}?.forEach {it.deleteRecursively()}
        error=null
    } }.get() }
    fun backup(passphrase:String):File=TripJournalFiles.backup(context,backupPayload(),passphrase)
    fun backupPreview(file:File,passphrase:String):JSONObject=TripJournalFiles.backupPreview(file,passphrase)
    fun restore(file:File,passphrase:String) { replaceBackup(TripJournalFiles.readBackup(file,passphrase)) }
    fun export(id:String):File {
        val snapshot=snapshot(); val trip=snapshot.first.firstOrNull { it.optString("id")==id } ?: error("Trip unavailable")
        return TripJournalFiles.export(context,trip,events(id),snapshot.second)
    }
    internal fun archive(id:String,options:TripExportOptions):File {
        val snapshot=snapshot();val trip=snapshot.first.firstOrNull {it.optString("id")==id} ?: kotlin.error("Trip unavailable")
        return TripJournalFiles.archive(context,trip,events(id),snapshot.second,options)
    }
    fun archive(id:String,maskRadiusMetres:Double=0.0,includeLogs:Boolean=maskRadiusMetres==0.0,includeMedia:Boolean=false):File {
        val snapshot=snapshot(); val trip=snapshot.first.firstOrNull { it.optString("id")==id } ?: error("Trip unavailable")
        return TripJournalFiles.archive(context,trip,events(id),snapshot.second,maskRadiusMetres,includeLogs,includeMedia)
    }
    override fun close() { worker.submit { if(::db.isInitialized) { db.close(); databaseReady=false } }.get(); worker.shutdownNow() }
}
