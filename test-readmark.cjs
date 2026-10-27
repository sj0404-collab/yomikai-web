// «Прочитано» ставится только когда голос реально заговорил. Отказ синтеза
// не должен съедать реплику: иначе при продолжении чтения она пропускается.
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

// Синтез речи: управляемый из теста
let mode = 'ok';
const voices = [{ name: 'Русский', lang: 'ru-RU', voiceURI: 'ru' }];
global.speechSynthesis = {
  speaking: false, pending: false,
  getVoices: () => voices,
  cancel() {}, resume() {}, pause() {},
  speak(u) {
    if (mode === 'fail') { setTimeout(() => u.onerror && u.onerror({ error: 'not-allowed' }), 5); return; }
    if (mode === 'silent') return;                       // ни старта, ни ошибки
    setTimeout(() => u.onstart && u.onstart(), 5);
    setTimeout(() => u.onend && u.onend(), 15);
  },
};
global.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };

const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync('/home/user/koma-web/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Reader, TTS, SpeakCursor, sanitizeRules, setRules: (o) => { RULES = sanitizeRules(o); }};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  const R = api.Reader, T = api.TTS;
  api.setRules({ speed: 'fast' });
  R.book = { id: 'b' }; R.page = 0; R.pages = [{}];
  R.spoken = new Set(); R.spokenDirty = false;
  R.paintPage = () => {}; R.paintAllFrames = () => {}; R.saveSpoken = () => {};
  R.followLine = () => {}; R.bands = [{ index: 0, top: 0, bottom: 1 }]; R.bandIndex = 0; R.band = R.bands[0];
  R.pageRect = () => ({ height: 800 });
  T.voice = null; T.rate = 1; T.primed = true;

  // 1. Голос заговорил — отметка есть
  mode = 'ok';
  const spoken = [];
  T.speakLine({ text: 'ПЕРВАЯ' }, () => spoken.push('end'));
  await new Promise(r => setTimeout(r, 120));
  ok(R.spoken.has(R.spokenKey(0, 'ПЕРВАЯ')), 'после реальной озвучки реплика отмечена прочитанной');
  ok(spoken.length === 1, 'после озвучки чтение пошло дальше');

  // 2. Синтез отказал — отметки нет, значит реплика НЕ пропадёт
  mode = 'fail';
  R.spoken.clear();
  T.speakLine({ text: 'ВТОРАЯ' }, () => {});
  await new Promise(r => setTimeout(r, 120));
  ok(!R.spoken.has(R.spokenKey(0, 'ВТОРАЯ')), 'при отказе синтеза реплика НЕ считается прочитанной');

  // 3. Синтез промолчал совсем — тоже не отмечаем
  mode = 'silent';
  R.spoken.clear();
  T.speakLine({ text: 'ТРЕТЬЯ' }, () => {});
  await new Promise(r => setTimeout(r, 1500));
  ok(!R.spoken.has(R.spokenKey(0, 'ТРЕТЬЯ')), 'если синтез не ответил — реплика не считается прочитанной');

  // 4. Отметку можно снять
  mode = 'ok';
  R.spoken.clear();
  T.speakLine({ text: 'ЧЕТВЁРТАЯ' }, () => {});
  await new Promise(r => setTimeout(r, 100));
  ok(R.spoken.size > 0, 'отметка поставлена');
  R.unmarkSpoken(0, 'ЧЕТВЁРТАЯ');
  ok(!R.spoken.has(R.spokenKey(0, 'ЧЕТВЁРТАЯ')), 'отметку можно снять (unmarkSpoken)');

  // 5. В «Тексте страницы» показываются ВСЕ реплики, прочитанные помечены
  const html = fs.readFileSync('/home/user/koma-web/part4.js', 'utf8');
  ok(/Показываем ВСЕ реплики страницы/.test(html), 'список реплик не фильтруется по «прочитано»');
  ok(/data\.lines\.map\(/.test(html) && /Reader\.spoken\.has/.test(html),
    'в списке есть и прочитанные строки, с пометкой');

  // 6. Рамка рисуется каждой строке, «прочитано» — только цвет
  const paint = html.slice(html.indexOf('paintPage(i) {'), html.indexOf('paintAllFrames()'));
  ok(/for \(const line of data\.lines\)/.test(paint), 'рамки рисуются по всем строкам страницы');
  ok(!/filter\(.*spoken/.test(paint), 'прочитанные строки не выпадают из рамок');

  
// ── Тень по буквам: лента «где читает» ──────────────────────────────────
{
  const C = api.SpeakCursor;
  ok(typeof C.start === 'function' && typeof C.tick === 'function', 'лента где читает есть');
  // Границы слов из onboundary: позиция встаёт ровно на начало слова.
  C.el = { innerHTML: '', style: {}, querySelectorAll: () => [], scrollTop: 0, clientHeight: 40 };
  C.chars = Array.from({ length: 20 }, () => ({ className: 'ch' }));
  C.on = true; C.exact = false; C.pos = 0; C.rate = 1;
  C.boundary(7);
  ok(C.pos === 7 && C.exact === true, 'onboundary двигает тень на начало слова');
  C.stop();
  ok(C.on === false && C.chars.length === 0, 'стоп убирает ленту');
}

console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.error('FATAL', e.stack); process.exit(1); });
