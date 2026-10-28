package net.koma.reader

import android.webkit.JavascriptInterface
import org.json.JSONObject

/**
 * Мост приложения (не читалки): версия, проверка обновления, перезагрузка,
 * диагностика Lens. Читалка показывает эти действия в «Правилах», только когда
 * `window.KomaApp` существует, — то есть только внутри АПК. В браузере тех же
 * кнопок нет, и это правильно: там нечего обновлять и нечего перезагружать.
 */
class KomaAppBridge(
    private val updater: Updater,
    private val engine: GlensEngine,
    private val appVersion: String,
    private val reload: (String) -> Unit,
) {

    @JavascriptInterface
    fun version(): String = JSONObject()
        .put("app", appVersion)
        .put("page", updater.localVersion())
        .put("source", "GitHub Releases · sj0404-collab/yomikai-web")
        .toString()

    /** Проверить обновление по кнопке. Возвращает JSON, читалка показывает итог. */
    @JavascriptInterface
    fun checkUpdate(): String {
        val res = updater.check()
        if (res.optBoolean("updated")) {
            // Перезагружаем на следующем кадре, чтобы успел уйти ответ в JS.
            Thread {
                Thread.sleep(700)
                reload("Обновлено до " + res.optString("version"))
            }.start()
        }
        return res.toString()
    }

    @JavascriptInterface
    fun lensSelfTest(): String = engine.selfTest().toString()

    @JavascriptInterface
    fun reloadNow(reason: String) = reload(reason.ifBlank { "перезагрузка" })
}
