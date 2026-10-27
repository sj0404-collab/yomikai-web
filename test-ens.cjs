// Комбинаторика на трудных строках + второй распознаватель («субагент»).
// Замер-обоснование: на облачке-крике со скриншота 17:30 бинаризация дала
// «ВОЗЬМИ» вместо «ВОЗЫМИ» и разделила слипшиеся слова («ТЫ БЫИ ЧТ ТЫМ»),
// а увеличение ×1.5/×2/×3 — ничего.
const fs = require('fs');
require('./shim.js');
delete global.indexedDB;
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync('/home/user/koma-web/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Words, DB, OCR, RULES, DEFAULT_RULES, sanitizeRules, SPEED_PRESETS,'
  + ' variantBetter, lineStat, invertCanvas, makeCanvas, DECODE_STATS};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  const dict = ['и', 'в', 'не', 'лучше', 'быть', 'более', 'черт', 'возьми', 'возьми,',
    'знать', 'жизнь', 'будучи', 'старшей', 'сестрой', 'тирана', 'равнодушным',
    'ты', 'был', 'что', 'можешь'].join('\n');
  await api.DB.put('kv', { k: 'dict:ru250k', v: dict + '\n' + Array.from({ length: 1200 }, (_, i) => 'слово' + i).join('\n') });
  await api.Words.load();
  ok(api.Words.ready, 'словарь загружен: ' + api.Words.size);

  const W = api;

  // 1. Перебор берёт вариант, где больше слов из словаря
  ok(W.variantBetter('ТАЕ ЧЕРТ ВОЗЬМИ', 'ТАЕ ЧЕРТ ВОЗЫМИ') === true,
    'вариант с «ВОЗЬМИ» лучше, чем с «ВОЗЫМИ»');
  ok(W.variantBetter('ТЫ БЫИ ЧТ ТЫМ', 'ТЫБЫЧТО ТМО') === true,
    'разделённые слова лучше слипшихся');
  // 2. Но не берёт вариант, который испортил слово (регресс e2e «будучи» → «буздчо»)
  ok(W.variantBetter('жизнь, буздчо старшей', 'жизнь, будучи старшей') === false,
    'испорченное слово не выигрывает у верного');
  ok(W.variantBetter('ЛУЧШЕ БЫТЬ БОЛЕЕ', 'ЛУЧШЕ БЫТЬ БОЛЕЕ') === false,
    'одинаковый текст не считается улучшением');
  // 3. Счётчик слов строки
  const st = W.lineStat('ЛУЧШЕ БЫТЬ БОЛЕЕ');
  ok(st.n === 3 && st.known === 3 && st.junk === 0, 'lineStat считает слова: ' + JSON.stringify(st));

  // 4. Инверсия действительно инвертирует (это отдельная подготовка, не бинаризация)
  const c = W.makeCanvas(4, 4);
  const g = c.getContext('2d');
  g.fillStyle = '#000'; g.fillRect(0, 0, 4, 4);
  const inv = W.invertCanvas(c);
  const px = inv.getContext('2d').getImageData(0, 0, 4, 4).data;
  ok(px[0] === 255 && px[1] === 255 && px[2] === 255, 'инверсия чёрного даёт белое');

  // 5. Настройки: перебор включён, у «Молнии» выключен, отключается правилом
  ok(W.sanitizeRules({}).hardVariants === true, 'перебор трудных строк включён по умолчанию');
  ok(W.sanitizeRules({ speed: 'lightning' }).hardVariants === false, 'у «Молнии» перебора нет');
  ok(W.sanitizeRules({ hardVariants: false }).hardVariants === false, 'перебор отключается правилом');

  // 6. Второй распознаватель: без файла его нет, и это не ломает движок
  ok(W.OCR.rec2 === null || W.OCR.rec2 === undefined, 'без cyrillic2.onnx второго распознавателя нет');
  ok(typeof W.OCR.checkRec2Alphabet === 'function', 'есть проверка азбуки второго распознавателя');
  // Проверка азбуки: словарь не пуст, поэтому «нет модели» = false, а не падение
  let threw = null;
  try { await W.OCR.checkRec2Alphabet(null); } catch (e) { threw = e; }
  ok(!threw && (await W.OCR.checkRec2Alphabet(null)) === false,
    'без модели проверка азбуки отвечает «нет», а не падает');

  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.log('FATAL', e.message); process.exit(1); });
