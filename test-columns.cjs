// Реплики рядом и абзацы: то, что терялось на прозе и могло теряться в манге.
//
// Замер 28.10: на странице журнала читалка находила 58 строк распознаванием и
// отдавала 2 реплики / 8 слов. Причины были две, обе здесь закреплены тестом:
//   1) mergeBandLines считал «тем же местом» всё, что совпало по вертикали, —
//      две реплики на одной высоте (две колонки, два облачка рядом) съедали
//      друг друга;
//   2) склейка в облачко не имела потолка высоты, и абзац-колонка собиралась в
//      блок на полстраницы, который потом считался дублем первой реплики.
require('./shim.js');
const fs = require('fs');
const path = require('path');

const here = __dirname;
const code = ['part2.js', 'part3.js', 'part4.js'].map(f => fs.readFileSync(path.join(here, f), 'utf8')).join('\n');
const api = new Function(code + '\n return { mergeBandLines, bubblesOf, sanitizeRules, makeCanvas };')();

let fails = 0;
const ok = (name, cond, extra) => {
  if (!cond) { console.log('FAIL', name, extra === undefined ? '' : '· ' + JSON.stringify(extra)); fails++; }
  else console.log('ok  ', name);
};

const R = api.sanitizeRules({});
const canvas = { width: 900, height: 1200 };
const reg = (text, left, top, right, bottom) => ({ text, left, top, right, bottom });

// 1. Две реплики на одной высоте, но в разных колонках — это ДВЕ реплики.
const left = { lines: [reg('левая колонка текст', 0.05, 0.20, 0.45, 0.22)], res: { band: { y0: 0 } } };
const right = { lines: [reg('правая колонка текст', 0.55, 0.20, 0.95, 0.22)], res: { band: { y0: 0 } } };
const merged = api.mergeBandLines([left, right], canvas);
ok('две реплики на одной высоте не съедают друг друга', merged.length === 2, merged.map(m => m.text));

// 2. Один и тот же текст в том же месте (перекрытие полос) — это дубль.
const a = { lines: [reg('УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ', 0.1, 0.30, 0.6, 0.33)], res: { band: { y0: 0 } } };
const b = { lines: [reg('УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ', 0.1, 0.305, 0.6, 0.335)], res: { band: { y0: 400 } } };
ok('тот же текст в том же месте — дубль схлопывается', api.mergeBandLines([a, b], canvas).length === 1);

// 3. Абзац-колонка не склеивается в блок выше 22 % страницы.
const column = [];
for (let i = 0; i < 20; i++) column.push(reg('строка абзаца ' + i, 0.06, 0.02 + i * 0.02, 0.44, 0.035 + i * 0.02));
const bubbles = api.bubblesOf(column, false, R);
const tallest = Math.max(...bubbles.map(l => l.bottom - l.top));
ok('абзац делится, а не висит блоком на полстраницы', tallest <= 0.23, { tallest: +tallest.toFixed(3), n: bubbles.length });
ok('абзац не потерялся при делении',
  bubbles.reduce((n, l) => n + (l.text.match(/строка/g) || []).length, 0) === 20,
  bubbles.map(l => l.text.length));

// 4. Облачко манги из трёх плотных строк по-прежнему ОДНА реплика (не режем).
const bubble = [reg('УЖЕ ПОРА', 0.10, 0.100, 0.60, 0.130),
  reg('НАЧИНАТЬ ВСТРЕЧУ,', 0.12, 0.135, 0.62, 0.165),
  reg('ТАК ЧТО ПРИБЫЛА.', 0.11, 0.170, 0.61, 0.200)];
const one = api.bubblesOf(bubble, true, R);
ok('облачко из трёх строк — одна реплика', one.length === 1, one.map(l => l.text));

// 5. Два отдельных облачка рядом — две реплики.
const two = api.bubblesOf([reg('ПЕРВАЯ РЕПЛИКА', 0.05, 0.10, 0.45, 0.13),
  reg('ВТОРАЯ РЕПЛИКА', 0.55, 0.10, 0.95, 0.13)], true, R);
ok('два облачка рядом — две реплики', two.length === 2, two.map(l => l.text));

console.log(fails ? `\n${fails} FAILED` : '\nALL PASSED');
process.exit(fails ? 1 : 0);
