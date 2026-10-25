// Что покажет интерфейс, когда WASM запрещён политикой страницы (предпросмотр).
require('/tmp/dom_shim.js');
const fs = require('fs');
const html = fs.readFileSync('/home/user/koma-web.html', 'utf8');
const js = html.slice(html.indexOf('<script>', html.indexOf('ort.min.js')) + 8);
const body = js.slice(0, js.lastIndexOf('</script>'));
const trimmed = body.slice(0, body.indexOf('(async function boot()'));
global.ort = {
  env: { wasm: {} }, logLevel: 'error',
  Tensor: class { constructor(t, d, dims) { this.type = t; this.data = d; this.dims = dims; } },
  InferenceSession: { create: async () => { throw new Error(
    "no available backend found. ERR: [wasm] RuntimeError: Aborted(CompileError: " +
    "WebAssembly.instantiate(): Refused to compile because 'unsafe-eval' is not an allowed source of script"); } },
};
new Function(trimmed + '; global.__api={OCR,renderModels,DB};')();
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
