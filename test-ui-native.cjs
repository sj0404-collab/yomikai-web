// ИНТЕРФЕЙС ЧТЕНИЯ В АПК + плавность прокрутки.
//
// Жалоба 28.10: «не плавное авточтение, резко дёрнулся, потом ещё дважды,
// прочитал всего одну реплику». Причин было две, и обе проверяются здесь:
//  1) за ленту спорили ТРИ независимых smooth-прокрутки — теперь один твин;
//  2) панель чтения жила в HTML поверх ленты и пересчитывалась на каждой
//     реплике — теперь в АПК панель нативная, под страницей.
const fs = require('fs');
require('./shim.js');
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.indexedDB = undefined;
const els = new Map();
const el = (id) => {
  if (!els.has(id)) els.set(id, {
    id, textContent: '', innerHTML: '', value: '', checked: false, style: {}, dataset: {}, disabled: false,
    scrollTop: 0, clientHeight: 800,
    classList: { s: new Set(), add(c) { this.s.add(c); }, remove(c) { this.s.delete(c); }, contains(c) { return this.s.has(c); }, toggle() {} },
    addEventListener() {}, appendChild() {}, closest() { return null; }, querySelector() { return null; },
    getBoundingClientRect: () => ({ top: 0, bottom: 800, height: 800, left: 0, right: 700 }),
    scrollTo(o) { if (o && typeof o.top === 'number') this.scrollTop = o.top; },
    scrollBy(o) { if (o && o.top) this.scrollTop += o.top; },
  });
  return els.get(id);
};
global.document.getElementById = el;
global.document.querySelector = (sel) => (String(sel) === '#strip' ? el('strip') : el(String(sel).replace(/^[#.]/, '').slice(0, 24)));
global.document.querySelectorAll = () => [];
global.document.addEventListener = () => {};
global.document.body = el('body');
global.ort = { env: { wasm: {} }, Tensor: class { constructor(t, d, dims) { this.data = d; this.dims = dims; } } };

const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Reader, TTS, State, SMOOTH, NATIVE_UI, VOICE, sanitizeRules, getRules: () => RULES};')();
const { Reader: R, TTS: T, SMOOTH, NATIVE_UI } = api;

// Лента и страница — как в жизни: полоса на экран, облачко внизу.
const strip = el('strip');
global.document.querySelector = (sel) => String(sel).includes('pagewrap')
  ? { getBoundingClientRect: () => ({ top: 0, bottom: 800, height: 800, left: 0, right: 700 }) }
  : el(String(sel).replace(/^[#.]/, '').slice(0, 24));

function resetReader() {
  R.book = { id: 'b' }; R.pages = [{}, {}]; R.page = 0; R.mode = 'vertical';
  R.canvases = [{ width: 700, height: 900 }, { width: 700, height: 900 }];
  R.bands = [{ index: 0, top: 0, bottom: 0.5 }, { index: 1, top: 0.5, bottom: 1 }];
  R.bandIndex = 0; R.band = R.bands[0];
  R.regions = new Map(); R.bandCache = new Map(); R.spoken = new Set();
  R.current = null;
  R.pageRect = () => ({ top: 0, height: 800 });
  R.syncSub = () => {}; R.saveSpoken = () => {}; R.paintPage = () => {}; R.paintAllFrames = () => {};
  R.prefetchNext = () => {}; R.prefetchBandAhead = () => {}; R.waitIdle = async () => {};
  T.queue = []; T.idx = 0; T.stopped = true; T.paused = false; T.curLine = null; T.curIdx = 0;
  strip.scrollTop = 0;
}

(async () => {
  resetReader();

  // ── 1. В браузере интерфейс остаётся своим
  delete global.window.KomaUi;
  ok(NATIVE_UI.there() === false, 'без моста KomaUi панель остаётся HTML-ной');
  ok(NATIVE_UI.push() === false, 'без моста состояние никуда не отправляется');
  ok(typeof global.window.KomaUiCmd === 'function', 'команды панели определены и в браузере');

  // ── 2. В АПК состояние уходит в нативную панель
  const sent = [];
  global.window.KomaUi = { show: (j) => sent.push(JSON.parse(j)), hide: () => sent.push('hide') };
  // В АПК есть и голос, и панель: голос нативный (системный движок Android).
  global.window.KomaSpeech = { speak() { return true; } };
  ok(NATIVE_UI.there() === true, 'мост KomaUi виден странице');

  // Чтение не запущено: очередь пуста (stop() её чистит) — панели нечего показывать.
  T.queue = []; T.curLine = null; T.curIdx = 0; T.stopped = true;
  R.current = null;
  ok(NATIVE_UI.push() === false && sent[sent.length - 1] === 'hide',
    'когда читать нечего, панель прячется, а не показывает пустоту');

  T.queue = [{ text: 'ПЕРВАЯ РЕПЛИКА' }, { text: 'ВТОРАЯ РЕПЛИКА' }, { text: 'ТРЕТЬЯ РЕПЛИКА' }];
  T.stopped = false; T.idx = 2; T.curIdx = 2; T.curLine = T.queue[1];
  R.current = T.queue[1];
  sent.length = 0;
  ok(NATIVE_UI.push() === true, 'во время чтения состояние уходит в панель');
  const st = sent[sent.length - 1];
  ok(st && st.text === 'ВТОРАЯ РЕПЛИКА', 'панель получает текст текущей реплики');
  ok(st.index === 2 && st.total === 3, 'и место в очереди: ' + st.index + ' из ' + st.total);
  ok(st.band === 1 && st.bands === 2, 'и полосу страницы: ' + st.band + ' из ' + st.bands);
  ok(st.playing === true && st.paused === false, 'и признак «звучит»');
  ok(/Android TTS/.test(st.voice), 'и чей это голос (в АПК — системный)');

  // ── 3. Кнопки нативной панели делают то же, что свои
  resetReader();
  let primed = 0, scanned = 0, readStarted = 0;
  T.prime = () => { primed++; };
  R.scanCurrent = async () => { scanned++; return {}; };
  T.readVisible = (o) => { readStarted++; T.stopped = false; };
  T.step = () => { T.curIdx = (T.curIdx || 0) + 1; return true; };
  T.replay = () => { T.replayDone = true; return true; };
  T.pauseRead = () => { T.pauseDone = true; return 'restart'; };
  T.resumeRead = () => { T.resumeDone = true; return true; };
  T.__proto__ = T.__proto__;   // no-op: методы ниже подменяются в объекте
  const stopCalls = [];
  const origStop = T.stop;
  T.stop = () => { stopCalls.push(1); T.stopped = true; NATIVE_UI.hide(); };

  global.window.KomaUiCmd('toggle');          // чтение стоит → начинаем
  await new Promise(r => setTimeout(r, 0));
  ok(primed === 1 && scanned === 1 && readStarted === 1, '▶ на панели запускает чтение (как своя кнопка)');
  ok(T.stopped === false, 'после ▶ чтение идёт');

  T.paused = false;
  global.window.KomaUiCmd('toggle');          // идёт → пауза
  ok(T.paused === true && T.pauseDone === true, '⏸ ставит паузу');
  global.window.KomaUiCmd('toggle');          // пауза → продолжаем
  ok(T.paused === false && T.resumeDone === true, '▶ после паузы продолжает');

  const before = T.curIdx;
  global.window.KomaUiCmd('next');
  ok(T.curIdx === before + 1, '⏭ переходит к следующей реплике');
  global.window.KomaUiCmd('repeat');
  ok(T.replayDone === true, '⟲ повторяет текущую реплику');
  global.window.KomaUiCmd('stop');
  ok(stopCalls.length === 1 && T.stopped === true, '⏹ останавливает чтение');
  ok(sent[sent.length - 1] === 'hide', 'и убирает панель с экрана');
  T.stop = origStop;

  // ── 4. ПРОКРУТКА: один твин, без рывков и без спора за ленту
  resetReader();
  strip.scrollTop = 0;
  SMOOTH.to(400, 200);
  ok(strip.scrollTop === 0, 'прокрутка начинается с анимации, а не прыжком');
  const seen = [];
  for (let i = 0; i < 6; i++) {
    await new Promise(r => setTimeout(r, 18));
    seen.push(strip.scrollTop);
  }
  ok(seen.every((v, i) => i === 0 || v >= seen[i - 1]), 'лента едет только вперёд, без откатов: ' + seen.join(','));
  ok(seen[seen.length - 1] > 0 && seen[seen.length - 1] < 400, 'движение плавное: промежуточные кадры есть');
  // Новая цель во время движения НЕ запускает вторую анимацию
  SMOOTH.to(100, 200);
  await SMOOTH.done();
  ok(Math.abs(strip.scrollTop - 100) <= 1, 'новая цель просто перенаправила движение (встали на 100, а не на 400)');

  // Кнопка «дальше» не должна драться с анимацией: done() ждёт остановки
  strip.scrollTop = 0;
  SMOOTH.to(300, 120);
  let done = false;
  SMOOTH.done().then(() => { done = true; });
  ok(done === false, 'done() не срабатывает, пока лента едет');
  await new Promise(r => setTimeout(r, 200));
  ok(done === true && Math.abs(strip.scrollTop - 300) <= 1, 'done() срабатывает ровно на остановке');

  // Один твин на всю читалку: три «прокрути к реплике» подряд не дают три анимации
  strip.scrollTop = 0;
  SMOOTH.to(200, 200);
  const idFirst = SMOOTH._raf;
  SMOOTH.to(500, 200);
  ok(SMOOTH._raf === idFirst, 'третьего прохода анимации не появилось — твин один');
  await SMOOTH.done();

  // ── 5. Источники: панель больше нигде не привязана к scrollTo напрямую
  const p4 = fs.readFileSync(__dirname + '/part4.js', 'utf8');
  ok(!/scrollTo\(\{\s*top:[^}]*behavior:\s*'smooth'/.test(p4),
    'ни один вызов не запускает свою smooth-анимацию мимо SMOOTH');

  // ── 6. Котлы: панель действительно нативная и стоит ПОД страницей
  const ui = fs.readFileSync(__dirname + '/apk/app/src/main/java/net/koma/reader/KomaUiBridge.kt', 'utf8');
  const main = fs.readFileSync(__dirname + '/apk/app/src/main/java/net/koma/reader/MainActivity.kt', 'utf8');
  ok(/@JavascriptInterface\s*\n\s*fun show\(/.test(ui) && /fun hide\(/.test(ui),
    'в панели есть show/hide для страницы');
  ok(/KomaUiCmd/.test(ui), 'кнопки панели отправляют KomaUiCmd в страницу');
  ok(/addJavascriptInterface\(ui, "KomaUi"\)/.test(main), 'мост KomaUi зарегистрирован');
  ok(/LinearLayout\.VERTICAL/.test(main) && /root\.addView\(web,/.test(main) && /root\.addView\(ui\.view,/.test(main),
    'страница и панель — одна колонка: панель не перекрывает текст');
  const p1 = fs.readFileSync(__dirname + '/part1.html', 'utf8');
  ok(/body\.native-ui #playBar\s*\{\s*display:\s*none/.test(p1),
    'в АПК своя HTML-панель скрыта — на экране одна панель, а не две');
  const p5 = fs.readFileSync(__dirname + '/part5.js', 'utf8');
  ok(/if \(NATIVE_UI\.there\(\)\) document\.body\.classList\.add\('native-ui'\)/.test(p5),
    'класс native-ui ставится только при живом мосте');

  console.log(process.exitCode ? 'ЕСТЬ ПАДЕНИЯ' : 'ALL PASSED');
  process.exit(process.exitCode || 0);
})().catch(e => { console.error('FAIL', e); process.exit(1); });
