package net.koma.reader

import android.content.Context
import android.net.Uri
import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

/**
 * Плагины читалки: правки поведения ФАЙЛАМИ JSON, без пересборки АПК.
 *
 * Зачем это в приложении, а не в странице:
 *  • файл плагина лежит рядом с приложением (`filesDir/plugins`), его можно
 *    положить, не пересобирая ни страницу, ни АПК;
 *  • плагины, вшитые в сборку, лежат в `assets/plugins` и работают сразу;
 *  • порядок применения задаётся полем `order`, так что правки не конфликтуют.
 *
 * Формат одного файла:
 * {
 *   "id": "мои-правки",
 *   "name": "Мои правки слов",
 *   "order": 10,
 *   "rules":      { "pageSide": 1280, "speechRate": 1.0 },   // правила распознавания
 *   "wordFixes":  { "ПОШЕВЕАИТЬСЯ": "ПОШЕВЕЛИТЬСЯ" },       // словарь замен слов
 *   "replace":    [ { "from": "ГОВОРЯ.ш", "to": "ГОВОРИШЬ" } ], // точечные замены
 *   "voice":      { "engine": "", "voice": "", "rate": 1.0 },   // синтез речи
 *   "ocr":        { "engine": "native" }                        // движок распознавания
 * }
 *
 * Приоритет: чем больше `order`, тем позже применяется (то есть главнее).
 */
class KomaPluginsBridge(
    private val ctx: Context,
    private val web: () -> WebView?,
) {

    private val io = Executors.newSingleThreadExecutor()

    val dir: File get() = File(ctx.filesDir, "plugins")

    /** Где лежат пользовательские плагины — чтобы человек мог их положить. */
    @JavascriptInterface
    fun where(): String = dir.absolutePath

    /** Открыть системный выбор файла плагина (копирование делает MainActivity). */
    @JavascriptInterface
    fun pick() {
        val a = ctx as? MainActivity
        a?.runOnUiThread { a.pickPluginFiles() }
    }

    /** Все плагины: сначала вшитые (assets), затем пользовательские (filesDir). */
    @JavascriptInterface
    fun all(): String {
        val plugins = JSONArray()
        val problems = JSONArray()
        val sources = JSONArray()
        try {
            // 1. Вшитые в сборку.
            val names = try { ctx.assets.list("plugins") ?: emptyArray() } catch (e: Throwable) { emptyArray() }
            for (n in (names ?: emptyArray()).sorted()) {
                if (!n.endsWith(".json", true)) continue
                try {
                    val text = ctx.assets.open("plugins/$n").bufferedReader().use { it.readText() }
                    val o = JSONObject(text)
                    o.put("_source", "assets/plugins/$n")
                    plugins.put(o)
                    sources.put("assets/plugins/$n")
                } catch (t: Throwable) {
                    problems.put("assets/plugins/$n: ${t.message ?: t.javaClass.simpleName}")
                }
            }
            // 2. Пользовательские (можно положить файл в папку и нажать «перечитать»).
            dir.mkdirs()
            val files = dir.listFiles { f -> f.isFile && f.name.endsWith(".json", true) } ?: emptyArray()
            for (f in files.sortedBy { it.name }) {
                try {
                    val o = JSONObject(f.readText())
                    o.put("_source", "plugins/${f.name}")
                    plugins.put(o)
                    sources.put("plugins/${f.name}")
                } catch (t: Throwable) {
                    problems.put("plugins/${f.name}: ${t.message ?: t.javaClass.simpleName}")
                }
            }
        } catch (t: Throwable) {
            problems.put("плагины не прочитались: ${t.message ?: t.javaClass.simpleName}")
        }
        // Сортируем по order (устойчиво: при равенстве — по имени источника).
        val list = ArrayList<JSONObject>()
        for (i in 0 until plugins.length()) list.add(plugins.getJSONObject(i))
        val sorted = list.sortedWith(compareBy({ it.optInt("order", 100) }, { it.optString("_source") }))
        val out = JSONArray()
        sorted.forEach { out.put(it) }
        return JSONObject()
            .put("ok", true)
            .put("plugins", out)
            .put("sources", sources)
            .put("problems", problems)
            .put("dir", dir.absolutePath)
            .toString()
    }

    /**
     * Плагины из файла, который человек выбрал системным «Файлами».
     *
     * Зачем: на Android 11+ папка приложения недоступна без root, и «положите
     * файл в plugins» — совет, который невозможно выполнить. Теперь: выбрал
     * .json в «Загрузках» → он скопирован в папку приложения → перечитан.
     */
    fun importUris(uris: List<Uri>): JSONObject {
        val out = JSONObject()
        val saved = JSONArray()
        try {
            dir.mkdirs()
            var any = 0
            for (u in uris) {
                val name = (u.lastPathSegment ?: "plugin.json").substringAfterLast('/')
                val safe = if (name.endsWith(".json", true)) name else "$name.json"
                val dst = File(dir, safe)
                val text = ctx.contentResolver.openInputStream(u)?.use { it.reader().readText() }
                    ?: throw IllegalStateException("не удалось открыть файл")
                // Проверяем, что это плагин, ДО записи: кривой файл не должен
                // попадать в папку и ломать чтение при следующем запуске.
                val obj = JSONObject(text)
                dst.writeText(text)
                saved.put(dst.name)
                any++
                if (obj.optString("id").isBlank() && obj.optString("name").isBlank()) {
                    out.put("warning", "в файле нет id/name — работает, но непонятно, чей он")
                }
            }
            out.put("ok", any > 0).put("saved", saved)
        } catch (t: Throwable) {
            out.put("ok", false).put("error", t.message ?: t.javaClass.simpleName)
        }
        return out
    }

    /** Перечитать плагины и сказать странице, что они обновились. */
    @JavascriptInterface
    fun reload() {
        io.execute {
            val ws = web() ?: return@execute
            ws.post {
                ws.evaluateJavascript(
                    "try{window.dispatchEvent(new CustomEvent('koma-plugins',{detail:{reload:true}}));}catch(e){}",
                    null
                )
            }
        }
    }
}
