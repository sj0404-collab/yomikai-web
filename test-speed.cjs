// Профили скорости и «само ничего не запускается».
const fs = require('fs');
require('./shim.js');
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
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {RULES, DEFAULT_RULES, SPEED_PRESETS, SPEED_NAMES, sanitizeRules, Reader};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

// 1. Четыре профиля, все на месте
// Пять профилей: к четырём прежним добавился «Умно» (28.10).
ok(Object.keys(api.SPEED_PRESETS).length === 5, 'пять профилей скорости');
ok(Object.keys(api.SPEED_NAMES).length === 5, 'у всех профилей есть русские названия');
ok(Object.keys(api.SPEED_NAMES).every(k => api.SPEED_PRESETS[k]),
  'у каждого профиля есть и пресет, и название — списки не разъехались');

// 2. По умолчанию — не самый медленный и без самозапуска
const def = api.sanitizeRules({});
ok(def.speed === 'fast', 'по умолчанию «Быстро», а не прежнее «Обычно» (speed=' + def.speed + ')');
ok(def.autoScan === false, 'само распознавание по умолчанию выключено');

// 3. Профиль главнее сохранённых чисел
const fromOldSave = api.sanitizeRules({ speed: 'lightning', pageSide: 1600, decodeVariants: true, detRetry: true });
ok(fromOldSave.pageSide === 960, 'старый pageSide 1600 не отменяет профиль (стало ' + fromOldSave.pageSide + ')');
ok(fromOldSave.decodeVariants === false && fromOldSave.detRetry === false, 'перебор и повтор детектора выключены профилем');

// 4. Тщательно — наоборот, включает всё
const th = api.sanitizeRules({ speed: 'thorough' });
ok(th.pageSide === 1920 && th.decodeVariants && th.uncoveredPass && th.largeText,
  '«Тщательно» включает все проходы (кадр ' + th.pageSide + ')');

// 5. Мусорный профиль не ломает правила
const bad = api.sanitizeRules({ speed: 'турбо' });
ok(bad.speed === 'fast', 'неизвестный профиль → «Быстро»');
ok(bad.junkRatio > 0 && bad.minConfidence >= 0, 'остальные правила остались рабочими');

// 6. Прежняя скорость достижима: «Обычно» = что было по умолчанию в v1.9.13
const n = api.sanitizeRules({ speed: 'normal' });
ok(n.pageSide === 1600 && n.largeText === true && n.uncoveredPass === true && n.decodeVariants === true,
  '«Обычно» совпадает с прежним поведением (pageSide 1600, все проходы)');

// 7. Карточка старта и её кнопки существуют в разметке
const html = fs.readFileSync(__dirname + '/part1.html', 'utf8');
for (const id of ['startCard', 'btnStartScan', 'btnStartRead', 'btnStartClose', 'cbAutoScan', 'speedChips', 'speedHint']) {
  ok(html.includes('id="' + id + '"'), 'в разметке есть #' + id);
}
for (const sp of ['lightning', 'fast', 'smart', 'normal', 'thorough']) {
  ok(html.includes('data-speed="' + sp + '"'), 'чип скорости ' + sp);
}

// 7b. Профиль «Умно»: скорость «Быстро», а дорогой перебор — только на трудных
// строках. Проверяем контракт, а не цифры: дешёвый детектор, дожим включён,
// потолок вариантов есть, и профиль не превращается в «Обычно».
const sm = api.sanitizeRules({ speed: 'smart' });
ok(sm.decodeVariants === true && sm.extCrop === true,
  '«Умно»: перебор вариантов и расширения кропа включены (это и даёт верные слова)');
ok(sm.autoDepth === true && sm.maxVariants >= 1 && sm.maxVariants < 6,
  '«Умно»: перебор идёт по гейту и не больше ' + sm.maxVariants + ' подготовок на строку');
ok(sm.maxDeepVariants > 0 && sm.maxDeepVariants <= 10,
  '«Умно»: потолок дорогих подготовок на строку = ' + sm.maxDeepVariants);
ok(api.SPEED_NAMES.smart === 'Умно', 'у профиля есть человеческое имя');
// профиль перебивает сохранённые числа — иначе «Умно» молча станет «Обычно»
const sm2 = api.sanitizeRules({ speed: 'smart', pageSide: 1600, autoDepth: false });
ok(sm2.pageSide === 1600 && sm2.autoDepth === true,
  '«Умно» не перебивается старыми сохранёнными значениями');


// 8. Чистая установка: правила обязаны пройти sanitize, иначе профиль не работает
const fresh = api.sanitizeRules({});                      // как в boot без сохранённых правил
ok(fresh.pageSide !== api.DEFAULT_RULES.pageSide,
  'профиль применяется и на чистой установке (pageSide ' + fresh.pageSide
  + ' вместо голых ' + api.DEFAULT_RULES.pageSide + ')');
ok(fresh.decodeVariants === false && fresh.uncoveredPass === false,
  'на чистой установке перебор и третий проход выключены — «Быстро» это не только слово');
ok(fresh.bandOverlap === 0, 'запас полосы по умолчанию 0: полоса = ровно экран');


// 9. Конвейер: по умолчанию выключен, включается осознанно
ok(api.sanitizeRules({}).pipeline === true, 'конвейер включён по умолчанию (нужна скорость)');
ok(api.sanitizeRules({ pipeline: false }).pipeline === false, 'конвейер отключается правилом');

console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
