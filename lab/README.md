# Что лежит в lab/ — рабочие скрипты замеров (27.10)

Это не часть приложения: html собирается из `part1.html` + `part0-*` + `part2..5.js`.
Скрипты перенесены из рабочей песочницы в репозиторий, чтобы замеры можно было повторить.
Многие требуют Chromium (playwright) и модель в `koma_models/` — см. `lab/README.md`.

## Замеры и разбор (lab/)

| файл | первая строка описания |
|---|---|
| `lab/adapt2.py` | Адаптивность на уровне фрагмента: каждый кусок текста читается двумя |
| `lab/adapt3.py` | Адаптивные условия со страховкой: основной проход + добор потерянного. |
| `lab/adaptive.py` | Адаптивные условия: страница прогоняется несколькими проходами, результаты |
| `lab/annotate.py` | Рисует найденные реплики на странице: рамки, номера = порядок чтения. |
| `lab/annotate_adaptive.py` | Разметка страницы по АДАПТИВНОЙ схеме (основной проход + добор потерянного).""" |
| `lab/beam.py` |  |
| `lab/beam2.py` |  |
| `lab/beam3.py` |  |
| `lab/build_preview.py` | !/usr/bin/env python3 |
| `lab/build_standalone.py` | Собирает standalone.html: один файл, без бэкенда. |
| `lab/chooser.py` | Адаптивные условия: какие настройки выбрать для конкретной страницы. |
| `lab/correct.py` | Послемодельная коррекция слов: словарь + правдоподобие буквосочетаний. |
| `lab/detone.py` | Чистка растрового фона (screen tone) перед распознаванием. |
| `lab/experiment.py` | Подбор условий, при которых страница читается полностью и в верном порядке. |
| `lab/frames.py` | Нарезка страницы по рамкам панелей (чёрные линии), а не по расположению текста. |
| `lab/generate_report.py` | Рисует скриншоты-отчёты: страница с рамками реплик и сравнение условий. |
| `lab/logs.py` | !/usr/bin/env python3 |
| `lab/panels2.py` | Эксперимент: рекурсивный XY-cut (самый большой разрыв делит панели). |
| `lab/panels3.py` | Рамки панелей по контурам рисунка — порядок чтения как в манге. |
| `lab/pipeline.py` | KOMA-распознавание в чистом Python: эталон для лаборатории. |
| `lab/retry.py` | Вторая попытка чтения «трудной» строки. |
| `lab/server.py` | !/usr/bin/env python3 |
| `lab/tune.py` | Подбор параметров склейки строк в реплику (облачко) по двум страницам-эталонам.""" |
| `lab/verify.py` | Финальная проверка условий в лаборатории — до переноса в приложение. |
| `lab/whitefy.py` | Белый текст на тёмном: предобработка вырезки перед распознаванием. |
| `lab/whitetext.py` | Поиск подхода к «плотному» тексту: декоративный шрифт на растровом фоне. |

## Точечные пробы (lab/probes/)

| файл | первая строка описания |
|---|---|
| `lab/probes/dump_logits.py` |  |
| `lab/probes/e2e_embed.py` | !/usr/bin/env python3 |
| `lab/probes/probe_ab.py` |  |
| `lab/probes/probe_ab_embed.py` |  |
| `lab/probes/probe_bands_stats.py` |  |
| `lab/probes/probe_beam_live.py` |  |
| `lab/probes/probe_beam_live2.py` |  |
| `lab/probes/probe_beam_opts.py` |  |
| `lab/probes/probe_bench.py` |  |
| `lab/probes/probe_bw.py` |  |
| `lab/probes/probe_cmp_cer.py` |  |
| `lab/probes/probe_crop.py` |  |
| `lab/probes/probe_crop2.py` |  |
| `lab/probes/probe_crop3.py` |  |
| `lab/probes/probe_cursor.py` |  |
| `lab/probes/probe_dict.py` |  |
| `lab/probes/probe_dict2.py` |  |
| `lab/probes/probe_dict3.py` |  |
| `lab/probes/probe_dict_real.py` |  |
| `lab/probes/probe_e2e_dict.py` |  |
| `lab/probes/probe_e2e_naive.py` |  |
| `lab/probes/probe_embed.py` |  |
| `lab/probes/probe_ens.py` |  |
| `lab/probes/probe_frames.py` |  |
| `lab/probes/probe_full_cer.py` |  |
| `lab/probes/probe_google_models.py` |  |
| `lab/probes/probe_hard.py` |  |
| `lab/probes/probe_large.py` |  |
| `lab/probes/probe_line32.py` |  |
| `lab/probes/probe_line32_hard.py` |  |
| `lab/probes/probe_mem.py` |  |
| `lab/probes/probe_pad.py` |  |
| `lab/probes/probe_pipe_run.py` |  |
| `lab/probes/probe_pipeline.py` |  |
| `lab/probes/probe_pipeline2.py` |  |
| `lab/probes/probe_polish.py` |  |
| `lab/probes/probe_rt.py` |  |
| `lab/probes/probe_rt2.py` |  |
| `lab/probes/probe_shadow2.py` |  |
| `lab/probes/probe_shadow3.py` |  |
| `lab/probes/probe_shadow4.py` |  |
| `lab/probes/probe_shear.py` |  |
| `lab/probes/probe_shots_diff.py` |  |
| `lab/probes/probe_slant.py` |  |
| `lab/probes/probe_stats_e2e.py` |  |
| `lab/probes/probe_words.py` |  |
| `lab/probes/probe_words2.py` |  |
| `lab/probes/probe_words3.py` |  |
