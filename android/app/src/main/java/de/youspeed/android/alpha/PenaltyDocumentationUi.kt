package de.youspeed.android.alpha

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.viewinterop.AndroidView
import org.json.JSONArray
import org.json.JSONObject

internal object PenaltyDocumentationHTML {
    fun make(context: Context, activeRules: SpeedPenaltyRuleSet, locale: String): String {
        val documents = sortedMapOf<String, JSONObject>()
        context.assets.list("Rules").orEmpty().filter { it.endsWith("-rules.json") }.forEach { file ->
            val document = JSONObject(context.assets.open("Rules/$file").bufferedReader().use { it.readText() })
            val code = document.optString("country_code").ifBlank { document.optString("land_code") }
            documents[code] = document
        }
        activeRules.documentationJSON?.let { documents[activeRules.countryCode] = JSONObject(it) }
        fun asset(name: String) = context.assets.open("penalty-documentation/$name").bufferedReader().use { it.readText() }
        val input = JSONObject().put("documents", JSONArray(documents.values.toList()))
            .put("translations", JSONObject(asset("translations.json"))).put("locale", locale)
            .put("activeCountry", PenaltyCountryCodes.normalize(referenceScreenshotCountry(context)) ?: activeRules.countryCode)
        return asset("index.html").replace("__YOUSPEED_RENDERER__", asset("renderer.js"))
            .replace("__YOUSPEED_INPUT__", input.toString().replace("<", "\\u003c"))
    }
}

@Composable
internal fun PenaltyDocumentationSheet(activeRules: SpeedPenaltyRuleSet, onDismiss: () -> Unit) {
    val context = LocalContext.current
    val locale = LocalConfiguration.current.locales[0].toLanguageTag()
    val html = remember(activeRules, locale) { PenaltyDocumentationHTML.make(context, activeRules, locale) }
    OfflineDocumentationSheet(stringResource(R.string.penalty_documentation_title), "penalty-documentation", html, onDismiss)
}

@Composable
internal fun OfflineDocumentationSheet(title: String, testTag: String, html: String, onDismiss: () -> Unit) {
    SheetScaffold(title = title, onDismiss = onDismiss, testTag = testTag) {
        AndroidView(modifier = Modifier.fillMaxSize(), factory = { viewContext ->
            WebView(viewContext).apply {
                settings.javaScriptEnabled = true
                settings.allowFileAccess = false
                settings.allowContentAccess = false
                settings.blockNetworkLoads = true
                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                        val url = request?.url ?: return true
                        if (request.hasGesture() && url.scheme in listOf("http", "https")) {
                            viewContext.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url.toString())))
                        }
                        return url.toString() != "about:blank"
                    }
                }
            }
        }, update = { view ->
            if (view.tag != html) {
                view.tag = html
                view.loadDataWithBaseURL(null, html, "text/html", "UTF-8", null)
            }
        }, onRelease = { it.destroy() })
    }
}

// Capture selection changes documentation only and is unavailable in release builds.
internal fun referenceScreenshotCountry(context: Context): String? {
    if (!BuildConfig.DEBUG) return null
    var current = context
    while (current is android.content.ContextWrapper) {
        if (current is android.app.Activity) return current.intent?.getStringExtra("screenshot_reference_country")
        current = current.baseContext
    }
    return null
}
