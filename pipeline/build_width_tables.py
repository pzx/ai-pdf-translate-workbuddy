# -*- coding: utf-8 -*-
r"""Build the width tables the JSX generator consumes (MAXW / SCALE / FINAL).

    python build_width_tables.py [pipeline.json]

Why this exists
---------------
The original project measured every word by hand and hard-coded two tables
(MAXW = max ink width per word, SCALE = font-size factor) inside its own JSX.
The generic pipeline needs the same numbers, produced automatically from data
it already has: the spans extracted from the source artwork + the translation
table + the real output font metrics.

Output: <work>/width_tables.json
  slot     {en: {maxw, maxink, size, is_title, n}}
  safe     {en: safe_width}
  pos      {en: [[color, page, row, bottom_gap], ...]}
  per_lang {lang: {en: {"val": text (may contain \r), "scale": factor}}}

Rules baked in (all configurable under "layout" in pipeline.json):
  * a word wider than its safe slot is first wrapped onto two lines, but only
    where there is enough empty space below it (wrap_space_pt);
  * wrapping balances the two lines and never splits a single word;
  * if wrapping is not allowed/possible the font size is scaled down, but never
    below min_scale (a word that still overflows is reported, not hidden);
  * titles are NOT handled here: their size comes from the artwork itself and
    is fitted to the title oval by make_jsx.py.
"""
import os
import sys
import json
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Config
from fontTools.ttLib import TTFont

cfg = Config(sys.argv[1] if len(sys.argv) > 1 else None)
lay = cfg.d.get('layout', {})
THRESH = float(lay.get('body_thresh_pt', 135))
TITLE_MAXW = float(lay.get('title_maxw_pt', 105))
SPACE_NEED = float(lay.get('wrap_space_pt', 26))
# A label that runs into the card's bottom edge may still be wrapped: make_jsx
# lifts the two-line block (and its illustration) by the shortfall, capped at
# this many points. So the required gap below shrinks by the same amount -- this
# is what lets bottom-row labels wrap instead of being force-shortened.
WRAP_LIFT = float(lay.get('wrap_lift_pt', 11))
MIN_GAP = max(0.0, SPACE_NEED - WRAP_LIFT)
MIN_SCALE = float(lay.get('min_scale', 0.72))
# HARD RULE: only TITLES may be resized. Body words keep the artwork's font size;
# when a translation does not fit they are wrapped, shortened or reported -- never
# shrunk. (Shrinking body text breaks the size symmetry the cards rely on.)
BODY_SHRINK = bool(lay.get('body_shrink', False))

_sp = os.path.join(cfg.work, cfg.f['spans'])
if not os.path.exists(_sp):
    raise SystemExit('spans not found: %s\n'
                     'run: python export_spans.py   (it reads the source .ai files)' % _sp)
spans = json.load(open(_sp, encoding='utf-8'))
D = json.load(open(os.path.join(cfg.work, cfg.f['translations']), encoding='utf-8'))
LANGS = {l['code']: l for l in cfg.d.get('languages', [])}

# ---- 0. page height + body style, measured (not assumed) --------------------
def _page_height(color):
    try:
        import pymupdf
        doc = pymupdf.open(cfg.source_path(color))
        h = doc[0].rect.height
        doc.close()
        return h
    except Exception:
        return float(lay.get('page_height', 0)) or 314.6

PAGE_H = _page_height(next(iter(spans)))

def _body_style():
    """The body text style = the (colour, size) pair carrying the most words."""
    tally = {}
    for _c, rows in spans.items():
        for s in rows:
            if not (s.get('text') or '').strip():
                continue
            k = (int(s['color']), round(float(s['size']), 2))
            tally[k] = tally.get(k, 0) + 1
    return max(tally, key=tally.get) if tally else (0, 18.0)

BODY_COLOR, BODY_SIZE = _body_style()

# ---- 1. slot / safe / pos ---------------------------------------------------
slot, safe, pos = {}, {}, {}
for color, rows in spans.items():
    for s in rows:
        t = (s['text'] or '').strip()
        if not t:
            continue
        w = s['bbox'][2] - s['bbox'][0]
        is_title = (int(s['color']) != BODY_COLOR) or (abs(float(s['size']) - BODY_SIZE) > 0.6)
        info = slot.setdefault(t, dict(maxw=TITLE_MAXW if is_title else THRESH,
                                       maxink=0.0, size=0.0, is_title=is_title, n=0))
        info['n'] += 1
        info['maxink'] = round(max(info['maxink'], w), 1)
        info['size'] = max(info['size'], float(s['size']))
        if not is_title:
            cy = (s['bbox'][1] + s['bbox'][3]) / 2
            gap = PAGE_H - s['bbox'][3]          # empty space below the word
            col = int(((s['bbox'][0] + s['bbox'][2]) / 2) // 60)   # column bucket
            pos.setdefault(t, []).append(
                [color, s['page'], 'top' if cy < PAGE_H * 0.7 else 'bot', round(gap, 1), col])

def safe_width(ink, n):
    """Fallback slot width from the word's own ink width (used only when the
    artwork gives us no neighbour to measure against)."""
    return max(80.0, min(THRESH, round(ink + (40 if n >= 2 else 42), 1)))

# ---- 1b. real horizontal room = the COLUMN PITCH, not the ink gap -----------
# A label is centred under its artwork, so it may grow sideways -- but only
# until it meets the neighbouring label doing the same. Measuring the ink gap
# alone lied badly: a label alone on its visual row, or with a wide neighbour,
# reported 200pt of "room" (365/635 slots hit the old 200 cap, median 200), so
# "wider than the slot -> wrap" almost never fired and long words ran into the
# next column. Two labels on a pitch P can each take P-2*PAD before they touch,
# which is exactly the ~119pt the validated reference project used (P=139.6).
PAD = float(cfg.d.get('decision_engine', {}).get('inter_label_gap_pt', 10.5))
ROOM_FLOOR = float(lay.get('room_floor_pt', 80))
room = {}
for color, rows in spans.items():
    bypage = {}
    for s in rows:
        t = (s.get('text') or '').strip()
        if not t:
            continue
        if int(s['color']) != BODY_COLOR or abs(float(s['size']) - BODY_SIZE) > 0.6:
            continue
        bypage.setdefault(s['page'], []).append(s)
    for page, items in bypage.items():
        items.sort(key=lambda s: (s['bbox'][1] + s['bbox'][3]) / 2.0)
        rows2 = []
        for s in items:
            cy = (s['bbox'][1] + s['bbox'][3]) / 2.0
            if rows2 and abs(cy - rows2[-1][0]) <= 8:
                rows2[-1][1].append(s)
            else:
                rows2.append([cy, [s]])
        for cy, group in rows2:
            group.sort(key=lambda s: s['bbox'][0])
            for i, s in enumerate(group):
                w = s['bbox'][2] - s['bbox'][0]
                cx = (s['bbox'][0] + s['bbox'][2]) / 2.0
                pitches = [abs(cx - (g['bbox'][0] + g['bbox'][2]) / 2.0)
                           for j, g in ((i - 1, group[i - 1] if i > 0 else None),
                                        (i + 1, group[i + 1] if i + 1 < len(group) else None))
                           if g is not None]
                if pitches:
                    # shared budget with the closest neighbour: P - 2*PAD, and
                    # never narrower than this word's own ink (it already fits)
                    avail = max(w, min(pitches) - 2 * PAD)
                else:
                    avail = THRESH          # alone on its row: only the cap applies
                avail = max(ROOM_FLOOR, min(THRESH, avail))
                t = s['text'].strip()
                room[t] = min(room.get(t, 1e9), avail)

for en, info in slot.items():
    if info['is_title']:
        safe[en] = TITLE_MAXW
    else:
        safe[en] = round(min(THRESH, room.get(en, safe_width(info['maxink'], info['n']))), 1)
    info['maxw'] = safe[en]          # JSX reads slot.maxw as the overflow test

# ---- 2. compound source keys ("word\r(word)" / "two\rwords") ----------------
# The artwork splits some labels over two lines; the frame content therefore
# carries "\r". Build their translation from the per-line translations: a
# parenthetical second line is a synonym (US/UK) and is dropped, anything else
# is a genuine second line and is translated line by line.
compound = set()
DECVAL, DVWRAP = {}, {}
for f in glob.glob(os.path.join(cfg.work, 'v7_dec_*.json')) + \
         glob.glob(os.path.join(cfg.work, '*decision*.json')):
    # Only real decision files are "v7_dec_<lang>_<color>.json". A tuning file
    # whose name merely contains "decision" (decision_tuning.json) used to be
    # parsed as one and crashed the whole step on an IndexError.
    _base = os.path.basename(f)
    _parts = _base[:-5].split('_') if _base.endswith('.json') else []
    if len(_parts) < 4 or _parts[0] != 'v7' or _parts[1] != 'dec':
        continue
    try:
        dd = json.load(open(f, encoding='utf-8'))
    except Exception:
        continue
    _lg = _parts[2]
    for recs in (dd.get(cfg.s['entries'], {}) or {}).values():
        for k, rec in (recs or {}).items():
            if '\r' in str(k):
                compound.add(k)
            if not isinstance(rec, dict):
                continue
            v = rec.get('val')
            if isinstance(v, str):
                DECVAL.setdefault((_lg, k), set()).add(v)
            if rec.get('wrap'):
                DVWRAP[(_lg, k)] = 1

def build_compound(lang):
    out = {}
    for key in compound:
        # 1) an explicit whole-phrase translation wins ("washing\r machine" is
        #    ONE idea split over two lines; translating line-by-line gives
        #    "lavare / macchina", which is nonsense)
        if key in D and D[key].get(lang):
            out[key] = D[key][lang]
            continue
        parts = str(key).split('\r')
        if len(parts) == 2 and parts[1].strip().startswith('('):
            if parts[0] in D and D[parts[0]].get(lang):
                out[key] = D[parts[0]][lang]        # synonym line -> single word
            continue
        trans = [D[p][lang] for p in parts if p in D and D[p].get(lang)]
        if len(trans) == len(parts):
            out[key] = '\r'.join(trans)
    return out

# ---- 3. per-language FINAL text + SCALE ------------------------------------
def measurer(path):
    f = TTFont(path)
    upm = f['head'].unitsPerEm
    hmtx = f['hmtx'].metrics
    cmap = {}
    for t in f['cmap'].tables:
        cmap.update(t.cmap)
    def width(s, size=BODY_SIZE):
        return sum(hmtx[cmap[ord(ch)]][0] for ch in s if ord(ch) in cmap) / upm * size
    return width

def wrap_balanced(text, maxw, W):
    if W(text) <= maxw:
        return text, 1.0
    words = text.split()
    if len(words) == 1:
        return None, maxw / W(text)          # cannot wrap a single word
    best = None
    for i in range(1, len(words)):
        l1, l2 = ' '.join(words[:i]), ' '.join(words[i:])
        m = max(W(l1), W(l2))
        if best is None or m < best[0]:
            best = (m, l1, l2)
    _, l1, l2 = best
    scale = maxw / best[0] if best[0] > maxw else 1.0
    return l1 + '\r' + l2, scale

per_lang = {}
overflows = {}
shorted_list = {}
for lang, lcfg in LANGS.items():
    W = measurer(cfg.font_file_for(lang))
    MAP_ALL = dict(D)
    for k, v in build_compound(lang).items():
        MAP_ALL[k] = {lang: v}

    # Second lines of two-line labels exist as their own keys too. Only THOSE
    # must stay out of the wrap race (they stole the column from their own first
    # line, forcing "subway station" down to "metro" though it had 100pt free).
    # A parenthetical that is NOT the second line of any compound key is a real
    # standalone label and must be treated like any other word.
    second_lines = set()
    for _k in MAP_ALL:
        if '\r' in str(_k):
            for _part in str(_k).split('\r')[1:]:
                if _part.strip().startswith('('):
                    second_lines.add(_part.strip())

    need = {}
    for en, entry in MAP_ALL.items():
        val = entry.get(lang) if isinstance(entry, dict) else entry
        if not val or slot.get(en, {}).get('is_title'):
            continue
        if str(en).strip() in second_lines:
            continue
        # compound keys are not in `slot` (spans are per line): inherit the
        # room of their first line instead of falling back to a 102pt guess
        sw = (safe.get(en) or safe.get(str(en).split('\r')[0])
              or safe_width(slot.get(en, {}).get('maxink', 60), 1))
        if W(val) > sw + 1.5:
            # `pos` is keyed by the text of a single source line, so a compound
            # key ("washing\rmachine") must look up its FIRST line -- otherwise
            # it has no recorded position, maxgap=0, and can never wrap.
            poses = pos.get(en, []) or pos.get(str(en).split('\r')[0], [])
            maxgap = max((p[3] for p in poses), default=0.0)
            need[en] = (val, sw, maxgap)

    # one wrap per COLUMN slot (not per whole row): two columns of the same row
    # are horizontally far apart, so both may carry a two-line label -- capping
    # it per row forced needless short translations ("negozio di giocattoli"
    # had 130pt of free space below and still got shortened).
    row_wrap = {}
    for en in sorted(need, key=lambda e: (need[e][2] >= SPACE_NEED, W(need[e][0]) / need[e][1]),
                     reverse=True):
        if need[en][2] < MIN_GAP:
            continue
        for p in (pos.get(en, []) or pos.get(str(en).split('\r')[0], [])):
            if p[3] < MIN_GAP:
                continue
            rk = (p[0], p[1], p[2], p[4] if len(p) > 4 else 0)
            if rk not in row_wrap:
                row_wrap[rk] = en
                break
    wrapped = set(row_wrap.values())

    out, overflow, shorted = {}, [], []
    for en, entry in MAP_ALL.items():
        val = entry.get(lang) if isinstance(entry, dict) else entry
        if not val:
            continue
        sw = (safe.get(en) or safe.get(str(en).split('\r')[0])
              or safe_width(slot.get(en, {}).get('maxink', 60), 1))
        # -- WHO DECIDES THE WRAP ------------------------------------------
        # The decision layer already proved, against the CARD FRAME and the
        # neighbouring labels, whether a two-line block fits. A single line that
        # is merely wider than the column slot but still inside the card is
        # legitimate (it may have been shifted inward), so the slot must NOT
        # force a wrap or a short translation here.
        if '\r' in val:
            out[en] = {'val': val, 'scale': 1.0}        # already two lines
        elif DVWRAP.get((lang, en)) and ' ' in val:
            s2, _sc = wrap_balanced(val, sw, W)         # flagged but still 1 line
            out[en] = {'val': s2 or val, 'scale': 1.0}
        else:
            out[en] = {'val': val, 'scale': 1.0}

        # report only: wider than the column slot. Trustworthy as a smell, not
        # as an error -- the card edge is what actually matters.
        w0 = max((W(p) for p in out[en]['val'].split('\r')), default=0.0)
        if w0 > sw + 0.5:
            overflow.append({'en': en, 'val': out[en]['val'].replace('\r', ' | '),
                             'width': round(w0, 1), 'slot': sw,
                             'need_scale': round(sw / w0, 3)})
        # keep the JSX overflow guard honest: MAXW is the width we PLANNED, so a
        # planned-but-wide single line must not raise BODY-OVERFLOW at build time
        if slot.get(en) and not slot[en].get('is_title'):
            slot[en]['maxw'] = round(max(sw, w0) + 0.6, 1)
    per_lang[lang] = out
    # A label whose artwork splits it over two lines exists TWICE in the maps:
    # as "subway station" and as "subway station\r(underground station)". They
    # are the same physical label, so the compound must inherit the treatment
    # its first line got -- otherwise one copy wraps/shortens and the other
    # copy keeps the long text, and the page shows the long one.
    for en in list(out):
        if '\r' not in en:
            continue
        base = out.get(en.split('\r')[0])
        if not base:
            continue
        if W(base['val']) < W(out[en]['val']) - 0.5:
            out[en] = dict(base)
    # sorted: an unsorted list made two identical runs produce different files
    # (set/dict iteration order), which turns every diff into noise
    overflows[lang] = sorted(
        [o for o in overflow if W(out.get(o['en'], {}).get('val', o['val'])) > o['slot'] + 0.5],
        key=lambda o: o['en'])
    shorted_list[lang] = shorted

json.dump(dict(slot=slot, safe=safe, pos=pos, per_lang=per_lang,
               overflow=overflows, short=shorted_list),
          open(os.path.join(cfg.work, 'width_tables.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)

print('body style: color=0x%06X size=%.1f | page height=%.1f' % (BODY_COLOR, BODY_SIZE, PAGE_H))
print('slot:', len(slot), '| title:', sum(1 for v in slot.values() if v['is_title']),
      '| body:', sum(1 for v in slot.values() if not v['is_title']),
      '| compound keys:', len(compound))
print('body shrink:', 'ON' if BODY_SHRINK else 'OFF (only titles may resize)')
for lang in LANGS:
    pl = per_lang[lang]
    scaled = [e for e, r in pl.items() if r['scale'] < 1.0]
    wrapped = [e for e, r in pl.items() if '\r' in r['val']]
    print('  %-5s scaled=%-3d wrapped=%-3d overflow(keep size, needs review)=%-3d %s' % (
        lang, len(scaled), len(wrapped), len(overflows[lang]),
        ', '.join('%s x%.2f' % (e, pl[e]['scale']) for e in scaled[:4])))
    for o in overflows[lang][:5]:
        print('      ! %-22s w=%.1f > slot %.1f (需缩到 %.2f，未缩)' % (
            o['en'].replace('\r', '/'), o['width'], o['slot'], o['need_scale']))
print('wrote', os.path.join(cfg.work, 'width_tables.json'))
