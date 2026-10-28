package net.koma.reader

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * Автообновление читалки с GitHub — из ОДНОГО релиза.
 *
 * Раньше на каждый выпуск создавался новый релиз, и в приложении это выглядело
 * бестолково: обновление скачивало ту же версию, что уже стоит, и перезагружало
 * страницу без всякого уведомления — «он обновляется на ту же версию и молчит».
 *
 * Теперь так:
 *  • в репозитории **один** релиз с фиксированным тегом [RELEASE_TAG], файлы в
 *    нём просто перезаписываются каждой сборкой (а не плодятся релизы);
 *  • в релизе лежит крошечный `version.json` — сначала читаем только его
 *    (сотня байт) и сравниваем версию. Совпала — **ничего не скачиваем**;
 *  • качаем `koma-web.html` (11 МБ) только когда версия действительно новее,
 *    и на каждом шаге сообщаем, что происходит.
 *
 * Установка самого APK не нужна: обновляется страница, а данные (модели, книги,
 * настройки) лежат в IndexedDB на постоянном адресе и остаются целыми.
 */
class Updater(private val ctx: Context, private val assetsVersion: String) {

    companion object {
        private const val REPO = "sj0404-collab/yomikai-web"
        /** Один релиз на всё: файлы в нём перезаписываются, тег не меняется. */
        const val RELEASE_TAG = "page"
        const val API_RELEASE = "https://api.github.com/repos/$REPO/releases/tags/$RELEASE_TAG"
        const val FILE_NAME = "koma-web.html"
        private const val VERSION_NAME = "version.json"
        private const val MIN_SIZE = 5_000_000L
        private const val UA = "KOMA-Android"
    }

    private val prefs = ctx.getSharedPreferences("koma", Context.MODE_PRIVATE)
    private val target get() = File(ctx.filesDir, FILE_NAME)
    private val tmp get() = File(ctx.filesDir, "$FILE_NAME.part")

    /** Файл обновления, если он есть и выглядит целым. */
    fun currentFile(): File? = target.takeIf { it.exists() && it.length() > MIN_SIZE }

    /**
     * Версия страницы, которая реально откроется.
     * Встроенная в АПК или уже скачанная — что там лежит, то и верно.
     */
    fun localVersion(): String =
        if (currentFile() != null) prefs.getString("htmlVersion", null) ?: assetsVersion else assetsVersion

    /**
     * Проверить и при необходимости скачать.
     * [progress] получает человеческие сообщения — их показываем тостами.
     * Возвращает JSON: {updated, version, reason}.
     */
    fun check(progress: (String) -> Unit = {}): JSONObject {
        val out = JSONObject().put("updated", false)
        try {
            progress("Проверяю обновление на GitHub…")
            val assetUrls = releaseAssets(get(API_RELEASE) { _, s -> s.readBytes().toString(Charsets.UTF_8) })
                ?: return out.put("reason", "в релизе «$RELEASE_TAG» нет файлов")

            // 1. Сначала только версия — сотня байт вместо 11 МБ.
            val remote = assetUrls[VERSION_NAME]
            var remoteVersion = ""
            if (remote != null) {
                try {
                    val vj = JSONObject(get(remote) { _, s -> s.readBytes().toString(Charsets.UTF_8) })
                    remoteVersion = vj.optString("page").trim()
                } catch (e: Throwable) {
                    GlensEngine.log("version.json: ${e.message}")
                }
            }
            val local = localVersion()
            if (remoteVersion.isNotEmpty()) {
                val cmp = compare(remoteVersion, local)
                if (cmp <= 0) {
                    return out.put("reason", "уже свежая ($local)")
                        .put("version", local)
                        .put("remote", remoteVersion)
                }
                progress("Найдена версия $remoteVersion — скачиваю…")
            } else {
                progress("Версии в релизе нет — проверяю страницу целиком")
            }

            // 2. Качаем страницу.
            val pageUrl = assetUrls[FILE_NAME]
                ?: return out.put("reason", "в релизе нет файла $FILE_NAME")
            val bytes = get(pageUrl) { conn, s ->
                val total = conn.contentLengthLong
                if (total > MIN_SIZE) progress("Скачиваю $remoteVersion (${total / 1024 / 1024} МБ)…")
                s.readBytes()
            }
            if (bytes.size < MIN_SIZE) return out.put("reason", "скачано подозрительно мало: ${bytes.size} Б")
            val text = String(bytes, Charsets.UTF_8)
            val ver = versionIn(text) ?: return out.put("reason", "в файле нет строки версии — не наша сборка")
            if (remoteVersion.isNotEmpty() && ver != remoteVersion) {
                // Файл и version.json разъехались — доверия нет, старое не трогаем.
                return out.put("reason", "версия в файле ($ver) не совпала с заявленной ($remoteVersion)")
            }
            // Та же версия, что уже стоит, — не перезаписываем и НЕ перезагружаем.
            if (compare(ver, local) <= 0) {
                return out.put("reason", "уже свежая ($local)").put("version", local)
            }

            tmp.writeBytes(bytes)
            if (!tmp.renameTo(target)) {
                target.delete()
                if (!tmp.renameTo(target)) return out.put("reason", "не удалось записать файл")
            }
            prefs.edit().putString("htmlVersion", ver).apply()
            GlensEngine.log("обновлено до $ver (${bytes.size} Б)")
            progress("Готово: $ver")
            return out.put("updated", true).put("version", ver).put("bytes", bytes.size)
        } catch (e: Throwable) {
            return out.put("reason", (e.message ?: e.javaClass.simpleName))
        }
    }

    // ── сеть ────────────────────────────────────────────────────────────────

    private fun releaseAssets(json: String): Map<String, String>? {
        val rel = JSONObject(json)
        val assets = rel.optJSONArray("assets") ?: return null
        val map = HashMap<String, String>()
        for (i in 0 until assets.length()) {
            val a = assets.getJSONObject(i)
            val name = a.optString("name")
            val url = a.optString("browser_download_url")
            if (name.isNotEmpty() && url.isNotEmpty()) map[name] = url
        }
        return map.ifEmpty { null }
    }

    private fun <T> get(url: String, read: (HttpURLConnection, java.io.InputStream) -> T): T {
        val conn = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 12000
            readTimeout = 120000
            instanceFollowRedirects = true
            setRequestProperty("User-Agent", UA)
            setRequestProperty("Accept", "application/vnd.github+json")
        }
        val code = conn.responseCode
        if (code !in 200..299) throw IllegalStateException("GitHub ответил HTTP $code")
        return conn.inputStream.use { read(conn, it) }
    }

    private fun versionIn(text: String): String? =
        Regex("VERSION = '(v[0-9.]+)'").find(text)?.groupValues?.get(1)

    /** Сравнение версий вида v1.9.34: >0 — первая новее. */
    private fun compare(a: String, b: String): Int {
        fun parts(v: String) = v.removePrefix("v").split('.').map { it.toIntOrNull() ?: 0 }
        val x = parts(a); val y = parts(b)
        for (i in 0 until maxOf(x.size, y.size)) {
            val d = (x.getOrNull(i) ?: 0) - (y.getOrNull(i) ?: 0)
            if (d != 0) return d
        }
        return 0
    }
}
