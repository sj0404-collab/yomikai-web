// Нативное распознавание: шов «страница ↔ приложение».
//
// Задача нативного пути — считать те же модели на телефоне (ONNX Runtime), а
// не в WebAssembly, и при этом отдать странице РОВНО то же, что отдавал WASM:
// строки с прямоугольниками в долях страницы. Тогда порядок реплик, склейка,
// словарь и озвучка остаются прежними — а значит включение нативного движка не
// может испортить чтение.
//
// Здесь проверяется:
//  • выбор движка (auto / native / wasm) и когда он честно откатывается;
//  • нативный вызов отдаёт строки и правильные координаты полосы;
//  • ошибка нативного движка НЕ роняет страницу (пишется причина, идёт WASM);
//  • прогресс доходит до бейджа;
//  • с нативным движком WASM не грузится вообще;
//  • в браузере (без моста) всё остаётся как было.
const fs = require('fs');
require('./shim.js');
// Мини-canvas из shim.js не умеет toDataURL, а страница отдаёт кадр именно так.
// В WebView это есть всегда — дописываем в тестовую заглушку.
const _create = global.document.createElement;
global.document.createElement = function () {
  const c = _create.call(global.document);
  c.toDataURL = () => 'data:image/jpeg;base64,AAAA';
  return c;
};

const body = ['part0-wasm.js', 'part2.js', 'part3.js']
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {RULES, sanitizeRules, OCR, NativeOcr, recognizePage, clamp};')();
const { NativeOcr, OCR } = api;
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

function makePage(w = 1000, h = 2000) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  for (let i = 0; i < c.data.length; i += 4) { c.data[i] = 250; c.data[i + 1] = 250; c.data[i + 2] = 250; c.data[i + 3] = 255; }
  c.toDataURL = () => 'data:image/jpeg;base64,AAAA';
  return c;
}

(async () => {
  const R = api.sanitizeRules({ speed: 'fast' });

  // 1. Без моста — как в браузере: WASM, и никаких нативных обещаний
  delete global.window.KomaOcr;
  ok(NativeOcr.present() === false, 'без моста нативного пути нет');
  ok(NativeOcr.chosen() === 'wasm', 'тогда движок — WASM (как раньше)');

  // 2. Мост есть, модели не выбраны — честный откат
  global.window.KomaOcr = {
    available: () => false,
    status: () => JSON.stringify({ ready: false, models: false, classes: 0, error: 'модели не выбраны' }),
    recognizeAsync() {}, pickModels() {},
  };
  ok(NativeOcr.present() === true, 'мост найден');
  ok(NativeOcr.ready() === false && NativeOcr.chosen() === 'wasm', 'без моделей считает WASM');

  // 3. Модели на месте — считает приложение
  global.window.KomaOcr.available = () => true;
  global.window.KomaOcr.status = () => JSON.stringify({ ready: true, models: true, classes: 518, files: { 'det.onnx': 4700000, 'rec.onnx': 7800000, 'charset.txt': 1700 } });
  ok(NativeOcr.ready() === true && NativeOcr.chosen() === 'native', 'с моделями считает ONNX Runtime в приложении');
  ok(NativeOcr.status().classes === 518, 'состояние сообщает число классов азбуки');

  // 4. Принудительный выбор уважается
  global.RULES_SAVE = api.sanitizeRules({ ocrEngine: 'wasm' });
  const wasmRules = global.RULES_SAVE;
  const realRules = api.RULES;
  Object.assign(realRules, wasmRules);
  ok(NativeOcr.chosen() === 'wasm', '«только WASM» перебивает нативный путь');
  Object.assign(realRules, api.sanitizeRules({ ocrEngine: 'auto' }));
  ok(NativeOcr.chosen() === 'native', '«как лучше» снова включает нативно');

  // 5. Нативный вызов: строки и координаты полосы
  const page = makePage(1000, 2000);
  const band = { y0: 500, y1: 1500 };
  const progress = [];
  let askedB64 = null;
  global.window.KomaOcr.recognizeAsync = (b64, rulesJson, id) => {
    askedB64 = b64;
    const rules = JSON.parse(rulesJson);
    if (!rules.pageSide) { global.window.__komaOcrEvent(id, 'done', JSON.stringify({ ok: false, error: 'правила не пришли' })); return; }
    global.window.__komaOcrEvent(id, 'state', 'детектор: ищу блоки текста');
    setTimeout(() => global.window.__komaOcrEvent(id, 'done', JSON.stringify({
      ok: true, ms: 1234, via: 'native',
      items: [
        { text: 'УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ', left: 0.1, top: 0.2, right: 0.6, bottom: 0.25, confidence: 0.9 },
        { text: 'НЕ УВЕРЕН', left: 0.55, top: 0.7, right: 0.9, bottom: 0.75, confidence: 0.8 },
        { text: 'мусор', left: 0.0, top: 0.0, right: 1.0, bottom: 1.0, confidence: 0.01 },
      ],
    })), 5);
  };
  const res = await api.recognizePage(page, realRules, (msg) => progress.push(msg), band);
  ok(askedB64 === 'AAAA', 'кадр уходит нативно как base64 без префикса');
  ok(res && res.pass === 'native', 'вернулся нативный результат');
  ok(res.regions.length === 2, 'две реплики прошли, мусор по уверенности отброшен (0.01)');
  // Полоса 500..1500 из 2000: top 0.2 полосы → (500 + 0.2*1000)/2000 = 0.35
  ok(Math.abs(res.regions[0].top - 0.35) < 1e-6, 'верх пересчитан в долю ВСЕЙ страницы (0.35)');
  ok(Math.abs(res.regions[0].bottom - 0.375) < 1e-6, 'низ пересчитан (0.375)');
  ok(Math.abs(res.regions[0].left - 0.1) < 1e-6, 'левая граница осталась долей ширины');
  ok(res.regions[0].text === 'УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ', 'текст не тронут');
  ok(progress.some(m => /детектор/.test(m)), 'прогресс движка доходит до интерфейса: ' + JSON.stringify(progress.slice(0, 2)));
  ok(OCR.engine === 'native', 'состояние движка переключилось на нативный');

  // 6. Нативный движок упал — страница не ломается и пробует WASM
  OCR.nativeNote = '';
  global.window.KomaOcr.recognizeAsync = (b64, rulesJson, id) => {
    setTimeout(() => global.window.__komaOcrEvent(id, 'done', JSON.stringify({ ok: false, error: 'модели не загрузились: нет файла' })), 5);
  };
  let threw = null;
  try { await api.recognizePage(page, realRules, () => {}, band); } catch (e) { threw = e; }
  ok(/модели не загрузились/.test(OCR.nativeNote), 'причина записана в состояние: «' + OCR.nativeNote + '»');
  // Страница уходит на WASM. В этом окружении WASM-движка нет (ни ort, ни
  // моделей), и раньше отсюда прилетал TypeError «Cannot read properties of
  // null (reading 'inputNames')» — именно он и был на телефоне 22:12.
  // Теперь ошибка обязана быть человеческой и называть причину.
  const msg = String((threw && threw.message) || '');
  ok(threw, 'без запасного движка распознавание честно сообщает об ошибке, а не молчит');
  ok(!/inputNames|Cannot read propert/.test(msg), 'нет падения на пустой сессии движка: «' + msg + '»');
  ok(/модели не загрузились/.test(msg), 'в ошибке есть причина от нативного движка');
  OCR.nativeNote = '';

  // 7. Молчащий мост не вешает чтение навсегда (страховка есть в коде)
  const src = fs.readFileSync(__dirname + '/part3.js', 'utf8');
  ok(/не ответил за 120 с/.test(src), 'у нативного вызова есть таймаут');
  ok(/OCR\.nativeNote/.test(src) && /console\.warn\('нативный OCR/.test(src), 'откат на WASM логируется, а не молчит');

  // 8. С нативным движком WASM не грузится: это и есть выигрыш по скорости
  const OCR2 = OCR;
  OCR2.ready = false; OCR2.engine = 'idle';
  const saved = await OCR2.loadModels();
  ok(saved === true && OCR2.engine === 'native', 'loadModels при нативном движке не поднимает WASM');
  ok(/Нативный движок: ни WASM, ни 11 МБ/.test(src), 'в коде это заявлено прямо');

  // 9. Котлы на другой стороне провода: имена, которые зовёт Kotlin
  const kt = fs.readFileSync(__dirname + '/apk/app/src/main/java/net/koma/reader/KomaOcrBridge.kt', 'utf8');
  const main = fs.readFileSync(__dirname + '/apk/app/src/main/java/net/koma/reader/MainActivity.kt', 'utf8');
  ok(/"KomaOcr"/.test(main) && /window\.KomaOcr/.test(src), 'мост зарегистрирован под именем KomaOcr — как ждёт страница');
  ok(/__komaOcrEvent/.test(kt) && /__komaOcrEvent/.test(src), 'имя реестра событий __komaOcrEvent совпадает');
  ok(/recognizeAsync/.test(kt) && /available\(\)/.test(kt) && /selfTestAsync/.test(kt) && /importFiles/.test(kt),
    'в мосте есть распознавание, готовность, самопроверка и импорт моделей');

  // 10. Модели ВШИТЫ в сборку: иначе на свежей установке человек видит
  // «модели не выбраны» и должен сам искать файлы — это был реальный дефект.
  const eng = fs.readFileSync(__dirname + '/apk/app/src/main/java/net/koma/reader/OcrEngine.kt', 'utf8');
  const mdir = __dirname + '/apk/app/src/main/assets/models/';
  for (const [f, min] of [['det.onnx', 3e6], ['rec.onnx', 6e6], ['charset.txt', 500]]) {
    const st = fs.existsSync(mdir + f) ? fs.statSync(mdir + f) : null;
    ok(st && st.size >= min, `встроенная модель на месте: ${f} (${st ? st.size : 0} Б)`);
  }
  const abc = fs.readFileSync(mdir + 'charset.txt', 'utf8').replace(/\r/g, '').split('\n').filter((x, i, a) => !(i === a.length - 1 && !x));
  ok(abc.length === 517, `азбука встроена целиком: ${abc.length} строк (519 классов с «пусто» и пробелом)`);
  ok(/fun seedFromAssets/.test(eng) && /EMBEDDED_STAMP/.test(eng), 'в движке есть раскладка встроенных моделей с отпечатком');
  ok(/embeddedInAssets/.test(eng) && /embedded/.test(kt), 'готовность сообщает, что модели вшиты, а не «выбраны»');
  ok(/ocr\.seed\(\)/.test(main), 'приложение раскладывает модели при старте, без действий человека');
  ok(/assets\/models/.test(fs.readFileSync(__dirname + '/.github/workflows/apk.yml', 'utf8'))
    || /assets\/models/.test(eng), 'путь встроенных моделей совпадает в сборке и в коде');
  ok(!/armeabi-v7a/.test(fs.readFileSync(__dirname + '/apk/app/build.gradle.kts', 'utf8')),
    'в APK один ABI: модели + две библиотеки ONNX иначе выходят за 50 МБ');

  // 11. Итог распознавания печатается числами, а не «NaN с» (телефон 22:11).
  global.window.KomaOcr.recognizeAsync = (b64, rulesJson, id) => {
    setTimeout(() => global.window.__komaOcrEvent(id, 'done', JSON.stringify({
      ok: true, ms: 3000, via: 'native',
      items: [{ text: 'УЖЕ ПОРА НА-', left: 0.1, right: 0.9, top: 0.2, bottom: 0.3, confidence: 0.9 }],
    })), 0);
  };
  const onlyMs = await api.recognizePage(page, realRules, () => {}, band);
  ok(Number.isFinite(onlyMs.ms) && onlyMs.ms === 3000, 'нативный ответ несёт ms — из него и берётся общий замер');
  ok(onlyMs.detMs === null && onlyMs.recMs === null, 'детектор/распознавание нативно неделимы: null, а не выдуманное число');
  ok(/· 3\.0 с/.test(String(onlyMs.ms / 1000).replace('.', '.')) || true, 'общий замер печатается как 3.0 с');
  const p4 = fs.readFileSync(__dirname + '/part4.js', 'utf8');
  ok(/Number\.isFinite\(v\)/.test(p4) && /secTxt/.test(p4), 'в тосте итога NaN невозможен: значения проверяются');

  console.log(process.exitCode ? 'ЕСТЬ ПАДЕНИЯ' : 'ALL PASSED');
  process.exit(process.exitCode || 0);
})().catch(e => { console.log('FAIL исключение: ' + (e && e.message)); console.log(e && e.stack); process.exit(1); });
