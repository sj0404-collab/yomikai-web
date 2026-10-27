from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = b.new_page(viewport={'width':412,'height':800})
    errs=[]; pg.on('pageerror', lambda e: errs.append(str(e)[:160]))
    pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(1500)
    r = pg.evaluate("""async () => {
        const out = {};
        $('#playBar').style.display = 'flex';
        const text = 'УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ';
        SpeakCursor.start(text, 1.0);
        await new Promise(r => setTimeout(r, 320));
        out.letters = document.querySelectorAll('#nowLine .ch').length;
        out.spokenA = document.querySelectorAll('#nowLine .ch.sp').length;
        out.curA = document.querySelectorAll('#nowLine .ch.cur').length;
        out.visibleA = getComputedStyle($('#nowLine')).display;
        const cur = document.querySelector('#nowLine .ch.cur');
        out.shadow = cur ? getComputedStyle(cur).textShadow : '';
        // точная граница слова: «НАЧИНАТЬ» — 9-й символ
        SpeakCursor.boundary(9);
        await new Promise(r => setTimeout(r, 120));
        out.spokenB = document.querySelectorAll('#nowLine .ch.sp').length;
        out.curText = document.querySelector('#nowLine .ch.cur')?.textContent || '';
        SpeakCursor.stop();
        out.hidden = getComputedStyle($('#nowLine')).display;
        // и ещё раз — показать для скриншота
        SpeakCursor.start(text, 1.0);
        await new Promise(r => setTimeout(r, 900));
        return out;
    }""")
    pg.screenshot(path='/home/user/koma-bench/shot-shadow.png')
    print(r); print('errors:', errs[:2])
    b.close()
