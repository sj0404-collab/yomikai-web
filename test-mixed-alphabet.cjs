// Кириллица, прочитанная латиницей, и латинский шум в репликах.
//
// Скриншот телефона 2.11: название манги вышло «cecmpoй mиpaнa» — шрифт рисует
// «т» как латинскую «m», и в озвучку ушло «сесмой мирана». Плюс в репликах
// оставались куски вроде «low cYnaYIowb» и «СЛУШАЙТЕЕУ.owb».
const fs = require('fs');
require('./shim.js');
delete global.indexedDB;
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
const dictSrc = fs.readFileSync(__dirname + '/part0-dict.js', 'utf8');
const body = ['part0-wasm.js', 'part2.js', 'part3.js']
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(dictSrc + '\n' + body + '; return {Words};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  await api.Words.load();
  const W = api.Words;
  const P = (t) => W.polish(t, 0.6, 0.9);

  ok(P('cecmpoй mиpaнa').toLowerCase().includes('сестрой тирана'),
    'название манги: «cecmpoй mиpaнa» → «сестрой тирана»');
  ok(P('Как прожить жизнь, будучиь старшей cecmpoй mиpaнa').toLowerCase()
    .includes('сестрой тирана'), 'и внутри полного названия тоже');
  ok(P('low cYnaYIowb') === '', 'латинский шум «low cYnaYIowb» отброшен');
  ok(P('ОНА ГОВОРИТ РАЗА, КОГДА СЛУШАЙТЕЕУ.owb').toLowerCase().includes('слушайте'),
    '«СЛУШАЙТЕЕУ.owb» → «СЛУШАЙТЕ»');
  ok(P('вы должны ьыть РАВНОДУШНЫ, КАК И ЗСЕГДА.').toLowerCase().includes('всегда'),
    '«ЗСЕГДА» → «ВСЕГДА»');
  ok(P('ПРОЧЬ.') === 'ПРОЧЬ.', 'короткая реплика «ПРОЧЬ.» остаётся');
  ok(P('ДА, ЭТО ИМЕННО ТО, ЧТО ВЫ ДОЛЖНЫ ДЕЛАТЬ.').toLowerCase().includes('должны делать'),
    'нормальная реплика не портится');
  // Настоящая латиница (звук, имя) не превращается в кириллицу: замена идёт
  // только когда получившееся слово есть в словаре. Отдельно: «BANG» чистой
  // латиницей отбрасывался и раньше (это путь звуков), моя правка его не
  // трогает — поэтому здесь проверяем именно отсутствие подмены.
  ok(W.fixAlphabet('BANG') === 'BANG', 'звук «BANG» не превращается в кириллицу');
  ok(W.fixAlphabet('owb') === 'owb', 'и «owb» тоже не подменяется');
  // run_all.sh считает тест пройденным только по последней строке.
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})();
