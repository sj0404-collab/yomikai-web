package net.koma.reader

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import org.json.JSONObject

/**
 * ПАНЕЛЬ ЧТЕНИЯ — нативная, в самом приложении.
 *
 * Зачем: страница рисовала панель в HTML, и во время чтения она жила своей
 * жизнью — уезжала вместе с лентой, попадала под реплику, а её высота
 * пересчитывалась на каждой реплике. Отсюда «дёрнулся, потом ещё дважды»
 * (телефон 28.10). Нативная панель не ездит: она лежит ПОД WebView отдельной
 * полосой, поэтому страница выше неё и неё не перекрывает, а высота полосы
 * постоянная — прокрутке нечего пересчитывать.
 *
 * Что показывает: текущую реплику целиком, «реплика 2 из 7 · полоса 1 из 4»,
 * движок голоса и полосу прогресса по репликам.
 * Что умеет: ▶/⏸, ⏭ (следующая), ⟲ (повторить), ⏹ (стоп) — командами в
 * страницу через `window.KomaUiCmd`. Чтением по-прежнему владеет страница:
 * панель — это интерфейс, а не второй движок, иначе реплики поедут дважды.
 */
class KomaUiBridge(
    private val ctx: Context,
    private val web: () -> WebView?,
) {

    private val bg = 0xFF15181D.toInt()
    private val fg = 0xFFF2F4F7.toInt()
    private val dim = 0xFF9AA3AE.toInt()
    private val accent = 0xFF6FB2FF.toInt()

    private val textView: TextView
    private val metaView: TextView
    private val playBtn: TextView
    private val bar: ProgressBar

    /** Вся панель: одна горизонтальная полоса под страницей. */
    val view: LinearLayout

    init {
        val pad = dp(10)

        val col = LinearLayout(ctx)
        col.orientation = LinearLayout.VERTICAL
        col.setPadding(pad, dp(6), pad, dp(8))
        col.setBackgroundColor(bg)
        col.visibility = View.GONE

        metaView = TextView(ctx).apply {
            setTextColor(dim)
            textSize = 11f
            maxLines = 1
            text = "Читалка"
        }
        textView = TextView(ctx).apply {
            setTextColor(fg)
            textSize = 15f
            maxLines = 3
            setPadding(0, dp(2), 0, dp(4))
        }

        val row = LinearLayout(ctx)
        row.orientation = LinearLayout.HORIZONTAL
        row.gravity = Gravity.CENTER_VERTICAL

        playBtn = mkBtn("▶") { send("toggle") }
        row.addView(playBtn, btnLp())
        row.addView(mkBtn("⏭") { send("next") }, btnLp())
        row.addView(mkBtn("⟲") { send("repeat") }, btnLp())
        row.addView(mkBtn("⏹") { send("stop") }, btnLp())

        bar = ProgressBar(ctx, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 1000
            progress = 0
        }
        val barLp = LinearLayout.LayoutParams(0, dp(6), 1f)
        barLp.leftMargin = dp(8)
        barLp.rightMargin = dp(4)
        row.addView(bar, barLp)

        col.addView(metaView, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        col.addView(textView, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        col.addView(row, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        view = col
    }

    private fun dp(v: Int): Int =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), ctx.resources.displayMetrics).toInt()

    private fun mkBtn(label: String, act: () -> Unit): TextView = TextView(ctx).apply {
        text = label
        setTextColor(fg)
        textSize = 19f
        gravity = Gravity.CENTER
        setPadding(dp(8), dp(4), dp(8), dp(4))
        isClickable = true
        isFocusable = true
        background = GradientDrawable().apply {
            cornerRadius = dp(10).toFloat()
            setColor(0xFF232830.toInt())
        }
        setOnClickListener { act() }
    }

    private fun btnLp(): LinearLayout.LayoutParams {
        val lp = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT)
        lp.rightMargin = dp(6)
        return lp
    }

    /** Команда в страницу: она владеет чтением, панель только нажимает кнопки. */
    private fun send(cmd: String) {
        val w = web() ?: return
        w.post { w.evaluateJavascript("window.KomaUiCmd&&window.KomaUiCmd(\"$cmd\")", null) }
    }

    // ── Мост для страницы ───────────────────────────────────────────────────

    /**
     * Показать панель и обновить её состояние.
     * Формат: {text, index, total, band, bands, playing, paused, voice, status}.
     */
    @JavascriptInterface
    fun show(json: String) {
        val o = try { JSONObject(json) } catch (e: Exception) { JSONObject() }
        val act = ctx as? android.app.Activity
        val apply = Runnable {
            paint(o)
            view.visibility = View.VISIBLE
        }
        if (act != null) act.runOnUiThread(apply) else apply.run()
    }

    /** Убрать панель (человек вышел из чтения). */
    @JavascriptInterface
    fun hide() {
        val act = ctx as? android.app.Activity
        val apply = Runnable { view.visibility = View.GONE }
        if (act != null) act.runOnUiThread(apply) else apply.run()
    }

    /** Видна ли панель — странице, чтобы не дублировать свою. */
    @JavascriptInterface
    fun shown(): Boolean = view.visibility == View.VISIBLE

    private fun paint(o: JSONObject) {
        val text = o.optString("text", "").trim()
        textView.text = if (text.isEmpty()) "Тишина" else text
        val i = o.optInt("index", 0)
        val total = o.optInt("total", 0)
        val band = o.optInt("band", 0)
        val bands = o.optInt("bands", 0)
        val bits = ArrayList<String>()
        if (total > 0) bits.add("реплика $i из $total")
        if (bands > 0) bits.add("полоса $band из $bands")
        val voice = o.optString("voice", "")
        if (voice.isNotEmpty()) bits.add(voice)
        val status = o.optString("status", "")
        if (status.isNotEmpty()) bits.add(status)
        metaView.text = if (bits.isEmpty()) "Читалка" else bits.joinToString(" · ")
        metaView.setTextColor(if (o.optBoolean("error", false)) 0xFFFF8A80.toInt() else dim)

        val playing = o.optBoolean("playing", false) && !o.optBoolean("paused", false)
        playBtn.text = if (playing) "⏸" else "▶"
        playBtn.setTextColor(if (playing) accent else fg)

        bar.progress = if (total > 0) ((i - 1) * 1000 / total).coerceIn(0, 1000) else 0
    }
}
