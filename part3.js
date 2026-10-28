
/* ───────────────────────── 4. Правила (тот же файл, что у АПК) ───────────────────────── */
const DEFAULT_RULES = {
  version: 'web-1',
  inkLowPercentile: 0.02, inkHighPercentile: 0.98, inkFlatSpread: 10,
  inkCoefficient: 0.45, inkMin: 40, inkMax: 235, binarizeFallback: 110,
  inkTileRows: 4, inkLevels: 1,
  contrastGain: 2.2, contrastOffset: -140,
  rescueMinRegions: 600, pageSide: 1600, rescueSide: 960, minConfidence: 0.25,
  cutMargin: 0.06, bandOverlap: 0, bandsMax: 8, wholeThreshold: 0.72,
  bubbleGap: 0.45, mergeHeightRatio: 1.8,
  speechRate: 0, autoScrollStep: 0.25, semiManual: false, semiManualSettleMs: 700,
  detRetry: true,          // повтор детектора с ImageNet-нормой, только если боксов 0
  largeText: true,         // второй проход по трудному тексту (каллиграфия, крупный шрифт)
  decodeVariants: true,    // перебор всех подготовок кропа ради верных слов
  uncoveredPass: true,     // искать строки, которые детектор не закрыл боксом
  largeMinWidth: 0.22,     // уже — это не текстовый блок (звуковые эффекты узкие)
  decodeRetryBelow: 1,     // повторное распознавание бинаризациями: только если букв < 1
  speed: 'fast',           // Молния | Быстро | Обычно | Тщательно (см. SPEED_PRESETS)
  extCrop: 'light',        // расширять кроп строки: 'light' — дешёво, true — полный перебор
  breakWords: true,        // дочинивать отдельные слова по кропу
  pipeline: true,          // читать, не дожидаясь конца полосы (замер в part4.js)
  hardVariants: true,      // на трудных строках перебирать подготовки и второй распознаватель
  autoScan: false,         // распознавать САМО при открытии и прокрутке? по умолчанию нет
  junkRatio: 0.6,          // доля слов не из словаря, при которой строка — мусор
  wordFixes: {},
};
/**
 * Профили скорости. Замерено на настоящей странице (720×2960, полосы 412×800,
 * headless Chromium, страница целиком): Молния ≈ 4,4 с, Быстро ≈ 4,5 с,
 * Обычно ≈ 18 с, Тщательно ≈ 18 с. Разница между «Быстро» и «Обычно» — это
 * расширение кропа строки (extCrop) и дочинка слов (breakWords): 144 вызова
 * модели против 23 на ту же страницу. На проверенной странице текст одинаковый,
 * включая «будучи», поэтому по умолчанию они выключены, а включаются в
 * «Обычно»/«Тщательно» — для трудных страниц. Текст на этой странице у всех четырёх одинаковый,
 * включая «жизнь, будучи старшей». Медленные профили нужны для трудных
 * страниц (мелкий шрифт, бледная печать, размытый скан), а не «на всякий случай».
 * Прежнее поведение = «Обычно».
 */
const SPEED_PRESETS = {
  lightning: { pageSide: 960, detRetry: false, largeText: false, decodeVariants: false,
               uncoveredPass: false, decodeRetryBelow: 0, extCrop: false, breakWords: false,
               hardVariants: false },
  // «Быстро» — это и есть авто: самый дешёвый путь (extCrop 'light', без
  // перебора) для всего, включая каллиграфию. Второй проход по крупному
  // тексту пробовали включить и здесь — на титуле он дал дубль «жизнь, Оцачит
  // старшей сестрой тирана» и 14,4 с вместо 4,3 с (кропов 88 против 25),
  // то есть хуже и в шесть раз медленнее. Предел возможного для этого шрифта —
  // именно этот путь: текст верный («жизнь, будучи старшей сестрой тирана»).
  fast:      { pageSide: 1280, detRetry: true, largeText: false, decodeVariants: false,
               uncoveredPass: false, decodeRetryBelow: 1, extCrop: 'light', breakWords: false },
  normal:    { pageSide: 1600, detRetry: true, largeText: true, decodeVariants: true,
               uncoveredPass: true, decodeRetryBelow: 1, extCrop: true, breakWords: true },
  thorough:  { pageSide: 1920, detRetry: true, largeText: true, decodeVariants: true,
               uncoveredPass: true, decodeRetryBelow: 3, bandOverlap: 0.25,
               extCrop: true, breakWords: true },
};
const SPEED_NAMES = { lightning: 'Молния', fast: 'Быстро', normal: 'Обычно', thorough: 'Тщательно' };
const SPEED_APPROX = { lightning: '≈20 с', fast: '≈25 с', normal: '≈80 с', thorough: '≈70 с' };

let RULES = { ...DEFAULT_RULES };
function sanitizeRules(r) {
  const R = { ...DEFAULT_RULES, ...(r || {}) };
  // Профиль скорости главнее сохранённых чисел: иначе старые значения
  // (pageSide 1600 и т. п.) молча отменяли бы выбранный профиль.
  if (!SPEED_PRESETS[R.speed]) R.speed = DEFAULT_RULES.speed;
  Object.assign(R, SPEED_PRESETS[R.speed]);
  const num = (k, a, b) => { R[k] = clamp(Number(R[k]) || 0, a, b); };
  num('inkLowPercentile', 0, .5); num('inkHighPercentile', .5, 1); num('inkFlatSpread', 0, 128);
  num('inkCoefficient', 0, .95); num('inkMin', 0, 254); num('inkMax', 1, 255);
  num('binarizeFallback', 0, 255); num('inkTileRows', 1, 16); num('inkLevels', 1, 2);
  num('contrastGain', 1, 8); num('contrastOffset', -255, 100);
  num('rescueMinRegions', 0, 100000); num('pageSide', 320, 4000); num('rescueSide', 320, 4000);
  num('minConfidence', 0, 1); num('cutMargin', 0, .4); num('bandOverlap', 0, .5);
  num('bandsMax', 1, 32); num('wholeThreshold', .3, 1); num('bubbleGap', .05, 3);
  num('mergeHeightRatio', 1.05, 6); num('speechRate', 0, 3); num('autoScrollStep', .05, .9);
  num('semiManualSettleMs', 0, 5000);
  R.detRetry = R.detRetry !== false;                       // повтор детектора при 0 боксов
  R.largeText = R.largeText !== false;
  R.decodeVariants = R.decodeVariants !== false;
  R.uncoveredPass = R.uncoveredPass !== false;
  R.autoScan = R.autoScan === true;                        // по умолчанию НЕ само
  R.extCrop = R.extCrop === false ? false : (R.extCrop === true ? true : 'light');
  R.breakWords = R.breakWords !== false;
  R.pipeline = R.pipeline !== false;     // конвейер включён; [{pipeline:false}] выключает
  R.hardVariants = R.hardVariants !== false;
  num('largeMinWidth', 0.05, 0.6);
  num('decodeRetryBelow', 0, 6);                           // <N букв → пробуем бинаризации
  num('junkRatio', 0, 1);                                  // 0 — фильтр выключен
  if (R.inkMax <= R.inkMin) R.inkMax = Math.min(255, R.inkMin + 1);
  R.inkTileRows = Math.round(R.inkTileRows); R.bandsMax = Math.round(R.bandsMax);
  R.inkLevels = Math.round(R.inkLevels); R.semiManualSettleMs = Math.round(R.semiManualSettleMs);
  R.semiManual = !!R.semiManual;
  if (typeof R.wordFixes !== 'object' || !R.wordFixes) R.wordFixes = {};
  return R;
}

/* ───────────────────────── 4b. Починка текста (порт KomaText.kt) ─────────────────────────
   Модель регулярно пишет русские буквы латиницей, греческими заглавными и
   цифрами: «HETΛOXO», «3ВУ4ИТ», «MHE TAK». Без этой починки строка не проходила
   фильтр языка и пропадала из реплики целиком. */
const LOOKALIKES = {
  a: 'а', e: 'е', o: 'о', c: 'с', p: 'р', x: 'х', y: 'у', k: 'к', m: 'м', t: 'т',
  b: 'в', h: 'н', u: 'и', n: 'п',
  A: 'А', E: 'Е', O: 'О', C: 'С', P: 'Р', X: 'Х', Y: 'У', K: 'К', M: 'М', T: 'Т',
  B: 'В', H: 'Н', U: 'И',
  'Λ': 'Л', 'Δ': 'Д', 'Α': 'А', 'Β': 'В', 'Ε': 'Е', 'Ζ': 'З', 'Η': 'Н', 'Ι': 'И',
  'Κ': 'К', 'Μ': 'М', 'Ν': 'Н', 'Ο': 'О', 'Ρ': 'Р', 'Τ': 'Т', 'Υ': 'У', 'Χ': 'Х',
  '3': 'з', '4': 'ч', '0': 'о', '6': 'б', '8': 'в',
  'α': 'а', 'β': 'в', 'γ': 'г', 'δ': 'д', 'ε': 'е', 'ζ': 'з', 'η': 'н', 'ι': 'и',
  'κ': 'к', 'μ': 'м', 'ν': 'п', 'ο': 'о', 'π': 'п', 'ρ': 'р', 'σ': 'с', 'τ': 'т',
  'υ': 'у', 'χ': 'х',
  l: 'л', d: 'д', g: 'г', f: 'ф', r: 'г', s: 'с', v: 'в', w: 'ш', z: 'з', j: 'й', i: 'и',
  q: 'я',
};
const GREEK = new Set(['Λ', 'Δ', 'Α', 'Β', 'Ε', 'Ζ', 'Η', 'Ι', 'Κ', 'Μ', 'Ν', 'Ο', 'Ρ', 'Τ', 'Υ', 'Χ']);
const isRusLetter = (ch) => /^[а-яё]$/i.test(ch);

function fixLookalikes(raw) {
  const lineIsRussian = Array.from(raw).some(ch => isRusLetter(ch) || GREEK.has(ch));
  if (!lineIsRussian) return raw;
  return raw.split(' ').map(word => {
    const letters = Array.from(word).filter(ch => /[\p{L}\p{N}]/u.test(ch));
    const convertible = letters.length && letters.every(ch => ch in LOOKALIKES);
    const wordHasRussian = Array.from(word).some(isRusLetter);
    if (!(wordHasRussian || convertible)) return word;
    // Если в слове нет строчных букв, то и подстановка должна быть заглавной:
    // «3ВУ4ИТ» → «ЗВУЧИТ», а не «зВУчИТ».
    const hasLower = Array.from(word).some(ch => /[a-zа-я]/.test(ch));
    return Array.from(word).map(ch => {
      const m = LOOKALIKES[ch];
      if (m === undefined) return ch;
      return hasLower ? m : m.toUpperCase();
    }).join('');
  }).join(' ');
}

/** Строка состоит ТОЛЬКО из символов-двойников: «OHO», «4YBC», «MHE TAK». */
function isLookalikeOnly(text) {
  const letters = Array.from(text).filter(ch => /[\p{L}\p{N}]/u.test(ch));
  return letters.length > 0 && letters.every(ch => ch in LOOKALIKES);
}
/** Принудительный перевод всей строки, даже если русских букв в ней нет. */
function fixLookalikesForced(raw) {
  const chars = Array.from(raw);
  const upper = chars.filter(ch => /[A-ZА-Я]/.test(ch)).length > chars.filter(ch => /[a-zа-я]/.test(ch)).length;
  return chars.map(ch => {
    const m = LOOKALIKES[ch];
    if (m === undefined) return ch;
    return upper ? m.toUpperCase() : m;
  }).join('');
}

/** Текст для синтезатора: убрать переносы, двойников, склеить «в д а ль». */
function cleanSpeech(raw) {
  let text = String(raw || '')
    .replace(/(?<=\p{L})\s*-\s*(?=\p{L})/gu, '')
    .replace(/\s+/g, ' ')
    .trim();
  text = isLookalikeOnly(text) ? fixLookalikesForced(text) : fixLookalikes(text);
  for (let k = 0; k < 3; k++) {
    text = text.replace(/(?<!\p{L})\p{L}(\s+\p{L}){1,4}(?!\p{L})/gu, m => m.replace(/\s+/g, ''));
  }
  return text.trim();
}

/* ───────────────────────── 4c. Язык: словарь и фильтр мусора ─────────────────────────
   Порт идеи KomaWords.kt. Модель путает похожие буквы и «видит» слова в
   каллиграфии и звуковых эффектах: «ол кослл алмчлс», «сттангасоат». Без словаря
   такие строки попадают в озвучку как реплики. Словарь — `ru_250k.txt` из
   assets/koma/dict того же APK, 250 000 слов по убыванию частоты.
   Он НЕ вшит в файл: его выбирают в ⚙ Модели, как и модели.
*/
/**
 * Склеить перенос слова через дефис: «РАВНО-» + «ДУШНЫМ» → «РАВНОДУШНЫМ».
 *
 * В комиксах реплика часто разбита переносом, и «половинки» — не слова: словарь
 * выкидывал «РАВНО-» и правил «ДУШНЫМ» в «ДУРНЫМ» (одна буква разницы), после
 * чего реплика означала совсем другое. Склеиваем до всех проверок: и внутри
 * строки («РАВНО- ДУШНЫМ»), и между строками (перевод строки).
 * Тире диалога («— ПРИВЕТ») не трогаем: у него пробелы с двух сторон, а
 * перенос пишется слитно с концом слова. Регистр второй части не важен —
 * в комиксах реплики капсом: «РАВНО-» + «ДУШНЫМ».
 */
function joinHyphens(text) {
  return String(text)
    .replace(/(\p{L})-\s*\n\s*(?=\p{L})/gu, '$1')           // перенос строки
    .replace(/(\p{L})-\s+(?=\p{L})/gu, '$1');                // перенос внутри строки
}

const Words = {
  ready: false,
  rank: null,          // слово → номер строки (ранг частоты)
  size: 0,
  ordered: true,       // список по убыванию частоты (иначе — только членство)
  KNOWN_RANK: 50000,
  COMMON_RANK: 100000,
  ALPHABET: 'абвгдежзийклмнопрстуфхцчшщъыьэюяё'.split(''),
  source: '',
  async load() {
    // 1) Свой файл, если пользователь загрузил его кнопкой «Словарь ru_250k»
    //    (нужен, если вшитый не подошёл). 2) Иначе — вшитый в файл словарь.
    let text = '';
    const row = await DB.get('kv', 'dict:ru250k');
    if (row && row.v) { text = String(row.v); this.source = 'свой файл'; }
    else if (typeof DICT_GZ_B64 === 'string' && DICT_GZ_B64.length > 1000) {
      try {
        text = await embeddedDictText();
        this.source = 'вшит в файл';
      } catch (e) {
        console.warn('вшитый словарь не разжался:', e);
      }
    }
    if (!text) { this.ready = false; return false; }
    const lines = text.split('\n');
    const rank = new Map();
    let n = 0;
    for (const line of lines) {
      const w = line.split(/\s+/)[0];
      if (!w) continue;
      const low = w.toLowerCase();
      if (!rank.has(low)) rank.set(low, n);
      n++;
    }
    this.rank = rank; this.size = n; this.ready = n > 1000;
    // Частотный порядок — это не украшение: KNOWN_RANK/COMMON_RANK сравнивают
    // НОМЕР СТРОКИ. Если пользователь положит большой словарь, отсортированный
    // по алфавиту (а 3-миллионные списки почти всегда такие), то «первыми»
    // окажутся слова на «а», все остальные получат номер > 100 000 и весь
    // разбор решит, что речь состоит из несуществующих слов: на замере 27.10
    // читалка вернула НОЛЬ реплик на странице, которая до этого читалась.
    // Поэтому проверяем порядок и честно выключаем то, что на нём держится.
    this.ordered = this.looksOrdered(rank);
    if (!this.ordered) {
      this.source = (this.source || 'свой файл') + ', без частотного порядка';
    }
    return this.ready;
  },
  /**
   * Проверка, что словарь лежит по убыванию частоты: самые частые русские
   * слова должны стоять в начале. Дешёвая (12 поисков), делается один раз.
   */
  looksOrdered(rank) {
    // Большой список, отсортированный ПО АЛФАВИТУ, — главный признак беды:
    // тогда номер строки ничего не говорит о частоте. Маленькие списки
    // (свои, ручные, из тестов) не проверяем: там ранги и так почти все «частые».
    if (rank.size < 50000) return true;
    let prev = null, asc = 0, total = 0;
    for (const w of rank.keys()) {
      if (prev !== null) { total++; if (prev <= w) asc++; }
      prev = w;
      if (total >= 2000) break;
    }
    if (!total) return true;
    return asc / total < 0.95;      // почти всё по возрастанию → это алфавит
  },
  /** Слово верное, если оно из частых. Без частотного порядка — «есть вообще». */
  isKnown(w) {
    if (!this.ready) return true;
    const low = w.toLowerCase();
    if (this.ordered === false) return this.rank.has(low);
    const r = this.rank.get(low);
    return r !== undefined && r <= this.KNOWN_RANK;
  },
  /**
   * Слово вообще есть в словаре (даже редкое). Отдельно от isKnown: порог
   * «частого» (KNOWN_RANK) нужен для эвристик «доля знакомых слов», но НЕ для
   * правки. Иначе «равнодушным» (позиция 51 295) считалось неизвестным и
   * заменялось на «дурным» (одна буква разницы) — и реплика
   * «ЛУЧШЕ БЫТЬ БОЛЕЕ РАВНО-ДУШНЫМ» читалась как «…БОЛЕЕ ДУРНЫМ»,
   * то есть смысл менялся. Правим только то, чего в русском нет.
   */
  inDict(w) {
    if (!this.ready || !this.rank) return false;
    return this.rank.get(String(w).toLowerCase()) !== undefined;
  },
  /** Одно редактирование: удаление, перестановка, замена, вставка. */
  edits1(word) {
    const out = new Set();
    const chars = Array.from(word);
    for (let i = 0; i < chars.length; i++) {
      out.add(chars.slice(0, i).concat(chars.slice(i + 1)).join(''));
      if (i + 1 < chars.length) {
        const sw = chars.slice();
        [sw[i], sw[i + 1]] = [sw[i + 1], sw[i]];
        out.add(sw.join(''));
      }
      for (const c of this.ALPHABET) {
        out.add(chars.slice(0, i).concat([c], chars.slice(i + 1)).join(''));
        out.add(chars.slice(0, i).concat([c], chars.slice(i)).join(''));
      }
    }
    return out;
  },
  candidate(word) {
    // Без частотного порядка «похожее слово» выбрать нельзя: ближайшим окажется
    // случайное редкое. Тогда лучше не править вовсе, чем испортить смысл.
    if (this.ordered === false) return null;
    let best = null, bestRank = Infinity;
    for (const cand of this.edits1(word)) {
      const r = this.rank.get(cand);
      if (r !== undefined && r <= this.COMMON_RANK && r < bestRank) { bestRank = r; best = cand; }
    }
    return best;
  },
  /** Сохранить регистр исходного слова. */
  sameCase(src, word) {
    const letters = Array.from(src);
    const upper = letters.filter(ch => /[A-ZА-ЯЁ]/.test(ch)).length > letters.filter(ch => /[a-zа-яё]/.test(ch)).length;
    return upper ? word.toUpperCase() : (letters[0] && /[A-ZА-ЯЁ]/.test(letters[0]) ? word[0].toUpperCase() + word.slice(1) : word);
  },
  ENDINGS: ['ами', 'ями', 'ого', 'его', 'ому', 'ему', 'ыми', 'ими', 'ах', 'ях', 'ов', 'ев',
    'ой', 'ей', 'ий', 'ый', 'ая', 'ое', 'ые', 'ие', 'ом', 'ем', 'ам', 'ям', 'мь', 'ью',
    'ы', 'и', 'а', 'е', 'о', 'у', 'ю', 'ь', 'я', 'й', 'м'],
  /**
   * Слово выглядит настоящим: есть в словаре ИЛИ это его словоформа
   * (ВЫСОЧЕСТВОМ → ВЫСОЧЕСТВ + ОМ). Без этой проверки «правка» превращала
   * нормальное «ВЫСОЧЕСТВОМ» в «ВЫСОЧЕСТВО».
   */
  isPlausible(word) {
    if (!this.ready) return true;
    if (this.ordered === false) return this.inDict(word);
    const low = String(word).toLowerCase();
    if (this.isKnown(low)) return true;
    if (low.length < 5) return false;
    for (const end of this.ENDINGS) {
      if (!low.endsWith(end)) continue;
      const stem = low.slice(0, low.length - end.length);
      if (stem.length < 4) continue;
      if (this.rank.has(stem) && this.rank.get(stem) <= this.COMMON_RANK) return true;
    }
    return false;
  },
  correctWord(word) {
    if (!this.ready) return word;
    const low = word.toLowerCase();
    if (low.length < 4) return word;
    // Есть в словаре (пусть и редкое) — не трогаем: замена на «похожее
    // частотное» слово меняла смысл («равнодушным» → «дурным»).
    if (this.inDict(low)) return word;
    if (this.isKnown(low) || this.isPlausible(low)) return word;
    const cand = this.candidate(low);
    // Первую букву у короткого слова не трогаем: «ЖЕШЬ» → «ЕШЬ» — это уже
    // другое слово (со скриншота реплика «…МОЖЕШЬ ЗНАТЬ!» читалась «ЕШЬ
    // ЗНАТЬ!»). Длинные слова чиним как раньше: «оддучив» → «будучи».
    if (cand && cand[0] !== low[0] && low.length < 5) return word;
    if (cand) return this.sameCase(word, cand);
    // Два редактирования — но только к ОЧЕНЬ частым словам и не для КАПСА:
    // «оддучив» → «будучи» (OCR на рукописном шрифте), при этом имена вроде
    // «ДРЕГЕР» остаются как есть.
    if (this.FIX_DISTANCE >= 2 && low.length >= 5 && !/^[А-ЯЁ]+$/.test(word)) {
      const deep = this.candidate2(low);
      if (deep) return this.sameCase(word, deep);
    }
    return word;
  },
  // 2 включать нельзя: расстояние 2 превращает «Сесмой» в «Самой» — это хуже,
  // чем оставить слово как есть. Оставляем честное одно редактирование.
  FIX_DISTANCE: 1,
  /**
   * Кандидат на расстоянии 2 среди очень частых слов.
   *
   * Перебор «удалений от удалений» не годится: он не умеет менять буквы, а
   * именно это нужно для «оддучив» → «будучи». Поэтому сверяемся с индексом
   * 20 000 самых частых слов, сгруппированных по длине.
   */
  candidate2(word) {
    if (!this.rank) return null;
    const MAXR = 20000, MAXD = 2;
    const idx = this.topIndex(MAXR);
    const n = Array.from(word).length;
    let best = null, bestRank = Infinity;
    for (let len = n - MAXD; len <= n + MAXD; len++) {
      const bucket = idx.get(len);
      if (!bucket) continue;
      for (const [cand, r] of bucket) {
        if (r >= bestRank) continue;
        if (levenshtein(word, cand) <= MAXD) { bestRank = r; best = cand; }
      }
    }
    return best;
  },
  /** Индекс частых слов по длине — строится один раз. */
  topIndex(maxRank) {
    if (this._topIndex && this._topRank === maxRank) return this._topIndex;
    const idx = new Map();
    for (const [w, r] of this.rank) {
      if (r > maxRank || w.length < 4) continue;
      if (!idx.has(w.length)) idx.set(w.length, []);
      idx.get(w.length).push([w, r]);
    }
    this._topIndex = idx; this._topRank = maxRank;
    return idx;
  },
  /**
   * Длинное слово, которого нет в словаре и которое не правится одним
   * изменением, — это почти всегда звуковой эффект или каллиграфия внутри
   * реплики («сттангасоат», «риооооро»). Такие слова убираем из текста, но
   * только если в реплике есть другие настоящие слова: иначе останется пустота.
   * Порог 8 букв выбран, чтобы не тронуть имена («БЕРСЕРК», «ДРЕГЕР»).
   */
  stripJunkWords(text) {
    if (!this.ready) return text;
    const words = String(text).split(' ');
    const known = words.filter(w => /[А-Яа-яЁё]{2,}/.test(w) && this.isKnown(w));
    if (known.length < 1) return text;
    const kept = words.filter(w => {
      const low = w.toLowerCase().replace(/[^а-яё]/g, '');
      // Слово есть в словаре (пусть редкое и длинное) — это не звук.
      // Иначе «РАВНОДУШНЫМ» (11 букв, позиция 51 295) выбрасывалось правилом
      // «длинное и неизвестное = звук», и реплика теряла половину смысла.
      if (this.inDict(low)) return true;
      if (this.isKnown(low) || this.isPlausible(low)) return true;
      // «сттангасоат» (11 букв), «риооооро» (три «о» подряд) — звуки, а не слова.
      // Порог подобран так, чтобы имена («БЕРСЕРК», «ДРЕГЕР») остались.
      if (low.length >= 10) return false;
      if (/(.)\1\1/.test(low)) return false;
      if (low.length <= 2) return false;     // «оо», «чв» — не слова
      return true;
    });
    return kept.join(' ').replace(/\s{2,}/g, ' ').trim();
  },
  /** Починка реплики: слова по словарю + висячий дефис в конце. */
  finish(text, keepAll) {
    let t = joinHyphens(String(text || ''));
    if (this.ready) {
      t = t.replace(/[А-Яа-яЁё]+/g, w => this.correctWord(w));
      if (!keepAll) t = this.stripJunkWords(t);
    }
    return t.replace(/(?<=\p{L})-\s*$/u, '').trim();
  },
  /**
   * Доля «несуществующих» слов. По ней строка из каллиграфии и звуковых
   * эффектов отбрасывается: в настоящей реплике почти все слова есть в словаре.
   */
  junkRatio(text) {
    if (!this.ready) return 0;
    const words = (String(text).match(/[А-Яа-яЁё]{3,}/g) || []).map(w => w.toLowerCase());
    if (!words.length) return 1;
    let junk = 0;
    for (const w of words) {
      if (this.ordered === false) { if (!this.rank.has(w)) junk++; continue; }
      const r = this.rank.get(w);
      if (r === undefined || r > this.COMMON_RANK) junk++;
    }
    return junk / words.length;
  },
  /**
   * Починить и отбросить мусор.
   *
   * Считать «долю мусора» после правки нельзя: правка умеет превратить
   * «кослл» в редкое, но существующее «колл», и строка «ол кослл алмчлс»
   * проходила фильтр (доля 0.5 при пороге 0.6). Поэтому сначала смотрим на
   * ИСХОДНЫЙ текст:
   *   • есть настоящие слова   → чиним словарь и оставляем;
   *   • нет ни одного, слов 2+  → это каллиграфия/звук, отбрасываем;
   *   • нет ни одного, слово 1  → возможно, опечатка: оставляем, только если
   *     после правки получается слово из словаря.
   */
  polish(text, junkRatio, conf) {
    const raw = String(text || '');
    if (!this.ready) return this.finish(raw);
    const thr = junkRatio ?? 0.6;
    // {2,} а не {3,}: «Тг. чв» — тоже не реплика, а короткие настоящие слова
    // («не», «да», «ты», «он») в словаре есть и проверку проходят.
    // Латинская мелочь — это не реплика, а номер страницы или логотип:
    // «Tr. 48», «HD», «Tl.48». В репликах кириллица.
    const cyrCount = (raw.match(/[А-Яа-яЁё]/g) || []).length;
    const latCount = (raw.match(/[A-Za-z]/g) || []).length;
    if (cyrCount === 0 && latCount > 0 && latCount <= 5) return '';

    const words = (raw.match(/[А-Яа-яЁё]{2,}/g) || []).map(w => w.toLowerCase());
    if (!words.length) return this.finish(raw);
    const known = words.filter(w => this.isKnown(w));
    const knownLong = known.filter(w => w.length >= 3);
    let fixed = this.finish(raw);
    if (!fixed) return '';
    // Чистка не должна съедать половину реплики. Пример со скриншота:
    // «ГДЕ, ЧЁРТ ВОЗЬМИ, ТЫ БЫЛ ЧТО ТЫ МОЖЕШЬ ЗНАТЬ!» осталось как
    // «ЕШЬ ЗНАТЬ!» — слова не из словаря выбросились, и смысл пропал.
    // Если выброшено больше 40 % слов, оставляем реплику целиком (словарь
    // только чинит слова, но ничего не выкидывает).
    const before = (raw.match(/[А-Яа-яЁё]{2,}/g) || []).length;
    const after = (fixed.match(/[А-Яа-яЁё]{2,}/g) || []).length;
    if (before >= 3 && after < before * 0.6) {
      const kept = this.finish(raw, true);
      if (kept) fixed = kept;
    }
    if (knownLong.length >= 1) return fixed;                     // есть настоящие слова

    // Одна-две буквы — это реплика только если это настоящее короткое слово:
    // «НЕ», «ДА», «ТЫ», «Я». «АН», «АО», «ОИ» — шум от декора, а не реплика.
    const letters = cyrCount + latCount;
    if (letters <= 2) {
      const only = (raw.match(/[А-Яа-яЁёA-Za-z]+/g) || []).join('').toLowerCase();
      const shortOk = ['я', 'не', 'да', 'ты', 'он', 'мы', 'вы', 'но', 'ну', 'же',
        'ли', 'ах', 'ох', 'эх', 'эй', 'уй', 'ой', 'ай', 'ей', 'их', 'им', 'её', 'его'];
      if (!shortOk.includes(only)) return '';
    }
    // Строка из имён: 1-3 слова, каждое С НАЧАЛА с заглавной — оставляем
    // (БЕРСЕРК, ГРАФЬ). Раньше проверялось «где-то в слове есть заглавная»,
    // и мусор «сУалошвл» с заглавной в середине считался именем.
    const wordList = raw.split(/[^\p{L}]+/u).filter(Boolean);
    const capNames = wordList.filter(w => /^[А-ЯЁ][а-яё]{2,}$/.test(w));
    const wordsLong = raw.match(/[А-Яа-яЁё]{3,}/g) || [];
    if (capNames.length >= 1 && capNames.length === wordList.filter(w => w.length >= 3).length
        && capNames.length === wordsLong.length && capNames.length <= 3) return fixed;
    // Имя или крик капсом, которого нет в словаре: «БЕРСЕРК», «НЕ СМЕЙ».
    // Но не «АААААА» и не «СОООООИТ»: тройной повтор буквы — это звук, а не имя.
    const caps = (raw.match(/[А-ЯЁ]{3,}/g) || []).filter(w => !/(.)\1\1/.test(w.toLowerCase()));
    const capsAll = raw.match(/[А-ЯЁ]{3,}/g) || [];
    if (caps.length >= 1 && caps.length === capsAll.length
        && caps.length === wordsLong.length && caps.length <= 4) return fixed;

    // ДЛИННЫЙ текст (абзац книги, журнала, старого скана) — отдельное правило.
    // Замер 28.10 на «Весёлых картинках» 1988: распознавание нашло 100 строк,
    // из них 87 русских, а в реплики вышло 10 — остальное выбрасывалось именно
    // здесь, потому что в слитом абзаце на 100+ слов неизбежно 10–20 % ошибок,
    // и доля «настоящих» падала ниже 0.5. Терять целый абзац из-за этого нельзя:
    // это ровно то «верные строки не трогать», только наоборот.
    // Опора — не доля, а число настоящих слов: если их хотя бы 4 и строка не
    // короче 12 слов, это текст, а мусорные строки такими не бывают (у мусора
    // из «ол кослл алмчлс» максимум 2–3 слова).
    if (words.length >= 12 && known.length >= 4) return fixed;

    // Длинная строка, где настоящих слов меньшинство, — это не реплика:
    // «то н оо о оно», «ол кослл алмчлс».
    if (words.length >= 3) {
      const knownRatio = known.length / words.length;
      if (knownRatio < 0.5) return '';
    }
    // Одна-две слова — реплика только если ВСЕ они настоящие: «да, это»,
    // «не сейчас». Иначе «ТА. ЧВ» (где «та» — слово, а «чв» — нет) считалось
    // репликой.
    if (known.length >= 1 && known.length === words.length && words.length <= 2) return fixed;
    return '';
  },
};

/* ───────────────────────── 5. OCR: модели в браузере ───────────────────────── */
const OCR = {
  det: null, rec: null, dict: null, ready: false,
  // Честное состояние движка. Раньше интерфейс писал «движок загружен,
  // моделей нет» даже когда все три модели лежали на месте, — потому что
  // флага было всего два. Теперь видно, на каком шаге и почему всё встало.
  engine: 'idle',        // idle | loading | ready | blocked | failed
  reason: '',
  hasFiles() { return !!(this.pendingDet && this.pendingRec && this.pendingDict); },
  /**
   * Совпадает ли азбука второго распознавателя с нашим словарём.
   * Гоняем пустой (белый) тензор и смотрим число классов: у CTC оно равно
   * «символы словаря + blank». Если не совпало — декодировать нечем.
   */
  async checkRec2Alphabet(sess) {
    try {
      const w = 320, h = 48;
      const data = new Float32Array(3 * h * w).fill(-1);       // белое поле
      const t = new ort.Tensor('float32', data, [1, 3, h, w]);
      const out = await runModel(sess, { [sess.inputNames[0]]: t }, 'проверка второго распознавателя');
      const C = out && out.dims ? out.dims[2] : 0;
      const want = (OCR.dict ? OCR.dict.length : 0) + 1;
      return C === want;
    } catch (e) { return false; }
  },

  async loadModels() {
    const det = await DB.get('kv', 'model:det');
    const rec = await DB.get('kv', 'model:rec');
    const dict = await DB.get('kv', 'model:dict');
    this.pendingDet = !!det; this.pendingRec = !!rec; this.pendingDict = !!dict;
    if (!det || !rec || !dict) {
      this.ready = false; this.engine = 'idle';
      this.reason = 'моделей нет';
      return false;
    }
    if (typeof ort === 'undefined') {
      this.ready = false; this.engine = 'failed';
      this.reason = 'onnxruntime-web не загрузился: нужна сеть при первом открытии';
      return false;
    }
    this.engine = 'loading'; this.reason = '';
    ort.env.wasm.numThreads = 1;                 // без COOP/COEP потоки не нужны
    ort.env.wasm.simd = true;
    ort.env.logLevel = 'error';
    try {
      // Движок работает на вшитых в файл бинарях: сеть не нужна вообще.
      await installOrtWasm();
      this.det = await ort.InferenceSession.create(det.v, { executionProviders: ['wasm'] });
      this.rec = await ort.InferenceSession.create(rec.v, { executionProviders: ['wasm'] });
      // Второй распознаватель — по желанию: «субагент» для трудных строк.
      // Требование одно: та же азбука (те же символы в том же порядке, что в
      // словаре), иначе его выход нельзя декодировать нашим словарём — тогда
      // честно говорим и не подсовываем его в работу.
      this.rec2 = null; this.rec2Note = ''; this.rec2Kind = null; this.rec2Charset = '';
      const rec2 = await DB.get('kv', 'model:rec2');
      if (rec2) {
        try {
          const sess = await ort.InferenceSession.create(rec2.v, { executionProviders: ['wasm'] });
          const cs = await DB.get('kv', 'model:rec2charset');
          if (cs && cs.v) {
            // «Линейная» модель из набора чтеца шрифтов: у неё своя азбука
            // (файл charset.txt), и читается она своим адаптером.
            this.rec2 = sess; this.rec2Kind = 'line32';
            this.rec2Charset = String(cs.v).replace(/\r?\n+$/, '');
            this.rec2Note = 'линейный распознаватель (' + this.rec2Charset.length + ' символов)';
          } else if (await this.checkRec2Alphabet(sess)) {
            this.rec2 = sess; this.rec2Kind = 'dict519';
            this.rec2Note = 'второй распознаватель подключён';
          } else {
            this.rec2Note = 'азбука не совпадает со словарём — не подключён';
          }
        } catch (e) {
          this.rec2Note = 'не загрузился: ' + String((e && e.message) || e).slice(0, 120);
        }
      }
    } catch (e) {
      this.ready = false;
      const msg = String((e && e.message) || e);
      // Песочница/строгий CSP запрещают WebAssembly.instantiate — это среда,
      // а не файл: на устройстве в Chrome тот же файл работает.
      const csp = /unsafe-eval|WebAssembly|CompileError|no available backend/i.test(msg);
      this.engine = csp ? 'blocked' : 'failed';
      this.reason = csp
        ? 'WebAssembly запрещён политикой безопасности этой страницы (предпросмотр). '
          + 'Скачайте файл и откройте в Chrome — там WASM разрешён.'
        : msg.slice(0, 300);
      return false;
    }
    const lines = String(dict.v).split('\n');
    while (lines.length && lines[lines.length - 1] === '') lines.pop();
    // Ровно как в KomaOcrEngine: blank(0) + символы словаря + пробел.
    this.dict = [''].concat(lines).concat([' ']);
    this.ready = true; this.engine = 'ready'; this.reason = '';
    this.stamp = (this.stamp || 0) + 1;      // см. _textCache: кэш живёт до смены модели
    return true;
  },
  /** Короткая строка для интерфейса. */
  statusText() {
    if (this.engine === 'ready') return 'движок готов';
    if (this.engine === 'loading') return 'движок загружается…';
    if (this.engine === 'blocked') return 'модели есть, но WASM заблокирован этой страницей';
    if (this.engine === 'failed') return 'модели есть, движок не поднялся';
    return this.hasFiles() ? 'модели есть, движок не запускался' : 'моделей нет';
  },
};

/* ── порог «чернил»: перцентили 2%/98% и коэффициент (KomaOcrEngine.inkThreshold) ── */
function inkThreshold(luma, R) {
  if (!luma.length) return -1;
  const hist = new Uint32Array(256);
  for (let i = 0; i < luma.length; i++) hist[luma[i] | 0]++;
  const pct = (p) => {
    const target = Math.max(1, Math.floor(luma.length * p));
    let acc = 0;
    for (let i = 0; i < 256; i++) { acc += hist[i]; if (acc >= target) return i; }
    return 255;
  };
  const low = pct(R.inkLowPercentile), high = pct(R.inkHighPercentile);
  if (high - low < R.inkFlatSpread) return -1;
  return clamp(Math.round(low + (high - low) * R.inkCoefficient), R.inkMin, R.inkMax);
}
/* ── второй уровень «чернил»: серый горб между фоном и тёмным текстом ── */
function greyInkRange(luma, R) {
  if (luma.length < 64) return null;
  const hist = new Uint32Array(256);
  for (let i = 0; i < luma.length; i++) hist[luma[i] | 0]++;
  const pct = (p) => {
    const target = Math.max(1, Math.floor(luma.length * p));
    let acc = 0;
    for (let i = 0; i < 256; i++) { acc += hist[i]; if (acc >= target) return i; }
    return 255;
  };
  const low = pct(R.inkLowPercentile), high = pct(R.inkHighPercentile);
  const spread = high - low;
  if (spread < 24) return null;
  const from = clamp(Math.floor(low + spread * 0.25), 0, 255);
  const to = clamp(Math.floor(low + spread * 0.80), 0, 255);
  let bestBin = -1, bestMass = 0;
  for (let i = from; i <= to; i++) {
    const mass = hist[Math.max(0, i - 1)] + hist[i] + hist[Math.min(255, i + 1)];
    if (mass > bestMass) { bestMass = mass; bestBin = i; }
  }
  if (bestBin < 0 || bestMass < Math.max(3, Math.floor(luma.length / 500))) return null;
  const lo = Math.max(low + 1, Math.floor(bestBin - spread * 0.10));
  const hi = Math.min(high - 1, Math.floor(bestBin + spread * 0.18));
  if (hi <= lo) return null;
  return [lo, hi];
}

/* ── холст ── */
function makeCanvas(w, h) {
  const c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h));
  return c;
}
function canvasFromImage(img) {
  const c = makeCanvas(img.naturalWidth || img.width, img.naturalHeight || img.height);
  c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
  return c;
}
function lumaFrom(data, w, h) {
  const out = new Uint8Array(w * h);
  for (let i = 0, p = 0; i < out.length; i++, p += 4) {
    out[i] = (data[p] * 77 + data[p + 1] * 151 + data[p + 2] * 28) >> 8;
  }
  return out;
}

/* ── достать тензор из результата run() (объект, Map, или по порядку) ──
   session.run() возвращает Promise, а внутри — либо простой объект, либо Map,
   в зависимости от версии. Раньше здесь читался out[name].data сразу, и на
   телефоне это давало «Cannot read properties of undefined (reading 'data')»:
   run() в браузере асинхронный, а мои Node-заглушки были синхронными. */
async function runModel(session, feeds, what) {
  const res = await session.run(feeds);
  const names = session.outputNames || [];
  if (res && typeof res.get === 'function') {
    if (names.length && res.get(names[0])) return res.get(names[0]);
    const first = res.values().next();
    return first.done ? null : first.value;
  }
  if (names.length && res[names[0]]) return res[names[0]];
  const vals = Object.keys(res || {}).map(k => res[k]);
  if (!vals.length) throw new Error((what || 'модель') + ' не вернула выходов');
  return vals[0];
}

/* ── детектор: боксы текстовых блоков (KomaOcrEngine.detectTile) ── */
async function detectBoxes(imgCanvas, side, R) {
  const { width: w0, height: h0 } = imgCanvas;
  const ratio = Math.min(1, side / Math.max(w0, h0));
  const w = Math.max(32, Math.round((w0 * ratio) / 32) * 32);
  const h = Math.max(32, Math.round((h0 * ratio) / 32) * 32);
  const c = makeCanvas(w, h);
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(imgCanvas, 0, 0, w, h);
  const px = ctx.getImageData(0, 0, w, h).data;
  const run = async (normalize) => {
    const data = new Float32Array(3 * w * h);
    const mean = [0.485, 0.456, 0.406], std = [0.229, 0.224, 0.225];
    for (let ch = 0; ch < 3; ch++) {
      const off = ch * w * h;
      for (let i = 0; i < w * h; i++) {
        const v = px[i * 4 + ch] / 255;
        data[off + i] = normalize ? (v - mean[ch]) / std[ch] : v;
      }
    }
    const t = new ort.Tensor('float32', data, [1, 3, h, w]);
    const name = OCR.det.inputNames[0];
    const tensor = await runModel(OCR.det, { [name]: t }, 'детектор');
    return components(tensor.data, h, w);           // карта [1,1,h,w]
  };
  let boxes = await run(false);
  let pass = 'normal';
  if (!boxes.length && (!R || R.detRetry !== false)) { boxes = await run(true); pass = 'imagenet'; }
  const out = boxes.slice(0, 400).map(b => ({
    left: clamp(Math.round((b[0] / w) * w0), 0, w0 - 1),
    top: clamp(Math.round((b[1] / h) * h0), 0, h0 - 1),
    right: clamp(Math.round((b[2] / w) * w0), 1, w0),
    bottom: clamp(Math.round((b[3] / h) * h0), 1, h0),
  })).filter(b => b.right > b.left && b.bottom > b.top);
  // Какая подготовка кадра дала боксы — видно в отчёте шторки.
  out.pass = pass;
  return out;
}
/* ── компоненты карты вероятностей (тот же BFS, порог 0.3) ── */
function components(map, h, w) {
  const visited = new Uint8Array(w * h);
  const queue = new Int32Array(w * h);
  const boxes = [];
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const idx = y * w + x;
      if (visited[idx] || map[idx] < 0.3) continue;
      let start = 0, end = 1; queue[0] = idx; visited[idx] = 1;
      let minX = x, maxX = x, minY = y, maxY = y, score = 0;
      while (start < end) {
        const n = queue[start++]; const xx = n % w, yy = (n - xx) / w;
        score += map[n];
        if (xx < minX) minX = xx; if (xx > maxX) maxX = xx;
        if (yy < minY) minY = yy; if (yy > maxY) maxY = yy;
        const nb = [xx > 0 ? n - 1 : -1, xx < w - 1 ? n + 1 : -1, yy > 0 ? n - w : -1, yy < h - 1 ? n + w : -1];
        for (const ni of nb) {
          if (ni >= 0 && !visited[ni] && map[ni] > 0.3) { visited[ni] = 1; queue[end++] = ni; }
        }
      }
      if (end < 6 || score / end < 0.5 || maxX - minX < 2 || maxY - minY < 2) continue;
      const expand = Math.max(2, Math.round(((maxX - minX) * (maxY - minY) * 1.5) / (2 * (maxX - minX + maxY - minY + 1))));
      boxes.push([Math.max(0, minX - expand), Math.max(0, minY - expand),
        Math.min(w, maxX + expand + 1), Math.min(h, maxY + expand + 1)]);
    }
  }
  return boxes.sort((a, b) => a[1] - b[1]);
}

/* ── нарезка бокса на строки по профилю «чернил» (KomaOcrEngine.textLines) ── */
function textLines(imgCanvas, box, R) {
  const pad = Math.max(2, Math.floor((box.bottom - box.top) * 0.12));
  const left = Math.max(0, box.left - pad), right = Math.min(imgCanvas.width, box.right + pad);
  const top = Math.max(0, box.top - pad), bottom = Math.min(imgCanvas.height, box.bottom + pad);
  if (right - left < 4 || bottom - top < 4) return [];
  const scale = Math.min(1, 400 / (right - left));
  const w = Math.max(4, Math.round((right - left) * scale));
  const h = Math.max(4, Math.round((bottom - top) * scale));
  const c = makeCanvas(w, h);
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(imgCanvas, left, top, right - left, bottom - top, 0, 0, w, h);
  const data = ctx.getImageData(0, 0, w, h).data;
  const luma = lumaFrom(data, w, h);
  if (inkThreshold(luma, R) < 0) return [];

  // подблочные пороги: несколько шрифтов в одном боксе
  const rows = clamp(Math.round(R.inkTileRows), 1, 16);
  const tileH = Math.max(1, Math.ceil(h / rows));
  const thr = new Array(rows);
  for (let i = 0; i < rows; i++) {
    const y0 = i * tileH, y1 = Math.min(h, y0 + tileH);
    thr[i] = y1 <= y0 ? -1 : inkThreshold(luma.subarray(y0 * w, y1 * w), R);
  }
  const grey = R.inkLevels >= 2 ? greyInkRange(luma, R) : null;
  const thrAt = (y) => thr[clamp(Math.floor(y / tileH), 0, rows - 1)];
  const isInk = (y, x) => {
    const l = luma[y * w + x];
    if (l < thrAt(y)) return true;
    return !!grey && l >= grey[0] && l <= grey[1];
  };
  const need = Math.max(1, Math.floor(w / 60));
  const rowHasInk = (y) => {
    let cnt = 0;
    for (let x = 0; x < w; x++) if (isInk(y, x)) { if (++cnt >= need) return true; }
    return false;
  };
  const runs = [];
  let y = 0;
  while (y < h) {
    if (!rowHasInk(y)) { y++; continue; }
    let end = y;
    while (end < h && rowHasInk(end)) end++;
    if (end > y) runs.push([y, end]);
    y = Math.max(end, y + 1);
  }
  if (!runs.length) return [];
  const heights = runs.map(r => r[1] - r[0]).sort((a, b) => a - b);
  const median = Math.max(1, heights[heights.length >> 1]);
  const merged = [];
  for (const r of runs) {
    const last = merged[merged.length - 1];
    if (last && r[0] - last[1] <= Math.max(1, Math.floor(median * 0.35))) last[1] = r[1];
    else merged.push([r[0], r[1]]);
  }
  const lines = [];
  for (const r of merged) {
    if (r[1] - r[0] < Math.max(2, Math.floor(median * 0.4))) continue;
    let x0 = w, x1 = -1;
    for (let yy = r[0]; yy < r[1]; yy++) for (let xx = 0; xx < w; xx++) {
      if (isInk(yy, xx)) { if (xx < x0) x0 = xx; if (xx > x1) x1 = xx; }
    }
    if (x1 < 0) continue;
    lines.push({
      left: clamp(Math.round(left + x0 / scale), left, right - 1),
      top: clamp(Math.round(top + r[0] / scale), top, bottom - 1),
      right: clamp(Math.round(left + (x1 + 1) / scale), left + 1, right),
      bottom: clamp(Math.round(top + (r[1] + 1) / scale), top + 1, bottom),
    });
  }
  return lines;
}

/* ── распознавание кропа (KomaOcrEngine.decode) ── */
/**
 * Прогнать кроп через распознаватель и отдать его выход как есть
 * ({T, C, p}) — вероятности по кадрам. Нужно для собственного декодера:
 * жадный разбор берёт только argmax, а поиск по словарю смотрит на все
 * классы кадра.
 */
/**
 * Кэш выхода модели на один кроп. Жадный разбор и свой декодер смотрят ОДИН
 * и тот же выход модели, и второй раз гонять распознаватель незачем: на
 * замере 27.10 это была самая дорогая часть перебора (+90–150 мс на строку).
 * Ключ — сам объект canvas, поэтому наклон (новый canvas) кэш не путает.
 */
let _probsCache = { canvas: null, res: null };
/**
 * Кэш «кроп → текст». Полосы чтения перекрываются (запас bandOverlap), поэтому
 * одна и та же строка попадает в две полосы и читается дважды — а это 78 мс на
 * вызов модели. Ключ — отпечаток самих пикселей (дешёвая выборка, ~0,3 мс) и
 * настройки, влияющие на чтение. При смене модели кэш забывается (OCR.stamp).
 */
const _textCache = new Map();
const TEXT_CACHE_MAX = 128;
function _cropKey(cv, wide, R) {
  // Отпечаток берём с МАЛЕНЬКОЙ копии (8×8): getImageData по всему кропу стоил
  // дороже самого чтения (замер: 5,4 с → 18,1 с на страницу), а 64 пикселя —
  // доли миллисекунды и достаточно, чтобы отличить строку от строки.
  let h = 2166136261 >>> 0;
  try {
    const thumb = makeCanvas(8, 8);
    const tg = thumb.getContext('2d', { willReadFrequently: true });
    tg.imageSmoothingEnabled = true; tg.imageSmoothingQuality = 'low';
    tg.drawImage(cv, 0, 0, 8, 8);
    const d = tg.getImageData(0, 0, 8, 8).data;
    for (let i = 0; i < d.length; i += 4) { h ^= d[i]; h = Math.imul(h, 16777619) >>> 0; }
  } catch (e) { return null; }
  return h + ':' + cv.width + 'x' + cv.height + ':' + (wide ? 1 : 0) +
    ':' + (R.extCrop === false ? 0 : (R.extCrop === 'light' ? 1 : 2)) +
    ':' + (R.decodeVariants === false ? 0 : 1) + ':' + (OCR.stamp || 0);
}
let _textHits = 0, _textMiss = 0;
function textCacheGet(key) {
  if (!key || !_textCache.has(key)) { if (key) _textMiss++; return null; }
  _textHits++;
  const v = _textCache.get(key);
  _textCache.delete(key); _textCache.set(key, v);      // освежаем порядок (LRU)
  return v;
}
function textCachePut(key, val) {
  if (!key) return;
  _textCache.set(key, val);
  if (_textCache.size > TEXT_CACHE_MAX) _textCache.delete(_textCache.keys().next().value);
}
async function recProbs(cropCanvas, sess) {
  const model = sess || OCR.rec;
  if (!model) return null;
  if (!sess && _probsCache.canvas === cropCanvas && _probsCache.res) return _probsCache.res;
  let w0 = cropCanvas.width, h0 = cropCanvas.height;
  if (w0 < 2 || h0 < 2) return null;
  let src = cropCanvas;
  if (h0 > w0 * 1.8) {                    // как в paddlePage: вертикальный кроп поворачиваем
    const rot = makeCanvas(h0, w0);
    const rc = rot.getContext('2d', { willReadFrequently: true });
    rc.translate(rot.width / 2, rot.height / 2); rc.rotate(Math.PI / 2);
    rc.drawImage(cropCanvas, -w0 / 2, -h0 / 2);
    src = rot; w0 = rot.width; h0 = rot.height;
  }
  const width = clamp(Math.round((48 * w0) / h0), 8, 960);
  const padded = Math.max(320, width);
  const c = makeCanvas(padded, 48);
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(src, 0, 0, width, 48);
  const px = ctx.getImageData(0, 0, width, 48).data;
  const norm = (ch) => px[0]; void norm;
  const data = new Float32Array(3 * 48 * padded);
  for (let ch = 0; ch < 3; ch++) {
    const off = ch * 48 * padded;
    for (let y = 0; y < 48; y++) for (let x = 0; x < width; x++) {
      data[off + y * padded + x] = ((px[(y * width + x) * 4 + ch] / 255) - 0.5) / 0.5;
    }
  }
  const t = new ort.Tensor('float32', data, [1, 3, 48, padded]);
  const logits = await runModel(model, { [model.inputNames[0]]: t }, 'распознавание');
  const T = logits.dims[1], C = logits.dims[2], values = logits.data;   // [1,T,519]
  const out = { T, C, p: values, width, padded };
  if (!sess) _probsCache = { canvas: cropCanvas, res: out };
  return out;
}

/** Жадный разбор выхода: самый вероятный класс на кадр (как было раньше). */
async function decodeCrop(cropCanvas, sess) {
  const res = await recProbs(cropCanvas, sess);
  if (!res) return ['', 0];
  const { T, C, p: values } = res;
  let text = '', prev = 0, score = 0, count = 0;
  for (let ti = 0; ti < T; ti++) {
    const base = ti * C;
    let best = 0, bestV = values[base];
    for (let ci = 1; ci < C; ci++) { const v = values[base + ci]; if (v > bestV) { bestV = v; best = ci; } }
    if (best !== 0 && best !== prev) {
      text += OCR.dict[best] ?? '';
      score += bestV; count++;
    }
    prev = best;
  }
  await yieldUI();          // отдать кадр браузеру: бейдж и ввод не замирают
  return [text, count ? score / count : 0];
}
/**
 * Наклон строки (shear). Замер 27.10 на облачке-крике: буквы там наклонены,
 * и модель читает их хуже. Если сдвинуть строку так, чтобы штрихи стали
 * вертикальными, восстанавливаются именно потерянные буквы:
 *   tan −0,2: «ТЫБЫЧТО ТМО» → «ТЫ БЫЛ ЧТ ТЫМО»   (появилось «БЫЛ»)
 *   tan −0,3: «ТАЕ ЧЕРТ ВОЗЫМИ» → «…ВОЗЬМИ»     (исправилось «ВОЗЫМИ»)
 *   tan +0,2: «ПΛОХ?» → «ПЛОХ?»                  (латинская Λ стала Л)
 * На ровных строках наклон только портит («ЛУЧШЕБbТЬ»), поэтому он не
 * заменяет чтение, а идёт отдельным вариантом в перебор трудных строк.
 */
function shearCanvas(src, tan) {
  const w = src.width, h = src.height;
  const extra = Math.ceil(Math.abs(tan) * h) + 1;
  const out = makeCanvas(w + extra, h);
  const g = out.getContext('2d', { willReadFrequently: true });
  g.fillStyle = '#fff'; g.fillRect(0, 0, out.width, out.height);
  g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
  // Сдвигаем построчно — так это работает и на настоящем canvas, и в тестах
  // (мини-canvas не умеет transform, и раньше наклон падал на g.save()).
  const base = tan > 0 ? extra : 0;
  for (let y = 0; y < h; y++) {
    const dx = base + Math.round(-tan * y);
    g.drawImage(src, 0, y, w, 1, dx, y, w, 1);
  }
  return out;
}

/**
 * СВОЙ ОЦЕНЩИК НАКЛОНА. Классика: если строку сдвинуть так, чтобы штрихи
 * букв стали вертикальными, столбцы «чернил» становятся резкими, и сумма
 * квадратов их высот растёт. Считаем по уменьшенной копии (высота 24 px),
 * поэтому стоит меньше 2 мс — вместо двух слепых прогонов модели по 90 мс.
 * Замер 27.10: на наклонной строке-крике находит −0,25…−0,30, на ровной — 0.
 */
function estimateSlant(crop, R) {
  const h = Math.min(24, crop.height), w = Math.max(8, Math.min(320, Math.round(crop.width * h / Math.max(1, crop.height))));
  if (w < 16 || h < 8) return 0;
  const small = makeCanvas(w, h);
  const g = small.getContext('2d', { willReadFrequently: true });
  g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
  g.drawImage(crop, 0, 0, w, h);
  const px = g.getImageData(0, 0, w, h).data;
  const ink = new Uint8Array(w * h);
  const thr = (R && R.binThreshold) || 128;
  for (let i = 0; i < w * h; i++) {
    const l = 0.299 * px[i * 4] + 0.587 * px[i * 4 + 1] + 0.114 * px[i * 4 + 2];
    ink[i] = l < thr ? 1 : 0;
  }
  const extra = Math.ceil(0.4 * h) + 1;
  const sums = new Float64Array(w + 2 * extra);
  let bestTan = 0, bestScore = -1;
  for (let tan = -0.35; tan <= 0.351; tan += 0.05) {
    sums.fill(0);
    for (let y = 0; y < h; y++) {
      const dx = extra + Math.round(-tan * y);
      const row = y * w;
      for (let x = 0; x < w; x++) if (ink[row + x]) sums[x + dx]++;
    }
    let score = 0;
    for (let i = 0; i < sums.length; i++) score += sums[i] * sums[i];
    if (score > bestScore) { bestScore = score; bestTan = tan; }
  }
  return Math.round(bestTan * 100) / 100;
}

/**
 * Словарь для декодера: слова БЕЗ регистра, по алфавиту — чтобы за один
 * двоичный поиск отвечать «есть ли слово, начинающееся с этих букв».
 * Строится один раз и только когда понадобился трудный разбор, поэтому на
 * обычных страницах не тратится ни времени, ни памяти.
 */
function decoderWords() {
  if (OCR._decWords !== undefined) return OCR._decWords;
  if (!Words.ready || !Words.rank) { OCR._decWords = null; return null; }
  const arr = [];
  for (const w of Words.rank.keys()) {
    let u = '';
    for (const ch of w) {
      const c = ch.toUpperCase();
      if ((c >= 'А' && c <= 'Я') || c === 'Ё') u += c;
    }
    if (u) arr.push(u);
  }
  arr.sort();
  OCR._decWords = arr;
  return arr;
}
/** Есть ли в словаре слово, начинающееся с u (двоичный поиск по алфавиту). */
function isWordPrefix(u, arr) {
  let lo = 0, hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    const w = arr[mid];
    if (w < u) lo = mid + 1;
    else if (!w.startsWith(u)) hi = mid;
    else return true;
  }
  return false;
}

/**
 * СВОЙ ДЕКОДЕР: поиск лучшей строки, а не жадный разбор.
 *
 * Жадный разбор берёт самый вероятный класс на каждом кадре и потом склеивает
 * повторы. Он не умеет ни «додумать» букву по словарю, ни отказаться от
 * мусорной вставки. Здесь — CTC-поиск по нескольким вариантам (beam search):
 * держим 10 лучших гипотез, и к вероятности кадров добавляем подсказку словаря:
 *   • буква продолжает слово из словаря .... +1,2
 *   • буква делает слово невозможным ..... −0,7
 *   • пробел после слова из словаря ....... +бонус по частоте слова
 * Пробел сразу после пробела и пустое слово не допускаются.
 *
 * Вес: ноль новых мегабайт — берётся уже вшитый словарь.
 * Замер на облачках 27.10 (CER, меньше — лучше):
 *   b1  0 % → 0 %     b2  0 % → 0 %
 *   b3  5,9 % → 2,9 % («УЖЕ», «НЕДОСТАТОЧНО», «ПЛОХ?» вместо «УЖІ», «НЕДОСТАТОЧНС», «ПΛОХ?»)
 *   b4 14,7 % → 14,7 % (шрифт слишком далёк от обучающего)
 */
function _beamLogsumexp(a, b) {
  if (a === -Infinity) return b;
  if (b === -Infinity) return a;
  const m = a > b ? a : b;
  return m + Math.log(Math.exp(a - m) + Math.exp(b - m));
}
function beamDecode(res, opts) {
  const { T, C, p } = res;
  const o = opts || {};
  const BEAM = o.beam || 10, TOPK = o.topk || 8;
  const BONUS = o.bonus ?? 1.2, PEN = o.pen ?? 0.7, WORD_W = o.wordW ?? 1.6;
  const dict = OCR.dict, words = decoderWords();
  const LN = (x) => (x > 1e-9 ? Math.log(x) : -20.72);
  const topC = new Int32Array(TOPK + 1), topV = new Float32Array(TOPK + 1);
  let beams = new Map([['', [0, -Infinity]]]);
  for (let ti = 0; ti < T; ti++) {
    const row = ti * C;
    // частичный отбор TOPK+1 самых вероятных классов кадра
    let n = 0;
    for (let c = 0; c < C; c++) {
      const v = p[row + c];
      if (n < TOPK + 1) {
        topC[n] = c; topV[n] = v;
        let i = n++;
        while (i > 0 && topV[i] > topV[i - 1]) {
          const tv = topV[i]; topV[i] = topV[i - 1]; topV[i - 1] = tv;
          const tc = topC[i]; topC[i] = topC[i - 1]; topC[i - 1] = tc; i--;
        }
      } else if (v > topV[TOPK]) {
        topC[TOPK] = c; topV[TOPK] = v;
        let i = TOPK;
        while (i > 0 && topV[i] > topV[i - 1]) {
          const tv = topV[i]; topV[i] = topV[i - 1]; topV[i - 1] = tv;
          const tc = topC[i]; topC[i] = topC[i - 1]; topC[i - 1] = tc; i--;
        }
      }
    }
    const next = new Map();
    const put = (pref, pb, pnb) => {
      const cur = next.get(pref);
      if (!cur) { next.set(pref, [pb, pnb]); return; }
      cur[0] = _beamLogsumexp(cur[0], pb);
      cur[1] = _beamLogsumexp(cur[1], pnb);
    };
    for (const [pref, sc] of beams) {
      const tot = _beamLogsumexp(sc[0], sc[1]);
      put(pref, tot + LN(p[row]), -Infinity);            // blank (класс 0)
      const lastCh = pref ? pref[pref.length - 1] : '';
      const sp = pref.lastIndexOf(' ');
      const word = pref.slice(sp + 1);
      for (let k = 0; k < n; k++) {
        const c = topC[k];
        if (c === 0) continue;
        const ch = dict[c] ?? '';
        if (!ch) continue;
        let bonus;
        if (ch === ' ') {
          if (!word) continue;                            // «  » и пробел в начале — нет
          if (words) {
            // частое слово — чуть выгоднее редкого
            const r = Words.rank.get(word.toLowerCase());
            bonus = (r !== undefined)
              ? WORD_W * (1 - Math.min(1, Math.log10(r + 1) / 6))
              : -PEN * 2;
          }
        } else {
          const cu = ch.toUpperCase();
          if (words && ((cu >= 'А' && cu <= 'Я') || cu === 'Ё')) {
            bonus = isWordPrefix((word + ch).toUpperCase(), words) ? BONUS : -PEN;
          } else bonus = 0;
        }
        const lp = LN(p[row + c]) + bonus;
        const np = pref + ch;
        // p_b — гипотеза «последним кадром был blank», p_nb — «последним была буква».
        // Всё, что добавляет букву, попадает в p_nb; blank — в p_b.
        if (lastCh && ch === lastCh) {
          put(pref, -Infinity, sc[1] + lp);              // повтор без blank — тот же префикс
          put(np, -Infinity, sc[0] + lp);                // повтор ПОСЛЕ blank — новый префикс
        } else {
          put(np, -Infinity, tot + lp);
        }
      }
    }
    const arr = Array.from(next.entries())
      .map(([pref, sc]) => ({ pref, v: _beamLogsumexp(sc[0], sc[1]) }))
      .sort((a, b) => b.v - a.v)
      .slice(0, BEAM);
    beams = new Map(arr.map(x => [x.pref, next.get(x.pref)]));
  }
  let best = '', bestV = -Infinity;
  for (const [pref, sc] of beams) {
    const v = _beamLogsumexp(sc[0], sc[1]);
    if (v > bestV) { bestV = v; best = pref; }
  }
  return [best.replace(/\s{2,}/g, ' ').trim(), bestV];
}

/**
 * Инверсия (негатив). Замер на облачке-крике со скриншота 17:30: модель
 * «привыкла» к чёрному тексту на белом; на негативе она читает те же строки
 * увереннее («БОЛЕЕ РАВНО-» conf 0.88 → 0.92, «ТАЕ ЧЕРТ ВОЗЫМИ» → «ВОЗЬМИ»).
 */
function invertCanvas(src) {
  const w = src.width, h = src.height;
  if (w < 2 || h < 2) return src;
  const out = makeCanvas(w, h);
  const g = out.getContext('2d', { willReadFrequently: true });
  g.drawImage(src, 0, 0);
  const img = g.getImageData(0, 0, w, h);
  for (let i = 0; i < img.data.length; i += 4) {
    img.data[i] = 255 - img.data[i];
    img.data[i + 1] = 255 - img.data[i + 1];
    img.data[i + 2] = 255 - img.data[i + 2];
  }
  g.putImageData(img, 0, 0);
  return out;
}

function binarizeCanvas(src, polarity, R) {
  const w = src.width, h = src.height;
  if (w < 2 || h < 2) return src;
  const ctx = src.getContext('2d', { willReadFrequently: true });
  const img = ctx.getImageData(0, 0, w, h);
  const luma = lumaFrom(img.data, w, h);
  let t = inkThreshold(luma, R);
  if (t < 0) t = R.binarizeFallback;
  for (let i = 0; i < luma.length; i++) {
    const dark = luma[i] < t;
    const v = polarity === 0 ? (dark ? 0 : 255) : (dark ? 255 : 0);
    const p = i * 4;
    img.data[p] = img.data[p + 1] = img.data[p + 2] = v; img.data[p + 3] = 255;
  }
  const out = makeCanvas(w, h);
  out.getContext('2d').putImageData(img, 0, 0);
  return out;
}
/** Счётчики проходов: видны в шторке текста, а не «где-то в консоли». */
const DECODE_STATS = { byVariant: {}, variantRuns: 0, variantsPicked: 0, uncoveredLines: 0, wordsTried: 0, wordsFixed: 0, hardLines: 0, rec2Picked: 0 };

/** Увеличение кропа: мелкий и рукописный текст CTC читает лучше крупнее. */
function upscaleCanvas(src, k) {
  const w = Math.max(1, Math.round(src.width * k));
  const h = Math.max(1, Math.round(src.height * k));
  const out = makeCanvas(w, h);
  const ctx = out.getContext('2d', { willReadFrequently: true });
  ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(src, 0, 0, w, h);
  return out;
}

/** Все ли слова строки настоящие (по словарю и словоформам). */
function allWordsKnown(text) {
  if (!Words.ready) return false;
  const words = String(text).match(/[\p{L}]{2,}/gu) || [];
  if (!words.length) return false;
  return words.every(w => {
    const low = w.toLowerCase();
    return Words.isKnown(low) || Words.isPlausible(low);
  });
}

/** Оценка текста: сколько слов настоящее и сколько мусорных + уверенность.
 *  Слово из словаря ценим выше, чем просто «похоже на словоформу»: иначе
 *  «будучию» (форма проходит isPlausible) набирает столько же, сколько
 *  «будучи», и при равном счёте выигрывает вариант с чуть большей
 *  уверенностью модели. */
function textScore(text, conf) {
  const words = String(text).match(/[\p{L}]{2,}/gu) || [];
  if (!words.length) return -50;
  let known = 0, weak = 0, junk = 0;
  for (const w of words) {
    const low = w.toLowerCase();
    if (!Words.ready || Words.isKnown(low)) known++;
    else if (Words.isPlausible(low)) weak++;
    else junk++;
  }
  return known * 10 + weak * 4 - junk * 12 + (conf || 0) * 3;
}

/**
 * Первая ЦЕЛАЯ реплика полосы — чтобы начать читать, не дожидаясь всей полосы.
 *
 * Режем не по строкам (это рвало реплики на куски: «УЖЕ ПОРА НА-» + «ЧИНАТЬ
 * ВСТРЕЧУ,»), а по ОБЛАЧКУ: берём самый верхний бокс и все боксы, которые
 * перекрываются с ним по вертикали, распознаём их вместе и склеиваем тем же
 * bubblesOf, что и весь проход. Замер: 0,57 с («Быстро») / 0,70 с («Обычно»)
 * против 1,2 / 12,3 с на всю полосу.
 */
async function recognizeFirstBubble(src, R, band, preDet) {
  try {
    const det = preDet || await detectWithRetry(src, R);
    if (!det.boxes.length) return null;
    // Группа = самый верхний бокс плюс то, что идёт сразу под ним без большого
    // разрыва (строки одного облачка). Проверка «перекрываются по вертикали»
    // не годилась: у титула строки стоят вплотную, но не перекрываются, и
    // первая реплика выходила обрезанной («Как прожить» вместо всей строки).
    const sorted = det.boxes.slice().sort((a, b) => a.top - b.top || a.left - b.left);
    const first = sorted[0];
    const h0 = Math.max(first.bottom - first.top, 1);
    const group = [first];
    let lastBottom = first.bottom;
    for (let k = 1; k < sorted.length; k++) {
      const b = sorted[k];
      const hb = Math.max(b.bottom - b.top, 1);
      const gap = b.top - lastBottom;
      if (gap > h0 * 0.9) break;                       // началось другое облачко
      if (Math.max(hb, h0) / Math.min(hb, h0) > R.mergeHeightRatio) continue;
      group.push(b);
      lastBottom = Math.max(lastBottom, b.bottom);
    }
    const regs = [];
    for (const box of group) {
      for (const ln of textLines(src, box, R)) {
        if (band && !lineInBand(ln, band, band.y0 || 0)) continue;
        const crop = makeCanvas(Math.max(1, ln.right - ln.left), Math.max(1, ln.bottom - ln.top));
        crop.getContext('2d', { willReadFrequently: true })
          .drawImage(src, ln.left, ln.top, ln.right - ln.left, ln.bottom - ln.top,
            0, 0, crop.width, crop.height);
        const wide = (ln.right - ln.left) / src.width >= 0.25;
        let text = '', conf = 0;
        try { [text, conf] = await decodeBetter(crop, R, { wide }); } catch (e) { continue; }
        if (!text || conf <= R.minConfidence) continue;
        regs.push({ text, left: ln.left / src.width, top: ln.top / src.height,
          right: ln.right / src.width, bottom: ln.bottom / src.height });
      }
    }
    if (!regs.length) return null;
    const rtl = (R.dir || 'rtl') === 'rtl';
    const bubble = bubblesOf(regs, rtl, R)[0];
    const text = bubble ? Words.polish(bubble.text, R.junkRatio, bubble.confidence) : '';
    return text && (text.match(/\p{L}/gu) || []).length >= 2 ? text : null;
  } catch (e) {
    console.warn('первая реплика не далась', e);
    return null;
  }
}

/**
 * Дочинить ОТДЕЛЬНЫЕ слова, не трогая уже верные.
 *
 * Идея: если в строке одно слово прочитано неверно («БУДЕ.», «ПРИБЫЛА»), то
 * перебор вариантов по всей строке бесполезен — модель ошибается на всём
 * кропе сразу. Поэтому строку режем по столбцам на слова, гоним варианты
 * только по кропу битого слова, а верные слова и верные строки не трогаем.
 *
 * Защита от порчи: замена принимается, только если из кропа получилось
 * настоящее слово (по словарю или как словоформа) близкой длины. На
 * каллиграфии кропы дают «p», «тр» — такие кандидаты отбрасываются, и
 * строка остаётся как была.
 */
async function refineBrokenWords(crop, text, R) {
  const re = /[\p{L}]{2,}/gu;
  const spans = [];
  let m;
  while ((m = re.exec(text))) spans.push({ word: m[0], start: m.index, end: re.lastIndex });
  if (spans.length < 2) return text;
  const bad = spans.filter(sp => {
    const low = sp.word.toLowerCase();
    return !(Words.isKnown(low) || Words.isPlausible(low));
  });
  if (!bad.length) return text;                       // всё верно — не трогаем

  const boxes = wordColumns(crop, R);
  if (boxes.length !== spans.length) return text;     // разметка не совпала — не рискуем

  let out = text;
  for (let i = spans.length - 1; i >= 0; i--) {       // справа налево, чтобы индексы не ехали
    const sp = spans[i];
    if (!bad.includes(sp)) continue;                  // верные слова пропускаем
    const box = boxes[i];
    const w = box[1] - box[0] + 1;
    if (w < 18 || w > crop.width * 0.6) continue;     // слишком узко/широко — не угадать
    const wordCrop = makeCanvas(w, crop.height);
    wordCrop.getContext('2d', { willReadFrequently: true })
      .drawImage(crop, box[0], 0, w, crop.height, 0, 0, w, crop.height);
    const cand = await bestWordVariant(wordCrop, sp.word, R);
    await yieldUI();
    if (!cand) continue;
    DECODE_STATS.wordsFixed++;
    out = out.slice(0, sp.start) + cand + out.slice(sp.end);
  }
  return out;
}

/** Варианты распознавания одного слова; возвращает первое настоящее слово. */
async function bestWordVariant(wordCrop, original, R) {
  const len = Array.from(original).length;
  const padX = Math.max(2, Math.round(wordCrop.height * 0.25));
  const padY = Math.max(1, Math.round(wordCrop.height * 0.15));
  const padded = makeCanvas(wordCrop.width + padX * 2, wordCrop.height + padY * 2);
  const pctx = padded.getContext('2d', { willReadFrequently: true });
  pctx.fillStyle = '#fff'; pctx.fillRect(0, 0, padded.width, padded.height);
  pctx.drawImage(wordCrop, padX, padY);
  const tries = [
    ['orig', wordCrop],
    ['pad', padded],
    ['up2', upscaleCanvas(wordCrop, 2)],
    ['padUp2', upscaleCanvas(padded, 2)],
    ['contrast', contrastCanvas(wordCrop)],
  ];
  for (const [name, cv] of tries) {
    DECODE_STATS.wordsTried++;
    let cand = '';
    try { [cand] = await decodeCrop(cv); } catch (e) { continue; }
    const clean = String(cand).replace(/[^\p{L}]/gu, '');
    if (!clean || Math.abs(Array.from(clean).length - len) > 1) continue;
    const low = clean.toLowerCase();
    if (!(Words.isKnown(low) || Words.isPlausible(low))) continue;
    if (low === original.toLowerCase()) return null;
    return clean;
  }
  return null;
}

/** Границы слов в строке по столбцовой проекции «чернил». */
function wordColumns(crop, R) {
  const w = crop.width, h = crop.height;
  if (w < 4 || h < 4) return [];
  const data = crop.getContext('2d', { willReadFrequently: true }).getImageData(0, 0, w, h).data;
  const luma = lumaFrom(data, w, h);
  const thr = inkThreshold(luma, R);
  if (thr < 0) return [];
  const ink = new Uint8Array(w);
  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) if (luma[y * w + x] < thr) { ink[x] = 1; break; }
  }
  const gapMax = Math.max(2, Math.round(h * 0.30));
  const boxes = [];
  let x0 = -1, gap = 0;
  for (let x = 0; x < w; x++) {
    if (ink[x]) { if (x0 < 0) x0 = x; gap = 0; }
    else if (x0 >= 0) {
      gap++;
      if (gap >= gapMax) { boxes.push([x0, x - gap]); x0 = -1; gap = 0; }
    }
  }
  if (x0 >= 0) boxes.push([x0, w - 1]);
  return boxes;
}

/**
 * Перебор всех подготовок кропа: как есть, увеличенный, с растянутой
 * яркостью и две полярности бинаризации. Побеждает вариант, где больше
 * настоящих слов и меньше мусорных. Как только все слова верные — выходим,
 * чтобы не тратить время на телефоне.
 */
/** Кроп с белыми полями: модель видит целые буквы, а не обрезанные края. */
/** Вырезать прямоугольник страницы в отдельный canvas (для отправки в Lens). */
function cropCanvas(src, x, y, w, h) {
  const out = makeCanvas(Math.max(1, Math.round(w)), Math.max(1, Math.round(h)));
  out.getContext('2d', { willReadFrequently: true })
    .drawImage(src, Math.round(x), Math.round(y), Math.round(w), Math.round(h), 0, 0, out.width, out.height);
  return out;
}

function padCanvas(src, frac) {
  const pad = Math.max(1, Math.round(src.height * frac));
  const out = makeCanvas(src.width + pad * 2, src.height + pad * 2);
  const ctx = out.getContext('2d', { willReadFrequently: true });
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.drawImage(src, pad, pad);
  return out;
}

async function decodeAllVariants(crop, R, first) {
  // Порядок по замеренной пользе на реальной странице: увеличение и контраст
  // дают верные слова чаще, бинаризация — редко и дорого.
  // Поля важнее увеличения: на рукописном титуле «сестрой тирана.» читается
  // только с отступом 20 %, а без него выходит «естра тирана». Поэтому поля
  // идут сразу после исходного кропа.
  const pointed = padCanvas(crop, 0.2);
  const tries = [['orig', crop], ['pad20', pointed]];
  if (crop.height >= 12) tries.push(['up2', upscaleCanvas(crop, 2)]);
  tries.push(['contrast', contrastCanvas(crop)]);
  tries.push(['pad20up2', upscaleCanvas(pointed, 2)]);
  tries.push(['bin0', binarizeCanvas(crop, 0, R)]);
  let best = null;
  for (const [name, cv] of tries) {
    let text = '', conf = 0;
    // Исходный кроп уже распознан в decodeBetter — не гоняем модель дважды.
    if (name === 'orig' && first) { text = first[0]; conf = first[1]; }
    else {
      try { [text, conf] = await decodeCrop(cv); } catch (e) { continue; }
    }
    DECODE_STATS.variantRuns++;
    const score = textScore(text, conf);
    if (!best || score > best.score) {
      if (best && best.variant !== 'orig') DECODE_STATS.variantsPicked++;
      best = { text, conf, score, variant: name };
    }
    if (allWordsKnown(best.text)) break;
    await yieldUI();
  }
  // Какой вариант в итоге выбран — по этим числам решаем, какие подготовки
  // кропа вообще нужны (замер 27.10: на 45 строках побеждает orig в 43 случаях).
  if (best) DECODE_STATS.byVariant[best.variant] = (DECODE_STATS.byVariant[best.variant] || 0) + 1;
  return best || ['', 0, 'none'];
}

async function decodeBetter(cropCanvas, R, opts = {}) {
  const first = await decodeCrop(cropCanvas);
  // Всё уже верно — не тратим батарею на перебор.
  if (allWordsKnown(first[0])) return first;
  const letters = (s) => (s.match(/\p{L}/gu) || []).length;
  // Широкие строки — это реплики и подписи: ради верных слов перебираем все
  // подготовки кропа. Узкие (звуковые эффекты) не перебираем: там всё равно
  // не слова, и на телефоне это лишние секунды.
  if (R.decodeVariants !== false && (opts.wide || letters(first[0]) >= 3)) {
    const best = await decodeAllVariants(cropCanvas, R, first);
    return [best.text, best.conf];
  }
  const need = Math.max(0, Math.round(R.decodeRetryBelow ?? 1));
  let out = first;
  if (!(need === 0 || letters(first[0]) >= need)) {
    let best = first;
    for (const pol of [0, 1]) {
      const att = await decodeCrop(binarizeCanvas(cropCanvas, pol, R));
      if (letters(att[0]) > letters(best[0])) best = att;
    }
    out = best;
  }
  // Строку всё ещё не узнаёт словарь — это «трудная строка»: перебираем
  // подготовки и второй распознаватель (см. decodeHard), берём лучший по
  // словарю. На нормальном тексте сюда не заходим и времени не тратим.
  if (!allWordsKnown(out[0])) {
    const hard = await decodeHard(cropCanvas, R, out);
    if (hard) return [hard[0], hard[1]];
  }
  return out;
}

/**
 * Трудная строка: перебор подготовок и второго распознавателя, выбор по словарю.
 *
 * Замер на облачке-крике со скриншота 17:30 («ГДЕ, ЧЁРТ ВОЗЬМИ, ТЫ БЫЛ ЧТО ТЫ
 * МОЖЕШЬ ЗНАТЬ!»), реальные модели:
 *   как есть            ТАЕ ЧЕРТ ВОЗЫМИ   (2 слова из 3 в словаре)
 *   бинаризация         ТАЕ ЧЕРТ ВОЗЬМИ   (3 из 3)   ← +слово
 *   инверсия            ТАЕ ЧЕРТ ВОЗЬМИ   (3 из 3)
 *   x1.5 / x2 / x3      ТАЕ ЧЕРТ ВОЗЫМИ   (2 из 3)   ← масштаб не помогает
 * Вторая строка того же облачка:
 *   как есть            ТЫБЫЧТО ТМО       (0 из 2)
 *   бинаризация         ТЫ БЫИ ЧТ ТЫМ     (3 из 4)   ← слова хотя бы разделились
 * Поэтому перебор идёт по бинаризации/инверсии, а не по масштабу: это дешевле и
 * на замере полезнее. Гоняем ТОЛЬКО на строках, где словарь недоволен, — на
 * обычном тексте лишних вызовов модели нет.
 */
/**
 * Сравнить два прочтения одной строки по словарю.
 * better = больше слов, которые словарь знает, при не большем числе мусора.
 */
function lineStat(t) {
  const ws = (String(t).match(/[А-Яа-яЁё]{2,}/g) || []).map(w => w.toLowerCase());
  let known = 0, junk = 0;
  for (const w of ws) {
    if (Words.inDict(w)) known++;
    else if (!Words.isPlausible(w)) junk++;
  }
  return { known, junk, n: ws.length };
}
function variantBetter(cand, base) {
  const a = lineStat(cand), b = lineStat(base);
  if (a.known > b.known) return true;
  if (a.known < b.known) return false;
  return a.junk < b.junk;
}

/**
 * Адаптер для второго семейства распознавателей — «линейные» модели из
 * набора чтеца шрифтов (best_r28_final.onnx, best_finetuned_r4.onnx):
 * вход 1×1×32×ширина, серый, luma/255, белый фон = 1, поля 20 % высоты,
 * CTC: класс 0 — blank, символы по файлу азбуки, последний класс — «неизвестно»,
 * дальше латиница A–Z a–z.
 *
 * Замер на облачках со скриншотов 27.10 (реальные модели, Chromium):
 *   b1 «ЛУЧШЕ БЫТЬ БОЛЕЕ РАВНОДУШНЫМ»      наша 0 % · r28 4,0 % · finetuned 8,0 %
 *   b2 «Я ТОЖЕ ТАК СЧИТАЮ…»               наша 0 % · r28 5,2 % · finetuned 8,6 %
 *   b3 «НО РАЗВЕ НАШ ЛИДЕР…»               наша 5,9 % · r28 17,6 % · finetuned 17,6 %
 *   b4 крик «ГДЕ, ЧЁРТ ВОЗЬМИ…»            наша 14,7 % · r28 73,5 % · finetuned 73,5 %
 * То есть на наших страницах эти модели слабее, зато в 5–10 раз быстрее
 * (7–23 мс на строку против 78–99). Поэтому они не заменяют основной, а
 * работают как ещё один вариант в переборе трудных строк: побеждает тот, у
 * кого по словарю больше верных слов (variantBetter).
 */
async function decodeLine32(crop, sess, charset, R) {
  const chars = String(charset || '');
  if (!sess || !chars) return ['', 0];
  // Поля 20 % высоты — так модель обучена (в отчёте чтеца: CER 19,8 % → 2,7 %).
  const m = Math.max(2, Math.round(crop.height * 0.2));
  const pad = makeCanvas(crop.width + 2 * m, crop.height + 2 * m);
  const pctx = pad.getContext('2d', { willReadFrequently: true });
  pctx.fillStyle = '#fff'; pctx.fillRect(0, 0, pad.width, pad.height);
  pctx.drawImage(crop, m, m);
  const h = 32;
  const w32 = Math.max(8, Math.round(pad.width * h / pad.height));
  const W = Math.ceil((w32 + 4) / 8) * 8;           // ширина кратна 8, слева 4 px
  const c = makeCanvas(W, h);
  const g = c.getContext('2d', { willReadFrequently: true });
  g.fillStyle = '#fff'; g.fillRect(0, 0, W, h);
  g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
  g.drawImage(pad, 4, 0, w32, h);
  const px = g.getImageData(0, 0, W, h).data;
  const data = new Float32Array(h * W);
  for (let i = 0; i < h * W; i++) {
    const o = i * 4;
    data[i] = (0.299 * px[o] + 0.587 * px[o + 1] + 0.114 * px[o + 2]) / 255;
  }
  const t = new ort.Tensor('float32', data, [1, 1, h, W]);
  const out = await runModel(sess, { [sess.inputNames[0]]: t }, 'чтец');
  if (!out || !out.dims) return ['', 0];
  // Формы выхода у семейства разные: best_r28_final даёт [1,63,163],
  // best_finetuned_r4 — [63,1,111]. Классы всегда последним измерением,
  // время — тем из первых двух, которое не единица.
  const d = out.dims, v = out.data;
  let T = 0, C = 0;
  if (d.length === 3) {
    C = d[2];
    if (d[0] === 1 && d[1] > 1) T = d[1];           // [1, T, C]
    else if (d[1] === 1) T = d[0];                  // [T, 1, C]
    else if (d[1] > 10) { T = d[1]; C = d[2]; }     // [N, T, C] — берём первый
    else return ['', 0];
  } else if (d.length === 2) { T = d[0]; C = d[1]; }
  else return ['', 0];
  if (T < 1 || C < 2 || v.length < T * C) return ['', 0];
  let text = '', prev = 0, score = 0, count = 0;
  for (let ti = 0; ti < T; ti++) {
    let best = 0, bestV = v[ti * C], off = ti * C;
    for (let ci = 1; ci < C; ci++) { const x = v[off + ci]; if (x > bestV) { bestV = x; best = ci; } }
    if (best !== 0 && best !== prev) {
      if (best < chars.length) text += chars[best];
      else if (best >= chars.length + 2) {          // латиница после «неизвестно»
        const k = best - chars.length - 2;
        text += k < 26 ? String.fromCharCode(65 + k) : String.fromCharCode(97 + (k - 26));
      }
      score += bestV; count++;
    }
    prev = best;
  }
  await yieldUI();
  return [text.trim(), count ? score / count : 0];
}

async function decodeHard(crop, R, first) {
  if (R.hardVariants === false || !OCR.ready) return null;
  // Перебор стоит ~3 вызова модели на строку, поэтому гоняем его только там,
  // где он осмыслен: строка похожа на речь (два слова и хоть одно из словаря)
  // или это широкая строка облачка, а не звук «Тг. чв». Плюс потолок на
  // страницу, чтобы трудная глава не превращалась в минуту ожидания.
  const stat = lineStat(first[0]);
  const wide = crop.width / Math.max(1, crop.height) >= 2.2;
  if (stat.n < 2 && !wide) return null;
  if (!stat.known && !wide) return null;
  if ((DECODE_STATS.hardLines = (DECODE_STATS.hardLines || 0) + 1) > 6) return null;
  // Только бинаризация: на замере именно она дала «ВОЗЬМИ» и разделила
  // слипшиеся слова, а инверсия/увеличение давали тот же текст (иногда чуть
  // увереннее). Каждый лишний вариант — это +130 мс на строку, а трудных
  // строк на странице бывает несколько: на e2e-странице перебор из трёх
  // вариантов стоил +2 с при том же результате.
  // Один и тот же кроп читаем по-разному: жадным разбором, своим декодером
  // со словарём, бинаризацией и (если подключён) вторым распознавателем.
  const readAs = async (cv, sess, mode) => {
    if (mode === 'beam') {
      const res = await recProbs(cv, sess);
      if (!res) return ['', 0];
      const [text, v] = beamDecode(res);
      return [text, Number.isFinite(v) ? Math.min(1, Math.max(0, 1 + v / 20)) : 0];
    }
    const isLine32 = sess && sess === OCR.rec2 && OCR.rec2Kind === 'line32';
    if (mode === 'line32' || isLine32) return decodeLine32(cv, sess, OCR.rec2Charset, R);
    return decodeCrop(cv, sess);
  };
  const bin0 = binarizeCanvas(crop, 0, R);
  const tries = [['bin0', bin0, null, 'greedy']];
  // Второй распознаватель (⚙ → Модели → cyrillic2.onnx): «субагент» для
  // трудных строк. Работает только если его азбука совпадает с текущим
  // словарём (проверяется при загрузке), иначе молча пропускается.
  if (OCR.rec2) tries.push(['rec2', crop, OCR.rec2, 'line32']);
  let best = { text: first[0], conf: first[1], variant: 'orig' };
  const takeVariant = async (name, cv, sess, mode) => {
    let text = '', conf = 0;
    try { [text, conf] = await readAs(cv, sess, mode); } catch (e) { return; }
    DECODE_STATS.variantRuns++;
    // Сравниваем по СЛОВАМ, а не по общей оценке. На титуле сочинения
    // (e2e, «Как прожить жизнь, будучи старшей сестрой тирана») общая оценка
    // выбрала вариант, где «будучи» стало «буздчо»: одна знакомая фраза
    // перевесила испорченное слово. Правило: вариант берём, только если он
    // добавил хотя бы одно слово, которое словарь знает, и не добавил
    // незнакомых. Равное число знакомых и меньше мусора — тоже лучше.
    if (variantBetter(text, best.text)) best = { text, conf, variant: name };
  };
  for (const [name, cv, sess, mode] of tries) await takeVariant(name, cv, sess, mode);
  // Поиск по словарю на ОРИГИНАЛЕ — самый дорогой шаг (второй прогон модели на
  // ту же строку). Он вытаскивает «БЫЛ» и «ЧТО» на наклонном шрифте, но за
  // страницу платим временем, поэтому ограничен тремя строками: на e2e-странице
  // без потолка это стоило +1,0 с, с потолком — вдвое меньше.
  if (lineStat(best.text).junk > 0
      && (DECODE_STATS.beamExtra = (DECODE_STATS.beamExtra || 0) + 1) <= 3) {
    await takeVariant('beam', crop, null, 'beam');
  }
  // Наклон — только если строка всё ещё не нравится словарю И наклон у неё
  // действительно есть (свой оценщик, ~1 мс). Раньше здесь было два слепых
  // прогона модели (±0,28/±0,24) — это +180 мс на каждую трудную строку.
  if (lineStat(best.text).junk > 0) {
    // Свой оценщик даёт ЗНАК наклона надёжно (на наклонных строках −0,1…−0,2,
    // на ровных 0), а точную величину — нет. Поэтому знак берём у него, а
    // величину — проверенную на замере. Один прогон вместо двух.
    const est = estimateSlant(binarizeCanvas(crop, 0, R) || crop, R);
    DECODE_STATS.slant = est;
    const tan = est < -0.05 ? -0.28 : (est > 0.05 ? 0.24 : 0);
    if (tan) {
      const name = tan < 0 ? 'shear-' : 'shear+';
      await takeVariant(name, shearCanvas(crop, tan), null, 'beam');
      if (best.variant === name) DECODE_STATS.shearPicked = (DECODE_STATS.shearPicked || 0) + 1;
    }
  }
  if (best.variant !== 'orig') DECODE_STATS.variantsPicked++;
  if (best.variant === 'beam') DECODE_STATS.beamPicked = (DECODE_STATS.beamPicked || 0) + 1;
  if (best.variant === 'rec2') DECODE_STATS.rec2Picked = (DECODE_STATS.rec2Picked || 0) + 1;
  return best.variant === 'orig' ? null : [best.text, best.conf, best.variant];
}

/* ── страница целиком: детектор → строки → распознавание ── */
/**
 * Видна ли строка на экране. band.vy0…vy1 — это ровно экран, без запаса,
 * который нужен был детектору. Строку, видимую хотя бы на 40 %, берём целиком
 * (не рвём реплику), а облачко ниже экрана не берём вовсе — иначе в шторке
 * появлялся «лишний» текст, которого на экране нет.
 */
/** Расстояние Левенштейна: нужно для честной правки в два редактирования. */
function levenshtein(a, b) {
  const s = Array.from(a), t = Array.from(b);
  if (!s.length) return t.length;
  if (!t.length) return s.length;
  let prev = new Array(t.length + 1);
  let cur = new Array(t.length + 1);
  for (let j = 0; j <= t.length; j++) prev[j] = j;
  for (let i = 1; i <= s.length; i++) {
    cur[0] = i;
    for (let j = 1; j <= t.length; j++) {
      const cost = s[i - 1] === t[j - 1] ? 0 : 1;
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
    }
    [prev, cur] = [cur, prev];
  }
  return prev[t.length];
}

function lineInBand(ln, band, y0) {
  if (!band || band.vy0 == null || band.vy1 == null) return true;
  const top = y0 + ln.top, bottom = y0 + ln.bottom;
  const h = bottom - top;
  if (h <= 0) return false;
  const over = Math.min(bottom, band.vy1) - Math.max(top, band.vy0);
  return over >= h * 0.4;
}

async function recognizePage(imgCanvas, R, onProgress, band, preDet) {
  const t0 = performance.now();
  DECODE_STATS.variantRuns = 0; DECODE_STATS.variantsPicked = 0; DECODE_STATS.uncoveredLines = 0; DECODE_STATS.wordsTried = 0; DECODE_STATS.wordsFixed = 0;
  DECODE_STATS.hardLines = 0; DECODE_STATS.rec2Picked = 0;
  // band = {y0, y1} в пикселях исходного кадра: распознаём ТОЛЬКО видимую
  // полосу. По правилу «длинную страницу читать в пределах видимой области»
  // иначе на вебтуне в 8000 px находились реплики на два экрана вперёд.
  let src = imgCanvas;
  const y0 = band ? Math.max(0, Math.round(band.y0)) : 0;
  const y1 = band ? Math.min(imgCanvas.height, Math.round(band.y1)) : imgCanvas.height;
  const bandH = Math.max(1, y1 - y0);
  if (band && (y0 > 0 || y1 < imgCanvas.height)) {
    const c = makeCanvas(imgCanvas.width, bandH);
    c.getContext('2d', { willReadFrequently: true })
      .drawImage(imgCanvas, 0, y0, imgCanvas.width, bandH, 0, 0, imgCanvas.width, bandH);
    src = c;
  }
  const visible = (ln) => lineInBand(ln, band, y0);

  // ── Проход 1: детектор. Если он не нашёл ничего, пробуем другие подготовки
  // кадра: бледная каллиграфия и светлый текст на белом фоне не ловятся на
  // исходном кадре, а на контрастном/бинаризованном находятся.
  // Конвейер уже прогнал детектор, чтобы начать читать раньше, — второй раз
  // его не гоняем (это ~450 мс на полосу). Кадр детектора тот же: полоса.
  const det = preDet || await detectWithRetry(src, R);
  const detMs = Math.round(performance.now() - t0);
  const t1 = performance.now();
  const W = src.width, H = src.height;
  let crops = 0;
  const regions = [];
  let largePasses = 0;

  const decodeLine = async (canvas, ln, wide, opts) => {
    const w = Math.max(1, ln.right - ln.left), h = Math.max(1, ln.bottom - ln.top);
    const c = makeCanvas(w, h);
    c.getContext('2d', { willReadFrequently: true })
      .drawImage(canvas, ln.left, ln.top, w, h, 0, 0, w, h);
    crops++;
    const ckey = _cropKey(c, wide, R);
    const hit = textCacheGet(ckey);
    if (hit) return hit;
    let [text, conf] = await decodeBetter(c, R, { wide });
    let bestScore = textScore(text, conf);
    // Титульная строка «жизнь, будучи старшей» на кропе по боксу строки читается
    // как «оддучив»: детектор обрезает низ строки, и CTC теряет «б» и «у». Точный
    // перебор обрезки со всех сторон (см. brute-official-box.json) дал: кроп,
    // расширяемый вверх на 30 % высоты строки, с полями 15 % — та же модель без
    // подмены слов читает «жизнь, будучи старшей» (conf 0.74). Перебираем такие
    // кропы только когда в строке есть незнакомые слова, и берём лучший по
    // textScore (словарные слова против мусора).
    // Расширение кропа пробуем только когда есть незнакомые слова. Пробовать
    // его ещё и для всех строк у края экрана — замерено: 196 кропов и 52 с
    // вместо 120 кропов и ~14 с, а текста больше не становится.
    if (R.extCrop !== false && text && !allWordsKnown(text) && !(opts && opts.skipExt)
        && (wide || (text.match(/\p{L}/gu) || []).length >= 5)) {
      const ext = (topFrac, botFrac) => {
        const dt = Math.round(h * topFrac), db = Math.round(h * botFrac);
        const t = clamp(ln.top - dt, 0, canvas.height - 1);
        const b = clamp(ln.bottom + db, t + 1, canvas.height);
        if (t >= ln.top && b <= ln.bottom) return null;         // нечего расширять
        const e = makeCanvas(w, Math.max(1, b - t));
        e.getContext('2d', { willReadFrequently: true })
          .drawImage(canvas, ln.left, t, w, b - t, 0, 0, w, b - t);
        return e;
      };
      // Подготовки из перебора: без них расширенный кроп даёт «будучь», а не «будучи».
      const preps = (e) => [
        ['orig', e], ['pad10', padCanvas(e, 0.10)], ['pad15', padCanvas(e, 0.15)],
        ['up15', upscaleCanvas(e, 1.5)], ['contrast', contrastCanvas(e)],
        ['gamma13', (() => { const src = e; const w2 = src.width, h2 = src.height;
          const ctx = src.getContext('2d', { willReadFrequently: true });
          const img = ctx.getImageData(0, 0, w2, h2), d = img.data;
          for (let i = 0; i < d.length; i += 4) for (let k = 0; k < 3; k++)
            d[i + k] = clamp(Math.round(255 * Math.pow(d[i + k] / 255, 1.3)), 0, 255);
          const out = makeCanvas(w2, h2); out.getContext('2d').putImageData(img, 0, 0); return out; })()],
      ];
      // Режим 'light' — один дешёвый вариант (захват вверх 30 % + поля 15 %):
      // именно он даёт «будучи», но стоит 1–2 вызова модели вместо 18.
      const makers = (R.extCrop === 'light')
        ? [ext(0.30, 0)]
        : [ext(0.30, 0), ext(0.15, 0), ext(0, 0.15)];
      const prepList = (R.extCrop === 'light')
        ? null                        // ниже берём только pad15
        : null;
      outer:
      for (const maker of makers) {
        if (!maker) continue;
        const list = (R.extCrop === 'light')
          ? [['pad15', padCanvas(maker, 0.15)]]
          : preps(maker);
        for (const [name, pc] of list) {
          crops++;
          let t2, c2;
          try { [t2, c2] = await decodeCrop(pc); } catch (e) { continue; }
          const s = textScore(t2, c2);
          if (s > bestScore) { bestScore = s; text = t2; conf = c2; }
          if (allWordsKnown(text)) break outer;   // все слова словарные — хватит
          await yieldUI();
        }
      }
    }
    const out = { text, conf };
    textCachePut(ckey, out);
    return out;
  };

  // ── Проход 1: строки внутри боксов. Сначала собираем всё, потом (зная
  // типичную высоту строки) решаем, какие боксы — крупный текст.
  const byBox = [];
  let done = 0;
  for (const box of det.boxes) {
    const lines = textLines(src, box, R).filter(visible);
    const items = [];
    for (let li = 0; li < lines.length; li++) {
      const ln = lines[li];
      if (onProgress && det.boxes.length)
        onProgress(done + (li + 1) / (lines.length + 1), det.boxes.length);
      await yieldUI();
      const wide = (ln.right - ln.left) / W >= 0.25;   // реплика, а не звук
      // Край полосы: строка могла быть разрезана границей экрана.

      let { text, conf } = await decodeLine(src, ln, wide);
      // Битые слова дочиниваем по одному, верные — не трогаем.
      if (R.breakWords !== false && wide && text && !allWordsKnown(text)) {
        const crop = makeCanvas(Math.max(1, ln.right - ln.left), Math.max(1, ln.bottom - ln.top));
        crop.getContext('2d', { willReadFrequently: true })
          .drawImage(src, ln.left, ln.top, ln.right - ln.left, ln.bottom - ln.top, 0, 0, crop.width, crop.height);
        const fixed = await refineBrokenWords(crop, text, R);
        if (fixed !== text && textScore(fixed, conf) > textScore(text, conf)) text = fixed;
      }
      if (text.trim() && conf > R.minConfidence) {
        items.push({
          text,
          left: ln.left / W, top: (y0 + ln.top) / imgCanvas.height,
          right: ln.right / W, bottom: (y0 + ln.bottom) / imgCanvas.height,
          confidence: conf,
        });
      }
    }
    byBox.push({ box, items });
    done++;
    if (onProgress) onProgress(done, det.boxes.length + 0);
    await sleep(0);      // не блокируем кадр
  }

  // ── Проход 2: крупный текст (титул, каллиграфия, большие буквы). На обычном
  // масштабе такой блок слипается в одну «строку» и читается плохо. Кроп
  // увеличиваем и ищем заново — тогда блок делится на строки, и каждая
  // распознаётся отдельно. Берём результат, только если он лучше первого.
  const pageMedian = medianLineHeight(byBox);
  let largeIdx = 0;
  for (const entry of byBox) {
    if (R.largeText === false) break;
    if (onProgress) onProgress(++largeIdx, byBox.length, 'крупный текст');
    await yieldUI();
    const own = entry.items.map(i => i.bottom - i.top).sort((a, b) => a - b);
    const h = own.length ? own[own.length >> 1] * imgCanvas.height : 0;
    const boxW = (entry.box.right - entry.box.left) / W;
    const firstTexts = entry.items.map(i => i.text);
    const letters = lettersOf(firstTexts);
    const hard = letters >= 8 && knownShare(firstTexts) < 0.5;
    const big = pageMedian > 0 && h > pageMedian * 1.8;
    if (boxW < (R.largeMinWidth ?? 0.22) || !(hard || big)) continue;
    largePasses++;
    const alt = await recognizeLargeBox(src, entry.box, R, { visible, y0, pageH: imgCanvas.height, W });
    crops += alt.crops;
    // Текст не теряем: принимаем второй проход, только если он сохранил хотя
    // бы 80 % букв (иначе из титула пропадали строки).
    if (!alt.items.length || lettersOf(alt.items.map(i => i.text)) < letters * 0.8) continue;
    // Если второй проход набрал заметно больше букв, это почти всегда дубль
    // («… будучи старшей жизнь, Оцачит старшей сестрой тирана»), а не более
    // точное чтение: такую замену не берём.
    if (lettersOf(alt.items.map(i => i.text)) > letters * 1.3) continue;
    if (qualityOf(alt.items.map(i => i.text)) > qualityOf(firstTexts)) entry.items = alt.items;
  }
  for (const entry of byBox) for (const item of entry.items) regions.push(item);

  // ── Проход 3: то, что детектор не закрыл боксами. Дешёвый поиск полос с
  // «чернилами» без боксов; если в такой полосе нашлись строки — распознаём.
  if (R.uncoveredPass !== false) {
    const extra = uncoveredBands(src, det.boxes, R);
    for (let bi = 0; bi < extra.length; bi++) {
      if (onProgress) onProgress(bi + 1, extra.length, 'области без боксов');
      await yieldUI();
      for (const ln of textLines(src, extra[bi], R)) {
        if (!visible(ln)) continue;
        const wide = (ln.right - ln.left) / W >= 0.25;
        const { text, conf } = await decodeLine(src, ln, wide, { skipExt: true });
        await yieldUI();
        if (!text.trim() || conf <= R.minConfidence) continue;
        DECODE_STATS.uncoveredLines++;
        const item = {
          text,
          left: ln.left / W, top: (y0 + ln.top) / imgCanvas.height,
          right: ln.right / W, bottom: (y0 + ln.bottom) / imgCanvas.height,
          confidence: conf,
        };
        // уже есть почти то же самое на этом месте — не дублируем
        const dup = regions.some(o =>
          Math.min(o.bottom, item.bottom) - Math.max(o.top, item.top) > (item.bottom - item.top) * 0.5
          && Math.abs(o.left - item.left) < 0.2);
        if (!dup) regions.push(item);
      }
    }
  }

  return {
    regions, boxes: det.boxes.length,
    ms: Math.round(performance.now() - t0),
    detMs, recMs: Math.round(performance.now() - t1), crops,
    band: band ? { y0, y1 } : null,
    detPass: det.pass,
    largePasses,
    variantRuns: DECODE_STATS.variantRuns,
    variantsPicked: DECODE_STATS.variantsPicked,
    uncoveredLines: DECODE_STATS.uncoveredLines,
    wordsTried: DECODE_STATS.wordsTried,
    wordsFixed: DECODE_STATS.wordsFixed,
  };
}

/**
 * Строки с текстом, которые детектор НЕ закрыл ни одним боксом.
 *
 * На скриншоте 12:54 средняя строка титула («жизнь, будучи») не попала ни в
 * один бокс и пропала из текста. Ищем по кадру полосы, где есть «чернила», но
 * нет боксов, и отдаём их на распознавание — чтобы не терять слова.
 */
function uncoveredBands(src, boxes, R) {
  const out = [];
  const SW = 200;                                   // рабочая ширина
  const k = SW / src.width;
  const w = SW, h = Math.max(8, Math.round(src.height * k));
  const small = makeCanvas(w, h);
  const ctx = small.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(src, 0, 0, w, h);
  const luma = lumaFrom(ctx.getImageData(0, 0, w, h).data, w, h);
  const thr = inkThreshold(luma, R);
  if (thr < 0) return out;
  const covered = new Uint8Array(h);
  for (const b of boxes) {
    const y0 = Math.max(0, Math.floor(b.top * k) - 2);
    const y1 = Math.min(h - 1, Math.ceil(b.bottom * k) + 2);
    for (let y = y0; y <= y1; y++) covered[y] = 1;
  }
  const need = Math.max(2, Math.round(w * 0.02));   // сколько тёмного в строке
  const hasInk = (y) => {
    let cnt = 0;
    for (let x = 0; x < w; x++) if (luma[y * w + x] < thr) { if (++cnt >= need) return true; }
    return false;
  };
  const runs = [];
  let y = 0;
  while (y < h) {
    if (covered[y] || !hasInk(y)) { y++; continue; }
    let end = y;
    while (end < h && !covered[end] && hasInk(end)) end++;
    if (end - y >= 3) runs.push([y, end]);
    y = Math.max(end, y + 1);
  }
  for (const [a, b] of runs) {
    const top = clamp(Math.floor(a / k) - 3, 0, src.height - 1);
    const bottom = clamp(Math.ceil(b / k) + 3, top + 1, src.height);
    out.push({ left: 0, top, right: src.width, bottom });
  }
  return out.slice(0, 12);
}

/** Медиана высоты реплик на странице — по ней отличаем крупный текст. */
/** Сколько букв в наборе строк. */
function lettersOf(texts) {
  let n = 0;
  for (const t of texts || []) n += (String(t).match(/\p{L}/gu) || []).length;
  return n;
}

/** Доля слов, известных словарю: по ней видно «трудный» текст. */
function knownShare(texts) {
  let all = 0, known = 0;
  for (const t of texts || []) {
    for (const w of String(t).match(/[\p{L}\p{N}]{2,}/gu) || []) {
      all++;
      if (!Words.ready || Words.isKnown(w.toLowerCase()) || Words.isPlausible(w.toLowerCase())) known++;
    }
  }
  return all ? known / all : 0;
}

function medianLineHeight(byBox) {
  const hs = [];
  for (const e of byBox) for (const i of e.items) hs.push(i.bottom - i.top);
  hs.sort((a, b) => a - b);
  return hs.length ? hs[hs.length >> 1] : 0;
}

/**
 * Насколько текст похож на настоящий: сколько слов знает словарь. По этой
 * оценке выбираем между первым и вторым проходом («будучи» лучше «будучиг»).
 */
function qualityOf(texts) {
  if (!texts || !texts.length) return 0;
  let known = 0, all = 0;
  for (const t of texts) {
    for (const w of String(t).match(/[\p{L}\p{N}]{2,}/gu) || []) {
      all++;
      if (!Words.ready || Words.isKnown(w.toLowerCase()) || Words.isPlausible(w.toLowerCase())) known++;
    }
  }
  if (!all) return 0;
  // Главное — доля знакомых слов. Число слов только чуть-чуть поощряется,
  // иначе вариант с лишними буквами («МОжиМЬ Как прожить») выигрывал у
  // чистого «Как прожить».
  return (known / all) * 100 + Math.min(all, 20) * 0.5;
}

/**
 * Детектор с повторами: если на исходном кадре боксов 0, пробуем контраст и
 * две полярности бинаризации. Возвращает, какая подготовка сработала, чтобы
 * это было видно в отчёте шторки, а не оставалось тайной.
 */
async function detectWithRetry(src, R) {
  const boxes = await detectBoxes(src, R.pageSide, R);
  if (boxes.length) return { boxes, pass: boxes.pass || 'normal' };
  if (R.detRetry === false) return { boxes: [], pass: 'none' };
  const variants = [
    ['contrast', () => contrastCanvas(src)],
    ['binary', () => binarizeCanvas(src, 0, R)],
    ['binary-inv', () => binarizeCanvas(src, 1, R)],
  ];
  for (const variant of variants) {
    try {
      const found = await detectBoxes(variant[1](), R.pageSide, R);
      if (found.length) return { boxes: found, pass: variant[0] };
    } catch (e) { console.warn('повтор детектора (' + variant[0] + ') не удался', e); }
  }
  return { boxes: [], pass: 'none' };
}

/** Растянуть диапазон яркости: бледный текст на белом иначе не виден детектору. */
function contrastCanvas(src) {
  const w = src.width, h = src.height;
  const ctx = src.getContext('2d', { willReadFrequently: true });
  const img = ctx.getImageData(0, 0, w, h);
  const luma = lumaFrom(img.data, w, h);
  let lo = 255, hi = 0;
  for (let i = 0; i < luma.length; i++) { const v = luma[i]; if (v < lo) lo = v; if (v > hi) hi = v; }
  const span = Math.max(1, hi - lo);
  for (let i = 0; i < luma.length; i++) {
    const v = clamp(Math.round(((luma[i] - lo) / span) * 255), 0, 255);
    const p = i * 4;
    img.data[p] = img.data[p + 1] = img.data[p + 2] = v; img.data[p + 3] = 255;
  }
  const out = makeCanvas(w, h);
  out.getContext('2d').putImageData(img, 0, 0);
  return out;
}

/**
 * Второй проход по крупному блоку: увеличить кроп, найти боксы заново,
 * разбить на строки и распознать каждую. Координаты возвращаются в системе
 * всей страницы, чтобы рамки стояли на месте.
 */
async function recognizeLargeBox(src, box, R, ctxInfo) {
  const out = { items: [], crops: 0 };
  const pad = Math.round((box.bottom - box.top) * 0.10);
  const left = clamp(box.left - pad, 0, src.width - 1);
  const right = clamp(box.right + pad, 1, src.width);
  const top = clamp(box.top - pad, 0, src.height - 1);
  const bottom = clamp(box.bottom + pad, 1, src.height);
  const bw = right - left, bh = bottom - top;
  if (bw < 40 || bh < 20) return out;
  const k = clamp(Math.round(1200 / Math.max(bw, bh)), 1, 4);
  if (k < 2) return out;                       // мелкий блок увеличивать незачем
  const up = makeCanvas(Math.round(bw * k), Math.round(bh * k));
  const uctx = up.getContext('2d', { willReadFrequently: true });
  uctx.imageSmoothingEnabled = true; uctx.imageSmoothingQuality = 'high';
  uctx.drawImage(src, left, top, bw, bh, 0, 0, up.width, up.height);
  // Бледная каллиграфия на белом не даёт чернильных строк на исходном кропе.
  // Поэтому пробуем три подготовки кадра и берём ту, где текст получился
  // осмысленнее: увеличено / с растянутой яркостью / бинаризовано.
  const full = { left: 0, top: 0, right: up.width, bottom: up.height };
  const variants = [
    up,
    contrastCanvas(up),
    binarizeCanvas(up, 0, R),
  ];
  let best = null;
  for (const work of variants) {
    await yieldUI();
    const boxes = await detectBoxes(work, R.pageSide, R);
    const lines = [];
    for (const b of boxes) for (const ln of textLines(work, b, R)) lines.push(ln);
    if (lines.length < 2) {
      for (const ln of textLines(work, full, R)) {
        if (!lines.some(o => Math.abs(o.top - ln.top) < 4)) lines.push(ln);
      }
    }
    if (!lines.length) continue;
    const got = await decodeLargeLines(work, lines, R, { k, left, top, src, ctxInfo });
    out.crops += got.crops;
    if (!got.items.length) continue;
    const score = qualityOf(got.items.map(i => i.text)) + Math.min(got.items.length, 6) * 3;
    if (!best || score > best.score) best = { score, items: got.items };
  }
  out.items = best ? best.items : [];
  return out;
}

/** Распознать найденные строки увеличенного кропа и вернуть их на страницу. */
async function decodeLargeLines(work, lines, R, info) {
  const items = [];
  let crops = 0;
  for (const ln of lines) {
    const orig = {
      left: clamp(Math.round(info.left + ln.left / info.k), 0, info.src.width - 1),
      top: clamp(Math.round(info.top + ln.top / info.k), 0, info.src.height - 1),
      right: clamp(Math.round(info.left + ln.right / info.k), 1, info.src.width),
      bottom: clamp(Math.round(info.top + ln.bottom / info.k), 1, info.src.height),
    };
    if (!info.ctxInfo.visible(orig)) continue;
    const c = makeCanvas(Math.max(1, ln.right - ln.left), Math.max(1, ln.bottom - ln.top));
    c.getContext('2d', { willReadFrequently: true })
      .drawImage(work, ln.left, ln.top, ln.right - ln.left, ln.bottom - ln.top, 0, 0, c.width, c.height);
    crops++;
    const wide = (ln.right - ln.left) / work.width >= 0.25;
    const [text, conf] = await decodeBetter(c, R, { wide });
    if (text.trim() && conf > R.minConfidence) {
      items.push({
        text,
        left: orig.left / info.ctxInfo.W,
        top: (info.ctxInfo.y0 + orig.top) / info.ctxInfo.pageH,
        right: orig.right / info.ctxInfo.W,
        bottom: (info.ctxInfo.y0 + orig.bottom) / info.ctxInfo.pageH,
        confidence: conf, large: true,
      });
    }
  }
  return { items, crops };
}


/* ───────────────────────── 6. Порядок чтения ───────────────────────── */
const isCyr = (t) => {
  const all = (t.match(/\p{L}/gu) || []).length;
  if (!all) return false;
  const ru = (t.match(/[а-яёА-ЯЁ]/gi) || []).length;
  return ru > 0 && ru * 2 >= all;
};
/* Правки слов из правил: до словаря, без учёта регистра, регистр сохраняем. */
function applyWordFixes(text, fixes) {
  const keys = Object.keys(fixes || {});
  if (!keys.length) return text;
  const low = {}; keys.forEach(k => low[k.toLowerCase()] = fixes[k]);
  return text.replace(/[\p{L}\p{N}]+/gu, (word) => {
    const rep = low[word.toLowerCase()];
    if (!rep) return word;
    if (word === word.toUpperCase()) return rep.toUpperCase();
    if (/^\p{Lu}/u.test(word)) return rep.charAt(0).toUpperCase() + rep.slice(1);
    return rep;
  });
}
/* облачка: склейка строк одной высоты (bubbleGap + mergeHeightRatio) */
/**
 * Перенос слова с точкой вместо дефиса: OCR читает «БУДЕ-» как «БУДЕ.».
 * Склеиваем без пробела, только если вместе получается слово из словаря —
 * иначе «НО.» + «ОН» превратилось бы в «НООН».
 */
function joinBrokenWord(text, next) {
  const m = String(text).match(/([\p{L}]{2,})[.\-]$/u);
  if (!m) return false;
  const head = String(next).trim().split(/\s+/)[0] || '';
  if (!/^[\p{L}]/u.test(head)) return false;
  const cand = (m[1] + head).toLowerCase();
  if (!Words.ready) return false;
  return Words.isKnown(cand) || Words.isPlausible(cand);
}

function bubblesOf(group, rtl, R) {
  const bubbleGap = R.bubbleGap;
  if (!group.length) return [];
  const sorted = group.slice().sort((a, b) => a.top - b.top || a.left - b.left);
  const blocks = [];
  for (const rg of sorted) {
    let target = null, bestGap = Infinity;
    for (const block of blocks) {
      const head = block[block.length - 1];
      const lineHeight = Math.max(head.bottom - head.top, 0.01);
      const overlap = Math.min(head.bottom, rg.bottom) - Math.max(head.top, rg.top);
      if (overlap <= lineHeight * 0.35) continue;
      const blockLeft = Math.min(...block.map(r => r.left));
      const blockRight = Math.max(...block.map(r => r.right));
      const gap = rg.left > blockRight ? rg.left - blockRight : (rg.right < blockLeft ? blockLeft - rg.right : 0);
      const rh = Math.max(rg.bottom - rg.top, 0.01);
      if (Math.max(lineHeight, rh) / Math.min(lineHeight, rh) > R.mergeHeightRatio) continue;
      const shortHead = (head.text.match(/[\p{L}\p{N}]/gu) || []).length <= 3;
      const shortRg = (rg.text.match(/[\p{L}\p{N}]/gu) || []).length <= 3;
      const limit = (shortHead && shortRg && overlap >= lineHeight * 0.7) ? lineHeight * 2.5 : lineHeight * R.bubbleGap;
      if (gap > limit) continue;
      if (gap < -lineHeight * 0.9) continue;
      // Потолок высоты: облачко не бывает выше 22 % страницы. Без этого проза
      // (две колонки журнала) склеивалась в один блок на полстраницы — «одна
      // реплика» на 75 слов (замер 28.10).
      const mergedTop = Math.min(...block.map(r => r.top), rg.top);
      const mergedBottom = Math.max(...block.map(r => r.bottom), rg.bottom);
      if (mergedBottom - mergedTop > 0.22) continue;
      if (gap < bestGap) { bestGap = gap; target = block; }
    }
    if (target) target.push(rg); else blocks.push([rg]);
  }
  // Слишком высокий блок — это не облачко, а АБЗАЦ или целая колонка: так
  // выглядит проза (журнал, книга). Замер 28.10 на странице «Весёлых картинок»:
  // две газетные колонки склеивались в блок высотой 0,34 страницы, и это была
  // одна «реплика» на 75 слов. Для манги правило безвредно: облачко редко выше
  // четверти страницы, а если и выше — его строки идут плотно, и разрез по
  // самому большому пробелу всё равно придётся на пустое место.
  const MAX_BLOCK = 0.22;                      // доля высоты страницы
  const splitTall = (block) => {
    if (block.length < 4) return [block];
    const span = (b) => Math.max(...b.map(r => r.bottom)) - Math.min(...b.map(r => r.top));
    if (span(block) <= MAX_BLOCK) return [block];
    const sortedB = block.slice().sort((a, b) => a.top - b.top);
    let cut = -1, bestGap = 0;
    for (let i = 1; i < sortedB.length; i++) {
      const gap = sortedB[i].top - sortedB[i - 1].bottom;
      if (gap > bestGap) { bestGap = gap; cut = i; }
    }
    if (cut < 0) return [block];
    const a = sortedB.slice(0, cut), b = sortedB.slice(cut);
    return [...splitTall(a), ...splitTall(b)];
  };
  const flatBlocks = blocks.flatMap(splitTall);
  const lines = flatBlocks.map(block => {
    const ordered = block.slice().sort((a, b) => rtl ? b.left - a.left : a.left - b.left);
    // Склейка частей одной строки ровно как в KomaAutoRead:
    //   «ВЫСО-» + «ЧЕСТВО» → без пробела и без дефиса;
    //   обрывок в 1-2 буквы после буквы → тоже без пробела.
    let text = '';
    ordered.forEach((part, index) => {
      const t = String(part.text || '').trim();
      if (!t) return;
      if (index > 0 && text) {
        const prev = ordered[index - 1]?.text?.trim() || '';
        const last = text[text.length - 1];
        if (last === '-' || last === '\u00AD') text = text.slice(0, -1);
        else if (joinBrokenWord(text, t)) text = text.replace(/[.\-]$/, '');   // «БУДЕ.» + «ТЕ» → «БУДЕТЕ»
        else if (!(t.length <= 2 && /\p{L}$/u.test(prev) && /^\p{L}/u.test(t))) text += ' ';
      }
      text += t;
    });
    text = cleanSpeech(text);
    return {
      text,
      left: Math.min(...block.map(r => r.left)), top: Math.min(...block.map(r => r.top)),
      right: Math.max(...block.map(r => r.right)), bottom: Math.max(...block.map(r => r.bottom)),
    };
  });
  // Строки одного облачка — в ОДНУ реплику, обрывки — в соседнюю (как в АПК:
  // mergeBubbles + absorbOrphans).
  return orderBubbles(absorbOrphans(mergeBubbles(lines, bubbleGap, R.mergeHeightRatio)), rtl);
}

/* Склейка переноса: дефис/тире — без пробела. */
function joinBubbleText(a, b) {
  const left = String(a || '').trim(), right = String(b || '').trim();
  if (!left) return right;
  if (!right) return left;
  const last = left[left.length - 1];
  if ('-\u2010\u2011\u2013\u2014\u2015'.includes(last)) return left.slice(0, -1) + right;
  // «БУДЕ.» + «ТЕ ГОВОРИТЬ» → «БУДЕТЕ ГОВОРИТЬ»: перенос слова OCR читает
  // точкой вместо дефиса. Склеиваем, только если получается слово из словаря.
  if (joinBrokenWord(left, right)) return left.replace(/[.\-]$/, '') + right;
  return left + ' ' + right;
}
/* Строки внутри одного облачка: перекрытие по ширине, центры рядом, зазор мал. */
function sameBubble(a, b, bubbleGap, mergeHeightRatio) {
  const aW = a.right - a.left, bW = b.right - b.left;
  const aH = a.bottom - a.top, bH = b.bottom - b.top;
  if (aW <= 0 || bW <= 0 || aH <= 0 || bH <= 0) return false;
  const overlap = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  if (overlap <= 0) return false;
  if (overlap / Math.min(aW, bW) < 0.30) return false;
  const centerShift = Math.abs((a.left + a.right) / 2 - (b.left + b.right) / 2);
  if (centerShift > Math.max(aW, bW) * 0.8) return false;
  const gap = b.top - a.bottom;
  if (gap < -aH * 0.6 || gap > Math.max(aH, bH) * Math.max(1.2, bubbleGap)) return false;
  if (aH > aW * 3 || bH > bW * 3) return false;   // вертикальные колонки — не строки
  // Крупное название и мелкие титры — РАЗНЫЕ реплики: иначе рамка рисуется по
  // объединению двух шрифтов и не совпадает с тем, что читается.
  //
  // Сравниваем высоту СТРОКИ (lh), а не всего облачка: у склеенного из двух-трёх
  // строк облачка высота втрое больше одной строки, и проверка «по габаритам»
  // отказывалась приклеить третью строку — облачко рвалось на части
  // («УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ,» / «ТАК ЧТО ЕЁ ВЫСОЧЕСТВО, ДОЛЖНО» / «БЫТЬ, ПРИБЫЛА.»).
  const aLine = a.lh || aH, bLine = b.lh || bH;
  if (Math.max(aLine, bLine) / Math.min(aLine, bLine) > mergeHeightRatio) return false;
  // Тот же потолок высоты, что и в bubblesOf: иначе вторая склейка
  // (mergeBubbles) снова собирала абзацы в блок на полстраницы.
  const mergedTop = Math.min(a.top, b.top), mergedBottom = Math.max(a.bottom, b.bottom);
  if (mergedBottom - mergedTop > 0.22) return false;
  return true;
}
function mergeBubbles(lines, bubbleGap, mergeHeightRatio) {
  if (lines.length <= 1) return lines;
  const sorted = lines.slice().sort((a, b) => a.top - b.top || a.left - b.left);
  const result = [];
  for (const line of sorted) {
    let bestIndex = -1, bestGap = Infinity;
    for (let i = 0; i < result.length; i++) {
      if (!sameBubble(result[i], line, bubbleGap, mergeHeightRatio)) continue;
      const gap = line.top - result[i].bottom;
      if (gap < bestGap) { bestGap = gap; bestIndex = i; }
    }
    if (bestIndex >= 0) {
      const b = result[bestIndex];
      const lineH = line.bottom - line.top;
      result[bestIndex] = {
        text: joinBubbleText(b.text, line.text),
        left: Math.min(b.left, line.left), top: Math.min(b.top, line.top),
        right: Math.max(b.right, line.right), bottom: Math.max(b.bottom, line.bottom),
        // Типичная высота строки внутри облачка — по ней и решается, можно ли
        // приклеить следующую строку.
        lh: Math.min(b.lh || (b.bottom - b.top), lineH),
      };
    } else result.push({ ...line, lh: line.bottom - line.top });
  }
  return result;
}
/* Обрывок в 1-3 буквы внутри чужой рамки — часть её слова. */
function absorbOrphans(bubbles) {
  if (bubbles.length <= 1) return bubbles;
  const alive = bubbles.slice();
  for (let pass = 0; pass < 4; pass++) {
    let merged = false;
    for (const orphan of alive.slice()) {
      if ((orphan.text.match(/[\p{L}\p{N}]/gu) || []).length > 3) continue;
      const cx = (orphan.left + orphan.right) / 2, cy = (orphan.top + orphan.bottom) / 2;
      let targetIndex = -1, bestDistance = Infinity;
      for (let i = 0; i < alive.length; i++) {
        const b = alive[i];
        if (b === orphan) continue;
        const padX = (b.right - b.left) * 0.12, padY = (b.bottom - b.top) * 0.35;
        if (cx < b.left - padX || cx > b.right + padX) continue;
        if (cy < b.top - padY || cy > b.bottom + padY) continue;
        const d = Math.abs(cy - (b.top + b.bottom) / 2);
        if (d < bestDistance) { bestDistance = d; targetIndex = i; }
      }
      if (targetIndex < 0) continue;
      const b = alive[targetIndex];
      {   // разная высота — разные реплики, обрывок не втягиваем
        const oh = orphan.bottom - orphan.top, bh = b.bottom - b.top;
        if (oh > 0 && bh > 0 && Math.max(oh, bh) / Math.min(oh, bh) > 2.5) continue;
      }
      const above = cy < (b.top + b.bottom) / 2;
      alive[targetIndex] = {
        text: above ? joinBubbleText(orphan.text, b.text) : joinBubbleText(b.text, orphan.text),
        left: Math.min(b.left, orphan.left), top: Math.min(b.top, orphan.top),
        right: Math.max(b.right, orphan.right), bottom: Math.max(b.bottom, orphan.bottom),
      };
      const idx = alive.indexOf(orphan);
      if (idx >= 0) alive.splice(idx, 1);
      merged = true;
      break;
    }
    if (!merged) break;
  }
  return alive;
}
/* Полосы сверху вниз, внутри полосы — по направлению чтения. */
function orderBubbles(bubbles, rtl) {
  if (bubbles.length <= 1) return bubbles;
  const heights = bubbles.map(b => b.bottom - b.top).sort((a, b) => a - b);
  const median = heights[heights.length >> 1];
  const tolerance = Math.max(0.02, median * 0.8);
  const bands = [];
  let bandTop = 0;
  for (const b of bubbles.slice().sort((x, y) => x.top - y.top)) {
    if (bands.length && b.top - bandTop <= tolerance) bands[bands.length - 1].push(b);
    else { bands.push([b]); bandTop = b.top; }
  }
  // rtl: правые реплики первыми (по убыванию left), ltr: по возрастанию.
  return bands.flatMap(band => band.sort((x, y) => rtl ? y.left - x.left : x.left - y.left));
}
/* панели: горизонтальные «желоба» между кадрами (упрощённый KomaPanels) */
/**
 * XY-cut как в KomaAutoRead.splitPanels: горизонтальная пустая полоса делит
 * страницу на верх/низ, вертикальная — на панели, стоящие рядом. Внутри панели
 * разрез повторяется.
 *
 * Раньше здесь была упрощённая версия («зазор больше 1.2 высоты строки»), и она
 * резала ОБЛАЧКО по строкам: «УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ,» / «ТАК ЧТО ЕЁ
 * ВЫСОЧЕСТВО, ДОЛЖНО» / «БЫТЬ, ПРИБЫЛА.» становились тремя репликами.
 */
const Y_CUT = 0.022, X_CUT = 0.035;

function mergeByAxis(group, byY, cut) {
  const sorted = group.slice().sort((a, b) => (byY ? a.top - b.top : a.left - b.left));
  const bands = [];
  for (const rg of sorted) {
    const start = byY ? rg.top : rg.left;
    const end = byY ? rg.bottom : rg.right;
    const last = bands[bands.length - 1];
    if (last && start - last.end <= cut) {
      last.end = Math.max(last.end, end);
      last.items.push(rg);
    } else {
      bands.push({ start, end, items: [rg] });
    }
  }
  return bands.length <= 1 ? [group] : bands.map(b => b.items);
}

function splitPanels(group, rtl = true, depth = 0) {
  if (group.length <= 1 || depth > 12) return [group];
  const heights = group.map(r => r.bottom - r.top).sort((a, b) => a - b);
  const lineHeight = Math.max(0.008, heights[heights.length >> 1]);
  // Порог — от реальной высоты строки на ЭТОЙ странице, а не от накопленной.
  const yCut = Math.max(Y_CUT, lineHeight * 0.9);
  const xCut = Math.max(X_CUT, lineHeight * 0.9);
  const rows = mergeByAxis(group, true, yCut);
  if (rows.length > 1) return rows.flatMap(r => splitPanels(r, rtl, depth + 1));
  const columns = mergeByAxis(group, false, xCut);
  if (columns.length > 1) {
    const ordered = rtl ? columns.slice().reverse() : columns;
    return ordered.flatMap(c => splitPanels(c, rtl, depth + 1));
  }
  return [group];
}
function readingOrder(regions, rtl, onlyCyr, R) {
  // Порядок как в KomaAutoRead: сначала нормализация и починка двойников,
  // ПОТОМ фильтр языка. Иначе фрагмент с латинскими буквами («He6лuцa»)
  // отбрасывался целиком, и слово пропадало из озвучки.
  let source = regions
    .map(r => {
      let text = String(r.text || '').replace(/\u00AD/g, '-').replace(/\s+/g, ' ').trim();
      text = applyWordFixes(text, R.wordFixes);
      const fixed = fixLookalikes(text);
      if (onlyCyr && !isCyr(fixed) && isLookalikeOnly(fixed)) text = fixLookalikesForced(fixed);
      else text = fixed;
      return { ...r, text };
    })
    .filter(r => /[\p{L}\p{N}]/u.test(r.text))
    .filter(r => !onlyCyr || isCyr(r.text));
  if (!source.length) return [];
  const lines = splitPanels(source, rtl, 0).flatMap(p => bubblesOf(p, rtl, R));
  // Языковая починка — на СОБРАННОЙ реплике (как KomaWords.finish): словарь
  // исправляет «ПОШЕВЕАИТЬСЯ» → «ПОШЕВЕЛИТЬСЯ» и выбрасывает строки, которых
  // в русском нет вовсе.
  const result = lines
    .map(l => ({ ...l, text: Words.polish(l.text, R.junkRatio, l.confidence) }))
    .filter(l => l.text && (l.text.match(/\p{L}/gu) || []).length >= 2);
  rescueLostLines(result, source, R);
  markLargeText(result, source);
  return result;
}

/**
 * Бо́льшая часть слов фрагмента уже есть в собранных репликах? Тогда это не
 * потеря, а вариант той же строки, и приклеивать его нельзя.
 */
function mostlyCovered(key, covered) {
  // Перенос слова («РАВНО-» + «ДУШНЫМ»): фрагмент целиком входит в слово
  // реплики — приклеивать нельзя, иначе получается «РАВНОДУШНЫМ. ДУШНЫМ.»
  const flat = key.replace(/ /g, '');
  if (flat.length >= 3 && covered.some(c => c.replace(/ /g, '').includes(flat))) return true;
  const words = key.split(' ').filter(w => w.length >= 3);
  if (!words.length) return covered.some(c => c.includes(key));
  const pool = new Set(covered.join(' ').split(' '));
  const hit = words.filter(w => pool.has(w)).length;
  return hit / words.length >= 0.5;
}

/** Нормализация для сравнения: регистр и пунктуация не важны. */
function normText(s) {
  return String(s || '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
}

/**
 * Страховка от потери строк при склейке: на скриншоте 23:20 из реплики
 * «Как прожить жизнь, будучи старшей сестрой тирана.» пропал конец — строка
 * распозналась («Сесмой тирана»), прошла чистку, но не попала ни в одну
 * реплику. Правило «реплику не резать» важнее аккуратности склейки: любой
 * осмысленный регион, которого нет в готовых репликах, приклеиваем к
 * ближайшей по вертикали (и только если он рядом, не дальше 18 % страницы).
 */
function rescueLostLines(result, source, R) {
  if (!result.length) return;
  const covered = result.map(l => normText(l.text));
  for (const r of source) {
    const t = String(Words.polish(r.text, R.junkRatio, r.confidence) || '').trim();
    if (!t) continue;
    const key = normText(t);
    if (key.length < 3) continue;
    // Уже внутри реплики? Сравниваем ПО СЛОВАМ, а не по префиксу: OCR на
    // одной и той же строке даёт варианты («ТАК ЧТО ЕЁ ВАСО ЧИТАТЬ ВСТРЕЧУ»),
    // и по префиксу страховка приклеивала уже собранное — получались дубли
    // («УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ…» дважды).
    if (mostlyCovered(key, covered)) continue;
    const rc = (r.top + r.bottom) / 2;
    let best = -1, bestD = Infinity;
    result.forEach((l, idx) => {
      const d = rc < l.top ? l.top - rc : (rc > l.bottom ? rc - l.bottom : 0);
      if (d < bestD) { bestD = d; best = idx; }
    });
    if (best < 0 || bestD > 0.18) continue;
    const l = result[best];
    const above = rc < (l.top + l.bottom) / 2;
    result[best] = {
      ...l,
      text: above ? (t + ' ' + l.text) : (l.text + ' ' + t),
      left: Math.min(l.left, r.left), top: Math.min(l.top, r.top),
      right: Math.max(l.right, r.right), bottom: Math.max(l.bottom, r.bottom),
      rescued: true,
    };
    covered.push(normText(result[best].text));
  }
}

/**
 * Крупный текст (титул, каллиграфия) помечаем: он показывается другим цветом,
 * чтобы не путать его с репликами. Отличие по кеглю: высота строки заметно
 * больше типичной для страницы.
 */
function markLargeText(result, source) {
  if (source.length < 3 || !result.length) return;
  const heights = source.map(r => r.bottom - r.top).sort((a, b) => a - b);
  const medH = heights[heights.length >> 1];
  if (!medH) return;
  for (const l of result) {
    const inside = source.filter(r => {
      const cy = (r.top + r.bottom) / 2;
      return cy >= l.top && cy <= l.bottom;
    });
    if (!inside.length) continue;
    const hs = inside.map(r => r.bottom - r.top).sort((a, b) => a - b);
    const h = hs[hs.length >> 1];
    if (h > medH * 1.5) l.large = true;
  }
}

/* ───────────────────────── 7. Полосы экрана (KomaBands) ───────────────────────── */
function bandsOf(viewportFraction, R) {
  const whole = R.wholeThreshold, overlap = R.bandOverlap, max = Math.round(R.bandsMax);
  if (!viewportFraction || viewportFraction <= 0 || viewportFraction >= whole) {
    return [{ index: 0, top: 0, bottom: 1, whole: true }];
  }
  const visible = clamp(viewportFraction, 0.12, whole);
  const bands = [];
  let top = 0, idx = 0;
  while (idx < max) {
    const bottom = Math.min(1, top + visible);
    bands.push({ index: idx, top, bottom, whole: false });
    if (bottom >= 0.999) break;
    top = Math.max(0.0001, bottom - visible * overlap);
    idx++;
  }
  const last = bands[bands.length - 1];
  if (last && last.bottom < 0.999) last.bottom = 1;
  return bands;
}
function cutAtBandBottom(line, band, cutMargin) {
  if (band.whole) return false;
  if (band.bottom <= line.bottom - 0.001) return false;
  if (line.bottom < band.bottom - cutMargin) return false;
  const t = line.text.trimEnd();
  if (!t) return false;
  return !/[.!?…"»)]$/.test(t);
}

/**
 * ─── Google Lens как ОТДЕЛЬНЫЙ движок ────────────────────────────────────────
 *
 * Зачем. Своя модель на манге даёт 4,8 % CER против 2,7 % у штатной, а на
 * чужих страницах (журналы 1988–2001 из archive.org) читалка находит меньше
 * трети строк — шрифт, вёрстка и печать другие. Lens читает такое заметно
 * лучше, но НЕ умеет работать офлайн и отправляет картинку в Google.
 *
 * Как устроено и почему именно так:
 *  • Модели и текст по-прежнему обрабатываются локально, а Lens — это ЯВНО
 *    включаемый второй движок. Пока режим «локально» (по умолчанию), ни один
 *    байт картинки никуда не уходит: send() в этом режиме даже не строит форму.
 *  • Отправка — обычная отправка ФОРМЫ в новую вкладку (`enctype=multipart`,
 *    поле `encoded_image`), а не fetch: навигацию окна CORS не ограничивает,
 *    поэтому это работает и из файла `file://`, где XHR к чужому домену
 *    невозможен. Проверено 28.10 в Chromium: Lens принимает файл и отвечает
 *    страницей результатов (из песочницы IP попал под проверку на робота, но
 *    сам аплоад прошёл — в обычном браузере открывается страница «Текст»).
 *  • Прочитать результат из другой вкладки нельзя (чужой домен). Поэтому
 *    текст возвращается ЧЕРЕЗ ЧЕЛОВЕКА: «Вставить из буфера» одной кнопкой
 *    (navigator.clipboard.readText в жесте) или вставкой в поле. Дальше эти
 *    строки живут как обычные реплики страницы: рамки, порядок, озвучка.
 *  • Никаких confirm()/prompt() — только тост и шторка.
 */
const LENS = {
  mode: 'local',                     // local | lens
  action: 'https://lens.google.com/v3/upload?hl=ru&ep=ccm',
  lastSentAt: 0, lastSentPage: null,
  pendingPage: null,                 // страница, для которой ждём текст от Lens

  isLens() { return this.mode === 'lens'; },

  /** Прочитать сохранённый выбор движка. */
  async load() {
    try {
      const row = await DB.get('kv', 'engine:mode');
      this.mode = (row && row.v === 'lens') ? 'lens' : 'local';
    } catch (e) { this.mode = 'local'; }
    return this.mode;
  },

  /** Сохранить выбор. Кнопка «Движок: …» работает без confirm(). */
  async setMode(mode) {
    this.mode = mode === 'lens' ? 'lens' : 'local';
    try { await DB.put('kv', { k: 'engine:mode', v: this.mode }); } catch (e) { /* некуда сохранить — не беда */ }
    return this.mode;
  },

  /**
   * Картинка страницы (или видимой полосы) → файл для формы.
   * Синхронно через toDataURL: отправка идёт из жеста пользователя, и ждать
   * промис toBlob нельзя — браузер уже считает жест «законченным» и может
   * заблокировать открытие вкладки.
   */
  toFile(canvas, name) {
    const url = canvas.toDataURL('image/png');
    const b64 = url.slice(url.indexOf(',') + 1);
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new File([bytes], name || 'page.png', { type: 'image/png' });
  },

  /**
   * Отправить страницу в Lens новой вкладкой. Возвращает { ok, reason }.
   * В режиме «локально» ничего не отправляет — это и есть защита от случайной
   * утечки картинки в сеть.
   */
  send(canvas, opts = {}) {
    if (!this.isLens() && !opts.force) {
      return { ok: false, reason: 'движок «локально» — картинка никуда не отправлялась' };
    }
    if (!canvas || !canvas.width) return { ok: false, reason: 'страница ещё не загрузилась' };
    try {
      const file = this.toFile(canvas, 'koma-page.png');
      const dt = new DataTransfer();
      dt.items.add(file);
      const form = document.createElement('form');
      form.method = 'POST';
      form.enctype = 'multipart/form-data';
      form.target = '_blank';                 // новая вкладка, читалка остаётся
      form.action = this.action;
      form.style.display = 'none';
      const input = document.createElement('input');
      input.type = 'file';
      input.name = 'encoded_image';
      input.id = 'lensFile';
      input.files = dt.files;                 // так файл и передаётся без выбора вручную
      form.appendChild(input);
      const dim = document.createElement('input');
      dim.type = 'hidden';
      dim.name = 'processed_image_dimensions';
      dim.value = canvas.width + ',' + canvas.height;
      form.appendChild(dim);
      document.body.appendChild(form);
      form.submit();
      setTimeout(() => form.remove(), 4000);  // разметку за собой убираем
      this.lastSentAt = Date.now();
      this.pendingPage = opts.page ?? null;
      return { ok: true, page: this.pendingPage, size: [canvas.width, canvas.height] };
    } catch (e) {
      return { ok: false, reason: String((e && e.message) || e) };
    }
  },

  /**
   * Текст из Lens → реплики страницы. Геометрия приблизительная (Lens не отдаёт
   * координаты нам), зато порядок сверху вниз сохраняется, рамки показывают
   * номера реплик, и озвучка работает тем же путём, что всегда.
   */
  textToLines(text) {
    // Принимаем и строку, и массив строк (массив удобнее вызывать из тестов и
    // из кода: String([...]) склеил бы всё через запятую в одну «строку»).
    const src = Array.isArray(text) ? text.join('\n') : String(text || '');
    const rows = src
      .split(/\r?\n/)
      .map(s => s.replace(/\s+/g, ' ').trim())
      .filter(s => (s.match(/\p{L}/gu) || []).length >= 2);
    const n = rows.length || 1;
    return rows.map((t, i) => ({
      text: t,
      left: 0.04, right: 0.96,
      top: +(i / n).toFixed(4), bottom: +(((i + 1) / n) - 0.002).toFixed(4),
      confidence: 1, large: false, bandTop: 0, fromLens: true,
    }));
  },
};
