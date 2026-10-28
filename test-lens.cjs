// Google Lens как отдельный движок — проверки без браузера.
// Живой прогон (вкладка, отправка формы, озвучка) — в e2e_lens.py.
require('./shim.js');
const fs = require('fs');
const path = require('path');

const here = __dirname;
const code = ['part2.js', 'part3.js'].map(f => fs.readFileSync(path.join(here, f), 'utf8')).join('\n');
const api = new Function(code + '\n return { LENS, cropCanvas, makeCanvas, sanitizeRules, readingOrder };')();

let fails = 0;
const ok = (name, cond, extra) => {
  if (!cond) { console.log('FAIL', name, extra === undefined ? '' : '· ' + JSON.stringify(extra)); fails++; }
  else console.log('ok  ', name);
};

// 1. По умолчанию — офлайн-движок, и картинка в сеть не уходит.
ok('движок по умолчанию «в файле»', api.LENS.mode === 'local', api.LENS.mode);
ok('isLens() честно отвечает', api.LENS.isLens() === false);
const cv = api.makeCanvas(40, 20);
const blocked = api.LENS.send(cv, { page: 0 });
ok('в режиме «в файле» отправки нет', blocked.ok === false && /никуда не отправлялась/.test(blocked.reason), blocked);

// 2. Адрес и поле формы — то, что реально понимает Lens (проверено 28.10).
ok('адрес загрузки Lens', /^https:\/\/lens\.google\.com\/v3\/upload/.test(api.LENS.action), api.LENS.action);
ok('в адресе язык ru', /hl=ru/.test(api.LENS.action));

// 3. Текст из Lens → реплики: порядок, геометрия, мусор отбрасывается.
const lines = api.LENS.textToLines('МАЛЫШКА МЕЛИССА\n\n  В курятнике   все спали. \n— Ко-ко-ко!\n*\n...');
ok('пустые строки и строки без букв отброшены', lines.length === 3, lines.map(l => l.text));
ok('текст подрезан и пробелы сжаты', lines[1].text === 'В курятнике все спали.', lines[1].text);
ok('порядок сверху вниз', lines[0].top < lines[1].top && lines[1].top < lines[2].top,
  lines.map(l => l.top));
ok('геометрия внутри страницы', lines.every(l => l.left >= 0 && l.right <= 1 && l.top >= 0 && l.bottom <= 1));
ok('помечено происхождение', lines.every(l => l.fromLens === true));
ok('из пустого текста — ноль реплик', api.LENS.textToLines('---\n\n   \n').length === 0);
ok('одна строка даёт одну реплику', api.LENS.textToLines('Привет').length === 1);

// 4. Вырезка полосы для отправки (в Lens уходит то, что видно).
const big = api.makeCanvas(300, 900);
const crop = api.cropCanvas(big, 10, 100, 200, 300);
ok('cropCanvas даёт ровно запрошенный размер', crop.width === 200 && crop.height === 300,
  [crop.width, crop.height]);

// 5. Режимы переключаются и «залипают» в самом объекте.
(async () => {
  ok('переключение на lens', (await api.LENS.setMode('lens')) === 'lens' && api.LENS.isLens());
  ok('неизвестное значение трактуется как офлайн', (await api.LENS.setMode('что-то')) === 'local');
  // 6. В режиме lens send() пытается отправить (в тесте DOM-заглушка бросит —
  // важно, что он НЕ отказывается по причине «режим локальный»).
  await api.LENS.setMode('lens');
  const sent = api.LENS.send(cv, { page: 0 });
  ok('в режиме lens отправка не блокируется режимом',
    !(sent.ok === false && /никуда не отправлялась/.test(sent.reason)), sent);
  console.log(fails ? `\n${fails} FAILED` : '\nALL PASSED');
  process.exit(fails ? 1 : 0);
})();
