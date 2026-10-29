// ДВИЖОК ЧТЕНИЯ: страница ↔ приложение (мост `KomaRead`).
//
// Зачем проверять: порядок реплик и склейка слов переехали в Kotlin
// (ReadEngine.kt). Ошибка там — это «читает не то и не в том порядке», то есть
// ровно та жалоба, с которой всё началось. Здесь закрепляется КОНТРАКТ:
//  • есть мост → страница берёт готовый план и НЕ пересортировывает его;
//  • нет моста (браузер) → работает прежний путь страницы;
//  • мост ответил мусором → тоже прежний путь, а не пустой текст;
//  • полосы приходят из приложения, но битый ответ не ломает чтение.
const fs = require('fs');
require('./shim.js');
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.indexedDB = undefined;
const el = () => ({ textContent: '', innerHTML: '', style: {}, dataset: {}, value: '', checked: false,
  classList: { contains: () => false, add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {}, closest() { return null; },
  getBoundingClientRect: () => ({ top: 0, bottom: 800, height: 800, left: 0, right: 700 }) });
global.document.getElementById = el;
global.document.querySelector = () => el();
global.document.querySelectorAll = () => [];
global.document.addEventListener = () => {};

const body = ['part0-wasm.js', 'part2.js', 'part3.js'].map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {NativeRead, bandsOf, sanitizeRules, readingOrder};')();
const { NativeRead } = api;

// ── 1. Браузера касается: моста нет — прежний путь
delete global.window.KomaRead;
ok(NativeRead.present() === false, 'без моста нативного движка чтения нет');
ok(NativeRead.plan([{ text: 'А', left: 0, top: 0, right: 1, bottom: 1 }], {}) === null,
  'без моста план не выдумывается');
ok(api.bandsOf(0.25, api.sanitizeRules({})).length > 1, 'полосы считаются по-старому, в странице');

// ── 2. Мост есть: план приходит из приложения как есть
let lastItems = null, lastRules = null;
global.window.KomaRead = {
  plan: (itemsJson, rulesJson) => {
    lastItems = JSON.parse(itemsJson);
    lastRules = JSON.parse(rulesJson);
    return JSON.stringify({ ok: true, replicas: [
      { text: 'НЕ УВЕРЕН, КАК СТОИТ СКАЗАТЬ ЭТО, НО...', left: 0.58, top: 0.22, right: 0.86, bottom: 0.33 },
      { text: 'УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ', left: 0.14, top: 0.10, right: 0.45, bottom: 0.29 },
      { text: 'В БУДУЩЕМ, КОГДА ВЫ БУДЕТЕ ГОВОРИТЬ', left: 0.14, top: 0.62, right: 0.47, bottom: 0.77 },
    ] });
  },
  bands: (h, f, r) => JSON.stringify([
    { index: 0, top: 0, bottom: 0.25, whole: false },
    { index: 1, top: 0.25, bottom: 0.5, whole: false },
  ]),
};
ok(NativeRead.present() === true, 'мост виден странице');
const items = [
  { text: 'УЖЕ ПОРА НА-', left: 0.14, top: 0.10, right: 0.42, bottom: 0.13, confidence: 0.9 },
  { text: 'ЧИНАТЬ ВСТРЕЧУ,', left: 0.14, top: 0.14, right: 0.44, bottom: 0.17, confidence: 0.9 },
];
const plan = NativeRead.plan(items, api.sanitizeRules({}));
ok(Array.isArray(plan) && plan.length === 3, 'план из приложения принят: ' + (plan && plan.length) + ' реплики');
ok(plan[0].text.startsWith('НЕ УВЕРЕН'), 'порядок приложения НЕ пересортировывается страницей');
ok(lastItems && lastItems.length === 2 && lastItems[0].text === 'УЖЕ ПОРА НА-', 'строки уходят в приложение целиком');
ok(lastRules && lastRules.dir === 'rtl', 'направление чтения передаётся (dir=rtl)');

// ── 3. Полосы из приложения
const nb = api.bandsOf(0.25, api.sanitizeRules({}));
ok(nb.length === 2 && nb[1].top === 0.25, 'полосы пришли из приложения');

// ── 4. Мусор от моста не ломает чтение
global.window.KomaRead.plan = () => 'не json';
ok(NativeRead.plan(items, {}) === null, 'битый ответ плана → страница считает сама');
global.window.KomaRead.bands = () => '{}';
ok(api.bandsOf(0.25, api.sanitizeRules({})).length > 1, 'битые полосы → считается по-старому');
global.window.KomaRead.plan = () => JSON.stringify({ ok: false, error: 'движок не смог' });
ok(NativeRead.plan(items, {}) === null, 'ok:false — тоже честный откат, без исключения');

// ── 5. Страница умеет брать готовый план (в scanPage)
const p4 = fs.readFileSync(__dirname + '/part4.js', 'utf8');
ok(/res\.plan === 'native'/.test(p4) && /res\.replicas/.test(p4),
  'scanPage использует готовые реплики, когда их собрало приложение');
ok(/Words\.polish/.test(p4) && /OCR\.readPlan/.test(p4),
  'словарь остаётся в странице, а откуда план — видно в состоянии');

// ── 6. Котлы на другой стороне: имена и файлы
const eng = fs.readFileSync(__dirname + '/apk/app/src/main/java/net/koma/reader/ReadEngine.kt', 'utf8');
const br = fs.readFileSync(__dirname + '/apk/app/src/main/java/net/koma/reader/KomaReadBridge.kt', 'utf8');
const main = fs.readFileSync(__dirname + '/apk/app/src/main/java/net/koma/reader/MainActivity.kt', 'utf8');
ok(/KomaRead/.test(main), 'мост зарегистрирован под именем KomaRead');
ok(/fun plan\(/.test(br) && /fun bands\(/.test(br), 'в мосте есть план и полосы');
ok(/sameBubble|absorbOrphans|orderBubbles/.test(eng) || /mergeBubbles/.test(eng) || /private fun sameBubble/.test(eng),
  'в движке есть склейка облачков и порядок реплик');
ok(fs.existsSync(__dirname + '/apk/tools/readtest/run.sh'), 'движок можно прогнать без Android: apk/tools/readtest/run.sh');

console.log(process.exitCode ? 'ЕСТЬ ПАДЕНИЯ' : 'ALL PASSED');
process.exit(process.exitCode || 0);
