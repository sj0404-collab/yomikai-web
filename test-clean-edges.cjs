// ЧИСТКА СТРОК, найденная прогоном в эмуляторе APKForge Studio (29.10).
//
// Две беды, которые видно только на живой странице:
//  1) тонкая полоска-«обрывок» от детектора (высота 0,002 страницы) с мусорным
//     текстом занижала «типичную высоту строки», и соседняя честная строка не
//     приклеивалась — ОДНА реплика выходила ДВУМЯ текстами;
//  2) обрывок звукового эффекта приклеивался к началу честной реплики:
//     «*ь*.*о НЕ УВЕРЕН, КАК СТОИТ СКАЗАТЬ ЭТО, НО…».
// Здесь закреплено и то, и другое — и то, что нормальные кавычки/тире не
// страдают.
const fs = require('fs');
require('./shim.js');
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.indexedDB = undefined;
const el = () => ({ textContent: '', innerHTML: '', style: {}, dataset: {}, value: '', checked: false,
  classList: { contains: () => false, add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {}, closest() { return null; },
  getBoundingClientRect: () => ({ top: 0, bottom: 800, height: 800, left: 0, right: 700 }) });
global.document.getElementById = el;
global.document.querySelector = () => el();
global.document.querySelectorAll = () => [];
global.document.addEventListener = () => {};
global.ort = { env: { wasm: {} }, Tensor: class { constructor(t, d, dims) { this.data = d; this.dims = dims; } } };

const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js'].map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {trimJunkEdges, cleanSpeech, bubblesOf, mergeBubbles, readingOrder, sanitizeRules, cleanLines, Words};')();

const T = api.trimJunkEdges;

// ── 1. Края реплики: обрывок звукового эффекта уходит
ok(T('*ь*.*о НЕ УВЕРЕН, КАК СТОИТ СКАЗАТЬ ЭТО, НО…') === 'НЕ УВЕРЕН, КАК СТОИТ СКАЗАТЬ ЭТО, НО…',
  'обрывок «*ь*.*о» в начале реплики убран');
ok(T('В БУДУЩЕМ, КОГДА ВЫ БУДЕТЕ ГОВОРИТЬ ~х~') === 'В БУДУЩЕМ, КОГДА ВЫ БУДЕТЕ ГОВОРИТЬ',
  'обрывок в конце реплики убран');
// ── 2. Нормальная пунктуация остаётся
ok(T('«В БУДУЩЕМ, КОГДА ВЫ БУДЕТЕ ГОВОРИТЬ С ЕЁ ВЫСОЧЕСТВОМ…»').startsWith('«В'),
  'открывающая кавычка не съедается');
ok(T('— ДА, Я СЛЫШУ.').startsWith('—'), 'тире в начале не съедается');
ok(T('УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ,').length > 5, 'обычная реплика не меняется');
ok(T('') === '' && T('   ') === '', 'пустое остаётся пустым');
// ── 3. Полоска-обрывок не разрезает реплику
const R = api.sanitizeRules({});
const L = (t, l, top, r, b) => ({ text: t, left: l, top, right: r, bottom: b });
const story = [
  L('УЖЕ ПОРА НА-', 0.14, 0.10, 0.42, 0.13),
  L('ЧИНАТЬ ВСТРЕЧУ,', 0.14, 0.14, 0.44, 0.17),
  L('ТАК ЧТО ЕЁ ВЫСО-', 0.14, 0.18, 0.45, 0.21),
  L('-ЧЕСТВО, ДОЛЖНО', 0.14, 0.22, 0.44, 0.25),
  L('БЫТЬ, ПРИБЫЛА.', 0.14, 0.26, 0.42, 0.29),
  L('НЕ УВЕРЕН,', 0.58, 0.22, 0.86, 0.25),
  L('КАК СТОИТ СКА-', 0.58, 0.26, 0.87, 0.29),
  L('ЗАТЬ ЭТО, НО...', 0.58, 0.30, 0.86, 0.33),
];
const sliver = L('так что сё выио шблтоо', 0.13, 0.1290, 0.86, 0.1310);    // толщина 0,002
const withSliver = api.readingOrder(story.concat([sliver]), 'rtl', true, R);
const withoutSliver = api.readingOrder(story, 'rtl', true, R);
// На этой странице ДВЕ реплики (левое облачко из пяти строк и правое из трёх):
// полоска не должна добавить третью.
ok(withSliver.length === 2, 'с полоской-обрывком реплик всё равно 2 (а не 3): ' + withSliver.length);
ok(withSliver.length === withoutSliver.length, 'полоска не меняет число реплик');
ok(withSliver.every(l => !/шблтоо/.test(l.text)), 'мусорный текст полоски не попал в реплики');
const first = withSliver.map(l => l.text).find(t => /УЖЕ ПОРА/.test(t)) || '';
ok(/ПРИБЫЛА/.test(first), 'реплика не разрезана: «УЖЕ ПОРА…» и «ПРИБЫЛА» в одном тексте');
ok((first.match(/УЖЕ ПОРА/g) || []).length === 1, 'и не удвоилась');

// ── 4. Средняя высота строки, а не минимум (иначе склейка ломается)
const three = [
  L('ПЕРВАЯ СТРОКА', 0.2, 0.10, 0.6, 0.130),
  L('ВТОРАЯ СТРОКА', 0.2, 0.135, 0.6, 0.165),
  L('ТРЕТЬЯ СТРОКА', 0.2, 0.170, 0.6, 0.200),
];
const merged3 = api.mergeBubbles(three.map(l => ({ ...l, lh: l.bottom - l.top, rows: 1 })), R.bubbleGap, R.mergeHeightRatio);
ok(merged3.length === 1, 'три строки одного облачка склеиваются в одну реплику: ' + merged3.length);
ok(/ТРЕТЬЯ/.test(merged3[0].text), 'и третья строка в ней есть');

// ── 5. Высота строки — СРЕДНЯЯ по строкам облачка, а не минимум.
// Блок из двух строк, к которому приклеивается третья: у блока высота в две
// строки, и «минимум высот» её занижал так, что третья строка уже не влезала
// (именно так облачко и рвалось на два текста).
const twoRows = {
  text: 'ПЕРВАЯ СТРОКА ВТОРАЯ СТРОКА',
  left: 0.2, top: 0.10, right: 0.6, bottom: 0.165,
  rows: 2, lh: (0.165 - 0.10) / 2,
};
const third = { ...three[2], lh: three[2].bottom - three[2].top, rows: 1 };
const mergedJunk = api.mergeBubbles([twoRows, third], R.bubbleGap, R.mergeHeightRatio);
ok(mergedJunk.length === 1, 'третья строка приклеивается к блоку из двух: ' + mergedJunk.length);
ok(/ТРЕТЬЯ/.test(mergedJunk[0].text), 'и она в тексте');

// ── 6. Котлы на другой стороне: та же чистка есть в движке приложения
const eng = fs.readFileSync(__dirname + '/apk/app/src/main/java/net/koma/reader/ReadEngine.kt', 'utf8');
ok(/trimJunkEdges/.test(eng), 'в Kotlin-движке есть та же чистка краёв');
ok(/median \* 0\.35|medianRaw \* 0\.35/.test(eng), 'и фильтр тонких полосок');
ok(!/lh = min\(b\.lh, line\.h\)/.test(eng), 'минимум высот больше не используется (он и ломал склейку)');
const main = fs.readFileSync(__dirname + '/apk/tools/readtest/Main.kt', 'utf8');
ok(/ПОЛОСКА-ОБРЫВОК/.test(main), 'readtest проверяет полоску-обрывок');

console.log(process.exitCode ? 'ЕСТЬ ПАДЕНИЯ' : 'ALL PASSED');
process.exit(process.exitCode || 0);
