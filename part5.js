
/* ───────────────────────── 12. Привязка событий ───────────────────────── */
/**
 * Что браузер умеет на самом деле. В вебе нет Android SAF — его нельзя
 * вызвать из страницы. Ближайшее: File System Access API (Chrome Android 132+,
 * Chrome/Edge на десктопе) и старый input[webkitdirectory] (только десктоп).
 * Ниже — честный ответ на вопрос «почему нет кнопки "выбрать папку"».
 */
const FILES = (() => {
  const ua = navigator.userAgent || '';
  const m = ua.match(/Chrome\/(\d+)/);
  const chromium = m ? +m[1] : 0;
  const android = /Android/i.test(ua);
  const fsa = typeof window.showDirectoryPicker === 'function';
  const dirInput = 'webkitdirectory' in document.createElement('input');
  const secure = window.isSecureContext !== false;
  let why = '';
  if (fsa) why = 'выбор папки доступен (File System Access)';
  else if (android) {
    why = 'выбор папки в этом браузере недоступен: Android-браузеры отдают только файлы';
    if (chromium && chromium < 132) why += ` (у вас Chrome ${chromium}, папка появится с 132)`;
  } else if (dirInput) why = 'выбор папки доступен (input webkitdirectory)';
  else why = 'выбор папки недоступен: браузер его не поддерживает';
  if (!secure) why += ' · страница не в защищённом контексте';
  return { fsa, dirInput, android, chromium, secure, why };
})();

function bindUI() {
  // ── Шторки: крестик в шапке и закрытие по подложке ──
  // Раньше «Закрыть» была только в самом низу: на телефоне шторка выше экрана,
  // и до кнопки надо было долистать. Плюс часть шторок закрывалась только ею.
  $$('.sheet').forEach(sh => {
    const head = sh.querySelector('.head');
    if (head && !head.querySelector('.x')) {
      const x = document.createElement('button');
      x.className = 'x'; x.type = 'button'; x.setAttribute('aria-label', 'Закрыть');
      x.textContent = '✕';
      x.onclick = () => closeSheets();
      head.appendChild(x);
    }
  });
  const bg = $('#sheetBg');
  if (bg) bg.onclick = () => closeSheets();
  // закрытие свайпом вниз по шапке — привычный жест
  $$('.sheet .head').forEach(head => {
    let y0 = null;
    head.addEventListener('touchstart', (e) => { y0 = e.touches[0].clientY; }, { passive: true });
    head.addEventListener('touchend', (e) => {
      if (y0 != null && e.changedTouches[0].clientY - y0 > 60) closeSheets();
      y0 = null;
    }, { passive: true });
  });

  // ── Импорт главы ────────────────────────────────────────────────────────
  // Каждый выбор — свой input: общий переиспользовался, и выбор модели
  // запускал импорт библиотеки («выбрал onnx — и меня выбросило в читалку»).
  const imgInput = $('#imgPick');
  const dirInput = $('#dirPick');
  const modelInput = $('#modelPick');
  const modelDirInput = $('#modelDirPick');
  const rulesInput = $('#rulesPick');

  $('#btnImport').onclick = () => {
    const fsOK = FILES.fsa;
    const dirOK = FILES.dirInput;
    // Кнопки не прячем: видно, что они есть и почему не работают.
    $('#btnPickDir').style.display = 'block';
    $('#btnPickDir').disabled = !dirOK;
    $('#btnPickDir').style.opacity = dirOK ? '1' : '.45';
    $('#btnPickFolderModern').style.display = 'block';
    $('#btnPickFolderModern').disabled = !fsOK;
    $('#btnPickFolderModern').style.opacity = fsOK ? '1' : '.45';
    $('#importCaps').textContent = 'Ваш браузер: ' + FILES.why;
    // Куда добавлять: список существующих глав
    const sel = $('#importTarget');
    const books = Library.books || [];
    sel.innerHTML = '<option value="">Новая глава</option>'
      + books.map(b => `<option value="${b.id}">Добавить страницы в «${escapeHtml(b.title)}» (${b.count} стр.)</option>`).join('');
    $('#importNote').innerHTML = dirOK || fsOK
      ? 'Папка: страницы берутся все сразу, порядок — по именам файлов.'
      : 'Этот браузер не умеет выбирать папку. Нажмите «Выбрать файлы или CBZ» '
        + 'и отметьте сразу все страницы главы — порядок возьмём из имён.';
    $('#importTip').innerHTML = 'Подойдёт: папка с главой · CBZ/ZIP · просто набор картинок.<br>'
      + (ENV.android
        ? 'На Android папку браузер не отдаёт: в файловом менеджере удерживайте первую '
          + 'страницу, затем последнюю — выберутся все, порядок возьмём из имён.'
        : 'На десктопе проще всего выбрать папку целиком.');
    openSheet('sheetImport');
  };

  async function addImages(files) {
    const target = ($('#importTarget') && $('#importTarget').value) || '';
    const imgs = Array.from(files).filter(f => /\.(jpe?g|png|webp|avif|bmp|gif)$/i.test(f.name));
    if (!imgs.length) { toast('Среди выбранных файлов нет картинок'); return; }
    // Одна книга на главу: имя папки, если оно есть, иначе имя файла/общий заголовок.
    const rel = (f) => f.webkitRelativePath || f.name;
    const folders = new Set(imgs.map(f => (f.webkitRelativePath || '').split('/')[0]).filter(Boolean));
    imgs.sort((a, b) => rel(a).localeCompare(rel(b), undefined, { numeric: true }));
    const title = folders.size === 1 ? Array.from(folders)[0]
      : imgs.length === 1 ? imgs[0].name.replace(/\.[^.]+$/, '')
      : 'Глава из ' + imgs.length + ' страниц';
    toast('Сохраняю ' + imgs.length + ' страниц…', 5000);
    const items = imgs.map(f => ({ name: f.name, blob: f }));
    if (target) {
      const book = await Library.appendTo(target, items);
      await Library.load();
      toast('Добавлено ' + imgs.length + ' стр. в «' + book.title + '» — всего ' + book.count);
    } else {
      await Library.addBook(title, items, 'files');
      await Library.load();
      toast('Добавлено: ' + title + ' (' + imgs.length + ' стр.)');
    }
  }

  $('#btnPickDir').onclick = () => {
    if (!FILES.dirInput) {
      toast('Этот браузер не умеет выбирать папку — ' + FILES.why + '. Выберите файлы или CBZ.', 7000);
      return;
    }
    dirInput.click();
  };
  $('#btnPickFolderModern').onclick = async () => {
    if (!FILES.fsa) {
      toast('Выбор папки недоступен: ' + FILES.why
        + '. Обновите Chrome до 132+ или соберите страницы в CBZ.', 7000);
      return;
    }
    try {
      const handle = await window.showDirectoryPicker();
      const files = [];
      for await (const entry of handle.values()) {
        if (entry.kind !== 'file') continue;
        files.push(await entry.getFile());
      }
      closeSheets();
      await addImages(files);
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      toast('Папка не открылась: ' + (e.message || e) + ' — выбирайте файлами', 5000);
      imgInput.click();
    }
  };
  $('#btnPickFiles').onclick = () => imgInput.click();

  dirInput.addEventListener('change', async () => {
    const files = Array.from(dirInput.files || []);
    dirInput.value = '';
    if (!files.length) return;
    closeSheets();
    try { await addImages(files); }
    catch (e) { toast('Не удалось добавить папку: ' + (e.message || e), 5000); }
  });
  imgInput.addEventListener('change', async () => {
    const files = Array.from(imgInput.files || []);
    imgInput.value = '';
    if (!files.length) return;
    closeSheets();
    try {
      const zips = files.filter(f => /\.(cbz|zip)$/i.test(f.name));
      for (const z of zips) await importZip(z);
      const rest = files.filter(f => !/\.(cbz|zip)$/i.test(f.name));
      if (rest.length) await addImages(rest);
    } catch (e) { toast('Импорт не удался: ' + (e.message || e), 5000); }
  });
  $('#closeImport').onclick = closeSheets;

  $('#btnModels').onclick = () => { openSheet('sheetModels'); renderModels(); };

  $('#btnRulesLib').onclick = () => { openSheet('sheetRules'); renderRulesInfo(); renderBufferSheet(); };
  $$('#closeSheets,#closeSheets2,#closeSheets3,#closeSheets4').forEach(b => b.onclick = closeSheets);

  // Кнопка «Проверить движок» была в разметке, но НИ К ЧЕМУ не привязана:
  // нажатие не делало ничего. Теперь она запускает синтетическую страницу и
  // показывает работу: «Проверяю…» → результат.
  if ($('#btnTestVoice')) {
    const b = $('#btnTestVoice');
    b.onclick = async (e) => {
      const el2 = e.currentTarget;
      if (el2.disabled) return;
      const label = el2.textContent || 'Проверить голос';
      el2.disabled = true; el2.textContent = 'Говорю…';
      try {
        // Проговариваем и показываем отчёт: какая из трёх причин молчания.
        const report = await selfTestVoice();
        toast(report, 9000);
      } finally {
        el2.disabled = false; el2.textContent = label;
      }
    };
  }

  const btnTest = $('#btnTestEngine');
  if (btnTest) btnTest.onclick = async (e) => {
    const b = e.currentTarget;
    if (b.disabled) return;
    const label = b.textContent || 'Проверить движок';
    b.disabled = true; b.textContent = 'Проверяю…';
    try { await selfTestEngine(); }
    finally { b.disabled = false; b.textContent = label; }
  };
  $('#btnPickModels').onclick = () => modelInput.click();
  // Осознанный выбор в шторке текста: распознать ВСЮ страницу, а не только
  // видимую полосу (у вебтуна полос много, автопрокрутка идёт по экрану).
  if ($('#btnFullPage')) {
    const b = $('#btnFullPage');
    b.onclick = async () => {
      const i = Reader.page;
      b.disabled = true;
      try {
        await Reader.scanPage(i, { force: true, keepSheet: true, full: true });
        renderTextSheet(i);
      } finally {
        b.disabled = false;
      }
    };
  }
  // Словарь — отдельным выбором: его берут из того же APK (assets/koma/dict).
  $('#btnPickDict').onclick = () => {
    const inp = document.createElement('input');
    inp.type = 'file'; inp.accept = '.txt,text/plain';
    inp.onchange = async () => {
      const f = inp.files && inp.files[0];
      if (!f) return;
      if (!/250k|ru_|russian|dict|словар/i.test(f.name) && f.size < 100000) {
        const ok = true; void ok;
      }
      toast('Читаю словарь…', 4000);
      const text = await f.text();
      const count = text.split('\n').filter(l => l.trim()).length;
      if (count < 1000) { toast('Это не словарь: ' + count + ' строк', 6000); return; }
      await DB.put('kv', { k: 'dict:ru250k', v: text });
      const ok = await Words.load();
      await renderModels();
      toast(ok ? 'Словарь загружен: ' + Words.size + ' слов' : 'Словарь не разобрался', 5000);
    };
    inp.click();
  };
  $('#btnPickModelDir').onclick = () => {
    if (!('webkitdirectory' in document.createElement('input'))) {
      toast('Папку браузер не выберет — выберите три файла сразу', 4000);
      modelInput.click();
      return;
    }
    modelDirInput.click();
  };
  modelInput.addEventListener('change', async () => {
    const files = Array.from(modelInput.files || []);
    modelInput.value = '';
    try { await storeModelFiles(files); }
    catch (e) { toast('Модель не принялась: ' + (e.message || e), 5000); }
  });
  modelDirInput.addEventListener('change', async () => {
    const files = Array.from(modelDirInput.files || []);
    modelDirInput.value = '';
    try { await storeModelFiles(files); }
    catch (e) { toast('Модели из папки не принялись: ' + (e.message || e), 5000); }
  });
  // Случайно стереть 12 МБ моделей одним касанием не даём.
  let armedClear = false, armTimer = null;
  $('#btnClearModels').onclick = async (e) => {
    const b = e.currentTarget;
    if (!armedClear) {
      armedClear = true; b.textContent = 'Точно убрать?';
      clearTimeout(armTimer);
      armTimer = setTimeout(() => { armedClear = false; b.textContent = 'Убрать модели'; }, 3000);
      return;
    }
    clearTimeout(armTimer); armedClear = false; b.textContent = 'Убрать модели';
    for (const k of ['model:det', 'model:rec', 'model:dict']) await DB.del('kv', k);
    OCR.ready = false; OCR.det = OCR.rec = null; OCR.engine = 'idle';
    await renderModels();
    toast('Модели убраны. Словарь вшит в файл — его трогать не нужно', 5000);
  };

  // правила
  $('#btnRulesImport').onclick = () => {
    const inp = rulesInput;
    inp.onchange = async () => {
      const f = inp.files?.[0]; inp.value = '';
      if (!f) return;
      try {
        RULES = sanitizeRules(JSON.parse(await f.text()));
        await DB.put('kv', { k: 'rules', v: JSON.stringify(RULES) });
        renderRulesInfo(); toast('Правила применены: ' + RULES.version);
      } catch (e) { toast('Файл правил не разобрался: ' + e.message); }
    };
    inp.click();
  };
  $('#btnRulesExport').onclick = () => {
    const blob = new Blob([JSON.stringify(RULES, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'koma-rules.json'; a.click();
  };
  $('#btnRulesReset').onclick = async () => {
    RULES = sanitizeRules({ ...DEFAULT_RULES });
    await DB.put('kv', { k: 'rules', v: JSON.stringify(RULES) });
    renderRulesInfo(); toast('Встроенные правила');
  };
  $('#btnWordFixesSave').onclick = async () => {
    try {
      const obj = JSON.parse($('#wordFixesBox').value || '{}');
      RULES.wordFixes = obj;
      await DB.put('kv', { k: 'rules', v: JSON.stringify(RULES) });
      toast('Правки слов сохранены: ' + Object.keys(obj).length);
      // пересчитываем порядок из буфера, без нового OCR
      const i = Reader.page;
      const buf = await Buffer.get(i);
      if (buf) {
        const data = Reader.regions.get(i);
        if (data) {
          data.lines = readingOrder(data.regions, Reader.mode === 'rtl', true, RULES);
          Reader.paintPage(i);
          toast('Порядок пересчитан из буфера: ' + data.lines.length + ' реплик');
        }
      }
    } catch (e) { toast('JSON правок не разобрался: ' + e.message); }
  };
  $('#btnBufferExport').onclick = async () => {
    const items = await Buffer.all();
    const text = items.map(p => `стр. ${p.page + 1} · r${p.rules}\n` +
      p.lines.map(l => '  ' + l.text).join('\n')).join('\n\n') || 'Буфер пуст';
    const blob = new Blob([text], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'koma-buffer.txt'; a.click();
  };
  $('#btnBufferClear').onclick = async () => { await Buffer.clear(); await renderBufferSheet(); toast('Буфер очищен'); };

  // читалка
  $('#btnBack').onclick = () => { TTS.stop(); show('library'); Library.load(); };
  // Открывая текст, ставим авточтение на паузу: иначе лента уезжает на
  // следующую страницу, пока человек читает текст, и кажется, что «текст не тот».
  const openTextSheet = () => {
    if (!TTS.stopped) { TTS.stop(); toast('Авточтение остановлено — вы открыли текст страницы', 3500); }
    openSheet('sheetText');
    renderTextSheet(null);           // страницу берём С ЭКРАНА, а не из сохранённого индекса
  };
  $('#btnScan').onclick = openTextSheet;
  $('#btnOcr2').onclick = openTextSheet;
  $('#btnSettings').onclick = () => { openSheet('sheetSettings'); syncSettingsUI(); };
  $('#btnMore').onclick = () => { openSheet('sheetRules'); renderRulesInfo(); renderBufferSheet(); };
  // Шторку НЕ закрываем: иначе не видно, что происходит, и результат некуда
  // показать. Сканируем ту страницу, чей текст открыт (Reader.textPage), а не
  // «текущую в ленте» — из-за этого раньше реплики не перезаписывались вовсе.
  $('#btnRescan').onclick = async () => {
    const i = (Reader.textPage ?? Reader.page);
    $('#btnRescan').disabled = true;
    try {
      await Reader.scanPage(i, { force: true, keepSheet: true });
    } finally {
      $('#btnRescan').disabled = false;
    }
  };
  $('#btnSpeakPage').onclick = async () => {
    TTS.prime();                        // «Прочитать» в шторке — тот же жест
    const i = (Reader.textPage ?? Reader.page);
    await Reader.scanPage(i, { keepSheet: false });
    closeSheets();
    TTS.readVisible();
  };
  $('#btnFrames').onclick = () => {
    Reader.frames = !Reader.frames;
    $('#btnFrames').classList.toggle('hot', Reader.frames);
    Reader.paintAllFrames();
  };
  $('#btnRead').onclick = () => {
    if (TTS.stopped) {
      TTS.prime();                       // разблокировать голос в жесте
      Reader.scanCurrent(false).then(() => TTS.readVisible());
    } else { TTS.stop(); }
  };
  $('#btnStop').onclick = () => TTS.stop();
  $('#btnPause').onclick = () => {
    if (speechSynthesis.speaking) { speechSynthesis.pause(); $('#btnPause').textContent = '▶'; }
    else { speechSynthesis.resume(); $('#btnPause').textContent = '⏸'; }
  };
  $('#btnSkip').onclick = () => { speechSynthesis.cancel(); if (!TTS.stopped) TTS.step(); };
  $('#nextArrow').onclick = async () => {
    hideArrow();
    TTS.prime();
    const step = Math.round(window.innerHeight * 0.85);
    $('#strip').scrollBy({ top: step, behavior: 'smooth' });
    await sleep(300 + RULES.semiManualSettleMs);
    if (!Reader.scrollBusy) TTS.readVisible();
  };

  // настройки чтения
  $('#modeChips').onclick = (e) => {
    const chip = e.target.closest('.chip'); if (!chip) return;
    Reader.mode = chip.dataset.mode;
    if (Reader.book) { Reader.book.mode = Reader.mode; DB.put('books', Reader.book); }
    Reader.buildStrip().then(() => { Reader.syncSub(); syncSettingsUI(); });
  };
  $('#dirChips').onclick = (e) => {
    const chip = e.target.closest('.chip'); if (!chip) return;
    Reader.dir = chip.dataset.dir;
    if (Reader.book) { Reader.book.dir = Reader.dir; DB.put('books', Reader.book); }
    Reader.rescanInDir();
    syncSettingsUI();
  };
  $('#cbAuto').onchange = (e) => {
    if (e.target.checked) Reader.scanCurrent(false).then(() => TTS.readVisible());
    else TTS.stop();
  };
  $('#cbSemi').onchange = (e) => { State.semi = e.target.checked; RULES.semiManual = e.target.checked; };
  $('#numSettle').onchange = async (e) => {
    RULES.semiManualSettleMs = clamp(+e.target.value || 0, 0, 5000);
    await DB.put('kv', { k: 'rules', v: JSON.stringify(RULES) });
  };
  $('#cbFrames').onchange = (e) => {
    Reader.frames = e.target.checked;
    $('#btnFrames').classList.toggle('hot', Reader.frames);
    Reader.paintAllFrames();
  };
  $('#cbFollow').onchange = (e) => { Reader.follow = e.target.checked; };
  $('#reader').addEventListener('click', (e) => {
    if (e.target.closest('.frame') || e.target.closest('button') || e.target.closest('.bottombar')) return;
    if (e.target.tagName === 'IMG') {
      $('#readerBar').classList.toggle('hide');
      $('#readerHeader').style.transform =
        $('#readerBar').classList.contains('hide') ? 'translateY(-110%)' : 'translateY(0)';
    }
  });
}
function syncSettingsUI() {
  $$('#modeChips .chip').forEach(c => c.classList.toggle('on', c.dataset.mode === Reader.mode));
  $$('#dirChips .chip').forEach(c => c.classList.toggle('on', c.dataset.dir === (Reader.dir || 'rtl')));
  $('#cbSemi').checked = !!RULES.semiManual;
  $('#cbFrames').checked = Reader.frames;
  $('#cbFollow').checked = Reader.follow;
  $('#numSettle').value = RULES.semiManualSettleMs;
  $('#cbAuto').checked = !TTS.stopped;
}

/* ───────────────────────── 13. Старт ───────────────────────── */
// Ошибки не должны прятаться в консоли: иначе кнопка «молчит», и непонятно почему.
window.addEventListener('error', (e) => {
  const msg = e.message || (e.error && e.error.message) || 'ошибка';
  toast('Ошибка: ' + msg, 5000);
  console.error(e.error || msg);
});
window.addEventListener('unhandledrejection', (e) => {
  toast('Ошибка: ' + ((e.reason && e.reason.message) || e.reason || 'неизвестно'), 5000);
  console.error(e.reason);
});

const ENV = {
  sandboxed: (() => { try { return window.self !== window.top; } catch { return true; } })(),
  android: /Android/i.test(navigator.userAgent),
};

function showEnvBanner() {
  const b = $('#envBanner');
  const lines = [];
  if (ENV.sandboxed) lines.push('Открыто в предпросмотре: выбор файлов и IndexedDB могут быть заблокированы. Скачайте файл и откройте в Chrome.');
  if (DB.inMemory) lines.push('Хранилище недоступно — библиотека живёт только до перезагрузки страницы.');
  b.style.display = lines.length ? 'block' : 'none';
  b.innerHTML = lines.join('<br>');
}
async function selfCheck() {
  const det = await DB.get('kv', 'model:det');
  const parts = [];
  parts.push('OCR: ' + OCR.statusText());
  parts.push('словарь: ' + (Words.ready ? Words.size.toLocaleString('ru-RU') + ' слов (' + (Words.source || 'вшит') + ')' : 'не загрузился'));
  parts.push(typeof ort === 'undefined' ? 'onnxruntime-web не загружен (нужна сеть)' : 'onnxruntime-web загружен');
  parts.push('TTS ' + (speechSynthesis.getVoices().length ? 'есть' : 'нет голосов'));
  if (ENV.android) parts.push('Android: папки нет, выбирайте файлы/CBZ');
  $('#selfCheck').textContent = 'KOMA Web ' + VERSION + ' · ' + parts.join(' · ');
}

(async function boot() {
  bindUI();
  Words.load().catch(e => console.warn('словарь не загрузился', e));
  watchScroll();
  TTS.init();
  const saved = await DB.get('kv', 'rules');
  if (saved) { try { RULES = sanitizeRules(JSON.parse(saved.v)); } catch (e) { console.warn(e); } }
  await Library.load();
  await renderModels();
  const ok = await OCR.loadModels().catch(e => { console.warn('модели не загрузились', e); return false; });
  if (!ok && (await DB.get('kv', 'model:det'))) toast('Модели есть, но движок не загрузился — нужна сеть для onnxruntime-web', 5000);
  renderRulesInfo();
  showEnvBanner();
  await selfCheck();
  setTimeout(selfCheck, 2500);
  // предупреждение о среде
  if (typeof ort === 'undefined') {
    $('#ortState').textContent = 'onnxruntime-web не загрузился: нет сети или открыто в предпросмотре без интернета.';
  }
})();
</script>
</body>
</html>
