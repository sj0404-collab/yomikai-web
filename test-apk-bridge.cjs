// Мост АПК ↔ читалка: контракт window.KomaLens.
//
// Проверяем шов между Kotlin и JS без телефона: страница должна
//  • увидеть движок АПК (transports → native);
//  • предпочесть асинхронный вызов и получить строки;
//  • показать ошибку моста ТЕКСТОМ, а не «ответ пустой»;
//  • пережить молчащий мост (таймаут) и уметь синхронный вызов;
//  • и совпадать по ИМЕНАМ с тем, что зовёт Kotlin (__komaLensResolve).
const fs = require('fs');
require('./shim.js');
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.indexedDB = undefined;
const el = () => ({ textContent: '', innerHTML: '', style: {}, value: '', checked: false,
  classList: { contains: () => false, add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {} });
global.document.getElementById = el;
global.document.querySelector = () => el();
global.document.querySelectorAll = () => [];

const body = ['part0-wasm.js', 'part2.js', 'part3.js']
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {RULES, LENS};')();
const { LENS } = api;

const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };
const canvas = { width: 120, height: 80, toDataURL: () => 'data:image/jpeg;base64,AAAAAAAA' };
const realTimeout = global.setTimeout;

async function run() {
  // 1. Без моста прямой путь честно недоступен
  delete global.window.KomaLens;
  ok(LENS.transports().length === 0, 'без моста транспортов нет — движок «в файле»');
  const noBridge = await LENS.recognizeDirect(canvas, { force: true });
  ok(noBridge.ok === false && /доступен/.test(noBridge.reason), 'без моста честный отказ, а не пустой ответ');

  // 2. Асинхронный мост: строки приходят через __komaLensResolve
  let seenId = null, seenOpts = null;
  global.window.KomaLens = {
    recognizeAsync(b64, optsJson, id) {
      seenId = id; seenOpts = optsJson;
      ok(b64 === 'AAAAAAAA', 'мост получил base64 кадра без префикса data:');
      realTimeout(() => global.window.__komaLensResolve[id](JSON.stringify({ lines: ['Первая реплика', 'Вторая'], ms: 900 })),
        5);
    },
  };
  ok(LENS.transports()[0] === 'native', 'мост виден как транспорт native');
  const good = await LENS.recognizeDirect(canvas, { force: true });
  ok(good.ok === true && good.via === 'native' && good.lines.length === 2, 'асинхронный мост вернул 2 реплики');
  ok(good.lines[0] === 'Первая реплика', 'порядок строк сохранён');
  ok(seenId && typeof seenId === 'string', 'идентификатор вызова передан в мост');
  ok(/lang/.test(seenOpts || ''), 'язык передан в опции моста');
  ok(global.window.__komaLensResolve[seenId] === undefined, 'запись реестра удалена после ответа');

  // 3. Ошибка моста — текстом
  global.window.KomaLens = {
    recognizeAsync(b64, o, id) {
      realTimeout(() => global.window.__komaLensResolve[id](
        JSON.stringify({ error: 'Google вернул страницу «включите JavaScript» (антибот)' })), 5);
    },
  };
  const bad = await LENS.recognizeDirect(canvas, { force: true });
  ok(bad.ok === false && /антибот/.test(bad.reason), 'ошибка моста доходит до человека как есть: «' + bad.reason + '»');

  // 4. Молчащий мост — таймаут, и страница не висит вечно
  global.setTimeout = (fn) => { fn(); return 0; };   // подменяем таймер: срабатывает сразу
  global.window.KomaLens = { recognizeAsync() { /* молчит */ } };
  const silent = await LENS.recognizeDirect(canvas, { force: true });
  global.setTimeout = realTimeout;
  ok(silent.ok === false && /60 с/.test(silent.reason), 'молчащий мост даёт понятный таймаут');

  // 5. Старый синхронный мост тоже работает
  global.window.KomaLens = { recognize: () => JSON.stringify({ lines: ['Третья'] }) };
  const sync = await LENS.recognizeDirect(canvas, { force: true });
  ok(sync.ok === true && sync.lines.length === 1 && sync.lines[0] === 'Третья', 'синхронный мост recognize тоже поддержан');

  // 6. Имена на другом конце провода: то, что зовёт Kotlin, есть в странице
  const kt = fs.readFileSync(__dirname + '/apk/app/src/main/java/net/koma/reader/KomaLensBridge.kt', 'utf8');
  const main = fs.readFileSync(__dirname + '/apk/app/src/main/java/net/koma/reader/MainActivity.kt', 'utf8');
  ok(/__komaLensResolve/.test(kt) && /__komaLensResolve/.test(fs.readFileSync(__dirname + '/part3.js', 'utf8')),
    'имя реестра __komaLensResolve совпадает в Kotlin и в странице');
  ok(/"KomaLens"/.test(main) && /window\.KomaLens/.test(fs.readFileSync(__dirname + '/part3.js', 'utf8')),
    'мост зарегистрирован под именем KomaLens — как ждёт страница');
  ok(/recognizeAsync/.test(kt) && /fun recognize\(/.test(kt), 'в мосте есть и async, и синхронный вызов');
  ok(/addJavascriptInterface\(KomaLensBridge/.test(main), 'мост подключён в WebView');
  ok(/addJavascriptInterface\([^)]*"KomaApp"\)/.test(main) || /"KomaApp"/.test(main), 'мост приложения (обновление) подключён');
}

run()
  .catch(e => { console.log('FAIL исключение: ' + e.message); process.exitCode = 1; })
  .then(() => console.log(process.exitCode ? 'ЕСТЬ ПАДЕНИЯ' : 'ALL PASSED'));
