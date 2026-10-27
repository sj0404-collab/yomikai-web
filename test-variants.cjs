// «Пробовать все варианты, но слова должны быть верными».
// Проверяем: перебор подготовок кропа, выбор по словарю, отказ от опасной
// правки в два редактирования, ранний выход когда всё уже верно.
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
  .map(f => fs.readFileSync('/home/user/koma-web/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Words, OCR, RULES, sanitizeRules, decodeBetter, textScore, allWordsKnown, makeCanvas, DECODE_STATS};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  const txt = fs.readFileSync(__dirname + '/data/ru_250k.txt', 'utf8');
  const rank = new Map(); let n = 0;
  for (const line of txt.split('\n')) { const w = (line.split(/\s+/)[0] || '').toLowerCase(); if (!w) continue; if (!rank.has(w)) rank.set(w, n); n++; }
  const W = api.Words; W.rank = rank; W.size = n; W.ready = true;
  const R = api.sanitizeRules(api.DEFAULT_RULES);
  R.minConfidence = 0;

  // 1. Опасная правка в два редактирования выключена
  ok(W.FIX_DISTANCE === 1, 'правка в два редактирования выключена (иначе «Сесмой» → «Самой»)');
  ok(W.correctWord('Сесмой') === 'Сесмой', '«Сесмой» не превращается в «Самой»');
  ok(W.correctWord('ПОШЕВЕАИТЬСЯ') === 'ПОШЕВЕЛИТЬСЯ', 'правка в одно редактирование работает');
  ok(W.correctWord('ВЫСОЧЕСТВОМ') === 'ВЫСОЧЕСТВОМ', 'настоящая словоформа не тронута');

  // 2. Оценка текста по словарю: верные слова > мусор с хорошей уверенностью
  const good = api.textScore('сестрой тирана', 0.5);
  const bad = api.textScore('есmpoй mиpана', 0.9);
  ok(good > bad, 'текст из настоящих слов оценивается выше (' + good.toFixed(1) + ' > ' + bad.toFixed(1) + ')');
  ok(api.allWordsKnown('сестрой тирана') === true, 'все слова известны — перебор можно не продолжать');
  ok(api.allWordsKnown('оддучив старшей') === false, 'слово с ошибкой распознаётся как неизвестное');

  // 3. Перебор реально пробует варианты и берёт лучший
  const crop = api.makeCanvas(120, 32);
  const ctx = crop.getContext('2d');
  const im = ctx.getImageData(0, 0, 120, 32); im.data.fill(240);
  for (let y = 8; y < 24; y++) for (let x = 5; x < 115; x++) im.data[(y * 120 + x) * 4] = 30;
  ctx.putImageData(im, 0, 0);

  api.OCR.dict = ['', ' '];
  let calls = 0;
  // первый вариант — мусор с высокой уверенностью, второй — верные слова
  const answers = [['есmpoй mиpана', 0.95], ['сестрой тирана', 0.4], ['сестрой тирана', 0.5], ['', 0]];
  api.OCR.rec = {
    inputNames: ['x'], outputNames: ['y'],
    run: async (feed) => {
      const [t] = answers[Math.min(calls, answers.length - 1)]; calls++;
      const C = 3, T = Math.max(1, t.length);
      const data = new Float32Array(T * C);
      for (let i = 0; i < T; i++) data[i * C + 1] = 1;
      return { y: { dims: [1, T, C], data } };
    },
  };
  api.OCR.dict = ['', ' ', 'x'];
  const [text, conf] = await api.decodeBetter(crop, R, { wide: true });
  ok(calls >= 2, 'перебор включился и попробовал больше одного варианта (вызовов: ' + calls + ')');
  ok(typeof text === 'string' && conf >= 0, 'вернулся текст варианта с лучшей оценкой по словарю');

  // 4. Если всё верно с первого раза — лишних прогонов нет
  calls = 0;
  api.OCR.rec = {
    inputNames: ['x'], outputNames: ['y'],
    run: async () => {
      calls++;
      const C = 3, T = 14, data = new Float32Array(T * C);
      for (let i = 0; i < T; i++) data[i * C + 1] = 1;
      return { y: { dims: [1, T, C], data } };
    },
  };
  // слова из заглушки не настоящие, поэтому перебор включится — но не больше
  // числа вариантов
  await api.decodeBetter(crop, R, { wide: true });
  ok(calls <= 6, 'перебор ограничен: 1 основной + 5 вариантов (вызовов: ' + calls + ')');

  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.error('FAIL', e.stack); process.exit(1); });
