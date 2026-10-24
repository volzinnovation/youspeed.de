package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId

/** Declarative bundle producer adapter; reference-policy semantics stay separate. */
object ConditionalSpeedRules {
    data class Result(val kmh: Int?, val unlimited: Boolean, val unresolved: Boolean, val reason: String, val reevaluation: Reevaluation? = null)
    data class Reevaluation(val rulesJSON: String, val baseKmh: Int?, val baseUnlimited: Boolean, val direction: Int?, val countryCode: String?, val timeZoneId: String? = null) {
        fun evaluate(atMs: Long): Result = try { ConditionalSpeedRules.evaluate(JSONObject(rulesJSON), Context(atMs = atMs, timeZoneId = timeZoneId, countryCode = countryCode, direction = direction), baseKmh, baseUnlimited) }
            catch (_: Exception) { unknown("corrupt_rule_set") }
    }
    data class Context(
        val atMs: Long = System.currentTimeMillis(), val timeZoneId: String? = null,
        val countryCode: String? = null, val direction: Int? = null,
        val vehicle: String = "motorcar", val facts: Map<String, Boolean> = emptyMap(),
        val clockTrusted: Boolean = true,
    )

    fun resolve(db: SQLiteDatabase, wayId: String, direction: Int?, baseKmh: Int?, baseUnlimited: Boolean,
                atMs: Long = System.currentTimeMillis(), timeZoneId: String? = null, countryCode: String? = null): Result? {
        val hasCapability = try { db.rawQuery("SELECT version,grammar FROM road_speed_capability", null).use {
            if (!it.moveToFirst() || it.getInt(0) != 1 || it.getString(1) != "youspeed-osm-speed-1" || it.moveToNext()) return unknown("unsupported_conditional_capability")
            true
        } } catch (_: android.database.sqlite.SQLiteException) {
            if (tableExists(db, "road_speed_capability") || tableExists(db, "road_speed_rule_set")) return unknown("incomplete_conditional_capability")
            false
        }
        val raw = try {
            db.rawQuery("SELECT rules_json FROM road_speed_rule_set WHERE way_id=?", arrayOf(wayId)).use {
                if (it.moveToFirst()) it.getString(0) else null
            }
        } catch (_: android.database.sqlite.SQLiteException) { return if (hasCapability) unknown("incomplete_conditional_capability") else legacyUnresolved(db, wayId, direction) }
        if (raw == null) return null
        if (raw.length > 262_144) return unknown("oversized_rule_set")
        return try { evaluate(JSONObject(raw), Context(atMs, timeZoneId, countryCode, direction), baseKmh, baseUnlimited)
            .copy(reevaluation = Reevaluation(raw, baseKmh, baseUnlimited, direction, countryCode, timeZoneId)) }
        catch (_: Exception) { unknown("corrupt_rule_set") }
    }

    private fun tableExists(db: SQLiteDatabase, name: String): Boolean = db.rawQuery(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", arrayOf(name),
    ).use { it.moveToFirst() }

    private fun unknown(reason: String) = Result(null, false, true, reason)
    private fun legacyUnresolved(db: SQLiteDatabase, wayId: String, direction: Int?): Result? {
        val electronic = try {
            val cursor = try { db.rawQuery("SELECT maxspeed,maxspeed_forward,maxspeed_backward FROM ways WHERE way_id=?", arrayOf(wayId)) }
                catch (_: android.database.sqlite.SQLiteException) { db.rawQuery("SELECT maxspeed FROM ways WHERE way_id=?", arrayOf(wayId)) }
            cursor.use {
                if (!it.moveToFirst()) false else {
                    val scoped = if (direction == 1) 1 else 2
                    val raw = if (it.columnCount == 3 && direction != null && !it.getString(scoped).isNullOrBlank()) it.getString(scoped) else it.getString(0)
                    raw?.trim()?.lowercase() in setOf("signals", "variable", "dynamic")
                }
            }
        } catch (_: android.database.sqlite.SQLiteException) { false }
        if (electronic) return unknown("electronic_sign_state_unknown")
        val raw = try { db.rawQuery("SELECT lane_tags_json FROM traffic_sign_way_direction WHERE way_id=? LIMIT 1", arrayOf(wayId)).use {
            if (it.moveToFirst()) it.getString(0) else null
        } } catch (_: android.database.sqlite.SQLiteException) { return null }
        val tags = try { raw?.let(::JSONObject) } catch (_: Exception) { null } ?: return null
        for (key in tags.keys()) {
            if (!key.startsWith("maxspeed")) continue
            val parts = key.split(':')
            if (parts.any { it in setOf("hgv", "bus", "motorcycle", "reason", "type") }) continue
            if ("forward" in parts && direction == -1 || "backward" in parts && direction == 1) continue
            if ("conditional" in parts || "variable" in parts && tags.optString(key) != "no") return unknown("legacy_conditional_rules_not_compiled")
        }
        return null
    }
    private fun JSONArray.objects(): List<JSONObject> = (0 until length()).mapNotNull { optJSONObject(it) }
    private fun JSONArray.ints(): List<Int> = (0 until length()).map { optInt(it, -1) }
    private fun JSONArray.strings(): List<String> = (0 until length()).map { optString(it) }

    fun evaluate(rules: JSONObject, context: Context, baseKmh: Int?, baseUnlimited: Boolean): Result {
        val allTags = rules.optJSONArray("tags")?.objects() ?: return unknown("unsupported_rule_set")
        if (rules.optInt("version") != 1 || rules.optString("grammar") != "youspeed-osm-speed-1" || allTags.size > 128) return unknown("unsupported_rule_set")
        val tags = allTags.filter { it.optString("role") == "speed" &&
            it.optString("vehicle") in setOf("all", "vehicle", "motor_vehicle", context.vehicle, "hazmat")
        }.sortedBy { it.optInt("priority") * 2 + if (it.optBoolean("conditional")) 1 else 0 }
        if (allTags.any { it.optString("role") == "variable" && it.optString("raw").lowercase() != "no" }) return unknown("variable_sign_state_unknown")
        val keys = sortedSetOf<String>()
        fun fact(key: String, assignment: Map<String, Boolean>): Boolean {
            return context.facts[key] ?: assignment[key] ?: run { keys.add(key); false }
        }
        fun truth(node: JSONObject, assignment: Map<String, Boolean>, depth: Int = 0): Boolean {
            if (depth >= 20) return fact("unsupported_depth", assignment)
            return when (node.optString("kind")) {
                "true" -> true
                "context" -> fact(node.optString("field", "unknown"), assignment)
                "not" -> !truth(node.optJSONObject("item") ?: JSONObject(), assignment, depth + 1)
                "all" -> (node.optJSONArray("items")?.objects() ?: listOf(JSONObject())).map { truth(it, assignment, depth + 1) }.all { it }
                "any" -> (node.optJSONArray("items")?.objects() ?: listOf(JSONObject())).map { truth(it, assignment, depth + 1) }.any { it }
                "schedule" -> {
                    val zone = context.timeZoneId ?: if (context.countryCode?.uppercase() in setOf("DE", "DEU")) "Europe/Berlin" else null
                    val local = if (context.clockTrusted && zone != null) try { Instant.ofEpochMilli(context.atMs).atZone(ZoneId.of(zone)) } catch (_: Exception) { null } else null
                    if (local == null) fact("schedule:" + canonical(node), assignment)
                    else {
                        val minute = local.hour * 60 + local.minute
                        val windows = node.optJSONArray("windows")
                        val anchors = mutableListOf<java.time.ZonedDateTime>()
                        if (windows == null || windows.length() == 0) anchors.add(local)
                        if (windows != null) for (i in 0 until windows.length()) {
                            val window = windows.optJSONArray(i) ?: continue
                            if (window.length() != 2) continue
                            val start = window.optInt(0); val end = window.optInt(1)
                            if (start < end && minute >= start && minute < end) anchors.add(local)
                            if (start > end) {
                                if (minute >= start) anchors.add(local)
                                else if (minute < end) anchors.add(local.minusDays(1))
                            }
                        }
                        val weekdays = node.optJSONArray("weekdays")?.ints() ?: emptyList()
                        val holidays = node.optJSONArray("holidays")?.strings() ?: emptyList()
                        anchors.map { anchor ->
                            val annual = anchor.monthValue * 100 + anchor.dayOfMonth
                            val start = node.optInt("annual_start", 0); val end = node.optInt("annual_end", 0)
                            val dateMatches = start == 0 || end == 0 || if (start <= end) annual in start..end else annual >= start || annual <= end
                            val holidayMatches = holidays.map { fact("$it:${anchor.year}-$annual", assignment) }.any { it }
                            dateMatches && (weekdays.isEmpty() && holidays.isEmpty() || anchor.dayOfWeek.value in weekdays || holidayMatches)
                        }.any { it }
                    }
                }
                else -> fact("unsupported_condition", assignment)
            }
        }
        fun outcome(assignment: Map<String, Boolean>): String {
            var selected = if (baseUnlimited) "unlimited" else baseKmh?.let { "numeric:$it" } ?: "unknown"
            for (tag in tags) {
                val direction = tag.optInt("direction")
                if (direction != 0) {
                    if (context.direction != null) { if (context.direction != direction) continue }
                    else if (fact("direction_forward", assignment) != (direction == 1)) continue
                }
                if (tag.optString("vehicle") == "hazmat" && !fact("vehicle_hazmat", assignment)) continue
                if (tag.optString("status") != "supported") { selected = "unsupported"; continue }
                for (clause in tag.optJSONArray("clauses")?.objects() ?: emptyList()) {
                    if (truth(clause.optJSONObject("condition") ?: JSONObject(), assignment)) {
                        val limit = clause.optJSONObject("limit") ?: JSONObject()
                        val kmh = limit.optDouble("kmh", Double.NaN)
                        selected = when {
                            limit.optString("kind") == "unlimited" -> "unlimited"
                            kmh.isFinite() && kmh > 0 && kmh <= 400 -> "numeric:${kotlin.math.floor(kmh + 0.5).toInt()}"
                            else -> "unsupported"
                        }
                    }
                }
            }
            return selected
        }
        outcome(emptyMap())
        for (tag in tags) {
            if (tag.optInt("direction") != 0 && context.direction == null) fact("direction_forward", emptyMap())
            if (tag.optString("vehicle") == "hazmat") fact("vehicle_hazmat", emptyMap())
            for (clause in tag.optJSONArray("clauses")?.objects() ?: emptyList()) truth(clause.optJSONObject("condition") ?: JSONObject(), emptyMap())
        }
        if (keys.size > 12) return unknown("too_many_unknown_contexts")
        val ordered = keys.toList()
        val outcomes = (0 until (1 shl ordered.size)).map { mask ->
            outcome(ordered.mapIndexed { index, key -> key to (mask and (1 shl index) != 0) }.toMap())
        }.toSet()
        val selected = outcomes.singleOrNull() ?: return unknown("conditional_applicability_unresolved")
        if (selected == "unsupported" || selected == "unknown") return unknown("conditional_applicability_unresolved")
        return Result(selected.removePrefix("numeric:").toIntOrNull(), selected == "unlimited", false, "conditional_rules_evaluated")
    }

    private fun canonical(value: Any?): String = when (value) {
        is JSONObject -> value.keys().asSequence().toList().sorted().joinToString(",", "{", "}") { JSONObject.quote(it) + ":" + canonical(value.opt(it)) }
        is JSONArray -> (0 until value.length()).joinToString(",", "[", "]") { canonical(value.opt(it)) }
        is String -> JSONObject.quote(value)
        else -> value.toString()
    }
}
