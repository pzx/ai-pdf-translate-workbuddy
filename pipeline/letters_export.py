# -*- coding: utf-8 -*-
"""Build the letter-reference workbook for alphabet cards.

    python letters_export.py [pipeline.json]

Two sheets:
  字母对应表 - 26 A..Z blocks: the letter stays English (source artwork), the
               word under it is translated per language. This table tells the
               reader which word goes with which letter.
  特有字母   - characters a language has beyond A-Z, each with a sample word.

Letter words are inferred from the source spans (alphabet pages), and per-
language translations come from the decision files. Override with a JSON map if
the automatic inference is wrong (set "letter_words" / "letter_pictures" /
"extra_letters" in pipeline.json).
"""
import os, sys, json, re
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from common import Config

cfg = Config(sys.argv[1] if len(sys.argv) > 1 else None)
OUT = cfg.letters_path()
os.makedirs(cfg.xlsx_dir, exist_ok=True)
spans = cfg.spans

# -- letter words -------------------------------------------------------------
lw = cfg.d.get('letter_words')
if lw:
    WORDS = [(w[0].upper(), w) for w in lw]
else:
    # infer: short words on the first pages; one per distinct first letter A-Z
    first_color = cfg.colors[0]['code']
    seen, out = set(), []
    max_page = cfg.d.get('letter_pages', 5)
    for it in spans.get(first_color, []):
        t = str(it.get('text', '')).strip()
        if it['page'] > max_page or not t or len(t) > 14 or t.isdigit():
            continue
        if t.lower() in seen:
            continue
        seen.add(t.lower()); out.append((t[0].upper(), t))
    out.sort()
    WORDS = out
try:
    assert len(WORDS) == 26, 'expected 26 letters, got %d' % len(WORDS)
except AssertionError as e:
    print('WARN', e, '- set "letter_words" in pipeline.json to fix')

# translation per language from the first colour's decision (alphabet pages shared)
trans = {}
for l in cfg.langs:
    d = __import__('common').load_dec(cfg, l['code'], cfg.colors[0]['code'])
    m = {}
    max_page = cfg.d.get('letter_pages', 5)
    for ab in [str(i) for i in range(max_page)]:
        for en, rec in d.get(cfg.s['entries'], {}).get(ab, {}).items():
            m[en.strip().lower()] = rec.get(cfg.s['value'], '')
    trans[l['code']] = m

HFILL = PatternFill('solid', fgColor='1F3864'); HFONT = Font(color='FFFFFF', bold=True, size=10)
THIN = Side(style='thin', color='BFBFBF'); BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
KEYF = PatternFill('solid', fgColor='DDEBF7')

wb = Workbook()
ws = wb.active; ws.title = '字母对应表'
PIC = cfg.d.get('letter_pictures', {})
hdr = ['字母', '插图', '英文'] + [l['name'] for l in cfg.langs]
ws.append(hdr)
for i, w in enumerate([6, 10, 12] + [18] * len(cfg.langs), 1):
    ws.column_dimensions[get_column_letter(i)].width = w
    c = ws.cell(row=1, column=i); c.fill = HFILL; c.font = HFONT
    c.alignment = Alignment(horizontal='center', vertical='center')
for r, (ch, en) in enumerate(WORDS, 2):
    ws.cell(row=r, column=1, value=ch).font = Font(bold=True, size=14)
    ws.cell(row=r, column=1).fill = KEYF
    ws.cell(row=r, column=2, value=PIC.get(en.lower(), PIC.get(en, '')))
    ws.cell(row=r, column=3, value=en)
    for j, l in enumerate(cfg.langs, 4):
        ws.cell(row=r, column=j, value=trans[l['code']].get(en.lower(), ''))
    for i in range(1, 4 + len(cfg.langs)):
        ws.cell(row=r, column=i).border = BORDER
        ws.cell(row=r, column=i).alignment = Alignment(vertical='center', wrap_text=(i == 3))
ws.freeze_panes = 'D2'

# -- extra characters ---------------------------------------------------------
extra = cfg.d.get('extra_letters')
if not extra:
    print('WARN no "extra_letters" in config; skipping 特有字母 sheet. '
          'Add e.g. {"de":[["Ä","A"],["ß","ss"]], "ru":[...]} for a complete table.')
else:
    ws2 = wb.create_sheet('特有字母')
    ws2.append(['语言', '字母', '对应拉丁字母 / 名称', '书中出现的词'])
    for i, w in enumerate([16, 8, 26, 30], 1):
        ws2.column_dimensions[get_column_letter(i)].width = w
        c = ws2.cell(row=1, column=i); c.fill = HFILL; c.font = HFONT
        c.alignment = Alignment(horizontal='center', vertical='center')
    r = 2
    for l in cfg.langs:
        code = l['code']
        if code not in extra:
            continue
        pool = []
        for c in cfg.colors:
            d = __import__('common').load_dec(cfg, code, c['code'])
            for ab, recs in d.get(cfg.s['entries'], {}).items():
                for en, rec in recs.items():
                    v = rec.get(cfg.s['value'], '')
                    if v and v not in pool:
                        pool.append(v)
        toks = []
        for w in pool:
            for tk in re.split(r'[\s\-–—]+', w):
                tk = tk.strip('.,()')
                if tk and tk not in toks:
                    toks.append(tk)
        first = True
        for item in extra[code]:
            ch, lat = item[0], (item[1] if len(item) > 1 else '')
            head = [w for w in toks if w.lower().startswith(ch.lower())]
            body = [w for w in toks if ch.lower() in w.lower() and w not in head]
            sample = '、'.join((head + body)[:3]) or '书中未出现'
            ws2.cell(row=r, column=1, value=l['name'] if first else '')
            ws2.cell(row=r, column=2, value=ch).font = Font(bold=True, size=13)
            ws2.cell(row=r, column=3, value=('≈ ' + lat) if lat else '')
            ws2.cell(row=r, column=4, value=sample)
            for i in range(1, 5):
                ws2.cell(row=r, column=i).border = BORDER
                ws2.cell(row=r, column=i).alignment = Alignment(vertical='center')
            r += 1; first = False

if os.path.exists(OUT):
    import shutil
    bak = os.path.join(cfg.work, '_bak_' + __import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S'))
    os.makedirs(bak, exist_ok=True); shutil.copy(OUT, bak)
wb.save(OUT)
print('wrote', OUT)
