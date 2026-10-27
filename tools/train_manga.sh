#!/bin/bash
# Дообучение на НАСТОЯЩИХ строках манги (data/lines + labels.tsv).
# База — модель, обученная на синтетике (runs/rec_v1.pt); тут она подстраивается
# под настоящие шрифты и повреждения. Строк мало (сотни), поэтому скорость
# маленькая и эпох немного: иначе модель запомнит разметку наизусть.
#
#   bash tools/train_manga.sh
set -e
cd "$(dirname "$0")/.."
BASE=${BASE:-runs/rec_v1.pt}
OUT=${OUT:-runs/rec_manga.pt}
LABELS=${LABELS:-data/lines/labels.tsv}
OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 python3 tools/train_rec.py \
  --threads 2 --crops data/lines --labels "$LABELS" \
  --steps 115 --epochs 60 --batch 8 --lr 4e-4 --val 45 \
  ${BASE:+--resume "$BASE"} --out "$OUT"
python3 tools/export_onnx.py --ckpt "$OUT" --out models/rec_manga.onnx --lines 45
