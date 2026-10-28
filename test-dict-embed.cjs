// Вшитый словарь: разжимается, 487 247 слов (250 000 частотных + 237 247
// словоформ частых лемм), языковая починка включается сама.
// Замер 27.10: словоформы дают тот же результат, что словарь на 1,5 млн
// («равнодушные» больше не превращается в «равнодушным»), но файл легче на
// 3,2 МБ и старт вдвое быстрее.
const fs = require('fs');
const crypto = require('crypto');
require('./shim.js');
delete global.indexedDB;
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
// part0-dict.js содержит вшитый словарь и b64ToBytes — грузим вместе
const dictSrc = fs.readFileSync(__dirname + '/part0-dict.js', 'utf8');
// Собираем как в реальной странице: сначала часть со словарём, потом приложение.
const combined = dictSrc + '\n' + body.slice(0, body.indexOf('(async function boot()'));
const api = new Function(combined + '; return {Words, DB, embeddedDictText, DICT_GZ_B64};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  ok(typeof api.DICT_GZ_B64 === 'string' && api.DICT_GZ_B64.length > 1000000,
    'словарь вшит в файл: ' + (api.DICT_GZ_B64.length / 1048576).toFixed(2) + ' МБ base64 (gzip)');
  const text = await api.embeddedDictText();
  const lines = text.split('\n').filter(l => l.trim());
  ok(lines.length === 487247, 'слов в словаре: ' + lines.length);
  ok(lines[0].startsWith('я ') && lines[0].split(' ')[1] === '5081568', 'первое слово по частоте: «' + lines[0] + '»');
  const md5 = crypto.createHash('md5').update(text, 'utf8').digest('hex');
  // Отпечаток эталонного словаря лежит в репозитории (tools/dict_md5.txt):
  // раньше тест тянул /home/user/lab/d_morph60.txt, то есть файл вне репозитория,
  // и на чужой машине просто падал с ENOENT.
  const wantPath = __dirname + '/tools/dict_md5.txt';
  const want = fs.existsSync(wantPath) ? fs.readFileSync(wantPath, 'utf8').trim() : '';
  ok(want.length === 32, 'эталонный отпечаток на месте: tools/dict_md5.txt');
  ok(md5 === want, 'разжатый словарь побайтово равен эталону (md5 ' + md5.slice(0, 8) + '…)');
  // Частотная часть не тронута: первые 250 000 строк — это ровно ru_250k
  const freqPart = lines.slice(0, 250000).join('\n') + '\n';
  const freqMd5 = crypto.createHash('md5').update(freqPart, 'utf8').digest('hex');
  const ruPath = __dirname + '/data/ru_250k.txt';
  const ruMd5 = crypto.createHash('md5').update(fs.readFileSync(ruPath, 'utf8'), 'utf8').digest('hex');
  ok(freqMd5 === ruMd5, 'первые 250 000 строк — тот же частотный список');
  // Словоформы стоят ПОСЛЕ частотного списка (поэтому «частыми» не считаются)
  ok(lines.indexOf('равнодушные') >= 250000, 'словоформа «равнодушные» есть: строка ' + lines.indexOf('равнодушные'));

  const ready = await api.Words.load();
  ok(ready === true && api.Words.source === 'вшит в файл', 'словарь подхватывается сам, без выбора файла');
  ok(api.Words.size === 487247, 'загружено слов: ' + api.Words.size);
  ok(api.Words.inDict('равнодушные') === true, 'словоформа «равнодушные» известна словарю');
  ok(api.Words.isKnown('равнодушные') === false, 'но «частой» не считается (порог по частоте цел)');
  ok(api.Words.finish('ПОШЕВЕАИТЬСЯ') === 'ПОШЕВЕЛИТЬСЯ', 'починка работает: ПОШЕВЕАИТЬСЯ → ' + api.Words.finish('ПОШЕВЕАИТЬСЯ'));
  ok(api.Words.polish('ол кослл алмчлс', 0.6) === '', 'мусорная строка отброшена');
  ok(api.Words.polish('УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ,', 0.6) !== '', 'настоящая реплика сохранена');
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.log('FATAL', e.message); process.exit(1); });
