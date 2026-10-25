// Вшитый словарь: разжимается, слов 250 000, языковая починка включается сама.
const fs = require('fs');
const crypto = require('crypto');
require('/tmp/shim.js');
delete global.indexedDB;
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync('/home/user/koma-web/' + f, 'utf8')).join('\n');
// part0-dict.js содержит вшитый словарь и b64ToBytes — грузим вместе
const dictSrc = fs.readFileSync('/home/user/koma-web/part0-dict.js', 'utf8');
// Собираем как в реальной странице: сначала часть со словарём, потом приложение.
const combined = dictSrc + '\n' + body.slice(0, body.indexOf('(async function boot()'));
const api = new Function(combined + '; return {Words, DB, embeddedDictText, DICT_GZ_B64};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  ok(typeof api.DICT_GZ_B64 === 'string' && api.DICT_GZ_B64.length > 1000000,
    'словарь вшит в файл: ' + (api.DICT_GZ_B64.length / 1048576).toFixed(2) + ' МБ base64 (gzip)');
  const text = await api.embeddedDictText();
  const lines = text.split('\n').filter(l => l.trim());
  ok(lines.length === 250000, 'слов в словаре: ' + lines.length);
  ok(lines[0].startsWith('я ') && lines[0].split(' ')[1] === '5081568', 'первое слово по частоте: «' + lines[0] + '»');
  const md5 = crypto.createHash('md5').update(text, 'utf8').digest('hex');
  const src = crypto.createHash('md5').update(fs.readFileSync('/home/user/lab/ru_250k.txt', 'utf8'), 'utf8').digest('hex');
  ok(md5 === src, 'разжатый словарь побайтово равен исходному ru_250k.txt');

  const ready = await api.Words.load();
  ok(ready === true && api.Words.source === 'вшит в файл', 'словарь подхватывается сам, без выбора файла');
  ok(api.Words.size === 250000, 'загружено слов: ' + api.Words.size);
  ok(api.Words.finish('ПОШЕВЕАИТЬСЯ') === 'ПОШЕВЕЛИТЬСЯ', 'починка работает: ПОШЕВЕАИТЬСЯ → ' + api.Words.finish('ПОШЕВЕАИТЬСЯ'));
  ok(api.Words.polish('ол кослл алмчлс', 0.6) === '', 'мусорная строка отброшена');
  ok(api.Words.polish('УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ,', 0.6) !== '', 'настоящая реплика сохранена');
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.log('FATAL', e.message); process.exit(1); });
