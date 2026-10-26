// Полноценная DOM-заглушка для тестов обработчиков (bindUI и т.п.).
// Раньше лежала в /tmp и терялась вместе с песочницей.
const fs = require('fs');
const htmlPath = fs.existsSync(__dirname + '/part1.html')
  ? __dirname + '/part1.html'
  : __dirname + '/koma-web.html';
const html = fs.readFileSync(htmlPath, 'utf8');

const ids = [...html.matchAll(/id="([^"]+)"/g)].map(m => m[1]);
const els = new Map();

class ClassList {
  constructor() { this.s = new Set(); }
  add(c) { this.s.add(c); }
  remove(c) { this.s.delete(c); }
  contains(c) { return this.s.has(c); }
  toggle(c, on) { if (on === undefined) { this.s.has(c) ? this.s.delete(c) : this.s.add(c); } else if (on) this.s.add(c); else this.s.delete(c); }
}

function makeEl(id) {
  const el = {
    id, textContent: '', innerHTML: '', value: '', disabled: false, files: null, checked: false,
    style: {}, dataset: {}, children: [], classList: new ClassList(),
    _l: {},
    addEventListener(type, fn) {
      // Тесты дёргают обработчик как el.onchange(); храним список и вешаем
      // обёртку, чтобы «как в браузере» работали оба способа.
      (this._l[type] = this._l[type] || []).push(fn);
      if (!this['on' + type]) {
        // async и с await: тест ждёт `await el.onchange()` — обработчик у нас
        // асинхронный, без await тест проверял состояние до его завершения.
        this['on' + type] = async (ev) => {
          for (const f of this._l[type]) await f(ev || { target: this, currentTarget: this });
        };
      }
    },
    removeEventListener(type, fn) { this._l[type] = (this._l[type] || []).filter(f => f !== fn); },
    appendChild(c) { this.children.push(c); return c; },
    removeChild() {}, remove() {},
    querySelector() { return makeEl('tmp-' + Math.random()); },
    querySelectorAll() { return []; },
    getBoundingClientRect: () => ({ top: 0, bottom: 800, height: 800, left: 0, right: 700, width: 700 }),
    scrollIntoView() {}, scrollTo() {}, focus() {}, click() {},
    setAttribute(k, v) { this[k] = v; }, getAttribute(k) { return this[k]; },
    insertAdjacentHTML() {},
  };
  return el;
}

function getById(id) {
  if (!els.has(id)) els.set(id, makeEl(id));
  return els.get(id);
}
// Все id из разметки доступны сразу — как в настоящем документе.
for (const id of ids) getById(id);

global.document = {
  getElementById: getById,
  querySelector: (sel) => getById(String(sel).replace(/^[#.]/, '').split(/[\s:>]/)[0] || 'tmp'),
  querySelectorAll: () => [],
  addEventListener() {},
  createElement: (tag) => {
    if (tag === 'canvas') {
      const c = { _w: 0, _h: 0, data: null, width: 0, height: 0, getContext: () => ({ drawImage() {}, getImageData: (x, y, w, h) => ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h }) }) };
      return c;
    }
    return makeEl('new-' + tag + '-' + Math.random());
  },
  body: makeEl('body'),
};
global.window = { innerHeight: 800, addEventListener() {}, matchMedia: () => ({ matches: false, addEventListener() {} }) };
global.navigator = { userAgent: 'Node' };
global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
global.speechSynthesis = { getVoices: () => [], speak() {}, cancel() {}, pause() {}, resume() {}, speaking: false };
global.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; } };
global.performance = { now: () => Date.now() };
// В узле IndexedDB нет. Без этой строки DB ждёт 3 секунды таймаута и уходит
// в память — тесты становились медленными и нестабильными.
global.indexedDB = undefined;
global.URL.createObjectURL = () => '';
global.URL.revokeObjectURL = () => {};
global.alert = () => {};
global.File = class {
  constructor(parts, name) {
    this.name = name; this._parts = parts || [];
    this.size = (parts && parts[0] && parts[0].length) || 1;
  }
  slice() { return this; }
  arrayBuffer() { return Promise.resolve(this._parts[0] || new ArrayBuffer(1)); }
  // cyrillic.txt читается как текст: без text() третий файл «не принимался».
  text() { return Promise.resolve(typeof this._parts[0] === 'string' ? this._parts[0] : 'алфавит'); }
};
global.Blob = class { constructor() {} };
global.fetch = async () => ({ ok: true, arrayBuffer: async () => new ArrayBuffer(1), text: async () => '' });

module.exports = { getById, els };
