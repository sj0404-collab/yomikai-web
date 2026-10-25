// Кэш распознанных страниц и правило «сколько раз повторять распознавание».
const fs = require('fs');
require('/tmp/shim.js');
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.document.addEventListener = () => {};
global.document.getElementById = () => null;
global.document.querySelector = () => null;
global.document.querySelectorAll = () => [];

global.ort = { env: { wasm: {} }, Tensor: class { constructor(t, d, dims) { this.data = d; this.dims = dims; } } };
const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync('/home/user/koma-web/' + f, 'utf8')).join('\n');
const trimmed = body.slice(0, body.indexOf('(async function boot()'));
const api = new Function(trimmed + '; return {Reader, State, decodeBetter, DEFAULT_RULES, makeCanvas, OCR};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  // 1. Страница уже распознана → повторного сканирования нет
  const R = api.Reader;
  R.book = { id: 'b1' };
  R.page = 0;
  R.pages = [{}, {}];
  R.regions.set(0, { lines: [{ text: 'раз', left: .1, top: .1, right: .5, bottom: .2 }], cached: true });
  let scanned = false;
  api.OCR.ready = true;
  api.OCR.det = { inputNames: ['x'], outputNames: ['y'], run: async () => { scanned = true; return {}; } };
  const res = await R.scanCurrent(false);
  ok(res && res.cached === true, 'scanCurrent(false) вернул данные из кэша');
  ok(scanned === false, 'модель повторно не запускалась');
  ok(api.State.scanning === false, 'флаг сканирования не залип');

  // 2. Правило decodeRetryBelow управляет числом прогонов распознавания
  let runs = 0;
  api.OCR.dict = ['', 'а'];
  api.OCR.rec = {
    inputNames: ['x'], outputNames: ['y'],
    run: async () => {
      runs++;
      const T = 2, C = 3, d = new Float32Array(T * C);
      d[0 * C + 0] = .9; d[1 * C + 1] = .9;         // «а»
      return { y: { dims: [1, T, C], data: d } };
    },
  };
  const crop = api.makeCanvas(40, 20);
  for (let i = 0; i < crop.data.length; i += 4) { crop.data[i] = crop.data[i + 1] = crop.data[i + 2] = 240; crop.data[i + 3] = 255; }

  runs = 0;
  await api.decodeBetter(crop, { ...api.DEFAULT_RULES, decodeRetryBelow: 0 });
  ok(runs === 1, 'при decodeRetryBelow=0 — один прогон (было бы 3)');

  runs = 0;
  await api.decodeBetter(crop, { ...api.DEFAULT_RULES, decodeRetryBelow: 1 });
  ok(runs === 1, 'текст из букв есть → повторов нет');

  runs = 0;
  await api.decodeBetter(crop, { ...api.DEFAULT_RULES, decodeRetryBelow: 5 });
  ok(runs === 3, 'порог 5 → первый прогон + два бинаризованных');
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.log('FATAL', e.message); process.exit(1); });
