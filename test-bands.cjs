// Полосы: на длинной странице распознаём только видимое, на короткой — всю.
const fs = require('fs');
require('./shim.js');
delete global.indexedDB;
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
const PAGE_H = 12000, VIEW = 800, SCROLL = 4000;   // страница 12000 px, экран 800
global.document.querySelector = (sel) => {
  if (sel === '#strip') return strip;
  const m = String(sel).match(/pagewrap\[data-page="(\d+)"\]/);
  if (!m) return { style: {}, classList: { contains: () => false, add() {}, remove() {} }, addEventListener() {} };
  const top = -SCROLL;                              // страница начинается выше экрана
  return { style: {}, getBoundingClientRect: () => ({ top, bottom: top + VIEW * (PAGE_H / VIEW), height: PAGE_H, width: 700, left: 0, right: 700 }) };
};
const strip = {
  clientHeight: VIEW,
  getBoundingClientRect: () => ({ top: 0, bottom: VIEW, height: VIEW, left: 0, right: 700 }),
  addEventListener() {}, classList: { contains: () => false, add() {}, remove() {} },
};
global.document.getElementById = (id) => (id === 'strip' ? strip : {
  id, textContent: '', innerHTML: '', style: {}, dataset: {}, disabled: false,
  classList: { contains: () => true, add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {}, getBoundingClientRect: () => ({ top: 0, bottom: VIEW, height: VIEW }),
});
global.ort = { env: { wasm: {} }, Tensor: class {} };

const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Reader, RULES, DEFAULT_RULES, sanitizeRules, recognizePage, makeCanvas, lineInBand};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

const R = api.Reader;
R.mode = 'vertical';
R.pages = [{ key: 'k0' }];
R.dir = 'rtl';
R.syncSub = () => {}; R.saveProgress = () => {}; R.ensureLoaded = () => {};
R.paintPage = () => {}; R.savePageBuffer = async () => {};
const canvas = { width: 700, height: PAGE_H };
R.canvases = [canvas];

const band = R.visibleBandPx(0);
ok(!!band, 'видимая полоса определена');
// экран 800 px из 12000 → ~7 % страницы плюс запас 15 % сверху/снизу
const frac = (band.y1 - band.y0) / PAGE_H;
ok(frac < 0.2, 'полоса занимает ' + (frac * 100).toFixed(0) + '% страницы, а не всю');
ok(band.y0 > 3400 && band.y0 < 4100 && band.y1 > 4700 && band.y1 < 5400,
  'полоса соответствует экрану 4000…4800 плюс запас от экрана: ' + Math.round(band.y0) + '…' + Math.round(band.y1));

// короткая страница — полоса не нужна
R.canvases = [{ width: 700, height: 800 }];
R.paintPage = () => {};
global.document.querySelector = (sel) => {
  if (sel === '#strip') return strip;
  const m = String(sel).match(/pagewrap\[data-page="(\d+)"\]/);
  if (!m) return { style: {}, classList: { contains: () => false } };
  return { style: {}, getBoundingClientRect: () => ({ top: 0, bottom: 800, height: 800, width: 700, left: 0, right: 700 }) };
};
ok(R.visibleBandPx(0) === null, 'страница по экрану — распознаём целиком, без полос');

// Страница в полтора экрана: оригинальный KOMA читает её ЦЕЛИКОМ (18 областей,
// 5 реплик, включая текст за нижним краем) — и мы тоже, полос не режем.
R.canvases = [{ width: 700, height: 1200 }];
ok(R.visibleBandPx(0) === null, 'страница до 2,2 экрана читается целиком, как в оригинале');

// recognizePage с полосой: боксы и координаты пересчитываются на всю страницу
(async () => {
const dict = ['не', 'да']; void dict;
let captured = null;
const pageCanvas = global.document.createElement('canvas');
pageCanvas.width = 700;
pageCanvas.height = PAGE_H;
api.RULES.detRetry = false;
global.ort.Tensor = class { constructor(t, d, dims) { this.data = d; this.dims = dims; } };
const api2 = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {recognizePage, RULES, OCR, detectBoxes};')();
api2.OCR.det = { inputNames: ['x'], outputNames: ['y'], run: async (f) => {
  captured = { h: f.x.dims[2], w: f.x.dims[3] };
  const d = new Float32Array(f.x.dims[2] * f.x.dims[3]).fill(0);
  return { y: { dims: [1, 1, f.x.dims[2], f.x.dims[3]], data: d } };
} };
// Новый инвариант: запасной путь пускают только с ЖИВЫМИ обеими сессиями —
// иначе на телефоне было падение «reading 'inputNames'» на пустой сессии.
// Тест проверяет геометрию полосы, поэтому распознаватель здесь тоже заглушка.
api2.OCR.rec = { inputNames: ['x'], outputNames: ['y'],
  run: async () => ({ y: { dims: [1, 1, 1, 519], data: new Float32Array(519) } }) };
const res = await api2.recognizePage(pageCanvas, api2.RULES, null, { y0: 4000, y1: 4800 });
ok(res.band && res.band.y0 === 4000, 'в результате видно, что это полоса 4000…4800');

// Видимость строк: экран 4200…4600, полоса детектора с запасом 4000…4800
const band = { y0: 4000, y1: 4800, vy0: 4200, vy1: 4600 };
const L = (top, bottom) => ({ top, bottom });
ok(api.lineInBand(L(300, 400), band, 4000) === true, 'строка внутри экрана (4300…4400) — в реплики');
ok(api.lineInBand(L(600, 700), band, 4000) === false, 'строка ниже экрана (4600+) отброшена — та самая «лишняя» реплика');
ok(api.lineInBand(L(300, 500), band, 4000) === true, 'строка на границе снизу взята целиком, а не обрезана');
ok(api.lineInBand(L(0, 90), band, 4000) === false, 'строка выше экрана отброшена');
ok(api.lineInBand(L(600, 700), null, 0) === true, 'без полосы (короткая страница) берём всё');
ok(captured && captured.h <= 1000, 'детектор получил полосу высотой ' + (captured ? captured.h : '?') + ' px, а не 12000');

// Границы полосы прилипают к пустому месту страницы (иначе экран режет
// облачко пополам и реплика читается двумя кусками — скриншот 17:30).
// Пиксельную карту в синтетическом тесте не построить, поэтому проверяем
// главное: без карты полоса НЕ пропадает и НЕ меняется.
{
  R.canvases = [canvas]; R._ink = null;
  let res = null, threw = null;
  try { res = R.blankSnap(0, 4000, 4800); } catch (e) { threw = e; }
  ok(!threw, 'blankSnap не падает без карты страницы');
  ok(res && res.y0 === 4000 && res.y1 === 4800, 'без карты полоса не меняется');
  // (что полоса при этом определяется — проверено выше, до этого блока)
}
console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.error('FAIL', e); process.exit(1); });
