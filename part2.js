'use strict';
/* ───────────────────────── 0. Мелкие утилиты ───────────────────────── */
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
function toast(msg, ms = 2200) {
  const el = $('#toast');
  el.textContent = msg; el.classList.add('on');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove('on'), ms);
}
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
// Macrotask-пауза: await внутри async-цепочек даёт только микрозадачи, браузер
// не рисует и не обрабатывает ввод — на телефоне бейдж «Распознаём…» замирает
// и страница выглядит зависшей. setTimeout отдаёт главный поток браузеру.
const yieldUI = () => new Promise(r => setTimeout(r, 0));

const VERSION = 'v1.9.21';

/* ───────────────────────── 1. Хранилище (IndexedDB) ─────────────────────────
   Всё локально: книги — блобы страниц, модели — ArrayBuffer, правила — JSON.
   Ничего не уходит в сеть: сервера у этой страницы нет.                        */
const DB = (() => {
  let dbp = null;
  // Если IndexedDB недоступен (предпросмотр в песочнице без same-origin),
  // работаем в памяти: библиотека и чтение живут до перезагрузки страницы,
  // но кнопки не «молчат».
  const memory = { books: new Map(), pages: new Map(), kv: new Map() };
  let useMemory = false;
  const memApi = {
    put: async (store, val) => {
      const key = store === 'books' ? val.id : store === 'pages' ? val.key : val.k;
      memory[store].set(key, val);
    },
    get: async (store, key) => memory[store].get(key),
    del: async (store, key) => { memory[store].delete(key); },
    all: async (store) => Array.from(memory[store].values()),
    clear: async (store) => { memory[store].clear(); },
  };
  function open() {
    if (dbp) return dbp;
    const raw = new Promise((res, rej) => {
      const r = indexedDB.open('koma-web', 1);
      r.onupgradeneeded = () => {
        const db = r.result;
        if (!db.objectStoreNames.contains('books')) db.createObjectStore('books', { keyPath: 'id' });
        if (!db.objectStoreNames.contains('pages')) db.createObjectStore('pages', { keyPath: 'key' });
        if (!db.objectStoreNames.contains('kv')) db.createObjectStore('kv', { keyPath: 'k' });
      };
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error || new Error('indexedDB открыть не удалось'));
      r.onblocked = () => rej(new Error('indexedDB заблокирован другой вкладкой'));
    });
    // Страховка: если браузер не ответил за 3 секунды (песочница, приватный
    // режим, «зависшая» вкладка), не висим навсегда — уходим в память.
    // Иначе любая запись (буфер, модели, книги) молча не завершалась.
    const timeout = new Promise((_, rej) => setTimeout(() => rej(new Error('indexedDB не ответил за 3 с')), 3000));
    dbp = Promise.race([raw, timeout]);
    return dbp;
  }
  async function tx(store, mode, fn) {
    const db = await open();
    return new Promise((res, rej) => {
      const t = db.transaction(store, mode);
      const s = t.objectStore(store);
      let out;
      const p = fn(s);
      if (p && p.onsuccess !== undefined) p.onsuccess = () => { out = p.result; };
      t.oncomplete = () => res(out);
      t.onerror = () => rej(t.error);
    });
  }
  const realApi = {
    put: (store, val) => tx(store, 'readwrite', s => s.put(val)),
    get: (store, key) => tx(store, 'readonly', s => s.get(key)),
    del: (store, key) => tx(store, 'readwrite', s => s.delete(key)),
    all: (store) => tx(store, 'readonly', s => s.getAll()),
    clear: (store) => tx(store, 'readwrite', s => s.clear()),
  };
  const wrap = (fn) => async (...args) => {
    if (useMemory) return memApi[fn.name](...args);
    try { return await realApi[fn.name](...args); }
    catch (e) {
      if (useMemory) return memApi[fn.name](...args);
      // Первый же отказ — переходим в память и говорим об этом один раз.
      console.warn('IndexedDB недоступен, работаю в памяти:', e);
      useMemory = true;
      DB.inMemory = true;
      return memApi[fn.name](...args);
    }
  };
  return {
    inMemory: false,
    put: wrap({ name: 'put' }), get: wrap({ name: 'get' }), del: wrap({ name: 'del' }),
    all: wrap({ name: 'all' }), clear: wrap({ name: 'clear' }),
  };
})();

/* ───────────────────────── 2. ZIP/CBZ без библиотек ─────────────────────────
   Используем DecompressionStream('deflate-raw') — есть в Chrome 80+/Safari 16+. */
async function unzip(buf) {
  const dv = new DataView(buf);
  const u8 = new Uint8Array(buf);
  // ищем End of Central Directory
  let eocd = -1;
  for (let i = u8.length - 22; i >= Math.max(0, u8.length - 66000); i--) {
    if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error('не ZIP');
  const count = dv.getUint16(eocd + 10, true);
  let off = dv.getUint32(eocd + 16, true);
  const files = [];
  for (let i = 0; i < count; i++) {
    if (dv.getUint32(off, true) !== 0x02014b50) break;
    const method = dv.getUint16(off + 10, true);
    const csize = dv.getUint32(off + 20, true);
    const nameLen = dv.getUint16(off + 28, true);
    const extraLen = dv.getUint16(off + 30, true);
    const cmtLen = dv.getUint16(off + 32, true);
    const localOff = dv.getUint32(off + 42, true);
    const name = new TextDecoder().decode(u8.subarray(off + 46, off + 46 + nameLen));
    off += 46 + nameLen + extraLen + cmtLen;
    if (name.endsWith('/')) continue;
    if (!/\.(jpe?g|png|webp|avif|bmp|gif)$/i.test(name)) continue;
    // локальный заголовок
    const lnLen = dv.getUint16(localOff + 26, true);
    const leLen = dv.getUint16(localOff + 28, true);
    const dataStart = localOff + 30 + lnLen + leLen;
    const raw = u8.subarray(dataStart, dataStart + csize);
    let data;
    if (method === 0) data = raw.slice();
    else if (method === 8) {
      const ds = new DecompressionStream('deflate-raw');
      const blob = new Blob([raw.slice()]);
      data = new Uint8Array(await new Response(blob.stream().pipeThrough(ds)).arrayBuffer());
    } else throw new Error('метод сжатия ' + method);
    files.push({ name, data });
  }
  files.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }));
  return files;
}

/* ───────────────────────── 3. Библиотека ───────────────────────── */
const Library = {
  books: [],
  async load() {
    this.books = (await DB.all('books') || []).sort((a, b) => (b.at || 0) - (a.at || 0));
    renderLibrary();
  },
  /**
   * Добавить страницы в СУЩЕСТВУЮЩУЮ главу.
   *
   * Зачем: в браузере на Android нельзя выбрать папку (SAF вебу недоступен), а
   * файловый выбор за один раз редко даёт все 20 страниц. Так можно добавлять
   * по частям — в ту же книгу, с продолжением нумерации.
   */
  async appendTo(bookId, files) {
    const book = await DB.get('books', bookId);
    if (!book) throw new Error('глава не найдена');
    const start = book.count || 0;
    for (let k = 0; k < files.length; k++) {
      const f = files[k];
      const name = String(f.name || ('page-' + (start + k))).split('/').pop();
      await DB.put('pages', { key: bookId + '/' + (start + k), id: bookId, index: start + k, name, blob: f.blob || f });
    }
    book.count = start + files.length;
    book.at = Date.now();
    await DB.put('books', book);
    return book;
  },
  async addBook(title, files, kind) {
    const id = 'b' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    const pages = [];
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      const name = f.name.split('/').pop();
      const blob = f.blob || new Blob([f.data], { type: mimeOf(name) });
      const key = id + '/' + i;
      await DB.put('pages', { key, id, index: i, name, blob });
      pages.push({ key, name });
    }
    const cover = pages.length ? (await DB.get('pages', pages[0].key))?.blob : null;
    const book = { id, title, kind, count: pages.length, at: Date.now(), progress: 0, mode: 'vertical', cover };
    await DB.put('books', book);
    return book;
  },
  async pages(bookId) {
    const rows = (await DB.all('pages') || []).filter(p => p.id === bookId);
    rows.sort((a, b) => a.index - b.index);
    return rows;
  },
  async remove(bookId) {
    const rows = (await DB.all('pages') || []).filter(p => p.id === bookId);
    for (const p of rows) await DB.del('pages', p.key);
    await DB.del('books', bookId);
  },
};
function mimeOf(name) {
  const e = name.split('.').pop().toLowerCase();
  return e === 'png' ? 'image/png' : e === 'webp' ? 'image/webp' : e === 'gif' ? 'image/gif' : 'image/jpeg';
}

function renderLibrary() {
  const grid = $('#libGrid');
  $('#libEmpty').style.display = Library.books.length ? 'none' : 'block';
  grid.innerHTML = '';
  for (const b of Library.books) {
    const el = document.createElement('div');
    el.className = 'card';
    el.dataset.armed = '0';
    const url = b.cover ? URL.createObjectURL(b.cover) : '';
    el.innerHTML = `${url ? `<img src="${url}" alt="">` : '<div class="nofoto">нет обложки</div>'}
      <button class="del">✕</button>
      <div class="cap">${escapeHtml(b.title)}<span>${b.count} стр. · ${b.mode === 'vertical' ? 'лента' : b.mode === 'rtl' ? 'справа налево' : 'слева направо'}</span></div>`;
    // confirm() в предпросмотре и части мобильных браузеров глушится, поэтому
    // спрашиваем вторым нажатием, а не модалкой.
    el.querySelector('.del').onclick = async (e) => {
      e.stopPropagation();
      if (el.dataset.armed !== '1') {
        el.dataset.armed = '1';
        el.querySelector('.del').textContent = '?';
        toast('Нажмите ✕ ещё раз, чтобы удалить «' + b.title + '»');
        setTimeout(() => {
          if (el.dataset.armed === '1') { el.dataset.armed = '0'; el.querySelector('.del').textContent = '✕'; }
        }, 3000);
        return;
      }
      await Library.remove(b.id); await Library.load();
      toast('Удалено');
    };
    el.onclick = () => openBook(b);
    grid.appendChild(el);
  }
}
/**
 * Открыть книгу. Раньше карточка звала openBook(), а такой функции не было
 * вовсе: тап по книге молча ничего не делал. Ошибки теперь видно, а не в консоли.
 */
async function openBook(book) {
  try {
    await Reader.open(book);
  } catch (e) {
    console.error('openBook', e);
    toast('Не удалось открыть «' + book.title + '»: ' + (e && e.message ? e.message : e), 5000);
  }
}
const escapeHtml = (s) => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* Импорт: папка / CBZ / отдельные картинки */
async function importDir(fileList) {
  const imgs = Array.from(fileList).filter(f => /\.(jpe?g|png|webp|avif|bmp|gif)$/i.test(f.name));
  if (!imgs.length) return toast('В выбранной папке нет картинок');
  imgs.sort((a, b) => a.webkitRelativePath.localeCompare(b.webkitRelativePath, undefined, { numeric: true }));
  const title = (imgs[0].webkitRelativePath || imgs[0].name).split('/')[0] || 'Глава';
  toast('Сохраняю ' + imgs.length + ' страниц…', 5000);
  await Library.addBook(title, imgs.map(f => ({ name: f.name, blob: f })), 'dir');
  await Library.load();
  toast('Добавлено: ' + title + ' (' + imgs.length + ' стр.)');
}
async function importZip(file) {
  toast('Разбираю архив…', 5000);
  const files = await unzip(await file.arrayBuffer());
  if (!files.length) return toast('В архиве нет картинок');
  const title = file.name.replace(/\.(cbz|zip)$/i, '');
  await Library.addBook(title, files, 'zip');
  await Library.load();
  toast('Добавлено: ' + title + ' (' + files.length + ' стр.)');
}
