// Дочинка ОТДЕЛЬНЫХ слов: битое слово перебирается по кропу, верные слова и
// верные строки не трогаются. Модель подменена: строка читается с ошибкой,
// а кроп битого слова — верно.
const fs = require('fs');
require('./shim.js');
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.indexedDB = undefined;
global.document.getElementById = () => ({
  textContent: '', innerHTML: '', style: {}, classList: { contains: () => false, add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {},
});
global.document.querySelector = () => null;
global.ort = { env: { wasm: {} }, Tensor: class { constructor(t, d, dims) { this.data = d; this.dims = dims; } } };
const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Words, OCR, RULES, sanitizeRules, refineBrokenWords, wordColumns, makeCanvas, DECODE_STATS};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  const txt = fs.readFileSync(__dirname + '/data/ru_250k.txt', 'utf8');
  const rank = new Map(); let n = 0;
  for (const line of txt.split('\n')) { const w = (line.split(/\s+/)[0] || '').toLowerCase(); if (!w) continue; if (!rank.has(w)) rank.set(w, n); n++; }
  const W = api.Words; W.rank = rank; W.size = n; W.ready = true;
  const R = api.sanitizeRules(api.DEFAULT_RULES);
  R.minConfidence = 0;

  // белый кроп 300×40 с четырьмя «словами» (тёмные блоки)
  const crop = api.makeCanvas(300, 40);
  const ctx = crop.getContext('2d');
  const im = ctx.getImageData(0, 0, 300, 40);
  im.data.fill(250);
  const words = [[10, 60], [90, 150], [180, 230], [255, 290]];
  for (const [a, b] of words) {
    for (let y = 8; y < 32; y++) for (let x = a; x < b; x++) {
      const p = (y * 300 + x) * 4;
      im.data[p] = im.data[p + 1] = im.data[p + 2] = 20;
    }
  }
  ctx.putImageData(im, 0, 0);

  const cols = api.wordColumns(crop, R);
  ok(cols.length === 4, 'строка разрезана на 4 слова (' + cols.length + ')');

  // Кроп-слово шириной меньше 100 px → «верное» слово; шире → мусор.
  // Так имитируем и строку (ошибка), и отдельное слово (верно).
  // decodeCrop всегда добивает ширину до 320, поэтому «широкий» и «узкий»
  // вход различаются по фактической ширине тензора: строка 360, слово 320.
  api.OCR.dict = ['', 'б', 'у', 'д', 'ч', 'и', 'о', 'л', 'в', 'а', 'к', 'п', 'р', 'ж', 'т', 'ь', 'с', 'е', 'й'];
  api.OCR.rec = {
    inputNames: ['x'], outputNames: ['y'],
    run: async (feed) => {
      const w = feed.x.dims[3];
      const word = w < 340 ? 'будучи' : 'оддучив';
      const T = word.length, C = api.OCR.dict.length, data = new Float32Array(T * C);
      for (let i = 0; i < T; i++) {
        const idx = Math.max(1, api.OCR.dict.indexOf(word[i]));
        data[i * C + idx] = 1;
      }
      return { y: { dims: [1, T, C], data } };
    },
  };
  api.DECODE_STATS.wordsFixed = 0; api.DECODE_STATS.wordsTried = 0;
  const fixed = await api.refineBrokenWords(crop, 'Как прожить оддучив старшей', R);
  ok(/будучи/.test(fixed), 'битое слово дочинено по своему кропу: «' + fixed + '»');
  ok(!/оддучив/.test(fixed), 'битое слово убрано');
  ok(/Как прожить/.test(fixed) && /старшей/.test(fixed), 'верные слова не тронуты');
  ok(api.DECODE_STATS.wordsFixed === 1, 'дочинено ровно одно слово (не перебирали верные)');

  // Строка, где всё верно — перебора нет вовсе
  api.DECODE_STATS.wordsTried = 0;
  const same = await api.refineBrokenWords(crop, 'Как прожить жизнь старшей', R);
  ok(same === 'Как прожить жизнь старшей', 'верная строка возвращена как есть');
  ok(api.DECODE_STATS.wordsTried === 0, 'по верной строке не было ни одной попытки перебора');

  // Мусорный кандидат не принимается: кроп даёт «p» — замена запрещена
  api.OCR.rec.run = async () => {
    const C = 3, T = 1, data = new Float32Array(T * C);
    data[1] = 1;
    return { y: { dims: [1, T, C], data } };
  };
  const junk = await api.refineBrokenWords(crop, 'Как прожить оддучив старшей', R);
  ok(/оддучив/.test(junk), 'мусорный кандидат («p») не подменяет слово: «' + junk + '»');

  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.error('FAIL', e.stack); process.exit(1); });
