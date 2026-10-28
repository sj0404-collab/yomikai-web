package net.koma.reader

import android.content.Context
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.webkit.JavascriptInterface
import android.webkit.WebView
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale

/**
 * Голос для читалки: нативный синтез речи Android за мостом `KomaSpeech`.
 *
 * Зачем понадобился: в Android WebView **нет** Web Speech API — `speechSynthesis`
 * там просто отсутствует. 28.10 на телефоне это выглядело так: надпись «Скрипты
 * страницы не выполнились», тост «Ошибка: speechSynthesis is not defined» и
 * пустая библиотека, потому что первый же вызов голоса обрывал запуск страницы.
 *
 * Здесь то же самое, но сделано как надо: строку произносит системный движок
 * (тот, что в «Настройки → Синтез речи»), а страница получает события
 * start/end/error в `window.__komaSpeechEvent(id, тип, данные)` — ровно те же,
 * что даёт браузерный SpeechSynthesisUtterance.
 *
 * Android TTS инициализируется асинхронно, поэтому:
 *  • вызовы до готовности ставятся в очередь и выполняются после onInit;
 *  • если движка нет вовсе, странице честно говорится «не готов», а не молчание.
 */
class KomaSpeechBridge(
    private val ctx: Context,
    private val web: () -> WebView?,
) {

    private var tts: TextToSpeech? = null
    private var ready = false
    private var broken: String? = null
    private val waiting = ArrayList<() -> Unit>()

    private fun ensureTts() {
        if (tts != null) return
        tts = TextToSpeech(ctx.applicationContext) { status ->
            if (status == TextToSpeech.SUCCESS) {
                val t = tts
                if (t == null) { broken = "движок не создался"; return@TextToSpeech }
                ready = true
                t.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(utteranceId: String?) = fire(utteranceId, "start", "")
                    override fun onDone(utteranceId: String?) = fire(utteranceId, "end", "")
                    @Deprecated("старый API")
                    override fun onError(utteranceId: String?) = fire(utteranceId, "error", "engine")
                    override fun onError(utteranceId: String?, errorCode: Int) =
                        fire(utteranceId, "error", errName(errorCode))
                })
                // Русский — основной язык читалки; если его нет, движок сам
                // скажет об этом через status(), а speak() вернёт ошибку.
                trySetLocale(Locale.forLanguageTag("ru-RU"))
                flush()
            } else {
                broken = if (status == TextToSpeech.ERROR) "движок TTS не инициализировался" else "TTS: код $status"
                GlensEngine.log("KomaSpeech: $broken")
                flush()
            }
        }
    }

    private fun trySetLocale(locale: Locale): Int? = try {
        tts?.setLanguage(locale)
    } catch (e: Exception) { null }

    private fun flush() {
        val list = ArrayList(waiting)
        waiting.clear()
        list.forEach { runCatching(it) }
    }

    private fun fire(id: String?, type: String, data: String) {
        val ws = web() ?: return
        val argId = JSONObject.quote(id ?: "")
        val argType = JSONObject.quote(type)
        val argData = JSONObject.quote(data)
        ws.post {
            ws.evaluateJavascript(
                "window.__komaSpeechEvent&&window.__komaSpeechEvent($argId,$argType,$argData)", null
            )
        }
    }

    private fun errName(code: Int): String = when (code) {
        TextToSpeech.ERROR_SYNTHESIS -> "синтез не удался"
        TextToSpeech.ERROR_SERVICE -> "служба TTS недоступна"
        TextToSpeech.ERROR_OUTPUT -> "нет аудиовыхода"
        TextToSpeech.ERROR_NETWORK -> "нужна сеть для голоса"
        TextToSpeech.ERROR_NETWORK_TIMEOUT -> "сеть для голоса не ответила"
        TextToSpeech.ERROR_NOT_INSTALLED_YET -> "голос ещё не установлен"
        TextToSpeech.ERROR_INVALID_REQUEST -> "неверный запрос"
        else -> "ошибка движка ($code)"
    }

    // ── Мост для страницы ───────────────────────────────────────────────────

    /** Список голосов в формате Web Speech: {name, lang, voiceURI}. */
    @JavascriptInterface
    fun voices(): String {
        ensureTts()
        val out = JSONArray()
        val t = tts ?: return out.toString()
        if (!ready) return out.toString()
        try {
            for (v in t.voices ?: emptySet()) {
                if (v.locale == null) continue
                val lang = v.locale.toLanguageTag()
                out.put(JSONObject().put("name", v.name).put("lang", lang).put("voiceURI", "native:" + v.name))
            }
        } catch (e: Exception) {
            GlensEngine.log("voices: ${e.message}")
        }
        // Часть движков (в том числе Google TTS сразу после установки) список
        // голосов не отдаёт, хотя говорить умеет: voices == null/пусто, а
        // speak() при этом произносит текст системным голосом. Раньше страница
        // в этом случае писала «Система не дала ни одного голоса» и отказывалась
        // читать — хотя синтез живой. Отдаём один честный пункт: системный.
        if (out.length() == 0) {
            out.put(JSONObject().put("name", "Системный голос Android")
                .put("lang", "ru-RU").put("voiceURI", "native:default"))
        }
        return out.toString()
    }

    /** Готовность и что за движок — для «Проверить голос» и строки состояния. */
    @JavascriptInterface
    fun status(): String {
        ensureTts()
        val o = JSONObject().put("ready", ready)
        broken?.let { o.put("error", it) }
        try {
            o.put("engine", tts?.defaultEngine ?: "")
            o.put("voices", tts?.voices?.size ?: 0)
            o.put("ru", trySetLocale(Locale.forLanguageTag("ru-RU"))
                ?.let { it != TextToSpeech.LANG_MISSING_DATA && it != TextToSpeech.LANG_NOT_SUPPORTED } ?: false)
        } catch (e: Exception) { /* движок ещё не готов */ }
        return o.toString()
    }

    /**
     * Произнести строку. Страница ждёт событие start, затем end (или error) —
     * по ним отмечается «прочитано» и двигается подсветка букв.
     */
    @JavascriptInterface
    fun speak(text: String, rate: String, lang: String, voiceName: String, id: String) {
        ensureTts()
        val t = tts
        if (t == null || (!ready && broken == null)) {
            // Движок ещё поднимается — выполним сразу после onInit, чтобы первая
            // же реплика не терялась (это была бы «тишина без причины»).
            waiting.add { speak(text, rate, lang, voiceName, id) }
            return
        }
        if (!ready) {
            fire(id, "error", broken ?: "TTS не готов")
            return
        }
        try {
            val locale = try { Locale.forLanguageTag(lang.ifBlank { "ru-RU" }) } catch (e: Exception) { Locale.forLanguageTag("ru-RU") }
            val res = trySetLocale(locale)
            if (res == TextToSpeech.LANG_MISSING_DATA || res == TextToSpeech.LANG_NOT_SUPPORTED) {
                trySetLocale(Locale.forLanguageTag("ru-RU"))
            }
            val wanted = voiceName.trim()
            if (wanted.isNotEmpty()) {
                try {
                    t.voices?.firstOrNull { it.name == wanted }?.let { t.voice = it }
                } catch (e: Exception) { GlensEngine.log("голос «$wanted» не выбран: ${e.message}") }
            }
            t.setSpeechRate((rate.toFloatOrNull() ?: 1f).coerceIn(0.5f, 2.5f))
            val code = t.speak(text, TextToSpeech.QUEUE_FLUSH, null, id)
            if (code != TextToSpeech.SUCCESS) fire(id, "error", "движок не принял фразу ($code)")
        } catch (e: Exception) {
            fire(id, "error", e.message ?: "сбой синтеза")
        }
    }

    @JavascriptInterface
    fun cancel() {
        waiting.clear()
        try { tts?.stop() } catch (e: Exception) { /* уже остановлен */ }
    }

    /** Остановка из Activity (ушли из приложения — читать в кармане не надо). */
    fun stopAll() {
        waiting.clear()
        try { tts?.stop() } catch (e: Exception) { }
    }

    fun shutdown() {
        waiting.clear()
        try { tts?.stop(); tts?.shutdown() } catch (e: Exception) { }
        tts = null
        ready = false
    }
}
