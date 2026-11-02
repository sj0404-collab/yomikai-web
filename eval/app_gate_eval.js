/* Замер гейта на размеченных страницах: принятые против помеченных. */
const fs = require('fs');
const NAMES = ['comic1x5', 'comic1x7', 'manhua3x2', 'manhua2-p2', 'kuro-p2', 'tyrant-p1'];
const GT = {};
for (const n of NAMES) {
  const raw = fs.readFileSync(`/home/user/label-work/${n}.gt.txt`, 'utf8').split('\n');
  GT[n] = [];
  for (const line of raw) {
    const i = line.indexOf(':');
    if (i < 0) continue;
    for (const part of line.slice(i + 1).split('|')) {
      const t = part.trim().replace(/^\*/, '');
      if (t) GT[n].push(t);
    }
  }
}
const lev = (a, b) => {
  const d = Array.from({length: a.length + 1}, (_, i) => [i]);
  for (let j = 1; j <= b.length; j++) d[0][j] = j;
  for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
    d[i][j] = Math.min(d[i-1][j] + 1, d[i][j-1] + 1, d[i-1][j-1] + (a[i-1] === b[j-1] ? 0 : 1));
  return d[a.length][b.length] / Math.max(1, Math.max(a.length, b.length));
};
const norm = (s) => s.toUpperCase().replace(/[^\p{L}\p{N}]/gu, '');
(async () => {
  const ort = require('/home/user/lab/ort.min.js');
  ort.env.wasm.numThreads = 1;
  ort.env.wasm.wasmPaths = '/home/user/lab/';
  const core = require('/home/user/web-ocr/core.js');
  const R = '/home/user';
  const pth = (x) => new Uint8Array(fs.readFileSync(x));
  const S = (n) => ort.InferenceSession.create(pth(`${R}/web-ocr/models/${n}`));
  const env = {
    det: await S('koma_det.onnx'), rec: await S('koma_rec.onnx'),
    eslav: await S('eslav-ft.onnx'), eslavWebtoon: await S('eslav-webtoon.onnx'),
    eslavHard: await S('eslav-hard.onnx'), eslavComic: await S('eslav-comic.onnx'),
    charset: fs.readFileSync(`${R}/web-ocr/models/charset.txt`, 'utf8').replace(/\n$/, '').split(''),
    dict: [''].concat(fs.readFileSync(`${R}/web-ocr/models/koma_dict.txt`, 'utf8').split(/\r?\n/).filter((s) => s.length), [' ']),
    vocab: new Set(fs.readFileSync(`${R}/web-ocr/data/vocab-ru.txt`, 'utf8').split(/\r?\n/).map((s) => s.trim().toUpperCase()).filter(Boolean)),
    ort,
  };
  const GENRE = { 'comic1x5': 'comic', 'comic1x7': 'comic', 'manhua3x2': 'webtoon', 'manhua2-p2': 'webtoon', 'kuro-p2': 'manga', 'tyrant-p1': 'webtoon' };
  let accS = 0, nS = 0, accU = 0, nU = 0, okS = 0, okU = 0;
  const stats = [];
  for (const name of NAMES) {
    const meta = JSON.parse(fs.readFileSync(`${R}/label-work/${name}.json`, 'utf8'));
    const rgb = new Uint8Array(fs.readFileSync(`${R}/label-work/${name}.rgb`));
    const res = await core.runPage(env, rgb, meta.w, meta.h, { genre: GENRE[name] });
    const voices = res.voices;
    const line = [];
    for (const r of voices) {
      let best = 1;
      const G = GT[name].map(norm);
      for (let i = 0; i < G.length; i++) {
        let acc = '';
        for (let k = i; k < Math.min(G.length, i + 6); k++) {
          acc += G[k];
          best = Math.min(best, lev(norm(r.text), acc));
        }
      }
      stats.push({ agree: r.agree, readers: r.readers, cer: best, unsure: r.unsure });
      if (r.unsure) { accU += best; nU++; if (best === 0) okU++; }
      else { accS += best; nS++; if (best === 0) okS++; }
      line.push(`${r.unsure ? '⚠' : ' '} ${best.toFixed(2)} ${r.text.slice(0, 46)}`);
    }
    console.log(`=== ${name} · реплик ${res.replies.length} (голос ${nS === 0 && nU === 0 ? voices.length : ''}) · принято ${voices.filter((r) => !r.unsure).length} · помечено ${voices.filter((r) => r.unsure).length}`);
    for (const l of line) console.log('   ' + l);
  }
  const by = {};
  for (const st of stats) {
    const k = `${st.agree}/${st.readers}`;
    (by[k] = by[k] || []).push(st.cer);
  }
  console.log('\nсогласие/чтецов, реплик, CER:');
  for (const k of Object.keys(by).sort()) {
    const a = by[k];
    console.log(`  ${k.padEnd(6)} ${String(a.length).padStart(3)} · CER ${(100*a.reduce((x,y)=>x+y,0)/a.length).toFixed(1)} %`);
  }
  console.log('\nИТОГ по размеченным страницам:');
  console.log(`  принято без правки: ${nS} реплик · CER ${(100*accS/Math.max(1,nS)).toFixed(2)} % · точно верных ${(100*okS/Math.max(1,nS)).toFixed(0)} %`);
  console.log(`  помечено «проверь»: ${nU} реплик · CER ${(100*accU/Math.max(1,nU)).toFixed(2)} % · точно верных ${(100*okU/Math.max(1,nU)).toFixed(0)} %`);
})();
