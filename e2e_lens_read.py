#!/usr/bin/env python3
"""Авточтение текста из Google Lens: помечает и показывает озвучиваемую строку?

  python3 e2e_lens_read.py

В головном Chromium голосов нет вовсе, поэтому синтез подменяется честной
заглушкой: она зовёт onstart/onend ровно как браузер и записывает, ЧТО и в
каком порядке её попросили сказать. Проверяем именно читалку, а не голос:

  1. Авточтение берёт строки из Lens по порядку (сверху вниз), каждую один раз.
  2. Пока строка звучит, её рамка помечена «cur» (та, что озвучивается), а на
     ленте «где читает» виден её текст.
  3. После озвучки строка помечается прочитанной: рамка «done», в шторке
     «Текст страницы» у неё отметка ✓.
  4. Рамки текста из Lens помечены как приблизительные (пунктир + номер), чтобы
     не выглядели точным местом на картинке.
  5. Дочитав полосу, читалка не зачитывает те же строки второй раз.
"""
import base64
import os
import sys

from playwright.sync_api import sync_playwright

HTML = os.environ.get('HTML', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'koma-web.html'))
IMG = '/home/user/uploads/Screenshot_20261023-131019.jpg'
MODELS = '/home/user/koma_models'


def b64(path):
    return base64.b64encode(open(path, 'rb').read()).decode()

LENS_TEXT = [
    'ДА, ПОЧЕМУ И НЕТ?',
    'ПОЖАЛУЙСТА, ПОЗВОЛЬ МНЕ ДО ОТВАЛА ПОЕСТЬ ВКУСНОЙ ЕДЫ.',
    'ПОЖАЛУЙСТА, Я СДЕЛАЮ ЧТО УГОДНО, ЧТОБЫ ЭТА ШТУКА ОТЦЕПИЛАСЬ.',
    'ПОЖАЛУЙСТА, СНИМИ С ХАНЫ ЭТО ПРОКЛЯТИЕ И ПОМОГИ МНЕ.',
]

fails = []


def chk(name, cond, extra=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ((' · ' + repr(extra)) if extra and not cond else ''))
    if not cond:
        fails.append(name)


SPEECH_STUB = """
window.__said = [];            // что попросили сказать, по порядку
window.__timeline = [];        // (текст, классы рамок в этот момент, лента)
(function () {
  const voices = [{ name: 'Тест RU', lang: 'ru-RU', voiceURI: 'test-ru', default: true }];
  let speaking = false;
  // window.speechSynthesis — атрибут только для чтения (геттер на Window),
  // обычное присваивание молча не срабатывает. Поэтому defineProperty.
  const stub = {
    getVoices: () => voices,
    onvoiceschanged: null,
    get speaking() { return speaking; },
    pending: false,
    speak(u) {
      window.__said.push(u.text);
      speaking = true;
      setTimeout(() => { if (u.onstart) u.onstart(); }, 30);
      // Пока «звучит» — записываем, что видно на экране.
      const t = setInterval(() => {
        const frames = Array.from(document.querySelectorAll('.frame'));
        const cur = frames.find(f => f.classList.contains('cur'));
        const now = document.getElementById('nowLine');
        window.__timeline.push({
          text: u.text,
          cur: cur ? { idx: frames.indexOf(cur), approx: cur.classList.contains('approx') } : null,
          nowLine: now && now.style.display !== 'none' ? now.textContent : null,
        });
      }, 60);
      setTimeout(() => {
        clearInterval(t); speaking = false;
        if (u.onend) u.onend();
      }, 420);
    },
    cancel() { speaking = false; },
    pause() {}, resume() {},
  };
  Object.defineProperty(window, 'speechSynthesis', { value: stub, configurable: true });
  return true;
})();
"""


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--no-sandbox', '--allow-file-access-from-files'])
        page = browser.new_page(viewport={'width': 412, 'height': 800})
        errs = []
        page.on('pageerror', lambda e: errs.append(str(e)[:200]))
        page.goto('file://' + HTML)
        page.wait_for_timeout(1400)

        # страница в читалке (модели не нужны: текст даёт Lens)
        page.evaluate("""async (b64img) => {
            const img = new Image();
            img.src = 'data:image/jpeg;base64,' + b64img;
            await img.decode();
            const c = makeCanvas(img.naturalWidth, img.naturalHeight);
            c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
            Reader.pages = [{ name: 'тест', img: c, w: c.width, h: c.height }];
            Reader.canvases = [c];
            Reader.page = 0;
            Reader.mode = 'vertical';
            document.getElementById('strip').innerHTML =
              '<div class="pagewrap" data-page="0" style="position:relative;height:600px">' +
              '<div data-frames="0" style="position:absolute;inset:0"></div></div>';
            Reader.frames = true;
            LENS.mode = 'lens';
            LENS.pendingPage = 0;
        }""", base64.b64encode(open(IMG, 'rb').read()).decode())
        page.evaluate(SPEECH_STUB)

        n = page.evaluate("async (t) => (await applyLensText(0, t)).lines", '\n'.join(LENS_TEXT))
        chk('текст из Lens принят в страницу', n == 4, n)

        frames = page.evaluate("""() => Array.from(document.querySelectorAll('.frame')).map(f => ({
            approx: f.classList.contains('approx'),
            num: (f.querySelector('.fnum') || {}).textContent || null }))""")
        chk('рамок столько же, сколько реплик', len(frames) == 4, len(frames))
        # Без моделей детектор недоступен — рамки обязаны быть «примерными»
        # (пунктир + номер), чтобы не притворяться точным местом на картинке.
        chk('без моделей рамки помечены как примерные', all(f['approx'] for f in frames), frames)
        chk('на рамках есть номера по порядку', [f['num'] for f in frames] == ['1', '2', '3', '4'],
            [f['num'] for f in frames])

        # авточтение
        page.evaluate("""() => { Reader.band = { top: 0, bottom: 1, whole: true };
            Reader.stopped = false; TTS.stopped = false; TTS.readVisible(); }""")
        page.wait_for_timeout(3500)

        said = page.evaluate("window.__said.slice()")
        chk('озвучены все 4 реплики и ровно по разу', len(said) == 4, said)
        chk('порядок озвучки = порядок строк из Lens', said == LENS_TEXT, said)

        spoken = page.evaluate("Array.from(Reader.spoken.values ? Reader.spoken.values() : [])")
        chk('все 4 строки помечены прочитанными', len(spoken) == 4, spoken)

        timeline = page.evaluate("window.__timeline")
        with_cur = [t for t in timeline if t['cur']]
        chk('во время озвучки видна рамка «озвучивается»', len(with_cur) > 0, len(timeline))
        # рамка «cur» должна соответствовать той строке, что звучит
        order = {t: i for i, t in enumerate(LENS_TEXT)}
        wrong = [t for t in with_cur if t['cur']['idx'] != order.get(t['text'])]
        chk('подсвечена именно озвучиваемая строка', not wrong, wrong[:2])
        chk('подсветка идёт по строкам сверху вниз',
            [t['cur']['idx'] for t in with_cur] == sorted(t['cur']['idx'] for t in with_cur),
            [t['cur']['idx'] for t in with_cur])

        lenta = [t for t in timeline if t['nowLine']]
        chk('лента «где читает» показывает текст реплики', len(lenta) > 0, len(timeline))
        chk('на ленте именно то, что звучит', all(t['text'].startswith(t['nowLine'][:6]) or
                                                t['nowLine'].replace(' ', '').startswith(t['text'][:6].replace(' ', ''))
                                                for t in lenta), lenta[:2])

        done = page.evaluate("Array.from(document.querySelectorAll('.frame')).map(f => f.classList.contains('done'))")
        chk('после озвучки все рамки помечены прочитанными', all(done), done)

        # повторного чтения тех же строк быть не должно
        page.evaluate("""() => { window.__said = []; TTS.readVisible(); }""")
        page.wait_for_timeout(1200)
        again = page.evaluate("window.__said.slice()")
        chk('те же строки второй раз не зачитываются', all(t not in LENS_TEXT for t in again) or not again,
            again)

        # 6. Когда модели есть, рамки ставятся по облачкам, найденным локальным
        #    детектором, а не равными полосами на всю ширину.
        print('· с моделями: рамки по облачкам')
        page.evaluate("""async ([det, rec, dict]) => {
            const t = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
            await DB.put('kv', { k: 'model:det', v: t(det).buffer });
            await DB.put('kv', { k: 'model:rec', v: t(rec).buffer });
            await DB.put('kv', { k: 'model:dict', v: new TextDecoder().decode(t(dict)) });
            return await OCR.loadModels();
        }""", [b64(os.path.join(MODELS, 'koma_det.onnx')), b64(os.path.join(MODELS, 'koma_rec.onnx')),
               b64(os.path.join(MODELS, 'koma_dict.txt'))])
        res = page.evaluate("async (t) => await applyLensText(0, t)", '\n'.join(LENS_TEXT))
        chk('детектор расставил рамки', res.get('placed') == 'det', res)
        geo = page.evaluate("""() => Array.from(document.querySelectorAll('.frame')).map(f => ({
            approx: f.classList.contains('approx'),
            w: parseFloat(f.style.width), top: parseFloat(f.style.top) }))""")
        chk('рамки всё равно помечены как примерные', all(g['approx'] for g in geo), geo)
        chk('рамки стоят на облачках, а не на всю ширину',
            all(g['w'] < 95 for g in geo), [g['w'] for g in geo])
        chk('рамки не совпадают с равными полосами',
            len({round(g['top'], 2) for g in geo}) > 1 and
            any(abs(g['top'] - i * 0.25) > 0.02 for i, g in enumerate(geo)),
            [round(g['top'], 3) for g in geo])

        chk('ошибок JS нет', not errs, errs[:2])
        browser.close()

    print('\nИТОГ: ' + ('ВСЁ ПРОШЛО' if not fails else f'ПАДЕНИЙ {len(fails)}: ' + ', '.join(fails)))
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
