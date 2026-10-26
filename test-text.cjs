// Порядок чтения и починка текста — по мотивам KomaAutoRead.kt / KomaText.kt.
const fs = require('fs');
require('./shim.js');
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.document.addEventListener = () => {};
const body = require('./koma-src.cjs').app;
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {cleanSpeech, readingOrder, bubblesOf, DEFAULT_RULES, sanitizeRules, joinBubbleText};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };
const R = api.sanitizeRules(api.DEFAULT_RULES);

// 1. Починка текста
ok(api.cleanSpeech('3ВУ4ИТ') === 'ЗВУЧИТ', 'цифры-двойники: 3ВУ4ИТ → ' + api.cleanSpeech('3ВУ4ИТ'));
ok(api.cleanSpeech('HETΛOXO') === 'НЕТЛОХО', 'греческие: HETΛOXO → ' + api.cleanSpeech('HETΛOXO'));
ok(api.cleanSpeech('MHE TAK') === 'МНЕ ТАК', 'латиница: MHE TAK → ' + api.cleanSpeech('MHE TAK'));
ok(api.cleanSpeech('ВЫСО- ЧЕСТВО') === 'ВЫСОЧЕСТВО', 'перенос: ' + api.cleanSpeech('ВЫСО- ЧЕСТВО'));
ok(api.cleanSpeech('в д а ль') === 'вда ль', 'цепочка букв (как в KomaText): ' + api.cleanSpeech('в д а ль'));

// 2. Два облачка друг под другом: строки внутри склеиваются, перенос убирается
const reg = (text, l, t, r, b) => ({ text, left: l, top: t, right: r, bottom: b, confidence: 1 });
const page = [
  reg('ЛУЧШЕ БЫТЬ БОЛЕЕ РАВНО-', 0.10, 0.10, 0.55, 0.13),
  reg('ДУШНЫМ.', 0.10, 0.14, 0.40, 0.17),        // та же реплика, ниже
  reg('НО РАЗВЕ', 0.10, 0.40, 0.45, 0.43),       // отдельная реплика ниже
];
const rtl = api.readingOrder(page, true, true, R);
ok(rtl.length === 2, 'две реплики из трёх строк: ' + rtl.length);
ok(rtl[0].text === 'ЛУЧШЕ БЫТЬ БОЛЕЕ РАВНОДУШНЫМ.', 'перенос слова склеен: «' + rtl[0].text + '»');
ok(rtl[1].text === 'НО РАЗВЕ', 'вторая реплика: «' + rtl[1].text + '»');

// 3. Направление: две реплики в один ряд — порядок зависит от dir
const row = [
  reg('ПРАВАЯ РЕПЛИКА', 0.55, 0.50, 0.95, 0.54),
  reg('ЛЕВАЯ РЕПЛИКА', 0.05, 0.51, 0.45, 0.55),
];
const a = api.readingOrder(row, true, true, R);
const b = api.readingOrder(row, false, true, R);
ok(a[0].text === 'ПРАВАЯ РЕПЛИКА', 'справа налево: первой идёт правая — «' + a[0].text + '»');
ok(b[0].text === 'ЛЕВАЯ РЕПЛИКА', 'слева направо: первой идёт левая — «' + b[0].text + '»');
console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
