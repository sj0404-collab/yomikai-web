require('./shim.js');
const src = require('./koma-src.cjs').app;
// вырезаем только части 2-3 (без UI/boot)
const cut = src.indexOf('/* ───────────────────────── 8. Читалка');
const code = src.slice(0, cut);
const run = new Function(code + `
  return { inkThreshold, greyInkRange, components, textLines, bandsOf, bubblesOf,
    readingOrder, splitPanels, applyWordFixes, cutAtBandBottom, sanitizeRules, DEFAULT_RULES,
    isCyr, decodeCrop, binarizeCanvas, makeCanvas, lumaFrom, decodeBetter };
  `);
const api = run();

const R = api.sanitizeRules({});
let fails = 0;
const eq = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g !== w) { console.log('FAIL', name, '\n  got ', g, '\n  want', w); fails++; }
  else console.log('ok  ', name);
};

// 1. inkThreshold: сверка с формулой из АПК
const luma = new Uint8Array(100*100);
for (let i=0;i<luma.length;i++) luma[i] = i < 2000 ? 160 : 250;   // 2% серых на белом
// Порог должен оказаться ВЫШЕ серых букв (160), иначе они не «чернила».
eq('inkThreshold keeps grey letters as ink', api.inkThreshold(luma, R) > 160, true);
const flat = new Uint8Array(100*100).fill(200);
eq('inkThreshold flat -> -1', api.inkThreshold(flat, R), -1);
// 2. второй уровень чернил находит серый горб
const tri = new Uint8Array(100*100);
for (let i=0;i<tri.length;i++){ const r=Math.random(); tri[i] = r<0.1?40 : r<0.35?165 : 250; }
const g = api.greyInkRange(tri, api.sanitizeRules({inkLevels:2}));
eq('greyInkRange finds grey hump', !!g && g[0] <= 165 && g[1] >= 165, true);
eq('greyInkRange null on two-level image', api.greyInkRange(luma, api.sanitizeRules({inkLevels:2})), null);
// 3. components: два пятна -> два бокса
const w=40,h=40, map=new Float32Array(w*h);
for(let y=5;y<12;y++)for(let x=5;x<20;x++) map[y*w+x]=0.9;
for(let y=25;y<35;y++)for(let x=10;x<30;x++) map[y*w+x]=0.8;
const boxes = api.components(map,h,w);
eq('components count', boxes.length, 2);
eq('components order by top', boxes[0][1] < boxes[1][1], true);
// 4. полосы
eq('bands whole when page fits', api.bandsOf(1, R).length, 1);
const bands = api.bandsOf(0.25, R);
eq('bands count <= bandsMax', bands.length <= R.bandsMax, true);
eq('bands last reaches bottom', Math.round(bands[bands.length-1].bottom*1000)/1000, 1);
// 5. облачка: одна строка + продолжение = одна реплика; разная высота = разные
const reg = (t,l,tp,r,b) => ({text:t,left:l,top:tp,right:r,bottom:b});
const same = api.bubblesOf([reg('УЖЕ ПОРА',0.1,0.10,0.6,0.14), reg('НАЧИНАТЬ',0.12,0.145,0.6,0.185)], true, R);
eq('two lines one bubble', same.length, 1);
const diffH = api.bubblesOf([reg('Небылица',0.1,0.10,0.8,0.20), reg('Автор оригинала',0.1,0.205,0.8,0.225)], true, R);
eq('title vs credits -> two bubbles', diffH.length, 2);
// 6. порядок чтения RTL: правая реплика первой
const two = api.readingOrder([reg('ПЕРВАЯ',0.6,0.30,0.9,0.36), reg('ВТОРАЯ',0.05,0.30,0.35,0.36)], true, true, R);
eq('rtl order right-to-left', two.map(x=>x.text), ['ПЕРВАЯ','ВТОРАЯ']);
const twoL = api.readingOrder([reg('ПЕРВАЯ',0.6,0.30,0.9,0.36), reg('ВТОРАЯ',0.05,0.30,0.35,0.36)], false, true, R);
eq('ltr order left-to-right', twoL.map(x=>x.text), ['ВТОРАЯ','ПЕРВАЯ']);
// 7. правки слов
eq('wordFixes case', api.applyWordFixes('Пвтор оригинала', {Пвтор:'Автор'}), 'Автор оригинала');
eq('wordFixes caps', api.applyWordFixes('ПВТОР ОРИГИНАЛА', {Пвтор:'Автор'}), 'АВТОР ОРИГИНАЛА');
eq('wordFixes untouched', api.applyWordFixes('мачехи', {Пвтор:'Автор'}), 'мачехи');
// 8. срез полосы
eq('cut at band bottom', api.cutAtBandBottom({text:'УЖЕ ПОРА НА-',left:0,top:0.42,right:1,bottom:0.49},{index:0,top:0,bottom:0.5,whole:false},0.06), true);
eq('finished line not cut', api.cutAtBandBottom({text:'ПРИБЫЛА.',left:0,top:0.42,right:1,bottom:0.49},{index:0,top:0,bottom:0.5,whole:false},0.06), false);
// 9. фильтр кириллицы
eq('isCyr russian', api.isCyr('ДАВАЙ ПОИГРАЕМ'), true);
eq('isCyr lettering latin', api.isCyr('Ro'), false);
console.log(fails ? `\n${fails} FAILED` : '\nALL PASSED');
process.exit(fails?1:0);
