# -*- coding: utf-8 -*-
"""Export decision JSONs into a review workbook (the editable VIEW of decisions).

    python ledger_export.py [pipeline.json]

Produces in xlsx_dir:
    <ledger>.xlsx   sheets: 总览 / one sheet per language / 全语言对照

Hard-won rules encoded here (do not remove):
  * BEFORE overwriting an existing ledger, import its edits back into the
    decisions - otherwise a re-export silently drops the reviewer's work.
    Skip with env XL_NO_SYNC=1.
  * Colour order follows config.colors (1,2,3,4); the shared title block goes
    AFTER all colours, never in the middle.
  * Columns are looked up by header name on import, so adding/reordering
    columns (e.g. 页码) never breaks the round trip.
  * Page column = artboard + 1 when ab_is_zero_based; titles have no page.
  * 中文 is an ANNOTATION only when the target language is a foreign language.
    If the target includes Chinese, Chinese IS the translation and goes in the
    译文 column (see references/batch-pipeline.md section 4).
"""
import os, sys, datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from common import (Config, crlf)

cfg = Config(sys.argv[1] if len(sys.argv) > 1 else None)
S = cfg.s
E, V, SZ, MODE = S['entries'], S['value'], S['size_override'], S['mode']
TITLES = S['titles']

OUT = cfg.ledger_path()
os.makedirs(cfg.xlsx_dir, exist_ok=True)

# -- rule: sync existing edits back before overwriting ------------------------
if os.path.exists(OUT) and not os.environ.get('XL_NO_SYNC'):
    import subprocess
    print('syncing existing workbook ->', OUT, flush=True)
    subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), 'ledger_import.py'),
                    OUT, cfg.path], cwd=os.path.dirname(__file__))

DATA = {}
for l in cfg.langs:
    for c in cfg.colors:
        DATA[(l['code'], c['code'])] = __import__('common').load_dec(cfg, l['code'], c['code'])

# titles are shared across colours; take them from the first colour
first_color = cfg.colors[0]['code']
TITLE_ROWS = {l['code']: sorted(DATA[(l['code'], first_color)].get(TITLES, {}).items())
              for l in cfg.langs}

# -- styles -------------------------------------------------------------------
HFILL = PatternFill('solid', fgColor='1F3864')
HFONT = Font(color='FFFFFF', bold=True, size=10)
THIN = Side(style='thin', color='BFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
EDIT = PatternFill('solid', fgColor='FFF2CC')
BAD = PatternFill('solid', fgColor='FCE4D6')
INFO = PatternFill('solid', fgColor='EDF2F9')

HDR = ['ID', '序号', '颜色', '画板', '页码', '字体', '字号', '中文', '英文原文', '译文', '模式', '审校备注']
WID = [30, 6, 8, 7, 7, 22, 7, 18, 26, 34, 10, 30]
CI = {h: i + 1 for i, h in enumerate(HDR)}


def head(ws, ncol, widths, freeze='A2'):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for i in range(1, ncol + 1):
        c = ws.cell(row=1, column=i)
        c.fill = HFILL; c.font = HFONT
        c.alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = freeze


def style_row(ws, r, ncol, wrapcols):
    for i in range(1, ncol + 1):
        ws.cell(row=r, column=i).border = BORDER
        ws.cell(row=r, column=i).alignment = Alignment(vertical='center', wrap_text=(i in wrapcols))


wb = Workbook()
ov = wb.active
ov.title = '总览'
order = cfg.order_index()

# -- one sheet per language ---------------------------------------------------
for l in cfg.langs:
    lang, lname = l['code'], l['name']
    ws = wb.create_sheet(lname)
    # 第10列列头显示为该语言名（如「意大利语」），而非笼统的「译文」；
    # CI 仍按原 HDR 建列号，列位置不变，ledger_import 已兼容语言名列头。
    lang_hdr = list(HDR)
    lang_hdr[CI['译文'] - 1] = lname
    ws.append(lang_hdr); head(ws, len(HDR), WID)
    r = 2
    for c in cfg.colors:
        color, cname, no = c['code'], c['name'], c['no']
        dec = DATA[(lang, color)].get(E, {})
        for ab in sorted(dec, key=lambda x: int(x)):
            for en, rec in sorted(dec[ab].items(), key=lambda kv: cfg.sort_key(order, kv[0], ab)):
                if not en:
                    continue
                def put(name, val):
                    ws.cell(row=r, column=CI[name], value=val)
                put('ID', '%s|%s|%s|%s' % (lang, color, ab, en))
                put('序号', no); put('颜色', cname); put('画板', int(ab))
                pg = ws.cell(row=r, column=CI['页码'],
                             value=(int(ab) + 1 if S.get('ab_is_zero_based', True) else int(ab)))
                pg.fill = INFO; pg.font = Font(size=9, color='595959')
                fo = ws.cell(row=r, column=CI['字体'], value=cfg.font_for(lang))
                fo.fill = INFO; fo.font = Font(size=9, color='595959')
                # "#abbr" rows carry the SOURCE size of the small variant, so the
                # reviewer sees 12.8 (the band), not 18 (the full name)
                _szv = rec.get(SZ) or rec.get('szsrc') or cfg.src_size(color, en, ab)
                sc = ws.cell(row=r, column=CI['字号'], value=_szv)
                sc.fill = EDIT; sc.number_format = '0.0'
                zc = ws.cell(row=r, column=CI['中文'],
                             value=cfg.zh(color, ab, en.split('#abbr')[0]))
                zc.fill = EDIT
                # "<en>#abbr" = the small-form role of the same English string
                # (e.g. the 'Mag.' inside the calendar cell vs 'maggio' below).
                # 英文原文 stays the RAW text: ledger_import builds the Chinese
                # gloss key from it, so a decorated label would create a bogus
                # gloss entry. The role is shown in 模式 instead; ID keeps #abbr.
                put('英文原文', en.split('#abbr')[0])
                vc = ws.cell(row=r, column=CI['译文'], value=rec.get(V, ''))
                vc.fill = BAD if not rec.get(V) else EDIT
                _mode = rec.get(MODE, '')
                if en.endswith('#abbr'):
                    _mode += '·缩写格'
                # a lifted row moves text AND artwork together: say so, otherwise
                # the reviewer sees a plain "keep" and wonders why the row sits
                # higher than in the English original
                if rec.get('illdy'):
                    _mode += '·整排↑%.1f' % float(rec['illdy'])
                put('模式', _mode)
                style_row(ws, r, len(HDR), (CI['英文原文'], CI['译文'], CI['审校备注']))
                r += 1
    # shared title block AFTER all colours
    ws.cell(row=r, column=1, value='— 本语言标题（各颜色共用一份）—').font = Font(bold=True, color='808080')
    r += 1
    for en, val in TITLE_ROWS[lang]:
        cid = ws.cell(row=r, column=CI['ID'], value='%s|ALL|TITLE|%s' % (lang, en))
        ws.cell(row=r, column=CI['颜色'], value='全部')
        ws.cell(row=r, column=CI['画板'], value='标题')
        fo = ws.cell(row=r, column=CI['字体'], value=cfg.font_for(lang))
        fo.fill = INFO; fo.font = Font(size=9, color='595959')
        sc = ws.cell(row=r, column=CI['字号'], value=cfg.src_size(first_color, en))
        sc.fill = INFO; sc.number_format = '0.0'
        zc = ws.cell(row=r, column=CI['中文'], value=cfg.zh(first_color, 'TITLE', en))
        zc.fill = EDIT
        ws.cell(row=r, column=CI['英文原文'], value=en.replace('\r', ' / '))
        vc = ws.cell(row=r, column=CI['译文'], value=val); vc.fill = EDIT
        ws.cell(row=r, column=CI['模式'], value='title')
        style_row(ws, r, len(HDR), (CI['英文原文'], CI['译文'], CI['审校备注']))
        r += 1

# -- cross-language comparison ------------------------------------------------
cp = wb.create_sheet('全语言对照')
LH = [l['name'] + ('  (%s)' % l['font'] if l['font'] != cfg.DEF_FONT else '') for l in cfg.langs]
CHDR = ['序号', '颜色', '画板', '页码', '英文原文', '中文', '字号', '字体'] + LH + ['缺失']
CWID = [6, 9, 7, 7, 30, 18, 7, 22] + [24] * len(cfg.langs) + [10]
CC = {h: i + 1 for i, h in enumerate(CHDR)}
# language columns carry a font suffix in the header, so map by position
LANGCOL = {l['code']: 9 + i for i, l in enumerate(cfg.langs)}   # 8 fixed cols + 1
for i, h in enumerate(CHDR, 1):
    cp.cell(row=1, column=i, value=h)   # head() already touched row 1, so write values by cell
head(cp, len(CHDR), CWID, freeze='F2')
for i in range(9, 9 + len(cfg.langs)):
    cp.cell(row=1, column=i).alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
cp.row_dimensions[1].height = 34

def cp_row(r, color, cname, no, ab, en, is_title=False):
    cp.cell(row=r, column=CC['序号'], value=('' if is_title else no))
    cp.cell(row=r, column=CC['颜色'], value=cname)
    cp.cell(row=r, column=CC['画板'], value=('标题' if is_title else int(ab)))
    pg = cp.cell(row=r, column=CC['页码'], value=('' if is_title else
                 int(ab) + (1 if S.get('ab_is_zero_based', True) else 0)))
    pg.fill = INFO; pg.font = Font(size=9, color='595959')
    cp.cell(row=r, column=CC['英文原文'], value=(en.replace('\r', ' / ') if is_title else en))
    zc = cp.cell(row=r, column=CC['中文'], value=cfg.zh(color, 'TITLE' if is_title else ab, en))
    zc.fill = EDIT
    sizes = []
    for l in cfg.langs:
        d = DATA[(l['code'], color)]
        if is_title:
            continue
        rec = d.get(E, {}).get(ab, {}).get(en)
        if rec and rec.get(SZ):
            sizes.append(rec[SZ])
    sz = cfg.src_size(first_color, en) if is_title else (max(sizes) if sizes else cfg.src_size(color, en, ab))
    s = cp.cell(row=r, column=CC['字号'], value=sz); s.number_format = '0.0'; s.fill = INFO
    fc = cp.cell(row=r, column=CC['字体'], value=cfg.DEF_FONT); fc.fill = INFO; fc.font = Font(size=9, color='595959')
    missing = []
    for i, l in enumerate(cfg.langs):
        d = DATA[(l['code'], color)]
        if is_title:
            val = d.get(TITLES, {}).get(en, '')
        else:
            rec = d.get(E, {}).get(ab, {}).get(en)
            if rec is None:
                missing.append(l['code']); continue
            val = rec.get(V, '')
        cc = cp.cell(row=r, column=LANGCOL[l['code']], value=val)
        if not val:
            cc.fill = BAD
    mc = cp.cell(row=r, column=CC['缺失'], value=','.join(missing))
    if missing:
        mc.font = Font(size=9, color='C00000')
    style_row(cp, r, len(CHDR), (CC['英文原文'], CC['中文'], *[LANGCOL[l['code']] for l in cfg.langs]))

rows = []
for c in cfg.colors:
    color, cname, no = c['code'], c['name'], c['no']
    abset = set()
    for l in cfg.langs:
        abset |= set(DATA[(l['code'], color)].get(E, {}).keys())
    for ab in sorted(abset, key=lambda x: int(x)):
        ens = set()
        for l in cfg.langs:
            ens |= {e for e in DATA[(l['code'], color)].get(E, {}).get(ab, {}) if e}
        for en in sorted(ens, key=lambda e: cfg.sort_key(order, e, ab)):
            rows.append((color, cname, no, ab, en))
r = 2
for color, cname, no, ab, en in rows:
    cp_row(r, color, cname, no, ab, en); r += 1
r += 1
cp.cell(row=r, column=1, value='— 标题（各颜色共用一份）—').font = Font(bold=True, color='808080')
r += 1
for en, _ in TITLE_ROWS[cfg.langs[0]['code']]:
    cp_row(r, first_color, '全部', '', 'TITLE', en, is_title=True); r += 1

# -- overview -----------------------------------------------------------------
ov.append(['语言', '语言代码', '颜色', '词条数', '待确认', '标题数', '输出字体'])
for c in ov[1]:
    c.fill = HFILL; c.font = HFONT
    c.alignment = Alignment(horizontal='center', vertical='center')
for col, w in zip('ABCDEFG', (18, 11, 10, 11, 11, 11, 24)):
    ov.column_dimensions[col].width = w
ov.freeze_panes = 'A2'
for l in cfg.langs:
    for c in cfg.colors:
        dec = DATA[(l['code'], c['code'])].get(E, {})
        n = sum(1 for ab in dec for en, rec in dec[ab].items() if en)
        pend = sum(1 for ab in dec for en, rec in dec[ab].items() if en and not rec.get(V))
        ov.append([l['name'], l['code'], c['name'], n, pend, len(TITLE_ROWS[l['code']]), cfg.font_for(l['code'])])

notes = [
    '', '这份表在哪、怎么保持最新',
    '固定位置：%s，文件名不带日期，永远是当前最新的一版。' % OUT,
    '重新出表时脚本会先把表里的改动回灌到决策文件，再覆盖表，不会丢你改过的内容。',
    '', '怎么用',
    '1. 浅黄底可改：语言页的「字号」「中文」「译文」，对照页的「中文」。',
    '   ID 是回写主键；序号/颜色/画板/页码/字体/英文原文请勿改动。',
    '   页码 = 画板 + 1（画板 0 起算），等于 PDF 页序，只读。',
    '2. 改完保存并关闭 Excel → ledger_import.py 回灌 → rebuild.py <lang> <color> 只重建那一本。',
    '3. 中文列：目标语言是外语时是注释、不参与排版；目标含中文时中文即译文，走译文列。',
]
rr = ov.max_row + 2
for t in notes:
    ov.cell(row=rr, column=1, value=t); rr += 1

try:
    wb.save(OUT)
except PermissionError:
    raise SystemExit('保存失败：%s 正被 Excel 打开，请先关闭。' % OUT)
print('wrote', OUT)
print('sheets:', wb.sheetnames, '| comparison rows:', len(rows))
