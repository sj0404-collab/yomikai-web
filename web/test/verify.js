/* Прогон браузерного движка (web-ocr/core.js) в Node и сверка с Python-эталоном.
 *
 *   node web-ocr/test/verify.js            # dense-a
 *   node web-ocr/test/verify.js dense-b    # другая страница
 *
 * Нужен onnxruntime-web: путь берётся из ORT_DIR (по умолчанию /tmp/ortw).
 */
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '../..');
const ORT_DIR = process.env.ORT_DIR || '/tmp/ortw';
const page = process.argv[2] || 'dense-a';

(async () => {
  const ort = require(path.join(ORT_DIR, 'ort.min.js'));
  ort.env.wasm.numThreads = 1;
  ort.env.wasm.wasmPaths = ORT_DIR + '/';

  const core = require('../core.js');
  const bytes = (p) => new Uint8Array(fs.readFileSync(p));
  const det = await ort.InferenceSession.create(bytes(path.join(ROOT, 'koma_models/koma_det.onnx')));
  const rec = await ort.InferenceSession.create(bytes(path.join(ROOT, 'koma_models/koma_rec.onnx')));

  const letters = fs.readFileSync(path.join(ROOT, 'koma_models/koma_dict.txt'), 'utf8')
    .split(/\r?\n/).filter((s) => s.length > 0);
  const dict = [''].concat(letters, [' ']);

  const vocab = new Set(fs.readFileSync(path.join(__dirname, 'vocab-ru.txt'), 'utf8')
    .split(/\r?\n/).map((s) => s.trim().toUpperCase()).filter(Boolean));

  const meta = JSON.parse(fs.readFileSync(path.join(__dirname, page + '.json'), 'utf8'));
  const rgb = new Uint8Array(fs.readFileSync(path.join(__dirname, page + '.rgb')));

  const opts = {};
  if (process.env.MINCONF) opts.minConf = parseFloat(process.env.MINCONF);
  const res = await core.runPage({ det, rec, dict, vocab, ort }, rgb, meta.w, meta.h, opts);

  console.log(`${page} ${meta.w}×${meta.h}`);
  console.log('статистика:', JSON.stringify(res.stats));
  res.replies.forEach((r, i) => console.log(`${String(i + 1).padStart(2)}. ${r.text}`));
  fs.writeFileSync(path.join(__dirname, page + '-web.json'),
    JSON.stringify({ replies: res.replies.map((r) => r.text), stats: res.stats }, null, 1));
})().catch((e) => { console.error('ОШИБКА:', e); process.exit(1); });
