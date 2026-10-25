// Вшитые WASM-бинари: разжимаются, отдаются движку как blob-URL, размеры сходятся.
const fs = require('fs');
const crypto = require('crypto');
const src = fs.readFileSync('/home/user/koma-web/part0-wasm.js', 'utf8');

const blobs = [];
global.URL = { createObjectURL: (b) => { blobs.push(b); return 'blob:test/' + blobs.length; }, revokeObjectURL() {} };
global.ort = { env: { wasm: {} } };
new Function(src + '; global.__api={installOrtWasm,gunzipB64,ORT_WASM_GZ};')();
const { installOrtWasm, gunzipB64, ORT_WASM_GZ } = global.__api;
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  const md5 = (u8) => crypto.createHash('md5').update(Buffer.from(u8)).digest('hex');
  const simd = await gunzipB64(ORT_WASM_GZ.simd);
  const plain = await gunzipB64(ORT_WASM_GZ.plain);
  ok(simd.length === 10595041, 'ort-wasm-simd.wasm разжат: ' + simd.length + ' байт');
  ok(md5(simd) === '49460a4b3ff6631a5475ff4e53ac5404', 'md5 SIMD совпадает с CDN-файлом');
  ok(plain.length === 9758086, 'ort-wasm.wasm разжат: ' + plain.length + ' байт');
  ok(md5(plain) === 'd51675fd5b58066c2cb0d2ffa4b6de78', 'md5 обычного WASM совпадает');
  ok(simd.slice(0, 4).join(',') === '0,97,115,109', 'сигнатура \\0asm на месте');

  const r = await installOrtWasm();
  ok(r === true, 'installOrtWasm вернул true');
  const paths = global.ort.env.wasm.wasmPaths;
  ok(paths && paths['ort-wasm-simd.wasm'] && paths['ort-wasm.wasm'], 'wasmPaths — карта «имя → blob:»');
  ok(blobs.length === 2 && blobs.every(b => b.type === 'application/wasm'), 'два Blob с application/wasm');
  ok(await installOrtWasm() === true && blobs.length === 2, 'повторный вызов не плодит Blob');

  // Ни одной сетевой ссылки в офлайн-части
  ok(!/https?:\/\//.test(src.replace(/'[^']*'/, '')), 'в части WASM нет http-ссылок');
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})();
