// Словарь: починка слов и отбрасывание строк, которых в русском нет.
const fs = require('fs');
require('./shim.js');
delete global.indexedDB;
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
const body = require('./koma-src.cjs').app;
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Words, DB, readingOrder, DEFAULT_RULES, sanitizeRules};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  // Небольшой «словарь частот»: ровно то, что делает ru_250k.txt (ранг = строка)
  const dict = ['и', 'в', 'не', 'уже', 'пора', 'начинать', 'встречу', 'так', 'что', 'её',
    'высочество', 'должно', 'быть', 'прибыла', 'не', 'уверен', 'как', 'стоит', 'сказать',
    'это', 'но', 'позволять', 'себе', 'увлечься', 'вы', 'должны', 'равнодушны',
    'всегда', 'притворитесь', 'обдумываете', 'говорит', 'раза', 'когда', 'слушаете',
    'прочь', 'да', 'именно', 'делать', 'как', 'прожить', 'жизнь', 'старшей', 'сестрой',
    'тирана', 'пошевелиться', 'сюда', 'три'].join('\n');
  await api.DB.put('kv', { k: 'dict:ru250k', v: dict + '\n' + Array.from({ length: 1200 }, (_, i) => 'слово' + i).join('\n') });
  const loaded = await api.Words.load();
  ok(loaded === true, 'словарь загружен: ' + api.Words.size + ' строк');

  ok(api.Words.finish('ПОШЕВЕАИТЬСЯ') === 'ПОШЕВЕЛИТЬСЯ',
    'починка слова: ПОШЕВЕАИТЬСЯ → ' + api.Words.finish('ПОШЕВЕАИТЬСЯ'));
  ok(api.Words.finish('СЮОДА') === 'СЮДА', 'СЮОДА → ' + api.Words.finish('СЮОДА'));
  ok(api.Words.finish('УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ,') === 'УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ,',
    'верная реплика не тронута');

  // Мусор из каллиграфии и звуковых эффектов
  ok(api.Words.polish('ол кослл алмчлс', 0.6) === '', 'мусор «ол кослл алмчлс» отброшен');
  ok(api.Words.polish('сттангасоат', 0.6) === '', 'мусор «сттангасоат» отброшен');
  // Слова этой реплики есть в мини-словаре ниже; фраза с незнакомыми словами
  // и здесь, и в жизни считается мусором — это и есть работа фильтра.
  ok(api.Words.polish('ВЫ ДОЛЖНЫ БЫТЬ РАВНОДУШНЫ', 0.6).length > 0, 'настоящая реплика осталась');
  // «три» — настоящее слово, поэтому реплику оставляем (правило «есть
  // настоящие слова → не выбрасывать»), но мусорные слова из неё уходят.
  ok(api.Words.polish('три посторонних слова', 0.6).length > 0,
    'реплика с настоящим словом осталась: «' + api.Words.polish('три посторонних слова', 0.6) + '»');
  ok(api.Words.polish('ъыь ффжж кщк', 0.6) === '', 'фраза без единого настоящего слова отброшена');

  // В порядке чтения мусор тоже выпадает
  const R = api.sanitizeRules(api.DEFAULT_RULES);
  const reg = (t, l, tp, r, b) => ({ text: t, left: l, top: tp, right: r, bottom: b, confidence: 1 });
  const lines = api.readingOrder([
    reg('УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ,', 0.09, 0.20, 0.47, 0.23),
    reg('ол кослл алмчлс', 0.10, 0.30, 0.40, 0.33),
    reg('ТАК ЧТО ЕЁ ВЫСОЧЕСТВО ДОЛЖНО БЫТЬ ПРИБЫЛА', 0.10, 0.40, 0.48, 0.43),
  ], true, true, R);
  ok(lines.length === 2, 'из трёх строк осталось две реплики: ' + lines.length);
  ok(!lines.some(l => /кослл/.test(l.text)), 'мусорной строки в репликах нет');
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.log('FATAL', e.message); process.exit(1); });
