// Второй проход распознавания прямо в сборке:
//  1) детектор вернул 0 боксов → повтор по контрасту/бинаризации;
//  2) крупный текст (титул) при повторном обнаружении делится на строки,
//     и вариант с настоящими словами вытесняет плохой первый проход.
const fs = require('fs');
require('./shim.js');
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.indexedDB = undefined;
global.document.getElementById = (id) => ({
  id, textContent: '', innerHTML: '', style: {}, dataset: {}, disabled: false,
  classList: { contains: () => false, add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {},
});
global.document.querySelector = () => null;
global.ort = { env: { wasm: {} }, Tensor: class { constructor(t, d, dims) { this.data = d; this.dims = dims; } } };
const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync('/home/user/koma-web/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {recognizePage, OCR, Words, sanitizeRules, DEFAULT_RULES, makeCanvas, qualityOf};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

// Словарь: «будучи» настоящее, «будучиг» — нет
const W = api.Words;
W.rank = new Map([['как', 1], ['прожить', 2], ['жизнь', 3], ['будучи', 4], ['старшей', 5], ['сестрой', 6], ['тирана', 7]]);
W.size = W.rank.size; W.ready = true;

const R = api.sanitizeRules(api.DEFAULT_RULES);
R.minConfidence = 0;
const page = api.makeCanvas(700, 900);
// Белый лист с тёмными строками: иначе кадр целиком чёрный и строк не найти.
{
  const w = page.width, h = page.height;
  const img = page.getContext('2d').getImageData(0, 0, w, h);
  img.data.fill(255);
  for (let y = 60; y < 100; y++) for (let x = 40; x < 300; x++) img.data[(y * w + x) * 4] = 10;
  page.getContext('2d').putImageData(img, 0, 0);
}

// Детектор: на первом кадре ничего, на «контрастном» — один бокс.
let detCalls = 0;
api.OCR.ready = true;
api.OCR.det = {
  inputNames: ['x'], outputNames: ['y'],
  run: async (feed) => {
    detCalls++;
    const h = feed.x.dims[2], w = feed.x.dims[3];
    const data = new Float32Array(h * w);
    // второй вызов (после повтора) «видит» текст в верхней трети кадра
    if (detCalls >= 2) {
      for (let y = 30; y < 90; y++) for (let x = 40; x < 260; x++) data[y * w + x] = 1;
    }
    return { y: { dims: [1, 1, h, w], data } };
  },
};
// Распознавание: чем крупнее кроп, тем лучше текст (так и задумано проходом 2)
api.OCR.dict = ['', ' ', 'б', 'у', 'д', 'и', 'ч', 'г', 'к', 'а', 'с', 'р', 'о', 'е', 'т'];
api.OCR.rec = {
  inputNames: ['x'], outputNames: ['y'],
  run: async (feed) => {
    const h = feed.x.dims[2], w = feed.x.dims[3];
    const T = 8, C = api.OCR.dict.length;
    const data = new Float32Array(T * C);
    const big = h * w > 20000;      // крупный кроп — второй проход
    const word = big ? 'будучи' : 'будучиг';
    for (let t = 0; t < T; t++) {
      const ch = word[Math.min(word.length - 1, t)] || ' ';
      const idx = Math.max(1, api.OCR.dict.indexOf(ch));
      data[t * C + idx] = 1;
    }
    return { y: { dims: [1, T, C], data } };
  },
};

(async () => {
  const res = await api.recognizePage(page, R, null, null);
  ok(detCalls >= 2, 'детектор повторился на другой подготовке кадра (вызовов: ' + detCalls + ')');
  ok(res.detPass && res.detPass !== 'normal', 'в отчёте видно, что сработал повтор: ' + res.detPass);
  ok(res.boxes >= 1, 'после повтора бокс найден: ' + res.boxes);
  ok(res.regions.length >= 1, 'из найденного бокса получен текст: ' + res.regions.length);

  // Крупный текст: сравниваем качество вариантов
  const good = api.qualityOf(['Как прожить жизнь, будучи']);
  const bad = api.qualityOf(['будучиг']);
  ok(good > bad, 'вариант с настоящими словами оценивается выше (' + Math.round(good) + ' > ' + Math.round(bad) + ')');

  // Когда детектор находит всё сразу — повторов нет
  detCalls = 0;
  api.OCR.det.run = async (feed) => {
    detCalls++;
    const h = feed.x.dims[2], w = feed.x.dims[3];
    const data = new Float32Array(h * w);
    for (let y = 30; y < 90; y++) for (let x = 40; x < 260; x++) data[y * w + x] = 1;
    return { y: { dims: [1, 1, h, w], data } };
  };
  const res2 = await api.recognizePage(page, R, null, null);
  // Первый вызов — детектор по странице; возможный второй — проход по крупному
  // тексту (он законный). Лишних прогонов «на всякий случай» быть не должно.
  ok(detCalls <= 2, 'по странице детектор отработал без лишних повторов (вызовов: ' + detCalls + ')');
  ok(res2.detPass === 'normal', 'отчёт: обычный проход');
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.error('FAIL', e.stack); process.exit(1); });
