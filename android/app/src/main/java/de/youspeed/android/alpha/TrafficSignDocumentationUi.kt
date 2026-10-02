package de.youspeed.android.alpha

import android.content.Context
import android.util.Base64
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import org.json.JSONArray
import org.json.JSONObject

internal object TrafficSignDocumentationHTML {
    fun make(context: Context, activeCountry: String?, locale: String): String {
        val catalogs = JSONArray()
        val images = JSONObject()
        context.assets.list("tsr").orEmpty().filter { Regex("prolix-[a-z]{2}-class-catalog-v1.json").matches(it) }.sorted().forEach { file ->
            val catalog = JSONObject(context.assets.open("tsr/$file").bufferedReader().use { it.readText() })
            catalogs.put(catalog)
            val signs = catalog.getJSONArray("signs")
            for (index in 0 until signs.length()) {
                val sign = signs.getJSONObject(index)
                val path = sign.optString("image_path")
                if (!sign.optBoolean("display_eligible") || !path.startsWith("tsr/sign-pictograms/") || !path.endsWith(".png") || ".." in path.split('/') || images.has(path)) continue
                val bytes = context.assets.open(path).use { it.readBytes() }
                images.put(path, "data:image/png;base64," + Base64.encodeToString(bytes, Base64.NO_WRAP))
            }
        }
        fun asset(name: String) = context.assets.open("traffic-sign-documentation/$name").bufferedReader().use { it.readText() }
        val common = context.assets.open("penalty-documentation/translations.json").bufferedReader().use { it.readText() }
        val input = JSONObject().put("catalogs", catalogs).put("images", images).put("locale", locale)
            .put("activeCountry", PenaltyCountryCodes.alpha2(activeCountry) ?: "DE")
            .put("translations", JSONObject(asset("translations.json"))).put("commonTranslations", JSONObject(common))
        return asset("index.html").replace("__YOUSPEED_RENDERER__", asset("renderer.js"))
            .replace("__YOUSPEED_INPUT__", input.toString().replace("<", "\\u003c"))
    }
}

@Composable
internal fun TrafficSignDocumentationSheet(activeCountry: String?, onDismiss: () -> Unit) {
    val context = LocalContext.current
    val locale = LocalConfiguration.current.locales[0].toLanguageTag()
    val html = remember(activeCountry, locale) { TrafficSignDocumentationHTML.make(context, activeCountry, locale) }
    OfflineDocumentationSheet(stringResource(R.string.traffic_sign_documentation_title), "traffic-sign-documentation", html, onDismiss)
}
