// При открытии страницы ничего не запускается само. Распознавание — только по
// кнопке или если человек сам включил автозапуск в настройках.
const fs = require('fs');
require('./shim.js');
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.indexedDB = undefined;
const els = {};
const mk = (id) => (els[id] = els[id] || {
  id, textContent: '', innerHTML: '', value: '', checked: false, style: {}, disabled: false,
  classList: { contains: () => false, add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {},
});
global.document.getElementById = mk;
global.document.querySelector = (s) => mk(String(s).replace('#', ''));
global.document.querySelectorAll = () => [];
global.ort = { env: { wasm: {} }, Tensor: class { constructor(t, d, dims) { this.data = d; this.dims = dims; } } };
const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Reader, State, sanitizeRules, DEFAULT_RULES,'
  + '   getRules: () => RULES, setRules: (o) => { RULES = sanitizeRules(o); }};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  const R = api.Reader;
  api.setRules({ speed: 'fast', autoScan: false });
  let scans = 0;

  // Минимальная страница: один «образ», пустой буфер
  R.pages = [{ id: 'p1', w: 720, h: 2960 }];
  R.page = 0;
  R.canvases = [{ width: 720, height: 2960 }];
  R.ratios = {};
  R.regions = new Map();
  R.bandCache = new Map();
  R.scrollBusy = false;
  R.pageRect = () => ({ top: 0, height: 2960 });
  R.visibleBandPx = () => null;
  R.syncSub = () => {};
  R.scanCurrent = async () => { scans++; };

  // 1. autoScan выключен — при открытии страницы ни одного распознавания
  await R.afterPageReady();
  await new Promise(r => setTimeout(r, 50));
  ok(scans === 0, 'при открытии страницы само распознавание не запустилось (вызовов: ' + scans + ')');
  ok(els['startCard'] && els['startCard'].style.display === 'block',
    'показана карточка «ничего не запущено»');
  ok(/открыта/.test(els['startTitle'].textContent), 'в карточке сказано, какая страница открыта: «'
    + els['startTitle'].textContent + '»');
  ok(/Ничего не запущено/.test(els['startHint'].textContent), 'и что ничего не запущено');

  // 2. Человек включил автозапуск — тогда распознаёт
  api.setRules({ ...api.getRules(), autoScan: true });
  await R.afterPageReady();
  await new Promise(r => setTimeout(r, 50));
  ok(scans === 1, 'с включённым автозапуском страница распознаётся (вызовов: ' + scans + ')');
  ok(els['startCard'].style.display === 'none', 'карточка скрыта, когда автозапуск включён');

  // 3. Уже распознанная страница карточку не показывает
  api.setRules({ ...api.getRules(), autoScan: false });
  R.regions.set(0, { lines: [{ text: 'ТЕКСТ' }], cached: true });
  await R.afterPageReady();
  ok(els['startCard'].style.display === 'none', 'распознанная страница открывается без карточки');

  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.error('FAIL', e.stack); process.exit(1); });
