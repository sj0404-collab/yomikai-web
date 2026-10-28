package net.koma.reader

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * Автообновление читалки прямо с GitHub.
 *
 * Читалка — один html-файл, поэтому «обновление приложения» без Play Market
 * сводится к замене этого файла: скачали с raw.githubusercontent.com, положили
 * в filesDir, WebView перезагрузили. Модели, книги и настройки при этом не
 * трогаются: они живут в IndexedDB на постоянном адресе
 * https://appassets.androidplatform.net/web/koma-web.html.
 *
 * Защита от порчи: скачанное принимается, только если это действительно наша
 * сборка (размер > 5 МБ и есть строка VERSION = 'v…'), и только после записи
 * во временный файл с последующей атомарной заменой. Старая копия остаётся.
 */
class Updater(private val ctx: Context) {

    companion object {
        // Откуда берём свежую сборку. Ветка main того же репозитория, что и код.
        const val URL_HTML =
            "https://raw.githubusercontent.com/sj0404-collab/yomikai-web/main/koma-web.html"
        const val FILE_NAME = "koma-web.html"
        private const val MIN_SIZE = 5_000_000L
    }

    private val prefs = ctx.getSharedPreferences("koma", Context.MODE_PRIVATE)
    private val target get() = File(ctx.filesDir, FILE_NAME)
    private val tmp get() = File(ctx.filesDir, "$FILE_NAME.part")

    fun currentFile(): File? = target.takeIf { it.exists() && it.length() > MIN_SIZE }

    fun localVersion(): String {
        val f = currentFile() ?: return "встроенная (assets)"
        return versionIn(f.readText()) ?: "неизвестно"
    }

    /**
     * Проверить обновление. silent=true — без сообщений (вызывается при старте).
     * Возвращает JSON для моста: {updated, version, reason}.
     */
    fun check(silent: Boolean = true): JSONObject {
        val out = JSONObject().put("updated", false)
        try {
            val etag = prefs.getString("etag", null)
            val conn = (URL(URL_HTML).openConnection() as HttpURLConnection).apply {
                connectTimeout = 10000
                readTimeout = 30000
                setRequestProperty("User-Agent", "KOMA-Android")
                if (etag != null && currentFile() != null) setRequestProperty("If-None-Match", etag)
            }
            val code = conn.responseCode
            if (code == 304) return out.put("reason", "уже свежая").put("version", localVersion())
            if (code !in 200..299) return out.put("reason", "GitHub ответил HTTP $code")
            val bytes = conn.inputStream.use { it.readBytes() }
            val etagNew = conn.getHeaderField("ETag")
            if (bytes.size < MIN_SIZE) return out.put("reason", "скачано подозрительно мало: ${bytes.size} Б")
            val text = String(bytes, Charsets.UTF_8)
            val ver = versionIn(text) ?: return out.put("reason", "в файле нет строки версии — не наша сборка")

            // Не перезаписываем тем же самым: экономим запись 11 МБ при каждом старте.
            val cur = currentFile()
            if (cur != null && cur.length() == bytes.size.toLong()) {
                if (etagNew != null) prefs.edit().putString("etag", etagNew).apply()
                return out.put("reason", "уже свежая").put("version", ver)
            }
            tmp.writeBytes(bytes)
            if (!tmp.renameTo(target)) {
                target.delete()
                if (!tmp.renameTo(target)) return out.put("reason", "не удалось записать файл")
            }
            if (etagNew != null) prefs.edit().putString("etag", etagNew).apply()
            prefs.edit().putString("htmlVersion", ver).apply()
            if (!silent) GlensEngine.log("обновлено до $ver")
            out.put("updated", true).put("version", ver).put("bytes", bytes.size)
        } catch (e: Throwable) {
            out.put("reason", String(e.message ?: e.javaClass.simpleName))
        }
        return out
    }

    private fun versionIn(text: String): String? =
        Regex("VERSION = '(v[0-9.]+)'").find(text)?.groupValues?.get(1)
}
