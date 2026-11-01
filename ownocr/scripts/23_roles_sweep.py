#!/usr/bin/env python3
"""Перебор ролей: сколько чтецов реально улучшают страницу, а сколько мешают.

Задача поставлена как «хоть 5, хоть 10 ролей — важно, чтобы удачно». Ответ на
это не рассуждение, а замер: гоняем одни и те же три страницы с разным набором
ролей и смотрим CER. Роли добавляются по одной, в порядке, в котором каждая
показала себя отдельно.

    python3 scripts/23_roles_sweep.py --pages dense-a dense-b dense-page

Пишет out/roles-sweep.json и печатает таблицу «ролей → CER».
"""
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'out')

CONFIGS = [
    ('без ролей', ''),
    ('eslav', 'eslav'),
    ('alphabet', 'alphabet'),
    ('base', 'base'),
    ('app', 'app'),
    ('eslav+stretch', 'eslav,eslav_stretch'),
    ('+otsu', 'eslav,eslav_stretch,eslav_otsu'),
    ('+blur', 'eslav,eslav_stretch,eslav_otsu,eslav_blur'),
    ('+base', 'eslav,eslav_stretch,eslav_otsu,eslav_blur,base'),
    ('+app', 'eslav,eslav_stretch,eslav_otsu,eslav_blur,base,app'),
    ('+alphabet', 'eslav,eslav_stretch,eslav_otsu,eslav_blur,base,app,alphabet'),
]

RE = re.compile(r'СРЕДНЕЕ ([\d.]+) % · дословно (\d+)/(\d+) · ≤15% (\d+)/(\d+) · ошибок (\d+)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pages', nargs='+', default=['dense-a', 'dense-b', 'dense-page'])
    ap.add_argument('--configs', default='', help='если задано — только эти названия через запятую')
    ap.add_argument('--sets', default='', help='свои наборы: "имя=роль,роль;имя2=роль"')
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    only = [x.strip() for x in a.configs.split(',') if x.strip()]
    configs = CONFIGS
    if a.sets:
        configs = []
        for part in a.sets.split(';'):
            if '=' in part:
                label, roles = part.split('=', 1)
                configs.append((label.strip(), roles.strip()))
    res = {}
    for label, roles in configs:
        if only and label not in only:
            continue
        env = dict(os.environ)
        env['OWNOCR_ROLES'] = roles
        env.setdefault('OWNOCR_ESLAV_MODEL', os.path.join(ROOT, 'model', 'eslav', 'eslav-ft.onnx'))
        env['LABEL'] = 'sweep'
        cmd = [sys.executable, os.path.join(ROOT, 'scripts', 'dev_bench.py'), '--pages', *a.pages]
        print(f'== {label:14s} роли: {roles or "—"}', flush=True)
        p = subprocess.run(cmd, env=env, cwd=os.path.dirname(ROOT), capture_output=True, text=True)
        tail = p.stdout.strip().splitlines()[-6:]
        m = RE.search(p.stdout)
        if not m:
            print('   замер не разобрался:\n' + '\n'.join(tail), flush=True)
            res[label] = {'roles': roles, 'error': True}
            continue
        cer, ex, tot, ok15, tot15, err = m.groups()
        res[label] = {'roles': roles, 'cer': float(cer), 'эталон_дословно': f'{ex}/{tot}',
                      'до_15': f'{ok15}/{tot15}', 'ошибок': int(err)}
        n = len([r for r in roles.split(',') if r.strip()])
        print(f'   ролей {n}: CER {cer} % · дословно {ex}/{tot} · ошибок {err}', flush=True)
        with open(os.path.join(OUT, 'roles-sweep.json'), 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    print('\nитог:')
    for label, v in res.items():
        if v.get('error'):
            print(f'  {label:14s} — не посчиталось')
        else:
            print(f"  {label:14s} ролей {len([r for r in v['roles'].split(',') if r.strip()])}: "
                  f"CER {v['cer']:4.1f} % · ошибок {v['ошибок']}")


if __name__ == '__main__':
    main()
