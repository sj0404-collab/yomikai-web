// Node-прогон обработчиков: ровно те пути, на которых падал файл.
require('./dom_shim.js');
const fs = require('fs');
const { getById } = require('./dom_shim.js');
// Собираем приложение из частей: в самом HTML теперь вшит движок на 7 МБ,
// и вырезать оттуда код регулярками — плохая идея.
const body = ['part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const trimmed = body.slice(0, body.indexOf('(async function boot()'));
new Function(trimmed + '; global.__api={bindUI,Library,DB};')();
const { bindUI, DB } = global.__api;
bindUI();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };
(async () => {
  // 1. Модели по одному: ни книги, ни читалки
  const mi = getById('modelPick');
  for (const n of ['detection.onnx', 'cyrillic.onnx']) {
    mi.files = [new File([new Uint8Array([7, 7])], n)];
    await mi.onchange();
  }
  ok((await DB.all('books')).length === 0, 'выбор модели не создаёт книгу');
  ok(!!(await DB.get('kv', 'model:det')), 'detection.onnx сохранён');
  ok(/❌ cyrillic\.txt/.test(getById('modelsState').innerHTML), 'недостающий файл показан как ❌');
  mi.files = [new File([new Uint8Array([1])], 'cyrillic.txt')];
  await mi.onchange();
  ok(/✅ cyrillic\.txt/.test(getById('modelsState').innerHTML), 'третий файл принят, шторка не закрылась');

  // 2. Импорт картинок: порядок из имён
  const inp = getById('imgPick');
  inp.files = ['003.jpg', '001.jpg', '002.jpg'].map(n => new File([new Uint8Array([1, 2, 3])], n));
  await inp.onchange();
  const pages = (await DB.all('pages')).sort((a, b) => a.index - b.index).map(p => p.name);
  ok(pages.join(',') === '001.jpg,002.jpg,003.jpg', 'страницы отсортированы по именам: ' + pages.join(','));
  ok((await DB.all('books')).length === 1, 'создана одна книга');

  // 3. Импорт папки: заголовок из имени папки
  const dir = getById('dirPick');
  dir.files = ['g/002.jpg', 'g/001.jpg'].map(n => {
    const f = new File([new Uint8Array([1])], n.split('/')[1]); f.webkitRelativePath = n; return f;
  });
  await dir.onchange();
  const books = await DB.all('books');
  ok(books.length === 2 && books.some(b => b.title === 'g'), 'папка дала книгу «g»');
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})();
