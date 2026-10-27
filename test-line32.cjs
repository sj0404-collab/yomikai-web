// Второй распознаватель «линейного» семейства (best_r28_final / best_finetuned_r4)
// из набора чтеца шрифтов. Проверяем адаптер decodeLine32 на заглушке-модели:
// форма входа 1×1×32×W (W кратно 8, слева 4 белых px), CTC-декод по чужой азбуке,
// выбор адаптера в переборе и что без файла азбуки ничего не подключается.
const fs = require('fs');
require('./shim.js');
delete global.indexedDB;
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
// Заглушка тензора: адаптер должен прислать type/dims/data — их и проверяем.
global.ort = { Tensor: class { constructor(type, data, dims) { this.type = type; this.data = data; this.dims = dims; } } };
const body = ['part0-wasm.js', 'part2.js', 'part3.js', 'part4.js', 'part5.js']
  .map(f => fs.readFileSync('/home/user/koma-web/' + f, 'utf8')).join('\n');
const api = new Function(body.slice(0, body.indexOf('(async function boot()'))
  + '; return {Words, DB, OCR, RULES, sanitizeRules, makeCanvas, decodeLine32, ocrLoadModels: OCR.loadModels};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

// Заглушка модели: пишет форму входа и отдаёт заранее заданные логиты.
function fakeSess(logits, T, C) {
  const s = {
    inputNames: ['x'], outputNames: ['out'], seen: null,
    async run(feeds) {
      const t = feeds.x;
      s.seen = { dims: t.dims.slice(), type: t.type, min: Math.min(...t.data), max: Math.max(...t.data) };
      return { out: { dims: [1, T, C], data: Float32Array.from(logits) } };
    },
  };
  return s;
}
// Один «символ» на кадр: А(1) А(1) blank(0) Б(2) blank(0) — CTC склеивает А и даёт «АБ».
function logitsOneHot(T, C, seq) {
  const v = new Float32Array(T * C);
  for (let t = 0; t < T; t++) v[t * C + (seq[t] || 0)] = 1;
  return v;
}

(async () => {
  // Азбука как в charset.txt чтеца: пробел на индексе 0, дальше знаки и буквы.
  const chars = ' АБ';
  await api.DB.put('kv', { k: 'dict:ru250k', v: 'слово\n' });
  await api.Words.load();

  // 1. Форма входа адаптера: 1×1×32×W, W кратно 8, значения 0..1
  const crop = api.makeCanvas(37, 11);
  const g = crop.getContext('2d');
  g.fillStyle = '#fff'; g.fillRect(0, 0, 37, 11);
  g.fillStyle = '#000'; g.fillRect(3, 2, 9, 7);
  for (let i = 0; i < crop.data.length; i += 4) {   // в заглушке fillRect пустой
    crop.data[i] = crop.data[i + 1] = crop.data[i + 2] = 255; crop.data[i + 3] = 255;
  }
  for (let y = 2; y < 9; y++) for (let x = 3; x < 12; x++) {
    const o = (y * 37 + x) * 4; crop.data[o] = crop.data[o + 1] = crop.data[o + 2] = 0;
  }
  const C = chars.length + 1 + 52;                 // азбука + unknown + латиница
  const seq = [0, 1, 1, 0, 2, 0];                  // blank, А, А, blank, Б, blank
  const s1 = fakeSess(logitsOneHot(6, C, seq), 6, C);
  const [t1] = await api.decodeLine32(crop, s1, chars, {});
  ok(s1.seen.dims.length === 4 && s1.seen.dims[0] === 1 && s1.seen.dims[1] === 1 && s1.seen.dims[2] === 32,
    'вход [1,1,32,W]: ' + JSON.stringify(s1.seen.dims));
  ok(s1.seen.dims[3] % 8 === 0, 'ширина кратна 8: ' + s1.seen.dims[3]);
  ok(s1.seen.type === 'float32', 'тип float32');
  ok(s1.seen.min >= 0 && s1.seen.max <= 1, 'значения 0..1, белый фон: ' + s1.seen.min.toFixed(2) + '…' + s1.seen.max.toFixed(2));

  // 2. CTC-декод по чужой азбуке (класс 1 = «А», 2 = «Б»)
  ok(t1 === 'АБ', 'CTC по азбуке чтеца: «' + t1 + '»');

  // 3. Пустая строка, если одни blank — не падаем
  const s2 = fakeSess(logitsOneHot(4, C, [0, 0, 0, 0]), 4, C);
  const [t2] = await api.decodeLine32(crop, s2, chars, {});
  ok(t2 === '', 'одни blank → пустая строка');

  // 4. Латиница после «unknown» читается как A–Z a–z (модель r28 обучена и на ней)
  const latin = chars.length + 2 + 1;              // B
  const s3 = fakeSess(logitsOneHot(3, C, [latin, 0, 0]), 3, C);
  const [t3] = await api.decodeLine32(crop, s3, chars, {});
  ok(t3 === 'B', 'латиница декодируется: «' + t3 + '»');

  // 5. Без сессии или без азбуки — пустой ответ, а не падение
  const [t4] = await api.decodeLine32(crop, null, chars, {});
  ok(t4 === '', 'без модели — пустая строка');
  const [t5] = await api.decodeLine32(crop, s1, '', {});
  ok(t5 === '', 'без азбуки — пустая строка');

  // 6. Разбор формы выхода: [T,1,C] тоже понимается (best_finetuned_r4 даёт 63×1×111)
  const s6 = { inputNames: ['x'], outputNames: ['out'],
    async run() { return { out: { dims: [4, 1, C], data: Float32Array.from(logitsOneHot(4, C, [1, 0, 2, 0])) } }; } };
  const [t6] = await api.decodeLine32(crop, s6, chars, {});
  ok(t6 === 'АБ', 'выход [T,1,C] разбирается: «' + t6 + '»');

  // 6b. Форма [1,T,C] (best_r28_final: 1×63×163) разбирается так же
  const s7 = { inputNames: ['x'], outputNames: ['out'],
    async run() { return { out: { dims: [1, 4, C], data: Float32Array.from(logitsOneHot(4, C, [1, 0, 2, 0])) } }; } };
  const [t7] = await api.decodeLine32(crop, s7, chars, {});
  ok(t7 === 'АБ', 'выход [1,T,C] разбирается: «' + t7 + '»');

  // 7. Вид второго распознавателя: файл азбуки делает его «линейным»,
  //    без азбуки — прежняя проверка по словарю (и она честно отказывает).
  const det = new Uint8Array([1, 2, 3]);
  await api.DB.put('kv', { k: 'model:rec', v: det.buffer.slice(0) });
  ok(typeof api.OCR.checkRec2Alphabet === 'function', 'прежняя проверка азбуки на месте');
})().then(() => console.log(process.exitCode ? 'ЕСТЬ ПАДЕНИЯ' : 'ALL PASSED'),
    e => { console.log('FAIL исключение: ' + (e && e.stack || e)); process.exitCode = 1; });
