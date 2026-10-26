// Регресс со скриншота 23:20: из реплики пропал конец («…старшей» вместо
// «…старшей сестрой тирана»), хотя строка распозналась. Плюс титул крупным
// текстом помечается, а не теряется.
const fs = require('fs');
require('./shim.js');
global.window.addEventListener = () => {};
global.document.getElementById = () => ({ textContent: '', innerHTML: '', style: {}, classList: { contains: () => false, add() {}, remove() {}, toggle() {} }, addEventListener() {} });
global.document.querySelector = () => null;
global.ort = { env: { wasm: {} }, Tensor: class {} };
const body = require('./koma-src.cjs').appCore;
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Words, readingOrder, sanitizeRules, DEFAULT_RULES, normText};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  const txt = require('./koma-src.cjs').dictText();
  const rank = new Map(); let n = 0;
  for (const line of txt.split('\n')) { const w = (line.split(/\s+/)[0] || '').toLowerCase(); if (!w) continue; if (!rank.has(w)) rank.set(w, n); n++; }
  const W = api.Words; W.rank = rank; W.size = n; W.ready = true;

  const R = api.sanitizeRules(api.DEFAULT_RULES);
  const reg = (text, left, top, right, bottom) => ({ text, left, top, right, bottom, confidence: 1 });

  // Строки титула — крупный кегль; реплика в облачке — обычный
  const regions = [
    reg('Как прожить жизнь, будучию', 0.10, 0.08, 0.90, 0.14),
    reg('старшей Сесмой тирана', 0.10, 0.15, 0.90, 0.21),
    reg('Тл. 48', 0.45, 0.45, 0.55, 0.472),
    reg('УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ, ТАК ЧТО', 0.15, 0.70, 0.75, 0.722),
    reg('ЕЁ ВЫСОЧЕСТВО, ДОЛЖНО БЫТЬ, ПРИБЫЛА.', 0.15, 0.724, 0.75, 0.746),
  ];
  const lines = api.readingOrder(regions, true, true, R);
  const title = lines[0] || {};
  ok(/тирана/.test(title.text), 'конец титула не потерян: «' + (title.text || '') + '»');
  ok(title.large === true, 'титул помечен крупным текстом');
  const reply = lines[1] || {};
  ok(resp_check(reply.text), 'реплика в облачке не помечена крупным: «' + (reply.text || '') + '»');

  function resp_check(t) {
    return typeof t === 'string' && /ПРИБЫЛА/.test(t);
  }

  // Дубли: OCR-вариант уже собранной строки не должен приклеиваться втройне
  const dup = api.readingOrder([
    reg('УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ, ТАК ЧТО', 0.15, 0.60, 0.75, 0.622),
    reg('ЕЁ ВЫСОЧЕСТВО, ДОЛЖНО БЫТЬ, ПРИБЫЛА.', 0.15, 0.624, 0.75, 0.646),
    reg('ТАК ЧТО ЕЁ ВАСО ЧИТАТЬ ВСТРЕЧУ', 0.15, 0.648, 0.75, 0.670),
  ], true, true, R);
  const dupText = dup.map(l => l.text).join(' | ');
  const twice = (dupText.match(/ВСТРЕЧУ/g) || []).length;
  ok(twice <= 2, 'вариант той же строки не приклеен повторно (ВСТРЕЧУ встречается ' + twice + ' раз)');

  // Страховка не должна приклеивать далёкий мусор
  const far = api.readingOrder([
    reg('УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ', 0.15, 0.20, 0.75, 0.222),
    reg('ксллтт ввв жж', 0.15, 0.90, 0.75, 0.922),
  ], true, true, R);
  ok(far.length === 1, 'мусорная строка в конце страницы не приклеена: реплик ' + far.length);

  // Пустая строка не превращается в реплику
  const empty = api.readingOrder([reg('Тл. 48', 0.4, 0.5, 0.6, 0.52)], true, true, R);
  ok(empty.length === 0, 'номер страницы сам по себе — не реплика');

  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})().catch(e => { console.error('FAIL', e); process.exit(1); });
