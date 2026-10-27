// Свой декодер (поиск по словарю вместо жадного разбора), наклон строки и
// оценщик наклона. Замер-обоснование (облачка 27.10, настоящие модели):
//   b4 «ГДЕ, ЧЁРТ ВОЗЬМИ, ТЫ БЫЛ ЧТО ТЫ МОЖЕШЬ ЗНАТЬ!»
//   было «ТАЕ ЧЕРТ ВОЗЬМИ / ТЫ БЫИ ЧТ ТЫМ / ЖЕШЬ ЗНАТЬ!»   CER 17,6 %
//   стало «ТАЕ ЧЕРТ ВОЗЬМИ / ТЫ БЫ ЧТО ТЫ МОО / ЖЕШЬ ЗНАТЬ!» CER 14,7 %
//   b3 «ПΛОХ?» → «ПЛОХ?» (латинская Λ стала кириллической Л)
const fs = require('fs');
require('./shim.js');
delete global.indexedDB;
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.ort = { Tensor: class { constructor(t, d, s) { this.type = t; this.data = d; this.dims = s; } } };
const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync('/home/user/koma-web/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Words, DB, OCR, RULES, beamDecode, shearCanvas, estimateSlant,'
  + ' decoderWords, isWordPrefix, makeCanvas, lineStat};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

// Мини-canvas с нарисованными пикселями: он же используется в тестах,
// поэтому «нарисовать» = записать точки в data.
function canvasWith(w, h, paint) {
  const c = api.makeCanvas(w, h);
  for (let i = 0; i < c.data.length; i += 4) { c.data[i] = c.data[i+1] = c.data[i+2] = 255; c.data[i+3] = 255; }
  paint((x, y) => { const o = (y * w + x) * 4; c.data[o] = c.data[o+1] = c.data[o+2] = 0; });
  return c;
}

(async () => {
  // ── 1. Словарь для декодера: без регистра и по алфавиту
  await api.DB.put('kv', { k: 'dict:ru250k', v: ['лучше', 'быть', 'более', 'чёрт', 'возьми', 'жизнь', 'ты', 'был',
    'что', 'можешь', 'знать', 'уж', 'уже', 'плох', 'наизусть'].join('\n')
    + '\n' + Array.from({ length: 1200 }, (_, i) => 'слово' + i).join('\n') });
  await api.Words.load();
  const words = api.decoderWords();
  ok(Array.isArray(words) && words.length > 15, 'словарь декодера построен: ' + (words && words.length) + ' слов');
  ok(words.every(w => w === w.toUpperCase()), 'слова в верхнем регистре');
  ok(words.every((w, i) => i === 0 || words[i - 1] <= w), 'отсортированы по алфавиту');
  ok(api.decoderWords() === words, 'строится один раз (кэш)');

  // ── 2. Проверка «есть ли слово с таким началом» (двоичный поиск)
  ok(api.isWordPrefix('ЛУЧ', words) === true, 'префикс ЛУЧ есть');
  ok(api.isWordPrefix('ЛУЧШЕ', words) === true, 'целое слово ЛУЧШЕ — тоже префикс');
  ok(api.isWordPrefix('ЛУЧШЕБ', words) === false, 'ЛУЧШЕБ нет');
  ok(api.isWordPrefix('ЦЦЦ', words) === false, 'несуществующее начало не признаётся');

  // ── 3. Декодер предпочитает слово из словаря бессмысленному набору
  // Азбука как у настоящей модели: класс 0 — blank.
  const savedDict = api.OCR.dict;
  api.OCR.dict = [' ', 'А', 'Б', 'В', 'Г'];
  api.Words.rank = new Map([['ав', 0]]);   // «АБВ» не слово, «АВ» есть в словаре
  api.OCR._decWords = undefined;
  // Кадры: А(0.9) → Б/В почти равны → В(0.9). Жадный разбор даст «АБВ».
  const T = 4, C = 5;
  const probs = new Float32Array(T * C);
  const set = (t, c, v) => { probs[t * C + c] = v; };
  set(0, 1, 0.9); set(0, 0, 0.05); set(0, 2, 0.03); set(0, 3, 0.02);
  set(1, 2, 0.55); set(1, 3, 0.42); set(1, 0, 0.03);   // акустика чуть за «АБВ»
  set(2, 3, 0.9); set(2, 0, 0.05); set(2, 2, 0.05);
  set(3, 0, 0.98);
  const [beamText] = api.beamDecode({ T, C, p: probs });
  ok(beamText === 'АВ', 'декодер выбрал слово из словаря: «' + beamText + '» (без словаря было бы «АБВ»)');

  // ── 4. Без словаря (нет Words) декодер не падает и читает как есть
  const savedReady = api.Words.ready;
  api.Words.rank = null; api.Words.ready = false;
  api.OCR._decWords = undefined;
  const [plain] = api.beamDecode({ T, C, p: probs });
  ok(plain === 'АБВ', 'без словаря — обычное чтение: «' + plain + '»');
  api.Words.ready = savedReady; api.OCR._decWords = undefined;

  // ── 5. Двойные пробелы не появляются, пустая строка не ломается
  api.OCR.dict = [' ', 'А'];
  api.Words.rank = null; api.OCR._decWords = undefined;
  const p2 = new Float32Array(4 * 2);
  p2[0 * 2 + 1] = 0.9; p2[1 * 2 + 1] = 0.9; p2[2 * 2 + 0] = 0.9; p2[3 * 2 + 0] = 0.9;
  const [two] = api.beamDecode({ T: 4, C: 2, p: p2 });
  ok(two === 'А', 'повтор буквы склеивается: «' + two + '»');
  const [empty] = api.beamDecode({ T: 2, C: 2, p: new Float32Array([0.9, 0.1, 0.9, 0.1]) });
  ok(empty === '', 'одни blank — пустая строка');
  api.OCR.dict = savedDict;

  // ── 6. Наклон: картинка шире, строки сдвинуты, работают на мини-canvas
  const src = canvasWith(20, 10, (put) => { for (let y = 2; y < 8; y++) for (let x = 8; x < 12; x++) put(x, y); });
  const sheared = api.shearCanvas(src, 0.3);
  ok(sheared.width > src.width, 'после наклона картинка шире: ' + src.width + ' → ' + sheared.width);
  ok(sheared.height === src.height, 'высота не меняется');
  const inkAt = (c, x, y) => { const o = (y * c.width + x) * 4; return c.data[o] < 128; };
  // при tan>0 нижние строки уезжают правее верхних (сдвиг −tan·y)
  // при tan>0 верхние строки уезжают правее нижних: одна и та же колонка
  // попадает в букву сверху и не попадает снизу (или наоборот)
  const cols = [];
  for (let x = 0; x < sheared.width; x++) cols.push([inkAt(sheared, x, 3), inkAt(sheared, x, 6)]);
  ok(cols.some(([a, b]) => a !== b), 'нижние строки сдвинуты относительно верхних');

  // ── 7. Оценщик наклона: ровная картинка — наклон 0, косая — правильный знак
  const straight = canvasWith(120, 60, (put) => {
    for (let x = 20; x < 100; x++) for (let y = 15; y < 45; y++) put(x, y);
  });
  const t0 = api.estimateSlant(straight, api.RULES);
  ok(Math.abs(t0) <= 0.05, 'ровная строка: наклон ' + t0);
  const slanted = canvasWith(140, 60, (put) => {
    for (let y = 15; y < 45; y++) {
      const dx = Math.round(0.25 * (45 - y));       // буквы наклонены вправо вверх
      for (let x = 20; x < 100; x++) put(x + dx, y);
    }
  });
  const t1 = api.estimateSlant(slanted, api.RULES);
  ok(t1 <= -0.05, 'косая строка: наклон ' + t1 + ' (знак отрицательный, как у «крика» на b4)');
})().then(() => console.log(process.exitCode ? 'ЕСТЬ ПАДЕНИЯ' : 'ALL PASSED'),
        e => { console.log('FAIL исключение: ' + (e && e.stack || e)); process.exitCode = 1; });
