// Отметка «прочитано» — только когда голос ДОШЁЛ ДО КОНЦА фразы.
//
// Причина: скриншот телефона 2.11 20:11. В «Тексте страницы» все реплики были
// с галочкой «прочитано», а голоса человек не слышал. Отметка ставилась на
// событии «начал говорить»; на Android TTS start может прийти и без звука
// (движок поднялся, но фразу не произнёс). Теперь отметка ставится на onend.
const fs = require('fs');
require('./shim.js');
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.indexedDB = undefined;
const els = {};
const mk = (id) => (els[id] = els[id] || {
  id, textContent: '', innerHTML: '', value: '', checked: false, style: {}, disabled: false,
  classList: { contains: () => false, add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {}, getBoundingClientRect: () => ({ top: 0, height: 800 }),
  scrollTo() {}, scrollBy() {}, clientHeight: 800,
});
global.document.getElementById = mk;
global.document.querySelector = (s) => mk(String(s).replace('#', '').split(' ')[0]);
global.document.querySelectorAll = () => [];
global.document.createElement = () => mk('t' + Math.random());
global.ort = { env: { wasm: {} }, Tensor: class { constructor(t, d, dims) { this.data = d; this.dims = dims; } } };

let mode = 'startOnly';                 // «начал и замолчал» — ровно случай с телефона
const voices = [{ name: 'Русский', lang: 'ru-RU', voiceURI: 'ru' }];
global.speechSynthesis = {
  speaking: false, pending: false,
  getVoices: () => voices,
  cancel() {}, resume() {}, pause() {},
  speak(u) {
    if (mode === 'startOnly') { setTimeout(() => u.onstart && u.onstart(), 5); return; }
    if (mode === 'instant') {                     // «start и сразу end» — движок молчит
      setTimeout(() => u.onstart && u.onstart(), 1);
      setTimeout(() => u.onend && u.onend(), 3);
      return;
    }
    setTimeout(() => u.onstart && u.onstart(), 5);
    setTimeout(() => u.onend && u.onend(), 400);   // реальная фраза длится, не 15 мс
  },
};
global.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };

const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Reader, TTS, SpeakCursor, sanitizeRules, setRules: (o) => { RULES = sanitizeRules(o); }};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  const R = api.Reader, T = api.TTS;
  api.setRules({ speed: 'fast' });
  R.book = { id: 'b' }; R.page = 0; R.pages = [{}];
  R.spoken = new Set(); R.spokenDirty = false;
  R.paintPage = () => {}; R.paintAllFrames = () => {}; R.saveSpoken = () => {};
  R.followLine = () => {};
  T.voice = null; T.rate = 1; T.primed = true;

  // 1. Голос начал, но до конца не дошёл — «прочитано» НЕ ставим.
  mode = 'startOnly';
  const went = [];
  T.speakLine({ text: 'ГОЛОС МОЛЧИТ' }, () => went.push('end'));
  await new Promise(r => setTimeout(r, 300));
  ok(!R.spoken.has(R.spokenKey(0, 'ГОЛОС МОЛЧИТ')),
    'старт без конца фразы НЕ считается прочитанным');
  ok(went.length === 0, 'чтение не ушло дальше молчащей реплики');

  // 2. Движок прислал start и мгновенный end — фразу он не произнёс.
  mode = 'instant';
  R.spoken.clear();
  const went2 = [];
  T.speakLine({ text: 'ЭТА ФРАЗА НЕ ПРОЗВУЧАЛА' }, () => went2.push('end'));
  await new Promise(r => setTimeout(r, 300));
  ok(!R.spoken.has(R.spokenKey(0, 'ЭТА ФРАЗА НЕ ПРОЗВУЧАЛА')),
    'мгновенный end (8+ букв за <250 мс) НЕ считается прочитанным');
  ok(went2.length === 1, 'но чтение продолжается — реплика не застревает');

  // 3. Голос дошёл до конца — отметка есть.
  mode = 'full';
  R.spoken.clear();
  T.speakLine({ text: 'ГОЛОС ДОЧИТАЛ' }, () => went.push('end'));
  await new Promise(r => setTimeout(r, 600));
  ok(R.spoken.has(R.spokenKey(0, 'ГОЛОС ДОЧИТАЛ')),
    'после конца фразы реплика отмечена прочитанной');
  ok(went.length >= 1, 'и только тогда чтение пошло дальше');
  // run_all.sh считает тест пройденным только по последней строке.
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})();
