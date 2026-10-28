package net.koma.reader

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.JsResult
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.webkit.WebViewAssetLoader
import java.io.File
import java.io.FileInputStream
import java.io.IOException

/**
 * KOMA для Android: WebView + нативный движок Lens + автообновление с GitHub.
 *
 * Почему так:
 *  • читалка — один самодостаточный html (модели, словарь, WASM внутри), ей не
 *    нужен сервер и не нужен интернет, кроме Lens и обновлений;
 *  • адрес страницы постоянный — https://appassets.androidplatform.net/web/koma-web.html.
 *    Это важно: IndexedDB, где лежат модели, книги и настройки, привязан к
 *    источнику, поэтому обновление файла НЕ стирает библиотеку;
 *  • Google Lens работает нативно (приложение само шлёт кадр и забирает текст),
 *    потому что в WebView это запрещено CORS — мост KomaLens обходит запрет,
 *    не открывая никаких сайтов и вкладок.
 */
class MainActivity : android.app.Activity() {

    private lateinit var web: WebView
    private lateinit var updater: Updater
    private lateinit var engine: GlensEngine
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    private val appVersion: String by lazy {
        try { packageManager.getPackageInfo(packageName, 0).versionName ?: "1.0" } catch (e: Exception) { "1.0" }
    }

    // Выбор файлов моделей: три файла сразу, через системный «Файлы».
    private val RC_FILES = 1001

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        updater = Updater(this, BuildConfig.PAGE_VERSION)
        engine = GlensEngine { CookieManager.getInstance().getCookie("https://lens.google.com") }

        web = WebView(this)
        setContentView(web, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))

        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            allowFileAccess = false               // всё отдаётся через https-домен приложения
            allowContentAccess = true             // выбор файлов моделей из «Файлов»
            mediaPlaybackRequiresUserGesture = false
            cacheMode = WebSettings.LOAD_DEFAULT
            userAgentString = userAgentString + " KOMAApp/$appVersion"
        }
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, true)

        // Постоянный адрес страницы: обновление файла не сбрасывает IndexedDB.
        val loader = WebViewAssetLoader.Builder()
            .setDomain(DOMAIN)
            .addPathHandler("/web/", HtmlHandler())
            .build()

        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(view: WebView?, request: WebResourceRequest?): WebResourceResponse? {
                val r = request ?: return null
                return loader.shouldInterceptRequest(r.url)
            }

            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val u = request?.url ?: return false
                // Внутри приложения остаёмся на своём домене; внешние ссылки
                // (например, GitHub или Lens, если человек сам нажал) — в браузер.
                if (u.host == DOMAIN) return false
                return try {
                    startActivity(Intent(Intent.ACTION_VIEW, u)); true
                } catch (e: Exception) { false }
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                // После загрузки сообщаем странице, какая версия оболочки: в
                // «Правилах» появится блок «Приложение» (только внутри АПК).
                view?.evaluateJavascript(
                    "window.__komaAppVersion=${quote(appVersion)};document.dispatchEvent(new Event('koma-app'));",
                    null
                )
            }
        }

        web.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(msg: android.webkit.ConsoleMessage?): Boolean {
                msg?.let { Log.d("KomaWeb", "${it.messageLevel()} ${it.message()} @${it.lineNumber()}") }
                return true
            }

            override fun onShowFileChooser(
                view: WebView?,
                callback: ValueCallback<Array<Uri>>?,
                params: FileChooserParams?,
            ): Boolean {
                fileCallback?.onReceiveValue(null)
                fileCallback = callback
                return try {
                    val intent = Intent(Intent.ACTION_GET_CONTENT).apply {
                        addCategory(Intent.CATEGORY_OPENABLE)
                        type = "*/*"
                        putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)   // три файла моделей сразу
                    }
                    startActivityForResult(Intent.createChooser(intent, "Выберите файлы моделей"), RC_FILES)
                    true
                } catch (e: Exception) {
                    fileCallback = null
                    false
                }
            }

            override fun onJsAlert(view: WebView?, url: String?, message: String?, result: JsResult?): Boolean {
                // confirm()/prompt() в читалке не используются намеренно, но если
                // появятся — не вешаем страницу.
                Toast.makeText(this@MainActivity, message ?: "", Toast.LENGTH_LONG).show()
                result?.confirm()
                return true
            }
        }

        web.addJavascriptInterface(KomaLensBridge(engine, appVersion) { web }, "KomaLens")
        web.addJavascriptInterface(
            KomaAppBridge(updater, engine, appVersion) { reason -> runOnUiThread { reload(reason) } },
            "KomaApp"
        )

        web.loadUrl(START_URL)

        // Автообновление: тихо, в фоне, после старта. Если скачалось новее —
        // один раз перезагружаем и говорим об этом тостом.
        Thread {
            val res = updater.check()
            if (res.optBoolean("updated")) {
                runOnUiThread { reload("Читалка обновлена до " + res.optString("version")) }
            }
        }.start()
    }

    private fun reload(reason: String) {
        Toast.makeText(this, reason, Toast.LENGTH_LONG).show()
        web.loadUrl(START_URL)
    }

    /**
     * Отдаём читалку: сначала обновлённый файл из filesDir, иначе встроенный
     * из assets. Оба — по одному и тому же адресу, поэтому для страницы это
     * одна и та же установка.
     */
    private inner class HtmlHandler : WebViewAssetLoader.PathHandler {
        override fun handle(path: String): WebResourceResponse? {
            val name = path.removePrefix("/")
            if (name != "koma-web.html" && name != "index.html" && name != "") return null
            val updated = updater.currentFile()
            return try {
                if (updated != null) {
                    WebResourceResponse("text/html", "utf-8", FileInputStream(updated))
                } else {
                    WebResourceResponse("text/html", "utf-8", assets.open("koma-web.html"))
                }
            } catch (e: IOException) {
                Log.e("Koma", "нет ни обновлённого файла, ни встроенного", e)
                null
            }
        }
    }

    /** Итог системного выбора файлов — отдаём странице. */
    @Deprecated("framework API: ActivityResult стартует библиотеку, а нам хватает этого")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != RC_FILES) return
        val cb = fileCallback ?: return
        fileCallback = null
        val uris: Array<Uri>? = when {
            data == null -> null
            (data.clipData?.itemCount ?: 0) > 1 -> (0 until data.clipData!!.itemCount)
                .map { data.clipData!!.getItemAt(it).uri }.toTypedArray()
            data.data != null -> arrayOf(data.data!!)
            else -> null
        }
        cb.onReceiveValue(uris)
    }

    override fun onBackPressed() {
        // Как в браузере: сначала «назад» внутри читалки, потом выход.
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    override fun onPause() {
        super.onPause()
        // Голос должен замолчать при уходе из приложения, иначе читает в кармане.
        web.evaluateJavascript(
            "try{(window.speechSynthesis||{}).cancel&&speechSynthesis.cancel();" +
            "window.TTS&&TTS.stop&&TTS.stop();}catch(e){}", null)
    }

    private fun quote(s: String) = "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"

    companion object {
        private const val DOMAIN = "appassets.androidplatform.net"
        private const val START_URL = "https://$DOMAIN/web/koma-web.html"
    }
}

@Suppress("unused")
private fun View.hide() { visibility = View.GONE }
