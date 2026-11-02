/* Сколько облачков видит детектор: старый путь (вся страница сжата до 1600)
   против нового (плитки 1500 в полном разрешении). */
const fs = require('fs');
const CASES = [
  ['tyrant-p2', 33, 106],     // облачков в разметке, строк
  ['manhua2-p2', 10, 9],
  ['manhua1-p1', 0, 0],
  ['manhua3x2', 12, 12],
];
(async () => {
  const ort = require('/home/user/lab/ort.min.js');
  ort.env.wasm.numThreads = 1; ort.env.wasm.wasmPaths = '/home/user/lab/';
  const core = require('/home/user/web-ocr/core.js');
  const R = '/home/user';
  const det = await ort.InferenceSession.create(new Uint8Array(fs.readFileSync(`${R}/web-ocr/models/koma_det.onnx`)));
  const o = JSON.parse(JSON.stringify(core.DEFAULTS));
  o.ort = ort;
  for (const [name, gtClouds, gtLines] of CASES) {
    const metaPath = `${R}/label-work/${name}.json`;
    if (!fs.existsSync(metaPath)) { console.log(`${name}: нет подготовленной страницы`); continue; }
    const meta = JSON.parse(fs.readFileSync(metaPath, 'utf8'));
    const rgb = new Uint8Array(fs.readFileSync(`${R}/label-work/${name}.rgb`));
    const W = meta.w, H = meta.h;
    // (а) как было: сжать длинную сторону до 1600 — это делает pageSide в Koma
    const k = Math.min(1, 1600 / Math.max(W, H));
    const sw = Math.max(32, Math.round(W * k)), sh = Math.max(32, Math.round(H * k));
    const small = new Uint8Array(sw * sh * 3);
    for (let y = 0; y < sh; y++) {
      const sy = Math.min(H - 1, Math.round(y / k));
      for (let x = 0; x < sw; x++) {
        const sx = Math.min(W - 1, Math.round(x / k));
        const p = (sy * W + sx) * 3, q = (y * sw + x) * 3;
        small[q] = rgb[p]; small[q + 1] = rgb[p + 1]; small[q + 2] = rgb[p + 2];
      }
    }
    const oOld = Object.assign({}, o, { tileSize: 1e9 });
    const oldBoxes = await core.detectPage(det, small, sw, sh, oOld);
    // (б) как стало: плитки 1500 по полному разрешению
    const newBoxes = await core.detectPage(det, rgb, W, H, o);
    const linesOf = (boxes, px, w, h) => {
      let n = 0;
      for (const b of boxes.slice(0, o.maxBoxes)) n += core.textLines(px, w, h, b, o).length;
      return n;
    };
    const oldLines = linesOf(oldBoxes, small, sw, sh);
    const newLines = linesOf(newBoxes, rgb, W, H);
    console.log(`${name} ${W}×${H}` + (gtClouds ? ` (в разметке облачков ${gtClouds}, строк ${gtLines})` : ''));
    console.log(`   было (сжатие до 1600): боксов ${oldBoxes.length}, строк ${oldLines}`);
    console.log(`   стало (плитки 1500):   боксов ${newBoxes.length}, строк ${newLines}`);
  }
})();
