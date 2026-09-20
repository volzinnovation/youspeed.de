package de.youspeed.android.alpha
import java.io.File
import kotlinx.serialization.json.*

fun main(args: Array<String>) {
    val vectors = Json.parseToJsonElement(File(args[0]).readText()).jsonObject.getValue("scenarios").jsonArray
    val results = vectors.map { raw ->
        val scenario = raw.jsonObject; val session = TSRApplicabilitySession()
        buildJsonObject {
            put("id", scenario.getValue("id"))
            put("frames", JsonArray(scenario.getValue("batches").jsonArray.map {
                TSRApplicabilityJson.encodeDiagnostic(session.evaluate(TSRApplicabilityJson.decodeBatch(it.jsonObject)))
            }))
        }
    }
    print(JsonArray(results))
}
