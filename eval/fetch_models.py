"""Подтянуть модели из репозитория, если их нет в рабочей папке.

Снимок рабочей папки не сохраняет крупные бинарники между запросами, поэтому
каждый замер начинается с этой проверки — иначе скрипты падают на «нет файла».
"""
import base64, json, os, urllib.request, urllib.parse

T = open('/home/user/uploads/_.gh_secret.txt').read().strip()
H = {'Authorization': 'Bearer ' + T, 'User-Agent': 'koma'}
REPO = 'sj0404-collab/yomikai-web'
NEED = {
    'ownocr/model/eslav/eslav-webtoon.onnx': 'ownocr/model/eslav/eslav-webtoon.onnx',
    'ownocr/model/eslav/eslav-hard.onnx': 'ownocr/model/eslav/eslav-hard.onnx',
    'ownocr/model/eslav/eslav-ft-all.onnx': 'ownocr/model/eslav/eslav-ft-all.onnx',
    'ownocr/model/eslav/eslav-ft.onnx': 'ownocr/model/eslav/eslav-ft.onnx',
    'web/models/eslav-comic.onnx': 'web-ocr/models/eslav-comic.onnx',
    'web/models/eslav-webtoon.onnx': 'web-ocr/models/eslav-webtoon.onnx',
    'web/models/eslav-ft.onnx': 'web-ocr/models/eslav-ft.onnx',
    'web/models/eslav-hard.onnx': 'web-ocr/models/eslav-hard.onnx',
    'ownocr/model/eslav/eslav-ft-all.pt': 'ownocr/model/eslav/eslav-ft-all.pt',
    'ownocr/model/eslav/eslav-hard.pt': 'ownocr/model/eslav/eslav-hard.pt',
}


def _raw(remote):
    u = f'https://api.github.com/repos/{REPO}/contents/{urllib.parse.quote(remote)}'
    d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=H)))
    b = urllib.request.Request(
        f'https://api.github.com/repos/{REPO}/git/blobs/{d["sha"]}',
        headers={**H, 'Accept': 'application/vnd.github.raw'})
    return urllib.request.urlopen(b).read()


def ensure(verbose=True):
    for remote, local in NEED.items():
        path = os.path.join('/home/user', local)
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, 'wb').write(_raw(remote))
        if verbose:
            print('подтянул', local, os.path.getsize(path) // 1024, 'КБ')


if __name__ == '__main__':
    ensure()
