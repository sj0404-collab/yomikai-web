// Голос: раньше «голос не работает» выглядело как тишина без причины.
// Проверяем: speak вызывается даже если прокрутка к реплике падает; ошибки
// синтеза не молчат; выбор голоса не подменяется без предупреждения.
const fs = require('fs');
require('./shim.js');
const els = new Map();
const toasts = [];
const el = (id) => {
  if (!els.has(id)) els.set(id, {
    id, textContent: '', innerHTML: '', style: {}, dataset: {}, disabled: false, files: null,
    classList: { s: new Set(), add(c) { this.s.add(c); }, remove(c) { this.s.delete(c); }, contains(c) { return this.s.has(c); }, toggle() {} },
    addEventListener() {}, querySelector() { return null; }, appendChild() {},
    getBoundingClientRect: () => ({ top: 0, bottom: 800, height: 800, left: 0, right: 700 }),
  });
  return els.get(id);
};
delete global.indexedDB;
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.document.addEventListener = () => {};
global.document.getElementById = el;
global.document.querySelector = (sel) => (sel === '#toast' ? el('toast') : el(String(sel).replace(/^[#.]/, '').slice(0, 30)));
global.document.querySelectorAll = () => [];
global.ort = { env: { wasm: {} }, Tensor: class { constructor(t, d, dims) { this.data = d; this.dims = dims; } } };

const spoken = [];
let voices = [{ name: 'Русский', lang: 'ru-RU', voiceURI: 'ru1' }, { name: 'English', lang: 'en-US', voiceURI: 'en1' }];
global.speechSynthesis = {
  getVoices: () => voices, speak: (u) => { spoken.push(u); }, cancel() {}, pause() {}, resume() {}, speaking: false,
};
global.SpeechSynthesisUtterance = class {
  constructor(text) { this.text = text; this.lang = ''; this.rate = 1; this.volume = 1; this.voice = null; }
};

const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {TTS, Reader, toast, RULES, selfTestVoice};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  const T = api.TTS;
  T.voices = voices.slice();
  T.voice = voices[0];
  T.rate = 1;

  // 1. speakLine действительно говорит
  T.speakLine({ text: 'проверка голоса', top: 0.1, bottom: 0.2 });
  ok(spoken.length === 1 && spoken[0].text === 'проверка голоса', 'озвучка уходит в синтезатор');

  // 2. прокрутка к реплике падает — голос всё равно звучит
  const realFollow = T.followLine;
  T.followLine = () => { throw new Error('геометрия сломалась'); };
  spoken.length = 0;
  let threw = null;
  try { T.speakLine({ text: 'второй раз', top: 0.9, bottom: 0.99 }); } catch (e) { threw = e; }
  ok(!threw, 'падение прокрутки не вылетает наружу');
  ok(spoken.length === 1, 'голос не теряется из-за ошибки прокрутки');
  T.followLine = realFollow;

  // 3. Ошибка синтеза не молчит
  spoken.length = 0;
  T.speakLine({ text: 'третий', top: 0.1, bottom: 0.2 }, () => {});
  const u = spoken[0];
  ok(typeof u.onerror === 'function', 'у озвучки есть обработчик ошибки');
  el('toast').textContent = '';
  u.onerror({ error: 'not-allowed' });
  ok(/не разрешил озвучку/.test(el('toast').textContent), 'not-allowed объясняется человеку');

  // 4. Пропавший голос заменяется русским, и это не молча
  T.voice = { name: 'Старый голос', lang: 'ru-RU', voiceURI: 'gone' };
  voices = [{ name: 'Новый русский', lang: 'ru-RU', voiceURI: 'ru2' }];
  spoken.length = 0;
  el('toast').textContent = '';
  T.speakLine({ text: 'четвёртый', top: 0.1, bottom: 0.2 });
  ok(T.voice.voiceURI === 'ru2', 'взят доступный русский голос');
  ok(/недоступен/.test(el('toast').textContent), 'о подмене голоса сказано');

  // 5. Ни одного голоса — прямое объяснение
  voices = [];
  el('toast').textContent = '';
  T.speakLine({ text: 'пятый', top: 0.1, bottom: 0.2 });
  ok(/Синтез речи/.test(el('toast').textContent), 'отсутствие голосов объяснено');

  // 6. prime разблокирует синтезатор в жесте
  T.primed = false; spoken.length = 0;
  T.prime();
  ok(spoken.length === 1 && spoken[0].volume > 0 && spoken[0].volume < 0.2, 'тихая фраза разблокирует озвучку по нажатию');

  // 7. Синтез молча не отвечает — человек узнаёт об этом (а не слушает тишину)
  spoken.length = 0;
  T.stopped = false;
  T.speakLine({ text: 'шестой', top: 0.1, bottom: 0.2 });
  const u6 = spoken[0];
  ok(typeof u6.onstart === 'function', 'у озвучки есть отметка «начал говорить»');
  els.get('toast').textContent = '';
  await new Promise(r => setTimeout(r, 1900));
  ok(/не ответил|Проверить голос/.test(el('toast').textContent), 'молчание синтеза объясняется: «' + el('toast').textContent + '»');

  // 8. cancel() не вызывается зря: очередь не убиваем, если ничего не звучит
  let cancelled = 0;
  const realCancel = global.speechSynthesis.cancel;
  global.speechSynthesis.cancel = () => { cancelled++; };
  global.speechSynthesis.speaking = false; global.speechSynthesis.pending = false;
  spoken.length = 0;
  T.speakLine({ text: 'седьмой', top: 0.1, bottom: 0.2 });
  ok(cancelled === 0, 'cancel() не дёргается, когда очередь пуста (WebView после него молчит)');
  global.speechSynthesis.speaking = true;
  cancelled = 0;
  T.speakLine({ text: 'восьмой', top: 0.1, bottom: 0.2 });
  ok(cancelled === 1, 'cancel() вызывается, когда предыдущая фраза ещё звучит');
  global.speechSynthesis.cancel = realCancel;

  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.error('FAIL', e); process.exit(1); });
