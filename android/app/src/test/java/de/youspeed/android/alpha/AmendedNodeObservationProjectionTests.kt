package de.youspeed.android.alpha

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class AmendedNodeObservationProjectionTests {
    private fun tag(key: String = "maxspeed", kmh: Int = 40, vehicle: String = "all",
                    conditional: Boolean = false, condition: String = "true"): JsonObject = buildJsonObject {
        put("key", key); put("raw", "50"); put("role", "speed"); put("vehicle", vehicle)
        put("direction", 0); put("lane", false); put("conditional", conditional); put("status", "supported")
        putJsonArray("clauses") { add(buildJsonObject {
            putJsonObject("limit") { put("kind", "numeric"); put("kmh", kmh) }
            putJsonObject("condition") { put("kind", condition) }
        }) }
    }
    private fun rules(vararg tags: JsonObject) = buildJsonObject {
        put("version", 1); put("grammar", "youspeed-osm-speed-1"); put("tags", JsonArray(tags.toList()))
    }.toString()
    private fun JsonObject.with(key: String, value: JsonElement) = JsonObject(toMutableMap().apply { put(key, value) })
    private fun projection(rules: String, raw: String? = "50") = AmendedNodeObservationProjection.numericValue(rules, raw)

    @Test fun correctedFixedBaseChangesObservationWithoutRewritingSourceEvidence() {
        val corrected = rules(tag())
        assertEquals(40.0, projection(corrected)!!, 0.0)
        assertEquals("50", Json.parseToJsonElement(corrected).jsonObject["tags"]!!.jsonArray[0].jsonObject["raw"]!!.jsonPrimitive.content)
        assertEquals(40.0, projection(corrected, null)!!, 0.0)
    }

    @Test fun hgvAndWetRestrictionsDoNotBecomeThePhysicalBase() {
        val hgv = tag("maxspeed:hgv", 25, "hgv")
        val wet = tag("maxspeed:conditional", 30, conditional = true, condition = "context")
        assertEquals(50.0, projection(rules(hgv, wet))!!, 0.0)
        assertEquals(50.0, projection(rules(tag(kmh = 50), hgv, wet))!!, 0.0)
    }

    @Test fun unknownVariableUnlimitedOrConflictingBaseCannotInventNumericObservation() {
        val base = tag()
        val clause = base["clauses"]!!.jsonArray.single().jsonObject
        for (kind in listOf("unknown", "unlimited")) {
            val changed = base.with("clauses", JsonArray(listOf(clause.with("limit", buildJsonObject { put("kind", kind) }))))
            assertNull(projection(rules(changed)))
        }
        assertNull(projection(rules(base.with("status", JsonPrimitive("unsupported")))))
        assertNull(projection(rules(base, tag(kmh = 60))))
        assertNull(projection(rules(base.with("clauses", JsonArray(listOf(clause, clause))))))
        assertNull(projection(rules(base, buildJsonObject { put("role", "variable"); put("raw", "yes") })))
        assertNull(projection("broken JSON"))
    }

    @Test fun explicitUnitsAndMalformedUniversalBaseStayUnknown() {
        for (raw in listOf("30 mph", "DE:urban", "signals", "NaN", "Infinity", "0", "401"))
            assertNull(raw, projection(rules(tag()), raw))
        assertNull(projection(rules(tag().with("direction", JsonPrimitive(1)))))
        assertNull(projection(rules(tag().with("lane", JsonPrimitive(true)))))
        assertNull(projection(rules(tag().with("lane", JsonPrimitive("false")))))
        assertNull(projection(rules(tag().with("conditional", JsonPrimitive("true")))))
        assertNull(projection(rules(tag("maxspeed:forward"))))
        assertNull(projection(rules(JsonObject(tag().toMutableMap().apply { remove("conditional") }))))
        val base = tag()
        val clause = base["clauses"]!!.jsonArray.single().jsonObject
        assertNull(projection(rules(base.with("clauses", JsonArray(listOf(clause.with("limit", buildJsonObject {
            put("kind", "numeric"); put("kmh", true)
        })))))))
    }
}
