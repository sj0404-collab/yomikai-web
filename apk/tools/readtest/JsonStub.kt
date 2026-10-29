// Мини-заглушка org.json для проверки ReadEngine без Android:
// хранит значения и умеет печатать JSON — больше движку чтения ничего не нужно.
package org.json

class JSONObject {
    private val map = LinkedHashMap<String, Any?>()
    constructor()
    constructor(json: String) { throw UnsupportedOperationException("заглушка") }
    fun put(k: String, v: Any?): JSONObject { map[k] = v; return this }
    fun optString(k: String, def: String = ""): String = (map[k] as? String) ?: def
    fun optDouble(k: String, def: Double = 0.0): Double = (map[k] as? Number)?.toDouble() ?: def
    fun optInt(k: String, def: Int = 0): Int = (map[k] as? Number)?.toInt() ?: def
    fun has(k: String) = map.containsKey(k)
    fun keys(): Set<String> = map.keys
    override fun toString(): String =
        map.entries.joinToString(",", "{", "}") { (k, v) -> "\"$k\":${jsonOf(v)}" }
}

class JSONArray {
    private val list = ArrayList<Any?>()
    constructor()
    constructor(c: Collection<*>) { list.addAll(c) }
    fun put(v: Any?): JSONArray { list.add(v); return this }
    fun length(): Int = list.size
    fun getJSONObject(i: Int): JSONObject = list[i] as JSONObject
    fun optJSONObject(i: Int): JSONObject? = list.getOrNull(i) as? JSONObject
    override fun toString(): String = list.joinToString(",", "[", "]") { jsonOf(it) }
}

fun jsonOf(v: Any?): String = when (v) {
    null -> "null"
    is String -> "\"" + v.replace("\\", "\\\\").replace("\"", "\\\"") + "\""
    is JSONObject -> v.toString()
    is JSONArray -> v.toString()
    is Number, is Boolean -> v.toString()
    else -> "\"$v\""
}
