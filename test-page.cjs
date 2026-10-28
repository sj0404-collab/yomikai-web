// «Какая страница на экране» — по геометрии, а не по застрявшему индексу.
const fs = require('fs');
require('./shim.js');
delete global.indexedDB;
const els = new Map();
const el = (id) => {
  if (!els.has(id)) els.set(id, {
    id, textContent: '', innerHTML: '', value: '', disabled: false, style: {}, dataset: {}, files: null,
    clientHeight: 800, clientWidth: 400,
    classList: { s: new Set(), add(c) { this.s.add(c); }, remove(c) { this.s.delete(c); }, contains(c) { return this.s.has(c); }, toggle() {} },
    addEventListener(t, f) { this['on' + t] = f; }, querySelector() { return null; }, appendChild() {},
    getBoundingClientRect() { return { top: 0, left: 0, width: 400, height: 800, bottom: 800, right: 400 }; },
  });
  return els.get(id);
};
const realCreate = global.document.createElement;
global.document.createElement = (t) => (t === 'canvas' ? realCreate('canvas') : el('mk'));
global.document.getElementById = el;
global.document.querySelectorAll = () => [];
// рельсы: страницы по 1000 px, лента прокручена в начало
const PAGE_H = 1000;
global.__scrollTop = 0;
global.document.querySelector = (sel) => {
  const m = String(sel).match(/pagewrap\[data-page="(\d+)"\]/);
  if (!m) return el(String(sel).replace(/^[#.]/, ''));
  const i = +m[1];
  return {
    dataset: { page: String(i) }, style: {},
    getBoundingClientRect() {
      const top = i * PAGE_H - global.__scrollTop;
      return { top, bottom: top + PAGE_H, left: 0, right: 400, width: 400, height: PAGE_H };
    },
  };
};
global.window.addEventListener = () => {};
global.window.innerHeight = 800;
global.navigator = { userAgent: 'Node' };
global.ort = { env: { wasm: {} }, Tensor: class {} };

const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Reader, readingOrder, DEFAULT_RULES, sanitizeRules};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

const R = api.Reader;
R.mode = 'vertical';
R.pages = Array.from({ length: 6 }, (_, i) => ({ key: 'k' + i }));
R.page = 3;                       // «застрявший» индекс, как на скриншоте
R.syncSub = () => {};
R.saveProgress = () => {};
R.ensureLoaded = () => {};

global.__scrollTop = 0;
ok(R.pageAtViewport() === 0, 'на самом верху определяется страница 1: ' + (R.pageAtViewport() + 1));
R.syncPage();
ok(R.page === 0, 'застрявший индекс 4 исправлен на 1 при сверке');

global.__scrollTop = 1000 + 300;   // середина второй страницы
ok(R.pageAtViewport() === 1, 'прокрутка на вторую страницу определяется верно');

global.__scrollTop = 2900;         // стык третьей и четвёртой
const at = R.pageAtViewport();
ok(at === 3, 'на стыке выбирается та, что занимает больше экрана: стр. ' + (at + 1));

// Порядок как в АПК: двойники чинятся ДО фильтра по языку
const rules = api.sanitizeRules(api.DEFAULT_RULES);
const lines = api.readingOrder([
  { text: 'MHE TAK', left: .1, top: .10, right: .5, bottom: .13, confidence: 1 },
  { text: 'He6лuцa', left: .1, top: .20, right: .5, bottom: .23, confidence: 1 },
], true, true, rules);
ok(lines.length === 2, 'латинские двойники не выброшены фильтром языка: ' + lines.map(l => l.text).join(' | '));
ok(lines[0].text === 'МНЕ ТАК', 'первая: «' + lines[0].text + '»');
console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
