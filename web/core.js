/*!
 * ownocr-web — движок распознавания манги в браузере.
 *
 * Это порт проверенной Python-версии (ownocr/page_det.py, det_tune.py,
 * text_clean.py, pair.py) на JavaScript. Всё считается на месте, в WASM:
 * никаких обращений к серверу, никаких «примеров, вписанных в код».
 *
 *   страница → детектор строк (koma_det.onnx)      → карта вероятностей
 *            → компоненты связности + расширение   → боксы облачков
 *            → резка бокса на строки по проекции   → рамки строк
 *            → дочистка рамок (weak/dupes)         → 41 рамка вместо 50
 *            → чтец строк (koma_rec.onnx, CTC)     → текст строки
 *            → чистка текста (крякозябры, цифры)   → реплика
 *            → порядок чтения манги (справа налево сверху вниз)
 *
 * Модуль не знает про DOM: на вход — пиксели, на выход — реплики. Поэтому
 * его можно прогнать в Node и сравнить с Python-эталоном.
 */
(function (root) {
  'use strict';

  // ── мелкая арифметика ────────────────────────────────────────────────────
  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);

  /** RGB (Uint8, 3 байта на пиксель) → яркость Y (Float32). */
  function luma(rgb, w, h) {
    const out = new Float32Array(w * h);
    for (let i = 0, p = 0; i < out.length; i++, p += 3) {
      out[i] = (299 * rgb[p] + 587 * rgb[p + 1] + 114 * rgb[p + 2]) / 1000;
    }
    return out;
  }

  /** Билинейное изменение размера RGB-канала (Uint8 → Uint8). */
  function resizeRGB(src, sw, sh, dw, dh) {
    const dst = new Uint8Array(dw * dh * 3);
    if (sw === dw && sh === dh) { dst.set(src); return dst; }
    const xs = new Float32Array(dw), ys = new Float32Array(dh);
    for (let x = 0; x < dw; x++) xs[x] = clamp((x + 0.5) * sw / dw - 0.5, 0, sw - 1);
    for (let y = 0; y < dh; y++) ys[y] = clamp((y + 0.5) * sh / dh - 0.5, 0, sh - 1);
    for (let y = 0; y < dh; y++) {
      const y0 = Math.floor(ys[y]), y1 = Math.min(sh - 1, y0 + 1), fy = ys[y] - y0;
      for (let x = 0; x < dw; x++) {
        const x0 = Math.floor(xs[x]), x1 = Math.min(sw - 1, x0 + 1), fx = xs[x] - x0;
        const i00 = (y0 * sw + x0) * 3, i10 = (y0 * sw + x1) * 3;
        const i01 = (y1 * sw + x0) * 3, i11 = (y1 * sw + x1) * 3;
        const o = (y * dw + x) * 3;
        for (let c = 0; c < 3; c++) {
          const a = src[i00 + c] + (src[i10 + c] - src[i00 + c]) * fx;
          const b = src[i01 + c] + (src[i11 + c] - src[i01 + c]) * fx;
          dst[o + c] = Math.round(a + (b - a) * fy);
        }
      }
    }
    return dst;
  }

  /** Билинейное изменение размера яркости (Float32). */
  function resizeLuma(src, sw, sh, dw, dh) {
    const dst = new Float32Array(dw * dh);
    if (sw === dw && sh === dh) { dst.set(src); return dst; }
    const xs = new Float32Array(dw), ys = new Float32Array(dh);
    for (let x = 0; x < dw; x++) xs[x] = clamp((x + 0.5) * sw / dw - 0.5, 0, sw - 1);
    for (let y = 0; y < dh; y++) ys[y] = clamp((y + 0.5) * sh / dh - 0.5, 0, sh - 1);
    for (let y = 0; y < dh; y++) {
      const y0 = Math.floor(ys[y]), y1 = Math.min(sh - 1, y0 + 1), fy = ys[y] - y0;
      for (let x = 0; x < dw; x++) {
        const x0 = Math.floor(xs[x]), x1 = Math.min(sw - 1, x0 + 1), fx = xs[x] - x0;
        const a = src[y0 * sw + x0] + (src[y0 * sw + x1] - src[y0 * sw + x0]) * fx;
        const b = src[y1 * sw + x0] + (src[y1 * sw + x1] - src[y1 * sw + x0]) * fx;
        dst[y * dw + x] = a + (b - a) * fy;
      }
    }
    return dst;
  }

  /** Кроп RGB как Float32-яркость: [x0,y0)-[x1,y1). */
  function cropLuma(rgb, w, x0, y0, x1, y1) {
    const cw = Math.max(0, x1 - x0), ch = Math.max(0, y1 - y0);
    const out = new Float32Array(cw * ch);
    for (let y = 0; y < ch; y++) {
      let p = ((y0 + y) * w + x0) * 3, o = y * cw;
      for (let x = 0; x < cw; x++, p += 3, o++) {
        out[o] = (299 * rgb[p] + 587 * rgb[p + 1] + 114 * rgb[p + 2]) / 1000;
      }
    }
    return out;
  }

  /** Привести страницу к виду «тёмное на светлом»: инверсия, если фон тёмный. */
  function normalizePage(rgb) {
    let dark = 0;
    const n = rgb.length / 3;
    for (let p = 0; p < rgb.length; p += 3) {
      if ((299 * rgb[p] + 587 * rgb[p + 1] + 114 * rgb[p + 2]) / 1000 < 128) dark++;
    }
    if (dark / n <= 0.55) return rgb;
    const out = new Uint8Array(rgb.length);
    for (let i = 0; i < rgb.length; i++) out[i] = 255 - rgb[i];
    return out;
  }

  // ── детектор ─────────────────────────────────────────────────────────────

  /** Связные области карты вероятностей (4 соседства) + отбраковка мелочи. */
  function components(prob, pw, ph, thr, minPix, minMean) {
    const seen = new Uint8Array(pw * ph);
    const boxes = [];
    const stack = new Int32Array(pw * ph);
    for (let sy = 0; sy < ph; sy++) {
      for (let sx = 0; sx < pw; sx++) {
        const s = sy * pw + sx;
        if (seen[s] || prob[s] < thr) continue;
        let top = 0;
        stack[top++] = s;
        seen[s] = 1;
        let minx = sx, maxx = sx, miny = sy, maxy = sy, n = 0, score = 0;
        while (top > 0) {
          const idx = stack[--top];
          const y = (idx / pw) | 0, x = idx - y * pw;
          n++; score += prob[idx];
          if (x < minx) minx = x;
          if (x > maxx) maxx = x;
          if (y < miny) miny = y;
          if (y > maxy) maxy = y;
          if (y > 0) { const j = idx - pw; if (!seen[j] && prob[j] >= thr) { seen[j] = 1; stack[top++] = j; } }
          if (y < ph - 1) { const j = idx + pw; if (!seen[j] && prob[j] >= thr) { seen[j] = 1; stack[top++] = j; } }
          if (x > 0) { const j = idx - 1; if (!seen[j] && prob[j] >= thr) { seen[j] = 1; stack[top++] = j; } }
          if (x < pw - 1) { const j = idx + 1; if (!seen[j] && prob[j] >= thr) { seen[j] = 1; stack[top++] = j; } }
        }
        if (n < minPix || score / n < minMean || maxx - minx < 2 || maxy - miny < 2) continue;
        const expand = Math.max(2, Math.round((maxx - minx) * (maxy - miny) * 1.5 /
          (2 * ((maxx - minx) + (maxy - miny)))));
        boxes.push([Math.max(0, minx - expand), Math.max(0, miny - expand),
          Math.min(pw, maxx + expand + 1), Math.min(ph, maxy + expand + 1)]);
      }
    }
    boxes.sort((a, b) => a[1] - b[1]);
    return boxes;
  }

  /** Один проход детектора по странице (одна плитка). */
  async function detectPage(det, rgb, w, h, opts) {
    const ratio = Math.min(1, 960 / Math.max(w, h));
    const dw = Math.max(32, Math.round(w * ratio / 32) * 32);
    const dh = Math.max(32, Math.round(h * ratio / 32) * 32);
    const scaled = resizeRGB(rgb, w, h, dw, dh);
    const x = new Float32Array(3 * dw * dh);
    const plane = dw * dh;
    for (let i = 0, p = 0, pp = 0; pp < plane; pp++, p += 3) {
      x[pp] = scaled[p] / 255;
      x[pp + plane] = scaled[p + 1] / 255;
      x[pp + plane * 2] = scaled[p + 2] / 255;
    }
    const tensor = new (opts.ort.Tensor)('float32', x, [1, 3, dh, dw]);
    const out = await det.run({ [det.inputNames[0]]: tensor });
    const prob = out[det.outputNames[0]].data;
    const pdims = out[det.outputNames[0]].dims;
    const pw = pdims[pdims.length - 1], ph = pdims[pdims.length - 2];
    const boxes = components(prob, pw, ph, opts.detThr, 6, 0.5);
    return boxes.map(([x1, y1, x2, y2]) => [
      Math.round(x1 / pw * w), Math.round(y1 / ph * h),
      Math.round(x2 / pw * w), Math.round(y2 / ph * h)]);
  }

  // ── резка бокса на строки ────────────────────────────────────────────────

  function textLines(rgb, w, h, box, opts) {
    const [bx1, by1, bx2, by2] = box;
    const pad = Math.max(2, Math.round((by2 - by1) * 0.12));
    const left = Math.max(0, bx1 - pad), right = Math.min(w, bx2 + pad);
    const top = Math.max(0, by1 - pad), bottom = Math.min(h, by2 + pad);
    if (right - left < 4 || bottom - top < 4) return [];
    const scale = Math.min(1, 400 / (right - left));
    const cw = Math.max(4, Math.round((right - left) * scale));
    const ch = Math.max(4, Math.round((bottom - top) * scale));
    const full = cropLuma(rgb, w, left, top, right, bottom);
    const small = resizeLuma(full, right - left, bottom - top, cw, ch);
    const inkThr = opts.inkLuma;
    const need = Math.max(1, Math.floor(cw / 60));
    const rowHasInk = (y) => {
      let c = 0;
      for (let x = 0; x < cw; x++) if (small[y * cw + x] < inkThr) c++;
      return c >= need;
    };
    const runs = [];
    for (let y = 0; y < ch;) {
      if (!rowHasInk(y)) { y++; continue; }
      let end = y;
      while (end < ch && rowHasInk(end)) end++;
      runs.push([y, end]);
      y = Math.max(end, y + 1);
    }
    if (!runs.length) return [[left, top, right, bottom]];
    const lens = runs.map((r) => r[1] - r[0]).sort((a, b) => a - b);
    const median = lens[Math.floor(lens.length / 2)];
    const merged = [];
    for (const run of runs) {
      if (merged.length && run[0] - merged[merged.length - 1][1] <= Math.max(1, Math.round(median * 0.35))) {
        merged[merged.length - 1][1] = run[1];
      } else merged.push([run[0], run[1]]);
    }
    const lines = [];
    for (const [a, b] of merged) {
      if (b - a < Math.max(2, Math.round(median * 0.4))) continue;
      let c0 = -1, c1 = -1;
      for (let x = 0; x < cw; x++) {
        let has = false;
        for (let y = a; y < b; y++) if (small[y * cw + x] < inkThr) { has = true; break; }
        if (has) { if (c0 < 0) c0 = x; c1 = x; }
      }
      if (c0 < 0) continue;
      const px0 = clamp(Math.round(left + c0 / scale), left, right - 1);
      const px1 = clamp(Math.round(left + (c1 + 1) / scale), px0 + 1, right);
      const py0 = clamp(Math.round(top + a / scale), top, bottom - 1);
      const py1 = clamp(Math.round(top + b / scale), py0 + 1, bottom);
      lines.push([px0, py0, px1, py1]);
    }
    return lines.length ? lines : [[left, top, right, bottom]];
  }

  // ── дочистка рамок (det_tune.py) ─────────────────────────────────────────

  function inkShare(rgb, w, x0, y0, x1, y1) {
    const cw = x1 - x0, ch = y1 - y0;
    if (cw <= 0 || ch <= 0) return 0;
    let ink = 0, total = cw * ch;
    for (let y = y0; y < y1; y++) {
      let p = (y * w + x0) * 3;
      for (let x = x0; x < x1; x++, p += 3) {
        if ((299 * rgb[p] + 587 * rgb[p + 1] + 114 * rgb[p + 2]) / 1000 < 140) ink++;
      }
    }
    return ink / total;
  }

  /** Слабые рамки (почти пусто или залито) и дубли (рамка внутри рамки). */
  function tuneLines(rgb, w, lines, opts) {
    const weak = [];
    for (const l of lines) {
      const ink = inkShare(rgb, w, l[0], l[1], l[2], l[3]);
      if (ink < opts.minInk || ink > opts.maxInk) continue;
      weak.push(l);
    }
    const sorted = weak.slice().sort((a, b) =>
      ((b[2] - b[0]) * (b[3] - b[1])) - ((a[2] - a[0]) * (a[3] - a[1])));
    const out = [];
    for (const l of sorted) {
      const area = (l[2] - l[0]) * (l[3] - l[1]);
      let inside = false;
      for (const k of out) {
        const ox = Math.min(l[2], k[2]) - Math.max(l[0], k[0]);
        const oy = Math.min(l[3], k[3]) - Math.max(l[1], k[1]);
        if (ox > 0 && oy > 0 && (ox * oy) / area >= opts.dupShare) { inside = true; break; }
      }
      if (!inside) out.push(l);
    }
    return out;
  }

  /**
   * Строка из интерфейса читалки, а не со страницы.
   *
   * На скриншотах (dense-b) сверху висит полоса приложения: «4 из 17 · Манга ·
   * Справа налево». Геометрически это обычная строка, и она попадала в реплики
   * первой. Признак, который отличает её от текста манги: она светлая на тёмной
   * плашке, а плашка тянется до края страницы. Настоящие надписи на чёрных
   * плашках манги в верхнюю полосу 10 % не попадают и под правило не идут.
   */
  function isUiBand(rgb, w, h, box, opts) {
    if (!opts.uiBandTop) return false;
    const [x0, y0, x1, y1] = box;
    if (y1 > h * opts.uiBandTop) return false;
    // фон вокруг рамки: тёмный?
    let dark = 0, total = 0;
    const ring = 6;
    for (let y = Math.max(0, y0 - ring); y < Math.min(h, y1 + ring); y++) {
      for (let x = Math.max(0, x0 - ring); x < Math.min(w, x1 + ring); x++) {
        if (x >= x0 && x < x1 && y >= y0 && y < y1) continue;
        const p = (y * w + x) * 3;
        if ((299 * rgb[p] + 587 * rgb[p + 1] + 114 * rgb[p + 2]) / 1000 < 110) dark++;
        total++;
      }
    }
    if (!total || dark / total < 0.8) return false;
    // текст внутри рамки: светлый?
    let bright = 0, n = 0;
    for (let y = y0; y < y1; y++) {
      for (let x = x0; x < x1; x++, n++) {
        const p = (y * w + x) * 3;
        if ((299 * rgb[p] + 587 * rgb[p + 1] + 114 * rgb[p + 2]) / 1000 > 95) bright++;
      }
    }
    return n > 0 && bright / n > 0.1;
  }

  function cropOk(rgb, w, box, opts) {
    const [x0, y0, x1, y1] = box;
    const cw = x1 - x0, ch = y1 - y0;
    if (cw < 4 || ch < opts.minCropH) return false;
    if (cw / ch > 20) return false;
    const ink = inkShare(rgb, w, x0, y0, x1, y1);
    return ink >= 0.01 && ink <= 0.92;
  }

  // ── чтец строк (koma_rec.onnx, CTC) ──────────────────────────────────────

  /**
   * Прочитать строку. Вход сети — 3×48×W, W считается из пропорций строки
   * (8…960), полотно не уже 320 px, поля заливаются серым 128.
   */
  async function readLine(rec, dict, rgb, w, box, opts) {
    let [x0, y0, x1, y1] = box;
    let cw = x1 - x0, ch = y1 - y0;
    const crop = new Uint8Array(cw * ch * 3);
    for (let y = 0; y < ch; y++) {
      let p = ((y0 + y) * w + x0) * 3, o = y * cw * 3;
      for (let x = 0; x < cw; x++, p += 3, o += 3) {
        crop[o] = rgb[p]; crop[o + 1] = rgb[p + 1]; crop[o + 2] = rgb[p + 2];
      }
    }
    // вертикальная надпись (внутри плоского бокса) — повернуть
    if (ch > cw * 1.8) {
      const rot = new Uint8Array(cw * ch * 3);
      for (let y = 0; y < ch; y++) {
        for (let x = 0; x < cw; x++) {
          const src = (y * cw + x) * 3;
          const nx = ch - 1 - y, ny = x;                     // np.rot90(k=-1)
          const dst = (ny * ch + nx) * 3;
          rot[dst] = crop[src]; rot[dst + 1] = crop[src + 1]; rot[dst + 2] = crop[src + 2];
        }
      }
      const t = cw; cw = ch; ch = t;
      return readBest(rec, dict, rot, cw, ch, opts, opts.vocab);
    }
    return readBest(rec, dict, crop, cw, ch, opts, opts.vocab);
  }

  /** Растянуть контраст: 2-й проход видит тонкие штрихи, которые теряются. */
  function autocontrast(crop, cw, ch) {
    const n = cw * ch;
    const hist = new Uint32Array(256);
    for (let i = 0, p = 0; i < n; i++, p += 3) {
      hist[(299 * crop[p] + 587 * crop[p + 1] + 114 * crop[p + 2]) / 1000 | 0]++;
    }
    let lo = 0, hi = 255, acc = 0;
    for (let v = 0; v < 256; v++) { acc += hist[v]; if (acc >= n * 0.02) { lo = v; break; } }
    acc = 0;
    for (let v = 255; v >= 0; v--) { acc += hist[v]; if (acc >= n * 0.02) { hi = v; break; } }
    if (hi - lo < 24) return crop;
    const lut = new Uint8Array(256);
    for (let v = 0; v < 256; v++) lut[v] = clamp(Math.round((v - lo) * 255 / (hi - lo)), 0, 255);
    const out = new Uint8Array(n * 3);
    for (let p = 0; p < n * 3; p++) out[p] = lut[crop[p]];
    return out;
  }

  /** Читаем строку дважды (как есть и с растянутым контрастом) и выбираем
   *  прочтение по числу словарных слов. Ошибки проходов разные: на одном теряется
   *  перекладина «Д», на другом пересвечивается тонкий штрих. */
  async function readBest(rec, dict, crop, cw, ch, opts, vocab) {
    // Один и тот же кроп чтец читает по-разному в зависимости от того, насколько
    // растянута строка: ошибки проходов не совпадают, и «правильное» прочтение
    // обычно то, где больше словарных слов. Поэтому читаем несколько вариантов.
    const variants = [crop];
    if (opts.twoPass) variants.push(autocontrast(crop, cw, ch));
    if (opts.stretch) {
      variants.push(resizeRGB(crop, cw, ch, Math.max(4, Math.round(cw * 0.85)), ch));
      variants.push(resizeRGB(crop, cw, ch, Math.round(cw * 1.15), ch));
    }
    let best = null, bestScore = -1e9;
    for (let i = 0; i < variants.length; i++) {
      const w = i >= 2 ? Math.round(cw * (i === 2 ? 0.85 : 1.15)) : cw;
      const r = await readFlat(rec, dict, variants[i], w, ch, opts);
      const score = scoreRead(r.text, vocab) + r.conf * (opts.stretchWeight || 0.6);
      if (score > bestScore) { bestScore = score; best = r; }
    }
    return best;
  }

  function scoreRead(text, vocab) {
    let score = 0;
    for (const raw of (text || '').split(/\s+/)) {
      const w = raw.replace(/^[.,!?…—«»"():;%]+|[.,!?…—«»"():;%]+$/g, '').toUpperCase();
      if (Array.from(w).length < 2) continue;
      if (vocab && vocab.has(w)) score += 3;
      else if (Array.from(w).filter((c) => VOWELS.has(c)).length >= 2) score += 1;
      else score -= 2;
    }
    return score;
  }

  async function readFlat(rec, dict, crop, cw, ch, opts) {
    const width = clamp(Math.round(48 * cw / ch), 8, 960);
    const canvasW = Math.max(320, width);
    const resized = resizeRGB(crop, cw, ch, width, 48);
    const x = new Float32Array(3 * 48 * canvasW).fill(0.00392156862745098); // 128 → (128/255-0.5)/0.5
    // заполняем серым 128 в нормализованном виде
    const grey = (128 / 255 - 0.5) / 0.5;
    x.fill(grey);
    const plane = 48 * canvasW;
    for (let yy = 0; yy < 48; yy++) {
      for (let xx = 0; xx < width; xx++) {
        const s = (yy * width + xx) * 3;
        const d = yy * canvasW + xx;
        x[d] = (resized[s] / 255 - 0.5) / 0.5;
        x[plane + d] = (resized[s + 1] / 255 - 0.5) / 0.5;
        x[plane * 2 + d] = (resized[s + 2] / 255 - 0.5) / 0.5;
      }
    }
    const tensor = new (opts.ort.Tensor)('float32', x, [1, 3, 48, canvasW]);
    const out = await rec.run({ [rec.inputNames[0]]: tensor });
    const data = out[rec.outputNames[0]].data;
    const dims = out[rec.outputNames[0]].dims;
    const steps = dims[dims.length - 2], classes = dims[dims.length - 1];
    const chars = [];
    let score = 0, count = 0, prev = 0;
    for (let t = 0; t < steps; t++) {
      const base = t * classes;
      let best = 0, bestV = data[base];
      for (let c = 1; c < classes; c++) {
        const v = data[base + c];
        if (v > bestV) { bestV = v; best = c; }
      }
      if (best !== 0 && best !== prev) {
        chars.push(dict[best] !== undefined ? dict[best] : '');
        score += bestV; count++;
      }
      prev = best;
    }
    return { text: chars.join(''), conf: count ? score / count : 0 };
  }

  /**
   * Второй чтец — «эслав» (CTC, вход 1×1×32×W, 109 букв, «пусто» = класс 109).
   * Дообучен на нашем домене, ошибки у него другие: где чтец приложения рвёт
   * слово, эслав часто видит его целиком. Голосование — по словам.
   */
  async function readEslav(rec, charset, rgb, w, box, opts) {
    const [x0, y0, x1, y1] = box;
    const cw = x1 - x0, ch = y1 - y0;
    if (cw < 4 || ch < 4) return { text: '', conf: 0 };
    const g = new Float32Array(cw * ch);
    for (let y = 0; y < ch; y++) {
      let p = ((y0 + y) * w + x0) * 3;
      for (let x = 0; x < cw; x++, p += 3) {
        g[y * cw + x] = (299 * rgb[p] + 587 * rgb[p + 1] + 114 * rgb[p + 2]) / 1000;
      }
    }
    const H = 32;
    const ww = Math.max(8, Math.round(cw * H / ch));
    const xs = new Float32Array(ww), ys = new Float32Array(H);
    for (let x = 0; x < ww; x++) xs[x] = clamp((x + 0.5) * cw / ww - 0.5, 0, cw - 1);
    for (let y = 0; y < H; y++) ys[y] = clamp((y + 0.5) * ch / H - 0.5, 0, ch - 1);
    const t = new Float32Array(H * ww);
    for (let y = 0; y < H; y++) {
      const y0i = Math.floor(ys[y]), y1i = Math.min(ch - 1, y0i + 1), fy = ys[y] - y0i;
      for (let x = 0; x < ww; x++) {
        const x0i = Math.floor(xs[x]), x1i = Math.min(cw - 1, x0i + 1), fx = xs[x] - x0i;
        const a = g[y0i * cw + x0i] + (g[y0i * cw + x1i] - g[y0i * cw + x0i]) * fx;
        const b = g[y1i * cw + x0i] + (g[y1i * cw + x1i] - g[y1i * cw + x0i]) * fx;
        // нормировка /127.5-1 — та, на которой модель учили и на которой она
        // даёт 8 % на строках (на /255 выходит хуже: 10,6 % против 2,7 %)
        t[y * ww + x] = (a + (b - a) * fy) / 127.5 - 1;
      }
    }
    const out = await rec.run({ [rec.inputNames[0]]: new (opts.ort.Tensor)('float32', t, [1, 1, H, ww]) });
    const data = out[rec.outputNames[0]].data;
    const dims = out[rec.outputNames[0]].dims;
    const T = dims[0], C = dims[dims.length - 1];
    let text = '', prev = -1, score = 0, count = 0;
    for (let i = 0; i < T; i++) {
      let best = 0, bestV = data[i * C];
      for (let c = 1; c < C; c++) {
        const v = data[i * C + c];
        if (v > bestV) { bestV = v; best = c; }
      }
      if (best !== prev && best !== 109 && best < charset.length) text += charset[best];
      if (best !== 109 && best !== prev) { score += bestV; count++; }
      prev = best;
    }
    return { text, conf: count ? score / count : 0 };
  }

  /**
   * Чужой чтец PP-OCR (PaddleOCR, кириллица): вход 3×48×W, каналы BGR,
   * нормировка /255−0,5, CTC с «пусто» = класс 0, словарь с 1-го класса.
   * Другой производитель и другое обучение — значит и ошибки другие.
   */
  async function readPP(rec, chars, rgb, w, box, opts) {
    const [x0, y0, x1, y1] = box;
    const cw = x1 - x0, ch = y1 - y0;
    if (cw < 4 || ch < 7) return { text: '', conf: 0 };
    const crop = new Uint8Array(cw * ch * 3);
    for (let y = 0; y < ch; y++) {
      let p = ((y0 + y) * w + x0) * 3, o = y * cw * 3;
      for (let x = 0; x < cw; x++, p += 3, o += 3) {
        crop[o] = rgb[p]; crop[o + 1] = rgb[p + 1]; crop[o + 2] = rgb[p + 2];
      }
    }
    const tw = clamp(Math.round(48 * cw / ch), 8, 3200);
    const resized = resizeRGB(crop, cw, ch, tw, 48);
    const plane = 48 * tw;
    const x = new Float32Array(3 * plane);
    for (let yy = 0; yy < 48; yy++) {
      for (let xx = 0; xx < tw; xx++) {
        const s = (yy * tw + xx) * 3, d = yy * tw + xx;
        x[d] = (resized[s + 2] / 255 - 0.5) / 0.5;
        x[plane + d] = (resized[s + 1] / 255 - 0.5) / 0.5;
        x[plane * 2 + d] = (resized[s] / 255 - 0.5) / 0.5;
      }
    }
    const out = await rec.run({ [rec.inputNames[0]]: new (opts.ort.Tensor)('float32', x, [1, 3, 48, tw]) });
    const data = out[rec.outputNames[0]].data;
    const dims = out[rec.outputNames[0]].dims;
    const T = dims[dims.length - 2], C = dims[dims.length - 1];
    let text = '', prev = -1;
    for (let i = 0; i < T; i++) {
      let best = 0, bestV = data[i * C];
      for (let c = 1; c < C; c++) {
        const v = data[i * C + c];
        if (v > bestV) { bestV = v; best = c; }
      }
      if (best !== prev && best !== 0) {
        const j = best - 1;
        if (j < chars.length) text += chars[j];
      }
      prev = best;
    }
    return { text, conf: 0 };
  }

  /**
   * Голосование двух чтецов — только «в плюс».
   *
   * Замер на трёх страницах показал, что простое большинство слов вредит: эслав
   * иногда портит слово, которое чтец приложения прочитал верно, и реплика
   * становится хуже («Я РАССЧИТ ЫПОНМТ НА ВАС»). Поэтому правило строгое: слово
   * эслава берём ТОЛЬКО если у приложения это слово не словарное, а у эслава —
   * словарное. В остальных случаях остаётся прочтение приложения. Такой постфиксер
   * может улучшить, но не может испортить.
   */
  // Голосование «в плюс» сравнивает слова ПО МЕСТАМ и требует равного числа
  // слов: если чтецы разбили строку по-разному (а это правило, а не редкость),
  // оно возвращает текст своего чтеца и второй голос пропадает целиком.
  // Замер на настоящей странице kuro-p1: старый и новый эслав давали
  // ОДИНАКОВЫЙ результат 51,1 %. Поэтому выбираем прочтение целиком — по числу
  // слов, найденных в словаре (длинные слова весят больше).
  function pickBetter(a, b, vocab) {
    if (!b) return a;
    if (!a) return b;
    const score = (t) => {
      let s = 0;
      for (const w of t.split(/\s+/)) {
        const k = fixChars(w).replace(/^[.,!?…—«»"():;%]+|[.,!?…—«»"():;%]+$/g, '').toUpperCase();
        if (k.length >= 3 && vocab && vocab.has(k)) s += k.length;
      }
      return s;
    };
    return score(b) > score(a) ? b : a;
  }

  function voteText(a, b, vocab) {
    if (!b || !a) return a || b;
    const wa = a.split(/\s+/).filter(Boolean), wb = b.split(/\s+/).filter(Boolean);
    if (wa.length !== wb.length) return a;              // разное число слов — не трогаем
    // похожие буквы (Δ→Д, латиница→кириллица) приводим ДО проверки по словарю:
    // иначе «ΔА» не находится в словаре, и его подменяет чужое «ДО»
    const key = (w) => fixChars(w).replace(/^[.,!?…—«»"():;%]+|[.,!?…—«»"():;%]+$/g, '').toUpperCase();
    let changed = 0;
    const out = wa.map((w, i) => {
      const ka = key(w), kb = key(wb[i]);
      if (!vocab.has(ka) && vocab.has(kb)) { changed++; return wb[i]; }
      return w;
    }).join(' ');
    return changed ? out : a;
  }

  // ── чистка текста (text_clean.py) ────────────────────────────────────────

  const LOOKALIKE = {
    'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'K': 'К', 'M': 'М',
    'O': 'О', 'P': 'Р', 'T': 'Т', 'X': 'Х', 'Y': 'У',
    'a': 'а', 'c': 'с', 'e': 'е', 'o': 'о', 'p': 'р', 'x': 'х', 'y': 'у',
    'k': 'к', 'm': 'м', 't': 'т', 'h': 'н', 'b': 'ь',
    'Λ': 'Л', 'Ο': 'О', 'Α': 'А', 'Ε': 'Е', 'Ρ': 'Р', 'Τ': 'Т', 'Κ': 'К',
    'Μ': 'М', 'Η': 'Н', 'Χ': 'Х', 'Ι': 'И', 'Ν': 'Н', 'Ζ': 'З', 'Υ': 'У',
    // Δ — это «Д», Β — «В»: чтец отдаёт их, когда пропадает перекладина
    'Δ': 'Д', 'Β': 'В', 'Ξ': 'Ж', 'Ζ': 'З',
    'і': 'и', 'ї': 'и', 'є': 'е', 'ґ': 'г', 'І': 'И', 'Ї': 'И', 'Є': 'Е', 'Ґ': 'Г'
  };
  const DIGIT_LOOKALIKE = { '3': 'З', '0': 'О', '4': 'Ч', '6': 'Б' };
  const VOWELS = new Set('АЕЁИОУЫЭЮЯ'.split(''));
  const CONSONANTS = new Set('БВГДЖЗЙКЛМНПРСТФХЦЧШЩЬЪ'.split(''));
  const LATIN_ONLY = new Set('BDEFGIJLNQRSUVWZ'.split(''));
  const EDGE = '.,!?…—«»"():;%';
  const JUNK_IN_WORD = '%"\'«»()[]{}|/\\+=~^*№';

  const fixChars = (s) => Array.from(s).map((c) => LOOKALIKE[c] || c).join('');

  function fixDigits(word) {
    if (!/[0-9]/.test(word) || !/\p{L}/u.test(word)) return word;
    return Array.from(word).map((c) => DIGIT_LOOKALIKE[c] || c).join('');
  }

  function wordOk(word, vocab) {
    let core = word.replace(new RegExp('^[' + '.,!?…—«»"():;%' + ']+|[' + '.,!?…—«»"():;%' + ']+$', 'g'), '');
    if (!core) return [false, ''];
    core = fixDigits(core);
    const letters = Array.from(core).filter((c) => /\p{L}/u.test(c));
    const digits = Array.from(core).filter((c) => /[0-9]/.test(c));
    if (!letters.length && !digits.length) return [false, ''];
    if (digits.length && !letters.length) return [true, core];
    const mixed = letters.length > 0 && digits.length > 0;
    let upper = core.toUpperCase();
    const hasVowel = Array.from(upper).some((c) => VOWELS.has(c));
    let doubled = false;
    for (let i = 0; i + 1 < upper.length; i++) {
      if (upper[i] === upper[i + 1] && 'ЁЪЬЙ'.includes(upper[i])) doubled = true;
    }
    const junkShare = Array.from(core).filter((c) => !/\p{L}/u.test(c) && !/[0-9]/.test(c)).length / Array.from(core).length;
    if (mixed && letters.length >= 2) return [false, ''];
    if (junkShare > 0.34) return [false, ''];
    if (!hasVowel && Array.from(core).length >= 3) return [false, ''];
    if (doubled) return [false, ''];
    if (Array.from(core).some((c) => LATIN_ONLY.has(c))) return [false, ''];
    if (!(core === upper || core === core.toLowerCase() ||
      (core[0] === upper[0] && core.slice(1) === core.slice(1).toLowerCase()))) {
      const up = Array.from(core).filter((c) => /\p{L}/u.test(c) && c === c.toUpperCase() && c !== c.toLowerCase()).length;
      const all = Array.from(core).filter((c) => /\p{L}/u.test(c)).length;
      core = (up / Math.max(1, all) >= 0.6) ? core.toUpperCase() : core.toLowerCase();
      upper = core.toUpperCase();
    }
    for (let i = 0; i + 1 < upper.length; i++) {
      if (upper[i] === upper[i + 1] && VOWELS.has(upper[i])) return [false, ''];
    }
    let run = 0;
    for (const c of upper) {
      run = CONSONANTS.has(c) ? run + 1 : 0;
      if (run >= 5) return [false, ''];
    }
    const nV = Array.from(upper).filter((c) => VOWELS.has(c)).length;
    const nC = Array.from(upper).filter((c) => CONSONANTS.has(c)).length;
    if (Array.from(core).length >= 4 && nV <= 1 && nC >= 3) {
      return (vocab && vocab.has(upper)) ? [true, core] : [false, ''];
    }
    return [true, core];
  }

  // Пары, которые чтец путает на манге: «ЗТО» вместо «ЭТО», «ДУХМ» вместо «ДУХИ».
  const CONFUSABLE = {
    'З': 'Э', 'Э': 'З', 'И': 'Й', 'Й': 'И', 'Ш': 'Щ', 'Щ': 'Ш', 'Ь': 'Ъ', 'Ъ': 'Ь',
    'О': 'А', 'А': 'О', 'Е': 'И', 'И': 'Е', 'У': 'И', 'Ц': 'Ч', 'Ч': 'Ц', 'Г': 'Т',
    'Н': 'М', 'М': 'Н', 'Б': 'В', 'В': 'Б', 'Л': 'И', 'К': 'Х', 'Х': 'К', 'С': 'О'
  };

  /** Починить слово по словарю: одна замена похожей буквы или одна вставка. */
  function spellFix(word, vocab) {
    if (!vocab || !vocab.size) return word;
    const letters = Array.from(word);
    if (letters.length < 3) return word;
    const upper = word.toUpperCase();
    if (vocab.has(upper)) return word;
    for (let i = 0; i < letters.length; i++) {
      const pair = CONFUSABLE[letters[i].toUpperCase()];
      if (!pair) continue;
      const cand = letters.slice(0, i).concat([pair], letters.slice(i + 1)).join('');
      if (vocab.has(cand.toUpperCase())) return cand;
    }
    // пропущенная буква: вставить любую из гласных на месте провала
    for (let i = 1; i < letters.length; i++) {
      for (const v of 'ОЕИАУЯ') {
        const cand = (letters.slice(0, i).join('') + v + letters.slice(i).join(''));
        if (vocab.has(cand.toUpperCase())) return cand;
      }
    }
    return word;
  }

  /** Убрать крякозябры. Пустая строка — нормальный ответ. */
  function dejunk(text, vocab) {
    if (!text) return '';
    const fixed = fixChars(text);
    const out = [];
    for (const word of fixed.split(/\s+/)) {
      if (!word) continue;
      const [ok, core0] = wordOk(word, vocab);
      if (!ok || !core0) continue;
      const core = vocab && vocab.size ? spellFix(core0, vocab) : core0;
      const lead = word.slice(0, word.length - word.replace(/^[.,!?…—«»"():;%]+/, '').length);
      const trail = word.slice(word.replace(/[.,!?…—«»"():;%]+$/, '').length);
      out.push(lead + core + trail);
    }
    let line = out.join(' ');
    line = line.replace(/\s+([,.!?…])/g, '$1');
    line = line.replace(/([,.!?…]){2,}/g, '$1');
    line = line.replace(/^[.,!?…-]+/, '');
    return line.trim();
  }

  function plausible(line, vocab) {
    for (const raw of line.split(/\s+/)) {
      const w = raw.replace(/^[.,!?…—«»"():;%]+|[.,!?…—«»"():;%]+$/g, '');
      if (Array.from(w).length < 2) continue;
      const up = w.toUpperCase();
      if (vocab && vocab.has(up)) return true;
      const vowels = Array.from(up).filter((c) => VOWELS.has(c)).length;
      if (Array.from(w).length >= 3 && vowels >= 2) return true;
    }
    return false;
  }

  // ── порядок чтения (page_det.py: split_panels/bubbles_of) ────────────────

  const SHIFT = 0.8;

  function mergeByAxis(group, byY, cut) {
    const key = (r) => (byY ? r.top : r.left);
    const end = (r) => (byY ? r.bottom : r.right);
    const bands = [];
    for (const r of group.slice().sort((a, b) => key(a) - key(b))) {
      const s = key(r), e = end(r);
      if (bands.length && s - bands[bands.length - 1][1] <= cut) {
        bands[bands.length - 1][1] = Math.max(bands[bands.length - 1][1], e);
        bands[bands.length - 1][2].push(r);
      } else bands.push([s, e, [r]]);
    }
    return bands.length > 1 ? bands.map((b) => b[2]) : [group];
  }

  function splitPanels(group, rtl, depth) {
    depth = depth || 0;
    if (group.length <= 1 || depth > 12) return [group];
    const hs = group.map((r) => r.bottom - r.top).sort((a, b) => a - b);
    const lh = Math.max(0.008, hs[Math.floor(hs.length / 2)]);
    const yCut = Math.max(0.022, lh * 0.9), xCut = Math.max(0.035, lh * 0.9);
    const rows = mergeByAxis(group, true, yCut);
    if (rows.length > 1) return rows.flatMap((p) => splitPanels(p, rtl, depth + 1));
    let cols = mergeByAxis(group, false, xCut);
    if (cols.length > 1) {
      if (rtl) cols = cols.slice().reverse();
      return cols.flatMap((p) => splitPanels(p, rtl, depth + 1));
    }
    return [group];
  }

  function sameBubble(a, b) {
    const aw = a.right - a.left, bw = b.right - b.left;
    const ah = a.bottom - a.top, bh = b.bottom - b.top;
    if (Math.min(aw, bw) <= 0 || Math.min(ah, bh) <= 0) return false;
    const ov = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    if (ov <= 0 || ov / Math.min(aw, bw) < 0.30) return false;
    if (Math.abs((a.left + a.right) / 2 - (b.left + b.right) / 2) > Math.max(aw, bw) * SHIFT) return false;
    const gap = b.top - a.bottom;
    if (gap < -ah * 0.6 || gap > Math.max(ah, bh) * 1.2) return false;
    return !(ah > aw * 3 || bh > bw * 3);
  }

  function joinText(a, b) {
    a = a.trim(); b = b.trim();
    if (!a) return b;
    if (!b) return a;
    if (/[-‐‑–—]$/.test(a)) return a.slice(0, -1) + b;
    return a + ' ' + b;
  }

  function bubblesOf(group, rtl, blockGap) {
    blockGap = blockGap === undefined ? 1.6 : blockGap;
    const blocks = [];
    for (const region of group.slice().sort((a, b) => (a.top - b.top) || (a.left - b.left))) {
      let target = null, bestGap = Infinity;
      for (const block of blocks) {
        const head = block[block.length - 1];
        const lh = Math.max(head.bottom - head.top, 0.01);
        if (Math.min(head.bottom, region.bottom) - Math.max(head.top, region.top) <= lh * 0.35) continue;
        const bl = Math.min(...block.map((b) => b.left)), br = Math.max(...block.map((b) => b.right));
        let gap;
        if (region.left > br) gap = region.left - br;
        else if (region.right < bl) gap = region.right - bl;
        else gap = 0;
        if (gap > lh * blockGap || gap < -lh * 0.9) continue;
        if (gap < bestGap) { bestGap = gap; target = block; }
      }
      if (target) target.push(region); else blocks.push([region]);
    }

    const lines = [];
    for (const block of blocks) {
      const rows = [];
      for (const r of block.slice().sort((a, b) => a.top - b.top)) {
        const lh = Math.max(r.bottom - r.top, 0.01);
        let placed = false;
        for (const row of rows) {
          const head = row[0];
          if (Math.min(head.bottom, r.bottom) - Math.max(head.top, r.top) > lh * 0.5) {
            row.push(r); placed = true; break;
          }
        }
        if (!placed) rows.push([r]);
      }
      const ordered = [];
      for (const row of rows) {
        row.sort((a, b) => (rtl ? b.left - a.left : a.left - b.left));
        ordered.push(...row);
      }
      let text = '';
      ordered.forEach((part, i) => {
        if (i) {
          const prev = ordered[i - 1].text;
          if (/[-­]$/.test(text)) text = text.slice(0, -1);
          else if (!(Array.from(part.text).length <= 2 && /\p{L}/u.test(prev.slice(-1)) && /\p{L}/u.test(part.text[0] || ''))) text += ' ';
        }
        text += part.text;
      });
      lines.push({
        text,
        left: Math.min(...ordered.map((p) => p.left)),
        top: Math.min(...ordered.map((p) => p.top)),
        right: Math.max(...ordered.map((p) => p.right)),
        bottom: Math.max(...ordered.map((p) => p.bottom))
      });
    }

    const result = [];
    for (const line of lines.slice().sort((a, b) => (a.top - b.top) || (a.left - b.left))) {
      let target = -1, bestGap = Infinity;
      result.forEach((bubble, index) => {
        if (!sameBubble(bubble, line)) return;
        const gap = line.top - bubble.bottom;
        if (gap < bestGap) { bestGap = gap; target = index; }
      });
      if (target >= 0) {
        const bubble = result[target];
        result[target] = {
          text: joinText(bubble.text, line.text),
          left: Math.min(bubble.left, line.left), top: Math.min(bubble.top, line.top),
          right: Math.max(bubble.right, line.right), bottom: Math.max(bubble.bottom, line.bottom)
        };
      } else result.push(line);
    }

    const ordered2 = result.slice().sort((a, b) => (a.top - b.top) || (a.left - b.left));
    const bands = [];
    for (const line of ordered2) {
      if (bands.length) {
        const band = bands[bands.length - 1];
        const maxBottom = Math.max(...band.map((b) => b.bottom));
        if (line.top - maxBottom < -0.25 * (line.bottom - line.top)) { band.push(line); continue; }
      }
      bands.push([line]);
    }
    const out = [];
    for (const band of bands) {
      band.sort((a, b) => (rtl ? (b.left - a.left) : (a.left - b.left)) || (a.top - b.top));
      out.push(...band);
    }
    return out;
  }

  function readingOrder(regions, rtl, blockGap) {
    const src = regions.filter((r) => Array.from(r.text).filter((c) => /[\p{L}\p{N}]/u.test(c)).length >= 2);
    const out = [];
    for (const panel of splitPanels(src, rtl)) out.push(...bubblesOf(panel, rtl, blockGap));
    return out;
  }

  // ── вся страница ─────────────────────────────────────────────────────────

  const DEFAULTS = {
    detThr: 0.3, inkLuma: 150, minInk: 0.025, maxInk: 0.92, dupShare: 0.7,
    minCropH: 7, minConf: 0.2, rtl: true, maxBoxes: 400, readConcurrency: 2,
    blockGap: 0.6, softAccept: true, twoPass: false, stretch: false, stretchWeight: 0.6,
    uiBandTop: 0.10, secondReader: true, thirdReader: false, pickSecond: false,
    genre: 'manga'
  };

  /**
   * Прогнать страницу целиком.
   * @param {{det:any, rec:any, dict:string[], vocab:Set<string>, ort:any}} env
   * @param {Uint8Array} pixels RGB, 3 байта на пиксель
   */
  async function runPage(env, pixels, width, height, options) {
    const opts = Object.assign({}, DEFAULTS, options || {});
    opts.ort = env.ort;
    opts.vocab = env.vocab;
    const t0 = now();
    let rgb = normalizePage(pixels);
    const tNorm = now() - t0;

    const tDet = now();
    const boxes = await detectPage(env.det, rgb, width, height, opts);
    const detMs = now() - tDet;

    let lines = [];
    for (const box of boxes.slice(0, opts.maxBoxes)) lines.push(...textLines(rgb, width, height, box, opts));
    const nLinesRaw = lines.length;
    lines = tuneLines(rgb, width, lines, opts);

    const regions = [];
    const dropped = { crop: 0, empty: 0, ui: 0 };
    const tRead = now();
    for (let i = 0; i < lines.length; i += opts.readConcurrency) {
      const chunk = lines.slice(i, i + opts.readConcurrency);
      const got = await Promise.all(chunk.map(async (box) => {
        if (isUiBand(rgb, width, height, box, opts)) { dropped.ui++; return null; }
        if (!cropOk(rgb, width, box, opts)) return null;
        const r = await readLine(env.rec, env.dict, rgb, width, box, opts);
        let text = r.text, conf = r.conf;
        // Жанр решает, КАКОЙ второй чтец смотреть. Замер на 174 настоящих
        // строках: наш чтец, дообученный на манге, даёт на манге 1,1 %, а на
        // вебтуне 29,8 %; чтец, обученный на вебтуне (манхва+маньхуа) — 0,2 %
        // на манхве и 1,9 % на маньхуа. Один чтец на всё — это 8–14 %.
        const eslavModel = (opts.genre === 'webtoon' && env.eslavWebtoon)
          ? env.eslavWebtoon : env.eslav;
        if (eslavModel && env.charset && opts.secondReader) {
          const e = await readEslav(eslavModel, env.charset, rgb, width, box, opts);
          if (e.text) text = opts.pickSecond ? pickBetter(text, e.text, env.vocab) : voteText(text, e.text, env.vocab);
        }
        if (env.pp && env.ppChars && opts.thirdReader) {
          const p = await readPP(env.pp, env.ppChars, rgb, width, box, opts);
          if (p.text) text = voteText(text, p.text, env.vocab);
        }
        return { box, text, conf };
      }));
      for (const g of got) {
        if (!g) { dropped.crop++; continue; }
        // Строку НЕ чистим по одной: чистка и отбраковка мусора делаются на
        // уровне готовой реплики (как в Python-версии). Иначе выброшенная
        // «мусорная» строка рвёт облачко на обрывки: «Я РАССЧИ-» и «НА ВАС,»
        // остаются двумя репликами вместо одной.
        const raw = fixChars(g.text).trim();
        const alnum = Array.from(raw).filter((c) => /[\p{L}\p{N}]/u.test(c)).length;
        if (!raw || g.conf < opts.minConf || alnum < 2) { dropped.empty++; continue; }
        regions.push({
          text: raw,
          left: g.box[0] / width, top: g.box[1] / height,
          right: g.box[2] / width, bottom: g.box[3] / height,
          score: g.conf
        });
      }
    }
    const readMs = now() - tRead;

    const replies = [];
    let junk = 0;
    for (const line of readingOrder(regions, opts.rtl, opts.blockGap)) {
      const text = dejunk(line.text, env.vocab);
      if (!text || !plausible(text, env.vocab)) { junk++; continue; }
      replies.push({
        text,
        box: [line.left * width, line.top * height, line.right * width, line.bottom * height]
      });
    }

    return {
      replies,
      regions,
      stats: {
        boxes: boxes.length, linesRaw: nLinesRaw, linesTuned: lines.length,
        droppedCrop: dropped.crop, droppedEmpty: dropped.empty, droppedUi: dropped.ui, junk,
        msDetect: Math.round(detMs), msRead: Math.round(readMs),
        msTotal: Math.round(now() - t0), msNormalize: Math.round(tNorm)
      }
    };
  }

  const now = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());

  const api = {
    pickBetter, runPage, detectPage, textLines, tuneLines, cropOk, readLine, dejunk, readPP, readEslav,
    plausible, readingOrder, normalizePage, luma, resizeRGB, inkShare,
    fixChars, fixDigits, wordOk, DEFAULTS
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.OwnOcr = api;
})(typeof self !== 'undefined' ? self : globalThis);
