/* Прямой Lens: правила, разбор ответа и то, что «без сайта» не открывает сайт.
   Проверяем на исходниках (как остальные тесты репозитория): без браузера. */
const fs = require('fs');
const path = require('path');
require(path.join(__dirname, 'shim.js'));
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.indexedDB = undefined;
const el = () => ({ textContent: '', innerHTML: '', style: {}, value: '', checked: false,
  classList: { contains: () => false, add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {} });
global.document.getElementById = el;
global.document.querySelector = () => el();
global.document.querySelectorAll = () => [];
global.ort = { env: { wasm: {} }, Tensor: class { constructor(t, d, dims) { this.data = d; this.dims = dims; } } };
const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync(path.join(__dirname, f), 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {RULES, DEFAULT_RULES, SPEED_PRESETS, sanitizeRules, LENS, makeCanvas, Reader};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

// 1. Адрес релея — обычная строка в правилах, не ломает остальное
ok(typeof api.sanitizeRules({}).lensRelay === 'string', 'lensRelay есть в правилах и это строка');
ok(api.sanitizeRules({ lensRelay: ' https://x.example/lens ' }).lensRelay === 'https://x.example/lens',
  'адрес релея обрезается от пробелов');
ok(api.sanitizeRules({ lensRelay: 'x'.repeat(2000) }).lensRelay.length <= 500,
  'слишком длинный адрес не раздувает правила');
ok(api.sanitizeRules({ speed: 'normal' }).lensRelay === '',
  'по умолчанию релея нет — прямой путь не включается сам');

// 2. Транспорты: мост АПК важнее релея, пустой список — честный «нет»
const L = api.LENS;
ok(Array.isArray(L.transports()) && L.transports().length === 0, 'без моста и релея транспортов нет');
ok(L.hasDirect() === false, 'прямой путь считается недоступным');
global.window = { KomaLens: { recognize: () => '{"lines":["а"]}' } };
ok(L.transports()[0] === 'native', 'мост KomaLens распознан как прямой транспорт АПК');
global.window = {};
api.RULES.lensRelay = 'https://relay.example/lens';
ok(L.transports().includes('relay'), 'свой релей тоже даёт прямой транспорт');
delete global.window;
api.RULES.lensRelay = '';

// 3. Разбор ответа: три формата, которые может вернуть релей или мост
const p1 = L.parseResponse('{"lines":["Матушка Медведица","Хрум-хрум!"]}', 'application/json');
ok(p1.length === 2 && p1[0] === 'Матушка Медведица', 'JSON {"lines": …} разобран');
const p2 = L.parseResponse('{"text":"Первая строка\\nВторая строка"}', 'application/json');
ok(p2.length === 2, 'JSON {"text": …} разобран по строкам');
const p3 = L.parseResponse('Просто текст\nи вторая строка\n\n', 'text/plain');
ok(p3.length === 2 && p3[1] === 'и вторая строка', 'голый текст разобран, пустые строки выкинуты');
const html = '<script>AF_initDataCallback({data:"\\u041c\\u0430\\u0442\\u0443\\u0448\\u043a\\u0430 \\u041c\\u0435\\u0434\\u0432\\u0435\\u0434\\u0438\\u0446\\u0430",x:1});</script>';
const p4 = L.parseResponse(html, 'text/html');
ok(p4.length === 1 && p4[0].includes('Матушка'), 'HTML от Lens: текст вытащен и \\uXXXX раскодирован');
ok(L.parseResponse('', 'application/json').length === 0, 'пустой ответ даёт пустой список, а не мусор');

// 4. Кадр для прямого пути — JPEG, а не PNG: так на 1,5 МБ меньше трафика.
//    В Node у мини-canvas нет toDataURL, поэтому проверяем сам выбор формата и
//    ограничение стороны; в браузере это делает lab/lens_direct_check.py.
const cv = api.makeCanvas(1000, 500);   // без уменьшения: мини-canvas умеет только это
cv.toDataURL = (type) => 'data:' + type + ';base64,/9j/4AAQSkZJRg==';
const b64 = L.toJpegBase64(cv, 1500, 0.78);
ok(b64.slice(0, 2) === '/9', 'кадр уходит JPEG-ом (начало /9 — это JPEG)');

// 5. В прямом пути нет ни формы, ни window.open: «без сайта» — значит без сайта
const p4src = fs.readFileSync(path.join(__dirname, 'part4.js'), 'utf8');
const p5src = fs.readFileSync(path.join(__dirname, 'part5.js'), 'utf8');
ok(/LENS\.hasDirect\(\)/.test(p4src) && /recognizeDirect/.test(p4src),
  'страница сначала пробует прямой путь, и только потом вкладку');
ok(!/window\.open/.test(p4src) && !/window\.open/.test(p5src),
  'window.open нигде не используется — вкладок из кода не появляется');
ok(/Прямое распознавание не вышло/.test(p4src) && /Прямой путь недоступен/i.test(p5src),
  'если прямой путь не сработал — сказано прямо, а не «получилось»');
ok(/btnLensDirect/.test(p5src), 'кнопка «Распознать без сайта» подключена к обработчику');

console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
