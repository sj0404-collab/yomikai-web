#!/bin/bash
# Обучение по ступеням: сначала лёгкая порча и короткие строки, потом всё
# жёстче и длиннее. Зачем: при полной порче с нуля CTC «залипает» на blank
# (потеря 3,6 не движется — проверено 27.10), при лёгкой ступени буквы
# выучиваются за минуты, и дальше порог поднимается.
#
#   bash tools/train_curriculum.sh            # ~15 минут на 2 ядрах CPU
#   OUT=runs/rec_v1.pt bash tools/train_curriculum.sh
set -e
cd "$(dirname "$0")/.."
OUT=${OUT:-runs/rec_v1.pt}
COMMON="--threads 2 --batch 24"

# ступень 1: 3–6 букв, ширина 96–128, порча 25 %
python3 tools/train_rec.py $COMMON --steps 1500 --epochs 3 --lr 3e-3 \
  --strength 0.25 --hard 0.2 --max-chars 6 --pad-choices 96,128 --out "$OUT"
cp "${OUT%.pt}.json" "${OUT%.pt}-s1.json" 2>/dev/null || true

# ступень 2: до 10 букв, ширина 128–192, порча 60 %
python3 tools/train_rec.py $COMMON --steps 2000 --epochs 9 --lr 2e-3 --resume "$OUT" \
  --strength 0.6 --hard 0.25 --max-chars 10 --pad-choices 128,192 --out "$OUT"
cp "${OUT%.pt}.json" "${OUT%.pt}-s2.json" 2>/dev/null || true

# ступень 3: до 14 букв, ширина до 320 (как у приложения), порча 100 %
python3 tools/train_rec.py $COMMON --steps 2500 --epochs 20 --lr 1.5e-3 --resume "$OUT" \
  --strength 1.0 --hard 0.3 --max-chars 14 --pad-choices 128,192,256,320 --out "$OUT"
echo "готово: $OUT"
