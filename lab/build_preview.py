#!/usr/bin/env python3
"""Собирает preview.html — страницу, которая работает во встроенном предпросмотре.

Предпросмотр файлов не имеет доступа к сети и к соседним файлам, поэтому здесь
всё вшито внутрь: картинки (data URI) и заранее посчитанный разбор страниц в
двух вариантах. Живое распознавание остаётся на сервере (lab/server.py).
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parent
data = json.loads((ROOT / "preview_data.json").read_text(encoding="utf-8"))

pages = []
for name, entry in data.items():
    # картинку ужимаем до ширины 700 px: предпросмотр не любит мегабайты
    image = Image.open(ROOT / "pages" / name)
    width = 700
    if image.width > width:
        image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=82)
    encoded = base64.b64encode(buffer.getvalue()).decode()
    pages.append({
        "name": name,
        "width": image.width,
        "height": image.height,
        "data": "data:image/jpeg;base64," + encoded,
        "variants": entry["variants"],
    })
    print(f"{name}: {image.size}, {len(encoded) // 1024} КБ base64")

payload = json.dumps(pages, ensure_ascii=False)
html = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KOMA lab — предпросмотр</title>
<style>
  :root{--bg:#14161a;--panel:#1c1f26;--panel2:#232833;--line:#2f3644;--text:#e8ebf2;--muted:#9aa3b5;--accent:#ff9838;--ok:#5ec27a}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
  header{display:flex;gap:12px;align-items:center;padding:12px 18px;border-bottom:1px solid var(--line);background:var(--panel);flex-wrap:wrap}
  header h1{font-size:16px;margin:0}
  .tag{font-size:12px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:2px 9px}
  main{display:grid;grid-template-columns:minmax(280px,1fr) minmax(320px,480px);gap:18px;padding:18px;align-items:start}
  @media (max-width:960px){main{grid-template-columns:1fr}}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px}
  .card h2{font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:0 0 10px}
  .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
  button{background:var(--panel2);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:6px 11px;font-size:13.5px;cursor:pointer}
  button.on{background:var(--accent);border-color:var(--accent);color:#20160c;font-weight:600}
  .stage{position:relative;background:#0d0f12;border-radius:12px;overflow:hidden;line-height:0;margin-top:12px}
  .stage img{width:100%;height:auto;display:block}
  .stage canvas{position:absolute;inset:0;width:100%;height:100%}
  ol.lines{list-style:none;margin:0;padding:0;counter-reset:n}
  ol.lines li{counter-increment:n;display:flex;gap:10px;padding:8px 4px;border-bottom:1px solid #262c37;cursor:pointer}
  ol.lines li:last-child{border-bottom:none}
  ol.lines li::before{content:counter(n);color:var(--accent);min-width:18px;text-align:right}
  .meta{color:var(--muted);font-size:12px;margin-top:3px}
  .hint{color:var(--muted);font-size:12.5px;margin-top:8px}
  .note{border:1px solid #6b5320;background:#2a2113;color:#f0e2c9;border-radius:12px;padding:10px 12px;font-size:13.5px;margin-bottom:12px}
  .note a{color:var(--accent)}
</style>
</head>
<body>
<header>
  <h1>KOMA lab — предпросмотр</h1>
  <span class="tag">разбор вшит в файл · без сети и без сервера</span>
  <span id="stats" class="tag"></span>
</header>
<main>
  <section class="card">
    <div class="note">
      Это статический снимок: страницы и результаты распознавания уже внутри файла.
      Живое распознавание своих страниц работает на сервере — <code>python3 lab/server.py 8000</code>,
      затем <b>http://localhost:8000</b> (или живое превью процесса «KOMA lab»).
    </div>
    <h2>Страница</h2>
    <div class="row" id="pages"></div>
    <h2 style="margin-top:14px">Вариант разбора</h2>
    <div class="row" id="variants">
      <button data-variant="2.9.7" class="on">2.9.7 — строки по проекции</button>
      <button data-variant="2.9.4">2.9.4 — бокс целиком</button>
    </div>
    <div class="stage"><img id="preview" alt=""><canvas id="overlay"></canvas></div>
  </section>
  <section class="card">
    <h2>Как читается</h2>
    <div id="out"></div>
    <div class="hint">Наведите строку — подсветится её рамка на странице. Сравните варианты: видно, где теряются слова.</div>
  </section>
</main>
<script>
const PAGES = __PAYLOAD__;
let pageIndex = 0, variant = '2.9.7', highlight = null;

const $ = (id) => document.getElementById(id);

function currentPage() { return PAGES[pageIndex]; }
function currentLines() { return currentPage().variants[variant].lines; }

function buildPageButtons() {
  const box = $('pages');
  box.innerHTML = '';
  PAGES.forEach((page, index) => {
    const button = document.createElement('button');
    button.textContent = page.name.replace(/\\.(jpg|png)$/i, '');
    button.className = index === pageIndex ? 'on' : '';
    button.addEventListener('click', () => { pageIndex = index; refresh(); });
    box.appendChild(button);
  });
}

document.querySelectorAll('#variants button').forEach((button) => {
  button.addEventListener('click', () => {
    variant = button.dataset.variant;
    document.querySelectorAll('#variants button').forEach((b) => b.classList.toggle('on', b === button));
    refresh();
  });
});

function refresh() {
  buildPageButtons();
  const page = currentPage();
  $('preview').src = page.data;
  $('preview').style.display = 'block';
  $('stats').textContent = `фрагментов ${page.variants[variant].regions} · реплик ${page.variants[variant].lines.length}`;
  const lines = currentLines();
  const out = $('out');
  if (!lines.length) {
    out.innerHTML = '<div class="hint">Реплик нет.</div>';
  } else {
    const list = document.createElement('ol');
    list.className = 'lines';
    lines.forEach((line) => {
      const item = document.createElement('li');
      const text = document.createElement('div');
      text.textContent = line.text;
      const meta = document.createElement('div');
      meta.className = 'meta';
      meta.textContent = `x ${Math.round(line.l * 100)}–${Math.round(line.r * 100)}% · y ${Math.round(line.t * 100)}–${Math.round(line.b * 100)}%`;
      text.appendChild(meta);
      item.appendChild(text);
      item.addEventListener('mouseenter', () => { highlight = line; draw(); });
      item.addEventListener('mouseleave', () => { highlight = null; draw(); });
      item.addEventListener('click', () => navigator.clipboard?.writeText(line.text));
      list.appendChild(item);
    });
    out.innerHTML = '';
    out.appendChild(list);
  }
  $('preview').onload = draw;
  if ($('preview').complete) draw();
}

function draw() {
  const img = $('preview');
  const canvas = $('overlay');
  if (!img.naturalWidth) return;
  canvas.width = img.clientWidth;
  canvas.height = img.clientHeight;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!highlight) return;
  const sx = canvas.width / img.naturalWidth, sy = canvas.height / img.naturalHeight;
  const x = highlight.l * img.naturalWidth * sx, y = highlight.t * img.naturalHeight * sy;
  const w = (highlight.r - highlight.l) * img.naturalWidth * sx, h = (highlight.b - highlight.t) * img.naturalHeight * sy;
  ctx.fillStyle = 'rgba(255,152,56,.25)';
  ctx.fillRect(x, y, w, h);
  ctx.strokeStyle = '#ff9838';
  ctx.lineWidth = 2.5;
  ctx.strokeRect(x, y, w, h);
}

window.addEventListener('resize', draw);
refresh();
</script>
</body>
</html>
"""
html = html.replace("__PAYLOAD__", payload)
target = ROOT / "preview.html"
target.write_text(html, encoding="utf-8")
print(f"preview.html: {target.stat().st_size / 1024:.0f} КБ")
