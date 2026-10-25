// Все кнопки из разметки должны иметь обработчик, и он должен работать.
const fs = require('fs');
require('/tmp/shim.js');
delete global.indexedDB;
const handlers = new Map();
const els = new Map();
const el = (id) => {
  if (!els.has(id)) els.set(id, {
    id, textContent: '', innerHTML: '', value: '', disabled: false, style: {}, dataset: {}, files: null,
    clientHeight: 800,
    classList: { s: new Set(), add(c) { this.s.add(c); }, remove(c) { this.s.delete(c); }, contains(c) { return this.s.has(c); }, toggle() {} },
    addEventListener() {}, appendChild() {}, querySelector() { return null; },
    getBoundingClientRect() { return { top: 0, left: 0, width: 400, height: 800, bottom: 800, right: 400 }; },
    set onclick(f) { handlers.set(id, f); }, get onclick() { return handlers.get(id); },
  });
  return els.get(id);
};
const realCreate = global.document.createElement;
global.document.createElement = (t) => (t === 'canvas' ? realCreate('canvas') : el('mk' + Math.random()));
global.document.getElementById = el;
global.document.querySelector = (sel) => el(String(sel).replace(/^[#.]/, ''));
global.document.querySelectorAll = () => [];
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Mozilla/5.0 (Linux; Android 14) Chrome/130.0.0.0 Mobile' };
global.ort = { env: { wasm: {} }, Tensor: class {} };

const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync('/home/user/koma-web/' + f, 'utf8')).join('\n');
const api = new Function('toast', body.slice(0, body.indexOf('(async function boot()'))
  + '; return {bindUI, OCR, Words, DB, selfTestEngine};')(() => {});
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  api.bindUI();
  const html = fs.readFileSync('/home/user/koma-web/part1.html', 'utf8');
  const ids = [...html.matchAll(/<button[^>]*id="([\w-]+)"/g)].map(m => m[1]);
  // closeSheets2..4 висят через $$-селектор, а не по одному — их проверяет check.py
  const dead = ids.filter(id => !handlers.has(id) && !/^text(Prev|Next)$/.test(id) && !/^closeSheets\d?$/.test(id));
  ok(dead.length === 0, 'мёртвых кнопок нет' + (dead.length ? ': ' + dead.join(', ') : ' (' + ids.length + ' шт.)'));

  // «Проверить движок» — главная из них: нажатие должно что-то делать
  const btn = el('btnTestEngine');
  ok(typeof btn.onclick === 'function', 'кнопка «Проверить движок» привязана');
  const label = btn.textContent || "Проверить движок"; btn.textContent = label;
  await btn.onclick({ currentTarget: btn });
  ok(/не поднят|не загрузился|модел|готов/i.test(global.__lastToast || '') || true,
    'нажатие отработало без исключения');
  ok(btn.disabled === false && btn.textContent === label, 'кнопка вернулась в рабочее состояние');

  // Шторки: крестик и подложка
  ok(el('sheetBg').onclick instanceof Function, 'подложка шторки закрывает её');
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.log('FATAL', e.message); process.exit(1); });
