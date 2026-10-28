// Чтение по полосам: порядок «распознать → прокрутить → прочитать».
//
// Что случилось на телефоне 28.10 (скриншоты 22:11–22:12) и что здесь
// закрепляется тестом:
//  1. «Полоса 1 распознана … · NaN с» — нативный проход не заполнял ms.
//  2. «Cannot read properties of null (reading 'inputNames')» — движок выбран
//     нативный, WASM-сессий нет, нативный проход не дал текста, и код шёл в
//     детектор с пустой сессией.
//  3. «Резко скролит и не читает, читает спустя несколько прокруток» — экран
//     прокручивался к полосе ДО её распознавания, полоса оказывалась пустой,
//     и лента прыгала дальше.
//  4. «Где рамки делись» — настройка рамок жила в памяти и сбрасывалась.
//  5. «Система не дала ни одного голоса» — пустой список голосов кэшировался
//     навсегда, хотя Android TTS ещё инициализировался.
const fs = require('fs');
require('./shim.js');
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.indexedDB = undefined;
const el = () => ({ textContent: '', innerHTML: '', style: {}, dataset: {}, value: '', checked: false,
  classList: { contains: () => false, add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {}, closest() { return null; }, scrollTo() {},
  offsetTop: 0, clientHeight: 800,
  getBoundingClientRect: () => ({ top: 0, bottom: 800, height: 800, left: 0, right: 700 }) });
global.document.getElementById = el;
global.document.querySelector = () => el();
global.document.querySelectorAll = () => [];
global.document.addEventListener = () => {};

const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js']
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {RULES, sanitizeRules, DEFAULT_RULES, Reader, TTS, VOICE, State, OCR, bandsOf, clamp};')();
const { Reader, VOICE, State, OCR, bandsOf, TTS } = api;

(async () => {
  // ── 1. Рамки: в правилах, по умолчанию включены, восстанавливаются
  ok(api.DEFAULT_RULES.frames === true, 'рамки включены по умолчанию (а не выключены молча)');
  ok(api.sanitizeRules({}).frames === true, 'без сохранённых правил рамки тоже включены');
  ok(api.sanitizeRules({ frames: false }).frames === false, 'выключенные человеком рамки уважаются');
  const p5 = fs.readFileSync(__dirname + '/part5.js', 'utf8');
  ok(/Reader\.frames = RULES\.frames !== false/.test(p5), 'при запуске рамки берутся из правил');
  ok(/RULES\.frames = Reader\.frames;[\s\S]{0,220}saveRules\(\)/.test(p5), 'переключение рамок сохраняется, а не живёт до перезапуска');

  // ── 2. Голоса: пустой ответ не прибивается кэшем навсегда
  global.window.speechSynthesis = undefined;
  let fakeVoices = [];
  global.window.KomaSpeech = {
    speak() { return true; },
    cancel() {},
    status() { return JSON.stringify({ ready: false }); },
    voices() { return JSON.stringify(fakeVoices); },
  };
  ok(VOICE.native() === true, 'нативный голос виден по мосту');
  ok(VOICE.voices().length === 0, 'пока TTS не готов — список пуст');
  fakeVoices = [{ name: 'ru-RU-x', lang: 'ru-RU', voiceURI: 'native:ru' }];
  ok(VOICE.voices().length === 1, 'как только движок отдал голоса — они появляются (кэш не залип на пустом)');
  const p4 = fs.readFileSync(__dirname + '/part4.js', 'utf8');
  ok(/_voiceTries/.test(p4) && /VOICE\.nativeReady\(\) === false/.test(p4),
    'пока TTS просыпается, страница ждёт и повторяет, а не кричит «нет голосов»');
  const kt = fs.readFileSync(__dirname + '/apk/app/src/main/java/net/koma/reader/KomaSpeechBridge.kt', 'utf8');
  ok(/Системный голос Android/.test(kt), 'мост отдаёт системный голос, когда движок список не дал');

  // ── 3. Полосы: пиксели и «уже распознана»
  const canvas = document.createElement('canvas');
  canvas.width = 800; canvas.height = 4000;
  Reader.canvases = { 0: canvas };
  Reader.pages = [{}, {}];
  const bands = bandsOf(0.25, api.sanitizeRules({}));
  Reader.bands = bands;
  const px = Reader.bandPx(0, bands[1]);
  ok(px && px.y0 >= 0 && px.y1 > px.y0, 'полоса переводится в пиксели кадра: ' + JSON.stringify(px));
  Reader.regions = new Map();
  Reader.bandCache = new Map();
  ok(Reader.bandScanned(0, bands[1]) === false, 'нечего не распознано — полоса не считается готовой');
  Reader.bandCache.set(0, new Map([['k', { res: { band: { y0: px.y0, y1: px.y1 } }, lines: [] }]]));
  ok(Reader.bandScanned(0, bands[1]) === true, 'совпадающая полоса в кэше считается распознанной');

  // ── 4. Порядок и отсутствие пустых прокруток
  const calls = [];
  Reader.regions = new Map();
  Reader.bandCache = new Map();
  Reader.page = 0; Reader.bandIndex = 0; Reader.stopped = false;
  Reader.waitIdle = async () => {};
  Reader.ensureLoaded = async () => {};
  TTS.stopped = false;
  // Полоса 1 — пустая (сканируется, текста нет), полоса 2 — с текстом.
  Reader.scanPage = async (i, opts) => { calls.push('scan:' + (opts && opts.bandPx ? 'px' : 'vis')); return null; };
  // Прокрутка теперь не дёргает ленту каждый переход, а проверяет, видно ли
  // реплику. Считаем вызовы отдельно: сколько раз лента реально поехала.
  const realScrollToLine = Reader.scrollToLineIfNeeded;
  Reader.scrollToLineIfNeeded = (i, line) => { calls.push('scroll'); return true; };
  TTS.readQueue = (un) => { calls.push('read:' + un.length); };
  TTS.stop = () => { calls.push('stop'); };
  TTS.queue = []; TTS.idx = 0;
  let bandNo = 0;
  Reader.unspokenInBand = () => {
    // Первый вызов (полоса 1) — пусто, второй (полоса 2) — одна реплика.
    bandNo++;
    return bandNo >= 2 ? [{ text: 'ВАШЕ ПРЕВОСХОДИТЕЛЬСТВО,', top: 0.3, bottom: 0.4, left: 0.1, right: 0.9 }] : [];
  };
  await TTS.advanceReading();
  const scrolls = calls.filter(c => c.startsWith('scroll')).length;
  const firstRead = calls.indexOf('read:1');
  const lastScroll = calls.map((c, i) => c.startsWith('scroll') ? i : -1).filter(i => i >= 0).pop();
  ok(scrolls === 1, 'лента прокрутилась РОВНО один раз, а не прыгала по пустым полосам: ' + calls.join(' → '));
  ok(lastScroll >= 0 && firstRead > lastScroll, 'прокрутка стоит перед чтением найденной полосы: ' + calls.join(' → '));
  ok(calls.filter(c => c === 'scan:px').length >= 1, 'полоса распознаётся ДО прокрутки (явная полоса, а не «что видно»)');
  ok(calls.indexOf('scan:px') < calls.indexOf('scroll'), 'порядок именно «распознать → прокрутить», иначе экран прыгает в пустоту');

  // ── 5. Откат на WASM без сессий — человеческая ошибка, а не падение
  const p3 = fs.readFileSync(__dirname + '/part3.js', 'utf8');
  ok(/Cannot read properties of null/.test(p3) && /if \(!OCR\.det \|\| !OCR\.rec\)/.test(p3),
    'перед запасным путём проверяется, что сессии движка живые');
  ok(/loadModels\(\{ wasm: true \}\)/.test(p3), 'запасной путь поднимается осознанно, а не предполагается');
  ok(/повтор с мягким порогом/.test(p3), 'если нативный проход дал 0 строк — есть один повтор с мягким порогом');

  // ── 6. Предраспознавание следующей полосы во время речи
  ok(/prefetchBandAhead/.test(p4) && /Reader\.prefetchBandAhead\(\)/.test(p4),
    'следующая полоса распознаётся, пока звучит текущая реплика');

  // ── 7. Явное нажатие ▶ читает С НАЧАЛА, а не с «места, где закончил»
  const RW = Reader;
  RW.spoken = new Set([RW.spokenKey(RW.page, 'ПЕРВАЯ РЕПЛИКА')]);
  RW.regions.set(RW.page, { lines: [
    { text: 'ПЕРВАЯ РЕПЛИКА', top: 0.05, bottom: 0.15 },
    { text: 'ВТОРАЯ РЕПЛИКА', top: 0.06, bottom: 0.16 },
  ] });
  RW.band = { index: 0, top: 0, bottom: 0.5 };
  TTS.queue = []; TTS.idx = 0; TTS.stopped = true;
  let queued = null;
  const saveStep = TTS.step; TTS.step = () => { queued = TTS.queue.map(l => l.text); };
  const savePause = TTS.speakLine; TTS.speakLine = () => {};
  RW.prefetchNext = () => {};
  await TTS.readVisible({ fromStart: true });
  ok(queued && queued.includes('ПЕРВАЯ РЕПЛИКА'),
    'по нажатию ▶ читается и уже прочитанная реплика: ' + JSON.stringify(queued));
  TTS.step = saveStep; TTS.speakLine = savePause;

  // ── 8. Прокрутка не дёргается, если реплика уже на экране
  const scroller = { clientHeight: 800, scrollTop: 100, _to: null,
    scrollTo(o) { this._to = o.top; }, addEventListener() {} };
  const wrap = { offsetTop: 0, getBoundingClientRect: () => ({ height: 3000, top: 0 }) };
  global.document.getElementById = (id) => (id === 'strip' ? scroller : el());
  global.document.querySelector = (sel) => (String(sel).includes('strip') ? scroller : wrap);
  RW.mode = 'vertical';
  RW.pageRect = () => ({ height: 3000 });
  RW.scrollToLineIfNeeded = realScrollToLine;      // вернуть настоящую логику
  ok(RW.scrollToLineIfNeeded(0, { top: 0.1 }) === false, 'реплика уже видна — лента не двигается (нет «ерзания»)');
  ok(RW.scrollToLineIfNeeded(0, { top: 0.9 }) === true, 'реплика за экраном — лента переезжает один раз');

  console.log(process.exitCode ? 'ЕСТЬ ПАДЕНИЯ' : 'ALL PASSED');
  process.exit(process.exitCode || 0);
})().catch(e => { console.log('FAIL исключение: ' + (e && e.message)); console.log(e && e.stack); process.exit(1); });
