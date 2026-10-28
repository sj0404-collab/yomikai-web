// Кнопка «Проверить обновление» и автообновление: раньше она МОЛЧАЛА.
//
// 28.10 на телефоне: обновление скачивало ту же версию, что уже стоит,
// перезагружало страницу без предупреждения, а по нажатию кнопки — ни звука.
// Причина: синхронный метод моста держал поток JavaScript всё время проверки и
// скачивания 11 МБ.
//
// Здесь проверяем поведение страницы с подставным мостом:
//  • по нажатию СРАЗУ появляется «Проверяю обновление…»;
//  • сообщения моста («Найдена версия…», «Скачиваю…») видны человеку;
//  • «уже свежая» — это «Обновлений нет», без перезагрузки;
//  • настоящая ошибка видна, а не проглочена;
//  • старая синхронная оболочка тоже поддержана;
//  • молчащий мост не оставляет человека без ответа.
const fs = require('fs');
require('./shim.js');

const PARTS = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js'];
const body = PARTS.map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const apiEnd = body.indexOf('(async function boot()');
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

function makeEnv() {
  const store = new Map();
  const el = (id) => {
    if (!store.has(id)) store.set(id, {
      id, textContent: '', innerHTML: '', style: {}, dataset: {}, disabled: false, files: null, value: '',
      onclick: null,
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
  global.document.querySelector = (sel) => el(String(sel).replace(/^[#.]/, '').slice(0, 30));
  global.document.querySelectorAll = () => [];
  global.document.createElement = () => el('created');
  global.navigator = { userAgent: 'Android WebView (Node-тест)' };
  global.indexedDB = undefined;
  global.localStorage = { _m: new Map(), getItem(k) { return this._m.has(k) ? this._m.get(k) : null; }, setItem(k, v) { this._m.set(k, String(v)); }, removeItem(k) { this._m.delete(k); } };
  global.ort = { env: { wasm: {} }, Tensor: class { constructor(t, d, dims) { this.data = d; this.dims = dims; } } };
  global.fetch = () => Promise.reject(new Error('сети нет'));
  delete global.speechSynthesis;
  delete global.SpeechSynthesisUtterance;
  global.window.KomaSpeech = {
    voices: () => JSON.stringify([{ name: 'ru', lang: 'ru-RU', voiceURI: 'native:ru' }]),
    status: () => JSON.stringify({ ready: true }),
    speak() {}, cancel() {},
  };
  return { el };
}

function build() {
  return new Function(body.slice(0, apiEnd) + '; return {bindUI};')();
}

(async () => {
  const env = makeEnv();
  const toastEl = env.el('toast');
  const lastToast = () => String(toastEl.textContent || '');

  // Подставная оболочка: новая (асинхронная) схема.
  const calls = [];
  global.window.KomaApp = {
    version: () => JSON.stringify({ app: '1.9.34', page: 'v1.9.34', release: 'page' }),
    checkUpdate(id) { calls.push(id); return undefined; },
    lensSelfTest: () => JSON.stringify({ ok: false, error: 'нет сети' }),
    reloadNow() {},
  };
  const api = build();
  api.bindUI();
  const btn = env.el('btnAppUpdate');
  ok(typeof btn.onclick === 'function', 'кнопка «Проверить обновление» подключена');

  // 1. Нажатие даёт немедленный отклик (раньше — тишина)
  toastEl.textContent = '';
  btn.onclick();
  ok(/Проверяю обновление/.test(lastToast()), 'по нажатию сразу видно «Проверяю обновление…»: «' + lastToast() + '»');
  ok(calls.length === 1 && /^u/.test(calls[0]), 'мост вызван с идентификатором запроса');

  // 2. Промежуточные сообщения моста доходят до человека
  const id = calls[0];
  toastEl.textContent = '';
  global.window.__komaAppEvent(id, 'state', 'Найдена версия v1.9.34 — скачиваю…');
  ok(/Найдена версия v1\.9\.34/.test(lastToast()), 'видно «Найдена версия…»: «' + lastToast() + '»');
  global.window.__komaAppEvent(id, 'state', 'Скачиваю v1.9.34 (11 МБ)…');
  ok(/Скачиваю/.test(lastToast()), 'видно «Скачиваю…»');

  // 3. «Уже свежая» — без перезагрузки и без «обновлено»
  let reloaded = 0;
  global.window.KomaApp.reloadNow = () => { reloaded++; };
  toastEl.textContent = '';
  global.window.__komaAppEvent(id, 'done', JSON.stringify({ updated: false, reason: 'уже свежая (v1.9.34)' }));
  ok(/Обновлений нет: уже свежая \(v1\.9\.34\)/.test(lastToast()), 'та же версия = «Обновлений нет», а не «обновлено»: «' + lastToast() + '»');
  await new Promise(r => setTimeout(r, 1700));
  ok(reloaded === 0, 'при той же версии перезагрузки нет');

  // 4. Настоящее обновление
  calls.length = 0;
  toastEl.textContent = '';
  btn.onclick();
  const id2 = calls[0];
  global.window.__komaAppEvent(id2, 'state', 'Найдена версия v1.9.35 — скачиваю…');
  global.window.__komaAppEvent(id2, 'done', JSON.stringify({ updated: true, version: 'v1.9.35', bytes: 11170000, reload: true }));
  ok(/Обновлено до v1\.9\.35/.test(lastToast()), 'видно «Обновлено до v1.9.35 — перезагружаю…»: «' + lastToast() + '»');

  // 5. Ошибка не проглатывается
  calls.length = 0;
  toastEl.textContent = '';
  btn.onclick();
  const id3 = calls[0];
  global.window.__komaAppEvent(id3, 'done', JSON.stringify({ updated: false, reason: 'GitHub ответил HTTP 503' }));
  ok(/Обновление не удалось: GitHub ответил HTTP 503/.test(lastToast()), 'ошибка видна текстом: «' + lastToast() + '»');

  // 6. Старая синхронная оболочка: мост вернул строку сразу
  global.window.KomaApp.checkUpdate = () => JSON.stringify({ updated: false, reason: 'уже свежая (v1.9.34)' });
  toastEl.textContent = '';
  btn.onclick();
  ok(/Обновлений нет/.test(lastToast()), 'синхронный ответ старой оболочки тоже понятен');

  // 7. Молчащий мост: ответ приходит сам, а не «ничего»
  let quietTimers = [];
  const realTimeout = global.setTimeout;
  global.window.KomaApp.checkUpdate = () => undefined;
  global.setTimeout = (fn, ms) => { if (ms === 180000) quietTimers.push(fn); return realTimeout(() => {}, 0); };
  toastEl.textContent = '';
  btn.onclick();
  ok(quietTimers.length === 1, 'поставлена страховка на случай молчащего моста');
  global.setTimeout = realTimeout;
  quietTimers[0]();
  ok(/не ответил/.test(lastToast()), 'молчащий мост заканчивается понятным сообщением: «' + lastToast() + '»');

  // 8. В браузере (без моста) кнопка честно говорит, что обновлять нечего
  delete global.window.KomaApp;
  const env2 = makeEnv();
  const api2 = build();
  api2.bindUI();
  const toast2 = env2.el('toast');
  toast2.textContent = '';
  env2.el('btnAppUpdate').onclick();
  ok(/только в приложении/.test(String(toast2.textContent)),
    'в браузере сказано прямо: «' + toast2.textContent + '»');

  console.log(process.exitCode ? 'ЕСТЬ ПАДЕНИЯ' : 'ALL PASSED');
  // Выходим сразу: в странице висят длинные страховочные таймеры, ждать их незачем.
  process.exit(process.exitCode || 0);
})().catch(e => { console.log('FAIL исключение: ' + (e && e.message)); console.log(e && e.stack); process.exitCode = 1; });
