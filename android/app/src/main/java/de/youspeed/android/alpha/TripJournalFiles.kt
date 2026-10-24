package de.youspeed.android.alpha

import android.content.Context
import android.graphics.Paint
import android.graphics.pdf.PdfDocument
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.security.SecureRandom
import java.time.Instant
import java.util.UUID
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import javax.crypto.Cipher
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec
import kotlin.math.*

internal data class TripExportOptions(val masked:Boolean=false,val maskRadiusMetres:Double=300.0,val homeLatitude:Double?=null,val homeLongitude:Double?=null,val includeRawLogs:Boolean=true,val includeOdometer:Boolean=false,val selectedMedia:Set<String> = emptySet())

/** Portable snapshots. No export silently publishes media or contacts a service. */
internal object TripJournalFiles {
    private fun hash(bytes:ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    private fun hash(file:File):String {
        val digest=MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input -> val buffer=ByteArray(65536); while(true) { val n=input.read(buffer); if(n<0) break; digest.update(buffer,0,n) } }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
    private fun iso(seconds:Double)=Instant.ofEpochMilli((seconds*1000).toLong()).toString()
    private fun payload(event:JSONObject)=runCatching { JSONObject(event.optString("payload")) }.getOrDefault(JSONObject())
    private fun csv(value:Any?):String {
        val raw=if(value==null || value==JSONObject.NULL) "" else value.toString()
        val safe=if(raw.trimStart().firstOrNull() in listOf('=','+','-','@','\t','\r')) "'$raw" else raw
        return "\"${safe.replace("\"","\"\"")}\""
    }
    private fun distance(a:JSONObject,b:JSONObject):Double {
        val lat1=Math.toRadians(a.getDouble("latitude")); val lat2=Math.toRadians(b.getDouble("latitude"))
        val dlat=lat2-lat1; val dlon=Math.toRadians(b.getDouble("longitude")-a.getDouble("longitude"))
        val h=sin(dlat/2).pow(2)+cos(lat1)*cos(lat2)*sin(dlon/2).pow(2)
        return 6371008.8*2*asin(sqrt(h.coerceIn(0.0,1.0)))
    }
    fun export(context:Context,trip:JSONObject,events:List<JSONObject>,counters:JSONObject):File = write(context,trip,events,counters,TripExportOptions())
    fun archive(context:Context,trip:JSONObject,events:List<JSONObject>,counters:JSONObject,radius:Double,logs:Boolean,media:Boolean):File {
        return archive(context,trip,events,counters,TripExportOptions(masked=radius>0,maskRadiusMetres=radius,includeRawLogs=logs,selectedMedia=if(media) TripJournalProjection.media(events).map {it.optString("id")}.toSet() else emptySet()))
    }
    fun archive(context:Context,trip:JSONObject,events:List<JSONObject>,counters:JSONObject,options:TripExportOptions):File {
        require(options.maskRadiusMetres.isFinite() && options.maskRadiusMetres in 0.0..10000.0)
        val root=write(context,trip,events,counters,options)
        val archive=File(root.parentFile,"${root.name}.zip")
        ZipOutputStream(archive.outputStream()).use { zip ->
            root.walkTopDown().filter { it.isFile }.sortedBy { it.relativeTo(root).path }.forEach { file ->
                zip.putNextEntry(ZipEntry(file.relativeTo(root).invariantSeparatorsPath)); file.inputStream().use { it.copyTo(zip) }; zip.closeEntry()
            }
        }
        return archive
    }
    private fun write(context:Context,original:JSONObject,allEvents:List<JSONObject>,counters:JSONObject,options:TripExportOptions):File {
        val masked=options.masked
        val radius=if(masked) options.maskRadiusMetres else 0.0
        val logs=options.includeRawLogs && !masked
        val trip=JSONObject(original.toString()).apply {remove("sign_classes")}
        val id=trip.getString("id")
        val root=File(context.filesDir,"trip-exports/$id/youspeed-trip-${iso(trip.getDouble("start")).take(10)}-${UUID.randomUUID()}")
        check(root.mkdirs()) { "Unable to prepare export; check available storage" }
        try {
            val gps=allEvents.filter { it.optString("kind")=="gps" }.map { it to payload(it) }
            val located=gps.filter { TripJournalProjection.trackEligible(it.second) && it.second.has("latitude") && it.second.has("longitude") }
            val home=if(options.homeLatitude!=null && options.homeLongitude!=null) JSONObject().put("latitude",options.homeLatitude).put("longitude",options.homeLongitude) else null
            val endpoints=listOfNotNull(located.firstOrNull()?.second,located.lastOrNull()?.second,home)
            fun hidden(p:JSONObject):Boolean {
                if(!p.has("latitude") || !p.has("longitude") || p.isNull("latitude") || p.isNull("longitude")) return masked
                return endpoints.any { distance(p,it)<radius }
            }
            val visibleFixes=if(masked) located.filterNot { hidden(it.second) } else located
            val visibleTimes=visibleFixes.map { it.first.optDouble("time") }
            val firstVisible=visibleTimes.minOrNull() ?: Double.POSITIVE_INFINITY
            val lastVisible=visibleTimes.maxOrNull() ?: Double.NEGATIVE_INFINITY
            val omissions=JSONArray()
            var hiddenBreak=true
            val events=if(!masked) allEvents.filter {options.includeOdometer || it.optString("kind")!="odometer_entry"} else allEvents.mapNotNull { e ->
                val kind=e.optString("kind"); val p=payload(e)
                val keep=when(kind) {
                    "gps" -> !hidden(p) && e.optDouble("time") in firstVisible..lastVisible
                    "sign" -> !hidden(p) && e.optDouble("time") in firstVisible..lastVisible
                    // Free-form TSR metadata and media locators can reveal hidden positions.
                    else -> false
                }
                if(!keep) { if(kind=="gps") hiddenBreak=true; null } else JSONObject(e.toString()).put("payload",JSONObject().apply {
                    val allowed=if(kind=="gps") listOf("latitude","longitude","accuracy","speed","altitude","course","valid","track_eligible","reason","distance_m","measurement_policy_version") else listOf("class_code","source","evidence_id","latitude","longitude","accuracy","confidence","value","units")
                    allowed.forEach { key -> if(p.has(key)) put(key,p.opt(key)) }
                    if(kind=="gps") { if(hiddenBreak) put("reason","segment_start"); hiddenBreak=false }
                }.toString())
            }
            if(!options.includeOdometer) { trip.remove("odo_start");trip.remove("odo_end") }
            if(masked) {
                listOf("vehicle","place","start_place","end_place").forEach { trip.remove(it) }
                omissions.put(JSONObject().put("reason","privacy_mask").put("endpoint_radius_m",radius).put("omitted_events",allEvents.size-events.size)
                    .put("excluded","Hidden positions, raw logs, free-form metadata, videos and remote links excluded; selected photos outside hidden areas are re-encoded without GPS metadata"))
            }
            val generated=System.currentTimeMillis()/1000.0
            val metadata=JSONObject().put("schema_version",1).put("generated_at",generated).put("measurement_policy_version",1)
                .put("units",JSONObject().put("distance","m").put("duration","s").put("speed","m/s").put("coordinates","longitude,latitude").put("event_time","Unix seconds UTC"))
                .put("in_progress_snapshot",trip.optString("state") in listOf("active","finalizing")).put("privacy_mask_radius_m",radius)
            var geometric=0.0; var prior:JSONObject?=null
            visibleFixes.forEach { (e,p) ->
                val q=prior; if(q!=null && p.optString("reason")=="accepted") geometric+=distance(q,p)
                prior=p
            }
            metadata.put("original_measured_distance_m",original.optDouble("distance",0.0)).put("shared_track_geometric_distance_m",geometric)
            File(root,"trip.json").writeText(JSONObject(metadata.toString()).put("trip",trip).toString(2))
            val gpx=StringBuilder("<?xml version=\"1.0\" encoding=\"UTF-8\"?><gpx version=\"1.1\" creator=\"YouSpeed\" xmlns=\"http://www.topografix.com/GPX/1/1\"><trk><name>YouSpeed</name>")
            val coordinates=JSONArray(); var segment=JSONArray(); var segmentOpen=false; var priorTime:Double?=null
            events.forEach { e ->
                if(e.optString("kind")=="gap") { if(segmentOpen) {gpx.append("</trkseg>"); segmentOpen=false}; if(segment.length()>0) {coordinates.put(segment);segment=JSONArray()}; priorTime=null }
                if(e.optString("kind")=="gps") {
                    val p=payload(e); val time=e.optDouble("time")
                    if(TripJournalProjection.trackEligible(p)) {
                        val gap=priorTime?.let { time-it>15 } ?: true
                        if(gap || p.optString("reason") in listOf("segment_start","sampling_gap")) {
                            if(segmentOpen) gpx.append("</trkseg>")
                            if(segment.length()>0) {coordinates.put(segment);segment=JSONArray()}
                            gpx.append("<trkseg>");segmentOpen=true
                        }
                        if(!segmentOpen) { gpx.append("<trkseg>");segmentOpen=true }
                        gpx.append("<trkpt lat=\"").append(p.getDouble("latitude")).append("\" lon=\"").append(p.getDouble("longitude")).append("\">")
                        if(!p.isNull("altitude") && p.has("altitude")) gpx.append("<ele>").append(p.optDouble("altitude")).append("</ele>")
                        gpx.append("<time>").append(iso(time)).append("</time></trkpt>")
                        segment.put(JSONArray().put(p.getDouble("longitude")).put(p.getDouble("latitude"))); priorTime=time
                    } else if(!p.optBoolean("valid") && p.optString("reason")!="duplicate_or_out_of_order") {
                        if(segmentOpen) { gpx.append("</trkseg>");segmentOpen=false }
                        if(segment.length()>0) {coordinates.put(segment);segment=JSONArray()};priorTime=null
                    }
                }
            }
            if(segmentOpen) gpx.append("</trkseg>")
            if(segment.length()>0) coordinates.put(segment)
            File(root,"track.gpx").writeText(gpx.append("</trk></gpx>").toString())
            File(root,"track.geojson").writeText(JSONObject().put("type","Feature").put("properties",metadata).put("geometry",JSONObject().put("type","MultiLineString").put("coordinates",coordinates)).toString())
            val kinds=listOf("gps","tsr","sign","gap")
            fun envelope(e:JSONObject)=JSONObject().put("schema_version",1).put("seq",e.optLong("seq")).put("time",e.optDouble("time")).put("kind",e.optString("kind")).put("payload",payload(e))
            kinds.forEach { kind ->
                val values=events.filter { it.optString("kind")==kind && (logs || kind in listOf("sign","gap")) }.map(::envelope)
                File(root,"$kind.ndjson").writeText(values.joinToString("\n"))
                File(root,"$kind.json").writeText(JSONObject().put("schema_version",1).put("events",JSONArray(values)).toString())
                File(root,"$kind.csv").writeText("sequence,time_utc,payload_json\n"+values.joinToString("\n") { e -> "${e.optLong("seq")},${csv(iso(e.optDouble("time")))},${csv(e.optString("payload"))}" })
            }
            val discoveries=TripJournalProjection.discoveries(events)
            File(root,"discoveries.json").writeText(JSONObject(metadata.toString()).put("discoveries",JSONArray(discoveries)).toString())
            File(root,"discoveries.csv").writeText("event_id,time_utc,class_code,source,latitude,longitude,confidence,value,units,media_id\n"+discoveries.joinToString("\n") { p -> listOf(p.opt("event_id"),iso(p.optDouble("time")),p.opt("class_code"),p.opt("source"),p.opt("latitude"),p.opt("longitude"),p.opt("confidence"),p.opt("value"),p.opt("units"),p.opt("media_id")).joinToString(",",transform=::csv) })
            val mediaIndex=TripJournalProjection.media(allEvents)
            val portableMedia=JSONArray()
            mediaIndex.forEach { item ->
                val source=File(item.optString("path"));val type=item.optString("type")
                val capturedAt=item.optDouble("time")
                val direct=item.takeIf { !it.isNull("latitude") && !it.isNull("longitude") }
                val nearest=located.minByOrNull { abs(it.first.optDouble("time")-capturedAt) }?.takeIf { abs(it.first.optDouble("time")-capturedAt)<=3 }
                val coordinate=direct ?: nearest?.second
                if(masked && (type!="photo" || coordinate==null || hidden(coordinate))) {
                    omissions.put(JSONObject().put("id",item.optString("id")).put("reason","privacy_mask_or_unknown_photo_position"));return@forEach
                }
                val row=if(masked) JSONObject().put("id",item.optString("id")).put("type",type).put("captured_at",capturedAt) else JSONObject(item.toString()).apply { remove("path");remove("local_path") }
                if(item.optString("id") in options.selectedMedia && source.isFile && type in listOf("photo","video")) {
                    val name="media/${UUID.randomUUID()}.${if(masked) "jpg" else source.extension}"
                    val destination=File(root,name);check(destination.parentFile!!.isDirectory || destination.parentFile!!.mkdirs())
                    if(masked) {
                        val image=android.graphics.BitmapFactory.decodeFile(source.path)
                        if(image==null) {omissions.put(JSONObject().put("id",item.optString("id")).put("reason","photo_metadata_stripping_failed"));return@forEach}
                        var upright=image
                        try {
                            val orientation=androidx.exifinterface.media.ExifInterface(source).getAttributeInt(androidx.exifinterface.media.ExifInterface.TAG_ORIENTATION,androidx.exifinterface.media.ExifInterface.ORIENTATION_NORMAL)
                            val matrix=android.graphics.Matrix().apply {when(orientation) {
                                androidx.exifinterface.media.ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> setScale(-1f,1f)
                                androidx.exifinterface.media.ExifInterface.ORIENTATION_ROTATE_180 -> setRotate(180f)
                                androidx.exifinterface.media.ExifInterface.ORIENTATION_FLIP_VERTICAL -> setScale(1f,-1f)
                                androidx.exifinterface.media.ExifInterface.ORIENTATION_TRANSPOSE -> {setRotate(90f);postScale(-1f,1f)}
                                androidx.exifinterface.media.ExifInterface.ORIENTATION_ROTATE_90 -> setRotate(90f)
                                androidx.exifinterface.media.ExifInterface.ORIENTATION_TRANSVERSE -> {setRotate(-90f);postScale(-1f,1f)}
                                androidx.exifinterface.media.ExifInterface.ORIENTATION_ROTATE_270 -> setRotate(-90f)
                            }}
                            if(!matrix.isIdentity) upright=android.graphics.Bitmap.createBitmap(image,0,0,image.width,image.height,matrix,true)
                            destination.outputStream().use {check(upright.compress(android.graphics.Bitmap.CompressFormat.JPEG,95,it))}
                        } finally {if(upright!==image) upright.recycle();image.recycle()}
                    } else source.copyTo(destination)
                    row.put("archive_path",name)
                } else omissions.put(JSONObject().put("id",item.optString("id")).put("reason",if(source.isFile) "media_not_selected" else "local_media_unavailable"))
                portableMedia.put(row)
            }
            val mediaDocument=JSONObject().put("schema_version",1).put("media",portableMedia).put("omitted",omissions)
            File(root,"media.json").writeText(mediaDocument.toString())
            File(root,"media-index.json").writeText(mediaDocument.toString())
            val journalTrip=JSONObject().put("id",trip.getString("id")).put("started_at",trip.optDouble("start")).put("ended_at",trip.opt("end") ?: JSONObject.NULL)
                .put("distance_m",trip.optDouble("distance")).put("duration_s",trip.optDouble("duration")).put("state",when(trip.optString("state")) {"disabled" -> "ended";"finalizing" -> "active";else -> trip.optString("state")})
                .put("vehicle",trip.opt("vehicle") ?: JSONObject.NULL).put("odometer_start_km",trip.opt("odo_start") ?: JSONObject.NULL).put("odometer_end_km",trip.opt("odo_end") ?: JSONObject.NULL)
            File(root,"journal.json").writeText(JSONObject().put("schema_version",1).put("generated_at",iso(generated)).put("measurement_policy_version",1)
                .put("units",JSONObject().put("distance","metre").put("duration","second").put("speed","metres_per_second").put("coordinates","longitude,latitude").put("event_time","unix_seconds_utc"))
                .put("trip",journalTrip).put("events",JSONArray(events.filter { logs || it.optString("kind") !in listOf("gps","tsr","media") }.map(::envelope))).put("media",portableMedia)
                .put("privacy",JSONObject().put("masked",masked).put("raw_logs_included",logs)).toString())
            File(root,"counters.json").writeText(JSONObject(metadata.toString()).put("lifetime",if(masked) JSONObject().put("excluded","privacy") else counters).put("retained_trip_distance_m",original.optDouble("distance",0.0)).toString())
            File(root,"counters.csv").writeText("counter_origin,lifetime_distance_m,lifetime_usage_s,trip_distance_m\n"+listOf(counters.opt("origin"),counters.opt("distance"),counters.opt("usage"),trip.opt("distance")).joinToString(",",transform=::csv))
            File(root,"overview.csv").writeText("trip_id,start_utc,end_utc,measured_distance_m,duration_s,state,vehicle,odometer_start_km,odometer_end_km\n"+listOf(trip.opt("id"),iso(trip.optDouble("start")),iso(trip.optDouble("end")),trip.opt("distance"),trip.opt("duration"),trip.opt("state"),trip.opt("vehicle"),trip.opt("odo_start"),trip.opt("odo_end")).joinToString(",",transform=::csv))
            val scope=ConsumerUiStrings.text("YouSpeed records your app trips. Trips can be deleted; vehicle odometer readings are optional. This is a private trip journal. Tax recognition as a formal logbook and an authority-ordered logbook under § 31a StVZO are not guaranteed.","YouSpeed zeichnet Ihre App-Fahrten auf. Fahrten können gelöscht werden; Fahrzeug-Kilometerstände sind freiwillig. Dies ist ein privates Fahrtenjournal. Eine steuerliche Anerkennung als ordnungsgemäßes Fahrtenbuch wird nicht zugesichert. Die Funktion erfüllt keine behördliche Fahrtenbuchauflage nach § 31a StVZO.","YouSpeed enregistre vos trajets dans l’application. Les trajets peuvent être supprimés et les relevés du véhicule sont facultatifs. Journal privé sans garantie de reconnaissance fiscale ni de conformité au § 31a StVZO.","YouSpeed registreert uw app-ritten. Ritten zijn verwijderbaar; kilometerstanden zijn optioneel. Privérittenboek zonder garantie van fiscale erkenning of conformiteit met § 31a StVZO.")
            fun t(en:String,de:String,fr:String,nl:String)=ConsumerUiStrings.text(en,de,fr,nl)
            fun readable(seconds:Double)=java.time.format.DateTimeFormatter.ofLocalizedDateTime(java.time.format.FormatStyle.SHORT).withZone(java.time.ZoneId.systemDefault()).format(Instant.ofEpochMilli((seconds*1000).toLong()))
            val lines=listOf(t("YouSpeed trip overview","YouSpeed Fahrtenübersicht","Résumé des trajets YouSpeed","YouSpeed rittenoverzicht"),
                "${readable(trip.optDouble("start"))} – ${readable(trip.optDouble("end"))}",
                t("Measured","Gemessen","Mesuré","Gemeten")+": %.3f km · ".format(trip.optDouble("distance")/1000)+t("Duration","Dauer","Durée","Duur")+": %.1f min".format(trip.optDouble("duration")/60),
                t("State","Status","État","Status")+": ${trip.optString("state")}; "+if(trip.optString("state") in listOf("active","finalizing")) t("IN-PROGRESS SNAPSHOT","ZWISCHENSTAND","INSTANTANÉ EN COURS","LOPENDE MOMENTOPNAME") else t("Saved trip","Gespeicherte Fahrt","Trajet conservé","Bewaarde rit"),
                t("Vehicle","Fahrzeug","Véhicule","Voertuig")+": ${trip.optString("vehicle","—")}",
                t("Car odometer","Fahrzeug-Kilometerstände","Compteur du véhicule","Kilometerstanden voertuig")+": ${trip.opt("odo_start") ?: "—"} / ${trip.opt("odo_end") ?: "—"} km",
                t("Hidden-area radius","Radius der verborgenen Bereiche","Rayon masqué","Straal verborgen gebied")+": $radius m; "+t("Visible track","Sichtbarer Track","Tracé visible","Zichtbare route")+": %.3f km".format(geometric/1000),"",scope,"",
                t("Visible route, times and photo content may still reveal locations. Original facts and counters do not change. Shared files cannot be recalled.",
                    "Sichtbare Route, Zeiten und Bildinhalte können weiterhin Orte verraten. Originale und Zähler bleiben unverändert. Geteilte Dateien können nicht zurückgerufen werden.",
                    "Le tracé visible, les horaires et les images peuvent encore révéler des lieux. Originaux et compteurs inchangés. Les fichiers partagés ne peuvent être rappelés.",
                    "Zichtbare route, tijden en beelden kunnen locaties onthullen. Originelen en tellers blijven gelijk. Gedeelde bestanden kunnen niet worden teruggehaald."))
            val wrapped=lines.flatMap { line ->
                val result=mutableListOf<String>();var current=""
                line.split(' ').flatMap {it.chunked(76).ifEmpty {listOf("")}}.forEach {word ->if(current.length+word.length+1>76) {result+=current;current=""};current+=if(current.isEmpty()) word else " $word"}
                result+=current;result
            }
            val pdf=PdfDocument();try {
                wrapped.chunked(35).forEachIndexed {pageIndex,pageLines ->
                    val page=pdf.startPage(PdfDocument.PageInfo.Builder(595,842,pageIndex+1).create());val paint=Paint().apply {textSize=11f}
                    pageLines.forEachIndexed {i,line ->page.canvas.drawText(line,36f,40f+i*21f,paint)}
                    pdf.finishPage(page)
                }
                File(root,"overview.pdf").outputStream().use {pdf.writeTo(it)}
            } finally {pdf.close()}
            File(root,"omissions.json").writeText(JSONObject().put("items",omissions).put("raw_logs_included",logs).put("media_included",options.selectedMedia.isNotEmpty()).toString())
            val files=JSONArray()
            root.walkTopDown().filter { it.isFile }.sortedBy { it.relativeTo(root).path }.forEach { f -> files.put(JSONObject().put("file",f.relativeTo(root).invariantSeparatorsPath).put("bytes",f.length()).put("sha256",hash(f))) }
            File(root,"manifest.json").writeText(JSONObject(metadata.toString()).put("files",files).put("masked",masked).put("raw_logs_included",logs).put("omitted_media",omissions).put("coverage_gaps",allEvents.count {it.optString("kind")=="gap"}).put("snapshot_state",trip.optString("state")).put("coverage",JSONArray(events.filter { it.optString("kind")=="gap" })).put("omissions",omissions).toString(2))
            return root
        } catch(failure:Exception) { root.deleteRecursively();throw failure }
    }
    private fun key(passphrase:String,salt:ByteArray,iterations:Int):SecretKeySpec {
        require(passphrase.length>=8) { "Use a backup passphrase with at least 8 characters" }
        val spec=PBEKeySpec(passphrase.toCharArray(),salt,iterations,256)
        return try { SecretKeySpec(SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded,"AES") } finally { spec.clearPassword() }
    }
    fun backup(context:Context,payload:JSONObject,passphrase:String):File {
        val salt=ByteArray(16).also { SecureRandom().nextBytes(it) }; val nonce=ByteArray(12).also { SecureRandom().nextBytes(it) }
        val cipher=Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE,key(passphrase,salt,100000),GCMParameterSpec(128,nonce))
        val sealed=nonce+cipher.doFinal(payload.toString().toByteArray(Charsets.UTF_8))
        val envelope=JSONObject().put("backup_version",1).put("cipher","AES-256-GCM").put("kdf","PBKDF2-HMAC-SHA256").put("iterations",100000)
            .put("salt",Base64.encodeToString(salt,Base64.NO_WRAP)).put("sealed",Base64.encodeToString(sealed,Base64.NO_WRAP)).put("sha256",hash(sealed))
        val root=File(context.filesDir,"trip-exports/backups").apply { check(isDirectory || mkdirs()) }
        return File(root,"youspeed-journal-${UUID.randomUUID()}.json").apply { writeText(envelope.toString()) }
    }
    fun readBackup(file:File,passphrase:String):JSONObject {
        require(file.isFile && file.length() in 1..512_000_000) { "Backup unavailable or too large" }
        val envelope=JSONObject(file.readText())
        require(envelope.getInt("backup_version")==1 && envelope.getString("cipher")=="AES-256-GCM" && envelope.getString("kdf")=="PBKDF2-HMAC-SHA256" && envelope.getInt("iterations")==100000) { "Unsupported backup version" }
        val salt=Base64.decode(envelope.getString("salt"),Base64.DEFAULT); val sealed=Base64.decode(envelope.getString("sealed"),Base64.DEFAULT)
        require(salt.size==16 && sealed.size>=28 && hash(sealed)==envelope.getString("sha256")) { "Backup checksum does not match" }
        val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key(passphrase,salt,100000),GCMParameterSpec(128,sealed.copyOfRange(0,12)))
        val payload=JSONObject(String(cipher.doFinal(sealed.copyOfRange(12,sealed.size)),Charsets.UTF_8))
        validateBackup(payload);return payload
    }
    fun backupPreview(file:File,passphrase:String):JSONObject {
        val p=readBackup(file,passphrase)
        return JSONObject().put("trip_count",p.getJSONArray("trips").length()).put("event_count",p.getJSONArray("events").length()).put("counters",p.getJSONArray("counters").getJSONObject(0))
    }
    fun validateBackup(payload:JSONObject) {
        require(payload.getInt("schema_version")==1 && payload.getString("kind")=="youspeed-journal-backup") { "Unsupported journal schema" }
        val counters=payload.getJSONArray("counters");require(counters.length()==1)
        val counter=counters.getJSONObject(0);require(counter.getInt("id")==1)
        listOf("origin","distance","usage").forEach { require(counter.getDouble(it).isFinite() && counter.getDouble(it)>=0) }
        val trips=payload.getJSONArray("trips");val ids=mutableSetOf<String>()
        for(i in 0 until trips.length()) {
            val t=trips.getJSONObject(i);UUID.fromString(t.getString("id"));require(ids.add(t.getString("id"))) { "Duplicate trip identity" }
            listOf("start","end","distance","duration").forEach { require(t.getDouble(it).isFinite() && t.getDouble(it)>=0) }
            require(t.getString("state") in listOf("active","finalizing","ended","interrupted","disabled"))
        }
        val events=payload.getJSONArray("events");val sequences=mutableSetOf<Long>()
        for(i in 0 until events.length()) {
            val e=events.getJSONObject(i);require(e.getString("trip") in ids && sequences.add(e.getLong("seq")) && e.getLong("seq")>0)
            require(e.getDouble("time").isFinite());require(e.getString("kind").length in 1..120);JSONObject(e.getString("payload"))
        }
        val bindings=payload.getJSONArray("bindings");val sessions=mutableSetOf<String>()
        for(i in 0 until bindings.length()) { val b=bindings.getJSONObject(i);require(b.getString("trip") in ids && sessions.add(b.getString("session"))) }
    }
}
