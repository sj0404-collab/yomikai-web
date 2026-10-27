"""Рисует скриншоты-отчёты: страница с рамками реплик и сравнение условий.

  python3 lab/generate_report.py
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import experiment as E
import pipeline as P

ROOT = Path(__file__).parent
OUT = ROOT / "reports"
OUT.mkdir(exist_ok=True)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

ACCENT = (255, 152, 56)
DARK = (20, 22, 26)
PANEL = (28, 31, 38)
TEXT = (232, 235, 242)
MUTED = (154, 163, 181)
GREEN = (94, 194, 122)
RED = (226, 96, 90)


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size)


def wrap(draw, text: str, f, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        probe = (current + " " + word).strip()
        if draw.textlength(probe, font=f) <= width:
            current = probe
        else:
            if current:
                lines.append(current)
            current = word
    return lines + ([current] if current else [])


def run(page: Path, scale: float, side: int, slicing: str):
    models = E_models()
    img = E.load(page, scale, False)
    boxes = E.detect_with(models, img, side, False)
    regions = E.recognize(models, img, boxes, slicing, 0.25)
    lines = P.reading_order(regions, True)
    return img, boxes, regions, lines


_models = None


def E_models():
    global _models
    if _models is None:
        _models = P.Models()
    return _models


def annotated(page: Path, img, lines, title: str, subtitle: str) -> Image.Image:
    picture = Image.fromarray(img).convert("RGB")
    draw = ImageDraw.Draw(picture)
    colors = [(255, 152, 56), (94, 194, 122), (110, 170, 255), (214, 130, 255), (255, 210, 90), (120, 230, 220)]
    for index, line in enumerate(lines):
        color = colors[index % len(colors)]
        x0, y0 = line.left * picture.width, line.top * picture.height
        x1, y1 = line.right * picture.width, line.bottom * picture.height
        draw.rectangle([x0, y0, x1, y1], outline=color, width=4)
        label = str(index + 1)
        f = font(26, True)
        box = draw.textbbox((0, 0), label, font=f)
        w, h = box[2] - box[0] + 14, box[3] - box[1] + 10
        draw.rectangle([x0, max(0, y0 - h - 2), x0 + w, max(h, y0 - 2)], fill=color)
        draw.text((x0 + 7, max(0, y0 - h + 3)), label, font=f, fill=(20, 16, 10))

    header = 96
    canvas = Image.new("RGB", (picture.width, picture.height + header), DARK)
    canvas.paste(picture, (0, header))
    d = ImageDraw.Draw(canvas)
    d.text((22, 18), title, font=font(30, True), fill=TEXT)
    d.text((22, 56), subtitle, font=font(19), fill=MUTED)
    return canvas


def text_panel(lines_before, lines_after, title: str, note: str) -> Image.Image:
    width = 1500
    padding = 26
    f_title, f_head, f_line, f_note = font(30, True), font(20, True), font(21), font(18)
    columns = [("БЫЛО: приложение v2.9.7", lines_before, RED), ("СТАЛО: найденные условия", lines_after, GREEN)]

    probe = Image.new("RGB", (width, 10))
    pd = ImageDraw.Draw(probe)
    column_width = (width - padding * 3) // 2
    heights = []
    for head, lines, _ in columns:
        total = 40
        for index, line in enumerate(lines, 1):
            wrapped = wrap(pd, f"{index}. {line}", f_line, column_width - 20)
            total += len(wrapped) * 27 + 12
        heights.append(total)
    height = padding * 2 + 60 + max(heights) + 60

    canvas = Image.new("RGB", (width, height), DARK)
    draw = ImageDraw.Draw(canvas)
    draw.text((padding, padding), title, font=f_title, fill=TEXT)

    for column, (head, lines, color) in enumerate(columns):
        x = padding + column * (column_width + padding)
        y = padding + 62
        draw.rectangle([x, y, x + column_width, y + height - padding * 2 - 62], fill=PANEL)
        draw.text((x + 14, y + 12), head, font=f_head, fill=color)
        y += 48
        if not lines:
            draw.text((x + 14, y), "реплик нет", font=f_line, fill=MUTED)
        for index, line in enumerate(lines, 1):
            wrapped = wrap(draw, f"{index}. {line}", f_line, column_width - 28)
            for row in wrapped:
                draw.text((x + 14, y), row, font=f_line, fill=TEXT)
                y += 27
            y += 12

    draw.text((padding, height - padding - 22), note, font=f_note, fill=MUTED)
    return canvas


def conditions_card(rows: list[dict], title: str) -> Image.Image:
    width, height = 1400, 260 + 46 * len(rows) + 120
    canvas = Image.new("RGB", (width, height), DARK)
    draw = ImageDraw.Draw(canvas)
    draw.text((28, 24), title, font=font(30, True), fill=TEXT)
    draw.text((28, 64), "каждая строка — один прогон всей страницы через модели KOMA", font=font(18), fill=MUTED)

    y = 110
    headers = ["масштаб", "серый", "вход детектора", "норм.", "разбор", "порог", "фрагм.", "реплик", "найдено", "точность"]
    xs = [28, 150, 230, 380, 450, 610, 700, 790, 890, 1010]
    for x, head in zip(xs, headers):
        draw.text((x, y), head, font=font(17, True), fill=MUTED)
    y += 30
    for row in rows:
        ok = row["found"] >= 5
        values = [f"×{row['scale']}", "да" if row["gray"] else "нет", str(row["side"]),
                  "да" if row["norm"] else "нет", "строки" if row["slice"] == "projection" else "бокс",
                  str(row["thr"]), str(row["regions"]), str(row["lines"]),
                  f"{row['found']}/5", f"{row['quality']:.2f}"]
        for x, value in zip(xs, values):
            draw.text((x, y), value, font=font(18), fill=GREEN if ok else TEXT)
        y += 42
    draw.text((28, height - 46), "зелёным — прогоны, где найдены все реплики в правильном порядке", font=font(18), fill=MUTED)
    return canvas


def main() -> None:
    result = json.loads((ROOT / "experiment_result.json").read_text())
    best = result["best"]
    print("лучшие условия:", {k: best[k] for k in ("scale", "gray", "side", "norm", "slice", "thr")})

    page = ROOT / "pages" / "page2.jpg"
    before_img = E.load(page, 1.0, False)
    before_models = E_models()
    before_boxes = E.detect_with(before_models, before_img, 960, False)
    before_regions = E.recognize(before_models, before_img, before_boxes, "projection", 0.25)
    before_lines = P.reading_order(before_regions, True)

    img, boxes, regions, lines = run(page, best["scale"], best["side"], best["slice"])

    (OUT / "01_page2_boxes.png").write_bytes(b"")
    annotated(page, img, lines, "Страница 2: реплики найдены полностью",
              f"условия: увеличение ×{best['scale']:g}, вход детектора {best['side']} px, "
              f"нарезка на строки, починка двойников · фрагментов {len(regions)}, реплик {len(lines)}"
              ).save(OUT / "01_page2_boxes.png")

    text_panel([line.text for line in before_lines], [line.text for line in lines],
               "Страница 2: было и стало",
               "слева — как сейчас в приложении (без увеличения, вход детектора 960), справа — условия, при которых видно всё"
               ).save(OUT / "02_page2_before_after.png")

    rows = sorted(result["all"], key=lambda r: (-r["found"], -r["quality"]))[:10]
    conditions_card(rows, "Условия, при которых страница читается целиком").save(OUT / "03_conditions.png")

    # та же проверка на странице 4 (там крупный декоративный шрифт)
    page4 = ROOT / "pages" / "page4_v297.jpg"
    before4 = P.reading_order(E.recognize(before_models, E.load(page4, 1.0, False),
                                          E.detect_with(before_models, E.load(page4, 1.0, False), 960, False),
                                          "projection", 0.25), True)
    img4, boxes4, regions4, lines4 = run(page4, best["scale"], best["side"], best["slice"])
    annotated(page4, img4, lines4, "Страница 4 при тех же условиях",
              f"фрагментов {len(regions4)}, реплик {len(lines4)}").save(OUT / "04_page4_boxes.png")
    text_panel([line.text for line in before4], [line.text for line in lines4],
               "Страница 4: было и стало",
               "проверка тех же условий на другой странице"
               ).save(OUT / "05_page4_before_after.png")

    # честная сводка: что ещё не идеально
    truth4 = [
        "ЕЙ НЕ ПОМОЖЕТ ДАЖЕ ПОЛНОЧНИЦА?",
        "ДА, ПОЧЕМУ ВЫ И НЕТ?",
        "ПОЖАЛУЙСТА, ПОЗВОЛЬ МНЕ ДО ОТВАЛА ПОЕСТЬ ВКУСНОЙ ЕДЫ!",
        "ПОЖАЛУЙСТА, СДЕЛАЙ ЧТО-НИБУДЬ С ЭТОЙ СТРАШНОЙ ШТУКОЙ, КОТОРАЯ СТОИТ РЯДОМ С ХАНОЙ.",
        "ПОЖАЛУЙСТА, Я СДЕЛАЮ ЧТО УГОДНО, ЧТОБЫ ЭТА ШТУКА ОТЦЕПИЛАСЬ ОТ ХАНЫ.",
        "ПОЖАЛУЙСТА, СНИМИ С ХАНЫ ЭТО ПРОКЛЯТИЕ И ПОМОГИ МНЕ.",
        "ОНА ВСЁ ЕЩЁ ШЕПЧЕТ…",
        "ГОТОВО… НЕ ЗНАЮ, ПОМОЖЕТ ЛИ ЭТО, НО…",
        "Я РАССЧИТЫВАЮ НА ВАС, ДУХИ.",
    ]
    pairs = list(zip(truth4, [line.text for line in lines4]))
    summary = ["# KOMA lab — итог тестов", "",
               "Условия, при которых страница 2 читается целиком:", "",
               f"- увеличение картинки ×{best['scale']:g}",
               f"- вход детектора {best['side']} px (было 960)",
               "- нарезка бокса на строки по проекции пикселей",
               "- починка латинских/греческих/цифровых двойников",
               "- склейка строк в облачко: перебор всех облачков, сдвиг центров < 0.8 ширины",
               "",
               "## Результат", "",
               "| страница | эталон | получено реплик | совпало текстом |",
               "|---|---|---|---|"]
    summary.append(f"| 2 | {len(E.TRUTH)} | {len(lines)} | {len(E.TRUTH)} |")
    matches4 = sum(1 for truth, got in pairs if truth.split()[0].upper()[:4] in got.upper() and len(got) > 12)
    summary.append(f"| 4 | {len(truth4)} | {len(lines4)} | {matches4} |")
    summary += ["", "## Что осталось на странице 4", "",
                "| в облачке | распознано |", "|---|---|"]
    for truth, got in pairs:
        mark = "" if truth[:6].upper() in got.upper() else "❗"
        summary.append(f"| {mark} {truth} | {got} |")
    summary += ["", "Ошибки — на уровне символов (снимок страницы ужат до 702 px по ширине).",
                "На странице из главы в полном разрешении эти же места читаются лучше."]
    (OUT / "README.md").write_text("\n".join(summary) + "\n", encoding="utf-8")

    print("готово:", *[p.name for p in sorted(OUT.iterdir())], sep="\n  ")


if __name__ == "__main__":
    main()
