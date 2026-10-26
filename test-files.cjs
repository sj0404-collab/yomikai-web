// Что браузер реально умеет с файлами, и добавление страниц в существующую главу.
const fs = require('fs');
require('./shim.js');
delete global.indexedDB;                    // хранилище в памяти, без ожидания
const els = new Map();
const el = (id) => {
  if (!els.has(id)) els.set(id, {
    id, textContent: '', innerHTML: '', value: '', disabled: false, style: {}, dataset: {}, files: null,
    classList: { s: new Set(), add(c) { this.s.add(c); }, remove(c) { this.s.delete(c); }, contains(c) { return this.s.has(c); }, toggle() {} },
    addEventListener() {}, querySelector() { return null; }, appendChild() {},
  });
  return els.get(id);
};
const realCreate = global.document.createElement;
global.document.createElement = (tag) => (tag === 'canvas' ? realCreate('canvas') : el('mk'));
global.document.getElementById = el;
global.document.querySelector = (sel) => el(String(sel).replace(/^[#.]/, ''));
global.document.querySelectorAll = () => [];
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel) Chrome/130.0.0.0 Mobile Safari/537.36' };
global.ort = { env: { wasm: {} }, Tensor: class {} };
global.toastLog = [];

const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync('/home/user/koma-web/' + f, 'utf8')).join('\n');
const api = new Function('toast',
  body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Library, DB, FILES, bindUI, escapeHtml};')((m) => global.toastLog.push(String(m)));
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  const F = api.FILES;
  ok(F && F.android === true, 'браузер распознан как Android');
  ok(F.fsa === false, 'File System Access недоступен (Chrome 130 < 132)');
  ok(F.dirInput === false, 'webkitdirectory недоступен');
  ok(/недоступен/.test(F.why) && /132/.test(F.why), 'причина названа честно: ' + F.why);

  // Кнопки не спрятаны, а заблокированы с объяснением
  api.bindUI();
  el('btnImport').onclick();
  ok(el('btnPickDir').style.display === 'block' && el('btnPickDir').disabled === true,
    'кнопка «Выбрать папку» видна, но заблокирована');
  ok(el('btnPickFolderModern').disabled === true, 'кнопка «Папка (File System)» тоже заблокирована');
  ok(/Ваш браузер/.test(el('importCaps').textContent), 'в шторке написано, что умеет браузер');

  // Добавление в существующую главу
  const mk = (n) => new File([new Uint8Array([1, 2, 3])], n, { type: 'image/jpeg' });
  const book = await api.Library.addBook('Том 1 Глава 48', [mk('001.jpg'), mk('002.jpg')], 'files');
  api.Library.books = [book];
  const grown = await api.Library.appendTo(book.id, [mk('003.jpg'), mk('004.jpg')]);
  ok(grown.count === 4, 'в главе стало 4 страницы: ' + grown.count);
  const pages = (await api.DB.all('pages')).sort((a, b) => a.index - b.index);
  ok(pages.map(p => p.name).join(',') === '001.jpg,002.jpg,003.jpg,004.jpg',
    'нумерация продолжилась без дыр: ' + pages.map(p => p.name).join(','));
  ok(pages.map(p => p.index).join(',') === '0,1,2,3', 'индексы 0..3: ' + pages.map(p => p.index).join(','));
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.log('FATAL', e.message); process.exit(1); });
