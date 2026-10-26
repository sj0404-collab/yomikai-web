// Что покажет интерфейс, когда WASM запрещён политикой страницы (предпросмотр).
require('./dom_shim.js');
const fs = require('fs');
// Собираем приложение из частей: в самом HTML теперь вшит движок на 7 МБ,
// и вырезать оттуда код регулярками — плохая идея.
const body = ['part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync('/home/user/koma-web/' + f, 'utf8')).join('\n');
const trimmed = body.slice(0, body.indexOf('(async function boot()'));
global.ort = {
  env: { wasm: {} }, logLevel: 'error',
  Tensor: class { constructor(t, d, dims) { this.type = t; this.data = d; this.dims = dims; } },
  InferenceSession: { create: async () => { throw new Error(
    "no available backend found. ERR: [wasm] RuntimeError: Aborted(CompileError: " +
    "WebAssembly.instantiate(): Refused to compile because 'unsafe-eval' is not an allowed source of script"); } },
};
// Вшитые бинари здесь не нужны: проверяем поведение при запрете WASM,
// а сам разбор base64 покрыт test-ort-wasm.cjs.
new Function('async function installOrtWasm(){return true;}' + trimmed
  + '; global.__api={OCR,renderModels,DB};')();
const { OCR, renderModels, DB } = global.__api;
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };
(async () => {
  await DB.put('kv', { k: 'model:det', v: new Uint8Array([1]) });
  await DB.put('kv', { k: 'model:rec', v: new Uint8Array([1]) });
  await DB.put('kv', { k: 'model:dict', v: 'а\nб' });
  const r = await OCR.loadModels();
  ok(r === false, 'loadModels вернул false');
  ok(OCR.engine === 'blocked', 'причина распознана как запрет WASM, а не «моделей нет»: ' + OCR.engine);
  const st = OCR.statusText();
  ok(/WASM заблокирован/.test(st), 'статус: ' + st);
  ok(/Chrome/.test(OCR.reason), 'в причине есть, что делать: ' + OCR.reason.slice(0, 60) + '…');
  await renderModels();
  const line = global.document.getElementById('ortState').textContent;
  ok(!/моделей нет/.test(line), 'строка движка больше не врёт: ' + line.slice(0, 70) + '…');
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})();
