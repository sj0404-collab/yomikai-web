package net.koma.reader

import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException

/**
 * Нативный движок Google Lens — тот же путь, что в оригинальном yomikai:
 * приложение само отправляет кадр и само забирает текст. В WebView так нельзя
 * (CORS), а здесь можно: запрос делает приложение, а читалке отдаётся готовый
 * текст через мост [KomaLensBridge].
 *
 * Что внутри:
 *  1. POST multipart на lens.google.com/v3/upload (поле encoded_image);
 *  2. разбор ответа: сначала AF_initDataCallback (там Lens держит свой результат),
 *     затем общий поиск читаемых строк по всему телу ответа;
 *  3. понятная ошибка, если Google отдал антибот-страницу «включите JavaScript».
 *
 * Важно: запрос идёт в фоновом потоке, а мост ждёт результат с таймаутом.
 * Поток UI не занят, поэтому бейдж «Lens: распознаю без сайта…» продолжает
 * рисоваться, пока идёт распознавание.
 */
class GlensEngine(private val cookieProvider: () -> String?) {

    private val pool = Executors.newSingleThreadExecutor()

    data class Result(val lines: List<String>, val ms: Long)

    /** Распознать кадр JPEG. Бросает GlensError с человеческим текстом. */
    fun recognize(jpeg: ByteArray, timeoutSec: Long = 45): Result {
        val started = System.currentTimeMillis()
        val task = pool.submit(Callable {
            val body = request(jpeg)
            val lines = parse(body)
            if (lines.isEmpty()) {
                throw GlensError(
                    if (looksLikeAntiBot(body))
                        "Google вернул страницу «включите JavaScript» (антибот) — с этого адреса прямой запрос не проходит. " +
                        "Работает запасной путь: вставка текста или свой релей в «Голос и чтение»."
                    else
                        "в ответе Google не нашлось текста (${body.length} символов)"
                )
            }
            lines
        })
        return try {
            Result(task.get(timeoutSec, TimeUnit.SECONDS), System.currentTimeMillis() - started)
        } catch (e: TimeoutException) {
            task.cancel(true)
            throw GlensError("Google не ответил за $timeoutSec с")
        } catch (e: java.util.concurrent.ExecutionException) {
            throw (e.cause as? GlensError) ?: GlensError(String(e.cause?.message ?: e.message ?: "ошибка сети"))
        }
    }

    /** Диагностика для кнопки «Проверить Lens»: что именно ответил Google. */
    fun selfTest(): JSONObject {
        val out = JSONObject()
        return try {
            val t0 = System.currentTimeMillis()
            val body = request(syntheticJpeg())
            val lines = parse(body)
            out.put("ok", lines.isNotEmpty())
            out.put("ms", System.currentTimeMillis() - t0)
            out.put("bytes", body.length)
            out.put("lines", JSONArray(lines))
            out.put("antiBot", looksLikeAntiBot(body))
        } catch (e: Throwable) {
            out.put("ok", false).put("error", String(e.message ?: e.javaClass.simpleName))
        }
    }

    // ── сеть ────────────────────────────────────────────────────────────────
    private fun request(jpeg: ByteArray): String {
        val boundary = "----KomaLens" + System.nanoTime().toString(16)
        val url = URL("https://lens.google.com/v3/upload?hl=ru&stcs=${System.currentTimeMillis()}&ep=ccm")
        val conn = url.openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.connectTimeout = 15000
        conn.readTimeout = 40000
        conn.doOutput = true
        conn.instanceFollowRedirects = true
        conn.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
        conn.setRequestProperty("User-Agent", UA)
        conn.setRequestProperty("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        conn.setRequestProperty("Accept-Language", "ru-RU,ru;q=0.9,en;q=0.8")
        conn.setRequestProperty("Referer", "https://lens.google.com/")
        val cookies = cookieProvider()
        if (!cookies.isNullOrBlank()) conn.setRequestProperty("Cookie", cookies)

        val head = ("--$boundary\r\nContent-Disposition: form-data; name=\"encoded_image\"; filename=\"page.jpg\"\r\n" +
            "Content-Type: image/jpeg\r\n\r\n").toByteArray()
        val tail = "\r\n--$boundary--\r\n".toByteArray()
        conn.setFixedLengthStreamingMode(head.size + jpeg.size + tail.size)
        conn.outputStream.use { os ->
            os.write(head); os.write(jpeg); os.write(tail)
        }
        val code = conn.responseCode
        val stream: InputStream = if (code in 200..299) conn.inputStream else (conn.errorStream ?: conn.inputStream)
        val body = stream.use { readAll(it) }
        if (code !in 200..299) throw GlensError("Lens ответил HTTP $code")
        return body
    }

    private fun readAll(input: InputStream): String {
        val buf = ByteArrayOutputStream()
        val chunk = ByteArray(16 * 1024)
        while (true) {
            val n = input.read(chunk)
            if (n <= 0) break
            buf.write(chunk, 0, n)
        }
        return buf.toString("UTF-8")
    }

    // ── разбор ответа ───────────────────────────────────────────────────────
    private fun parse(body: String): List<String> {
        val fromBlocks = fromInitData(body)
        if (fromBlocks.isNotEmpty()) return fromBlocks
        return fromLooseText(body)
    }

    /** Lens складывает результат в AF_initDataCallback: там строки в кавычках. */
    private fun fromInitData(body: String): List<String> {
        var best = emptyList<String>()
        for (block in body.split("AF_initDataCallback")) {
            val found = ArrayList<String>()
            val re = Regex("\"((?:\\\\.|[^\"\\\\]){2,160})\"")
            for (m in re.findAll(block)) {
                val s = decodeEscapes(m.groupValues[1])
                val letters = s.count { it.isLetter() }
                if (letters >= 3 && letters.toDouble() / s.length > 0.55) found.add(s)
            }
            if (found.size > best.size) best = found
        }
        return best.filter { it.count { ch -> ch.isLetter() } >= 2 }
    }

    /**
     * Запасной разбор: в теле ответа (обычно JSON внутри script) ищем длинные
     * куски, где преобладают буквы и есть пробелы — это и есть реплики.
     * Нужен, потому что формат Lens меняется, а текст остаётся текстом.
     */
    private fun fromLooseText(body: String): List<String> {
        val out = ArrayList<String>()
        val re = Regex("\"((?:\\\\.|[^\"\\\\]){3,200})\"")
        for (m in re.findAll(body)) {
            val s = decodeEscapes(m.groupValues[1]).trim()
            val letters = s.count { it.isLetter() }
            val cyr = s.count { it in 'А'..'я' || it == 'Ё' || it == 'ё' }
            if (letters >= 4 && cyr >= 3 && letters.toDouble() / s.length > 0.5) out.add(s)
        }
        return out.distinct()
    }

    private fun decodeEscapes(s: String): String {
        if (!s.contains("\\u")) return s
        return Regex("\\\\u([0-9a-fA-F]{4})").replace(s) { m ->
            m.groupValues[1].toInt(16).toChar().toString()
        }
    }

    private fun looksLikeAntiBot(body: String): Boolean =
        body.contains("enablejs", ignoreCase = true) && !body.contains("AF_initDataCallback")

    /** Маленький кадр с текстом: чтобы «Проверить Lens» не требовал книги. */
    private fun syntheticJpeg(): ByteArray {
        val bmp = android.graphics.Bitmap.createBitmap(600, 200, android.graphics.Bitmap.Config.ARGB_8888)
        val c = android.graphics.Canvas(bmp)
        c.drawColor(android.graphics.Color.WHITE)
        val p = android.graphics.Paint().apply {
            color = android.graphics.Color.BLACK
            textSize = 48f
            isAntiAlias = true
        }
        c.drawText("Проверка движка KOMA", 20f, 100f, p)
        val out = ByteArrayOutputStream()
        bmp.compress(android.graphics.Bitmap.CompressFormat.JPEG, 85, out)
        return out.toByteArray()
    }

    companion object {
        // Мобильный Chrome: с ним Lens отдаёт страницу результата, а не заглушку.
        private const val UA =
            "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) " +
            "Chrome/122.0.0.0 Mobile Safari/537.36"
        fun log(msg: String) = Log.d("KomaLens", msg)
    }
}

class GlensError(message: String) : Exception(message)
