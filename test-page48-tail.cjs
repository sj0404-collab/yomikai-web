// Реплики со скриншота 21:20 (страница 4, «Том 1 Глава 48»).
//
// Было в 1.9.48: реплика 1 теряла начало («пе СЕБЕ УВЛЕЧЬСЯ…»), реплика 2
// обрывалась на «…КОГДА СЛУША» — хвост «ЕТЕ ЕЁ.» выбрасывался, потому что
// чтец прочитал его латиницей с точками: «TE EË.».
// Стало: обе реплики целиком.
const fs = require('fs');
require('./shim.js');
delete global.indexedDB;
global.window.addEventListener = () => {};
global.navigator = { userAgent: 'Node' };
const dictSrc = fs.readFileSync(__dirname + '/part0-dict.js', 'utf8');
const body = ['part0-wasm.js', 'part2.js', 'part3.js']
  .map(f => fs.readFileSync(__dirname + '/' + f, 'utf8')).join('\n');
const api = new Function(dictSrc + '\n' + body + '; return {Words};')();
const ok = (c, m) => { console.log((c ? 'PASS ' : 'FAIL ') + m); if (!c) process.exitCode = 1; };

(async () => {
  await api.Words.load();
  const W = api.Words;
  const P = (t) => W.polish(t, 0.6, 0.9);

  // Хвост реплики 2: «СЛУШАЕ-» + «TE EË.» (латиница с точками).
  ok(P('ЗА, КОГДА СЛУШАЕ- TE EË.').toUpperCase().includes('СЛУШАЕТЕ ЕЁ'),
    'хвост «СЛУШАЕ- TE EË.» → «СЛУШАЕТЕ ЕЁ» (реплика не обрывается)');
  // Реплика целиком, как её отдал движок чтения.
  const r2 = P('ВЫ ДОЛЖНЫ ЬЫТЬ РАВНОДУШНЫ, КАК И ЗСЕГДА. ПРИТВОРИТЕСЬ ЧТО ОБДУМЫВАЕТЕ ЧТО ОНА ГОВОРИТ 2-З РАЗА, КОГДА СЛУШАЕTE EË.');
  ok(r2.toUpperCase().startsWith('ВЫ ДОЛЖНЫ БЫТЬ'), '«ЬЫТЬ» → «БЫТЬ»');
  ok(r2.toUpperCase().includes('КАК И ВСЕГДА'), '«ЗСЕГДА» → «ВСЕГДА»');
  ok(/2-3 РАЗА/.test(r2), '«2-З РАЗА» → «2-3 РАЗА» (цифры не выбрасываются)');
  ok(r2.toUpperCase().trim().endsWith('СЛУШАЕТЕ ЕЁ.'), 'и реплика кончается на «СЛУШАЕТЕ ЕЁ.»');
  // Реплика 1 не должна терять начало.
  const r1 = P('НЕ ПОЗВОЛЯЙТЕ СЕБЕ УВЛЕЧЬСЯ ЕЁ ВЫСОЧЕСТВОМ.');
  ok(r1.startsWith('НЕ ПОЗВОЛЯЙТЕ'), 'реплика 1 начинается с «НЕ ПОЗВОЛЯЙТЕ»');
  ok(P('ПРОЧЬ.') === 'ПРОЧЬ.', 'короткая «ПРОЧЬ.» остаётся');
  ok(P('ДА, ЭТО ИМЕННО ТО, ЧТО ВЫ ДОЛЖНЫ ДЕЛАТЬ.').toUpperCase().includes('ДОЛЖНЫ ДЕЛАТЬ'),
    'четвёртая реплика не портится');
  console.log(process.exitCode ? 'FAILED' : 'ALL PASSED');
})();
