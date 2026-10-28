// WebView без Web Speech API: то, что 28.10 сломало АПК на телефоне.
//
// На телефоне было так: «Скрипты страницы не выполнились», тост
// «speechSynthesis is not defined» и пустая библиотека — первый же вызов голоса
// обрывал boot(). В Android WebView speechSynthesis отсутствует ВООБЩЕ.
//
// Здесь это воспроизводится честно: в окружении НЕТ speechSynthesis и нет
// SpeechSynthesisUtterance. Проверяем, что страница всё равно поднимается,
// а голос в АПК идёт через нативный мост KomaSpeech.
const fs = require('fs');
require('./shim.js');

const PARTS = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js'];
const body = PARTS.map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api_end = body.indexOf('(async function boot()');

const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };
const toasts = [];

/** Собственное окружение под каждый сценарий: как новый запуск на телефоне. */
function makeEnv({ withSpeechApi = false, withBridge = false } = {}) {
  const store = new Map();
  const el = (id) => {
    if (!store.has(id)) store.set(id, {
      id, textContent: '', innerHTML: '', style: {}, dataset: {}, disabled: false, files: null, value: '',
      classList: { s: new Set(), add(c) { this.s.add(c); }, remove(c) { this.s.delete(c); }, contains(c) { return this.s.has(c); }, toggle() {} },
      addEventListener() {}, querySelector() { return null; }, appendChild() {},
      closest() { return null; },
      getBoundingClientRect: () => ({ top: 0, bottom: 800, height: 800, left: 0, right: 700 }),
    });
    return store.get(id);
  };
  global.window = { innerHeight: 1600, addEventListener: () => {} };
  global.document = global.document || {};
  global.document.addEventListener = () => {};
  global.document.getElementById = el;
  // Один и тот же элемент по одному и тому же селектору — как в настоящем DOM.
  global.document.querySelector = (sel) => el(String(sel).replace(/^[#.]/, '').slice(0, 30));
  global.document.querySelectorAll = () => [];
  global.document.createElement = () => el('created');
  global.navigator = { userAgent: 'Android WebView (Node-тест)' };
  global.indexedDB = undefined;
  global.localStorage = {
    _m: new Map(),
    getItem(k) { return this._m.has(k) ? this._m.get(k) : null; },
    setItem(k, v) { this._m.set(k, String(v)); },
    removeItem(k) { this._m.delete(k); },
  };
  global.ort = { env: { wasm: {} }, Tensor: class { constructor(t, d, dims) { this.data = d; this.dims = dims; } } };
  global.fetch = () => Promise.reject(new Error('сети нет (как в самолёте)'));

  // Ключевое отличие WebView от Chrome: этих имён в окружении НЕТ.
  delete global.speechSynthesis;
  delete global.SpeechSynthesisUtterance;
  if (withSpeechApi) {
    global.speechSynthesis = { getVoices: () => [{ name: 'Rus', lang: 'ru-RU', voiceURI: 'r1' }], speak() {}, cancel() {}, pause() {}, resume() {}, speaking: false, pending: false };
    global.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; this.volume = 1; } };
  }

  const calls = { speak: [], cancel: 0 };
  if (withBridge) {
    global.window.KomaSpeech = {
      voices: () => JSON.stringify([{ name: 'ru-ru-x-afn', lang: 'ru-RU', voiceURI: 'native:ru-ru-x-afn' }]),
      status: () => JSON.stringify({ ready: true, engine: 'com.google.android.tts', voices: 24, ru: true }),
      speak(text, rate, lang, voice, id) { calls.speak.push({ text, rate, lang, voice, id }); },
      cancel() { calls.cancel++; },
    };
  }
  return { el, calls, store };
}

function buildApi() {
  return new Function(body.slice(0, api_end)
    + '; return {TTS, VOICE, Reader, RULES, State, selfTestVoice, toast, selfCheck};')();
}
let toastEl = null;

(async () => {
  // ── Сценарий 1: WebView, моста голоса ещё нет (так было при первом запуске)
  let env = makeEnv({ withSpeechApi: false, withBridge: false });
  toastEl = env.el('toast');
  let api = buildApi();
  ok(typeof speechSynthesis === 'undefined', 'в окружении теста speechSynthesis действительно нет');

  // Сам баг: TTS.init() не должен бросать
  let threw = null;
  try { api.TTS.init(); } catch (e) { threw = e; }
  ok(!threw, 'TTS.init() без speechSynthesis не падает' + (threw ? ': ' + threw.message : ''));
  ok(api.VOICE.available() === false, 'фасад честно говорит: синтеза нет');
  ok(/голосов нет/.test(env.el('selVoice').innerHTML), 'в списке голосов написано «голосов нет», а не пусто');

  let vThrew = null, report = '';
  try { report = await api.selfTestVoice(); } catch (e) { vThrew = e; }
  ok(!vThrew, '«Проверить голос» без синтеза не падает');
  ok(/нет|KomaSpeech/i.test(report), '«Проверить голос» объясняет причину: «' + report + '»');

  toastEl.textContent = '';
  api.TTS.speakLine({ text: 'реплика', top: 0.1, bottom: 0.2 });
  ok(/синтез|голос/i.test(toastEl.textContent), 'попытка читать без синтеза объясняется человеку');

  // ── Сценарий 2: АПК — есть нативный мост KomaSpeech (Android TTS)
  env = makeEnv({ withSpeechApi: false, withBridge: true });
  toastEl = env.el('toast');
  api = buildApi();
  ok(api.VOICE.available() === true, 'в АПК синтез есть — через нативный мост');
  ok(api.VOICE.kind() === 'Android TTS (АПК)', 'фасад знает, чей это голос');
  api.TTS.init();
  ok(api.TTS.voices.length === 1 && /ru/.test(api.TTS.voices[0].lang), 'голоса пришли из Android TTS (русский первым)');
  ok(/ru-ru-x-afn/.test(env.el('selVoice').innerHTML), 'русский голос показан в списке выбора');

  // prime в АПК ничего не шлёт: жест не нужен
  api.TTS.prime();
  ok(env.calls.speak.length === 0, 'в АПК разблокировка жестом не нужна и не шлёт пустую фразу');

  // Реплика → мост
  let thenCalled = false;
  const line = { text: 'УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ', top: 0.1, bottom: 0.2 };
  api.TTS.rate = 1.2;
  api.TTS.speakLine(line, () => { thenCalled = true; });
  ok(env.calls.speak.length === 1, 'реплика ушла в нативный движок');
  const call = env.calls.speak[0];
  ok(call.text === line.text, 'в движок уходит текст реплики целиком');
  ok(call.lang === 'ru-RU', 'язык русский');
  ok(call.rate === '1.2', 'скорость передана (' + call.rate + ')');
  ok(call.voice === 'ru-ru-x-afn', 'выбранный голос передан по имени');
  ok(/^v\d+_/.test(call.id), 'у каждой фразы свой идентификатор для событий');

  // События движка: start → «прочитано», end → следующая реплика
  const marked = [];
  api.Reader.markSpoken = (p, t) => marked.push(t);
  global.window.__komaSpeechEvent(call.id, 'start', '');
  ok(marked.length === 1 && marked[0] === line.text, 'после start реплика отмечена прочитанной');
  global.window.__komaSpeechEvent(call.id, 'end', '');
  ok(thenCalled === true, 'после end читалка идёт дальше');

  // Ошибка движка → человеку текстом, без молчания
  toastEl.textContent = '';
  env.calls.speak.length = 0;
  api.TTS.speakLine({ text: 'вторая', top: 0.1, bottom: 0.2 });
  const c2 = env.calls.speak[0];
  global.window.__komaSpeechEvent(c2.id, 'error', 'служба TTS недоступна');
  ok(/служба TTS недоступна/.test(toastEl.textContent), 'ошибка нативного движка видна: «' + toastEl.textContent + '»');

  // Пауза: у Android TTS её нет — значит стоп и продолжение реплики заново
  api.TTS.stopped = false;
  const mode = api.TTS.pauseRead();
  ok(mode === 'restart' && env.calls.cancel >= 1, 'пауза в АПК = остановка движка (cancel)');
  ok(api.TTS.pausedLine && api.TTS.pausedLine.text === 'вторая', 'реплика запомнена для продолжения');
  env.calls.speak.length = 0;
  api.TTS.resumeRead();
  ok(env.calls.speak.length === 1 && env.calls.speak[0].text === 'вторая', 'продолжение говорит ту же реплику');

  // Стоп гасит и нативный движок
  api.TTS.stop();
  ok(env.calls.cancel >= 2, 'стоп отменяет нативную речь');

  // ── Сценарий 3: браузер (Web Speech есть, моста нет) — прежнее поведение цело
  env = makeEnv({ withSpeechApi: true, withBridge: false });
  toastEl = env.el('toast');
  api = buildApi();
  ok(api.VOICE.kind() === 'Web Speech', 'в браузере голос по-прежнему Web Speech');
  api.TTS.init();
  ok(api.TTS.voices.length === 1, 'голоса браузера на месте');

  // ── Сценарий 4: boot целиком в условиях WebView не оставляет «скрипты не выполнились»
  env = makeEnv({ withSpeechApi: false, withBridge: true });
  toastEl = env.el('toast');
  // Запускаем ВСЮ страницу целиком: части + настоящий boot. Именно так это
  // происходит в приложении, и именно здесь раньше всё обрывалось.
  const sc = env.el('selfCheck');
  sc.textContent = 'Скрипты страницы не выполнились — поэтому кнопки не реагируют.';
  // Выполняем настоящий boot из part5.js (он в общем теле, но мы его срезали —
  // поэтому берём только ту часть, что после api_end).
  const bootEnd = body.indexOf('</script>', api_end);
  const wholeCode = body.slice(0, bootEnd > 0 ? bootEnd : undefined);
  new Function(wholeCode)();
  await new Promise(r => setTimeout(r, 500));
  ok(!/Скрипты страницы не выполнились/.test(sc.textContent),
    'после boot надпись «Скрипты страницы не выполнились» заменена состоянием');
  ok(/KOMA Web v/.test(sc.textContent), 'состояние показывает версию: «' + String(sc.textContent).slice(0, 80) + '…»');
  ok(!/голос: ?:/.test(sc.textContent), 'строка состояния не ломается на голосе');

  console.log(process.exitCode ? 'ЕСТЬ ПАДЕНИЯ' : 'ALL PASSED');
})().catch(e => { console.log('FAIL исключение: ' + (e && e.message)); console.log(e && e.stack); process.exitCode = 1; });
