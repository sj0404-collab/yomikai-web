"""Тесеракт как ещё один чтец строки — для сравнения и как «третий голос».

Настройки подобраны замером на 113 размеченных строках манги и манхвы:

| настройки | CER |
|---|---|
| psm 7, ×1 | 19,2 % |
| psm 7, ×2 | 24,4 % |
| psm 6, ×2 | 25,3 % |
| **psm 13 (строка как есть), ×2** | **7,4 %** |

psm 13 («raw line») — ключ: тесеракт не пытается искать блоки и колонки в кропе,
который и так является одной строкой. Масштаб ×2 помогает мелкому шрифту манги.

Читает через pytesseract (системный бинарь tesseract-ocr + tesseract-ocr-rus):
в браузере его нет, там нужен tesseract.js и это отдельный разговор о весе.
"""
from __future__ import annotations

import cv2
import numpy as np

LANG = 'rus'
PSM = 13
SCALE = 2.0


class TesseractReader:
    def __init__(self, lang: str = LANG, psm: int = PSM, scale: float = SCALE):
        import pytesseract  # noqa: F401  — падаем рано, если нет зависимости
        self.lang, self.psm, self.scale = lang, psm, scale

    def read(self, img: np.ndarray) -> tuple[str, float]:
        import pytesseract

        g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if self.scale != 1.0:
            g = cv2.resize(g, None, fx=self.scale, fy=self.scale,
                           interpolation=cv2.INTER_CUBIC)
        data = pytesseract.image_to_data(g, lang=self.lang,
                                         config=f'--psm {self.psm}',
                                         output_type=pytesseract.Output.DICT)
        words, confs = [], []
        for w, c in zip(data['text'], data['conf']):
            if w.strip():
                words.append(w.strip())
                try:
                    confs.append(float(c))
                except ValueError:
                    pass
        text = ' '.join(words)
        conf = (sum(confs) / len(confs) / 100.0) if confs else 0.0
        return text, conf
