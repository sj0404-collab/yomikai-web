// Плагины: правки поведения ФАЙЛОМ JSON, без пересборки АПК.
//
// Проверяем ровно то, ради чего это сделано: правила и замены слов приезжают
// из файла, применяются поверх сохранённых настроек, и один кривой плагин не
// ломает чтение.
const fs = require('fs');
require('./shim.js');
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
global.indexedDB = undefined;
global.document.getElementById = () => ({ textContent: '', innerHTML: '', style: {}, dataset: {},
  value: '', checked: false, classList: { contains: () => false, add() {}, remove() {}, toggle() {} },
  addEventListener() {}, appendChild() {}, closest() { return null; },
  getBoundingClientRect: () => ({ top: 0, bottom: 800, height: 800, left: 0, right: 700 }) });
global.document.querySelector = () => global.document.getElementById();
global.document.querySelectorAll = () => [];
global.document.addEventListener = () => {};

const body = ['part0-wasm.js', 'part2.js', 'part3.js']
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Plugins, sanitizeRules, fixLookalikes, readingOrder, DEFAULT_RULES};')();
const { Plugins } = api;

(async () => {
  // ── 1. Без моста (браузер) плагинов нет и это не ошибка
  delete global.window.KomaPlugins;
  await Plugins.load();
  ok(Plugins.present() === false, 'в браузере моста плагинов нет');
  ok(Plugins.list.length === 0, 'и список пуст — страница работает как раньше');
  ok(/не в приложении/.test(Plugins.describe()), 'человеку честно сказано, где плагины живут');

  // ── 2. Мост отдал плагины: правила и замены применяются
  global.window.KomaPlugins = {
    all: () => JSON.stringify({
      ok: true, dir: '/data/plugins',
      sources: ['assets/plugins/00-example.json', 'plugins/mine.json'],
      problems: [],
      plugins: [
        { id: 'base', name: 'База', order: 10, rules: { pageSide: 1280 }, _source: 'assets/plugins/00-example.json' },
        { id: 'mine', name: 'Мои правки', order: 20, rules: { pageSide: 1024 },
          wordFixes: { 'ПОШЕВЕАИТЬСЯ': 'ПОШЕВЕЛИТЬСЯ' },
          replace: [{ from: 'ГОВОРЯ.ш', to: 'ГОВОРИШЬ' }],
          _source: 'plugins/mine.json' },
      ],
    }),
    reload: () => {},
  };
  await Plugins.load();
  ok(Plugins.list.length === 2, 'плагины прочитались из моста');
  ok(Plugins.present() === true, 'мост виден странице');
  ok(/Мои правки/.test(Plugins.describe()), 'в настройках видно, какие плагины загружены');
  ok(/\/data\/plugins/.test(Plugins.describe()), 'видно папку, куда класть файлы');

  // order: последний главнее
  const rules = Plugins.rules();
  ok(rules.pageSide === 1024, 'правила применяются по порядку order (последний главнее): ' + rules.pageSide);
  ok(Plugins.ordered()[1].id === 'mine', 'сортировка по order работает');

  // ── 3. Слова и точечные замены
  ok(Plugins.text('ГОВОРЯ.ш ПО ПРАВДЕШЬ') === 'ГОВОРИШЬ ПО ПРАВДЕШЬ',
    'точечная замена из плагина: «' + Plugins.text('ГОВОРЯ.ш ПО ПРАВДЕШЬ') + '»');
  ok(/ПОШЕВЕЛИТЬСЯ/.test(Plugins.text('ПОШЕВЕАИТЬСЯ')), 'словарная правка из плагина применяется');
  ok(Plugins.text('пошевеаиться') === 'пошевелиться' || /пошевел/i.test(Plugins.text('пошевеаиться')),
    'правка работает и в нижнем регистре: «' + Plugins.text('пошевеаиться') + '»');
  ok(Plugins.text('') === '', 'пустая строка не ломается');

  // ── 4. Правила плагинов накладываются на сохранённые настройки
  const merged = api.sanitizeRules({ speed: 'fast' }, Plugins.rules());
  ok(merged.pageSide === 1024, 'правило из плагина главнее профиля скорости: ' + merged.pageSide);
  ok(api.sanitizeRules({ speed: 'fast' }).pageSide === 1280, 'без плагина профиль скорости работает как раньше');

  // ── 5. Сломанный плагин не валит чтение
  global.window.KomaPlugins.all = () => 'не json';
  await Plugins.load();
  ok(Plugins.list.length === 0 && Plugins.problems.length === 1,
    'кривой JSON не роняет страницу, а попадает в список ошибок: ' + Plugins.problems[0]);
  ok(Plugins.text('текст') === 'текст', 'без плагинов текст остаётся как есть');

  // ── 6. Мост в АПК: имена и файлы
  const kt = fs.readFileSync(__dirname + '/apk/app/src/main/java/net/koma/reader/KomaPluginsBridge.kt', 'utf8');
  const main = fs.readFileSync(__dirname + '/apk/app/src/main/java/net/koma/reader/MainActivity.kt', 'utf8');
  ok(/KomaPlugins/.test(main), 'мост зарегистрирован под именем KomaPlugins');
  ok(/filesDir, "plugins"/.test(kt), 'пользовательские плагины читаются из папки приложения');
  ok(/assets\.open\("plugins\//.test(kt), 'вшитые плагины читаются из assets/plugins');
  ok(fs.existsSync(__dirname + '/apk/app/src/main/assets/plugins/00-example.json'),
    'образец формата вшит в сборку — человеку есть с чего начать');

  console.log(process.exitCode ? 'ЕСТЬ ПАДЕНИЯ' : 'ALL PASSED');
  process.exit(process.exitCode || 0);
})().catch(e => { console.log('FAIL исключение: ' + (e && e.message)); console.log(e && e.stack); process.exit(1); });
