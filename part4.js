
/* ───────────────────────── 8. Читалка ───────────────────────── */
const Reader = {
  book: null, pages: [], urls: [], canvases: [], imgEls: [],
  mode: 'vertical', dir: 'rtl', page: 0, frames: true, follow: true,
  regions: new Map(),          // page → {regions, boxes, ms}
  bandCache: new Map(),        // page → Map(ключ полосы → распознанное)
                               // (поле bands занято массивом полос из bandsOf)
  spoken: new Set(),        // «стр|текст» — что уже прочитано вслух
  spokenDirty: false,
  current: null,
  scrollBusy: false,

  async open(book) {
    this.book = book;
    this.pages = await Library.pages(book.id);
    if (!this.pages.length) return toast('В книге нет страниц');
    this.mode = book.mode || 'vertical';
    this.dir = book.dir || 'rtl';
    this.page = clamp(book.progress || 0, 0, this.pages.length - 1);
    this.regions.clear();
    // Что уже прочитано — из базы: после остановки и даже перезапуска чтение
    // продолжается с первого непрочитанного места, а не с начала страницы.
    this.spoken = new Set((await DB.get('kv', 'spoken:' + book.id))?.v || []);
    // Уже распознанные страницы берём из буфера: повторное открытие книги и
    // повторное чтение не должны снова стоить 10 секунд на страницу.
    let cleaned = 0;
    try {
      const buf = await Buffer.all();
      for (const row of buf) {
        if (row && Array.isArray(row.lines) && row.lines.length) {
          // Текст в буфере распознан прежней версией — прогоняем его через
          // нынешние правила чистки, иначе старый мусор («Тг. чв») живёт вечно.
          const lines = await cleanLines(row.lines);
          this.regions.set(row.page, { lines, regions: null, cached: true, ms: 0, detMs: 0, recMs: 0, crops: lines.length, boxes: 0 });
          if (lines.length !== row.lines.length) {
            await Buffer.put(row.page, lines);
            cleaned++;
          }
        }
      }
      if (buf.length) toast('Из буфера: ' + buf.length + ' стр. уже распознаны', 3000);
    } catch (e) { console.warn('буфер не прочитался', e); }
    $('#rTitle').textContent = book.title;
    $('#pageTotal').textContent = String(this.pages.length);
    show('reader');
    this.syncSub();
    await this.buildStrip();
    this.scrollToPage(this.page, false);
    // Ничего не запускаем сами: сначала человек видит, что происходит.
    if (!this.regions.get(this.page)) this.showStart(); else this.hideStart();
  },

  syncSub() {
    const modeText = (this.mode === 'vertical' ? 'Вертикально' : this.mode === 'rtl' ? 'Страницы' : 'Страницы')
      + ' · ' + (this.dir === 'rtl' ? '← справа налево' : 'слева направо →');
    $('#rSub').textContent = `KOMA · веб · ${this.page + 1} из ${this.pages.length} · ${modeText}`;
    $('#pageNum').textContent = String(this.page + 1);
  },

  async buildStrip() {
    const strip = $('#strip');
    if (this.ratios && Object.keys(this.ratios).length) {
      const vals = Object.values(this.ratios);
      this.bookRatio = vals.reduce((a, b) => a + b, 0) / vals.length;
    }
    strip.innerHTML = '';
    this.urls.forEach(u => URL.revokeObjectURL(u));
    this.urls = []; this.imgEls = []; this.canvases = [];
    strip.style.display = this.mode === 'vertical' ? 'block' : 'none';
    $('#paged').classList.toggle('on', this.mode !== 'vertical');
    if (this.mode === 'vertical') {
      for (let i = 0; i < this.pages.length; i++) {
        const wrap = document.createElement('div');
        wrap.className = 'pagewrap'; wrap.dataset.page = i;
        // Место под страницу резервируется сразу: пропорция известна из буфера
        // (если страницу уже открывали) или берётся средняя по книге.
        wrap.style.aspectRatio = String((this.ratios && this.ratios[i]) || this.bookRatio || 0.7);
        const img = document.createElement('img');
        img.alt = 'Страница ' + (i + 1);
        img.decoding = 'async';
        img.onload = () => { this.onPageSized(i); };
        wrap.appendChild(img);
        const frames = document.createElement('div');
        frames.className = 'frames'; frames.dataset.frames = i;
        wrap.appendChild(frames);
        strip.appendChild(wrap);
        this.imgEls[i] = img;
        this.paintPage(i);
      }
    } else {
      const paged = $('#paged');
      paged.innerHTML = '';
      for (let i = 0; i < this.pages.length; i++) {
        const box = document.createElement('div');
        box.className = 'pagebox'; box.dataset.page = i;
        box.innerHTML = '<div class="inner"><img alt="Страница ' + (i + 1) + '"></div>';
        paged.appendChild(box);
        this.imgEls[i] = box.querySelector('img');
        this.imgEls[i].onload = () => this.onPageSized(i);
      }
    }
    // грузим страницы лениво: сначала текущую и соседние
    for (const i of this.loadOrder()) this.ensureLoaded(i);
  },

  loadOrder() {
    const out = [];
    for (let d = 0; d <= this.pages.length; d++) {
      for (const i of [this.page - d, this.page + d]) {
        if (i >= 0 && i < this.pages.length && !out.includes(i)) out.push(i);
      }
      if (out.length > 6) break;
    }
    return out;
  },

  async ensureLoaded(i) {
    const img = this.imgEls[i];
    if (!img || img.dataset.src) return;
    img.dataset.src = '1';
    const row = this.pages[i];
    const blob = (await DB.get('pages', row.key))?.blob;
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    this.urls[i] = url;
    img.src = url;
  },

  async onPageSized(i) {
    const img = this.imgEls[i];
    if (!img || !img.naturalWidth) return;
    // Запоминаем пропорции: без этого незагруженные страницы схлопывались в 0
    // по высоте, лента прыгала, и «текущая страница» определялась неверно.
    const ratio = img.naturalWidth / img.naturalHeight;
    this.ratios = this.ratios || {};
    if (!this.ratios[i]) {
      this.ratios[i] = ratio;
      const wrap = document.querySelector(`.pagewrap[data-page="${i}"]`);
      if (wrap) wrap.style.aspectRatio = String(ratio);
    }
    if (!this.canvases[i]) {
      // рабочий холст для OCR — один раз на страницу
      this.canvases[i] = canvasFromImage(img);
    }
    this.paintPage(i);
    if (i === this.page) this.afterPageReady();
  },

  paintPage(i) {
    const framesEl = this.mode === 'vertical'
      ? document.querySelector(`[data-frames="${i}"]`)
      : null;
    if (!framesEl) return;
    framesEl.innerHTML = '';
    if (!this.frames) return;
    const data = this.regions.get(i);
    if (!data) return;
    // Рамка рисуется КАЖДОЙ распознанной строке, независимо от того, прочитана
    // она или нет. «Прочитано» — это только цвет (класс done), а не фильтр.
    data.lines.forEach((line, idx) => {
      const d = document.createElement('div');
      d.className = 'frame';
      d.style.left = (line.left * 100) + '%';
      d.style.top = (line.top * 100) + '%';
      d.style.width = ((line.right - line.left) * 100) + '%';
      d.style.height = ((line.bottom - line.top) * 100) + '%';
      const isCur = this.current && this.current.text === line.text;
      const isDone = this.spoken.has(this.spokenKey(i, line.text));
      if (line.large) d.classList.add('large');     // титул/каллиграфия — другой цвет
      // Текст из Lens: координат нет, полосы равные — честно помечаем пунктиром
      // и номером, чтобы «рамка» не выглядела точным местом на картинке.
      if (line.fromLens || data.fromLens) {
        // 'det' — рамка стоит на облачке, найденном локальным детектором;
        // 'band' — координат нет вовсе, полосы равные (пунктир + номер).
        d.classList.add('approx');
        const n = document.createElement('span');
        n.className = 'fnum';
        n.textContent = String(idx + 1);
        d.appendChild(n);
      }
      if (isCur) d.classList.add('cur');
      else if (isDone) d.classList.add('done');
      d.onclick = () => TTS.speakLine(line);
      framesEl.appendChild(d);
    });
  },

  paintAllFrames() {
    for (let i = 0; i < this.pages.length; i++) this.paintPage(i);
  },

  afterPageReady() {
    const i = this.page;
    const c = this.canvases[i];
    if (!c) return;
    // Видимая доля страницы: полосы (как KomaBands в АПК)
    const rect = this.pageRect(i);
    const vp = window.innerHeight - 0;
    const frac = rect && rect.height > 0 ? clamp(vp / rect.height, 0.12, 1) : 1;
    this.bands = bandsOf(frac, RULES);
    this.band = this.bands[clamp(this.bandIndex || 0, 0, this.bands.length - 1)];
    this.syncSub();
    if (RULES.semiManual && State.semi) return;         // ждём остановки и прокрутки
    // Буфер прошлой версии хранит страницу, распознанную ЦЕЛИКОМ. Для длинной
    // страницы это лишние реплики за пределами экрана — такую пересчитываем
    // видимой полосой один раз (полоса запомнится в bandCache).
    const data = this.regions.get(i);
    const staleFull = data && data.cached && this.visibleBandPx(i);
    // Само ничего не запускаем: человек сам сказал «Распознать» (или включил
    // автозапуск в настройках). Иначе при открытии страницы начиналось
    // распознавание, и было непонятно, что вообще происходит.
    if (!this.scrollBusy && (!data || staleFull)) {
      if (RULES.autoScan) { this.hideStart(); this.scanCurrent(false); }
      else this.showStart();
    }
    if (data && !staleFull) this.hideStart();     // страница уже распознана
  },

  /**
   * Какая страница РЕАЛЬНО на экране — по геометрии, а не по сохранённому
   * индексу. Раньше считалось только внутри обработчика scroll и только когда
   * у страницы уже был загружен образ; при ленивой загрузке (высота 0 до
   * загрузки) и после автолистания индекс «застревал»: на экране первая
   * страница, а шапка и распознавание — четвёртая.
   */
  /**
   * Видимая сейчас полоса страницы — в пикселях её кадра.
   *
   * Возвращает null, если страница целиком помещается на экран (обычная
   * страница манги) — тогда распознаём всю. Для длинного вебтуна полоса
   * ограничена экраном плюс небольшим запасом, иначе в реплики попадает текст
   * на два экрана вперёд («нашёл 5 реплик, хотя видно одну»).
   */
  visibleBandPx(i) {
    try { return this.visibleBandPxInner(i); } catch (e) { return null; }
  },
  visibleBandPxInner(i) {
    const c = this.canvases[i];
    const wrap = document.querySelector(`.pagewrap[data-page="${i}"]`);
    const scroller = $('#strip');
    if (!c || !wrap || !scroller || this.mode !== 'vertical') return null;
    const r = wrap.getBoundingClientRect();
    const sr = scroller.getBoundingClientRect();
    if (!r.height || !c.height) return null;
    const scale = c.height / r.height;                 // пиксели кадра на экранный px
    const viewH = scroller.clientHeight || window.innerHeight;
    const overlap = clamp(Number(RULES.bandOverlap) || 0, 0, 0.6);
    // Запас по умолчанию НОЛЬ: полоса = ровно то, что видно на экране.
    // Замер на странице 720×2960: с запасом 200 px — 19,6 с и 147 кропов,
    // ровно экранами — 13,4 с и 120 кропов, текст одинаковый. Разрезанные
    // границей экрана строки ловит защита atEdge в recognizePage.
    const pad = Math.min(r.height * overlap, viewH * 0.25);
    // Экран в координатах страницы
    const topPx = (Math.max(sr.top, r.top) - r.top) + 0;      // видимое начало
    const botPx = (Math.min(sr.top + viewH, r.bottom) - r.top);
    const y0 = clamp((topPx - pad) * scale, 0, c.height);
    const y1 = clamp((botPx + pad) * scale, 0, c.height);
    if (y1 - y0 < 32) return null;
    // Если видно (почти) всю страницу — полоса не нужна
    if (y1 - y0 >= c.height * 0.92) return null;
    // Короткая страница (до 2,2 экрана) читается ЦЕЛИКОМ — как оригинальный
    // KOMA: на скриншоте 11:24 оригинал нашёл 18 областей и 5 реплик на всю
    // страницу, включая «В БУДУЩЕМ, КОГДА ВЫ БУДЕТЕ…» за нижним краем экрана.
    // Полоса нужна только вебтуну в десятки тысяч пикселей.
    if (c.height <= viewH * 2.2) return null;
    const vy0 = clamp(topPx * scale, 0, c.height);
    const vy1 = clamp(botPx * scale, 0, c.height);
    // Границы полосы прилипают к пустому месту страницы: иначе экран режет
    // облачко пополам, и реплика читалась двумя кусками на двух «страницах»
    // («НО РАЗВЕ» отдельно от остального облачка — скриншот 17:30).
    // Если карту «где пусто» построить нельзя (нет canvas/getImageData или
    // страница не отрисована), полоса остаётся как была — это не повод её
    // терять целиком.
    let snap = { y0, y1 };
    try { snap = this.blankSnap(i, y0, y1); } catch (e) { snap = { y0, y1 }; }
    return {
      y0: snap.y0, y1: snap.y1, vy0, vy1,
      key: Math.round(vy0 / 96) + ':' + Math.round(vy1 / 96),
    };
  },

  /**
   * Карта «где на странице пусто»: по строке берём самую тёмную точку. Нужна,
   * чтобы границы полосы не проходили через текст.
   */
  inkRows(i) {
    if (this._ink && this._ink.page === i && this._ink.canvas === this.canvases[i]) return this._ink;
    const c = this.canvases[i];
    if (!c || !c.width) return null;
    try {
    const w = 48;
    const h = Math.max(1, Math.round(c.height * (w / c.width)));
    const t = makeCanvas(w, h);
    const g = t.getContext('2d', { willReadFrequently: true });
    g.drawImage(c, 0, 0, w, h);
    let data;
    try { data = g.getImageData(0, 0, w, h).data; } catch (e) { return null; }
    const dark = new Uint8Array(h);
    for (let y = 0; y < h; y++) {
      let m = 255;
      for (let x = 0; x < w; x++) {
        const o = (y * w + x) * 4;
        const v = Math.min(data[o], data[o + 1], data[o + 2]);
        if (v < m) m = v;
      }
      dark[y] = m;
    }
    this._ink = { page: i, canvas: c, h, dark };
    return this._ink;
    } catch (e) { return null; }        // нет canvas/getImageData — полоса как есть
  },

  /** Сдвинуть границу полосы к ближайшей пустой строке (в пределах допуска). */
  blankSnap(i, y0, y1) {
    const ink = this.inkRows(i);
    const c = this.canvases[i];
    if (!ink || !c) return { y0, y1 };
    const rowOf = (px) => clamp(Math.round(px / c.height * ink.h), 0, ink.h - 1);
    const isBlank = (r) => ink.dark[clamp(r, 0, ink.h - 1)] >= 232;
    const maxShift = Math.round(c.height / ink.h) * 6;      // ~6 строк растра
    const find = (px, dir) => {
      const r0 = rowOf(px);
      for (let d = 0; d <= 6; d++) {
        const r = dir < 0 ? r0 - d : r0 + d;
        if (r < 0 || r >= ink.h) break;
        if (isBlank(r)) return Math.round(r * c.height / ink.h);
      }
      return null;
    };
    let ny1 = y1, ny0 = y0;
    const down = find(y1, +1);
    const up = find(y1, -1);
    // Низ двигаем вниз, если пусто близко; иначе вверх — но не меньше 55 %
    // исходной полосы, иначе начнём резать по живому.
    if (down != null && down - y1 <= maxShift) ny1 = Math.min(c.height, down);
    else if (up != null && y1 - up <= maxShift && up - y0 >= (y1 - y0) * 0.55) ny1 = up;
    const upTop = find(y0, -1);
    const downTop = find(y0, +1);
    if (upTop != null && y0 - upTop <= maxShift) ny0 = Math.max(0, upTop);
    else if (downTop != null && downTop - y0 <= maxShift && ny1 - downTop >= (y1 - y0) * 0.55) ny0 = downTop;
    if (ny1 - ny0 < 32) return { y0, y1 };
    return { y0: ny0, y1: ny1 };
  },

  pageAtViewport() {
    const scroller = $('#strip');
    if (!scroller || this.mode !== 'vertical') return this.page;
    const vh = scroller.clientHeight || window.innerHeight;
    const mid = vh * 0.45;                     // чуть выше центра — реплики сверху
    let best = -1, bestArea = -1, bestDist = Infinity, bestNear = -1;
    for (let i = 0; i < this.pages.length; i++) {
      const wrap = document.querySelector(`.pagewrap[data-page="${i}"]`);
      if (!wrap) continue;
      const r = wrap.getBoundingClientRect();
      const sr = scroller.getBoundingClientRect();
      const top = r.top - sr.top, bottom = r.bottom - sr.top;
      const visible = Math.min(bottom, vh) - Math.max(top, 0);
      if (visible > bestArea) { bestArea = visible; best = i; }
      const d = Math.abs(top - mid);
      if (d < bestDist) { bestDist = d; bestNear = i; }
    }
    // Если середина экрана попала в пустоту (страница не загружена и места нет),
    // берём ту, что занимает больше всего экрана.
    return best >= 0 ? best : Math.max(0, bestNear);
  },

  /** Сверить сохранённый индекс с экраном и обновить шапку/подгрузку. */
  syncPage() {
    if (!this.pages || !this.pages.length) return this.page;
    const actual = this.pageAtViewport();
    if (actual !== this.page) {
      this.page = actual;
      this.ensureLoaded(actual);
      this.ensureLoaded(actual + 1);
      this.saveProgress();
      this.syncSub();
      return actual;
    }
    this.syncSub();
    return this.page;
  },

  pageRect(i) {
    const img = this.imgEls[i];
    if (!img) return null;
    return img.getBoundingClientRect();
  },

  scrollToPage(i, animate = true) {
    const wrap = document.querySelector(`.pagewrap[data-page="${i}"]`) || document.querySelector(`.pagebox[data-page="${i}"]`);
    if (!wrap) return;
    wrap.scrollIntoView({ block: 'start', behavior: animate ? 'smooth' : 'auto' });
    this.page = i;
    this.syncSub();
    this.ensureLoaded(i);
    this.ensureLoaded(i + 1);
    this.saveProgress();
  },

  saveProgress() {
    if (!this.book) return;
    this.book.progress = this.page;
    this.book.mode = this.mode;
    DB.put('books', this.book);
  },

  /** Сохранить в буфер все реплики страницы (собранные из полос). */
  async savePageBuffer(i) {
    if (!this.book || !this.book.id) return;       // некуда сохранять — не ошибка
    const data = this.regions.get(i);
    if (data && data.lines) await Buffer.put(i, data.lines);
  },
  /** Смена направления чтения: пересортировать уже распознанное, без OCR. */
  rescanInDir() {
    const rtl = (this.dir || 'rtl') === 'rtl';
    let n = 0;
    for (const [i, data] of this.regions) {
      if (!data || !data.regions) continue;       // из буфера — регионов нет
      data.lines = readingOrder(data.regions, rtl, true, RULES);
      Buffer.put(i, data.lines);
      n++;
    }
    this.paintAllFrames();
    toast(n ? 'Порядок пересчитан: ' + (rtl ? 'справа налево' : 'слева направо') : 'Откройте страницу заново, чтобы применить направление', 4000);
  },

  /**
   * Распознать КОНКРЕТНУЮ страницу.
   *
   * Раньше единственная точка входа (`scanCurrent`) брала «текущую» страницу в
   * момент вызова. Из-за этого «Распознать заново» из шторки «Текст страницы N»
   * сканировало ту страницу, на которой лента оказалась к тому моменту, а не ту,
   * чей текст открыт: реплики не перезаписывались вообще.
   */
  async scanPage(i, opts = {}) {
    this.hideStart();
    // Режим «Google Lens»: локальный конвейер НЕ запускаем вообще. Иначе
    // получалось бы «нажал Распознать — и ничего не произошло, только звёздочка
    // покрутилась»: Lens работает в другой вкладке, а местный OCR тут ни при чём.
    if (LENS.isLens() && !opts.fromLens && !opts.silent) {
      const cv = this.canvases[i];
      if (!cv) { toast('Страница ' + (i + 1) + ' ещё не загрузилась'); return null; }
      const band = opts.full ? null : this.visibleBandPx(i);
      const crop = band ? cropCanvas(cv, 0, band.y0, cv.width, Math.max(1, band.y1 - band.y0)) : cv;
      // СНАЧАЛА прямой путь — как в АПК: сами отправили, сами забрали текст,
      // никаких сайтов и новых вкладок. Вкладка — только если прямого пути нет
      // и человек сам нажмёт «Открыть в Lens».
      if (LENS.hasDirect()) {
        const badge = $('#scanBadge');
        if (badge) { badge.classList.add('on'); badge.textContent = 'Lens: распознаю без сайта…'; }
        let got;
        try { got = await LENS.recognizeDirect(crop, { page: i }); }
        finally { if (badge) badge.classList.remove('on'); }
        if (got.ok) {
          const res = await applyLensText(i, got.lines.join('\n'), { fromDirect: true });
          toast('Lens напрямую — ' + (got.via === 'native' ? 'движок АПК' : 'свой релей') + '): '
                + got.lines.length + ' реплик за ' + got.ms + ' мс', 6000);
          return this.regions.get(i) || (res && res.ok ? this.regions.get(i) : null);
        }
        // Прямой путь не получился — говорим причину и НЕ открываем сайт молча.
        openSheet('sheetLens');
        LENS.pendingPage = i;
        renderLensSheet(i);
        toast('Прямое распознавание не вышло: ' + got.reason, 9000);
        return this.regions.get(i) || null;
      }
      const sent = LENS.send(crop, { page: i });
      if (sent.ok) {
        toast('Страница ' + (i + 1) + ' ушла в Google Lens — откройте новую вкладку', 6000);
        openSheet('sheetLens');
        LENS.pendingPage = i;
        renderLensSheet(i);
      } else {
        toast('Lens не открылся: ' + sent.reason, 7000);
      }
      return this.regions.get(i) || null;
    }
    const silent = !!opts.silent;          // предзагрузка: без бейджа и тостов
    const force = !!opts.force;
    const keepSheet = !!opts.keepSheet;
    if (i == null || i < 0 || i >= this.pages.length) return null;

    // Полоса, которую сейчас видно: ключ нужен, чтобы при прокрутке
    // распознавать новые куски, а уже распознанные не гонять заново.
    // opts.bandPx — явная полоса в пикселях кадра. Нужна, чтобы распознать
    // следующую полосу ЗАРАНЕЕ, пока звучит речь, и не ждать 3 секунды после
    // прокрутки (на телефоне 22:11 это выглядело как «прокрутил и молчит»).
    const band = opts.full ? null : (opts.bandPx || this.visibleBandPx(i));
    const bandKey = band ? band.key : 'page';
    if (!(this.bandCache instanceof Map)) this.bandCache = new Map();
    const bandMap = this.bandCache.get(i) || new Map();

    // Кэш годится, если: (а) полоса уже распознана; (б) страницу распознали
    // целиком; (в) данные пришли из буфера прошлой сессии — тогда считаем их
    // полной страницей, иначе старые книги распознавались бы заново.
    const cached = this.regions.get(i);
    const hasBands = this.bandCache.has(i);
    const fresh = cached && (band ? (hasBands && bandMap.has(bandKey)) : !hasBands);
    if (cached && fresh && !force) { this.paintPage(i); return cached; }

    if (silent && (State.scanning || State.prefetching)) return null;
    if (State.scanning && !silent) {
      // Молча выходить нельзя: нажатие «Распознать заново» выглядело как
      // «кнопка не работает». Ставим в очередь и говорим об этом.
      State.pendingScan = { i, force, keepSheet, full: !!opts.full };
      const msg = 'Идёт распознавание — страница ' + (i + 1) + ' встала в очередь';
      toast(msg, 4000);
      if (keepSheet) $('#textStats').textContent = msg + '…';
      return null;
    }

    const c = this.canvases[i];
    if (!c) { toast('Страница ' + (i + 1) + ' ещё не загрузилась'); return null; }
    if (!OCR.ready) {
      // Раньше шторка «Модели» открывалась ПУСТОЙ: состояние рисует renderModels,
      // а её здесь никто не звал. На скриншоте с телефона 28.10 так и было —
      // «СОСТОЯНИЕ» без единой строки, непонятно, чего не хватает.
      openSheet('sheetModels');
      renderModels().catch(() => {});
      toast('Сначала добавьте модели OCR (⚙ → Модели)');
      return null;
    }

    if (silent) State.prefetching = true; else State.scanning = true;
    if (!silent) {
      $('#scanBadge').classList.add('on');
      $('#scanBadge').textContent = `Распознаём… стр. ${i + 1}`;
    }
    if (keepSheet) $('#textStats').textContent = `Распознаю страницу ${i + 1} заново…`;
    try {
      const label = band ? `полосу ${i + 1}` : `страницу ${i + 1}`;
      const res = await recognizePage(c, RULES, (done, total, phase) => {
        // Числа проверяем: раньше сюда мог прийти текст фазы вместо числа, и в
        // бейдже висело «Распознаём… NaN/0» (телефон 22:41).
        const okDone = Number.isFinite(done), okTotal = Number.isFinite(total) && total > 0;
        const t = (phase && !okTotal)
          ? `Распознаём… ${phase}`
          : (phase
            ? `Распознаём… ${phase} ${Math.max(1, Math.ceil(done))}/${total}`
            : (okTotal ? `Распознаём… ${Math.min(total, Math.max(1, Math.ceil(done)))}/${total}` : 'Распознаём…'));
        $('#scanBadge').textContent = t;
        if (keepSheet) {
          $('#textStats').textContent = (okDone && okTotal)
            ? `Распознаю ${label} заново… ${done}/${total}`
            : `Распознаю ${label} заново…` + (phase ? ' ' + phase : '');
        }
      }, band, opts.det || null);
      // Направление чтения — отдельная настройка (dir), а не раскладка.
      const rtl = (this.dir || 'rtl') === 'rtl';
      let fresh;
      if (res.plan === 'native' && Array.isArray(res.replicas) && res.replicas.length) {
        // Порядок и склейку уже сделал движок чтения в приложении. Здесь только
        // слова: словарь и языковая починка живут в странице (3 МБ словаря).
        fresh = res.replicas
          .map(r => ({
            ...r,
            text: Words.polish(String(r.text || ''), RULES.junkRatio, r.confidence),
          }))
          .filter(l => l.text && (l.text.match(/\p{L}/gu) || []).length >= 2);
        OCR.readPlan = 'native';
      } else {
        fresh = readingOrder(res.regions, rtl, true, RULES);
        OCR.readPlan = 'page';
      }
      // Края реплик чистим ЗДЕСЬ, на выходе распознавания: обрывок звукового
      // эффекта приклеивается к началу текста уже при склейке строк, то есть
      // позже первой чистки («*ь*.*о НЕ УВЕРЕН…» — эмулятор APKForge, 29.10).
      fresh = fresh
        .map(l => ({ ...l, text: trimJunkEdges(String(l.text || '')) }))
        .filter(l => l.text && (l.text.match(/\p{L}/gu) || []).length >= 2);
      // Помечаем, на какой полосе нашлась реплика: в шторке видно, что
      // показано «на экране», а что распознано раньше с этой же страницы.
      const bandTop = band ? Math.round(band.y0) : 0;
      fresh = fresh.map(l => ({ ...l, bandTop }));
      const at = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

      // Собираем полосы страницы: новая заменяет старую с тем же ключом,
      // остальные остаются. Их реплики идут сверху вниз.
      bandMap.set(bandKey, { lines: fresh, res, at });
      const detPass = res.detPass || 'normal';
      const largePasses = res.largePasses || 0;
      this.bandCache.set(i, bandMap);
      const parts = Array.from(bandMap.entries())
        .sort((a, b) => (a[1].res.band?.y0 ?? 0) - (b[1].res.band?.y0 ?? 0));
      const lines = mergeBandLines(parts.map(([, part]) => part), c);
      const total = parts.reduce((acc, [, p]) => acc + (p.res.ms || 0), 0);
      this.regions.set(i, {
        ...res, lines, at, bands: parts.length,
        detPass, largePasses,
        ms: total, detMs: res.detMs, recMs: res.recMs, crops: res.crops,
        boxes: res.boxes, regions: res.regions,
        bandKeys: parts.length,
      });
      await this.savePageBuffer(i);
      this.paintPage(i);
      if (silent) return this.regions.get(i);      // молча: это фоновая загрузка
      // Числа берём только те, что есть. Нативный проход неделим (детектор и
      // распознавание идут одним вызовом), поэтому для него печатаем один
      // замер; раньше поля были пустыми и тост писал «NaN с».
      const secTxt = (v) => (Number.isFinite(v) && v > 0 ? (v / 1000).toFixed(1) : null);
      const nativePass = (res.via === 'native' || res.detPass === 'native');
      const totalSec = secTxt(res.ms)
        || secTxt((Number(res.detMs) || 0) + (Number(res.recMs) || 0)) || '?';
      const how = nativePass
        ? `нативно, ${res.crops} строк`
        : `детектор ${secTxt(res.detMs) || '0.0'} с, распознавание ${secTxt(res.recMs) || '0.0'} с, ${res.crops} строк`
          + (OCR.nativeNote ? `, нативно не вышло: ${String(OCR.nativeNote).slice(0, 80)}` : '');
      toast(`${band ? 'Полоса' : 'Страница'} ${i + 1} ${force ? 'обновлена' : 'распознана'}: ${fresh.length} реплик`
        + (parts.length > 1 ? `, всего ${lines.length} на странице` : '')
        + ` · ${totalSec} с (${how})`, 6000);
      // Шторка остаётся открытой — и обязательно перерисовывается.
      if ($('#sheetText').classList.contains('on')) renderTextSheet(i);
      return this.regions.get(i);
    } catch (e) {
      console.error(e);
      const ln = String((e && e.stack) || '').split('\n')[1] || '';
      const where = ln.trim().replace(/\s*\(?.*\//, '(').replace(/^at /, '');
      const msg = 'Ошибка распознавания: ' + (e.message || e) + (where ? ' · ' + where : '');
      toast(msg, 8000);
      if (keepSheet) $('#textStats').textContent = msg;
      return null;
    } finally {
      State.scanning = false;
      State.prefetching = false;
      $('#scanBadge').classList.remove('on');
      const p = State.pendingScan;
      State.pendingScan = null;
      if (p) setTimeout(() => this.scanPage(p.i, { force: p.force, keepSheet: p.keepSheet }), 50);
    }
  },

  /** Совместимость: распознать текущую страницу. */
  async scanCurrent(force = false, preDet = null) {
    return this.scanPage(this.page, { force, det: preDet });
  },

  /** Карточка «ничего не запущено»: показывается, пока страница не распознана. */
  showStart() {
    const el = $('#startCard');
    if (!el) return;
    const data = this.regions.get(this.page);
    if (data) { el.style.display = 'none'; return; }
    $('#startTitle').textContent = 'Страница ' + (this.page + 1) + ' открыта';
    $('#startHint').textContent = 'Ничего не запущено. Скорость: '
      + (SPEED_NAMES[RULES.speed] || RULES.speed) + ' ' + (SPEED_APPROX[RULES.speed] || '');
    $('#cbAutoScan').checked = !!RULES.autoScan;
    el.style.display = 'block';
  },
  hideStart() {
    const el = $('#startCard');
    if (el) el.style.display = 'none';
  },

  /** Ключ «прочитано»: страница + нормализованный текст (OCR может дать вариант). */
  spokenKey(i, text) {
    const t = String(text || '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
    return i + '|' + t;
  },
  unmarkSpoken(i, text) {
    this.spoken.delete(this.spokenKey(i, text));
    this.spokenDirty = true;
    this.paintPage(i);
  },
  markSpoken(i, text) {
    this.spoken.add(this.spokenKey(i, text));
    this.spokenDirty = true;
    this.paintPage(i);
  },
  /** Сохранить отметки «прочитано» в базу (не чаще раза в 3 с). */
  saveSpoken() {
    if (!this.spokenDirty || !this.book) return;
    this.spokenDirty = false;
    const k = 'spoken:' + this.book.id;
    DB.put('kv', { k, v: Array.from(this.spoken).slice(-4000) }).catch(() => {});
  },
  /** Непрочитанные реплики ВСЕЙ страницы — страховка от «прочитал одну». */
  unspokenPage() {
    const data = this.regions.get(this.page);
    if (!data) return [];
    return (data.lines || []).filter(l => !this.spoken.has(this.spokenKey(this.page, l.text)));
  },
  /** Непрочитанные реплики текущей полосы. */
  unspokenInBand() {
    const i = this.page;
    return this.visibleLines().filter(l => !this.spoken.has(this.spokenKey(i, l.text)));
  },

  /**
   * Пока человек слушает текущую страницу, тихо распознаём следующую. Тогда
   * переход не упирается в «Распознаём… стр. N»: страница уже готова. Раньше
   * 14 страниц читались как 14 ожиданий подряд.
   */
  prefetchNext() {
    if (!OCR.ready) return;
    const i = this.page + 1;
    if (i >= this.pages.length || this.regions.get(i)) return;
    clearTimeout(this.prefetchTimer);
    this.prefetchTimer = setTimeout(async () => {
      if (this.stopped === undefined) return;
      if (State.scanning || State.prefetching) return;
      if (!this.canvases[i]) return;               // страница ещё не декодирована
      try { await this.scanPage(i, { full: true, silent: true }); } catch (e) { /* фон — молча */ }
    }, 700);
  },
  /* ── Полосы: распознать ВПЕРЁД, прокрутить ПОСЛЕ ──────────────────────── */

  /** Полоса (доли страницы) → пиксели кадра + ключ для кэша полос. */
  bandPx(i, b) {
    const c = this.canvases[i];
    if (!c || !b || b.whole) return null;
    const y0 = clamp(Math.round(b.top * c.height), 0, c.height);
    const y1 = clamp(Math.round(b.bottom * c.height), 0, c.height);
    if (y1 - y0 < 32) return null;
    return { y0, y1, vy0: y0, vy1: y1,
      key: 'b' + (b.index || 0) + ':' + Math.round(y0 / 96) + '-' + Math.round(y1 / 96) };
  },
  /** Уже распознана ли эта полоса (в кэше полос или страница целиком). */
  bandScanned(i, b) {
    const data = this.regions.get(i);
    const maps = this.bandCache && this.bandCache.get(i);
    if (data && !maps) return true;                 // страница распознана целиком
    if (!maps) return false;
    const px = this.bandPx(i, b);
    if (!px) return !!data;
    const h = Math.max(1, px.y1 - px.y0);
    for (const [, part] of maps) {
      const r = part && part.res && part.res.band;
      if (!r) return true;                          // этот кусок — вся страница
      if (Math.min(r.y1, px.y1) - Math.max(r.y0, px.y0) > h * 0.6) return true;
    }
    return false;
  },
  /**
   * Гарантировать текст полосы: при необходимости распознать её ЗДЕСЬ и сейчас.
   * Возвращает непрочитанные реплики этой полосы.
   */
  async ensureBandLines(i, ni) {
    const bands = this.bands || [];
    const b = bands[ni];
    if (!b) return [];
    this.bandIndex = ni;
    this.band = b;
    if (b.whole) return this.unspokenInBand();
    await this.waitIdle();
    if (!this.bandScanned(i, b)) {
      const px = this.bandPx(i, b);
      if (px) await this.scanPage(i, { bandPx: px });
    }
    this.band = b;
    return this.unspokenInBand();
  },
  /**
   * Прокрутить к реплике, ТОЛЬКО если её не видно (или видно у самого края).
   * Спокойное чтение вместо дёрганья: если строка уже на экране — не трогаем
   * ленту вовсе.
   */
  scrollToLineIfNeeded(i, line) {
    try {
      const sc = $('#strip');
      const wrap = document.querySelector(`.pagewrap[data-page="${i}"]`);
      if (!sc || !wrap || !line || this.mode !== 'vertical') return false;
      const h = wrap.getBoundingClientRect().height || ((this.pageRect(i) || {}).height || 0);
      if (!h) return false;
      const viewH = sc.clientHeight || window.innerHeight;
      const abs = (wrap.offsetTop || 0) + clamp(line.top, 0, 1) * h;   // строка в ленте
      const rel = abs - sc.scrollTop;                                  // где она на экране
      // Уже хорошо видно: от 8 % до 80 % экрана — ничего не делаем.
      if (rel > viewH * 0.08 && rel < viewH * 0.8) return false;
      const target = Math.max(0, abs - viewH * 0.22);
      if (Math.abs(target - sc.scrollTop) < 24) return false;
      SMOOTH.to(target, 240);            // один твин на всех, без спора за ленту
      return true;
    } catch (e) { return false; }
  },

  /** Прокрутить ленту ровно к началу полосы (без накопления сдвига). */
  scrollToBand(i, ni, animate = true) {
    const b = (this.bands || [])[ni];
    const wrap = document.querySelector(`.pagewrap[data-page="${i}"]`);
    const sc = $('#strip');
    if (!b || !wrap || !sc) return false;
    const h = wrap.getBoundingClientRect().height || ((this.pageRect(i) || {}).height || 0);
    if (!h) return false;
    const target = Math.max(0, (wrap.offsetTop || 0) + b.top * h);
    if (animate) SMOOTH.to(target, 260);
    else { SMOOTH.stop(); sc.scrollTop = target; }
    return true;
  },
  /**
   * Пока человек слушает текущую полосу — тихо распознать следующую.
   * Это и убирает «прокрутил и несколько секунд молчит»: к моменту перехода
   * текст следующей полосы уже посчитан.
   */
  prefetchBandAhead() {
    if (!OCR.ready || RULES.pipeline === false) return;
    const i = this.page, bands = this.bands || [];
    const ni = (this.bandIndex || 0) + 1;
    if (ni >= bands.length) return;             // дальше страница — её prefetchNext
    clearTimeout(this._bandTimer);
    this._bandTimer = setTimeout(async () => {
      try {
        if (typeof TTS !== 'undefined' && TTS.stopped !== false) return;  // не читаем
        if (State.scanning || State.prefetching) return;
        if (Reader.bandScanned(i, bands[ni])) return;
        const px = Reader.bandPx(i, bands[ni]);
        if (!px) return;
        await Reader.scanPage(i, { bandPx: px, silent: true });
      } catch (e) { /* фон — молча */ }
    }, 500);
  },

  /** Дождаться конца фоновой загрузки, чтобы не запускать два распознавания. */
  async waitIdle(ms = 25000) {
    const t0 = Date.now();
    while ((State.scanning || State.prefetching) && Date.now() - t0 < ms) await sleep(120);
  },

  /* Реплики текущей полосы — то, что читается */
  visibleLines() {
    const data = this.regions.get(this.page);
    if (!data) return [];
    if (!this.band || this.band.whole) return data.lines;
    const b = this.band;
    return data.lines.filter(l => l.bottom > b.top && l.top < b.bottom);
  },
};

/* ───────────────────────── 9. Буфер строк ───────────────────────── */
const Buffer = {
  async put(page, lines) {
    // Буфер живёт в книге. Если книга не из библиотеки (страница открыта сама
    // по себе), сохранять некуда — и падать из-за этого нельзя: раньше отсюда
    // прилетал тост «Ошибка распознавания: Cannot read properties of null»,
    // хотя распознавание прошло нормально (замечено 28.10 на прозе).
    if (!Reader.book || !Reader.book.id) return;
    const key = 'buf:' + Reader.book.id + ':' + page;
    await DB.put('kv', { k: key, v: { page, at: Date.now(), rules: RULES.version, lines } });
  },
  async get(page) {
    return (await DB.get('kv', 'buf:' + Reader.book.id + ':' + page))?.v || null;
  },
  async all() {
    const rows = (await DB.all('kv') || []).filter(r => r.k.startsWith('buf:' + (Reader.book?.id || '')));
    return rows.map(r => r.v).sort((a, b) => a.page - b.page);
  },
  async clear() {
    const rows = (await DB.all('kv') || []).filter(r => r.k.startsWith('buf:' + (Reader.book?.id || '')));
    for (const r of rows) await DB.del('kv', r.k);
  },
};

/* ───────────────────────── 10. Озвучка ───────────────────────── */
/**
 * «Где читает»: лента над плеером, где каждая буква — отдельный элемент, а
 * текущая подсвечена тенью.
 *
 * Точную привязку «буква ↔ звук» браузер не даёт: SpeechSynthesis шлёт
 * onboundary только по границам СЛОВ (и только часть движков). Поэтому так:
 * границы слов дают точку отсчёта, а внутри слова тень идёт по оценке —
 * ≈14 символов в секунду при rate 1.0 (замер по длительности реплик:
 * «УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ, ТАК ЧТО ЕЁ ВЫСОЧЕСТВО, ДОЛЖНО БЫТЬ, ПРИБЫЛА» —
 * 78 знаков, 5,6 с). Как только приходит новая граница, позиция выравнивается
 * по ней, поэтому расхождение не копится.
 */
const SpeakCursor = {
  el: null, chars: [], pos: 0, t0: 0, rate: 1, exact: false, timer: 0, on: false,
  cps() { return 14 * (this.rate || 1); },
  start(text, rate) {
    const el = $('#nowLine');
    if (!el) return;
    this.el = el; this.rate = rate || 1; this.pos = 0; this.exact = false; this.on = true;
    this.t0 = performance.now();
    el.innerHTML = Array.from(text).map((ch, i) =>
      `<span class="ch" data-i="${i}">${escapeHtml(ch)}</span>`).join('');
    this.chars = Array.from(el.querySelectorAll('.ch'));
    el.style.display = 'block';
    clearInterval(this.timer);
    this.timer = setInterval(() => this.tick(), 50);
    this.paint();
  },
  /** Точка отсчёта из onboundary: charIndex — начало слова. */
  boundary(charIndex) {
    if (!this.on || typeof charIndex !== 'number' || charIndex < 0) return;
    this.exact = true;
    this.pos = Math.min(charIndex, this.chars.length);
    this.pos0 = this.pos;
    this.t0 = performance.now();
    this.paint();
  },
  tick() {
    if (!this.on || !this.chars.length) return;
    if (!this.exact) {
      const done = (performance.now() - this.t0) / 1000 * this.cps();
      this.pos = Math.min(this.chars.length, Math.round(done));
      this.paint();
    } else {
      // После границы слова внутри слова ведём тень по оценке.
      const guess = this.pos0 + (performance.now() - this.t0) / 1000 * this.cps();
      const p = Math.min(this.chars.length, Math.round(guess));
      if (p !== this.pos) { this.pos = p; this.paint(); }
    }
  },
  paint() {
    for (let i = 0; i < this.chars.length; i++) {
      const c = this.chars[i];
      const k = i < this.pos ? 'ch sp' : (i === this.pos ? 'ch cur' : 'ch');
      if (c.className !== k) c.className = k;
    }
    // Лента — одна строка в высоту (меньше закрывает страницу), поэтому
    // за текущей буквой она подкручивается сама: видно именно ту строку, где
    // сейчас звучит голос.
    if (this.el && this.pos > 0 && this.chars[this.pos]) {
      const c = this.chars[this.pos];
      const y = c.offsetTop || 0;
      const h = c.offsetHeight || 17;
      // Прокрутка кратна высоте строки: иначе снизу торчала половина
      // следующей строки — выглядело как обрезанный текст.
      // Высота строки — из line-height: у символа offsetHeight округляется
      // по-разному, и строки «плыли» на пару пикселей.
      let rowH = h;
      try { rowH = parseFloat(getComputedStyle(this.el).lineHeight) || h; } catch (e) { rowH = h; }
      const top = Math.floor(y / rowH) * rowH;
      if (top < this.el.scrollTop || top + h > this.el.scrollTop + this.el.clientHeight) {
        this.el.scrollTop = Math.max(0, top);
      }
    }
  },
  stop() {
    this.on = false;
    clearInterval(this.timer); this.timer = 0;
    if (this.el) { this.el.style.display = 'none'; this.el.innerHTML = ''; }
    this.chars = [];
  },
};

/**
 * ГОЛОС: один слой над двумя движками речи.
 *
 * В браузере это Web Speech API (`speechSynthesis`). В Android WebView его НЕТ
 * ВООБЩЕ: 28.10 на телефоне это выглядело как «Скрипты страницы не выполнились»
 * и тост «speechSynthesis is not defined» — падал самый первый вызов в TTS.init(),
 * и всё, что шло дальше по boot (правила, библиотека, модели), не выполнялось.
 * Поэтому речи в приложении даёт нативный Android TTS через мост KomaSpeech,
 * а страница общается только с этим фасадом и не знает, кто под ним.
 *
 * Фасад повторяет ровно тот минимум, который нужен читалке: список голосов,
 * speak с событиями start/end/error, отмена, пауза (где есть) и состояние.
 */
const VOICE = {
  _voices: null, _handlers: {}, _seq: 0, speaking: false, paused: false,

  /** Нативный синтез из АПК. В браузере его нет — и это нормально. */
  native() {
    return !!(typeof window !== 'undefined' && window.KomaSpeech
      && typeof window.KomaSpeech.speak === 'function');
  },
  /** Web Speech API. В WebView отсутствует, поэтому только через typeof. */
  synth() {
    return (typeof speechSynthesis !== 'undefined') ? speechSynthesis : null;
  },
  available() { return this.native() || !!this.synth(); },
  /** Чей это голос — для проверок и для честных сообщений человеку. */
  kind() { return this.native() ? 'Android TTS (АПК)' : (this.synth() ? 'Web Speech' : null); },

  /** Список голосов в одном формате: {name, lang, voiceURI}. */
  voices() {
    if (this.native()) {
      // Пустой ответ НЕ кэшируем: Android TTS инициализируется асинхронно, и
      // первый вызов почти всегда приходит раньше, чем движок готов. Раньше
      // пустой список запоминался навсегда — отсюда «Система не дала ни одного
      // голоса» (телефон 22:12) при живом синтезе.
      if (this._voices && this._voices.length) return this._voices;
      try {
        const raw = window.KomaSpeech.voices();
        const arr = JSON.parse(typeof raw === 'string' ? raw : JSON.stringify(raw || []));
        this._voices = (Array.isArray(arr) ? arr : []).map((v, i) => (
          typeof v === 'string'
            ? { name: v, lang: 'ru-RU', voiceURI: 'native:' + i }
            : { name: v.name || ('голос ' + i), lang: v.lang || 'ru-RU', voiceURI: v.voiceURI || ('native:' + i) }));
      } catch (e) { console.warn('KomaSpeech.voices', e); this._voices = []; }
      return this._voices;
    }
    const sw = this.synth();
    if (!sw) return [];
    try { return (sw.getVoices() || []).slice(); } catch (e) { return []; }
  },

  /** Движки синтеза, установленные в системе (только в АПК). */
  engines() {
    if (!this.native() || typeof window.KomaSpeech.engines !== 'function') return [];
    try {
      const raw = window.KomaSpeech.engines();
      const arr = JSON.parse(typeof raw === 'string' ? raw : JSON.stringify(raw || []));
      return Array.isArray(arr) ? arr : [];
    } catch (e) { return []; }
  },
  /** Переключить движок синтеза. Пусто — системный по умолчанию. */
  useEngine(name) {
    if (!this.native() || typeof window.KomaSpeech.useEngine !== 'function') return false;
    try { window.KomaSpeech.useEngine(String(name || '')); this._voices = null; return true; }
    catch (e) { return false; }
  },

  /** Короткая причина состояния голоса — для честных сообщений человеку. */
  statusText() {
    if (!this.native()) {
      const sw = this.synth();
      if (!sw) return 'синтеза речи нет';
      return 'Web Speech: голосов ' + (sw.getVoices() || []).length;
    }
    try {
      const raw = window.KomaSpeech.status();
      const o = JSON.parse(typeof raw === 'string' ? raw : JSON.stringify(raw || {}));
      const bits = [];
      if (o.engine) bits.push(String(o.engine).split('.').pop());
      bits.push(o.ready ? 'готов' : 'не готов');
      if (o.ru === false) bits.push('нет русского голоса');
      if (o.voices) bits.push('голосов ' + o.voices);
      if (o.error) bits.push(o.error);
      return bits.join(', ');
    } catch (e) { return ''; }
  },

  /** Скажет ли нативный движок по-русски; null — не знаем (браузер). */
  nativeReady() {
    if (!this.native()) return null;
    try {
      const st = window.KomaSpeech.status();
      const o = JSON.parse(typeof st === 'string' ? st : JSON.stringify(st || {}));
      return !!o.ready;
    } catch (e) { return false; }
  },

  cancel() {
    this.speaking = false; this.paused = false; this._handlers = {};
    if (this.native()) { try { window.KomaSpeech.cancel(); } catch (e) { /* моста уже нет */ } }
    const sw = this.synth();
    if (sw) { try { sw.cancel(); } catch (e) { /* ignore */ } }
  },
  pause() {
    this.paused = true;
    const sw = this.synth();
    if (this.native()) {
      // У Android TTS паузы нет: честно останавливаем и запоминаем, что читаем.
      // Продолжение начинает текущую реплику заново — об этом говорим в интерфейсе.
      try { window.KomaSpeech.cancel(); } catch (e) {}
      this.speaking = false;
      return 'restart';
    }
    if (sw) { try { sw.pause(); } catch (e) {} }
    return 'pause';
  },
  resume() {
    this.paused = false;
    const sw = this.synth();
    if (sw && !this.native()) { try { sw.resume(); } catch (e) {} return true; }
    return false;
  },

  /**
   * Сказать текст. opts: {lang, rate, voice, onstart, onboundary, onend, onerror}.
   * Возвращает true, если движок принял фразу.
   */
  speak(text, opts = {}) {
    // Что уходит в голос — сразу и мосту стенда (KomaUi.spoken): в эмуляторе
    // это строка на «экране» и журнал порядка, а не догадки по логам.
    try {
      if (typeof window !== 'undefined' && window.KomaUi
          && typeof window.KomaUi.spoken === 'function') {
        window.KomaUi.spoken(String(text || ''));
      }
    } catch (e) { /* моста нет — обычный браузер */ }
    if (this.native()) {
      const id = 'v' + (++this._seq) + '_' + Date.now().toString(36);
      this._handlers[id] = opts;
      this.speaking = true;
      window.__komaSpeechEvent = window.__komaSpeechEvent || ((eid, type, data) => {
        const h = VOICE._handlers[eid];
        if (!h) return;
        if (type === 'start') { VOICE.speaking = true; if (h.onstart) h.onstart(); }
        else if (type === 'end') { delete VOICE._handlers[eid]; VOICE.speaking = false; if (h.onend) h.onend(); }
        else if (type === 'error') {
          delete VOICE._handlers[eid]; VOICE.speaking = false;
          if (h.onerror) h.onerror({ error: String(data || 'native') });
        }
      });
      try {
        window.KomaSpeech.speak(String(text || ''), String(opts.rate || 1),
          String(opts.lang || 'ru-RU'), String((opts.voice && opts.voice.name) || ''), id);
        return true;
      } catch (e) {
        delete this._handlers[id];
        this.speaking = false;
        if (opts.onerror) opts.onerror({ error: String((e && e.message) || e) });
        return false;
      }
    }
    const sw = this.synth();
    if (!sw || typeof SpeechSynthesisUtterance === 'undefined') return false;
    const u = new SpeechSynthesisUtterance(String(text || ''));
    try { if (opts.voice) u.voice = opts.voice; } catch (e) { /* старый голос */ }
    u.lang = opts.lang || (opts.voice && opts.voice.lang) || 'ru-RU';
    u.rate = opts.rate || 1;
    if (opts.volume != null) u.volume = opts.volume;
    u.onstart = () => { this.speaking = true; if (opts.onstart) opts.onstart(); };
    u.onboundary = (e) => { if (opts.onboundary) opts.onboundary((e && e.charIndex) || 0); };
    u.onend = () => { this.speaking = false; if (opts.onend) opts.onend(); };
    u.onerror = (e) => { this.speaking = false; if (opts.onerror) opts.onerror(e); };
    try { sw.speak(u); return true; } catch (e) {
      if (opts.onerror) opts.onerror({ error: String((e && e.message) || e) });
      return false;
    }
  },
};

/* Кадр анимации и время: в браузере requestAnimationFrame/performance,
   в прогонах без окна — таймер. Обёртки — чтобы не звать браузерные
   глобалы напрямую (сборка проверяет, что каждый вызов определён). */
const RAF = (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function')
  ? window.requestAnimationFrame.bind(window) : null;
const CAF = (typeof window !== 'undefined' && typeof window.cancelAnimationFrame === 'function')
  ? window.cancelAnimationFrame.bind(window) : null;
const nowMs = () => (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();

/**
 * ПЛАВНАЯ ПРОКРУТКА ЛЕНТЫ — один твин за раз.
 *
 * Было: три места дёргали `scrollTo({behavior:'smooth'})` независимо
 * (scrollToLineIfNeeded, followLine, scrollToBand), и на смене реплики они
 * спорили за ленту. Каждый вызов стартовал свою анимацию, лента бросала
 * начатую и ехала к другой цели — это и есть «резко дёрнулся, потом ещё
 * дважды» (телефон 28.10). Родной smooth-scroll в WebView при этом не даёт
 * ни события «доехал», ни отмены.
 *
 * Стало: один requestAnimationFrame-твин. Новая цель во время движения не
 * запускает вторую анимацию, а просто меняет точку назначения — движение
 * остаётся непрерывным. `done()` ждёт, пока лента реально встанет, поэтому
 * голос начинает реплику уже на неподвижной странице.
 */
const SMOOTH = {
  _raf: 0, _to: 0, _wait: [],
  /** Кадр: в браузере rAF, в тестах и старом WebView — таймер. */
  _raf2(fn) {
    if (typeof RAF === 'function') return RAF(fn);
    return setTimeout(() => fn(nowMs()), 16);
  },
  _caf(id) {
    if (!id) return;
    try {
      if (typeof CAF === 'function') CAF(id);
      else clearTimeout(id);
    } catch (e) { /* уже отменён */ }
  },
  /** Ехать к y (в пикселях ленты). Возвращает false, если ехать некуда. */
  to(y, ms = 240) {
    const sc = $('#strip');
    if (!sc) return false;
    const from = sc.scrollTop || 0;
    const to = Math.max(0, Math.round(y));
    if (Math.abs(to - from) < 2) { this._to = to; return false; }
    this._to = to;
    if (this._raf) return true;                 // уже едем — только цель обновилась
    const start = from, t0 = nowMs();
    const tick = (t) => {
      const k = Math.min(1, Math.max(0, (t - t0) / ms));
      const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;   // easeInOutQuad
      sc.scrollTop = Math.max(0, start + (this._to - start) * e);
      if (k < 1) { this._raf = this._raf2(tick); return; }
      this._raf = 0;
      sc.scrollTop = Math.max(0, this._to);
      const w = this._wait; this._wait = [];
      w.forEach(f => { try { f(); } catch (e) { /* ждём, не падаем */ } });
    };
    this._raf = this._raf2(tick);
    return true;
  },
  /** Ждать остановки ленты (сразу, если она стоит). */
  done() {
    if (!this._raf) return Promise.resolve();
    return new Promise(res => this._wait.push(res));
  },
  /** Человек сам тронул ленту — анимацию отдаём ему. */
  stop() {
    this._caf(this._raf);
    this._raf = 0;
    const w = this._wait; this._wait = [];
    w.forEach(f => { try { f(); } catch (e) { } });
  },
};

/**
 * ИНТЕРФЕЙС ЧТЕНИЯ В АПК.
 *
 * В приложении панель чтения нативная (KomaUi): она лежит под страницей, не
 * ездит вместе с лентой и не пересчитывает свою высоту на каждой реплике.
 * Страница остаётся владельцем чтения — она лишь рассказывает панели, что
 * сейчас звучит, и принимает от неё нажатия (`window.KomaUiCmd`). В браузере
 * моста нет, и всё работает по-старому: своя HTML-панель.
 */
const NATIVE_UI = {
  there() {
    return !!(typeof window !== 'undefined' && window.KomaUi
      && typeof window.KomaUi.show === 'function');
  },
  /** Отдать панели текущее состояние чтения. */
  push() {
    if (!this.there()) return false;
    try {
      const cur = (typeof Reader !== 'undefined' && Reader.current) || null;
      const line = (TTS && (TTS.curLine || cur)) || null;
      const total = (TTS && TTS.queue) ? TTS.queue.length : 0;
      const idx = (TTS && TTS.curIdx) ? TTS.curIdx : (total ? 1 : 0);
      const bands = (typeof Reader !== 'undefined' && Reader.bands) ? Reader.bands.length : 0;
      const band = (typeof Reader !== 'undefined') ? (Reader.bandIndex | 0) + 1 : 0;
      let voice = '';
      try { voice = VOICE.native() ? 'Android TTS' : 'Web Speech'; } catch (e) { voice = ''; }
      const paused = !!(TTS && TTS.paused);
      const playing = !!(TTS && !TTS.stopped);
      if (!playing && !line && !total) { this.hide(); return false; }
      window.KomaUi.show(JSON.stringify({
        text: (line && line.text) || '',
        index: Math.min(idx || 0, total || 0),
        total: total,
        band: band, bands: bands,
        playing: playing, paused: paused,
        voice: voice,
        status: paused ? 'пауза' : '',
      }));
      return true;
    } catch (e) { console.warn('KomaUi.show', e); return false; }
  },
  hide() {
    if (!this.there() || typeof window.KomaUi.hide !== 'function') return;
    try { window.KomaUi.hide(); } catch (e) { /* моста уже нет */ }
  },
};

/**
 * КОМАНДЫ С НАТИВНОЙ ПАНЕЛИ (KomaUiBridge в АПК).
 *
 * Панель в приложении только показывает состояние и ловит нажатия; чтением
 * владеет страница. Поэтому здесь ровно те же действия, что у своих кнопок —
 * иначе поведение в АПК и в браузере разъехалось бы.
 */
if (typeof window !== 'undefined') {
  window.KomaUiCmd = (cmd) => {
    try {
      switch (String(cmd || '')) {
        case 'toggle':
          if (TTS.stopped) {
            TTS.prime();
            Reader.scanCurrent(false).then(() => TTS.readVisible({ fromStart: true }));
          } else if (!TTS.paused) {
            TTS.pauseRead(); TTS.paused = true;
          } else {
            TTS.resumeRead(); TTS.paused = false;
          }
          break;
        case 'next':
          // Пропуск: гасим текущую фразу и сразу идём к следующей реплике.
          VOICE.cancel();
          if (!TTS.stopped) TTS.step();
          break;
        case 'repeat':
          TTS.replay();
          break;
        case 'stop':
        default:
          TTS.stop();
          break;
      }
    } catch (e) { console.warn('KomaUiCmd', e); }
    NATIVE_UI.push();
  };
}

const TTS = {
  voices: [], voice: null, rate: 1, speaking: false, stopped: true, queue: [], idx: 0, primed: false,
  init() {
    // Ни одного прямого обращения к speechSynthesis: в WebView его нет вовсе.
    const fill = () => {
      try {
        const all = VOICE.voices();
        this.voices = all.filter(v => /ru/i.test(v.lang)).concat(all.filter(v => !/ru/i.test(v.lang)));
        const sel = $('#selVoice');
        if (!sel) return;
        // Первый пункт — «системный по умолчанию». Это НЕ заглушка: именно так
        // читают все, кто настроил голос в Android (Tera TTS и прочие).
        const savedIdx = localStorage.getItem('koma.voice');
        const chosen = (savedIdx !== null && savedIdx !== 'default') ? +savedIdx : -1;
        sel.innerHTML = '<option value="default">системный (как в настройках Android)</option>'
          + this.voices.map((v, i) =>
            `<option value="${i}">${escapeHtml(v.name)} (${v.lang})</option>`).join('');
        sel.value = (chosen >= 0 && this.voices[chosen]) ? String(chosen) : 'default';
        this.voice = (sel.value === 'default') ? null : (this.voices[+sel.value] || null);
      } catch (e) { console.warn('голоса не заполнились', e); }
    };
    fill();
    const sw = VOICE.synth();
    if (sw) { try { sw.onvoiceschanged = fill; } catch (e) { /* ignore */ } }
    // Список ДВИЖКОВ синтеза (в АПК): человек может выбрать Tera TTS, даже
    // если системным по умолчанию стоит другой.
    try {
      const selE = $('#selTtsEngine');
      if (selE && typeof VOICE.engines === 'function') {
        const list = VOICE.engines();
        if (list.length) {
          const savedE = localStorage.getItem('koma.ttsEngine') || '';
          selE.innerHTML = '<option value="">системный движок</option>'
            + list.map(e => `<option value="${escapeHtml(e.name)}">${escapeHtml(e.label || e.name)}${e.default ? ' · по умолчанию' : ''}</option>`).join('');
          selE.value = list.some(e => e.name === savedE) ? savedE : '';
          selE.onchange = (ev) => {
            const name = ev.target.value || '';
            localStorage.setItem('koma.ttsEngine', name);
            try { VOICE.useEngine(name); } catch (err) { console.warn('движок не переключился', err); }
            VOICE._voices = null;          // голоса у нового движка свои
            setTimeout(fill, 400);
          };
        }
      }
    } catch (e) { /* в браузере движков нет — это нормально */ }
    $('#selVoice').onchange = (e) => {
      // «default» — это выбор системного голоса, а не отсутствие выбора.
      if (e.target.value === 'default') {
        this.voice = null;
        localStorage.setItem('koma.voice', 'default');
      } else {
        this.voice = this.voices[+e.target.value] || null;
        localStorage.setItem('koma.voice', e.target.value);
      }
    };
    const r = $('#rngRate');
    r.value = +(localStorage.getItem('koma.rate') || (RULES.speechRate || 1));
    this.rate = +r.value;
    r.oninput = () => { this.rate = +r.value; localStorage.setItem('koma.rate', r.value); };
  },
  stop() {
    this.stopped = true; this.speaking = false; this.queue = [];
    try { SpeakCursor.stop(); } catch (e) { /* ленты ещё нет */ }
    VOICE.cancel();
    Reader.current = null;
    Reader.paintAllFrames();
    $('#playBar').style.display = 'none';
    $('#btnRead').textContent = '▶';
    this.curLine = null; this.curIdx = 0;
    NATIVE_UI.hide();
  },
  /**
   * Повторить текущую реплику (кнопка ⟲ на нативной панели).
   * Отдельный метод, потому что просто «ещё раз speakLine» без остановки
   * накладывает вторую фразу на первую.
   */
  replay() {
    const line = this.curLine || Reader.current;
    if (!line || !line.text) return false;
    VOICE.cancel();
    this.stopped = false;
    this.speakLine(line, () => { if (!this.stopped) this.step(); });
    NATIVE_UI.push();
    return true;
  },
  /**
   * Держать читаемую реплику в «безопасной» полосе экрана: сверху шапка и
   * бейдж распознавания, снизу панель проигрывания и нижняя панель. Раньше
   * плеер стоял прямо на облачке — текст реплики был закрыт.
   * Масштаб не меняем (правило), только прокручиваем ленту.
   */
  followLine(line) {
    if (Reader.mode !== 'vertical' || !line) return;
    const wrap = document.querySelector(`.pagewrap[data-page="${Reader.page}"]`);
    const sc = $('#strip');
    if (!wrap || !sc) return;
    const r = wrap.getBoundingClientRect();
    const sr = sc.getBoundingClientRect();
    if (!r.height || !sr.height) return;
    const top = r.top + line.top * r.height;
    const bottom = r.top + line.bottom * r.height;
    const safeTop = sr.top + 72;                        // шапка + бейдж
    // Нижняя граница учитывает ленту «где читает»: она висит над панелью
    // плеера, и без поправки реплика оказывалась ровно под ней (правило:
    // UI не должен закрывать облачко).
    // Высоту ленты берём, только если она реально показана и это лента, а не
    // случайный нулевой/растянутый элемент: иначе безопасная зона схлопывалась
    // и читалка дёргала страницу на каждой реплике.
    let nowH = 0;
    try {
      const ln = $('#nowLine');
      const shown = ln && ln.style && ln.style.display && ln.style.display !== 'none';
      const lr = ln && ln.getBoundingClientRect ? ln.getBoundingClientRect() : null;
      if (shown && lr && lr.height > 0 && lr.height < 120) nowH = lr.height + 8;
    } catch (e) { nowH = 0; }
    const safeBottom = sr.top + sr.height - 170 - nowH;  // панель чтения + лента
    if (top >= safeTop && bottom <= safeBottom) return;
    const want = sr.top + sr.height * 0.3;               // реплику — в верхнюю треть
    // Тот же единственный твин: followLine больше не тянет ленту отдельно от
    // перехода к следующей полосе.
    SMOOTH.to(Math.max(0, sc.scrollTop + top - want), 220);
  },
  /**
   * Chrome/WebView разрешает озвучку только «из жеста»: если между нажатием и
   * speak() есть await (распознавание, чтение буфера), speak молча отбивается
   * с ошибкой not-allowed — панель есть, звука нет. Пустая фраза в самом
   * обработчике нажатия разблокирует синтезатор.
   */
  prime() {
    // В АПК голос нативный: там нет правила «только из жеста», разблокировать нечего.
    if (VOICE.native()) { this.primed = true; return; }
    try {
      if (!VOICE.synth()) return;
      if (this.primed) { VOICE.resume(); return; }
      VOICE.speak(' ', { rate: 1, lang: 'ru-RU', volume: 0.05 });
      this.primed = true;
    } catch (e) { console.warn('голос не разблокировался', e); }
  },
  /**
   * Голос, которым читать.
   *
   * Возвращает null, если человек голос НЕ выбирал: тогда говорит системный
   * голос по умолчанию — тот, что стоит в «Настройки → Синтез речи» (Tera TTS
   * и любой другой). Раньше здесь брался первый русский голос движка, и это
   * молча подменяло выбор человека (замечание 28.10 22:4x).
   */
  pickVoice() {
    const cur = this.voice;
    if (!cur) return null;                       // «системный по умолчанию»
    let avail = [];
    try { avail = VOICE.voices() || []; } catch (e) { avail = []; }
    if (!avail.length) return null;              // список не отдан — пусть решает движок
    return avail.find(v => v.voiceURI === cur.voiceURI || v.name === cur.name) || null;
  },
  speakLine(line, then) {
    // «Прочитано» отмечаем ТОЛЬКО когда голос реально заговорил (нажатие ▶ не
    // считается). Раньше отметка ставилась сразу: если синтез отказывал (нет
    // голоса, not-allowed), строка считалась прочитанной и при продолжении
    // чтения ПРОПУСКАЛАСЬ — то есть текст терялся. Отказ = не отмечаем.
    let marked = false;
    if (!VOICE.available()) {
      toast('В этой среде нет синтеза речи: ни системного голоса, ни движка АПК', 8000);
      return;
    }
    const avail = VOICE.voices();
    if (!avail.length) {
      if (VOICE.native()) {
        // В АПК список голосов даёт Android. Пустой список ≠ «нет синтеза»:
        //  • движок ещё поднимается — ждём и повторяем (до двух раз);
        //  • движок готов, но список голосов не отдал — говорим системным
        //    голосом по умолчанию, а не молчим.
        if (VOICE.nativeReady() === false && (this._voiceTries || 0) < 2) {
          this._voiceTries = (this._voiceTries || 0) + 1;
          toast('Android TTS просыпается — повторю через секунду', 2500);
          setTimeout(() => { if (!this.stopped) this.speakLine(line, then); }, 1100);
          return;
        }
        if (!this._noVoiceHinted) {
          this._noVoiceHinted = true;
          console.warn('список голосов пуст, читаю системным голосом по умолчанию');
        }
      } else {
        toast('Система не дала ни одного голоса: Настройки Android → Синтез речи', 7000);
      }
    } else {
      this._voiceTries = 0;
    }
    const chosen = this.pickVoice();
    if (this.voice && !chosen) {
      // Выбранный раньше голос пропал (сменили движок синтеза, перезапустили
      // TTS). Не подсовываем «первый русский» — возвращаемся к системному и
      // говорим об этом один раз.
      toast('Голос «' + (this.voice.name || '') + '» пропал — читаю системным', 5000);
      this.voice = null;
    } else if (chosen && this.voice && chosen.voiceURI !== this.voice.voiceURI) {
      toast('Голос «' + (this.voice.name || '') + '» недоступен, читаю ' + chosen.name, 5000);
      this.voice = chosen;
    } else if (chosen) {
      this.voice = chosen;
    }
    // Явно выбранный голос — только если человек его выбирал. Иначе null:
    // мост не будет трогать голос и локаль, и заговорит системный (Tera TTS).
    // cancel() «на всякий случай» убивает очередь: следующий вызов уже не
    // запускается. Отменяем только если что-то реально звучит (в браузере) —
    // нативный движок отменять перед каждой репликой не нужно и вредно.
    if (!VOICE.native()) {
      const sw = VOICE.synth();
      try {
        if (sw && (sw.speaking || sw.pending)) VOICE.cancel();
      } catch (e) { /* ignore */ }
    }
    Reader.current = line;
    Reader.paintAllFrames();
    let started = false;
    const started0 = () => {
      started = true;
      marked = true;
      try { Reader.markSpoken(Reader.page, line.text); } catch (e) { /* не критично */ }
      // Тень по буквам стартует вместе со звуком, а не по нажатию кнопки.
      try { SpeakCursor.start(line.text, this.rate); } catch (e) { /* не критично */ }
    };
    const finished = () => { try { SpeakCursor.stop(); } catch (e) {} if (then) then(); };
    const failed = (code) => {
      this.speaking = false;
      try { SpeakCursor.stop(); } catch (err) {}
      // Не заговорил — снимаем возможную отметку, иначе строка потеряется.
      if (!started && marked) { try { Reader.unmarkSpoken(Reader.page, line.text); } catch (err) {} }
      // Молчать нельзя: раньше «голос не работает» выглядело как поломка
      // читалки, хотя движок просто отбил озвучку.
      if (code === 'not-allowed') toast('Браузер не разрешил озвучку — нажмите ▶ ещё раз', 5000);
      else if (code === 'interrupted' || code === 'canceled') { /* это наш cancel() */ }
      else toast('Голос не сказал: ' + code, 5000);
      if (then) then();
    };
    const accepted = VOICE.speak(line.text, {
      lang: (this.voice && this.voice.lang) || 'ru-RU',
      rate: this.rate,
      voice: this.voice,
      onstart: started0,
      // Точная граница слова (Chrome отдаёт её как name:'word'). Нативный Android
      // TTS границ не шлёт — там тень идёт по оценке, ровно как и раньше.
      onboundary: (ci) => { try { SpeakCursor.boundary(ci || 0); } catch (err) { /* ignore */ } },
      onend: finished,
      onerror: (e) => failed((e && e.error) || 'unknown'),
    });
    if (!accepted) {
      toast('Синтез отказал: движок не принял фразу', 6000);
      return;
    }
    // Если синтез не начал говорить и не сообщил ошибку — молчать нельзя:
    // именно это выглядело как «голос по умолчанию молчит».
    clearTimeout(this._watch);
    const watchdog = (ms) => {
      clearTimeout(this._watch);
      this._watch = setTimeout(() => {
        if (started || this.stopped) return;
        if (VOICE.native()) {
          // Не заговорил — пробуем ещё раз системным голосом БЕЗ выбора
          // конкретного голоса и без скорости. Раньше при «движок молчит»
          // страница просто останавливалась, и это выглядело как «голос умер».
          if ((this._softAgain || 0) < 1) {
            this._softAgain = (this._softAgain || 0) + 1;
            try {
              VOICE.speak(line.text, {
                lang: 'ru-RU', rate: 1, voice: null,
                onstart: () => { started = true; },
                onend: () => { if (then) then(); },
                onerror: (e) => { console.warn('голос: повтор не удался', e); },
              });
            } catch (e) { console.warn('голос: повтор не запустился', e); }
            watchdog(2200);
            return;
          }
          const st = VOICE.statusText ? VOICE.statusText() : '';
          toast('Голос не заговорил. ⚙ → «Проверить голос»' + (st ? ': ' + st : ''), 7000);
          return;
        }
        // Браузер: молчание Web Speech видно по speaking/pending.
        const sw = VOICE.synth();
        if (sw && !sw.speaking && !sw.pending) {
          toast('Синтез не ответил. Нажмите ⚙ → «Проверить голос»', 6000);
        }
      }, ms);
    };
    watchdog(1500);
    // Прокрутка — ПОСЛЕ запуска речи и в try: ошибка геометрии не должна съедать звук.
    try { this.followLine(line); } catch (e) { console.warn('не прокрутил к реплике', e); }
    // Пока звучит эта реплика — тихо распознаём следующую полосу. Так переход
    // не упирается в ожидание: к моменту «дочитал» текст уже готов.
    try { Reader.prefetchBandAhead(); } catch (e) { console.warn('предраспознавание полосы', e); }
  },
  /** Пауза: в браузере — настоящая, в АПК — остановка с продолжением реплики заново. */
  pauseRead() {
    const mode = VOICE.pause();
    setTimeout(() => NATIVE_UI.push(), 0);
    if (mode === 'restart') {
      this.pausedLine = Reader.current;
      toast('В приложении пауза = стоп: продолжу эту реплику сначала', 3500);
    }
    return mode;
  },
  resumeRead() {
    setTimeout(() => NATIVE_UI.push(), 0);
    if (VOICE.native()) {
      const line = this.pausedLine;
      this.pausedLine = null;
      if (line) { this.speakLine(line, () => { if (!this.stopped) this.step(); }); return true; }
      return false;
    }
    return VOICE.resume();
  },
  async readVisible(opts = {}) {
    // fromStart — человек нажал ▶ сам. Тогда читаем С ВЕРХА видимой полосы,
    // включая то, что уже было прочитано раньше. Раньше отметки «прочитано»
    // соблюдались и при явном нажатии: страница молча ждала, пока дойдёшь до
    // места, где остановился в прошлый раз (жалоба с телефона 22:41).
    const fromStart = !!opts.fromStart;
    // Если страница ещё не распознана — сначала распознать, потом читать.
    // Раньше в этот момент вылезало «На этой полосе нет распознанного текста»
    // прямо во время сканирования, хотя текст вот он.
    const i = Reader.page;
    // Конвейер: распознаём и читаем одновременно. Голос начинает с первой
    // готовой реплики, остальные досчитываются, пока звучит речь.
    if (OCR.ready && !State.scanning && RULES.pipeline === true
        && !Reader.unspokenInBand().length && !Reader.regions.get(i)) {
      return this.readWhileScanning();
    }
    if (!Reader.regions.get(i)) {
      if (State.scanning) {
        toast('Распознаю страницу, начну читать сразу после', 4000);
        const wait = setInterval(() => {
          if (!State.scanning) {
            clearInterval(wait);
            if (Reader.regions.get(i) && !this.stopped && !State.waitingScroll) this.readVisible();
          }
        }, 400);
        return;
      }
      if (OCR.ready) {
        toast('Сначала распознаю страницу…', 4000);
        await Reader.scanCurrent(false, det);        // детекция уже есть — второй раз не гоняем
      }
    }
    const lines = fromStart ? Reader.visibleLines() : Reader.unspokenInBand();
    if (!lines.length && Reader.visibleLines().length) {
      // На этой полосе всё прочитано — переходим к следующему куску.
      return this.advanceReading();
    }
    if (!lines.length && !Reader.visibleLines().length) {
      if (Reader.scrollBusy) return toast('Лента едет — дочитаю, когда остановится', 3000);
      const data = Reader.regions.get(i);
      if (!data) { toast('Сначала нужно распознать страницу: ✨ Текст страницы', 4000); return; }
      toast('На этой полосе нет распознанного текста — прокрутите к репликам', 4000);
      return;
    }
    this.queue = lines.slice();          // только непрочитанное на этой полосе
    this.stopped = false; this.idx = 0;
    this._softAgain = 0;                 // новый запуск — снова есть право на повтор
    Reader.prefetchNext();               // следующая страница — пока слушаем эту
    $('#playBar').style.display = 'flex';
    $('#btnRead').textContent = '⏸';
    this.step();
  },
  /**
   * Читать и распознавать одновременно.
   *
   * Не по строкам: построчная отдача рвала реплики на куски («УЖЕ ПОРА НА-» +
   * «ЧИНАТЬ ВСТРЕЧУ,»), а реплику резать нельзя. Поэтому так: сначала
   * распознаём ТОЛЬКО первую целую реплику (0,57 с «Быстро», 0,70 с «Обычно»)
   * и сразу начинаем её читать, а пока звучит речь — распознаём полосу
   * целиком и продолжаем с того, что ещё не прочитано.
   */
  async readWhileScanning() {
    this.queue = []; this.idx = 0; this.stopped = false;
    this.scanDone = false;
    $('#playBar').style.display = 'flex';
    $('#btnRead').textContent = '⏸';
    $('#playStatus').textContent = 'распознаю…';
    const i = Reader.page;
    const c = Reader.canvases[i];
    const band = Reader.visibleBandPx(i);
    const bandCanvas = (() => {
      if (!c) return null;
      if (!band) return c;
      const y0 = Math.max(0, Math.round(band.y0)), y1 = Math.min(c.height, Math.round(band.y1));
      const out = makeCanvas(c.width, Math.max(1, y1 - y0));
      out.getContext('2d', { willReadFrequently: true })
        .drawImage(c, 0, y0, c.width, y1 - y0, 0, 0, c.width, y1 - y0);
      return out;
    })();
    let first = null, det = null;
    if (bandCanvas && OCR.ready) {
      try {
        det = await detectWithRetry(bandCanvas, RULES);           // ~450 мс
        first = await recognizeFirstBubble(bandCanvas, RULES,
          band ? { ...band, y0: 0 } : null, det).catch(() => null);  // +100…300 мс
      } catch (e) { console.warn('конвейер: детектор не сработал', e); det = null; }
    }
    if (first) {
      // Первую реплику конвейера прогоняем через ТОТ ЖЕ фильтр, что и остальные
      // строки страницы (cleanLines): иначе в чтение пролезало то, что при
      // обычном распознавании отбрасывается — например, обрывок титульной
      // надписи с ошибкой в слове (эмулятор Forge, 29.10: первым звучало
      // «Как прожить жизнь, оддучиг старшей сестрой тирана.»).
      let firstText = first;
      try {
        const cleaned = await cleanLines([{ text: first, top: 0, bottom: 0.002, confidence: 1 }]);
        firstText = cleaned.length ? String(cleaned[0].text || '').trim() : '';
      } catch (e) { firstText = first; }
      if (firstText && (firstText.match(/\p{L}/gu) || []).length >= 2) {
        $('#playStatus').textContent = '';
        this.queue.push({ text: firstText, top: 0, bottom: 0 });
        this.step();                  // голос пошёл, пока идёт распознавание полосы
      }
    }
    $('#scanBadge').classList.add('on');
    $('#scanBadge').textContent = 'Распознаём… стр. ' + (i + 1);
    try {
      await Reader.scanCurrent(false);
    } catch (e) { console.warn('конвейер: полоса не распозналась', e); }
    finally {
      this.scanDone = true;
      $('#scanBadge').classList.remove('on');
    }
    // Дальше — обычный путь по уже распознанной полосе (первая реплика уже
    // отмечена прочитанной, поэтому повторно не читается).
    if (!this.stopped) {
      const rest = Reader.unspokenInBand();
      if (rest.length) this.readQueue(rest);
      else if (!first) this.readVisible();
    }
  },
  step() {
    if (this.stopped) return;
    Reader.saveSpoken();
    if (this.idx >= this.queue.length) {
      // Конвейер: реплики ещё идут — ждём следующую, а не заканчиваем чтение.
      if (State.scanning && !this.scanDone) {
        $('#playStatus').textContent = 'распознаю…';
        clearTimeout(this._waitMore);
        this._waitMore = setTimeout(() => { if (!this.stopped) this.step(); }, 150);
        return;
      }
      $('#playStatus').textContent = '';
      NATIVE_UI.push();
      this.onQueueEnd();
      return;
    }
    const line = this.queue[this.idx++];
    this.curLine = line;                       // что звучит — для панели и ⟲
    this.curIdx = this.idx;
    $('#playStatus').textContent = (RULES.semiManual && State.semi) ? 'ждём прокрутки' : '';
    NATIVE_UI.push();
    this.speakLine(line, () => { if (!this.stopped) this.step(); });
  },
  /**
   * Дальше по чтению: следующая полоса той же страницы → следующая страница →
   * конец книги. Раньше сразу прыгали на следующую СТРАНИЦУ, и остаток
   * длинной страницы не читался. И полосу перед чтением обязательно
   * распознаём: «страница уже есть в памяти» не значит «есть эта полоса».
   */
  async advanceReading() {
    // ОДИН проход за раз. Раньше два вызова (из step и из конвейера) шли
    // параллельно: каждый считал «следующую полосу» и дёргал ленту — отсюда
    // «дёрнулся, потом ещё дважды, а прочитал одну реплику» (телефон 28.10).
    if (this._advancing) return;
    this._advancing = true;
    try {
      let page = Reader.page;
      for (let guard = 0; guard < 64; guard++) {
        if (this.stopped) return;
        Reader.page = page;
        const bands = Reader.bands || [];
        let found = null, foundNi = -1;
        for (let ni = (Reader.bandIndex || 0) + 1; ni < bands.length; ni++) {
          const un = await Reader.ensureBandLines(page, ni);
          if (this.stopped) return;
          if (un.length) { found = un; foundNi = ni; break; }
          // Полоса пустая после распознавания — идём дальше, но БЕЗ прокрутки.
        }
        if (found) {
          Reader.bandIndex = foundNi;
          Reader.band = bands[foundNi] || Reader.band;
          Reader.page = page;
          Reader.scrollToLineIfNeeded(page, found[0]);
          // Ждём именно остановки ленты, а не «примерно 160 мс»: раньше голос
          // начинал реплику, пока страница ещё ехала, и она прыгала под звук.
          await SMOOTH.done();
          await sleep(40);
          Reader.page = page;
          return this.readQueue(found);
        }
        // Полосы кончились, а на странице остались непрочитанные реплики
        // (например, текст попал в полосу, которую мы не считали текущей):
        // читаем их, а не прыгаем дальше молча.
        Reader.bandIndex = bands.length;
        const rest = Reader.unspokenPage();
        if (rest.length) { Reader.page = page; return this.readQueue(rest); }

        // Следующая страница. Тоже: распознать, потом листать.
        if (page < Reader.pages.length - 1) {
          const next = page + 1;
          await Reader.ensureLoaded(next);
          Reader.page = next;
          Reader.bandIndex = 0;
          Reader.band = (Reader.bands || [])[0] || null;
          await Reader.waitIdle();
          if (!Reader.regions.get(next)) {
            await Reader.scanPage(next, { full: true, silent: true }).catch(() => {});
          }
          Reader.page = next;
          Reader.band = (Reader.bands || [])[0] || null;
          const un = Reader.unspokenInBand();
          if (un.length) {
            Reader.scrollToLineIfNeeded(next, un[0]);
            return this.readQueue(un);
          }
          const restNext = Reader.unspokenPage();
          if (restNext.length) return this.readQueue(restNext);
          page = next;
          continue;
        }
        this.stop();
        toast('Конец книги', 2500);
        return;
      }
    } finally {
      this._advancing = false;
    }
  },

  /** Прочитать ровно этот список реплик (без повторного вывода полосы). */
  readQueue(lines) {
    this.queue = lines.slice();
    this.idx = 0;
    this.curLine = null; this.curIdx = 0;
    this.stopped = false;
    $('#playBar').style.display = 'flex';
    $('#btnRead').textContent = '⏸';
    Reader.prefetchNext();
    this.step();
  },

  async onQueueEnd() {
    Reader.current = null;
    Reader.paintAllFrames();
    if (!RULES.semiManual || !State.semi) {
      // обычный режим: следующая полоса → следующая страница → конец книги
      return this.advanceReading();
    }
    // полуручной: встали и ждём прокрутки
    State.waitingScroll = true;
    $('#playBar').style.display = 'flex';
    $('#playStatus').textContent = 'ждём прокрутки';
    showArrow();
  },
};

/* ───────────────────────── 11. Состояние и интерфейс ───────────────────────── */
const State = { scanning: false, prefetching: false, semi: false, waitingScroll: false, autoScroll: true, pendingScan: null };

function show(id) {
  $$('.screen').forEach(s => s.classList.toggle('on', s.id === id));
}
function openSheet(id) {
  $$('.sheet').forEach(s => s.classList.toggle('on', s.id === id));
  const bg = $('#sheetBg');
  if (bg) bg.classList.toggle('on', !!id);
  // Новая шторка всегда открывается сверху, а не с прокруткой от прошлой.
  const sh = document.getElementById(id);
  if (sh) { const b = sh.querySelector('.body'); if (b) b.scrollTop = 0; }
}
function closeSheets() {
  $$('.sheet').forEach(s => s.classList.remove('on'));
  const bg = $('#sheetBg');
  if (bg) bg.classList.remove('on');
}

function showArrow() {
  const a = $('#nextArrow');
  a.className = 'nextArrow ' + (Reader.mode === 'vertical' ? 'down' : Reader.mode === 'rtl' ? 'left' : 'right');
  a.textContent = Reader.mode === 'vertical' ? '▼ Прокрутить' : Reader.mode === 'rtl' ? '◀ Прокрутить' : '▶ Прокрутить';
  a.style.display = 'flex';
}
function hideArrow() { $('#nextArrow').style.display = 'none'; }

/**
 * Повторная чистка готовых строк: правила мусора менялись, а в буфере лежит
 * текст, распознанный раньше. Пустые строки выпадают вместе со своими рамками.
 */
async function cleanLines(lines) {
  const keyOf = (t) => String(t || '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  const out = [];
  for (const ln of lines) {
    // Мусорные края («*ь*.*о НЕ УВЕРЕН…») снимаем ПОСЛЕ словаря: обрывок
    // звукового эффекта приклеивается к реплике уже при склейке строк.
    let text = Words.ready ? Words.polish(ln.text, RULES.junkRatio, ln.confidence) : ln.text;
    text = trimJunkEdges(text || '');
    // Регистр: «ОНА Вс ШЕПЧЕТ» → «ОНА ВС ШЕПЧЕТ» (см. fixCaseInCaps).
    text = fixCaseInCaps(text);
    if (!text) continue;
    // Один и тот же текст в том же месте — дубль от полос прежней версии.
    const k = keyOf(text);
    const dup = k && out.some(o => keyOf(o.text) === k
      && Math.min(o.bottom, ln.bottom) > Math.max(o.top, ln.top));
    if (dup) continue;
    out.push(text === ln.text ? ln : { ...ln, text });
  }
  return out;
}

/**
 * Текст, вставленный из Google Lens, становится обычными репликами страницы.
 * Геометрия приблизительная (Lens не отдаёт нам координаты), поэтому в шторке
 * это честно написано: рамки — по номерам сверху вниз, а не по пикселям.
 */
async function applyLensText(pageIndex, text, opts = {}) {
  const lines = LENS.textToLines(text);
  if (!lines.length) return { ok: false, reason: 'в тексте нет ни одной строки с буквами' };

  // ── Где на картинке эти строки ────────────────────────────────────────────
  // Lens координат не отдаёт. Раньше строки раскладывались равными полосами на
  // всю ширину — и первая рамка накрывала шапку страницы, что выглядело как
  // «какая-то синяя рамка ни о чём». Теперь, если локальный детектор доступен
  // (он у нас есть и работает ~0,4 с), рамки ставятся по найденным облачкам
  // в том же порядке, в каком идёт текст. Равные полосы остаются запасным
  // вариантом: без моделей или когда детектор ничего не нашёл.
  let placed = 'band';
  const cv = Reader.canvases[pageIndex];
  if (cv && OCR.ready && opts.detect !== false) {
    try {
      const det = await detectWithRetry(cv, RULES);
      const rtl = (Reader.dir || 'rtl') === 'rtl';
      const boxes = (det.boxes || [])
        .filter(b => (b.right - b.left) > cv.width * 0.03 && (b.bottom - b.top) > cv.height * 0.006)
        .sort((a, b) => (a.top - b.top) || (rtl ? b.left - a.left : a.left - b.left));
      // Рамки ставим, если детектор нашёл хотя бы два облачка. Соответствие
      // «реплика ↔ облачко» при этом ПРИБЛИЗИТЕЛЬНОЕ (Lens может склеить или
      // разбить иначе), поэтому рамка всегда рисуется пунктиром с номером и не
      // притворяется точным адресом реплики.
      const fit = boxes.length >= 2;
      if (fit) {
        lines.forEach((line, i) => {
          const b = boxes[Math.min(boxes.length - 1, Math.floor(i * boxes.length / lines.length))];
          line.left = +(b.left / cv.width).toFixed(4);
          line.right = +(b.right / cv.width).toFixed(4);
          line.top = +(b.top / cv.height).toFixed(4);
          line.bottom = +(b.bottom / cv.height).toFixed(4);
          line.lensPlaced = 'det';        // место найдено детектором, текст — из Lens
        });
        placed = 'det';
      }
    } catch (e) { console.warn('Lens: детектор не сработал, ставлю полосы', e); }
  }
  if (placed !== 'det') for (const line of lines) line.lensPlaced = 'band';

  // Собираем запись С НУЛЯ, не подмешивая то, что осталось от локального OCR:
  // иначе в ней жили бы старые regions/ms, и «Распознать заново» или смена
  // направления чтения дёргали бы данные, которых больше нет.
  const at = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  Reader.regions.set(pageIndex, {
    lines, regions: null, cached: true, fromLens: true, lensPlaced: placed,
    ms: 0, detMs: 0, recMs: 0, crops: 0, boxes: 0, bands: 0, at,
  });
  // Полоса-кэш сбрасываем: иначе следующее распознавание вернёт старые строки.
  if (Reader.bandCache instanceof Map) Reader.bandCache.delete(pageIndex);
  // Прочитанное от прошлого текста к новому не относится.
  try { Reader.spoken.clear(); } catch (e) { /* не критично */ }
  Reader.current = null;
  Reader.paintPage(pageIndex);
  if ($('#sheetText').classList.contains('on')) renderTextSheet(pageIndex);
  return { ok: true, lines: lines.length, placed };
}

/** Шторка Lens: состояние + какая страница ждёт текст. */
function renderLensSheet(pageIndex) {
  const i = pageIndex ?? LENS.pendingPage ?? Reader.textPage ?? Reader.page;
  LENS.pendingPage = i;
  const st = $('#lensState');
  if (st) {
    const own = Reader.regions.get(i);
    const tr = LENS.transports();
    const howDirect = tr.includes('native') ? 'движок АПК (без сайта)'
      : tr.includes('relay') ? 'через свой релей (без сайта)' : '';
    st.innerHTML = `Движок: <b>${LENS.isLens() ? 'Google Lens' : 'в файле (офлайн)'}</b>`
      + ` · страница ${i + 1}`
      + (howDirect ? ` · прямой путь: <b style="color:#8fd18f">${howDirect}</b>` : ' · прямой путь не настроен')
      + (own && own.fromLens ? ` · в странице уже ${own.lines.length} реплик из Lens` : '')
      + (LENS.lastSentAt ? ' · отправлено ' + new Date(LENS.lastSentAt).toLocaleTimeString('ru-RU') : '')
      + (LENS.lastDirect ? ` · прямой ответ ${LENS.lastDirect.ms} мс` : '');
  }
  // Почему прямой путь доступен или нет — прямо в шторке, до нажатия кнопок.
  const why = $('#lensDirectWhy');
  if (why) {
    const tr = LENS.transports();
    why.innerHTML = tr.length
      ? 'Прямой путь: <b style="color:#8fd18f">'
        + (tr.includes('native') ? 'движок АПК (KomaLens)' : 'свой релей')
        + '</b> — сайт не открывается, текст вернётся сюда сам.'
      : 'Прямой путь не настроен: в браузере Google не отдаёт ответ чужой странице, '
        + 'а в АПК подключится встроенный движок. Пока работает сайт и вставка текста.';
  }
  const box = $('#lensBox');
  if (box && !box.value) {
    const own = Reader.regions.get(i);
    if (own && own.fromLens) box.value = own.lines.map(l => l.text).join('\n');
  }
}

async function renderTextSheet(i) {
  // Открывая шторку, сначала сверяем индекс с тем, что реально на экране:
  // раньше здесь стоял «застрявший» Reader.page, и текст открывался не той
  // страницы, которую человек видит.
  if (i == null) i = Reader.syncPage();
  const onScreen = Reader.pageAtViewport();
  const data = Reader.regions.get(i);
  $('#textTitle').innerHTML = `Текст страницы ${i + 1}`
    + (i === onScreen ? '' : `<span class="hint" style="font-weight:400"> · на экране стр. ${onScreen + 1}</span>`);
  if ($('#textNav')) {
    const hasPrev = i > 0, hasNext = i < Reader.pages.length - 1;
    $('#textNav').innerHTML = `<button class="btn" id="textPrev" ${hasPrev ? '' : 'disabled'}>◀${hasPrev ? ' стр. ' + i : ''}</button>`
      + `<span class="hint" style="align-self:center">${i + 1} из ${Reader.pages.length}</span>`
      + `<button class="btn" id="textNext" ${hasNext ? '' : 'disabled'}>${hasNext ? 'стр. ' + (i + 2) + ' ' : ''}▶</button>`;
    if ($('#textPrev')) $('#textPrev').onclick = () => renderTextSheet(i - 1);
    if ($('#textNext')) $('#textNext').onclick = () => renderTextSheet(i + 1);
  }
  if (!data) { $('#textStats').textContent = 'Страница ещё не распознана'; $('#textOrdered').innerHTML = ''; $('#textRaw').textContent = ''; return; }
  Reader.textPage = i;
  const raw = data.regions || [];
  const stamp = data.at ? ' · обновлено ' + data.at : '';
  $('#textStats').textContent = (data.fromLens
    ? `${data.lines.length} реплик · текст из Google Lens · `
      + (data.lensPlaced === 'det' ? 'рамки по облачкам (найдены локально, порядок из Lens)' : 'рамки примерные — полосы')
    : data.cached
    ? `${data.lines.length} реплик · из буфера (без повторного распознавания)`
    : `${raw.length} строк · ${Number.isFinite(data.boxes) ? data.boxes : raw.length} блоков · ${data.crops || 0} кропов · `
      // Нативный проход неделим (детектор и распознавание — один вызов), поэтому
      // вместо двух чисел печатаем одно и слово «нативно». Раньше здесь были
      // подстановки undefined → «NaN с» и «0.0 с» (телефон 22:42).
      + ((data.detPass === 'native' || data.via === 'native')
        ? `итого ${(Number(data.ms) || 0) / 1000 < 0.05 ? '?' : ((Number(data.ms) || 0) / 1000).toFixed(1)} с нативно (одним проходом)`
        : `итого ${((Number(data.ms) || 0) / 1000).toFixed(1)} с = детектор ${((Number(data.detMs) || 0) / 1000).toFixed(1)} с `
          + `+ распознавание ${((Number(data.recMs) || 0) / 1000).toFixed(1)} с`)
      + (data.bands > 1 ? ` · полос: ${data.bands}` : '')
      + (data.detPass && data.detPass !== 'normal'
        ? ' · детектор нашёл со 2-й попытки: ' + ({
          contrast: 'контраст', binary: 'бинаризация',
          'binary-inv': 'инверсия', imagenet: 'нормализация кадра',
        }[data.detPass] || data.detPass) : '')
      + (data.largePasses ? ` · 2-й проход по крупному тексту: ${data.largePasses}` : '')
      + (data.variantRuns ? ` · перебор вариантов: ${data.variantRuns}` : '')
      + (data.uncoveredLines ? ` · строк вне боксов: ${data.uncoveredLines}` : '')
      + (data.wordsFixed ? ` · дочинено слов: ${data.wordsFixed}` : '')
      + stamp);
  // Показываем ВСЕ реплики страницы, включая уже прочитанные: прочитанное не
  // исчезает из списка, а помечается. Иначе выглядело бы, будто текст пропал.
  // Группируем по полосам страницы. Раньше был один общий список, и на
  // странице 3 в нём оказалась реплика, которую видно на странице 2 — это
  // выглядело как чужие/пропавшие реплики.
  const bandOf = (l) => (Number.isFinite(l.bandTop) ? l.bandTop : 0);
  const groups = new Map();
  for (const l of data.lines) {
    const k = bandOf(l);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(l);
  }
  const curTop = Reader.band && Number.isFinite(Reader.band.y0) ? Math.round(Reader.band.y0) : null;
  let counter = 0;
  $('#textOrdered').innerHTML = data.lines.length
    ? Array.from(groups.entries()).sort((a, b) => a[0] - b[0]).map(([top, list]) => {
        const onScreen = curTop != null && Math.abs(top - curTop) < 12;
        const head = groups.size > 1
          ? `<div class="hint" style="margin:6px 0 2px">${onScreen ? '● на экране' : '○ распознано раньше'}</div>`
          : '';
        return head + list.map((l) => {
          counter++;
          const done = Reader.spoken.has(Reader.spokenKey(i, l.text));
          return `<div class="lineitem${l.large ? ' large' : ''}">`
            + `<b>${counter}</b>${done ? '<span class="done">✔ </span>' : ''}${escapeHtml(l.text)}`
            + (l.large ? '<span class="hint"> · крупный текст</span>' : '')
            + (done ? '<span class="hint"> · прочитано</span>' : '') + '</div>';
        }).join('');
      }).join('')
    : '<div class="hint">Реплик не найдено</div>';
  $('#textRaw').textContent = raw.map(r => r.text).join('\n') || '—';
}
async function renderBufferSheet() {
  const items = await Buffer.all();
  const total = items.reduce((a, b) => a + b.lines.length, 0);
  $('#bufferInfo').textContent = `Страниц в буфере: ${items.length} · строк: ${total}`;
  $('#bufferList').innerHTML = items.map(p => p.lines.map(l =>
    `<div class="lineitem"><b>${p.page + 1}</b>${escapeHtml(l.text)}</div>`).join('')).join('');
}
function renderRulesInfo() {
  $('#rulesVer').textContent = `Версия: ${RULES.version}`+
    (RULES.wordFixes && Object.keys(RULES.wordFixes).length ? ` · правок слов: ${Object.keys(RULES.wordFixes).length}` : '');
  $('#wordFixesBox').value = JSON.stringify(RULES.wordFixes || {}, null, 2);
}

/* ─── модели ─── */
async function renderModels() {
  const det = await DB.get('kv', 'model:det');
  const rec = await DB.get('kv', 'model:rec');
  const dict = await DB.get('kv', 'model:dict');
  const f = (x, n) => x ? `${n}: ${(x.v.byteLength / 1048576).toFixed(1)} МБ` : `${n}: нет`;
  const mark = (ok) => ok ? '✅' : '❌';
  const noneYet = !det && !rec && !dict;
  $('#modelsState').innerHTML = [
    noneYet ? '❌ моделей нет — выберите три файла кнопкой «Выбрать файлы» ниже' : '',
    `${mark(!!det)} ${f(det, 'detection.onnx')}`,
    `${mark(!!rec)} ${f(rec, 'cyrillic.onnx')}`,
    `${mark(!!dict)} ${dict ? `cyrillic.txt: ${String(dict.v).split('\n').filter(Boolean).length} символов` : 'cyrillic.txt: нет'}`,
    (await DB.get('kv', 'model:rec2'))
      ? `➕ второй распознаватель: ${OCR.rec2 ? 'подключён — ' + (OCR.rec2Note || 'трудные строки') : 'есть, но ' + (OCR.rec2Note || 'не подключён')}`
      : '➕ второй распознаватель: нет (не обязательно)',
  ].filter(Boolean).join('<br>');
  const note = $('#engineNote');
  if (note) {
    note.style.display = OCR.engine === 'blocked' || OCR.engine === 'failed' ? 'block' : 'none';
    note.innerHTML = OCR.engine === 'blocked'
      ? 'Так выглядит запрет WebAssembly на этой странице (предпросмотр в приложении). '
        + 'Модели уже сохранены — открывать заново не нужно. Скачайте файл и откройте в Chrome: '
        + 'там движок поднимется с теми же тремя файлами.'
      : '';
  }
  if ($('#dictState')) {
    const row = Words.ready
      ? (Words.ordered === false
        ? '⚠️ словарь: ' + Words.size.toLocaleString('ru-RU') + ' слов (' + (Words.source || 'свой файл')
          + '). Список не по убыванию частоты, поэтому правка слов выключена: слова не '
          + 'исправляются, но и верные не портятся. Чтобы правка работала, нужен словарь '
          + 'по частоте (как ru_250k).'
        : '✅ словарь: ' + Words.size.toLocaleString('ru-RU') + ' слов (' + (Words.source || 'вшит') + ')')
      : '❌ словарь не разжался — мусорные строки попадут в озвучку';
    $('#dictState').innerHTML = row;
  }
  $('#ortState').textContent = (typeof ort === 'undefined')
    ? 'onnxruntime-web не загрузился: нужна сеть при первом открытии файла.'
    : OCR.statusText() + (OCR.reason ? ' — ' + OCR.reason : '');
  renderNativeOcr().catch(() => {});
}

/**
 * Блок «Нативный движок» в шторке моделей.
 * Показывается только там, где есть мост `window.KomaOcr` (то есть в АПК):
 * в браузере считать модели нативно нечем, и кнопок-обманок там нет.
 */
async function renderNativeOcr() {
  const block = $('#nativeOcrBlock');
  if (!block) return;
  if (typeof NativeOcr === 'undefined' || !NativeOcr.present()) { block.style.display = 'none'; return; }
  block.style.display = 'block';
  const st = NativeOcr.status();
  const mb = (n) => n ? (n / 1048576).toFixed(1) + ' МБ' : 'нет';
  const mark = (ok) => (ok ? '✅' : '❌');
  const files = st.files || {};
  const embedded = !!st.embedded;
  // Модели встроены в сборку и раскладываются при первом запуске: пока они
  // копируются, честно пишем «готовлю», а не «модели не выбраны» — иначе
  // человек видит красные кресты на свежей установке и думает, что всё сломано.
  const seeding = embedded && !st.models;
  const rows = [];
  if (embedded) {
    rows.push('📦 модели вшиты в приложение — выбирать файлы не нужно');
  }
  rows.push(
    `${mark(st.models)} детектор: ${mb(files['det.onnx'])}`,
    `${mark(st.models)} распознаватель: ${mb(files['rec.onnx'])}`,
    `${mark(st.classes > 0)} азбука: ${st.classes ? (st.classes - 1) + ' символов' : 'нет'}`,
    seeding ? '⏳ раскладываю встроенные модели (первый запуск, пара секунд)'
      : (st.ready ? '✅ движок готов'
        : '❌ ' + (st.error || (embedded ? 'модели готовятся' : 'модели не выбраны'))),
    'считает: <b>' + (NativeOcr.chosen() === 'native' ? 'нативно (ONNX Runtime)' : 'WASM в странице') + '</b>'
      + (OCR.nativeNote ? '<br><span class="hint">последний раз нативный путь: ' + escapeHtml(OCR.nativeNote) + '</span>' : ''),
  );
  // Пока идёт раскладка — переспрашиваем, но не бесконечно.
  if (seeding) {
    if (renderNativeOcr.tries === undefined) renderNativeOcr.tries = 0;
    if (renderNativeOcr.tries < 20) {
      renderNativeOcr.tries++;
      setTimeout(() => { renderNativeOcr().catch(() => {}); }, 700);
    }
  } else {
    renderNativeOcr.tries = 0;
  }
  $('#nativeOcrState').innerHTML = rows.join('<br>');
  // Кнопки выбора движка показывают, что выбрано в правилах.
  const mode = (RULES && RULES.ocrEngine) || 'auto';
  const hot = (id) => { const b = $(id); if (b) b.classList.toggle('hot', b.dataset.ocr === mode); };
  hot('#btnEngineAuto'); hot('#btnEngineNative'); hot('#btnEngineWasm');
}
/**
 * Проверка движка на синтетической странице: гоняем ровно тот же путь, что и на
 * кадре, но на картинке, нарисованной кодом. Так видно, работает ли WASM, не
 * открывая главу. Если WASM запрещён политикой страницы (предпросмотр), здесь
 * это будет сказано прямо, а не «движок загружен, моделей нет».
 */
/**
 * Проверка голоса по нажатию: говорит тестовую фразу и возвращает отчёт о том,
 * что видит браузер. Нужна, потому что «молчит» — это три разные причины
 * (нет голосов в системе, браузер запретил озвучку, синтез не ответил).
 */
async function selfTestVoice() {
  if (!VOICE.available()) {
    // Раньше здесь было «В этой среде вообще нет синтеза речи (speechSynthesis
    // undefined)» — и это единственное, что видел человек в АПК до 28.10.
    return 'Синтеза речи нет: ни Web Speech в этой среде, ни движка АПК KomaSpeech';
  }
  const avail = VOICE.voices();
  const chosen = TTS.pickVoice();
  const parts = [];
  parts.push('движок: ' + VOICE.kind());
  parts.push('голосов: ' + avail.length);
  parts.push('выбран: ' + (chosen ? chosen.name + ' [' + chosen.lang + ']' : 'системный по умолчанию (ru-RU)'));
  if (VOICE.native()) {
    const ready = VOICE.nativeReady();
    parts.push(ready ? 'Android TTS готов' : 'Android TTS не готов (нет данных движка)');
  }
  let started = false, err = '';
  const accepted = VOICE.speak('Проверка голоса. Раз, два, три.', {
    lang: (chosen && chosen.lang) || 'ru-RU',
    rate: TTS.rate || 1,
    voice: chosen,
    onstart: () => { started = true; },
    onerror: (e) => { err = (e && e.error) || 'unknown'; },
  });
  if (!accepted) {
    parts.push('движок не принял фразу');
    return parts.join(' · ');
  }
  await sleep(1500);
  parts.push(started ? 'синтез заговорил' : (err ? 'ошибка синтеза: ' + err : 'синтез не ответил за 1,5 с'));
  return parts.join(' · ');
}

async function selfTestEngine() {
  if (!OCR.ready) {
    const ok = await OCR.loadModels().catch(e => { OCR.engine = 'failed'; OCR.reason = String(e.message || e); return false; });
    if (!ok) { await renderModels(); toast(OCR.statusText() + (OCR.reason ? ': ' + OCR.reason : ''), 8000); return; }
  }
  try {
    // Тестовая «страница» рисуется НАСТОЯЩИМ canvas: у элемента нет свойства
    // .data (оно было только в Node-заглушке), из-за этого проверка падала с
    // «Cannot read properties of undefined (reading 'length')».
    const W = 600, H = 800;
    const c = makeCanvas(W, H);
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#101010';
    for (let y = 120; y < 180; y += 2) ctx.fillRect(80, y, 440, 1);
    const boxes = await detectBoxes(c, DEFAULT_RULES.pageSide, RULES);
    toast(boxes.length
      ? 'Движок считает: детектор вернул ' + boxes.length + ' бокс(ов) на тестовой картинке'
      : 'Движок считает, но на тестовой картинке боксов 0 — проверьте модели', 7000);
    await renderModels();
  } catch (e) {
    toast('Движок не считает: ' + (e.message || e), 8000);
    OCR.engine = 'failed'; OCR.reason = String(e.message || e); await renderModels();
  }
}

/**
 * Принять любое количество выбранных файлов модели. Ключевое: шторку не
 * закрываем, разбираем по именам, показываем, чего ещё не хватает.
 */
async function storeModelFiles(files) {
  if (!files || !files.length) return;
  const saved = [];
  for (const f of files) {
    const n = f.name.toLowerCase();
    if (n === 'detection.onnx') { await DB.put('kv', { k: 'model:det', v: await f.arrayBuffer() }); saved.push('detection.onnx'); }
    else if (n === 'cyrillic.onnx') { await DB.put('kv', { k: 'model:rec', v: await f.arrayBuffer() }); saved.push('cyrillic.onnx'); }
    else if (n === 'cyrillic.txt') { await DB.put('kv', { k: 'model:dict', v: await f.text() }); saved.push('cyrillic.txt'); }
    // Второй распознаватель — по желанию. Имя файла принципиально другое,
    // чтобы его нельзя было принять за основной.
    else if (n === 'cyrillic2.onnx' || n === 'rec2.onnx' || n === 'line32.onnx'
             || n === 'best_r28_final.onnx' || n === 'best_finetuned_r4.onnx' || n === 'best_base_r3.onnx') {
      await DB.put('kv', { k: 'model:rec2', v: await f.arrayBuffer() });
      saved.push(f.name + ' (второй распознаватель)');
    }
    // Азбука второго распознавателя — отдельно от основного словаря:
    // перепутать нельзя, иначе основной распознаватель начнёт читать мусор.
    else if (n === 'charset.txt' || n === 'line32.txt') {
      await DB.put('kv', { k: 'model:rec2charset', v: await f.text() });
      saved.push(f.name + ' (азбука второго распознавателя)');
    }
  }
  if (!saved.length) {
    await renderModels();
    toast('Нужны файлы detection.onnx, cyrillic.onnx, cyrillic.txt — по именам. Выбрано: '
      + Array.from(files).map(f => f.name).join(', '), 6000);
    return;
  }
  await renderModels();
  const det = await DB.get('kv', 'model:det');
  const rec = await DB.get('kv', 'model:rec');
  const dict = await DB.get('kv', 'model:dict');
  const missing = [!det && 'detection.onnx', !rec && 'cyrillic.onnx', !dict && 'cyrillic.txt'].filter(Boolean);
  toast('Принято: ' + saved.join(', ') + (missing.length ? ' · ещё нужно: ' + missing.join(', ') : ''), 5000);
  if (!missing.length) {
    try {
      const ok = await OCR.loadModels();
      toast(ok ? 'Все три модели на месте, движок готов'
               : 'Модели сохранены. ' + OCR.statusText() + (OCR.reason ? ': ' + OCR.reason : ''), 9000);
    } catch (e) {
      OCR.engine = 'failed'; OCR.reason = String(e.message || e);
      toast('Движок не поднялся: ' + OCR.reason, 8000);
    }
    await renderModels();
    if (typeof selfCheck === 'function') await selfCheck();
  }
}

/* Совместимость: старый вход выбора моделей ведёт на общий разбор файлов,
   но НЕ через общий input библиотеки (из-за него выбор модели открывал читалку). */
async function pickModels() {
  const inp = document.getElementById('modelPick');
  if (inp) inp.click();
}

/* ─── прокрутка: ждём остановки ─── */
function watchScroll() {
  const strip = $('#strip');
  let t = null, raf = 0;
  // Человек тронул ленту пальцем — отдаём прокрутку ему, анимация чтения
  // уступает и не «догоняет» под пальцем.
  try {
    strip.addEventListener('touchstart', () => SMOOTH.stop(), { passive: true });
    strip.addEventListener('wheel', () => SMOOTH.stop(), { passive: true });
  } catch (e) { /* не критично */ }
  const busy = () => {
    Reader.scrollBusy = true;
    clearTimeout(t);
    t = setTimeout(async () => {
      Reader.scrollBusy = false;
      Reader.syncPage();
      onScrollSettled();
    }, Math.max(120, RULES.semiManualSettleMs));
  };
  const onScroll = () => {
    busy();
    // Страницу определяем НА КАЖДОМ кадре прокрутки, а не только когда
    // «успокоится»: иначе шапка и распознавание живут прошлой страницей.
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const before = Reader.page;
      Reader.syncPage();
      if (Reader.page !== before) {
        Reader.ensureLoaded(Reader.page);
        Reader.ensureLoaded(Reader.page + 1);
      }
    });
  };
  strip.addEventListener('scroll', onScroll, { passive: true });
  // В части браузеров scrollend есть — используем как точку «остановились».
  if ('onscrollend' in strip) strip.addEventListener('scrollend', () => Reader.syncPage(), { passive: true });
  window.addEventListener('resize', () => Reader.syncPage());
  window.addEventListener('orientationchange', () => setTimeout(() => Reader.syncPage(), 300));
  if (window.visualViewport) window.visualViewport.addEventListener('resize', () => Reader.syncPage());
  $('#paged').addEventListener('scroll', (e) => {
    if (e.target.classList && e.target.classList.contains('pagebox')) busy();
  }, true);
  $('#paged').addEventListener('touchmove', () => busy(), { passive: true });
  document.addEventListener('keydown', (e) => {
    if (!document.getElementById('reader').classList.contains('on')) return;
    if (e.key === 'ArrowRight' || e.key === 'PageDown') turnPage(1);
    if (e.key === 'ArrowLeft' || e.key === 'PageUp') turnPage(-1);
  });
}
/**
 * Собрать реплики страницы из полос без дублей.
 *
 * Полосы перекрываются (запас нужен детектору), поэтому одно и то же облачко
 * попадало в две-три полосы и реплика повторялась — на скриншоте 11:26 было
 * 11 реплик там, где в оригинале 5. Правило: полоса, распознанная позже,
 * вытесняет всё, что раньше попало в её вертикальный диапазон; одинаковый
 * текст с пересечением по вертикали тоже считается дублем.
 */
function mergeBandLines(parts, canvas) {
  const H = (canvas && canvas.height) || 1;
  const out = [];
  const keyOf = (t) => String(t || '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  const overlapV = (a, b) => Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
  for (const part of parts) {
    for (const ln of part.lines) {
      const k = keyOf(ln.text);
      const h = Math.max(1e-6, ln.bottom - ln.top);
      // Тот же текст в том же месте — дубль от перекрытия полос.
      if (k && out.some(o => keyOf(o.text) === k && overlapV(o, ln) > h * 0.2)) continue;
      // Разный текст на одном месте: оставляем тот, что осмысленнее. Ничего не
      // выбрасываем «по диапазону полосы» — так терялись реплики, которые
      // соседняя полоса просто не распознала.
      // «Одно и то же место» — это совпадение И по вертикали, И по горизонтали.
      // Раньше хватало вертикали, и две реплики на одной высоте (две колонки
      // газеты; два облачка рядом в манге) считались дублем друг друга: одна
      // молча выбрасывалась. Замер 28.10 на странице-прозе: 58 распознанных
      // строк → 2 реплики, потому что правая и левая колонки «перекрывались».
      const overlapH = (a, b) => Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const same = out.findIndex(o => {
        const oh = Math.max(1e-6, o.bottom - o.top);
        const ow = Math.max(1e-6, o.right - o.left);
        const w = Math.max(1e-6, ln.right - ln.left);
        return overlapV(o, ln) > Math.min(h, oh) * 0.6
          && overlapH(o, ln) > Math.min(w, ow) * 0.5;
      });
      if (same >= 0) {
        const q1 = qualityOf([out[same].text]) + Math.min(ln.text.length, 60) * 0.3;
        const q2 = qualityOf([ln.text]) + Math.min(ln.text.length, 60) * 0.3;
        if (q2 > q1) out[same] = ln;
        continue;
      }
      out.push(ln);
    }
  }
  // Порядок чтения: сверху вниз, а внутри строки — справа налево для манги.
  // Раньше здесь был простой `sort((a,b) => a.top - b.top)`, и он убивал
  // порядок: две реплики на одной высоте (или с разницей в 1–2 ‰) вставали по
  // левому краю, то есть для манги наоборот. Живой прогон 29.10: в нижней панели
  // «ОНА ВСЁ ЕЩЁ ШЕПЧЕТ» (справа) читалась ПОСЛЕДНЕЙ вместо первой.
  const rtl = (typeof Reader !== 'undefined' ? Reader.dir : 'rtl') !== 'ltr';
  return orderBubbles(out, rtl);
}

async function onScrollSettled() {
  if (!$('#reader').classList.contains('on')) return;
  const i = Reader.page;
  await Reader.ensureLoaded(i);
  // Распознаём видимую полосу, если она ещё не распознана (вебтун: страница
  // длиннее экрана, полосы идут по мере прокрутки).
  if (OCR.ready && !State.scanning && RULES.autoScan) {
    const band = Reader.visibleBandPx(i);
    const key = band ? band.key : 'page';
    const bandMap = Reader.bandCache.get(i);
    const done = bandMap && bandMap.has(key);
    const hasPage = Reader.regions.get(i) && !band;
    if (!done && !hasPage) await Reader.scanPage(i, {});
  }
  if (RULES.semiManual && State.semi) {
    if (State.waitingScroll) {
      // человек прокрутил — читаем то, что видно
      State.waitingScroll = false; hideArrow();
      await sleep(RULES.semiManualSettleMs);
      if (!Reader.scrollBusy) TTS.readVisible();
    }
  }
}
function turnPage(dir) {
  const next = clamp(Reader.page + dir, 0, Reader.pages.length - 1);
  if (Reader.mode === 'vertical') {
    const wrap = document.querySelector(`.pagewrap[data-page="${next}"]`);
    wrap?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } else {
    document.querySelectorAll('.pagebox').forEach(b => b.classList.toggle('on', +b.dataset.page === next));
    Reader.page = next; Reader.syncSub(); Reader.ensureLoaded(next); Reader.afterPageReady(); Reader.saveProgress();
  }
}
