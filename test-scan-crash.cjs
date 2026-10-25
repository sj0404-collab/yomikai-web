// Регресс со скриншота 22:55: «Ошибка: this.bands.get is not a function».
// Reader.bands — это массив полос из bandsOf(), а кэш распознанных полос
// лежит в отдельном поле bandCache. Плюс: буфер прошлой версии чистится заново.
const fs = require('fs');
require('/tmp/shim.js');
const els = new Map();
const el = (id) => {
  if (!els.has(id)) els.set(id, {
    id, textContent: '', innerHTML: '', style: {}, dataset: {}, disabled: false, files: null,
    classList: { s: new Set(), add(c) { this.s.add(c); }, remove(c) { this.s.delete(c); }, contains(c) { return this.s.has(c); }, toggle() {} },
    addEventListener() {}, querySelector() { return null; }, appendChild() {},
    getBoundingClientRect: () => ({ top: 0, bottom: 800, height: 800, left: 0, right: 700 }),
  });
  return els.get(id);
};
delete global.indexedDB;
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.document.addEventListener = () => {};
global.document.getElementById = el;
global.document.querySelector = (sel) => (sel === '#strip' ? el('strip') : el(String(sel).replace(/^[#.]/, '').slice(0, 30)));
global.document.querySelectorAll = () => [];
global.ort = { env: { wasm: {} }, Tensor: class { constructor(t, d, dims) { this.data = d; this.dims = dims; } } };

const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync('/home/user/koma-web/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Reader, State, OCR, Words, cleanLines, RULES};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  const R = api.Reader;
  R.pages = [{}, {}]; R.page = 0; R.book = { id: 'b' };
  R.canvases = [{ width: 700, height: 900 }, { width: 700, height: 900 }];
  R.mode = 'vertical';
  R.afterPageReady = () => {};              // bands выставим руками, как он это делает
  R.bands = [{ index: 0, top: 0, bottom: 1, whole: false }];
  R.band = R.bands[0];
  api.OCR.ready = false;                    // дальше проверки движка не идём

  let err = null;
  try { await R.scanPage(0, {}); } catch (e) { err = e; }
  ok(!err, 'scanPage при Reader.bands-массиве не падает' + (err ? ': ' + err.message : ''));
  ok(R.bandCache instanceof Map, 'кэш полос — отдельная Map');

  let err2 = null;
  try { await R.scanPage(0, { full: true, force: true }); } catch (e) { err2 = e; }
  ok(!err2, 'кнопка «Распознать всю страницу целиком» не падает' + (err2 ? ': ' + err2.message : ''));
  ok(api.State.scanning === false, 'флаг сканирования не залип после ошибки');

  // Буфер прошлой версии: мусор уходит, настоящие реплики остаются
  const W = api.Words;
  W.rank = new Map([['уже', 1], ['пора', 2], ['начинать', 3], ['встречу', 4], ['высочество', 5], ['должно', 6], ['быть', 7], ['прибыла', 8]]);
  W.size = W.rank.size; W.ready = true;
  const lines = await api.cleanLines([
    { text: 'Тг. чв', top: 0.1 },
    { text: 'УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ,', top: 0.2 },
  ]);
  ok(lines.length === 1, 'из буфера убрана мусорная строка (осталось ' + lines.length + ')');
  ok(lines[0] && /УЖЕ ПОРА/.test(lines[0].text), 'настоящая реплика из буфера сохранена');
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.error('FAIL', e); process.exit(1); });
