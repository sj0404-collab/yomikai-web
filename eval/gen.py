# общий загрузчик: 183 размеченные строки + категории
import json, cv2
W='/home/user/evalwork'
HAND={'manhua2','comic3','comic4','manhua5'}
_items=json.load(open(f'{W}/index.json'))
def items():
    for it in _items:
        it['gray']=cv2.imread(f"{W}/{it['i']}.png", cv2.IMREAD_GRAYSCALE)
        yield it
CATS={'всё':lambda it:True,'рукописный':lambda it:it['page'] in HAND,
      'печатный':lambda it:it['page'] not in HAND,'мелкий':lambda it:it['h']<=22,
      'крупный':lambda it:it['h']>=40,'звуки':lambda it:it['kind']=='sfx'}
MODELS={'webtoon':'/home/user/ownocr/model/eslav/eslav-webtoon.onnx',
        'hard':'/home/user/ownocr/model/eslav/eslav-hard.onnx',
        'ftall':'/home/user/ownocr/model/eslav/eslav-ft-all.onnx',
        'gentle':'/home/user/ownocr/out/eslav-gentle.onnx'}
