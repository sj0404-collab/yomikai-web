// Регресс со скриншота 11:26: 11 реплик там, где в оригинале KOMA 5 —
// полосы перекрывались, и одно облачко распознавалось по 3 раза.
const fs = require('fs');
require('./shim.js');
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.document.getElementById = (id) => ({
  id, textContent: '', innerHTML: '', style: {}, dataset: {}, disabled: false,
  classList: { contains: () => false, add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {},
});
global.document.querySelector = () => null;
global.ort = { env: { wasm: {} }, Tensor: class {} };
const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync('/home/user/koma-web/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {mergeBandLines};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

const canvas = { height: 1000 };
const L = (text, top, bottom) => ({ text, left: 0.1, top, right: 0.9, bottom });

// Три перекрывающиеся полосы, каждая видит одно и то же облачко
const parts = [
  { res: { band: { y0: 0, y1: 500 } }, lines: [L('ПЕРВАЯ РЕПЛИКА', 0.05, 0.10), L('ВТОРАЯ РЕПЛИКА', 0.30, 0.35)] },
  { res: { band: { y0: 300, y1: 800 } }, lines: [L('ВТОРАЯ РЕПЛИКА', 0.30, 0.35), L('ТРЕТЬЯ РЕПЛИКА', 0.60, 0.65)] },
  { res: { band: { y0: 600, y1: 1000 } }, lines: [L('ТРЕТЬЯ РЕПЛИКА', 0.60, 0.65), L('ЧЕТВЁРТАЯ РЕПЛИКА', 0.85, 0.90)] },
];
const merged = api.mergeBandLines(parts, canvas);
const texts = merged.map(l => l.text);
ok(texts.length === 4, 'из 6 записей осталось 4 реплики (было ' + texts.length + ': ' + texts.join(' | ') + ')');
ok(new Set(texts).size === texts.length, 'дублей текста нет');
ok(texts[0] === 'ПЕРВАЯ РЕПЛИКА' && texts[3] === 'ЧЕТВЁРТАЯ РЕПЛИКА', 'порядок сверху вниз сохранён');
ok(merged.every((l, i) => i === 0 || merged[i - 1].top <= l.top), 'реплики отсортированы по вертикали');

// Одна полоса — поведение как раньше
const one = api.mergeBandLines([{ res: { band: { y0: 0, y1: 1000 } }, lines: [L('А', 0.1, 0.2), L('Б', 0.3, 0.4)] }], canvas);
ok(one.length === 2, 'одна полоса не теряет реплики');
console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
