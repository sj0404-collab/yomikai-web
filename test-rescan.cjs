// «Распознать заново» должно пересканировать ИМЕННО страницу из шторки, даже
// если лента уже уехала вперёд, и обновлять буфер. Раньше сканировалась
// текущая страница ленты — реплики не перезаписывались.
const fs = require('fs');
require('/tmp/shim.js');
const realCreate = global.document.createElement;
// IndexedDB в узле нет: пусть хранилище сразу идёт в память, без ожидания.
delete global.indexedDB;   // мини-canvas из шима
const els = new Map();
const el = (id) => {
  if (!els.has(id)) els.set(id, {
    id, textContent: '', innerHTML: '', style: {}, dataset: {}, disabled: false, files: null,
    classList: { s: new Set(), add(c) { this.s.add(c); }, remove(c) { this.s.delete(c); }, contains(c) { return this.s.has(c); }, toggle() {} },
    addEventListener() {}, querySelector() { return null; }, appendChild() {},
  });
  return els.get(id);
};
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.document = global.document || {};
global.document.addEventListener = () => {};
global.document.getElementById = el;
global.document.querySelector = (sel) => el(String(sel).replace(/^[#.]/, ''));
global.document.querySelectorAll = () => [];
global.document.createElement = (tag) => (tag === 'canvas' ? realCreate('canvas') : el('tmp' + Math.random()));
global.ort = { env: { wasm: {} }, Tensor: class { constructor(t, d, dims) { this.data = d; this.dims = dims; } } };

const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync('/home/user/koma-web/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Reader, State, OCR, Buffer, renderTextSheet, DEFAULT_RULES};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  const R = api.Reader;
  R.book = { id: 'book1' };
  R.pages = [{}, {}, {}];
  R.page = 2;                      // лента уехала на третью страницу
  R.dir = 'rtl';
  R.canvases = [api.makeCanvas ? null : null];   // ниже заполним

  // canvas-заглушки с контентом, чтобы recognizePage не упал
  const mk = () => {
    const c = realCreate('canvas');
    c.width = 64; c.height = 64;
    for (let i = 0; i < c.data.length; i += 4) { c.data[i] = 240; c.data[i + 1] = 240; c.data[i + 2] = 240; c.data[i + 3] = 255; }
    // Тёмные штрихи — «буквы», иначе textLines не находит строк и реплик нет.
    for (let y = 12; y < 30; y++) for (let x = 12; x < 48; x++) {
      if ((x % 8) < 5) { const k = (y * 64 + x) * 4; c.data[k] = 20; c.data[k + 1] = 20; c.data[k + 2] = 20; }
    }
    return c;
  };
  R.canvases = [mk(), mk(), mk()];

  let recCalls = 0;
  api.OCR.ready = true;
  api.OCR.dict = ['', 'А'];
  api.OCR.det = {
    inputNames: ['x'], outputNames: ['y'],
    run: async () => {
      // одна белая область = один бокс
      const d = new Float32Array(64 * 64);
      for (let y = 10; y < 30; y++) for (let x = 10; x < 50; x++) d[y * 64 + x] = 0.9;
      return { y: { dims: [1, 1, 64, 64], data: d } };
    },
  };
  api.OCR.rec = {
    inputNames: ['x'], outputNames: ['y'],
    run: async () => {
      recCalls++;
      const T = 5, C = 3, d = new Float32Array(T * C);
      // «АА» — две буквы, чтобы реплика прошла фильтр «не меньше двух букв»
      d[0 * C + 0] = .99; d[1 * C + 1] = .99; d[2 * C + 0] = .99; d[3 * C + 1] = .99;
      return { y: { dims: [1, T, C], data: d } };
    },
  };

  // Сканируем страницу 1 (индекс 0), хотя лента на индексе 2
  const res = await R.scanPage(0, { force: true, keepSheet: true });
  ok(!!res && Array.isArray(res.lines), 'scanPage(0) вернул результат для страницы 1');
  ok(R.regions.has(0) && !R.regions.has(2), 'распознана страница из шторки, а не текущая в ленте');
  const buf = await api.Buffer.get(0);
  ok(res.lines.length > 0, 'реплики найдены: ' + res.lines.length + ' «' + (res.lines[0]?.text || '') + '»');
  ok(!!buf && buf.lines.length === res.lines.length && buf.lines.length > 0,
    'буфер страницы 1 перезаписан: ' + (buf ? buf.lines.length : 0) + ' реплик');
  ok(!(await api.Buffer.get(2)), 'буфер страницы 3 не тронут');
  ok(!!res.at, 'в записи есть время обновления: ' + res.at);

  // Замок: второе нажатие во время сканирования не теряется, а встаёт в очередь
  const first = R.scanPage(0, { force: true });
  const second = await R.scanPage(1, { force: true, keepSheet: true });
  ok(second === null && api.State.pendingScan && api.State.pendingScan.i === 1,
    'во время сканирования второе нажатие встало в очередь на страницу 2');
  await first;
  await new Promise(r => setTimeout(r, 120));
  ok(api.State.pendingScan === null, 'очередь разобрана');
  ok(R.regions.has(1), 'страница из очереди досканирована');
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.log('FATAL', e.message); process.exit(1); });
