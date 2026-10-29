package net.koma.reader

import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.max
import kotlin.math.min

/**
 * ДВИЖОК ЧТЕНИЯ в приложении: из строк распознавания собирает РЕПЛИКИ в
 * правильном порядке. Раньше это целиком жило в странице (bubblesOf,
 * mergeBubbles, orderBubbles, readingOrder), и именно там чтение то прыгало,
 * то читало одну реплику, то корёжило слова.
 *
 * Что здесь есть:
 *  • строки → «ряды» по вертикали, внутри ряда — справа налево (манга);
 *  • склейка обрывков: «ВЫСО-» + «ЧЕСТВО» → «ВЫСОЧЕСТВО»;
 *  • ряды → облачка: по перекрытию по вертикали и зазору по горизонтали;
 *  • потолок высоты облачка (иначе проза склеивается в «реплику» на 75 слов);
 *  • разрезание слишком высокого блока по самому большому пробелу;
 *  • порядок реплик: сверху вниз, реплики на одной высоте — справа налево.
 *
 * Чего здесь НЕТ и почему: языковая починка и словарь (Words.polish) остаются в
 * странице — словарь весит 3 МБ, и его перенос не влияет ни на скорость, ни на
 * порядок. Приложение отвечает за геометрию и порядок, страница — за слова.
 */
class ReadEngine {

    class Line(
        val text: String,
        val left: Double,
        val top: Double,
        val right: Double,
        val bottom: Double,
        val confidence: Double = 0.0,
    ) {
        val height: Double get() = max(bottom - top, 1e-6)
        val width: Double get() = max(right - left, 1e-6)
        val letters: Int get() = text.count { it.isLetter() || it.isDigit() }
    }

    class Rules(
        val dir: String = "rtl",
        val bubbleGap: Double = 0.45,
        val mergeHeightRatio: Double = 1.8,
        val maxBlockHeight: Double = 0.22,
    ) {
        val rtl: Boolean get() = dir != "ltr"

        companion object {
            fun from(json: String?): Rules {
                val o = try { JSONObject(json ?: "{}") } catch (e: Throwable) { JSONObject() }
                val d = Rules()
                return Rules(
                    dir = o.optString("dir", d.dir).ifBlank { d.dir },
                    bubbleGap = o.optDouble("bubbleGap", d.bubbleGap),
                    mergeHeightRatio = o.optDouble("mergeHeightRatio", d.mergeHeightRatio),
                    maxBlockHeight = o.optDouble("maxBlockHeight", d.maxBlockHeight),
                )
            }
        }
    }

    companion object {
        /** Сколько строк максимум берём в работу: защита от мусорного детектора. */
        private const val MAX_LINES = 2000

        private fun cleanSpeech(t: String): String =
            trimJunkEdges(t.replace('\u00AD', '-').replace(Regex("\\s+"), " ").trim())

        /**
         * Мусорные края реплики: обрывок звукового эффекта («*ь*.*о») иногда
         * приклеивается к началу честной строки. Снимаем крайние слова, где
         * букв 1–2 и знаков (не букв) не меньше двух; одиночная кавычка или
         * тире в начале нормальной реплики остаётся.
         */
        private fun trimJunkEdges(text: String): String {
            val tokens = text.split(' ').filter { it.isNotEmpty() }.toMutableList()
            fun junk(t: String): Boolean {
                val letters = t.count { it.isLetter() }
                val marks = t.count { !it.isLetterOrDigit() }
                return letters <= 2 && marks >= 2
            }
            while (tokens.size > 1 && junk(tokens.first())) tokens.removeAt(0)
            while (tokens.size > 1 && junk(tokens.last())) tokens.removeAt(tokens.size - 1)
            return tokens.joinToString(" ")
        }
    }

    /**
     * Строка (или блок строк) с «типичной высотой» — как lh в странице.
     * rows — сколько текстовых строк внутри блока; высота ОДНОЙ строки
     * считается как span/rows. Минимум высот для этого не годился: одна тонкая
     * строка (детектор иногда отдаёт полоску в 2 пикселя) навсегда занижала lh,
     * и следующие строки облачка уже не приклеивались — реплика разрезалась на
     * два текста (эмулятор Forge, 29.10).
     */
    private class Row(
        var text: String,
        var left: Double,
        var top: Double,
        var right: Double,
        var bottom: Double,
        var lh: Double,
        /** Сколько текстовых строк внутри блока (для средней высоты строки). */
        var rows: Int = 1,
    ) {
        val w: Double get() = right - left
        val h: Double get() = bottom - top
    }

    /** Склейка соседних кусков одной реплики: «ВЫСО-» + «ЧЕСТВО» → слитно. */
    private fun joinText(a: String, b: String): String {
        val left = a.trim()
        val right = b.trim()
        if (left.isEmpty()) return right
        if (right.isEmpty()) return left
        val last = left.last()
        // «ВЫСО-» + «ЧЕСТВО» (или «-ЧЕСТВО») → «ВЫСОЧЕСТВО»: перенос слова.
        val hyph = "-\u2010\u2011\u2013\u2014\u2015"
        if (hyph.indexOf(last) >= 0) return left.dropLast(1) + right.trimStart(*hyph.toCharArray())
        if (hyph.indexOf(right.first()) >= 0 && left.last().isLetter()) return left + right.drop(1)
        // «БУДЕ.» + «ТЕ ГОВОРИТЬ» → «БУДЕТЕ ГОВОРИТЬ»: перенос слова OCR прочитал
        // точкой вместо дефиса. Склеиваем только короткий обрывок.
        val m = Regex("([\\p{L}]{2,})[.\\-]$").find(left)
        if (m != null) {
            val head = right.split(Regex("\\s+")).firstOrNull() ?: ""
            if (head.isNotEmpty() && head.first().isLetter() && head.length <= 3) {
                return left.dropLast(1) + right
            }
        }
        return "$left $right"
    }

    /** Приклеивается ли строка b к реплике a (порт sameBubble из страницы). */
    private fun sameBubble(a: Row, b: Row, R: Rules): Boolean {
        if (a.w <= 0 || b.w <= 0 || a.h <= 0 || b.h <= 0) return false
        val overlap = min(a.right, b.right) - max(a.left, b.left)
        if (overlap <= 0) return false
        if (overlap / min(a.w, b.w) < 0.30) return false
        val centerShift = kotlin.math.abs((a.left + a.right) / 2 - (b.left + b.right) / 2)
        if (centerShift > max(a.w, b.w) * 0.8) return false
        val gap = b.top - a.bottom
        if (gap < -a.h * 0.6 || gap > max(a.h, b.h) * max(1.2, R.bubbleGap)) return false
        if (a.h > a.w * 3 || b.h > b.w * 3) return false     // вертикальные колонки — не строки
        val heightOk = max(a.lh, b.lh) / min(a.lh, b.lh) <= R.mergeHeightRatio
        if (!heightOk) {
            // Высота рамки — плохой признак кегля: детектор обводит «ЯРАССЧИ-» по
            // заглавным, а «ТbВАЮ» под ним — по строчным, и облачко рвалось на
            // реплики. Сравниваем средний шаг буквы (ширина / число букв); порог
            // мягкий, поэтому «заголовок + мелкие титры» остаются разными.
            fun adv(x: Row): Double = x.w / max(1, x.text.count { it.isLetterOrDigit() }).toDouble()
            val aAdv = adv(a)
            val bAdv = adv(b)
            if (aAdv <= 0.0 || bAdv <= 0.0) return false
            if (max(aAdv, bAdv) / min(aAdv, bAdv) > 1.35) return false
            if (min(a.h, b.h) < max(a.h, b.h) * 0.3) return false
        }
        val mergedTop = min(a.top, b.top)
        val mergedBottom = max(a.bottom, b.bottom)
        if (mergedBottom - mergedTop > R.maxBlockHeight) return false
        return true
    }

    /** Главная точка входа: строки → реплики в порядке чтения. */
    fun plan(items: List<Line>, R: Rules): List<JSONObject> {
        val kept = items.filter { it.text.isNotBlank() && it.letters >= 1 }.take(MAX_LINES)
        if (kept.isEmpty()) return emptyList()
        // Тонкие полоски-обрывки убираем ДО склейки: детектор иногда отдаёт
        // рамку высотой в 2–3 пикселя поперёк картинки. Текст из неё — мусор, а
        // крошечная высота портила «типичную высоту строки», и соседняя честная
        // строка переставала приклеиваться — реплика разрезалась на два текста
        // (нашлось прогоном в эмуляторе APKForge, 29.10).
        // Фильтр включается ТОЛЬКО на настоящей странице (>= 4 строк): на двух
        // строках («заголовок + титры») медиана считала заголовок, и титры
        // выбрасывались — они становились частью заголовка.
        val rawHeights = kept.map { it.height }.filter { it > 0 }.sorted()
        val medianRaw = if (rawHeights.isEmpty()) 0.0 else rawHeights[rawHeights.size / 2]
        val filtered = if (kept.size >= 4 && medianRaw > 0)
            kept.filter { it.height >= medianRaw * 0.35 } else kept
        val src = filtered.ifEmpty { kept }.sortedWith(compareBy({ it.top }, { it.left }))

        // ── A. Облачка-блоки: строку приклеиваем, если она рядом по вертикали
        //       и по горизонтали (это уровень «бокс детектора»).
        val blocks = ArrayList<MutableList<Line>>()
        for (ln in src) {
            var target: MutableList<Line>? = null
            var bestGap = Double.MAX_VALUE
            for (block in blocks) {
                val head = block.last()
                val overlap = min(head.bottom, ln.bottom) - max(head.top, ln.top)
                if (overlap <= head.height * 0.35) continue
                val blockLeft = block.minOf { it.left }
                val blockRight = block.maxOf { it.right }
                val gap = when {
                    ln.left > blockRight -> ln.left - blockRight
                    ln.right < blockLeft -> blockLeft - ln.right
                    else -> 0.0
                }
                if (max(head.height, ln.height) / min(head.height, ln.height) > R.mergeHeightRatio) continue
                val shortHead = head.letters <= 3
                val shortLn = ln.letters <= 3
                val limit = if (shortHead && shortLn && overlap >= head.height * 0.7) head.height * 2.5
                            else head.height * R.bubbleGap
                if (gap > limit) continue
                if (gap < -head.height * 0.9) continue
                val mergedTop = min(block.minOf { it.top }, ln.top)
                val mergedBottom = max(block.maxOf { it.bottom }, ln.bottom)
                if (mergedBottom - mergedTop > R.maxBlockHeight) continue
                if (gap < bestGap) { bestGap = gap; target = block }
            }
            if (target != null) target.add(ln) else blocks.add(mutableListOf(ln))
        }

        // ── B. Слишком высокий блок — абзац или колонка: режем по наибольшему пробелу.
        val flat = ArrayList<List<Line>>()
        fun splitTall(block: List<Line>) {
            if (block.size < 4) { flat.add(block); return }
            val span = block.maxOf { it.bottom } - block.minOf { it.top }
            if (span <= R.maxBlockHeight) { flat.add(block); return }
            val sorted = block.sortedBy { it.top }
            var cut = -1
            var best = 0.0
            for (i in 1 until sorted.size) {
                val gap = sorted[i].top - sorted[i - 1].bottom
                if (gap > best) { best = gap; cut = i }
            }
            if (cut < 0) { flat.add(block); return }
            splitTall(sorted.subList(0, cut))
            splitTall(sorted.subList(cut, sorted.size))
        }
        blocks.forEach { splitTall(it) }

        // ── C. Блок → строка: ряды сверху вниз, внутри ряда — справа налево.
        val linesOfBlocks = ArrayList<Row>()
        for (block in flat) {
            val rows = ArrayList<MutableList<Line>>()
            for (part in block.sortedBy { it.top }) {
                val row = rows.firstOrNull { r ->
                    val rTop = r.minOf { it.top }
                    val rBottom = r.maxOf { it.bottom }
                    min(rBottom, part.bottom) - max(rTop, part.top) > min(part.height, rBottom - rTop) * 0.5
                }
                if (row != null) row.add(part) else rows.add(mutableListOf(part))
            }
            val ordered = ArrayList<Line>()
            for (row in rows.sortedBy { r -> r.minOf { it.top } }) {
                ordered.addAll(row.sortedWith { a, b ->
                    val c = if (R.rtl) b.left.compareTo(a.left) else a.left.compareTo(b.left)
                    if (c != 0) c else a.top.compareTo(b.top)
                })
            }
            var text = ""
            ordered.forEachIndexed { index, part ->
                val t = part.text.trim()
                if (t.isEmpty()) return@forEachIndexed
                text = if (index == 0 || text.isEmpty()) t else joinText(text, t)
            }
            val clean = cleanSpeech(text)
            if (clean.isBlank()) continue
            val rowsCount = maxOf(1, block.size)
            val blockTop = block.minOf { it.top }
            val blockBottom = block.maxOf { it.bottom }
            linesOfBlocks.add(Row(
                text = clean,
                left = block.minOf { it.left },
                top = blockTop,
                right = block.maxOf { it.right },
                bottom = blockBottom,
                lh = (blockBottom - blockTop) / rowsCount,
                rows = rowsCount,
            ))
        }
        if (linesOfBlocks.isEmpty()) return emptyList()

        // ── D. Строки одного облачка — в ОДНУ реплику (порт mergeBubbles).
        val bubbles = ArrayList<Row>()
        for (line in linesOfBlocks.sortedWith(compareBy({ it.top }, { it.left }))) {
            var bestIndex = -1
            var bestGap = Double.MAX_VALUE
            for (i in bubbles.indices) {
                if (!sameBubble(bubbles[i], line, R)) continue
                val gap = line.top - bubbles[i].bottom
                if (gap < bestGap) { bestGap = gap; bestIndex = i }
            }
            if (bestIndex >= 0) {
                val b = bubbles[bestIndex]
                val mergedTop = min(b.top, line.top)
                val mergedBottom = max(b.bottom, line.bottom)
                val mergedRows = b.rows + maxOf(1, line.rows)
                bubbles[bestIndex] = Row(
                    text = joinText(b.text, line.text),
                    left = min(b.left, line.left), top = mergedTop,
                    right = max(b.right, line.right), bottom = mergedBottom,
                    lh = (mergedBottom - mergedTop) / mergedRows,
                    rows = mergedRows,
                )
            } else {
                // «Типичная высота» — span/rows, как и при склейке: иначе блок
                // из двух строк не принимал третью (отношение высот > 1,8) и
                // облачко рвалось на два текста.
                val r = maxOf(1, line.rows)
                bubbles.add(Row(line.text, line.left, line.top, line.right, line.bottom,
                    line.h / r, r))
            }
        }

        // ── E. Обрывки в 1–3 знака приклеиваем к ближайшей реплике (absorbOrphans).
        var orphans = bubbles
        for (pass in 0 until 4) {
            var merged = false
            for (orphan in orphans.toList()) {
                if (orphan.text.count { it.isLetter() || it.isDigit() } > 3) continue
                val cx = (orphan.left + orphan.right) / 2
                val cy = (orphan.top + orphan.bottom) / 2
                var targetIndex = -1
                var bestDistance = Double.MAX_VALUE
                for (i in orphans.indices) {
                    val b = orphans[i]
                    if (b === orphan) continue
                    val padX = b.w * 0.12
                    val padY = b.h * 0.35
                    if (cx < b.left - padX || cx > b.right + padX) continue
                    if (cy < b.top - padY || cy > b.bottom + padY) continue
                    val d = kotlin.math.abs(cy - (b.top + b.bottom) / 2)
                    if (d < bestDistance) { bestDistance = d; targetIndex = i }
                }
                if (targetIndex < 0) continue
                val b = orphans[targetIndex]
                if (orphan.h > 0 && b.h > 0 && max(orphan.h, b.h) / min(orphan.h, b.h) > 2.5) continue
                val above = cy < (b.top + b.bottom) / 2
                val mergedRow = Row(
                    text = if (above) joinText(orphan.text, b.text) else joinText(b.text, orphan.text),
                    left = min(b.left, orphan.left), top = min(b.top, orphan.top),
                    right = max(b.right, orphan.right), bottom = max(b.bottom, orphan.bottom),
                    lh = (max(b.bottom, orphan.bottom) - min(b.top, orphan.top)) / (b.rows + orphan.rows),
                    rows = b.rows + orphan.rows,
                )
                orphans = ArrayList(orphans)
                orphans[targetIndex] = mergedRow
                orphans.remove(orphan)
                merged = true
                break
            }
            if (!merged) break
        }

        // ── F. Порядок реплик: «ряды» по вертикали, внутри ряда — справа налево
        //       (порт orderBubbles). Это и есть порядок чтения манги.
        val heights = orphans.map { it.h }.sorted()
        val median = if (heights.isEmpty()) 0.05 else heights[heights.size / 2]
        val tolerance = max(0.02, median * 0.8)
        val bandsOut = ArrayList<MutableList<Row>>()
        var bandTop = 0.0
        for (b in orphans.sortedBy { it.top }) {
            if (bandsOut.isNotEmpty() && b.top - bandTop <= tolerance) {
                bandsOut.last().add(b)
            } else {
                bandsOut.add(mutableListOf(b))
                bandTop = b.top
            }
        }
        val ordered = ArrayList<Row>()
        for (band in bandsOut) {
            ordered.addAll(band.sortedWith { a, b ->
                if (R.rtl) b.left.compareTo(a.left) else a.left.compareTo(b.left)
            })
        }

        // Реплика-мусор («е ой», «оооо») в озвучку не идёт; настоящие короткие
        // реплики («ДА.», «НЕТ!») проходят — в них слова, а не обрывки.
        val realOneLetter = setOf('а', 'и', 'в', 'с', 'к', 'у', 'о', 'я')
        fun junkReplica(text: String): Boolean {
            val letters = text.count { it.isLetter() }
            if (letters == 0) return true
            if (Regex("(\\p{L})\\1\\1", RegexOption.IGNORE_CASE).containsMatchIn(text)) return true
            if (letters > 12) return false
            return text.split(Regex("[^\\p{L}]+")).any { w ->
                w.length == 1 && w[0].lowercaseChar() !in realOneLetter
            }
        }
        return ordered.filter { r -> !junkReplica(r.text) }.map { r ->
            JSONObject()
                // Края чистим в самом конце: обрывок звукового эффекта
                // приклеивается уже при склейке, после первых чистых строк.
                .put("text", trimJunkEdges(r.text))
                .put("left", r.left).put("top", r.top)
                .put("right", r.right).put("bottom", r.bottom)
        }
    }

    /**
     * Полосы страницы: то, что видно на экране (доля страницы), плюс признак
     * «страница целиком». Границы полос — правило чтения, а не интерфейс.
     */
    fun bands(
        pageHeightPx: Double,
        viewportPx: Double,
        R: Rules,
        wholeThreshold: Double = 0.72,
        bandsMax: Int = 8,
        overlap: Double = 0.0,
    ): JSONArray {
        val out = JSONArray()
        val whole = {
            val a = JSONArray()
            a.put(JSONObject().put("index", 0).put("top", 0.0).put("bottom", 1.0).put("whole", true))
            a
        }
        if (pageHeightPx <= 0 || viewportPx <= 0) return whole()
        val fraction = viewportPx / pageHeightPx
        if (fraction <= 0 || fraction >= wholeThreshold) return whole()
        var top = 0.0
        var idx = 0
        while (idx < bandsMax) {
            val bottom = min(1.0, top + fraction)
            out.put(JSONObject().put("index", idx).put("top", top).put("bottom", bottom).put("whole", false))
            if (bottom >= 0.999) return out
            top = max(0.0001, bottom - fraction * overlap)
            idx++
        }
        if (out.length() > 0) out.getJSONObject(out.length() - 1).put("bottom", 1.0)
        return out
    }
}
