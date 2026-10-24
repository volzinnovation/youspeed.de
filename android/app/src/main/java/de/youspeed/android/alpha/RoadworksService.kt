package de.youspeed.android.alpha

import android.content.Context
import android.location.Location
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.compose.runtime.*
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.Executors
import kotlin.math.ceil

/** Optional public data; requests never include GPS, road or installation IDs. */
internal class RoadworksService internal constructor(context: Context, preferencesName: String = "roadworks", private val transport: ((String, String?, Int, Long) -> Reply)? = null) {
    companion object {
        @Volatile private var instance: RoadworksService? = null
        fun get(context: Context): RoadworksService = instance ?: synchronized(this) {
            instance ?: RoadworksService(context.applicationContext).also { instance = it }
        }
    }
    private val preferences = context.getSharedPreferences(preferencesName, Context.MODE_PRIVATE)
    var enabled by mutableStateOf(preferences.getBoolean("enabled", false)); private set
    var status by mutableStateOf(if (enabled) "unavailable" else "off"); private set
    var card by mutableStateOf<RoadworksRelevance.Card?>(null); private set
    var nearby by mutableStateOf<List<Pair<RoadworksAdvisory.Feature, Double>>>(emptyList()); private set
    private val handler = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor { Thread(it, "roadworks-download").apply { isDaemon = true } }
    private val directory = File(context.cacheDir, preferencesName)
    private var cache = RoadworksSnapshotCache()
    private var manifest: RoadworksAdvisory.Manifest? = null
    private var receivedUptime = Double.NEGATIVE_INFINITY
    private val relevance = RoadworksRelevance()
    private var fix: RoadworksRelevance.Fix? = null
    private var driving = false; private var foreground = false
    @Volatile private var generation = 0L
    @Volatile private var connection: HttpURLConnection? = null
    private var loading = false; private var nextAttempt = 0.0; private var failures = 0; private var etag: String? = null
    private var transportState: String? = null
    private val heartbeat = object : Runnable {
        override fun run() {
            if (!enabled || !driving || !foreground) return
            evaluate(); refresh(); handler.postDelayed(this, 1000)
        }
    }
    private fun uptime() = SystemClock.elapsedRealtime() / 1000.0
    val sourceAgeMinutes: Long? get() {
        val value = manifest ?: return null
        val oldest = minOf(value.sourcePublication ?: return null, value.sourceModified ?: return null)
        if (!receivedUptime.isFinite()) return null
        return ((value.serverTime.toEpochMilli() - oldest.toEpochMilli()) / 1000.0 + uptime() - receivedUptime).takeIf { it.isFinite() && it >= 0 }?.let { (it / 60).toLong() }
    }
    init {
        val initialGeneration = generation
        worker.execute {
            val restored = listOf("manifest.json", "previous-manifest.json").firstNotNullOfOrNull { name -> runCatching {
                val value = RoadworksAdvisory.parseManifest(File(directory, name).readBytes())
                val cached = RoadworksSnapshotCache()
                value.snapshotId?.let { id -> cached.install(File(directory, "$id.json").readBytes(), value) }
                cached to value
            }.getOrNull() }
            handler.post { if (generation == initialGeneration && manifest == null && restored != null) { cache = restored.first; manifest = restored.second; evaluate() } }
        }
    }
    fun updateEnabled(value: Boolean) {
        enabled = value; preferences.edit().putBoolean("enabled", value).apply()
        generation++; connection?.disconnect(); loading = false; card = null; nearby = emptyList(); relevance.reset(); nextAttempt = 0.0; transportState = null
        handler.removeCallbacks(heartbeat)
        status = if (value) "unavailable" else "off"
        if (value) { session(driving, foreground); refresh(explicit = true) }
    }
    fun clearCache() {
        generation++; connection?.disconnect(); loading = false; manifest = null; etag = null; transportState = null
        cache = RoadworksSnapshotCache(); relevance.reset(); card = null; nearby = emptyList()
        worker.execute { directory.deleteRecursively() }; status = if (enabled) "unavailable" else "off"
    }
    fun update(location: Location) {
        val copied = Location(location)
        if (Looper.myLooper() != Looper.getMainLooper()) { handler.post { update(copied) }; return }
        fix = RoadworksRelevance.Fix(RoadworksAdvisory.Point(copied.latitude, copied.longitude), Instant.ofEpochMilli(copied.time), if (copied.hasAccuracy() && copied.provider != android.location.LocationManager.NETWORK_PROVIDER) copied.accuracy.toDouble() else Double.POSITIVE_INFINITY)
        evaluate()
    }
    fun session(driving: Boolean, foreground: Boolean) {
        val entered = driving && foreground && !(this.driving && this.foreground)
        this.driving = driving; this.foreground = foreground
        if (!driving || !foreground) { if (loading) { generation++; connection?.disconnect(); loading = false }; relevance.reset(); card = null }
        handler.removeCallbacks(heartbeat)
        if (enabled && driving && foreground) handler.postDelayed(heartbeat, 1000)
        if (entered) nextAttempt = 0.0
        evaluate(); if (driving && foreground) refresh()
    }
    private fun evaluate() {
        val freshness = manifest?.freshness(receivedUptime, uptime()) ?: RoadworksAdvisory.Freshness.UNAVAILABLE
        if (enabled && !loading) status = transportState ?: if (fix == null) "no_gps" else freshness.name.lowercase()
        card = relevance.update(cache.snapshot, freshness, fix, Instant.now(), enabled, driving, foreground)
        nearby = if (enabled && manifest?.enabled == true && fix != null) cache.snapshot?.features.orEmpty().map { it to RoadworksAdvisory.distance(fix!!.point, it) }
            .filter { it.second <= 5000 }.sortedWith(compareBy<Pair<RoadworksAdvisory.Feature, Double>> { it.second }.thenBy { it.first.id }) else emptyList()
    }
    fun refresh(explicit: Boolean = false) {
        if (!enabled || loading || !explicit && (!driving || !foreground || uptime() < nextAttempt)) return
        if (!explicit) { val p = fix?.point ?: return; if (p.latitude !in 47.4..49.9 || p.longitude !in 7.3..10.7) return }
        val token = generation; val validator = etag; val oldManifest = manifest; val oldBytes = cache.bytes
        loading = true; status = "loading"; nextAttempt = uptime() + 300 + Math.random() * 15
        worker.execute {
            var retryAfter = 0.0
            val result = runCatching {
                val reply = (transport ?: ::fetch)("/youspeed/live/v1/regions/DE-BW", validator, 262144, token)
                retryAfter = reply.retryAfter
                if (reply.code in 400..499 && reply.code !in setOf(408, 429)) retryAfter = maxOf(300.0, retryAfter)
                if (reply.code == 304) { require(oldManifest != null); return@runCatching null }
                require(reply.code == 200) { "roadworks_http_${reply.code}" }
                var candidate = RoadworksAdvisory.parseManifest(reply.bytes)
                if (reply.date != null) candidate = candidate.validatedHttpClock(reply.date, reply.age)
                val bytes = if (candidate.enabled && candidate.snapshotId != null) {
                    if (candidate.snapshotId == oldManifest?.snapshotId && oldBytes != null) oldBytes
                    else (transport ?: ::fetch)(requireNotNull(candidate.snapshotPath), null, 8388608, token).also { require(it.code == 200) }.bytes
                } else null
                val validated = RoadworksSnapshotCache()
                if (bytes != null) validated.install(bytes, candidate)
                check(token == generation)
                check(directory.isDirectory || directory.mkdirs())
                if (bytes != null) atomic(File(directory, "${candidate.snapshotId}.json"), bytes)
                val current = File(directory, "manifest.json")
                if (current.isFile) atomic(File(directory, "previous-manifest.json"), current.readBytes())
                atomic(current, reply.bytes)
                val keep = setOf("manifest.json", "previous-manifest.json", "${candidate.snapshotId}.json", "${oldManifest?.snapshotId}.json")
                directory.listFiles()?.filter { it.name !in keep }?.forEach { it.delete() }
                Triple(candidate, if (bytes != null) validated else null, reply.etag)
            }
            handler.post {
                if (token != generation) return@post
                loading = false
                if (result.isSuccess) {
                    result.getOrNull()?.let { (value, cached, validatorValue) -> manifest = value; if (cached != null) cache = cached; receivedUptime = uptime(); etag = validatorValue }
                    failures = 0; transportState = null; evaluate()
                } else {
                    failures++; nextAttempt = uptime() + maxOf(retryAfter, listOf(30.0, 120.0, 300.0)[minOf(2, failures - 1)]) + Math.random() * 5
                    transportState = if (result.exceptionOrNull()?.message?.contains("unsupported_roadworks_version") == true) "update_required" else if (cache.snapshot == null) "unavailable" else "offline"
                    evaluate()
                }
            }
        }
    }
    internal data class Reply(val code: Int, val bytes: ByteArray, val etag: String?, val date: Instant?, val age: Double, val retryAfter: Double)
    private fun fetch(path: String, validator: String?, limit: Int, token: Long): Reply {
        require(path.startsWith("/youspeed/live/v1/regions/DE-BW") && !path.contains('?') && !path.contains('#') && !path.contains(".."))
        val request = URL("https://live-eu.woladen.de$path").openConnection() as HttpURLConnection
        connection = request
        try {
            request.instanceFollowRedirects = false; request.connectTimeout = 15000; request.readTimeout = 20000
            request.setRequestProperty("Accept", "application/json, application/geo+json")
            if (validator != null) request.setRequestProperty("If-None-Match", validator)
            val code = request.responseCode
            require(request.contentLengthLong <= 2097152)
            val bytes = if (code == 200) request.inputStream.use { input ->
                val output = java.io.ByteArrayOutputStream(); val buffer = ByteArray(8192)
                while (true) { check(token == generation); val count = input.read(buffer); if (count < 0) break; require(output.size() + count <= limit); output.write(buffer, 0, count) }
                output.toByteArray()
            } else ByteArray(0)
            val date = request.getHeaderField("Date")?.let { runCatching { ZonedDateTime.parse(it, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant() }.getOrNull() }
            val retryHeader = request.getHeaderField("Retry-After")
            val retry = (retryHeader?.toDoubleOrNull() ?: retryHeader?.let { runCatching { (ZonedDateTime.parse(it, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant().toEpochMilli() - System.currentTimeMillis()) / 1000.0 }.getOrNull() } ?: 0.0).coerceIn(0.0, 86400.0)
            return Reply(code, bytes, request.getHeaderField("ETag"), date, request.getHeaderField("Age")?.toDoubleOrNull() ?: 0.0, retry)
        } finally { request.disconnect(); if (connection === request) connection = null }
    }
    private fun atomic(file: File, bytes: ByteArray) {
        val temp = File(file.parentFile, file.name + ".tmp"); temp.outputStream().use { it.write(bytes); it.flush() }
        check(temp.renameTo(file)) { "roadworks_cache_write_failed" }
    }
    internal fun awaitDownloadsForTests() { worker.submit {}.get(5, java.util.concurrent.TimeUnit.SECONDS) }
}

private fun roadworksText(en: String, de: String, fr: String, nl: String) = ConsumerUiStrings.text(en, de, fr, nl)
private fun roadworksStatusText(status: String): String = when (status) {
    "off" -> roadworksText("Off", "Aus", "Désactivé", "Uit")
    "loading" -> roadworksText("Updating reports…", "Meldungen werden aktualisiert…", "Actualisation des signalements…", "Meldingen worden bijgewerkt…")
    "fresh" -> roadworksText("Reports available", "Meldungen verfügbar", "Signalements disponibles", "Meldingen beschikbaar")
    "delayed" -> roadworksText("Publisher updates delayed", "Aktualisierung des Anbieters verzögert", "Mises à jour du fournisseur retardées", "Updates van de bron vertraagd")
    "offline" -> roadworksText("Offline · saved reports", "Offline · gespeicherte Meldungen", "Hors ligne · signalements enregistrés", "Offline · opgeslagen meldingen")
    "update_required" -> roadworksText("App update required for these reports", "App-Update für diese Meldungen erforderlich", "Mise à jour de l’app nécessaire", "App-update nodig voor deze meldingen")
    "no_gps" -> roadworksText("Location unavailable · parked BW download available", "Standort fehlt · BW-Download im Stand verfügbar", "Position indisponible · téléchargement BW à l’arrêt", "Locatie niet beschikbaar · BW-download bij stilstand")
    "requested", "approved" -> roadworksText("Reported as planned", "Als geplant gemeldet", "Signalé comme prévu", "Gemeld als gepland")
    "implemented" -> roadworksText("Reported as in effect", "Als wirksam gemeldet", "Signalé comme en cours", "Gemeld als van kracht")
    "resolved" -> roadworksText("Work periods available", "Arbeitszeiträume verfügbar", "Périodes de travaux disponibles", "Werkperioden beschikbaar")
    else -> roadworksText("Report availability or work period uncertain", "Verfügbarkeit oder Arbeitszeitraum ungewiss", "Disponibilité ou période de travaux incertaine", "Beschikbaarheid of werkperiode onzeker")
}

private fun roadworksKindText(kind: String) = when (kind) {
    "closure" -> roadworksText("Reported closure", "Gemeldete Sperrung", "Fermeture signalée", "Gemelde afsluiting")
    "roadworks" -> roadworksText("Reported roadworks", "Gemeldete Baustelle", "Travaux signalés", "Gemelde wegwerkzaamheden")
    else -> roadworksText("Report type uncertain", "Meldungsart ungewiss", "Type de signalement incertain", "Soort melding onzeker")
}

private fun roadworksAgeText(age: Long?): String =
    roadworksText("Source age", "Alter der Quelldaten", "Âge des données source", "Leeftijd brongegevens") + ": " +
        (age?.let { "$it min" } ?: roadworksText("unknown", "unbekannt", "inconnu", "onbekend"))

private fun roadworksDirectionText(direction: String): String {
    val value = when (direction) {
        "unknown" -> roadworksText("unknown", "unbekannt", "inconnu", "onbekend")
        "one_direction" -> roadworksText("one direction", "eine Richtung", "un seul sens", "één richting")
        else -> direction
    }
    val source = if (direction == "both") roadworksText("Publisher: both directions", "Anbieter: beide Richtungen", "Fournisseur : deux sens", "Bron: beide richtingen")
        else roadworksText("Publisher direction", "Richtungsangabe des Anbieters", "Sens indiqué par le fournisseur", "Richting volgens de bron") + ": " + value
    return source + " · " + roadworksText("Your road/direction is unverified", "Eigene Straße/Fahrtrichtung nicht bestätigt", "Votre route et votre sens ne sont pas vérifiés", "Uw weg/rijrichting is niet bevestigd")
}

@Composable internal fun RoadworksSettingsSection() {
    val service = RoadworksService.get(LocalContext.current)
    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(roadworksText("Live roadworks", "Live-Baustellen", "Travaux en direct", "Actuele wegwerkzaamheden"), style = MaterialTheme.typography.titleMedium)
        Row { Text(roadworksText("Reported roadworks in BW", "Gemeldete Baustellen in BW", "Travaux signalés en BW", "Gemelde wegwerkzaamheden in BW"), Modifier.weight(1f)); Switch(service.enabled, service::updateEnabled) }
        Text(roadworksText("Optional Wi-Fi/cellular updates. Proximity stays on this phone. Partial, possibly delayed reports; no change to speed limits.", "Optionale Updates über WLAN/Mobilfunk. Nähe wird auf dem Telefon berechnet. Unvollständige, möglicherweise verspätete Meldungen; keine Änderung der Tempolimits.", "Mises à jour facultatives Wi-Fi/mobile. Proximité calculée sur ce téléphone. Données partielles et parfois retardées ; aucun changement de limitation.", "Optionele wifi/mobiele updates. Nabijheid wordt op deze telefoon berekend. Onvolledige, mogelijk vertraagde meldingen; geen invloed op snelheidslimieten."), style = MaterialTheme.typography.bodySmall)
        if (service.enabled) {
            Text(roadworksStatusText(service.status), style = MaterialTheme.typography.bodySmall)
            Text(roadworksAgeText(service.sourceAgeMinutes), style = MaterialTheme.typography.bodySmall)
            OutlinedButton({ service.refresh(explicit = true) }) { Text(roadworksText("Refresh BW data", "BW-Daten aktualisieren", "Actualiser BW", "BW-gegevens vernieuwen")) }
            OutlinedButton(service::clearCache) { Text(roadworksText("Clear cached data", "Gespeicherte Daten löschen", "Effacer le cache", "Cache wissen")) }
            if (service.nearby.isEmpty() && service.status in setOf("fresh", "delayed")) Text(roadworksText("No reported roadworks nearby in the available data (5 km).", "In den verfügbaren Daten keine gemeldeten Baustellen in der Nähe (5 km).", "Aucun chantier signalé à proximité dans les données disponibles (5 km).", "Geen wegwerkzaamheden in de beschikbare gegevens in de buurt (5 km)."), style = MaterialTheme.typography.bodySmall)
            service.nearby.forEach { (feature, distance) ->
                Text(listOf("${feature.roadLabel} · ${distance.toInt()} m", roadworksKindText(feature.kind),
                    roadworksText("Source description (German)", "Quellbeschreibung (Deutsch)", "Description source (allemand)", "Bronbeschrijving (Duits)"),
                    feature.description, "${feature.outer.start} – ${feature.outer.end}",
                    "${roadworksStatusText(feature.operatorStatus)} · ${roadworksStatusText(feature.scheduleStatus)}",
                    roadworksDirectionText(feature.direction),
                    roadworksText("Source ID", "Quell-ID", "Identifiant source", "Bron-ID") + ": " + feature.id).joinToString("\n"))
            }
            Text("Verkehrsministerium Baden-Württemberg · BEMaS via MobiData BW · dl-de/by-2-0", style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable internal fun RoadworksDrivingAdvisory() {
    val service = RoadworksService.get(LocalContext.current)
    service.card?.let { card ->
        Text(listOf(roadworksText("Reported nearby", "In der Nähe gemeldet", "Signalé à proximité", "In de buurt gemeld"),
            roadworksKindText(card.feature.kind), card.feature.roadLabel, "${(ceil(card.distanceM / 10) * 10).toInt()} m",
            roadworksAgeText(service.sourceAgeMinutes),
            if (card.freshness == RoadworksAdvisory.Freshness.DELAYED) roadworksText("delayed", "verzögert", "retardé", "vertraagd") else "",
            if (service.status == "offline") roadworksText("offline", "offline", "hors ligne", "offline") else "")
            .filter { it.isNotEmpty() }.joinToString(" · "), style = MaterialTheme.typography.bodySmall)
    }
}
