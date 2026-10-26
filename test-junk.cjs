// Мусорные «слова» от OCR не должны попадать в реплики, настоящие — остаются.
const fs = require('fs');
require('./shim.js');
global.window.addEventListener = () => {};
global.document.getElementById = (id) => ({
  id, textContent: '', innerHTML: '', style: {}, dataset: {}, disabled: false,
  classList: { contains: () => false, add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {},
});
global.document.querySelector = () => null;
global.ort = { env: { wasm: {} }, Tensor: class {} };
const body = require('./koma-src.cjs').appCore;
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Words, RULES};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };
const W = api.Words;

(async () => {
  // словарь — маленький, свой: ранг задаётся порядком строк
  W.rank = new Map([['вы', 1], ['должны', 2], ['быть', 3], ['равнодушны', 4],
    ['высочеством', 5], ['высочество', 6], ['они', 7], ['говорят', 8], ['этому', 9]]);
  W.size = W.rank.size;
  W.ready = true;

  // 1. словоформа «корень + окончание» — настоящая, не правим
  ok(W.isPlausible('высочеством') === true, '«высочеством» — настоящая словоформа');
  ok(W.isPlausible('тг') === false, '«тг» — не слово');

  // 2. окончание не портит слово
  ok(W.correctWord('ВЫСОЧЕСТВОМ') === 'ВЫСОЧЕСТВОМ', '«ВЫСОЧЕСТВОМ» больше не превращается в «ВЫСОЧЕСТВО»');

  // 3. stripJunkWords выбрасывает мусор, оставляет фразу
  const kept = W.stripJunkWords('вы должны быть равнодушны');
  ok(kept === 'вы должны быть равнодушны', 'настоящая реплика не тронута: «' + kept + '»');

  // целую мусорную строку отбрасывает polish: настоящих слов в ней нет
  ok(W.polish('косллттт алмчлс тг чв') === '', 'строка из мусора отброшена целиком');
  ok(W.polish('Тг. чв') === '', '«Тг. чв» — не реплика');
  ok(W.polish('вы должны быть равнодушны') === 'вы должны быть равнодушны', 'настоящая реплика проходит polish');
  ok(W.polish('БЕРСЕРК') === 'БЕРСЕРК', 'имя капсом сохранено');

  const mixed = W.stripJunkWords('они соооит оо ом');
  ok(!/соооит|ом\b/.test(mixed) && /они/.test(mixed), 'мусор выброшен, слово «они» осталось: «' + mixed + '»');
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.error('FAIL', e); process.exit(1); });
