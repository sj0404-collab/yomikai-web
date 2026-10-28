package net.koma.reader

import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * Мост приложения (не читалки): версия, проверка обновления, диагностика Lens.
 * Читалка показывает эти действия в правилах, только когда `window.KomaApp`
 * существует, — то есть только внутри АПК.
 *
 * Обновление сделано асинхронным намеренно. Раньше `checkUpdate()` был обычным
 * синхронным методом моста: он держал поток JavaScript всё время проверки и
 * скачивания 11 МБ, поэтому на нажатие «Проверить обновление» экран **молчал** —
 * ни тоста, ни строки, ничего. Теперь страница сразу получает управление, а по
 * ходу дела приходят сообщения в `window.__komaAppEvent(id, 'state'|'done', …)`.
 */
class KomaAppBridge(
    private val updater: Updater,
    private val engine: GlensEngine,
    private val appVersion: String,
    private val web: () -> WebView?,
    private val reload: (String) -> Unit,
) {

    private val pool = Executors.newSingleThreadExecutor()

    @JavascriptInterface
    fun version(): String = JSONObject()
        .put("app", appVersion)
        .put("page", updater.localVersion())
        .put("release", Updater.RELEASE_TAG)
        .toString()

    /**
     * Проверить и, если есть новее, скачать. Ответ — в `window.__komaAppEvent`.
     * Промежуточные сообщения идут тем же путём с типом 'state': «Проверяю…»,
     * «Найдена версия…», «Скачиваю…». Молчания не бывает ни на одном шаге.
     */
    @JavascriptInterface
    fun checkUpdate(cbId: String) {
        pool.execute {
            val emit = { type: String, text: String ->
                post(cbId, type, text)
            }
            try {
                val res = updater.check { msg -> emit("state", msg) }
                emit("done", res.toString())
                if (res.optBoolean("updated")) {
                    // Даём странице показать «перезагружаю…», иначе человек
                    // видит, что приложение моргнуло, и не понимает, почему.
                    Thread.sleep(1500)
                    reload("Читалка обновлена до " + res.optString("version"))
                }
            } catch (e: Throwable) {
                emit("done", JSONObject().put("updated", false)
                    .put("reason", (e.message ?: e.javaClass.simpleName)).toString())
            }
        }
    }

    @JavascriptInterface
    fun lensSelfTest(): String = engine.selfTest().toString()

    @JavascriptInterface
    fun reloadNow(reason: String) = reload(reason.ifBlank { "перезагрузка" })

    private fun post(cbId: String, type: String, text: String) {
        val ws = web() ?: return
        val id = JSONObject.quote(cbId)
        val t = JSONObject.quote(type)
        val d = JSONObject.quote(text)
        ws.post {
            ws.evaluateJavascript("window.__komaAppEvent&&window.__komaAppEvent($id,$t,$d)", null)
        }
    }
}
