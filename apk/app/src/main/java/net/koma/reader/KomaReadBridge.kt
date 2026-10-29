package net.koma.reader

import android.webkit.JavascriptInterface
import org.json.JSONArray
import org.json.JSONObject

/**
 * Мост движка чтения: `window.KomaRead`.
 *
 * Страница отдаёт строки распознавания, приложение возвращает ГОТОВЫЕ РЕПЛИКИ
 * в порядке чтения и полосы страницы. Смысл: порядок реплик, склейка слов и
 * полосы — правила чтения, а не интерфейс; им место в приложении, где их нельзя
 * случайно сломать правкой страницы.
 *
 * Всё синхронно и быстро (тысячи строк — единицы миллисекунд): чистая геометрия,
 * без сети, без моделей, без потоков.
 */
class KomaReadBridge(private val engine: ReadEngine = ReadEngine()) {

    /** `items` = [{text,left,top,right,bottom,confidence}] в долях страницы. */
    @JavascriptInterface
    fun plan(itemsJson: String, rulesJson: String): String {
        return try {
            val arr = JSONArray(itemsJson)
            val rules = ReadEngine.Rules.from(rulesJson)
            val lines = ArrayList<ReadEngine.Line>(arr.length())
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                val text = o.optString("text", "")
                if (text.isBlank()) continue
                lines.add(
                    ReadEngine.Line(
                        text = text,
                        left = o.optDouble("left", 0.0),
                        top = o.optDouble("top", 0.0),
                        right = o.optDouble("right", 1.0),
                        bottom = o.optDouble("bottom", 1.0),
                        confidence = o.optDouble("confidence", 0.0),
                    )
                )
            }
            val out = engine.plan(lines, rules)
            JSONObject().put("ok", true).put("replicas", JSONArray(out)).toString()
        } catch (t: Throwable) {
            JSONObject().put("ok", false).put("error", t.message ?: t.javaClass.simpleName).toString()
        }
    }

    /** Полосы страницы по высоте кадра и экрана (пиксели). */
    @JavascriptInterface
    fun bands(pageHeightPx: Double, viewportPx: Double, rulesJson: String): String {
        return try {
            engine.bands(pageHeightPx, viewportPx, ReadEngine.Rules.from(rulesJson)).toString()
        } catch (t: Throwable) {
            JSONArray().toString()
        }
    }
}
