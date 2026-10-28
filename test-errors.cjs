/* Ошибки, которые видит человек: промис-цепочки на функциях, которые промис
   не возвращают, и пустые места в интерфейсе.

   Почему этот тест появился: на телефоне 28.10 всплыл тост
   «Ошибка: Cannot read properties of undefined (reading 'catch')».
   Причина — строка вида `await renderTextSheet(null).catch(...)`, где
   renderTextSheet объявлена как обычная (не async) функция: она возвращает
   undefined, и `.catch` падает. Сообщение ничего не говорит ни человеку, ни мне,
   поэтому проверка автоматическая: берём объявленные функции, смотрим, какие из
   них не async, и ищем вызовы `.then(` / `.catch(` прямо на них. */
const fs = require('fs');
const path = require('path');

const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };
const files = ['part2.js', 'part3.js', 'part4.js', 'part5.js'];
const src = files.map(f => fs.readFileSync(path.join(__dirname, f), 'utf8')).join('\n');

// 1. Какие функции объявлены БЕЗ async
const syncFns = new Set();
for (const m of src.matchAll(/(^|[^.\w])(?<!async\s)function\s+([A-Za-z_$][\w$]*)\s*\(/g)) {
  const before = src.slice(Math.max(0, m.index - 12), m.index + 1);
  if (/async\s*$/.test(before)) continue;
  syncFns.add(m[2]);
}
ok(syncFns.size > 40, 'функции найдены и разобраны (' + syncFns.size + ' не-async)');

// 2. Ни на одной из них не висит .then/.catch
const bad = [];
for (const m of src.matchAll(/\b([A-Za-z_$][\w$]*)\s*\((?:[^()]|\([^()]*\))*\)\s*\.(catch|then)\s*\(/g)) {
  const name = m[1];
  if (syncFns.has(name)) bad.push(name + '().' + m[2]);
}
ok(bad.length === 0, 'нет .then/.catch на не-async функциях' + (bad.length ? ': ' + [...new Set(bad)].join(', ') : ''));

// 3. renderTextSheet — та самая функция: обязана возвращать промис
const p4 = fs.readFileSync(path.join(__dirname, 'part4.js'), 'utf8');
ok(/async function renderTextSheet\s*\(/.test(p4),
  'renderTextSheet объявлена async (её результат ждут через await)');
const p5 = fs.readFileSync(path.join(__dirname, 'part5.js'), 'utf8');
ok(/Promise\.resolve\(renderTextSheet\(/.test(p5),
  'и на всякий случай вызов обёрнут в Promise.resolve — два замка на одну дверь');

// 4. Шторка «Модели» никогда не открывается пустой
ok(/openSheet\('sheetModels'\);\s*\n\s*renderModels\(\)/.test(p4),
  'автооткрытие «Моделей» сразу рисует состояние, а не пустоту');
ok(/моделей нет — выберите три файла/.test(p4),
  'когда моделей нет вовсе — это написано словами, а не пустой строкой');

// 5. Глобальные обработчики ошибок на месте: ошибка не должна молчать
ok(/addEventListener\('unhandledrejection'/.test(p5), 'необработанные промисы показываются человеку');
ok(/addEventListener\('error'/.test(p5), 'синхронные ошибки тоже показываются');

console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
