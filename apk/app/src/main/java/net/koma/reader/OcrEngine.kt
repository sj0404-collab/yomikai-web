package net.koma.reader

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Base64
import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.nio.FloatBuffer
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Распознавание страницы НАТИВНО: те же модели (детектор + распознаватель),
 * тот же алгоритм, что в странице, но исполняет их ONNX Runtime для Android —
 * без WebAssembly, без 11 МБ вшитого в html движка и без потолка скорости,
 * который даёт браузерный WASM.
 *
 * Почему это отдельный класс, а не «ещё один мост»: расчёт живёт в приложении,
 * страница остаётся интерфейсом. Всё, что отвечает за качество сборки текста
 * (порядок реплик справа налево, склейка в реплики, словарь, варианты чтения),
 * осталось в странице без изменений — нативный код отдаёт ровно те же строки с
 * теми же прямоугольниками, что отдавал браузерный конвейер. Поэтому включение
 * нативного движка не может испортить чтение: если что-то не так, страница
 * возвращается к проверенному WASM-пути.
 *
 * Соответствие шагов (страница → приложение):
 *   detectBoxes     → [detect]
 *   components      → [components]
 *   textLines       → [textLines]
 *   recProbs+CTC    → [decode]
 *   recognizePage   → [recognize] (только боксы 1-го прохода; проходы «крупный
 *                     текст» и «области без боксов» пока остаются в странице)
 */
class OcrEngine(private val modelsDir: File) {

    companion object {
        const val DET = "det.onnx"
        const val REC = "rec.onnx"
        const val CHARSET = "charset.txt"
        private const val DET_THRESHOLD = 0.3f
    }

    class Rules(
        val pageSide: Int = 1600,
        val minConfidence: Double = 0.25,
        val detRetry: Boolean = true,
        val inkLowPercentile: Double = 0.02,
        val inkHighPercentile: Double = 0.98,
        val inkFlatSpread: Int = 10,
        val inkCoefficient: Double = 0.45,
        val inkMin: Int = 40,
        val inkMax: Int = 235,
        val inkTileRows: Int = 4,
        val inkLevels: Int = 1,
    ) {
        companion object {
            fun from(json: String?): Rules {
                val o = try { JSONObject(json ?: "{}") } catch (e: Throwable) { JSONObject() }
                val d = Rules()
                return Rules(
                    pageSide = o.optInt("pageSide", d.pageSide),
                    minConfidence = o.optDouble("minConfidence", d.minConfidence),
                    detRetry = o.optBoolean("detRetry", d.detRetry),
                    inkLowPercentile = o.optDouble("inkLowPercentile", d.inkLowPercentile),
                    inkHighPercentile = o.optDouble("inkHighPercentile", d.inkHighPercentile),
                    inkFlatSpread = o.optInt("inkFlatSpread", d.inkFlatSpread),
                    inkCoefficient = o.optDouble("inkCoefficient", d.inkCoefficient),
                    inkMin = o.optInt("inkMin", d.inkMin),
                    inkMax = o.optInt("inkMax", d.inkMax),
                    inkTileRows = o.optInt("inkTileRows", d.inkTileRows),
                    inkLevels = o.optInt("inkLevels", d.inkLevels),
                )
            }
        }
    }

    data class Item(val text: String, val left: Int, val top: Int, val right: Int, val bottom: Int, val confidence: Double)

    private var env: OrtEnvironment? = null
    private var det: OrtSession? = null
    private var rec: OrtSession? = null
    private var charset: List<String> = emptyList()
    var error: String? = null
        private set

    /** Забыть загруженные модели: после импорта новых файлов сессии создаются заново. */
    @Synchronized
    fun reset() {
        try { det?.close() } catch (e: Throwable) { }
        try { rec?.close() } catch (e: Throwable) { }
        det = null; rec = null; charset = emptyList(); error = null
    }

    fun modelsPresent(): Boolean =
        File(modelsDir, DET).exists() && File(modelsDir, REC).exists() && File(modelsDir, CHARSET).exists()

    fun ready(): Boolean = modelsPresent() && det != null && rec != null && charset.isNotEmpty()

    /** Загрузить модели в память (один раз; повторный вызов ничего не делает). */
    @Synchronized
    fun load(): Boolean {
        if (ready()) return true
        error = null
        if (!modelsPresent()) { error = "модели не выбраны"; return false }
        return try {
            val e = OrtEnvironment.getEnvironment()
            val opts = OrtSession.SessionOptions().apply {
                setIntraOpNumThreads(max(2, Runtime.getRuntime().availableProcessors() / 2))
                setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
            }
            det = e.createSession(File(modelsDir, DET).absolutePath, opts)
            rec = e.createSession(File(modelsDir, REC).absolutePath, opts)
            charset = readCharset(File(modelsDir, CHARSET))
            env = e
            if (charset.isEmpty()) { error = "файл азбуки пуст"; return false }
            GlensEngine.log("нативный OCR: модели загружены, классов ${charset.size}")
            true
        } catch (t: Throwable) {
            error = "модели не загрузились: ${t.message ?: t.javaClass.simpleName}"
            GlensEngine.log("нативный OCR: $error")
            false
        }
    }

    /**
     * Азбука распознавателя: одна позиция на строку файла, как в странице.
     * Класс 0 — «пусто», последний класс — пробел (ровно как OCR.dict в part3.js).
     */
    private fun readCharset(f: File): List<String> {
        val lines = f.readText().split('\n').map { it.trimEnd('\r') }.toMutableList()
        while (lines.isNotEmpty() && lines.last().isEmpty()) lines.removeAt(lines.size - 1)
        return listOf("") + lines + listOf(" ")
    }

    fun status(): JSONObject {
        val o = JSONObject()
        o.put("ready", ready())
        o.put("models", modelsPresent())
        o.put("classes", charset.size)
        o.put("error", error ?: "")
        o.put("ort", "onnxruntime-android")
        o.put("files", JSONObject()
            .put(DET, File(modelsDir, DET).length())
            .put(REC, File(modelsDir, REC).length())
            .put(CHARSET, File(modelsDir, CHARSET).length()))
        return o
    }

    /** Распознать кадр (JPEG base64). Возвращает список строк страницы. */
    fun recognize(base64Jpeg: String, rulesJson: String?, progress: (String) -> Unit): List<Item> {
        if (!load()) throw IllegalStateException(error ?: "нативный движок не готов")
        val bytes = Base64.decode(base64Jpeg, Base64.DEFAULT)
        val page = BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
            ?: throw IllegalStateException("кадр не декодировался")
        return recognizeBitmap(page, Rules.from(rulesJson), progress)
    }

    fun recognizeBitmap(page: Bitmap, rules: Rules, progress: (String) -> Unit): List<Item> {
        val t0 = System.currentTimeMillis()
        progress("детектор: ищу блоки текста")
        val boxes = detect(page, rules.pageSide, rules.detRetry)
        val detMs = System.currentTimeMillis() - t0
        if (boxes.isEmpty()) { GlensEngine.log("нативный OCR: боксов 0 за $detMs мс"); return emptyList() }
        progress("детектор нашёл ${boxes.size} блоков за $detMs мс")

        val out = ArrayList<Item>()
        var done = 0
        for (b in boxes) {
            done++
            progress("распознаю $done/${boxes.size}")
            val lines = textLines(page, b, rules).ifEmpty { listOf(b) }
            for (ln in lines) {
                val w = max(1, ln[2] - ln[0])
                val h = max(1, ln[3] - ln[1])
                val crop = try { Bitmap.createBitmap(page, ln[0], ln[1], w, h) } catch (e: Throwable) { continue }
                val wide = w.toDouble() / page.width >= 0.25
                val (text, conf) = try { decode(crop, wide) } finally { crop.recycle() }
                if (text.isBlank() || conf <= rules.minConfidence) continue
                out.add(Item(text.trim(), ln[0], ln[1], ln[2], ln[3], conf))
            }
        }
        GlensEngine.log("нативный OCR: ${out.size} строк за ${System.currentTimeMillis() - t0} мс")
        return out
    }

    // ── 1. Детектор ──────────────────────────────────────────────────────────

    /** detectBoxes: кадр → боксы в координатах ДЕТЕКТОРА, затем обратно в кадр. */
    private fun detect(src: Bitmap, side: Int, retry: Boolean): List<IntArray> {
        val w0 = src.width; val h0 = src.height
        val ratio = min(1.0, side.toDouble() / max(w0, h0))
        val w = max(32, ((w0 * ratio / 32).roundToInt()) * 32)
        val h = max(32, ((h0 * ratio / 32).roundToInt()) * 32)
        val small = Bitmap.createScaledBitmap(src, w, h, true)
        val px = IntArray(w * h)
        small.getPixels(px, 0, w, 0, 0, w, h)
        if (small !== src) small.recycle()

        val f = FloatArray(3 * w * h)
        val mean = floatArrayOf(0.485f, 0.456f, 0.406f)
        val std = floatArrayOf(0.229f, 0.224f, 0.225f)
        fun fill(normalize: Boolean) {
            for (ch in 0 until 3) {
                val off = ch * w * h
                val shift = when (ch) { 0 -> 16; 1 -> 8; else -> 0 }
                for (i in 0 until w * h) {
                    val v = ((px[i] shr shift) and 0xFF) / 255f
                    f[off + i] = if (normalize) (v - mean[ch]) / std[ch] else v
                }
            }
        }

        var raw = runDet(f, h, w)
        if (raw.isEmpty() && retry) { fill(true); raw = runDet(f, h, w) }
        val out = ArrayList<IntArray>()
        for (b in raw.take(400)) {
            val left = clamp(((b[0].toDouble() / w) * w0).roundToInt(), 0, w0 - 1)
            val top = clamp(((b[1].toDouble() / h) * h0).roundToInt(), 0, h0 - 1)
            val right = clamp(((b[2].toDouble() / w) * w0).roundToInt(), 0, w0)
            val bottom = clamp(((b[3].toDouble() / h) * h0).roundToInt(), 0, h0)
            if (right > left && bottom > top) out.add(intArrayOf(left, top, right, bottom))
        }
        return out
    }

    private fun runDet(f: FloatArray, h: Int, w: Int): List<IntArray> {
        val sess = det ?: return emptyList()
        val e = env ?: return emptyList()
        val name = sess.inputNames.first()
        val shape = longArrayOf(1, 3, h.toLong(), w.toLong())
        OnnxTensor.createTensor(e, FloatBuffer.wrap(f), shape).use { tensor ->
            sess.run(mapOf(name to tensor)).use { res ->
                val t = res[0] as OnnxTensor
                val buf = t.floatBuffer
                val map = FloatArray(w * h)
                buf.get(map)
                return components(map, h, w)
            }
        }
    }

    /** components: BFS по карте вероятностей, порог 0.3, тот же расширяющий запас. */
    private fun components(map: FloatArray, h: Int, w: Int): List<IntArray> {
        val visited = BooleanArray(w * h)
        val queue = IntArray(w * h)
        val boxes = ArrayList<IntArray>()
        for (y in 0 until h) for (x in 0 until w) {
            val idx = y * w + x
            if (visited[idx] || map[idx] < DET_THRESHOLD) continue
            var start = 0; var end = 1
            queue[0] = idx; visited[idx] = true
            var minX = x; var maxX = x; var minY = y; var maxY = y
            var score = 0.0
            while (start < end) {
                val n = queue[start++]
                val xx = n % w; val yy = (n - xx) / w
                score += map[n]
                if (xx < minX) minX = xx
                if (xx > maxX) maxX = xx
                if (yy < minY) minY = yy
                if (yy > maxY) maxY = yy
                if (xx > 0) { val ni = n - 1; if (!visited[ni] && map[ni] > DET_THRESHOLD) { visited[ni] = true; queue[end++] = ni } }
                if (xx < w - 1) { val ni = n + 1; if (!visited[ni] && map[ni] > DET_THRESHOLD) { visited[ni] = true; queue[end++] = ni } }
                if (yy > 0) { val ni = n - w; if (!visited[ni] && map[ni] > DET_THRESHOLD) { visited[ni] = true; queue[end++] = ni } }
                if (yy < h - 1) { val ni = n + w; if (!visited[ni] && map[ni] > DET_THRESHOLD) { visited[ni] = true; queue[end++] = ni } }
            }
            if (end < 6 || score / end < 0.5 || maxX - minX < 2 || maxY - minY < 2) continue
            val expand = max(2, (((maxX - minX) * (maxY - minY) * 1.5) / (2 * (maxX - minX + maxY - minY + 1))).roundToInt())
            boxes.add(intArrayOf(
                max(0, minX - expand), max(0, minY - expand),
                min(w, maxX + expand + 1), min(h, maxY + expand + 1)
            ))
        }
        boxes.sortBy { it[1] }
        return boxes
    }

    // ── 2. Нарезка блока на строки по профилю «чернил» ─────────────────────

    private fun textLines(page: Bitmap, box: IntArray, rules: Rules): List<IntArray> {
        val pad = max(2, ((box[3] - box[1]) * 0.12).toInt())
        val left = max(0, box[0] - pad)
        val right = min(page.width, box[2] + pad)
        val top = max(0, box[1] - pad)
        val bottom = min(page.height, box[3] + pad)
        if (right - left < 4 || bottom - top < 4) return emptyList()

        val scale = min(1.0, 400.0 / (right - left))
        val w = max(4, ((right - left) * scale).roundToInt())
        val h = max(4, ((bottom - top) * scale).roundToInt())
        val crop = Bitmap.createBitmap(page, left, top, right - left, bottom - top)
        val small = Bitmap.createScaledBitmap(crop, w, h, true)
        crop.recycle()
        val px = IntArray(w * h)
        small.getPixels(px, 0, w, 0, 0, w, h)
        small.recycle()

        val luma = IntArray(w * h)
        for (i in 0 until w * h) {
            val p = px[i]
            luma[i] = (((p shr 16) and 0xFF) * 77 + ((p shr 8) and 0xFF) * 151 + (p and 0xFF) * 28) shr 8
        }
        if (inkThreshold(luma, rules) < 0) return emptyList()

        val rows = clamp(rules.inkTileRows, 1, 16)
        val tileH = max(1, ceil(h.toDouble() / rows).toInt())
        val thr = IntArray(rows) { i ->
            val y0 = i * tileH; val y1 = min(h, y0 + tileH)
            if (y1 <= y0) -1 else inkThreshold(luma.copyOfRange(y0 * w, y1 * w), rules)
        }
        fun thrAt(y: Int) = thr[clamp(y / tileH, 0, rows - 1)]
        val need = max(1, w / 60)
        fun rowHasInk(y: Int): Boolean {
            var cnt = 0
            val base = y * w
            for (x in 0 until w) if (luma[base + x] < thrAt(y)) { if (++cnt >= need) return true }
            return false
        }

        val runs = ArrayList<IntArray>()
        var y = 0
        while (y < h) {
            if (!rowHasInk(y)) { y++; continue }
            var end = y
            while (end < h && rowHasInk(end)) end++
            if (end > y) runs.add(intArrayOf(y, end))
            y = max(end, y + 1)
        }
        if (runs.isEmpty()) return emptyList()

        val heights = runs.map { it[1] - it[0] }.sorted()
        val median = max(1, heights[heights.size shr 1])
        val merged = ArrayList<IntArray>()
        for (r in runs) {
            val last = merged.lastOrNull()
            if (last != null && r[0] - last[1] <= max(1, (median * 0.35).toInt())) last[1] = r[1]
            else merged.add(intArrayOf(r[0], r[1]))
        }

        val lines = ArrayList<IntArray>()
        for (r in merged) {
            if (r[1] - r[0] < max(2, (median * 0.4).toInt())) continue
            var x0 = w; var x1 = -1
            for (yy in r[0] until r[1]) for (xx in 0 until w) {
                if (luma[yy * w + xx] < thrAt(yy)) { if (xx < x0) x0 = xx; if (xx > x1) x1 = xx }
            }
            if (x1 < 0) continue
            lines.add(intArrayOf(
                clamp((left + x0 / scale).roundToInt(), left, right - 1),
                clamp((top + r[0] / scale).roundToInt(), top, bottom - 1),
                clamp((left + (x1 + 1) / scale).roundToInt(), left + 1, right),
                clamp((top + (r[1] + 1) / scale).roundToInt(), top + 1, bottom),
            ))
        }
        return lines
    }

    /** inkThreshold: порог «чернил» по перцентилям яркости (как в странице). */
    private fun inkThreshold(luma: IntArray, rules: Rules): Int {
        if (luma.isEmpty()) return -1
        val hist = IntArray(256)
        for (v in luma) hist[v and 0xFF]++
        fun pct(p: Double): Int {
            val target = max(1, (luma.size * p).toInt())
            var acc = 0
            for (i in 0 until 256) { acc += hist[i]; if (acc >= target) return i }
            return 255
        }
        val low = pct(rules.inkLowPercentile)
        val high = pct(rules.inkHighPercentile)
        if (high - low < rules.inkFlatSpread) return -1
        return clamp((low + (high - low) * rules.inkCoefficient).roundToInt(), rules.inkMin, rules.inkMax)
    }

    // ── 3. Распознавание кропа строки ───────────────────────────────────────

    /** decodeCrop: кроп → (текст, средняя уверенность) жадным CTC-разбором. */
    private fun decode(crop: Bitmap, wide: Boolean): Pair<String, Double> {
        val sess = rec ?: return "" to 0.0
        val e = env ?: return "" to 0.0
        var src = crop
        var rotated = false
        if (crop.height > crop.width * 1.8) {
            val m = android.graphics.Matrix().apply { postRotate(90f) }
            src = Bitmap.createBitmap(crop, 0, 0, crop.width, crop.height, m, true)
            rotated = true
        }
        val w0 = src.width; val h0 = src.height
        if (w0 < 2 || h0 < 2) { if (rotated) src.recycle(); return "" to 0.0 }
        val width = clamp(((48.0 * w0) / h0).roundToInt(), 8, 960)
        val padded = max(320, width)
        val scaled = Bitmap.createScaledBitmap(src, width, 48, true)
        if (rotated) src.recycle()

        val px = IntArray(width * 48)
        scaled.getPixels(px, 0, width, 0, 0, width, 48)
        scaled.recycle()

        val f = FloatArray(3 * 48 * padded) { -1f }        // поля = чёрные, как прозрачный canvas
        for (ch in 0 until 3) {
            val off = ch * 48 * padded
            val shift = when (ch) { 0 -> 16; 1 -> 8; else -> 0 }
            for (y in 0 until 48) for (x in 0 until width) {
                val v = ((px[y * width + x] shr shift) and 0xFF) / 255f
                f[off + y * padded + x] = (v - 0.5f) / 0.5f
            }
        }

        val name = sess.inputNames.first()
        val shape = longArrayOf(1, 3, 48, padded.toLong())
        OnnxTensor.createTensor(e, FloatBuffer.wrap(f), shape).use { tensor ->
            sess.run(mapOf(name to tensor)).use { res ->
                val t = res[0] as OnnxTensor
                val info = t.info as ai.onnxruntime.TensorInfo
                val dims = info.shape                       // [1, T, C]
                val T = dims[1].toInt()
                val C = dims[2].toInt()
                val values = FloatArray(T * C)
                t.floatBuffer.get(values)
                val chars = charset
                val sb = StringBuilder()
                var prev = 0
                var score = 0.0
                var count = 0
                for (ti in 0 until T) {
                    val base = ti * C
                    var best = 0
                    var bestV = values[base]
                    for (ci in 1 until C) { val v = values[base + ci]; if (v > bestV) { bestV = v; best = ci } }
                    if (best != 0 && best != prev) {
                        if (best < chars.size) sb.append(chars[best])
                        score += bestV; count++
                    }
                    prev = best
                }
                return sb.toString() to (if (count > 0) score / count else 0.0)
            }
        }
    }

    private fun clamp(v: Int, lo: Int, hi: Int) = if (v < lo) lo else if (v > hi) hi else v

    /** Тест движка на синтетической странице: видно, что модели реально считают. */
    fun selfTest(): JSONObject {
        val o = JSONObject()
        if (!load()) return o.put("ok", false).put("error", error ?: "движок не готов")
        return try {
            val t0 = System.currentTimeMillis()
            val bmp = android.graphics.Bitmap.createBitmap(900, 300, android.graphics.Bitmap.Config.ARGB_8888)
            val c = android.graphics.Canvas(bmp)
            c.drawColor(android.graphics.Color.WHITE)
            val p = android.graphics.Paint().apply {
                color = android.graphics.Color.BLACK; textSize = 64f; isAntiAlias = true
            }
            c.drawText("Проверка движка KOMA", 40f, 120f, p)
            c.drawText("Вторая строка", 40f, 230f, p)
            val items = recognizeBitmap(bmp, Rules(), {})
            bmp.recycle()
            val arr = JSONArray()
            for (it in items) arr.put(JSONObject().put("text", it.text).put("confidence", it.confidence))
            o.put("ok", items.isNotEmpty())
                .put("ms", System.currentTimeMillis() - t0)
                .put("items", arr)
                .put("text", items.joinToString(" | ") { it.text })
        } catch (t: Throwable) {
            o.put("ok", false).put("error", t.message ?: t.javaClass.simpleName)
        }
    }
}
