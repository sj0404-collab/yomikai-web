// Исходники для тестов: режем собранный koma-web.html на те же куски,
// которые раньше лежали отдельными part-файлами. Так тесты и check.py
// работают с текущим деревом, где есть только монолит.
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const html = fs.readFileSync(path.join(__dirname, 'koma-web.html'), 'utf8');
const script = html.slice(html.indexOf('<script>') + 8, html.lastIndexOf('</script>'));

const wasmStart = script.indexOf('const ORT_WASM_GZ');
const dictStart = script.indexOf('const DICT_GZ_B64');
const appStart = script.indexOf("'use strict';", dictStart);
if (wasmStart < 0 || dictStart < 0 || appStart < 0) {
  throw new Error('koma-web.html: не найдены секции ORT_WASM_GZ / DICT_GZ_B64 / приложения');
}

// part0-wasm.js: ORT_WASM_GZ + b64ToBytes + gunzipB64 + installOrtWasm
const wasmSrc = script.slice(wasmStart, dictStart);

// part0-dict.js: b64ToBytes + DICT_GZ_B64 + embeddedDictText
const b64Start = wasmSrc.indexOf('function b64ToBytes');
const b64End = wasmSrc.indexOf('/** gzip', b64Start);
const b64ToBytes = wasmSrc.slice(b64Start, b64End);
const dictSrc = b64ToBytes + '\n' + script.slice(dictStart, appStart);

// part2..5: приложение от 'use strict' до </script> (включая boot)
const app = script.slice(appStart);

// part2..4: приложение без UI (секция 11) и без boot; dummy boot нужен,
// чтобы существующий в тестах slice(0, indexOf('(async function boot()')) работал.
const sec11 = script.indexOf('11. Состояние', appStart);
const coreEnd = sec11 < 0 ? app.length : script.lastIndexOf('/*', sec11);
const appCore = script.slice(appStart, coreEnd) + '\n(async function boot(){})\n';

let dictTextCache = null;
function dictText() {
  if (dictTextCache === null) {
    const m = html.match(/const DICT_GZ_B64\s*=\s*'([^']+)'/);
    if (!m) throw new Error('koma-web.html: не найден DICT_GZ_B64');
    dictTextCache = zlib.gunzipSync(Buffer.from(m[1], 'base64')).toString('utf8');
  }
  return dictTextCache;
}

module.exports = { html, script, wasmSrc, dictSrc, app, appCore, dictText };
