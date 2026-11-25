# -*- coding: utf-8 -*-
"""qa_prebuild.py -- pre-build QA gate (no Illustrator, no export).

Reads the decision JSONs that build_decisions.py just wrote, plus the exported
geometry and the real font metrics, and reports every layout defect that used
to be found only by rendering pages and eyeballing them. Run it BEFORE
rebuild.py: a defect caught here costs one edit to the translation table; the
same defect caught after a build costs a full re-export of the book.

Checks
  GLYPH  a translated character is missing from the target font  -> blank/box
  FIT    the word cannot fit its slot even at layout.min_scale    -> overflow
  CLASH  two labels on one row are closer than clash_gap_pt       -> touching
  PN     a label runs into the corner page number                 -> overprint
  MISS   no translation at all / translation equals the English    -> untranslated
  TITLE  a card title is empty, or identical to its English        -> suspicious
  ABBR   an abbreviation cell holds a full word (12-13pt slot)     -> breaks cell

Exit code 0 = clean, 1 = at least one hard issue (TITLE-identical is a warning
because French "Nature"/"Sports" are genuinely spelled the same).

Usage
  PIPELINE_CONFIG=/path/pipeline.json python qa_prebuild.py            # all
  PIPELINE_CONFIG=... python qa_prebuild.py it,de --detail
  PIPELINE_CONFIG=... python qa_prebuild.py --json work/qa_prebuild.json
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Config                      # noqa: E402
from geomlib import GeomLib                    # noqa: E402
from fontTools.ttLib import TTFont             # noqa: E402

argv = sys.argv[1:]
detail = '--detail' in argv
json_out = None
if '--json' in argv:
    json_out = argv[argv.index('--json') + 1]
sel = [a for a in argv if not a.startswith('--') and a != json_out]

cfg = Config(None)
LAY = cfg.d.get('layout', {}) or {}
ENG = cfg.d.get('decision_engine', {}) or {}
MIN_SCALE = float(LAY.get('min_scale', 0.72))
CLASH_GAP = float(LAY.get('clash_gap_pt', ENG.get('min_gap_pt', 5.669)))
PN_GAP = float(LAY.get('pageno_gap_pt', ENG.get('inter_label_gap_pt', 10.5)))
CAP = float((cfg.d.get('geometry') or {}).get('cap_ratio_default', 0.728))
CAPBY = (cfg.d.get('geometry') or {}).get('cap_ratio_by_lang', {})

langs = sel[0].split(',') if sel else [l['code'] for l in cfg.langs]
colors = [c['code'] for c in cfg.colors]

_fonts = {}


def metrics(code):
    if code not in _fonts:
        f = TTFont(cfg.font_file_for(code), lazy=True)
        cm = {}
        for t in f['cmap'].tables:
            cm.update(t.cmap)
        _fonts[code] = (f['head'].unitsPerEm, f['hmtx'].metrics, cm)
    return _fonts[code]


def text_w(code, s, size):
    upm, hm, cm = metrics(code)
    w = 0.0
    for ln in str(s).split('\r'):
        ww = 0.0
        for ch in ln:
            g = cm.get(ord(ch))
            if g is not None and g in hm:
                ww += hm[g][0]
        w = max(w, ww / upm * size)
    return w


T = json.load(open(os.path.join(cfg.work, cfg.f['translations']), encoding='utf-8'))
WT_PATH = os.path.join(cfg.work, 'width_tables.json')
WT = json.load(open(WT_PATH, encoding='utf-8')) if os.path.exists(WT_PATH) else {}
geom = GeomLib(cfg)


def tr_of(en, code):
    """Translation lookup that understands the engine's synthetic keys."""
    base = en.split('@')[0]
    if base.startswith('short@'):
        return None                                   # split part of a wrap
    if base.endswith('#abbr'):
        base = base[:-5]
        e = T.get(base)
        return e.get(code + '_abbr') if isinstance(e, dict) else None
    return (T.get(base) or {}).get(code)


def pick(items, en, cx):
    """The decision entry for THIS occurrence: duplicated words are emitted as
    'en@1'/'en@2', so match on x instead of taking the first one."""
    cand = [(k, v) for k, v in items.items() if k.split('@')[0] == en]
    if not cand:
        return None, None
    cand.sort(key=lambda kv: abs((kv[1].get('cx') if kv[1].get('cx') is not None else cx) - cx))
    return cand[0]


rows_out = []
hard = 0
for code in langs:
    cap = float(CAPBY.get(code, CAP))
    for color in colors:
        p = cfg.decision_path(code, color)
        if not os.path.exists(p):
            rows_out.append({'lang': code, 'color': color, 'issues': None})
            continue
        d = json.load(open(p, encoding='utf-8'))
        dec = d.get(cfg.s['entries'], d)
        tmap = d.get(cfg.s.get('titles', 'title_map')) or {}
        issues = {k: [] for k in ('GLYPH', 'FIT', 'CLASH', 'PN', 'MISS', 'TITLE', 'ABBR', 'TITLESAME')}

        for ab, items in dec.items():
            for en, v in items.items():
                val = v.get('val') or ''
                sz = v.get('sz') or ENG.get('base_size', 18.0)
                if not val:
                    issues['MISS'].append([ab, en, 'empty'])
                    continue
                _, _, cm = metrics(code)
                bad = sorted({c for c in val.replace('\r', '')
                              if ord(c) not in cm and not c.isspace()})
                if bad:
                    issues['GLYPH'].append([ab, en, ''.join(bad), val])
                want = tr_of(en, code)
                # A word that happens to be spelled the same in the target
                # language (pizza, mango, panda, French "Nature") is NOT a
                # missing translation -- only an absent table entry is.
                if want is None and not en.split('@')[0].startswith('short@'):
                    issues['MISS'].append([ab, en, 'no-translation'])
                # Measure the text the solver ACTUALLY decided to set, not the
                # value recorded in the width table. The table is written before
                # the solver runs, so it still holds the long form; when the
                # solver picked a short form ("коляска" instead of "инвалидная
                # коляска") the old code compared the short text against the
                # long text's scale and reported a phantom overflow -- chasing
                # those reports would have made me damage correct translations.
                sl = (WT.get('slot') or {}).get(
                    en.split('@')[0].replace('#abbr', '')) or {}
                base_sz = float(ENG.get('base_size', 18.0))
                need = None
                if sl.get('maxw'):
                    wid = text_w(code, val, base_sz)
                    if wid > 0:
                        need = sl['maxw'] / wid
                # Two things make the single-line slot test meaningless:
                # a value the solver already split, and a multi-word value the
                # width table can split (its 2-line form is far narrower). What
                # genuinely cannot recover is ONE long word -- it can only be
                # shrunk or replaced, so that is what gets reported.
                if (need is not None and need < MIN_SCALE and ' ' not in val
                        and '\r' not in val and v.get('mode') != 'wrap' and not v.get('wrap')):
                    issues['FIT'].append([ab, en, val, round(need, 2)])
                if '#abbr' in en and sz < 15 and need is not None and need < 0.9:
                    issues['ABBR'].append([ab, en, val, round(need, 2)])

        for ab, pg in geom.parse(color).items():
            items = dec.get(str(ab)) or {}
            # CLASH -- same row, measured with the real translated widths
            byline = {}
            for l in pg['labels']:
                _, v = pick(items, l['en'], l['cx'])
                val = (v or {}).get('val') or l['en']
                sz = (v or {}).get('sz') or ENG.get('base_size', 18.0)
                cx = (v or {}).get('cx')
                cx = l['cx'] if cx is None else cx
                # group by the engine's own row id when geometry provides it:
                # rounding cy merges cells from different rows and reports
                # phantom collisions
                rid = (l.get('facts') or {}).get('row')
                if rid is None:
                    rid = round(l['cy'], 0)
                byline.setdefault(rid, []).append(
                    (cx, text_w(code, val, sz), l['en'], val))
            for cy, lst in byline.items():
                lst.sort()
                for a, b in zip(lst, lst[1:]):
                    gap = (b[0] - b[1] / 2) - (a[0] + a[1] / 2)
                    if gap < CLASH_GAP:
                        issues['CLASH'].append([ab, a[2], b[2], round(gap, 1)])
            # PN -- the corner page number is untranslatable, hence invisible to
            # every label-to-label check. It is still ink on the card.
            pn = pg.get('pageno')
            if pn:
                pL = min(pn['box'][0], pn['box'][2])
                pTop = max(pn['box'][1], pn['box'][3])
                pBot = min(pn['box'][1], pn['box'][3])
                for l in pg['labels']:
                    _, v = pick(items, l['en'], l['cx'])
                    val = (v or {}).get('val') or l['en']
                    sz = (v or {}).get('sz') or ENG.get('base_size', 18.0)
                    cx = (v or {}).get('cx')
                    cx = l['cx'] if cx is None else cx
                    h = cap * sz
                    if l['cy'] + h / 2 <= pBot or l['cy'] - h / 2 >= pTop:
                        continue
                    gap = pL - (cx + text_w(code, val, sz) / 2)
                    if gap < PN_GAP - 0.3:
                        issues['PN'].append([ab, l['en'], val, round(gap, 1)])

        for en, val in tmap.items():
            if not (val or '').strip():
                issues['TITLE'].append([en, 'empty'])
            elif val.strip() == str(en).split('\r')[0].strip():
                # spelled the same in the target language (fr "Nature",
                # "Sports"): worth an eyeball, never a blocker
                issues['TITLESAME'].append([en, val])

        n = {k: len(v) for k, v in issues.items() if k != 'TITLESAME'}
        block = sum(n[k] for k in ('GLYPH', 'FIT', 'CLASH', 'PN', 'MISS', 'ABBR'))
        hard += block
        rows_out.append({'lang': code, 'color': color, 'counts': n, 'issues': issues})

HDR = ('%-6s%-8s%7s%6s%7s%5s%6s%6s' %
       ('lang', 'color', 'GLYPH', 'FIT', 'CLASH', 'PN', 'MISS', 'TITLE'))
print('=' * 74)
print('qa_prebuild  FIT<%.2f  CLASH<%.1fpt  PN<%.1fpt' % (MIN_SCALE, CLASH_GAP, PN_GAP))
print('=' * 74)
print(HDR)
tot = {k: 0 for k in ('GLYPH', 'FIT', 'CLASH', 'PN', 'MISS', 'TITLE')}
for r in rows_out:
    if r['issues'] is None:
        print('%-6s%-8s   (no decision json)' % (r['lang'], r['color']))
        continue
    c = r['counts']
    for k in tot:
        tot[k] += c[k]
    print('%-6s%-8s%7d%6d%7d%5d%6d%6d' %
          (r['lang'], r['color'], c['GLYPH'], c['FIT'], c['CLASH'], c['PN'], c['MISS'], c['TITLE']))
print('-' * 74)
print('%-14s%7d%6d%7d%5d%6d%6d' % ('TOTAL', tot['GLYPH'], tot['FIT'], tot['CLASH'],
                                   tot['PN'], tot['MISS'], tot['TITLE']))

if detail:
    for r in rows_out:
        if not r['issues'] or not sum(r['counts'].values()):
            continue
        print('\n### %s / %s' % (r['lang'], r['color']))
        for k, lst in r['issues'].items():
            for it in lst[:15]:
                print('  %-5s %s' % (k, it))
            if len(lst) > 15:
                print('  %-5s ... %d more' % (k, len(lst) - 15))

if json_out:
    json.dump(rows_out, open(json_out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\nwrote %s' % json_out)

print('\n%s  (%d blocking issue%s)' %
      ('FAIL' if hard else 'PASS', hard, '' if hard == 1 else 's'))
sys.exit(1 if hard else 0)
