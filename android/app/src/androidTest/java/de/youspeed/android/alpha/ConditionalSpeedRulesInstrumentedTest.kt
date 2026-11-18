package de.youspeed.android.alpha

import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertFalse
import org.junit.Test
import java.time.Instant

class ConditionalSpeedRulesInstrumentedTest {
    private fun nightRules()=JSONObject("""{"version":1,"grammar":"youspeed-osm-speed-1","tags":[{"role":"speed","vehicle":"all","direction":0,"conditional":true,"priority":0,"status":"supported","raw":"30 @ (22:00-06:00)","clauses":[{"limit":{"kind":"numeric","kmh":30},"source_span":[0,18],"condition":{"kind":"schedule","windows":[[1320,360]],"weekdays":[],"holidays":[]}}]}]}""")
    @Test fun drivingWetRuleKeepsNormalReferenceAndTranslatedPreview() {
        val rules=nightRules()
        val tag=rules.getJSONArray("tags").getJSONObject(0)
        tag.put("raw","30 @ (wet)")
        tag.getJSONArray("clauses").getJSONObject(0).put("source_span",org.json.JSONArray(listOf(0,10)))
            .put("condition",JSONObject().put("kind","context").put("field","road_surface_wet"))
        val rule=ConditionalSpeedRules.Reevaluation(rules.toString(),50,false,1,"DE")
        val result=rule.evaluate(0)
        assertEquals(50,result.kmh);assertFalse(result.unresolved)
        assertEquals(ConditionalSpeedPreview(30,"wet"),result.inactivePreview)
        val original=java.util.Locale.getDefault()
        try {
            java.util.Locale.setDefault(java.util.Locale.GERMAN)
            assertEquals("Bei Nässe",result.inactivePreview?.localizedRestrictionText)
        } finally {java.util.Locale.setDefault(original)}
        assertTrue(ConditionalSpeedRules.evaluate(rules,ConditionalSpeedRules.Context(countryCode="DE",direction=1),50,false).unresolved)
        assertTrue(rule.copy(baseKmh=null).evaluate(0).unresolved)
    }
    @Test fun associationRequiresMatchingNumberVehicleDirectionAndValidity() {
        val rules=nightRules()
        fun rule(direction:Int?=1)=ConditionalSpeedRules.Reevaluation(rules.toString(),50,false,direction,"DE")
        assertTrue(rule().containsConditionalLimit(30,0))
        assertFalse(rule().containsConditionalLimit(60,0))
        val tag=rules.getJSONArray("tags").getJSONObject(0)
        tag.put("direction",-1)
        assertFalse(rule().containsConditionalLimit(30,0));assertFalse(rule(null).containsConditionalLimit(30,0))
        tag.put("direction",0).put("vehicle","hgv")
        assertFalse(rule().containsConditionalLimit(30,0))
        tag.put("vehicle","all")
        assertFalse(rule().copy(validUntilUTC=0.0).containsConditionalLimit(30,0))
    }
    @Test fun outsideWindowUsesIndependentBaseAndNeverInventsOne() {
        val context=ConditionalSpeedRules.Context(atMs=Instant.parse("2026-10-23T10:00:00Z").toEpochMilli(),countryCode="DE",direction=1)
        assertEquals(90,ConditionalSpeedRules.evaluate(nightRules(),context,90,false).kmh)
        assertEquals(true,ConditionalSpeedRules.evaluate(nightRules(),context,null,true).unlimited)
        assertEquals(true,ConditionalSpeedRules.evaluate(nightRules(),context,null,false).unresolved)
    }
    @Test fun cachedReevaluationKeepsExplicitTimezoneAndHalfOpenBoundary() {
        android.database.sqlite.SQLiteDatabase.create(null).use { db ->
            db.execSQL("CREATE TABLE road_speed_capability(version INTEGER,grammar TEXT)")
            db.execSQL("INSERT INTO road_speed_capability VALUES(1,'youspeed-osm-speed-1')")
            db.execSQL("CREATE TABLE road_speed_rule_set(way_id INTEGER PRIMARY KEY,rules_json TEXT)")
            db.execSQL("INSERT INTO road_speed_rule_set VALUES(12,?)",arrayOf(nightRules().toString()))
            val initial=requireNotNull(ConditionalSpeedRules.resolve(db,"12",1,90,false,
                Instant.parse("2026-10-23T19:59:00Z").toEpochMilli(),"Europe/Paris","FR"))
            assertEquals(90,initial.kmh)
            assertEquals(ConditionalSpeedPreview(30, "22:00-06:00"),initial.inactivePreview)
            val cached=requireNotNull(initial.reevaluation)
            val active = cached.evaluate(Instant.parse("2026-10-23T20:00:00Z").toEpochMilli())
            assertEquals(30,active.kmh)
            assertEquals(null,active.inactivePreview)
            val expired = cached.evaluate(Instant.parse("2026-10-24T04:00:00Z").toEpochMilli())
            assertEquals(90,expired.kmh)
            assertEquals(initial.inactivePreview,expired.inactivePreview)
        }
    }
    @Test fun partialCapabilityCannotExecuteRulesOrRestoreScalarFallback() {
        for (schema in listOf("CREATE TABLE road_speed_capability(other TEXT)","CREATE TABLE road_speed_rule_set(way_id INTEGER,rules_json TEXT)")) {
            android.database.sqlite.SQLiteDatabase.create(null).use { db ->
                db.execSQL(schema)
                val result=ConditionalSpeedRules.resolve(db,"12",1,120,false)
                assertEquals(true,result?.unresolved)
                assertEquals(null,result?.kmh)
            }
        }
    }
    @Test fun legacyElectronicMarkerCannotInventRoadDefault() {
        android.database.sqlite.SQLiteDatabase.create(null).use { db ->
            db.execSQL("CREATE TABLE ways(way_id INTEGER,maxspeed TEXT)"); db.execSQL("INSERT INTO ways VALUES(716,'signals')")
            assertEquals(true, ConditionalSpeedRules.resolve(db, "716", 1, 100, false)?.unresolved)
        }
    }
    @Test fun brokenKnownCapabilityCannotRestoreScalarSpeed() {
        android.database.sqlite.SQLiteDatabase.create(null).use { db ->
            db.execSQL("CREATE TABLE road_speed_capability(version INTEGER,grammar TEXT)")
            db.execSQL("INSERT INTO road_speed_capability VALUES(1,'youspeed-osm-speed-1')")
            val result = ConditionalSpeedRules.resolve(db, "12", 1, 120, false)
            assertEquals(true, result?.unresolved)
            assertEquals(null, result?.kmh)
        }
    }
    @Test fun sharedConformance() {
        val fixtures = InstrumentationRegistry.getInstrumentation().targetContext.assets
            .open("conditional-speed-rules/conformance-v1.json").bufferedReader().use { JSONObject(it.readText()) }.getJSONArray("cases")
        for (index in 0 until fixtures.length()) {
            val row = fixtures.getJSONObject(index)
            val ctx = row.getJSONObject("context")
            val facts = ctx.optJSONObject("facts")?.let { json -> json.keys().asSequence().associateWith { json.getBoolean(it) } } ?: emptyMap()
            val result = ConditionalSpeedRules.evaluate(row.getJSONObject("rules"), ConditionalSpeedRules.Context(
                atMs = Instant.parse(ctx.getString("at")).toEpochMilli(), countryCode = ctx.optString("country_code"),
                direction = if (ctx.isNull("direction")) null else ctx.getInt("direction"), facts = facts,
                clockTrusted = ctx.optBoolean("clock_trusted", true),
            ), if (row.isNull("base_kmh")) null else row.getInt("base_kmh"), row.getBoolean("base_unlimited"))
            val expected = row.getJSONObject("expected")
            assertEquals(row.getString("id"), if (expected.isNull("kmh")) null else expected.getInt("kmh"), result.kmh)
            assertEquals(row.getString("id"), expected.getBoolean("unlimited"), result.unlimited)
            assertEquals(row.getString("id"), expected.getBoolean("unresolved"), result.unresolved)
        }
    }
}
