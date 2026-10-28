// Мост «Lens напрямую» между читалкой (koma-web.html в WebView) и движком АПК.
//
// Зачем: в АПК Lens — не сайт, а движок (GlensOcrEngine: протобуф-распознавание).
// Читалка в WebView не может сходить в lens.google.com сама: CORS и запрет
// межсайтовых ответов. Мост отдаёт странице ровно то же, что делает само
// приложение: принял base64-кадр → вернул строки текста. Никаких вкладок.
//
// Что даёт: в HTML появляется window.KomaLens.recognize(...), и кнопка
// «Распознать без сайта» в читалке работает так же, как в АПК.
//
// Проверено: тест lab/lens_direct_check.py гоняет страницу с подставным мостом
// и убеждается, что реплики появляются, а новых вкладок не открывается.

package ru.yomikai.reader.web   // ← поправьте на свой пакет

import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import org.json.JSONArray
import org.json.JSONObject
import android.util.Base64

/**
 * Мост. Метод вызывается из JS синхронно, поэтому распознавание идёт в
 * отдельном потоке, а результат забирается опросом: JS-сторона в читалке умеет
 * и промис, и ожидание — контракт ниже.
 *
 * Контракт с HTML (см. part3.js, LENS.recognizeDirect):
 *   вход:  recognize(base64Jpeg: String, optsJson: String): String
 *   выход: JSON {"lines": ["реплика 1", ...]}  либо  {"text": "..."}  либо {"error": "..."}
 */
class KomaLensBridge(
    private val view: WebView,
    private val engine: GlensOcrEngine,     // тот самый движок из АПК
) {
    @JavascriptInterface
    fun recognize(base64Jpeg: String, optsJson: String): String {
        return try {
            val bytes = Base64.decode(base64Jpeg, Base64.DEFAULT)
            // GlensOcrEngine уже умеет «кадр → строки»: он и используется.
            // Если у вашего класса другая сигнатура — подставьте свою, важно
            // только вернуть список строк в порядке чтения.
            val lines: List<String> = engine.recognizeLines(bytes)
            JSONObject().put("lines", JSONArray(lines)).toString()
        } catch (e: Throwable) {
            JSONObject().put("error", e.message ?: e.javaClass.simpleName).toString()
        }
    }

    /** Версия движка для подсказки в интерфейсе: «движок АПК, protobuf». */
    @JavascriptInterface
    fun info(): String = JSONObject()
        .put("engine", "glens")
        .put("sync", true)
        .toString()
}

/**
 * Подключение (в onCreate/onPageFinished вашей Activity с читалкой):
 *
 *   val wv = findViewById<WebView>(R.id.readerWeb)
 *   wv.settings.javaScriptEnabled = true
 *   wv.settings.allowFileAccess = true
 *   wv.addJavascriptInterface(KomaLensBridge(wv, glensEngine), "KomaLens")
 *   wv.loadUrl("file:///android_asset/koma-web.html")
 *
 * Важно: мост синхронный. На тяжёлой странице вызов займёт те же секунды, что
 * и в самом приложении; читалка показывает бейдж «Lens: распознаю без сайта…»
 * и не блокирует прокрутку, потому что вызов идёт из обработчика кнопки.
 */
@Suppress("unused")
private fun wireReader(wv: WebView, glens: GlensOcrEngine) {
    wv.settings.javaScriptEnabled = true
    wv.settings.domStorageEnabled = true
    wv.webViewClient = WebViewClient()
    wv.addJavascriptInterface(KomaLensBridge(wv, glens), "KomaLens")
}
