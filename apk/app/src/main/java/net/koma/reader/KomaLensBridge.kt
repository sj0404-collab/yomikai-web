package net.koma.reader

import android.webkit.JavascriptInterface
import org.json.JSONArray
import org.json.JSONObject
import android.util.Base64

/**
 * Мост «Lens напрямую» для читалки. Именно его ждёт koma-web.html:
 * `window.KomaLens.recognize(base64Jpeg, optsJson)` → строка JSON.
 *
 * Метод вызывается из JS синхронно и блокирует ТОЛЬКО поток моста, не UI:
 * сеть и разбор идут в [GlensEngine] на своём потоке. Поэтому бейдж
 * «Lens: распознаю без сайта…» рисуется, пока идёт распознавание.
 */
class KomaLensBridge(private val engine: GlensEngine, private val appVersion: String) {

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

    /** Диагностика: что вернул Google на тестовую картинку. */
    @JavascriptInterface
    fun selfTest(): String = engine.selfTest().toString()

    @JavascriptInterface
    fun info(): String = JSONObject()
        .put("engine", "glens-native")
        .put("app", appVersion)
        .toString()
}
