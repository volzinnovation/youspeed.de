package de.youspeed.android.alpha

import java.io.File
import kotlinx.serialization.json.*

/** Host-only API timings; parsing the external input file is measured separately. */
fun main(args: Array<String>) {
    require(args.size in 3..4) { "Expected vectors.json warmups[1..20] repeats[3..100]" }
    val typed = args.last() == "--typed"
    val warmups = args[1].toInt(); val repeats = args[2].toInt()
    require(warmups in 1..20 && repeats in 3..100)
    fun milliseconds(start: Long) = (System.nanoTime() - start).toDouble() / 1_000_000
    var start = System.nanoTime()
    val bytes = File(args[0]).readBytes()
    val readMs = milliseconds(start); start = System.nanoTime()
    val document = Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
    val parseMs = milliseconds(start)
    val policy = LaneSemanticHint.Policy(document.getValue("policy").jsonObject)
    val cases = document.getValue("qualificationCases").jsonArray.map { it.jsonObject }
        .filter { it["expectedReason"]?.jsonPrimitive?.content == "qualified" }
    require(cases.isNotEmpty()) { "No expected-qualified cases" }
    val outputs = cases.map { item ->
        val context = item.getValue("context").jsonObject; val hint = item.getValue("hint").jsonObject
        val materializeStart = System.nanoTime()
        val mask = hint.getValue("mask").jsonObject
        val metadata = JsonObject(hint.filterKeys { it != "mask" })
        val scores = if (typed) mask.getValue("probabilities").jsonArray.map { it.jsonPrimitive.double }.toDoubleArray() else doubleArrayOf()
        val validity = if (typed) mask.getValue("validity").jsonArray.map { it.jsonPrimitive.boolean }.toBooleanArray() else booleanArrayOf()
        val width = mask.getValue("width").jsonPrimitive.int; val height = mask.getValue("height").jsonPrimitive.int
        val materializationMs = milliseconds(materializeStart)
        val samples = mutableListOf<JsonObject>()
        repeat(warmups + repeats) { iteration ->
            val cycleStart = System.nanoTime()
            var start = System.nanoTime()
            val qualified = if (typed) LaneSemanticHint.qualifyTyped(metadata, width, height, scores, validity, context, policy) else LaneSemanticHint.qualify(hint, context, policy)
            val qualifyMs = milliseconds(start); check(qualified.accepted) { qualified.reason }
            start = System.nanoTime()
            val cache = LaneSemanticHint.Cache(policy, context)
            val cacheInitMs = milliseconds(start)
            start = System.nanoTime()
            val offered = if (typed) cache.offerTyped(metadata, width, height, scores, validity) else cache.offer(hint)
            val cacheOfferMs = milliseconds(start); check(offered.accepted) { offered.reason }
            start = System.nanoTime()
            val current = cache.current()
            val cacheCurrentMs = milliseconds(start); check(current.accepted) { current.reason }
            val cycleMs = milliseconds(cycleStart)
            if (iteration >= warmups) samples += buildJsonObject {
                put("qualificationMs", qualifyMs); put("cacheConstructionMs", cacheInitMs)
                put("acceptedOfferMs", cacheOfferMs); put("currentRevalidationMs", cacheCurrentMs); put("cycleMs", cycleMs)
            }
        }
        buildJsonObject {
            put("typedMaterializationMs", materializationMs)
            put("id", item.getValue("id")); put("width", hint.getValue("mask").jsonObject.getValue("width"))
            put("height", hint.getValue("mask").jsonObject.getValue("height")); put("samples", JsonArray(samples))
        }
    }
    println(buildJsonObject {
        put("schemaVersion", 1); put("platform", "kotlin"); put("clock", "System.nanoTime")
        put("warmupsPerCase", warmups); put("measuredRepetitionsPerCase", repeats)
        put("inputRepresentation", if (typed) "typed_buffers" else "json_bridge")
        put("inputBytes", bytes.size); put("inputReadMs", readMs); put("inputParseMs", parseMs); put("cases", JsonArray(outputs))
    })
}
