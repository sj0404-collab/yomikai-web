#!/usr/bin/env python3
"""Хвост журнала лаборатории в читаемом виде.

  python3 lab/logs.py            — последние 20 событий
  python3 lab/logs.py 50         — последние 50
  python3 lab/logs.py --follow   — следить в реальном времени
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

LOG = Path(__file__).parent / "logs" / "lab.log"


def format_event(record: dict) -> str:
    kind = record.get("event")
    if kind == "http":
        return f"{record['time']}  ·  {record['method']} {record['path']}  ({record['remote']})"
    if kind == "note":
        return f"{record['time']}  ·  ПОДПИСЬ «{record['note']}» ({record['page']})"
    if kind == "upload":
        return f"{record['time']}  ·  ЗАГРУЗКА {record['file']} · {record['size']} · {record['bytes']} байт"
    if kind in ("ocr", "ocr_from_cache"):
        head = (f"{record['time']}  ·  РАСПОЗНАНО {record['page']} "
                f"[{record['variant']}, {'справа налево' if record['rtl'] else 'слева направо'}] "
                f"· фрагментов {record['regions']} · реплик {record['lines']}"
                + ("  (из кэша)" if kind == "ocr_from_cache" else ""))
        lines = [f"          {i:2}. {text}" for i, text in enumerate(record.get("texts", []), 1)]
        return "\n".join([head] + lines)
    return f"{record['time']}  ·  {kind}: " + json.dumps(record, ensure_ascii=False)


def main() -> None:
    args = [a for a in sys.argv[1:]]
    follow = "--follow" in args or "-f" in args
    count = next((int(a) for a in args if a.isdigit()), 20)
    if not LOG.exists():
        print("журнала пока нет:", LOG)
        return
    lines = LOG.read_text(encoding="utf-8").splitlines()
    for line in lines[-count:]:
        try:
            print(format_event(json.loads(line)))
        except json.JSONDecodeError:
            print(line)
    if not follow:
        return
    print("\n… слежу за журналом (Ctrl+C — выход)")
    position = len(lines)
    while True:
        time.sleep(2)
        fresh = LOG.read_text(encoding="utf-8").splitlines()
        for line in fresh[position:]:
            try:
                print(format_event(json.loads(line)), flush=True)
            except json.JSONDecodeError:
                print(line, flush=True)
        position = len(fresh)


if __name__ == "__main__":
    main()
