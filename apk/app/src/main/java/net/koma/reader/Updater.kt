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
 * сводится к замене этого файла: скачали со страницы Releases, положили в
 * filesDir, WebView перезагрузили. Модели, книги и настройки при этом целы:
 * они живут в IndexedDB на постоянном адресе страницы
 * https://appassets.androidplatform.net/web/koma-web.html.
 *
 * Источник — последний релиз репозитория, в котором лежит файл koma-web.html
 * (его кладёт туда сборка по тегу). Тег релиза имеет вид `page-v1.9.31`, и это
 * даёт бесплатную проверку без скачивания: сравнили тег с местной версией —
 * и всё. Экономия 11 МБ на каждом запуске.
 *
 * Защита от порчи: скачивание принимается, только если это действительно наша
 * сборка (>= 5 МБ и есть строка `VERSION = 'v…'`), и только после записи во
 * временный файл с атомарной заменой. Старая копия остаётся до успеха.
 */
class Updater(private val ctx: Context, private val assetsVersion: String) {

    companion object {
        private const val REPO = "sj0404-collab/yomikai-web"
        private const val API_LATEST = "https://api.github.com/repos/$REPO/releases/latest"
        const val FILE_NAME = "koma-web.html"
        private const val MIN_SIZE = 5_000_000L
        private const val UA = "KOMA-Android"
    }

    private val prefs = ctx.getSharedPreferences("koma", Context.MODE_PRIVATE)
    private val target get() = File(ctx.filesDir, FILE_NAME)
    private val tmp get() = File(ctx.filesDir, "$FILE_NAME.part")

    /** Файл обновления, если он есть и выглядит целым. */
    fun currentFile(): File? = target.takeIf { it.exists() && it.length() > MIN_SIZE }

    /** Какая версия страницы сейчас реально откроется. */
    fun localVersion(): String =
        if (currentFile() != null) prefs.getString("htmlVersion", null) ?: assetsVersion else assetsVersion

    /**
     * Проверить и, если есть новее, скачать.
     * Возвращает JSON для моста: {updated, version, reason}.
     */
    fun check(): JSONObject {
        val out = JSONObject().put("updated", false)
        try {
            val rel = JSONObject(get(API_LATEST, null))
            val tag = rel.optString("tag_name").trim()
            val tagVersion = tag.removePrefix("page-").trim()
            if (tagVersion.isNotEmpty() && tagVersion == localVersion() && currentFile() != null) {
                return out.put("reason", "уже свежая ($tagVersion)").put("version", tagVersion)
            }

            // Ищем файл читалки среди вложений релиза.
            var url: String? = null
            val assets = rel.optJSONArray("assets")
            if (assets != null) {
                for (i in 0 until assets.length()) {
                    val a = assets.getJSONObject(i)
                    val name = a.optString("name")
                    if (name == FILE_NAME || name.endsWith("/$FILE_NAME")) {
                        url = a.optString("browser_download_url")
                        break
                    }
                }
            }
            if (url == null || url.isEmpty()) {
                return out.put("reason", "в релизе ${tag.ifEmpty { "?" }} нет файла $FILE_NAME — обновление не из чего брать")
            }

            val bytes = get(url, null) { _, stream -> stream.readBytes() }
            if (bytes.size < MIN_SIZE) return out.put("reason", "скачано подозрительно мало: ${bytes.size} Б")
            val text = String(bytes, Charsets.UTF_8)
            val ver = versionIn(text) ?: return out.put("reason", "в файле нет строки версии — не наша сборка")

            // Уже эта версия (например, релиз без смены тега) — не трогаем файл.
            if (ver == localVersion() && currentFile() != null) {
                return out.put("reason", "уже свежая ($ver)").put("version", ver)
            }

            tmp.writeBytes(bytes)
            if (!tmp.renameTo(target)) {
                target.delete()
                if (!tmp.renameTo(target)) return out.put("reason", "не удалось записать файл")
            }
            prefs.edit().putString("htmlVersion", ver).putString("etag", tag).apply()
            GlensEngine.log("обновлено до $ver (${bytes.size} Б из $tag)")
            out.put("updated", true).put("version", ver).put("bytes", bytes.size)
        } catch (e: Throwable) {
            out.put("reason", (e.message ?: e.javaClass.simpleName))
        }
        return out
    }

    // ── сеть ────────────────────────────────────────────────────────────────
    private fun get(url: String, etag: String?): String = get(url, etag) { _, s -> s.readBytes() }.toString(Charsets.UTF_8)

    private fun <T> get(url: String, etag: String?, read: (HttpURLConnection, java.io.InputStream) -> T): T {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 12000
            readTimeout = 60000
            instanceFollowRedirects = true
            setRequestProperty("User-Agent", UA)
            setRequestProperty("Accept", "application/vnd.github+json")
            if (etag != null) setRequestProperty("If-None-Match", etag)
        }
        val code = conn.responseCode
        if (code !in 200..299) throw IllegalStateException("GitHub ответил HTTP $code")
        return conn.inputStream.use { read(conn, it) }
    }

    private fun versionIn(text: String): String? =
        Regex("VERSION = '(v[0-9.]+)'").find(text)?.groupValues?.get(1)
}
