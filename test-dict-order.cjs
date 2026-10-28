// Словарь без частотного порядка (большой алфавитный список) не должен
// «оглуплять» читалку. Замер 27.10: список на 3 000 000 слов, отсортированный
// по алфавиту, давал НОЛЬ реплик на странице, которая с ru_250k читается
// целиком, — потому что KNOWN_RANK сравнивает номер строки.
const fs = require('fs');
require('./shim.js');
delete global.indexedDB;
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.ort = { Tensor: class { constructor(t, d, s) { this.type = t; this.data = d; this.dims = s; } } };
const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Words, DB, RULES, lineStat, variantBetter};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

// Частотный список: сначала частые слова, потом редкие — как ru_250k.
const FREQ = ['и', 'в', 'не', 'что', 'он', 'на', 'я', 'с', 'как', 'это', 'ты', 'же',
  'лучше', 'быть', 'более', 'равнодушным', 'тирана', 'будучи', 'высочеством'];
// Алфавитный список на 60 000 слов — как большой список, отсортированный по
// алфавиту: частые слова разбросаны, номер строки ничего не значит.
const ALPHA = Array.from({ length: 60000 }, (_, i) => 'аа' + String(i).padStart(5, '0'))
  .concat(FREQ).sort();

(async () => {
  // 1. Частотный порядок распознаётся
  await api.DB.put('kv', { k: 'dict:ru250k', v: FREQ.concat(Array.from({ length: 1200 }, (_, i) => 'редкое' + i)).join('\n') });
  await api.Words.load();
  ok(api.Words.ordered === true, 'частотный список: порядок распознан');
  ok(api.Words.isKnown('лучше') === true, 'частое слово известно');
  const savedKnown = api.Words.KNOWN_RANK;
  api.Words.KNOWN_RANK = 12;                    // как будто слов в словаре много
  ok(api.Words.isKnown('редкое500') === false, 'слово за порогом частоты не «частое»');
  api.Words.KNOWN_RANK = savedKnown;
  ok(api.Words.candidate('лутше') === 'лучше', 'правка слов работает');
  ok(api.Words.junkRatio('абажур абрикос') === 1, 'мусор по частоте считается');

  // 2. Алфавитный список: режим «только членство»
  await api.DB.put('kv', { k: 'dict:ru250k', v: ALPHA.join('\n') });
  await api.Words.load();
  ok(api.Words.ordered === false, 'алфавитный список: порядок НЕ распознан');
  ok(/без частотного порядка/.test(api.Words.source), 'в источнике честно сказано: ' + api.Words.source);

  // 3. Настоящие словарь-слова остаются «настоящими» (иначе строка считалась бы мусором)
  ok(api.Words.isKnown('лучше') === true, 'в мягком режиме слово из словаря = настоящее');
  ok(api.Words.isKnown('аа00005') === true, 'и слово с дальнего конца списка тоже');
  ok(api.Words.junkRatio('лучше быть более') === 0, 'настоящая фраза не считается мусором');

  // 4. Правка слов выключена — верные слова не портятся
  ok(api.Words.candidate('лутше') === null, 'в мягком режиме кандидатов нет');
  ok(api.Words.correctWord('лутше') === 'лутше', 'слово не «исправляется» наугад');

  // 5. Строка из каллиграфии по-прежнему отбрасывается (мусор = нет в словаре)
  ok(api.Words.junkRatio('ол кослл алмчлс') === 1, 'каллиграфия = мусор и в мягком режиме');

  // 6. polish не съедает нормальную реплику
  const kept = api.Words.polish('ЛУЧШЕ БЫТЬ БОЛЕЕ РАВНОДУШНЫМ.', 0.6, 0.9);
  ok(kept.trim().length > 10, 'реплика осталась: «' + kept.slice(0, 40) + '»');

  // 7. Частотный режим возвращается, если словарь снова по частоте
  await api.DB.put('kv', { k: 'dict:ru250k', v: FREQ.concat(Array.from({ length: 1200 }, (_, i) => 'редкое' + i)).join('\n') });
  await api.Words.load();
  ok(api.Words.ordered === true, 'после перезагрузки частотный порядок снова включён');
})().then(() => console.log(process.exitCode ? 'ЕСТЬ ПАДЕНИЯ' : 'ALL PASSED'),
      e => { console.log('FAIL исключение: ' + (e && e.stack || e)); process.exitCode = 1; });
