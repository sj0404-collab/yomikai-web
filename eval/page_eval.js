// Замер по страницам: весь конвейер (детектор + чтецы + чистка) против эталона.
// Эталоны только для двух страниц — они и остались размеченными по репликам.
const fs = require('fs');
const lev = (a, b) => {
  if (a === b) return 0;
  const n = a.length, m = b.length;
  let prev = Array.from({ length: m + 1 }, (_, j) => j), cur = new Array(m + 1);
  for (let i = 1; i <= n; i++) {
    cur[0] = i;
    for (let j = 1; j <= m; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    [prev, cur] = [cur, prev];
  }
  return prev[m];
};
const clean = (s) => (s || '').toUpperCase().replace(/[^А-ЯЁA-Z0-9]+/g, ' ').trim();
const cer = (a, b) => {
  a = clean(a); b = clean(b);
  return lev(a, b) / Math.max(1, Math.max(a.length, b.length));
};
(async () => {
  const ort = require('/home/user/lab/ort.min.js');
  ort.env.wasm.numThreads = 1;
  ort.env.wasm.wasmPaths = '/home/user/lab/';
  const core = require('/home/user/web-ocr/core.js');
  const R = '/home/user';
  const pth = (x) => new Uint8Array(fs.readFileSync(x));
  const S = (n) => ort.InferenceSession.create(pth(`${R}/web-ocr/models/${n}`));
  const det = await S('koma_det.onnx');
  const rec = await S('koma_rec.onnx');
  const mang = await S('eslav-ft.onnx');
  const web = await S('eslav-webtoon.onnx');
  const hard = await S('eslav-hard.onnx');
  const hand = await S('eslav-hand.onnx');
  const comic = await S('eslav-comic.onnx');
  const letters = fs.readFileSync(`${R}/web-ocr/models/koma_dict.txt`, 'utf8').split(/\r?\n/).filter((s) => s.length);
  const dict = [''].concat(letters, [' ']);
  const vocab = new Set(fs.readFileSync(`${R}/web-ocr/data/vocab-ru.txt`, 'utf8').split(/\r?\n/).map((s) => s.trim().toUpperCase()).filter(Boolean));
  const charset = (fs.readFileSync(`${R}/web-ocr/models/charset.txt`, 'utf8').replace(/\n$/, '')).split('');
  const cases = [['kuro-p1', 'manga'], ['reader-p1', 'webtoon'], ['comic4', 'comic'],
                 ['manhua2', 'webtoon'], ['manhua3x2', 'webtoon']];
  const all = [];
  for (const [page, genre] of cases) {
    const meta = JSON.parse(fs.readFileSync(`${R}/evalwork/${page}.json`, 'utf8'));
    const rgb = new Uint8Array(fs.readFileSync(`${R}/evalwork/${page}.rgb`));
    let truth = null;
    try { truth = JSON.parse(fs.readFileSync(`${R}/web-ocr/test/${page}-truth.json`, 'utf8')); } catch (e) { truth = null; }
    const t0 = Date.now();
    const res = await core.runPage({ det, rec, eslav: mang, eslavWebtoon: web, eslavHard: hard, eslavHand: hand, eslavComic: comic, charset, dict, vocab, ort }, rgb, meta.w, meta.h, { genre });
    const ms = Date.now() - t0;
    const voices = res.voices.map((r) => r.text);
    const sounds = res.sounds.map((s) => s.sound + ':' + s.text);
    let line = `${page}: ${ms} мс · реплик ${voices.length} · звуков ${sounds.length}`;
    if (truth) {
      const n = Math.min(truth.length, voices.length);
      const cs = [];
      for (let i = 0; i < n; i++) cs.push(cer(truth[i], voices[i]));
      for (let i = n; i < truth.length; i++) cs.push(1);
      const c = 100 * cs.reduce((a, b) => a + b, 0) / cs.length;
      line = `${page}: CER ${c.toFixed(1)} % · реплик ${voices.length}/${truth.length} · звуков ${sounds.length} · ${ms} мс`;
      all.push(c);
    }
    console.log(line);
    if (process.env.SHOW) voices.forEach((v, i) => console.log('   ', i, JSON.stringify(v.slice(0, 90))));
  }
  if (all.length) console.log(`СРЕДНЕЕ по страницам с эталоном: ${(all.reduce((a, b) => a + b, 0) / all.length).toFixed(1)} %`);
})();
