# -*- coding: utf-8 -*-
"""Import ledger edits back into decision files (the only way content changes).

    python ledger_import.py <workbook.xlsx> [pipeline.json] [--dry]

Only 译文 / 字号 / 中文 are read back; every other field stays as the layout
engine decided. Idempotent - unchanged rows are ignored. Written changes are
backed up first. Encodes all the D7 lessons:
  * columns located by HEADER NAME, not fixed index
  * \r <-> \n normalised both ways (xlsx turns soft returns into \n)
  * changing a size back to the source value clears the override
  * title rows with colour=ALL fan out to every colour; title keys matched
    with newline normalisation
  * 中文 column feeds gloss JSON (words + per-cell overrides), from BOTH the
    language sheets and the comparison sheet
"""
import os, sys, json, shutil, datetime
from openpyxl import load_workbook
from common import (Config, columns, crlf, nk)

args = [a for a in sys.argv[1:] if not a.startswith('--')]
dry = '--dry' in sys.argv
path = args[0] if args else None
cfg_path = args[1] if len(args) > 1 else None
cfg = Config(cfg_path)
S = cfg.s
E, V, SZ = S['entries'], S['value'], S['size_override']
TITLES = S['titles']

if not path:
    cands = []
    for d, _, fs in os.walk(cfg.xlsx_dir):
        cands += [os.path.join(d, f) for f in fs if f.endswith('.xlsx') and cfg.f['ledger'][:3] in f]
    if not cands:
        raise SystemExit('no ledger found; pass the path explicitly')
    path = max(cands, key=os.path.getmtime)
    print('auto-selected:', path)

wb = load_workbook(path)
stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
bakdir = os.path.join(cfg.work, '_bak_' + stamp)
os.makedirs(bakdir, exist_ok=True)

cache, changed, touched = {}, 0, set()

def get(lang, color):
    k = (lang, color)
    if k not in cache:
        p = cfg.decision_path(lang, color)
        cache[k] = (p, json.load(open(p, encoding='utf-8')))
    return cache[k]

def as_size(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if 4 <= f <= 200 else None

def backup(p):
    if p not in touched:
        shutil.copy(p, bakdir); touched.add(p)

print('reading', path)
# -- language sheets: 译文 + 字号 ----------------------------------------------
for l in cfg.langs:
    lang, lname = l['code'], l['name']
    if lname not in wb.sheetnames:
        print('  ! missing sheet', lname); continue
    ws = wb[lname]
    col = columns(ws)
    # 新台账语言页列头为该语言名（如「意大利语」），兼容旧的「译文」列头
    val_c = col.get('译文') or col.get(lname)
    cid_c, sz_c = col.get('ID'), col.get('字号')
    if not cid_c or not val_c:
        print('  ! %s has no ID/译文 column' % lname); continue
    rows = 0
    for r in range(2, ws.max_row + 1):
        cid = ws.cell(row=r, column=cid_c).value
        if not cid or not isinstance(cid, str) or cid.count('|') < 3:
            continue
        parts = cid.split('|', 3)
        if parts[0] != lang:
            continue
        color, ab, en = parts[1], parts[2], crlf(parts[3])
        newval = ws.cell(row=r, column=val_c).value
        if newval is None:
            continue
        newval = crlf(newval)
        newsz = as_size(ws.cell(row=r, column=sz_c).value) if sz_c else None
        if ab == 'TITLE':
            targets = [c['code'] for c in cfg.colors] if color == 'ALL' else [color]
            for c in targets:
                p, d = get(lang, c)
                tm = d.get(TITLES, {})
                key = en if en in tm else next((k for k in tm if crlf(k) == en), None)
                if key is None:
                    continue
                if tm.get(key) != newval:
                    print('  ~ %s/%s title %r: %r -> %r' % (lang, c, key, tm.get(key), newval))
                    if not dry:
                        backup(p); tm[key] = newval; changed += 1
            rows += 1; continue
        if not ab.isdigit():
            continue
        p, d = get(lang, color)
        drecs = d.get(E, {}).get(ab, {})
        key = en if en in drecs else next((k for k in drecs if crlf(k) == en), None)
        if key is None:
            continue
        rec = drecs[key]
        if rec.get(V, '') != newval:
            print('  ~ %s/%s ab%s %r: %r -> %r' % (lang, color, ab, key, rec.get(V), newval))
            if not dry:
                backup(p); rec[V] = newval; changed += 1
        if newsz is not None:
            cur = rec.get(SZ)
            # "#abbr" rows (small-form role of the same English string) are
            # sized by their OWN source size; without this the round trip wrote
            # an sz override equal to the source size on every import
            base = rec.get('szsrc') or cfg.src_size(color, key, ab)
            if abs(newsz - base) < 0.05:
                if cur is not None:
                    print('  ~ %s/%s ab%s %r size: %s -> source %.1f' % (lang, color, ab, key, cur, base))
                    if not dry:
                        backup(p); rec.pop(SZ, None); changed += 1
            elif cur is None or abs(float(cur) - newsz) > 0.05:
                print('  ~ %s/%s ab%s %r size: %s -> %.1f' % (lang, color, ab, key, cur or base, newsz))
                if not dry:
                    backup(p); rec[SZ] = newsz; changed += 1
        rows += 1
    print('  %-10s rows=%d' % (lname, rows))

# -- 中文 column -> gloss (language sheets + comparison) ----------------------
zh_sheets = [l['name'] for l in cfg.langs if l['name'] in wb.sheetnames]
if '全语言对照' in wb.sheetnames:
    zh_sheets.append('全语言对照')
gpath = os.path.join(cfg.work, cfg.f['gloss'])
g = json.load(open(gpath, encoding='utf-8'))
GW, GO = g.setdefault('words', {}), g.setdefault('overrides', {})
gchanged = 0
for sheet in zh_sheets:
    ws = wb[sheet]
    col = columns(ws)
    cc, ca, ce, cz = col.get('颜色'), col.get('画板'), col.get('英文原文'), col.get('中文')
    if not all((cc, ca, ce, cz)):
        print('  ! %s has no 中文/颜色/画板/英文原文 column' % sheet); continue
    n = 0
    for r in range(2, ws.max_row + 1):
        rawc = str(ws.cell(row=r, column=cc).value or '').strip()
        color = cfg.NAME2COLOR.get(rawc)
        ab = ws.cell(row=r, column=ca).value
        en = ws.cell(row=r, column=ce).value
        z = ws.cell(row=r, column=cz).value
        if not color or en is None or z is None:
            continue
        z = str(z).strip()
        if not z:
            continue
        k = nk(en).replace(' / ', ' ')
        key = '%s|TITLE|%s' % (color, k) if str(ab).strip() in ('标题', 'TITLE') else '%s|%s|%s' % (color, ab, k)
        cur = GO.get(key) or GW.get(k, '')
        if cur != z:
            print('  ~ 中文 %s %s: %r -> %r' % (sheet, key, cur, z))
            gchanged += 1
            if not dry:
                GO[key] = z
        n += 1
    print('  %-10s 中文 rows=%d' % (sheet, n))
if gchanged and not dry:
    backup(gpath)
    json.dump(g, open(gpath, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
changed += gchanged

if not dry:
    for p, d in cache.values():
        if p in touched:
            json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('changed=%d files=%d backup=%s' % (changed, len(touched), bakdir if (changed and not dry) else '-'))
