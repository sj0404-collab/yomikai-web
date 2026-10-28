package net.koma.reader

import android.util.Base64
import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * Мост «Lens напрямую» для читалки. Именно его ждёт koma-web.html:
 * `window.KomaLens.recognize(base64Jpeg, optsJson)` → строка JSON.
 *
 * Метод вызывается из JS синхронно и блокирует ТОЛЬКО поток моста, не UI:
 * сеть и разбор идут в [GlensEngine] на своём потоке. Поэтому бейдж
 * «Lens: распознаю без сайта…» рисуется, пока идёт распознавание.
 */
class KomaLensBridge(
    private val engine: GlensEngine,
    private val appVersion: String,
    private val web: () -> WebView?,
) {

    private val pool = Executors.newSingleThreadExecutor()

    @JavascriptInterface
    fun recognize(base64Jpeg: String, optsJson: String): String {
        val out = JSONObject()
        return try {
            val bytes = Base64.decode(base64Jpeg, Base64.DEFAULT)
            if (bytes.size < 512) {
                return out.put("error", "кадр пустой — страница не загрузилась").toString()
            }
            val res = engine.recognize(bytes)
            out.put("lines", JSONArray(res.lines))
            out.put("ms", res.ms)
            out.put("via", "native")
            out.toString()
        } catch (e: Throwable) {
            GlensEngine.log("recognize: ${e.message}")
            out.put("error", e.message ?: e.javaClass.simpleName).toString()
        }
    }

    /**
     * То же распознавание, но НЕ блокирует JS: ответ придёт в
     * `window.__komaLensResolve[cbId](jsonString)`.
     *
     * Зачем: синхронный вызов держит поток JavaScript, пока идёт сеть, и на
     * медленном ответе Google интерфейс замирает. Здесь страница получает
     * управление сразу и продолжает рисовать бейдж, а текст приходит, когда
     * движок закончил.
     */
    @JavascriptInterface
    fun recognizeAsync(base64Jpeg: String, optsJson: String, cbId: String) {
        pool.execute {
            val json = recognize(base64Jpeg, optsJson)
            web()?.post {
                val id = JSONObject.quote(cbId)
                val arg = JSONObject.quote(json)
                web()?.evaluateJavascript(
                    "window.__komaLensResolve&&window.__komaLensResolve[$id]&&window.__komaLensResolve[$id]($arg)",
                    null
                )
            }
        }
    }

    /** Диагностика: что вернул Google на тестовую картинку. */
    @JavascriptInterface
    fun selfTest(): String = engine.selfTest().toString()

    @JavascriptInterface
    fun info(): String = JSONObject()
        .put("engine", "glens-native")
        .put("app", appVersion)
        .toString()
}
