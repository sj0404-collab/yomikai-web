// Регресс: session.run() асинхронный. Раньше результат читался сразу, и в
// браузере это давало «Cannot read properties of undefined (reading 'data')»,
// потому что Node-заглушки возвращали объект синхронно.
const fs = require('fs');
// Мини-canvas из shim.js: здесь DOM не нужен, а dom_shim отдаёт пустой 2d-контекст.
// window.addEventListener нужен для глобальных обработчиков ошибок из part5.
require('./shim.js');
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.document = global.document || {};
global.document.addEventListener = () => {};
const W = 320, H = 192;

global.ort = {
  env: { wasm: {} },
  Tensor: class { constructor(type, data, dims) { this.type = type; this.data = data; this.dims = dims; } },
};

const body = require('./koma-src.cjs').app;
const trimmed = body.slice(0, body.indexOf('(async function boot()'));
const api = new Function(trimmed + '; return {detectBoxes, decodeCrop, decodeBetter, makeCanvas, OCR, DEFAULT_RULES};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

// карта вероятностей с белым прямоугольником 40×20 — как настоящий детектор
function probMap() {
  const m = new Float32Array(H * W);
  for (let y = 40; y < 60; y++) for (let x = 30; x < 70; x++) m[y * W + x] = 0.95;
  return m;
}
const detTensor = () => ({ dims: [1, 1, H, W], data: probMap() });
const recTensor = () => {                        // «А» в словаре под индексом 1
  const T = 6, C = 519, d = new Float32Array(T * C);
  for (let t = 0; t < T; t++) d[t * C + (t === 2 ? 1 : 0)] = 0.9;
  return { dims: [1, T, C], data: d };
};

async function run(useMap) {
  return useMap ? new Map([['out', arguments[1]]]) : { out: arguments[1] };
}

(async () => {
  // 1. Промис-результат в простом объекте
  api.OCR.det = { inputNames: ['x'], outputNames: ['out'], run: async () => ({ out: detTensor() }) };
  api.OCR.rec = { inputNames: ['x'], outputNames: ['out'], run: async () => ({ out: recTensor() }) };
  api.OCR.dict = ['', 'А', 'Б'];
  const c = api.makeCanvas(W, H);
  for (let i = 0; i < c.data.length; i += 4) { c.data[i] = c.data[i + 1] = c.data[i + 2] = 250; c.data[i + 3] = 255; }
  const boxes = await api.detectBoxes(c, 1600);
  ok(boxes.length >= 1, 'детектор вернул ' + boxes.length + ' бокс(ов) при асинхронном run()');
  const [text] = await api.decodeCrop(c);
  ok(text === 'А', 'распознавание вернуло «' + text + '» при асинхронном run()');

  // 2. Результат в виде Map (другая версия ORT)
  api.OCR.det = { inputNames: ['x'], outputNames: ['out'], run: async () => new Map([['out', detTensor()]]) };
  api.OCR.rec = { inputNames: ['x'], outputNames: ['out'], run: async () => new Map([['out', recTensor()]]) };
  ok((await api.detectBoxes(c, 1600)).length >= 1, 'Map-результат детектора тоже читается');
  ok((await api.decodeCrop(c))[0] === 'А', 'Map-результат распознавания тоже читается');

  // 3. Имя выхода не совпало — берём первый по порядку, а не падаем
  api.OCR.det = { inputNames: ['x'], outputNames: ['нет-такого'], run: async () => ({ out: detTensor() }) };
  ok((await api.detectBoxes(c, 1600)).length >= 1, 'несовпавшее имя выхода не роняет детектор');

  // 4. Совсем пустой результат — понятная ошибка, а не «reading data»
  api.OCR.det = { inputNames: ['x'], outputNames: ['out'], run: async () => ({}) };
  try {
    await api.detectBoxes(c, 1600);
    ok(false, 'пустой результат должен давать ошибку');
  } catch (e) {
    ok(/детектор не вернула выходов/.test(e.message), 'понятная ошибка: ' + e.message);
  }
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.log('FATAL', e.message); process.exit(1); });
