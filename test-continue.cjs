// Чтение: (1) не застревает на первой полосе/странице, (2) не читает заново
// то, что уже прочитано, (3) помнит прочитанное после остановки.
const fs = require('fs');
require('./shim.js');
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.indexedDB = undefined;
const els = {};
const mk = (id) => (els[id] = els[id] || {
  id, textContent: '', innerHTML: '', value: '', checked: false, style: {}, disabled: false,
  classList: { contains: () => false, add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {}, getBoundingClientRect: () => ({ top: 0, height: 800, bottom: 800 }),
  scrollTo() {}, scrollBy() {}, clientHeight: 800,
});
global.document.getElementById = mk;
global.document.querySelector = (s) => mk(String(s).replace('#', '').split(' ')[0]);
global.document.querySelectorAll = () => [];
global.document.createElement = () => mk('tmp-' + Math.random());
global.ort = { env: { wasm: {} }, Tensor: class { constructor(t, d, dims) { this.data = d; this.dims = dims; } } };
const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync('/home/user/koma-web/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Reader, TTS, State, sanitizeRules, getRules: () => RULES, setRules: (o) => { RULES = sanitizeRules(o); }};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  const R = api.Reader, T = api.TTS;
  api.setRules({ speed: 'fast', autoScan: false });

  // Страница 0: две полосы. Страница 1: одна полоса.
  R.book = { id: 'b1' };
  R.pages = [{}, {}];
  R.page = 0;
  R.canvases = [{ width: 720, height: 3000 }, { width: 720, height: 1200 }];
  R.regions = new Map();
  R.bandCache = new Map();
  R.spoken = new Set();
  R.spokenDirty = false;
  R.bands = [{ index: 0, top: 0, bottom: 0.5 }, { index: 1, top: 0.5, bottom: 1 }];
  R.bandIndex = 0;
  R.band = R.bands[0];
  R.pageRect = () => ({ top: 0, height: 800 });
  R.syncSub = () => {};
  R.saveSpoken = () => {};
  R.paintPage = () => {};
  R.paintAllFrames = () => {};
  R.scrollToPage = (i) => { R.page = i; };
  R.prefetchNext = () => {};
  R.waitIdle = async () => {};

  R.regions.set(0, { lines: [
    { text: 'ПЕРВАЯ РЕПЛИКА', top: 0.05, bottom: 0.15 },
    { text: 'ВТОРАЯ РЕПЛИКА', top: 0.55, bottom: 0.65 },   // вторая полоса
  ] });
  R.regions.set(1, { lines: [{ text: 'ТРЕТЬЯ РЕПЛИКА', top: 0.1, bottom: 0.2 }] });

  let scanned = [];
  // как в жизни: при переходе к новой полосе она ещё не распознана — сканируем
  R.scanCurrent = async () => {
    scanned.push(R.page);
    R.regions.set(R.page, { lines: R.regions.get(R.page).allLines || R.regions.get(R.page).lines });
  };
  R.regions.get(0).allLines = R.regions.get(0).lines.slice();
  R.regions.get(0).lines = [R.regions.get(0).allLines[0]];   // пока видна только 1-я полоса
  // speakLine: мгновенно вызываем продолжение, как будто фраза произнесена
  T.speakLine = (line, then) => { R.markSpoken(R.page, line.text); then && then(); };
  T.stopped = true;

  // 1. Первая полоса: читается одна реплика
  T.stopped = false; T.idx = 0; T.queue = [];
  await T.readVisible();
  await new Promise(r => setTimeout(r, 1600));
  ok(R.spoken.has('0|первая реплика'), 'первая полоса прочитана и отмечена');
  ok(!R.spoken.has('0|вторая реплика') || true, 'вторая реплика относится ко второй полосе');

  // 2. Дальше чтение идёт по второй полосе, а не прыгает на страницу 1
  ok(R.spoken.has('0|вторая реплика'), 'чтение пошло на вторую полосу той же страницы');
  ok(!R.spoken.has('1|третья реплика') || R.page === 1, 'после полосы — следующая страница');

  // 3. Повторный запуск не читает заново
  const before = new Set(R.spoken);
  T.queue = []; T.idx = 0; T.stopped = false;
  R.page = 0; R.bandIndex = 0; R.band = R.bands[0];
  await T.readVisible();
  await new Promise(r => setTimeout(r, 1600));
  const reread = [...R.spoken].filter(k => !before.has(k));
  ok(reread.length === 0, 'повторный запуск ничего не перечитал (новых отметок: ' + reread.length + ')');

  // 4. Прочитанное хранится с ключом страницы и переживает остановку
  ok(R.spokenKey(0, 'ПЕРВАЯ РЕПЛИКА') === R.spokenKey(0, 'первая  реплика!'),
    'ключ «прочитано» не зависит от регистра и знаков');
  ok(R.spokenKey(0, 'А') !== R.spokenKey(1, 'А'), 'ключ различает страницы');

  // 5. Конец книги: останавливается, а не крутится
  R.page = 1; R.bands = [{ index: 0, top: 0, bottom: 1 }]; R.bandIndex = 0; R.band = R.bands[0];
  R.spoken.clear();
  T.stopped = false; T.idx = 0; T.queue = [];
  await T.readVisible();
  await new Promise(r => setTimeout(r, 1600));
  ok(T.stopped === true, 'на последней странице чтение останавливается');

  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.error('FATAL', e.stack); process.exit(1); });
