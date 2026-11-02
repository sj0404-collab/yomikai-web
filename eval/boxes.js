// Рамки строк для разметки: тот же детектор и те же чистки, что в приложении.
const fs = require('fs');
(async () => {
  const ort = require('/home/user/lab/ort.min.js');
  ort.env.wasm.numThreads = 1;
  ort.env.wasm.wasmPaths = '/home/user/lab/';
  const core = require('/home/user/web-ocr/core.js');
  const R = '/home/user';
  const name = process.argv[2];
  const meta = JSON.parse(fs.readFileSync(`${R}/label-work/${name}.json`, 'utf8'));
  const rgb = new Uint8Array(fs.readFileSync(`${R}/label-work/${name}.rgb`));
  const det = await ort.InferenceSession.create(
    new Uint8Array(fs.readFileSync(`${R}/web-ocr/models/koma_det.onnx`)));
  const o = JSON.parse(JSON.stringify(core.DEFAULTS));
  o.ort = ort;
  const boxes = await core.detectPage(det, rgb, meta.w, meta.h, o);
  let lines = [];
  for (const b of boxes.slice(0, o.maxBoxes)) lines.push(...core.textLines(rgb, meta.w, meta.h, b, o));
  const tuned = core.tuneLines(rgb, meta.w, lines, o);
  console.log(JSON.stringify(tuned));
})();
