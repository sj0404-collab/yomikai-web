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
 * Мост нативного распознавания: `window.KomaOcr`.
 *
 * Модели живут В ПРИЛОЖЕНИИ (filesDir/models), а не в IndexedDB страницы:
 *  • их выбирают системным «Файлами» — нативно, без прогона 12 МБ через base64;
 *  • считает ONNX Runtime для Android, без WebAssembly;
 *  • странице остаётся интерфейс, порядок реплик, словарь и озвучка.
 *
 * Вызов асинхронный: `recognizeAsync(base64, rulesJson, cbId)`, сообщения идут в
 * `window.__komaOcrEvent(cbId, 'state'|'done', данные)`. Синхронный вариант
 * держал бы поток JavaScript все секунды распознавания — на этом уже обжигались
 * с обновлением.
 */
class KomaOcrBridge(
    private val ctx: Context,
    private val engine: OcrEngine,
    private val web: () -> WebView?,
    private val requestModelFiles: () -> Unit,
) {

    private val pool = Executors.newSingleThreadExecutor()

    val modelsDir: File get() = File(ctx.filesDir, "models")

    @JavascriptInterface
    fun status(): String {
        val o = engine.status()
        o.put("engine", "native")
        o.put("dir", modelsDir.absolutePath)
        return o.toString()
    }

    /** Открыть системный выбор файлов моделей (det, rec, азбука). */
    @JavascriptInterface
    fun pickModels() {
        requestModelFiles()
    }

    /** Готовность без загрузки в память: страница спрашивает часто. */
    @JavascriptInterface
    fun available(): Boolean = engine.modelsPresent()

    /**
     * Импорт выбранных файлов. Классификация по имени, а если имена ничего не
     * говорят — по размеру: детектор всегда меньше распознавателя.
     */
    fun importFiles(uris: List<Uri>): JSONObject {
        val out = JSONObject()
        try {
            modelsDir.mkdirs()
            val onnx = ArrayList<Pair<Uri, Long>>()
            var charset: Uri? = null
            for (u in uris) {
                val name = (u.lastPathSegment ?: "").lowercase()
                val size = sizeOf(u)
                when {
                    name.endsWith(".txt") -> charset = u
                    name.endsWith(".onnx") -> onnx.add(u to size)
                    else -> {
                        // Имя без расширения: угадываем по содержимому.
                        if (size > 0 && size < 200_000) charset = u else onnx.add(u to size)
                    }
                }
            }
            if (onnx.isEmpty()) return out.put("ok", false).put("error", "не выбрано ни одного файла .onnx")
            val sorted = onnx.sortedBy { it.second }
            val detUri: Uri
            val recUri: Uri
            if (sorted.size >= 2) {
                val byNameDet = sorted.firstOrNull { (u, _) -> (u.lastPathSegment ?: "").lowercase().contains("det") }
                val byNameRec = sorted.firstOrNull { (u, _) -> (u.lastPathSegment ?: "").lowercase().let { n -> n.contains("rec") || n.contains("cyr") } }
                detUri = byNameDet?.first ?: sorted.first().first
                recUri = byNameRec?.first ?: sorted.last().first
            } else {
                return out.put("ok", false).put("error", "нужны два файла .onnx (детектор и распознаватель)")
            }
            copy(detUri, File(modelsDir, OcrEngine.DET))
            copy(recUri, File(modelsDir, OcrEngine.REC))
            if (charset != null) copy(charset, File(modelsDir, OcrEngine.CHARSET))
            if (!File(modelsDir, OcrEngine.CHARSET).exists()) {
                return out.put("ok", false).put("error", "нет файла азбуки (.txt): без него распознаватель не прочитать")
            }
            engine.reset()
            out.put("ok", true).put("status", JSONObject(engine.status().toString()))
        } catch (e: Throwable) {
            out.put("ok", false).put("error", e.message ?: e.javaClass.simpleName)
        }
        return out
    }

    private fun sizeOf(u: Uri): Long = try {
        ctx.contentResolver.openAssetFileDescriptor(u, "r")?.use { it.length } ?: 0L
    } catch (e: Throwable) { 0L }

    private fun copy(src: Uri, dst: File) {
        ctx.contentResolver.openInputStream(src)?.use { input ->
            dst.outputStream().use { output -> input.copyTo(output) }
        } ?: throw IllegalStateException("не удалось открыть файл")
    }

    /**
     * Распознать кадр нативно. Ответ: `{ok, items:[{text,left,top,right,bottom,confidence}], ms}`,
     * координаты — ДОЛИ кадра (0..1), как ждёт страница.
     */
    @JavascriptInterface
    fun recognizeAsync(base64Jpeg: String, rulesJson: String, cbId: String) {
        pool.execute {
            val t0 = System.currentTimeMillis()
            try {
                if (!engine.load()) {
                    emit(cbId, "done", JSONObject().put("ok", false)
                        .put("error", engine.error ?: "модели не загрузились").toString())
                    return@execute
                }
                val items = engine.recognize(base64Jpeg, rulesJson) { msg -> emit(cbId, "state", msg) }
                // Переводим пиксели в доли кадра: страница живёт в нормализованных координатах.
                val dims = decodeSize(base64Jpeg)
                val arr = JSONArray()
                for (it in items) {
                    arr.put(JSONObject()
                        .put("text", it.text)
                        .put("left", it.left.toDouble() / dims.first)
                        .put("top", it.top.toDouble() / dims.second)
                        .put("right", it.right.toDouble() / dims.first)
                        .put("bottom", it.bottom.toDouble() / dims.second)
                        .put("confidence", it.confidence))
                }
                emit(cbId, "done", JSONObject()
                    .put("ok", true)
                    .put("items", arr)
                    .put("ms", System.currentTimeMillis() - t0)
                    .put("via", "native")
                    .toString())
            } catch (t: Throwable) {
                emit(cbId, "done", JSONObject().put("ok", false)
                    .put("error", t.message ?: t.javaClass.simpleName).toString())
            }
        }
    }

    /** Размер кадра без полного декодирования — нужен для нормализации координат. */
    private fun decodeSize(base64Jpeg: String): Pair<Int, Int> {
        return try {
            val bytes = android.util.Base64.decode(base64Jpeg, android.util.Base64.DEFAULT)
            val opts = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
            android.graphics.BitmapFactory.decodeByteArray(bytes, 0, bytes.size, opts)
            Pair(maxOf(1, opts.outWidth), maxOf(1, opts.outHeight))
        } catch (e: Throwable) { Pair(1, 1) }
    }

    /** Проверка на синтетической странице: видно, что движок реально читает. */
    @JavascriptInterface
    fun selfTestAsync(cbId: String) {
        pool.execute {
            val res = try { engine.selfTest() } catch (t: Throwable) {
                JSONObject().put("ok", false).put("error", t.message ?: t.javaClass.simpleName)
            }
            emit(cbId, "done", res.toString())
        }
    }

    private fun emit(cbId: String, type: String, data: String) {
        val ws = web() ?: return
        val id = JSONObject.quote(cbId)
        val t = JSONObject.quote(type)
        val d = JSONObject.quote(data)
        ws.post { ws.evaluateJavascript("window.__komaOcrEvent&&window.__komaOcrEvent($id,$t,$d)", null) }
    }
}
