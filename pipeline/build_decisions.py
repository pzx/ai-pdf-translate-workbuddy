# -*- coding: utf-8 -*-
r"""Generic layout decision engine: source geometry + translations -> decisions.

    python build_decisions.py it purple        # one book
    python build_decisions.py all              # every language x colour
    python build_decisions.py it               # all colours for one language

Reads geom_<color>.tsv / inner_<color>.tsv / ink_<color>.tsv (via geomlib)
and a translations table, then solves a LAYOUT-AGNOSTIC placement for every
label so the output carries real `cx` / `dy` / `sz`. This is the engine that
the decision-completeness gate in make_jsx.py requires.

Layout-agnostic parts (generic):
  - keep label centred on its source position / own illustration
  - never worse clearance than the English source (frame/page/illustration/text)
  - single -> short -> wrap -> shift -> manual ladder, row packing + row align
Project-specific tuning (SHORT/SIZEFIX/COMPOUND/MANUAL_TITLE) is OPTIONAL and
lives in a separate JSON named by config.files.decision_tuning. A new project
can omit it entirely and still get cx/dy/sz for ordinary layouts.

Translations table format (config.files.translations):
    {"<english>": {"<lang_code>": "<translation>", ...}, ...}
Soft line breaks are '\\r'. A key with a parenthetical like "ice cream\\r(vanilla)"
falls back to its first part if the full key is absent.
"""
import os, sys, json, collections
from fontTools.ttLib import TTFont
from common import Config, norm
from geomlib import GeomLib

cfg = Config()
HERE = os.path.dirname(os.path.abspath(__file__))
S = cfg.s


def font_file(lang):
    """Resolve the font file for width measurement (see Config.resolve_font_file)."""
    return cfg.font_file_for(lang)


def load_translations():
    p = os.path.join(cfg.work, cfg.f.get('translations', 'translations.json'))
    if not os.path.exists(p):
        raise SystemExit('translations table not found: %s' % p)
    return json.load(open(p, encoding='utf-8'))


def load_tuning():
    key = cfg.f.get('decision_tuning')
    if not key:
        return {}
    p = os.path.join(cfg.work, key)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}


TUNE = load_tuning()
# R4: persistent hand-edit position corrections.  Keyed by "<ab>|<english key>"
# under lang->color. Applied at write time so a clean rebuild reproduces the
# reviewer's placement without any manual patch to the generated decisions.
POS = {}
for _lang, _colors in (TUNE.get('pos', {}) or {}).items():
    for _color, _recs in _colors.items():
        for _k, _d in _recs.items():
            POS[(_lang, _color, _k)] = _d
SIZEFIX = {}
for _lang, _items in TUNE.get('sizefix', {}).items():
    for _en, _sz in _items.items():
        SIZEFIX[(_lang, _en)] = _sz
COMPOUND = TUNE.get('compound', {})
MANUAL_TITLES = TUNE.get('titles', {})

# tuning constants (all overridable via config.decision_engine; defaults were
# validated on a 24-page bilingual card deck)
P = cfg.d.get('decision_engine', {})
MM = float(P.get('min_gap_pt', 2 / 25.4 * 72))
IGH = float(P.get('inter_label_gap_pt', 10.5))
GAP_OWN = float(P.get('own_illus_gap_pt', 1.0))
DX_MAX = float(P.get('shift_cap_pt', 8.0))
COL_RATIO = float(P.get('column_ratio', 0.25))
UP_MAX = float(P.get('wrap_lift_cap_pt', 12.0))
RELAX_DX = float(P.get('relax_shift_pt', 26.0))
BASE_SIZE = float(P.get('base_size', 18.0))
LEAD_EXTRA = float(P.get('lead_extra_pt', 1.0))

# The corner page number is NOT a translatable label, so it never enters
# state[] -- which is why a long word used to grow straight into it: a shipped
# deck had "accovacciarsi" 4.8pt from the "16" and "cavolo riccio" at 1.1pt,
# i.e. printing on top of it. It is a hard right-hand obstacle for any label on
# the same row, not just something below the text.
LAY = cfg.d.get('layout', {}) or {}
PN_GAP = float(LAY.get('pageno_gap_pt', IGH))       # keep >= inter-label gap
PN_SHIFT_CAP = float(LAY.get('pageno_shift_cap_pt', 16.0))
# Body type is FIXED on this deck family: only a card title may change size.
# The solver therefore has no "shrink" rung -- a label that cannot fit is
# reported (PN-TIGHT / manual) for the translator to reword, never silently
# set smaller than the rest of the card.

T = load_translations()

# Short forms live in the translation table as "<lang>_short" (that is where the
# reviewer edits them). The decision layer used to read only the project-level
# tune.short, which is empty in a normal project -> every "cannot fit" label fell
# through to mode=manual and shipped at full length.
SHORT = {}
for _en, _rec in (T.items() if isinstance(T, dict) else []):
    if not isinstance(_rec, dict):
        continue
    for _k, _v in _rec.items():
        if _k.endswith('_short') and isinstance(_v, str) and _v.strip():
            SHORT.setdefault(_k[:-6], {})[_en] = _v.replace('\n', '\r')
for _lang, _items in (TUNE.get('short', {}) or {}).items():
    SHORT.setdefault(_lang, {}).update(_items)
GL = GeomLib(cfg)


def make_engine(lang, color):
    fp = font_file(lang)
    f = TTFont(fp)
    head = f['head']
    UPM = head.unitsPerEm if hasattr(head, 'unitsPerEm') else head['unitsPerEm']
    HM = f['hmtx'].metrics
    CMAP = {}
    for t in f['cmap'].tables:
        CMAP.update(t.cmap)

    def width(s, size=BASE_SIZE):
        return sum(HM[CMAP[ord(c)]][0] for c in s if ord(c) in CMAP) / UPM * size

    o = f['OS/2']
    asc = o.sTypoAscender if hasattr(o, 'sTypoAscender') else o['sTypoAscender']
    desc = o.sTypoDescender if hasattr(o, 'sTypoDescender') else o['sTypoDescender']
    typo = (asc - desc) / UPM * BASE_SIZE
    lead = round(typo + LEAD_EXTRA, 1)
    print('LANG=%s COLOR=%s font=%s typo=%.2f LEAD=%.1f' %
          (lang, color, os.path.basename(fp), typo, lead))

    def tr(en):
        e = T.get(en)
        if e is None:
            # parenthetical fallback: "word\r(hint)" -> use "word"
            head = str(en).split('\r')[0]
            e = T.get(head)
        v = e.get(lang) if isinstance(e, dict) else e
        if isinstance(v, str):
            return v.replace('\n', '\r')
        return en

    def line_w(v):
        return max(width(ln) for ln in str(v).split('\r'))

    def wrap2(v):
        words = str(v).split()
        if len(words) < 2:
            return v
        best = None
        for i in range(1, len(words)):
            l1 = ' '.join(words[:i]); l2 = ' '.join(words[i:])
            m = max(width(l1), width(l2))
            if best is None or m < best[0]:
                best = (m, l1, l2)
        return best[1] + '\r' + best[2]

    def abbr(en):
        """Small-form translation ("<lang>_abbr"), used when one English string
        plays both the abbreviated and the full-length role on a card."""
        e = T.get(en)
        if isinstance(e, dict):
            v = e.get(lang + '_abbr')
            if isinstance(v, str) and v:
                return v.replace('\n', '\r')
        return None

    title_map = {}
    # Titles are driven by the geometry's T objects, not by guessing from the
    # whole translation table (which would misclassify body words as titles).
    # The generic exporter fills T.en; legacy TSVs may leave it empty, in which
    # case we fall back to matching T objects by their exact box to any label
    # key from MANUAL_TITLES only.
    title_keys = set()
    for pg in GL.parse(color).values():
        tg = pg.get('title')
        if tg and tg.get('en'):
            title_keys.add(tg['en'])
    if not title_keys:
        title_keys = set(MANUAL_TITLES.get(lang, {}).keys())
    # sorted: title_keys is a set, so an unsorted loop made title_map's key
    # order (and therefore the generated JSX) change on every run
    for en in sorted(title_keys):
        e = T.get(en)
        if e is None:
            head = str(en).split('\r')[0]
            e = T.get(head)
        v = e.get(lang) if isinstance(e, dict) else e
        if isinstance(v, str) and v:
            title_map[en] = v.replace('\n', '\r')
    title_map.update(MANUAL_TITLES.get(lang, {}))

    ink = GL.ink_boxes(color)
    pages = GL.parse(color)
    return dict(width=width, lead=lead, tr=tr, line_w=line_w, wrap2=wrap2,
                abbr=abbr, title_map=title_map, ink=ink, pages=pages)


def solve_book(lang, color):
    eng = make_engine(lang, color)
    width, lead = eng['width'], eng['lead']
    tr, line_w, wrap2 = eng['tr'], eng['line_w'], eng['wrap2']
    title_map, ink, pages = eng['title_map'], eng['ink'], eng['pages']
    abbr_value = eng['abbr']
    span_sizes = {}
    for _s in cfg.spans.get(color, []):
        _t = (_s.get('text') or '').strip()
        if _t:
            span_sizes.setdefault((int(_s.get('page', 0)), _t), []).append(
                float(_s.get('size') or 0))

    # ---- coverage guard -------------------------------------------------
    # A missing entry makes tr() fall back to the ENGLISH text silently: the
    # decision still gets a cx, make_jsx "replaces" the word with itself, and
    # the PDF passes verify.py (pages ok, text=0) while being untranslated.
    # Refuse to build a book the translation table does not cover.
    _all_en = {l['en'] for pg in pages.values() for l in pg['labels']}
    _miss = sorted(e for e in _all_en
                   if T.get(e) is None and T.get(str(e).split('\r')[0]) is None)
    if _miss:
        _rate = len(_miss) / max(1, len(_all_en))
        print('  TRANS-MISSING %s/%s: %d/%d label(s) have no entry (%.0f%%)'
              % (lang, color, len(_miss), len(_all_en), _rate * 100))
        for _e in _miss[:15]:
            print('    - %r' % _e)
        if _rate > 0.10:
            raise SystemExit(
                'REFUSED: translation table covers only %.0f%% of %s/%s. '
                'Filling it in is cheaper than shipping English cards.'
                % (100 - _rate * 100, lang, color))
    _same = sorted(e for e in _all_en if tr(e) == e)
    if _same:
        print('  note: %d label(s) intentionally keep the English text (%s): %s'
              % (len(_same), lang, ', '.join(map(repr, _same[:8]))))

    # ---- facts guard ----------------------------------------------------
    # Every decision above (card edge, row lift, text clearance) is derived from
    # the page facts. A page without an inner frame used to be skipped with a
    # bare `continue`: its labels kept the English text and the build stayed
    # green. Same for pages whose labels have no matching illustration -- the
    # lift budgets silently become 0.
    _no_frame = sorted(int(ab) + 1 for ab, pg in pages.items()
                       if pg['labels'] and not pg.get('frame_inner'))
    if _no_frame:
        raise SystemExit(
            'REFUSED %s/%s: no inner card frame on page(s) %s.\n'
            '  frame_inner comes from files.geom_inner (export_geometry.py); without it the card\n'
            '  edges are unknown, so wrapping and in-card shifting cannot be decided.\n'
            '  Fix: run export_geometry.py %s (it must emit the inner TSV).'
            % (lang, color, _no_frame, color))
    _lab_all = [l for pg in pages.values() for l in pg['labels']]
    _no_art = [l['en'] for l in _lab_all if not (l.get('facts') or {}).get('ill')]
    _lim = float((cfg.d.get('layout') or {}).get('facts_max_missing_ratio', 0.5))
    if _no_art:
        _r2 = len(_no_art) / max(1, len(_lab_all))
        if _r2 >= 0.35:
            print('  FACTS-NOART %s/%s: %d/%d label(s) have no matching illustration (%.0f%%)'
                  % (lang, color, len(_no_art), len(_lab_all), _r2 * 100))
            for _e in _no_art[:12]:
                print('    - %r' % _e)
        if _r2 > _lim:
            raise SystemExit(
                'REFUSED %s/%s: %.0f%% of labels have no own illustration.\n'
                '  geometry_export.illus_above / own_illus_cy_gap do not match this layout,\n'
                '  so the lift budgets would all be 0 and bottom rows would be short-translated.'
                % (lang, color, _r2 * 100))

    DEC, TITLES, SHORT_USED, PENDING, REPORT = {}, {}, {}, [], []
    for ab, pg in pages.items():
        if not pg['labels']:
            continue
        fr = pg['frame_inner']
        fx0, fx1 = fr[0] + MM, fr[2] - MM
        fyt, fyb = fr[1] - MM, fr[3] + MM
        labels = pg['labels']

        # ---- one English string, two roles on the same card ----------------
        # 'May' is the small abbreviation printed inside the calendar cell AND
        # the full month name printed below it. A decision key is the English
        # text, so one entry cannot carry two translations ('Mag.' vs 'maggio').
        # The TOPMOST duplicate (the small band) is promoted to its own key
        # "<en>#abbr" whose value comes from the "<lang>_abbr" table; make_jsx
        # then picks it by the frame's own font size. Requires the two
        # occurrences to really differ in size (>=1.25x), so ordinary repeated
        # words are untouched.
        page_no = ab + 1 if cfg.s.get('ab_is_zero_based', True) else ab
        _dups = {}
        for _l in labels:
            _dups.setdefault(_l['en'], []).append(_l)
        abbr_rows = {}
        for _en, _rows in _dups.items():
            if len(_rows) < 2:
                continue
            _szs = sorted(set(span_sizes.get((page_no, _en), [])))
            if len(_szs) < 2 or max(_szs) / min(_szs) < 1.25:
                continue
            _val = abbr_value(_en)
            if not _val:
                PENDING.append('ABBR-MISS %s ab%d %r (add "%s_abbr")'
                               % (color, ab, _en, lang))
                continue
            _row = max(_rows, key=lambda r: r['cy'])   # the band sits highest
            abbr_rows[_en] = (_row, _val, min(_szs))
        tg = pg.get('title')
        if tg:
            TITLES[str(ab)] = {'box': tg['box'], 'cx': tg['cx'], 'cy': tg['cy'],
                               'en': tg.get('en', '')}

        def own_box(l):
            o = l.get('own_illus')
            if not o:
                return None
            return ink.get((ab, round(o['cx']), round(o['cy'])), o['box'])

        # R3 homograph disambiguation: the SAME English word can legitimately
        # appear twice on one artboard with different meanings and the SAME size
        # (e.g. "short" = not-tall vs not-long). state[] is keyed by the English
        # word, so the two labels used to collapse into one decision and
        # Illustrator rendered one of them twice (overlapping) while leaving the
        # other blank. Record every occurrence's x position; at write time we
        # emit "en@1"/"en@2" with per-position values (the translation table may
        # give "short@1"/"short@2" distinct words).
        DUPPOS = {}
        _byen = {}
        for l in labels:
            _byen.setdefault(l['en'], []).append(l)
        for _en, _rows in _byen.items():
            if len(_rows) > 1 and _en not in abbr_rows:
                DUPPOS[_en] = sorted(round(float(x['cx']), 1) for x in _rows)

        state = {}
        for l in labels:
            _ab = abbr_rows.get(l['en'])
            if _ab and l is _ab[0]:
                continue          # the band is emitted as "<en>#abbr" below
            state[l['en']] = {'val': tr(l['en']), 'cx': l['cx'], 'dy': 0.0,
                              'illdy': 0.0, 'rowdy': 0.0, 'mode': 'keep'}
            if (lang, l['en']) in SIZEFIX:
                state[l['en']]['sz'] = SIZEFIX[(lang, l['en'])]

        # Per-label lift budget for a TWO-LINE rewrite (make_jsx consumes it):
        #   ill   : the label's own illustration box
        #   room  : how far the text alone may rise before it touches that art
        #           (many labels sit well below their picture, so text-only is
        #            enough and nothing else has to move)
        #   illok : 1 only for the BOTTOM row of a card -- the one case where the
        #           art may travel with the text; everywhere else the text must
        #           fit in `room`, otherwise the label is reported (WRAP-TIGHT)
        # Facts come from geomlib (_attach_facts) -- row id, own art box, the
        # text-only clearance, the bottom-row flag and the head-room above the
        # art. Deriving them here again is what produced the inverted-sign bug.
        OGAP_PT = float(P.get('obstacle_gap_pt', 2.0))
        BOTTOM_ROW_PT = float(P.get('bottom_row_pt', 60.0))
        ILLBOX, ILLMETA, ROWS = {}, {}, {}
        for _l in labels:
            _f = _l.get('facts') or {}
            if _f.get('ill'):
                ILLBOX[_l['en']] = _f['ill']
            ILLMETA[_l['en']] = {'room': _f.get('room', 0.0),
                                 'illok': _f.get('illok', 0),
                                 'ceil': _f.get('ceil'),
                                 'hasart': 1 if _f.get('ill') else 0,
                                 'row': _f.get('row')}
        for _rn, _members in (pg.get('rows') or {}).items():
            ROWS[_rn] = [m['en'] for m in _members]

        hs = sorted(l['box'][1] - l['box'][3] for l in labels
                    if 12 < (l['box'][1] - l['box'][3]) < 30)
        H1 = hs[len(hs) // 2] if hs else 19.4

        def h1_of(l):
            h = l['box'][1] - l['box'][3]
            return h if 12 < h < 30 else H1

        def box_of(l, cx, val, dy=0.0):
            k = (state.get(l['en'], {}).get('sz') or BASE_SIZE) / BASE_SIZE
            h = (h1_of(l) + (lead if '\r' in val else 0.0)) * k
            top = l['box'][1] + dy
            w = line_w(val) * k
            return [cx - w / 2, top, cx + w / 2, top - h]

        def obstacles_below(l):
            best = fyb
            for ii in pg['illus']:
                if ii is l.get('own_illus'):
                    continue
                b = ii['box']
                if b[1] >= l['box'][3] - 1:
                    continue
                if not (b[2] > l['box'][0] - 8 and b[0] < l['box'][2] + 8):
                    continue
                best = max(best, b[1])
            if pg['pageno'] and pg['pageno']['box'][1] < l['box'][3] and abs(pg['pageno']['cx'] - l['cx']) < 120:
                best = max(best, pg['pageno']['box'][1])
            for oen, st in state.items():
                if oen == l['en']:
                    continue
                lo = [x for x in labels if x['en'] == oen][0]
                if abs(lo['cx'] - l['cx']) > 60:
                    continue
                ob = box_of(lo, st['cx'], st['val'], st['dy'])
                if ob[1] >= l['box'][3] - 1:
                    continue
                if ob[3] < l['box'][1]:
                    best = max(best, ob[1])
            return best

        def sep(a, b):
            hx = max(b[0] - a[2], a[0] - b[2])
            if a[3] > b[1]:
                vy = a[3] - b[1]
            elif b[3] > a[1]:
                vy = b[3] - a[1]
            else:
                vy = 0.0
            return max(hx, vy)

        BY_EN = dict((x['en'], x) for x in labels)

        def violations(en, box, others, ignore=()):
            v = []
            if box[0] < fx0 - 0.3 and 'LF' not in ignore: v.append('LF')
            if box[2] > fx1 + 0.3 and 'RF' not in ignore: v.append('RF')
            if box[3] < fyb - 0.3 and 'BF' not in ignore: v.append('BF')
            if box[1] > fyt + 0.3 and 'TF' not in ignore: v.append('TF')
            l = BY_EN[en]
            # WCLEAR: the artwork's own cushion. The source design routinely
            # leaves only 1-2 pt between a label and an illustration BOUNDING
            # box (bboxes have empty margins), so requiring the general 2 mm
            # here vetoed every two-line rewrite at the last step.
            WC = float(P.get('wrap_clear_pt', 1.0))
            if pg['pageno'] and 'PN' not in ignore:
                if sep(box, pg['pageno']['box']) < min(WC, sep(l['box'], pg['pageno']['box'])) - 0.01:
                    v.append('PN')
            if 'IL' not in ignore:
                for ii in pg['illus']:
                    if ii is l.get('own_illus'):
                        continue
                    if sep(box, ii['box']) < min(WC, sep(l['box'], ii['box'])) - 0.01:
                        v.append('IL'); break
            if 'TX' not in ignore:
                for oen, ob in others.items():
                    if oen == en:
                        continue
                    lim = min(IGH, sep(l['box'], BY_EN[oen]['box']))
                    if sep(box, ob) < lim - 0.01:
                        v.append('TX'); break
            return v

        def others_boxes(skip=None):
            ob = {}
            for en, st in state.items():
                if en == skip:
                    continue
                l = [x for x in labels if x['en'] == en][0]
                ob[en] = box_of(l, st['cx'], st['val'], st['dy'])
            return ob

        def col_ok(l, cx, maxdx=None):
            mx = DX_MAX if maxdx is None else maxdx
            o = l.get('own_illus')
            if not o:
                return abs(cx - l['cx']) <= mx
            tol = max(mx, COL_RATIO * o['w'])
            return abs(cx - o['cx']) <= tol and abs(cx - l['cx']) <= mx

        def try_single(en, val, maxdx=None):
            mx = DX_MAX if maxdx is None else maxdx
            l = [x for x in labels if x['en'] == en][0]
            ob = others_boxes(en)
            steps = int(mx / 0.5)
            for cx in [l['cx'] + d * 0.5 * s for d in range(0, steps + 1) for s in ([1] if d == 0 else [1, -1])]:
                if abs(cx - l['cx']) > mx + 0.01 or not col_ok(l, cx, mx):
                    continue
                _v2 = violations(en, box_of(l, cx, val, 0.0), ob)
                if not _v2:
                    return cx, 0.0
                if os.environ.get('DEBUG_LABEL') == en and 1188 <= cx <= 1200:
                    print('   single-try mx=%.0f cx=%.1f -> %s' % (mx, cx, _v2))
            return None

        def row_lift_mates(l):
            """The other labels of the same row (they travel with it).

            Returns None when some cell of the row has no illustration: then the
            row cannot be kept level, so the caller must not lift a single
            picture on its own.
            """
            rn = (l.get('facts') or {}).get('row')
            out = []
            for m in (pg.get('rows') or {}).get(rn, []):
                if m['en'] != l['en']:
                    out.append(m)       # cells without art just move their text
            return out

        def feasible_wrap(en, val):
            """Can a two-line block go here?

            Returns (cx, dy, illdy, rowlift, mates) or None.

              dy       lift applied to THIS label's text
              illdy    lift applied to THIS label's own illustration
              rowlift  lift applied to EVERY cell of the same row
              mates    labels that receive `rowlift` too

            Order: text first (it may rise into the gap above it), then the whole
            row together. A single picture is never lifted on its own -- that
            would leave the three pictures of one row at different heights.
            """
            l = [x for x in labels if x['en'] == en][0]
            H = h1_of(l) + lead
            ob = others_boxes(en)
            down = obstacles_below(l)
            rowdy = float(state.get(en, {}).get('rowdy') or 0.0)
            top0 = l['box'][1] + rowdy
            f = l.get('facts') or {}
            base_max = float(f.get('room') or 0.0)          # text-only clearance
            art_room, mates = 0.0, None
            if f.get('illok'):
                mates = row_lift_mates(l)
                if mates is not None:
                    caps = []
                    for m in [l] + mates:
                        c = (m.get('facts') or {}).get('ceil')
                        caps.append(0.0 if c is None else max(0.0, float(c) - rowdy))
                    art_room = min(caps) if caps else 0.0
            for cx in [l['cx'] + d * 0.5 * s for d in range(0, 17) for s in ([1] if d == 0 else [1, -1])]:
                if abs(cx - l['cx']) > DX_MAX + 0.01 or not col_ok(l, cx):
                    continue
                # least lift that clears the bottom; a two-line block always
                # grows DOWNWARD from the source line, so a negative value just
                # means "no lift needed" -- applying it would drag the block
                # down onto the row below (it did: dy=-38.7 on a top-row label)
                # wrap_clear_pt: the cushion between the wrapped block and
                # whatever is below. MM (2 mm) is the general obstacle cushion
                # and is far stricter than the artwork itself -- the source
                # labels often sit 1-2 pt from the frame, so a two-line block
                # "needed" 3-6 pt of lift that nothing could give and the label
                # stayed long, crossing the card edge and its illustration.
                dy_min = max(0.0, down + float(P.get('wrap_clear_pt', 1.0)) - top0 + H)
                dy_max = base_max + art_room
                if dy_min > dy_max + 0.01:
                    if os.environ.get('DEBUG_LABEL') == en:
                        print('   wrap-noroom: dy_min=%.1f base_max=%.1f art_room=%.1f'
                              % (dy_min, base_max, art_room))
                    continue
                _ill = max(0.0, round(dy_min - base_max, 1))
                if _ill > 0.01 and (mates is None or _ill > art_room + 0.01):
                    continue
                for cand in (dy_min,):
                    _v = violations(en, box_of(l, cx, val, cand), ob)
                    if not _v:
                        _self = _ill if f.get('ill') else 0.0
                        return (cx, round(cand, 1), _self, _ill,
                                [m['en'] for m in (mates or [])] if _ill > 0.01 else [])
                    if os.environ.get('DEBUG_LABEL') == en:
                        print('   wrap-try cx=%.1f dy=%.1f top=%.1f h=%.1f -> %s'
                              % (cx, cand, top0, H, _v))
            if os.environ.get('DEBUG_LABEL') == en:
                print('   wrap-impossible: dy_min=%.1f base_max=%.1f art_room=%.1f down=%.1f'
                      % (dy_min, base_max, art_room, down))
            return None

        for _ in range(10):
            changed = False
            order = sorted(state.keys(), key=lambda e: -line_w(state[e]['val']))
            for en in order:
                l = [x for x in labels if x['en'] == en][0]
                st = state[en]
                ob = others_boxes(en)
                _vv = violations(en, box_of(l, st['cx'], st['val'], st['dy']), ob)
                if os.environ.get('DEBUG_LABEL') == en:
                    print('   [%s] %r w=%.1f cx=%.1f dy=%.1f -> %s'
                          % (st['mode'], st['val'].replace('\r', '|'),
                             line_w(st['val']), st['cx'], st['dy'], _vv or 'ok'))
                if not _vv:
                    if st['mode'] == 'manual':
                        st['mode'] = 'keep'
                    continue
                # A value whose line break came FROM THE TABLE is a request,
                # not a suggestion: keep the break and re-centre the block.
                # Flattening it made a hand-set two-line label ("cadeira de\
                # rodas", written because the single line overruns its column)
                # come back as one 148pt line that then had to be shifted until
                # it nearly touched its neighbour. Solved values (wrap/short)
                # still go through the normal ladder below.
                cand_val = st['val'] if '\r' in st['val'] else st['val'].replace('\r', ' ')
                got = try_single(en, cand_val)
                if got:
                    st.update(val=cand_val, cx=got[0], dy=got[1], mode='single'); changed = True; continue
                # 2) a bigger INWARD shift, still inside the label's own column.
                #    This is the sanctioned answer to "the word runs into the card
                #    edge / the page number": move it, do not change the word and
                #    do not break it in two. It used to sit AFTER the short form,
                #    so 'cadeira de rodas' was shortened to the wrong word
                #    ('cadeira' = chair) when a 12pt inward shift was enough.
                got = try_single(en, cand_val, RELAX_DX)
                if got:
                    st.update(val=cand_val, cx=got[0], dy=got[1], mode='shift2'); changed = True; continue
                # WRAP BEFORE SHORT: a two-line label that fits the card is
                # always preferred to a different (shorter) word. The old order
                # had it the other way round, which is why bottom-row labels were
                # shortened even when a two-line block was perfectly legal.
                if ' ' in cand_val:
                    got = feasible_wrap(en, wrap2(cand_val))
                    if got:
                        st.update(val=wrap2(cand_val), cx=got[0], dy=got[1],
                                  illdy=got[2], mode='wrap')
                        for _m in got[4]:
                            state[_m]['rowdy'] = round(
                                float(state[_m].get('rowdy') or 0.0) + got[3], 1)
                        changed = True; continue
                sv = SHORT.get(lang, {}).get(en)
                if sv:
                    got = try_single(en, sv)
                    if got:
                        st.update(val=sv, cx=got[0], dy=got[1], mode='short')
                        SHORT_USED.setdefault(str(ab), {})[en] = sv; changed = True; continue
                if sv:
                    got = try_single(en, sv, RELAX_DX)
                    if got:
                        st.update(val=sv, cx=got[0], dy=got[1], mode='short')
                        SHORT_USED.setdefault(str(ab), {})[en] = sv; changed = True; continue
                fsz = SIZEFIX.get((lang, en))
                if fsz:
                    l = [x for x in labels if x['en'] == en][0]
                    k = fsz / BASE_SIZE
                    w = line_w(cand_val) * k
                    h = h1_of(l) * k
                    ob = others_boxes(en)
                    hit = None
                    for d in range(0, 2 * int(RELAX_DX / 0.5) + 1):
                        for s in ([1] if d == 0 else [1, -1]):
                            cx = l['cx'] + d * 0.5 * s
                            if abs(cx - l['cx']) > RELAX_DX + 0.01 or not col_ok(l, cx, RELAX_DX):
                                continue
                            top = l['box'][1]
                            if not violations(en, [cx - w / 2, top, cx + w / 2, top - h], ob):
                                hit = cx; break
                        if hit is not None:
                            break
                    if hit is not None:
                        st.update(val=cand_val, cx=hit, dy=0.0, mode='fit', sz=fsz); changed = True; continue
                st['mode'] = 'manual'
                if 'AB%d %s' % (ab, en) not in PENDING:
                    PENDING.append('AB%d %s' % (ab, en))
                changed = True
            if not changed:
                break

        # row packing + row alignment (same as v7: keep rows visually level)
        rows = []
        for l in labels:
            for r in rows:
                if abs(l['cy'] - r[0]) <= 20:
                    r[1].append(l); break
            else:
                rows.append([l['cy'], [l]])

        def pack_row(mem):
            mem = sorted(mem, key=lambda x: x['cx'])
            ws = [line_w(state[x['en']]['val']) for x in mem]
            lo = [fx0 + w / 2 for w in ws]
            hi = [fx1 - w / 2 for w in ws]
            cx = [state[x['en']]['cx'] for x in mem]
            for _ in range(400):
                moved = False
                for i in range(len(mem) - 1):
                    gap = (cx[i + 1] - ws[i + 1] / 2) - (cx[i] + ws[i] / 2)
                    if gap < IGH - 0.01:
                        d = (IGH - gap) / 2 + 0.05
                        cx[i] -= d; cx[i + 1] += d; moved = True
                for i in range(len(mem)):
                    if cx[i] < lo[i]: cx[i] = lo[i]
                    if cx[i] > hi[i]: cx[i] = hi[i]
                if not moved:
                    break
            for i in range(len(mem)):
                if cx[i] < lo[i] - 0.01 or cx[i] > hi[i] + 0.01:
                    return None
                if i + 1 < len(mem) and (cx[i + 1] - ws[i + 1] / 2) - (cx[i] + ws[i] / 2) < IGH - 0.5:
                    return None
            return cx

        for _ry, mem in rows:
            if len(mem) < 2 or not any(state[x['en']]['mode'] == 'manual' for x in mem):
                continue
            mem = sorted(mem, key=lambda x: x['cx'])
            cc = pack_row(mem)
            if cc is None:
                continue
            mnames = set(x['en'] for x in mem)

            def ob_row(en):
                o = {}
                for oen, st2 in state.items():
                    if oen == en or oen in mnames:
                        continue
                    l2 = [y for y in labels if y['en'] == oen][0]
                    o[oen] = box_of(l2, st2['cx'], st2['val'], st2['dy'])
                return o

            ok = True
            for i, x in enumerate(mem):
                en = x['en']; st2 = state[en]
                if violations(en, box_of(x, cc[i], st2['val'], st2['dy']), ob_row(en)):
                    ok = False; break
            if not ok:
                continue
            for i, x in enumerate(mem):
                en = x['en']
                state[en]['cx'] = round(cc[i], 1)
                if state[en]['mode'] == 'manual':
                    state[en]['mode'] = 'row'

        for _ry, mem in rows:
            # A row that was deliberately placed (a wrapped label, or a row lift
            # that moved every cell) must not be re-"aligned" afterwards: the
            # align pass rewrites dy for the whole row, which would undo both the
            # wrap offset and the lift (it did: text ended 23pt above its art).
            if any(state[x['en']].get('mode') == 'wrap' or state[x['en']].get('rowdy')
                   for x in mem):
                continue
            live = [x for x in mem if state[x['en']]['mode'] != 'manual']
            if len(live) < 2:
                continue
            singles = [x for x in live if '\r' not in state[x['en']]['val']]
            pool = singles if singles else live
            tops = sorted(x['box'][1] for x in pool)
            ref = tops[len(tops) // 2]
            base = dict((x['en'], ref - x['box'][1]) for x in mem)
            mnames = set(x['en'] for x in mem)
            prev = dict((x['en'], state[x['en']]['dy']) for x in mem)

            def ob_out(en):
                o = {}
                for oen, st2 in state.items():
                    if oen == en or oen in mnames:
                        continue
                    l2 = [y for y in labels if y['en'] == oen][0]
                    o[oen] = box_of(l2, st2['cx'], st2['val'], st2['dy'])
                return o

            obs = dict((x['en'], ob_out(x['en'])) for x in mem)
            pick = None
            for k in [0.0] + [float(s * v) for v in range(1, 21) for s in (-1, 1)]:
                ok = True
                for x in live:
                    st2 = state[x['en']]
                    if violations(x['en'], box_of(x, st2['cx'], st2['val'], base[x['en']] + k), obs[x['en']]):
                        ok = False; break
                if ok:
                    pick = k; break
            if pick is None:
                for x in mem:
                    state[x['en']]['dy'] = prev[x['en']]
            else:
                for x in mem:
                    state[x['en']]['dy'] = round(base[x['en']] + pick, 1)

        # ---- page-number no-go zone (horizontal) -------------------------
        # Keep every label on the page-number's row at least PN_GAP clear of
        # it by nudging the text left, capped by PN_SHIFT_CAP and by the room
        # to the left neighbour. Text stays centred under its own art; only a
        # few pt ever move, which is invisible on a 470pt card. If a label is
        # simply too long to clear the number, it is reported (PN-TIGHT) so
        # the translator shortens the word instead of shipping an overlap.
        pn = pg.get('pageno')
        if pn:
            pB = [min(pn['box'][0], pn['box'][2]),
                  max(pn['box'][1], pn['box'][3]),
                  min(pn['box'][1], pn['box'][3])]
            pL, pTop, pBot = pB
            _order = sorted(state.items(),
                            key=lambda kv: kv[1]['cx'])
            _done = []                      # (right_edge, left_edge) shifted already
            for en, st in _order:
                if st.get('mode') == 'manual':
                    continue
                lo = [x for x in labels if x['en'] == en]
                if not lo:
                    continue
                lo = lo[0]
                k = (st.get('sz') or BASE_SIZE) / BASE_SIZE
                w = line_w(st['val']) * k
                h = h1_of(lo) + (lead if '\r' in st['val'] else 0.0)
                top = lo['box'][1] + st['dy'] + float(st.get('rowdy') or 0.0)
                bot = top - h
                if not (top > pBot and bot < pTop):     # not on the number's row
                    continue
                L, R = st['cx'] - w / 2, st['cx'] + w / 2
                need = R - (pL - PN_GAP)
                if need <= 0.2:        # already clear (sub-0.2pt = rounding)
                    continue
                room = PN_SHIFT_CAP
                for (nr, _nl) in _done:                 # left neighbour already moved
                    if nr <= L + 0.5:
                        room = min(room, L - (nr + MM))
                shift = min(need, room)
                if shift < need - 0.1:
                    print('PN-TIGHT %s/%s ab%d %r need=%.1f only=%.1f '
                          '(left neighbour limits the nudge)' % (lang, color, ab, st['val'], need, shift))
                if shift <= 0.05:
                    print('PN-TIGHT %s/%s ab%d %r right=%.1f limit=%.1f '
                          '(too long to clear the page number)'
                          % (lang, color, ab, st['val'], R, pL - PN_GAP))
                    continue
                st['cx'] = round(st['cx'] - shift, 1)
                st['pnfix'] = 1
                print('PN-SHIFT %s/%s ab%d %r dx=-%.1f' % (lang, color, ab, st['val'], shift))
                _done.append((st['cx'] + w / 2, st['cx'] - w / 2))

        dec = {}
        for en, st in state.items():
            if os.environ.get('DEBUG_LABEL') == en:
                print('   EMIT %s/%s %r mode=%s' % (lang, color, st['val'], st['mode']))
            _row = float(st.get('rowdy') or 0.0)
            d = {'val': st['val'], 'cx': round(st['cx'], 1),
                 'dy': round(st['dy'] + _row, 1), 'mode': st['mode']}
            # R4: reviewer hand-edit delta, keyed by "<ab>|<english key>"
            _pd = POS.get((lang, color, '%d|%s' % (ab, en)))
            if _pd:
                d['cx'] = round(d['cx'] + float(_pd.get('dx', 0)), 1)
                d['dy'] = round(d['dy'] + float(_pd.get('dy', 0)), 1)
                d['posfix'] = 1
            if st.get('sz'):
                d['sz'] = st['sz']
            if st.get('pnfix'):
                d['pnfix'] = 1
            _ill = float(st.get('illdy') or 0.0) + _row
            if abs(_ill) > 0.01:
                d['illdy'] = round(_ill, 1)
            if st.get('mode') == 'wrap':
                # authoritative: the decision layer proved a two-line block fits
                # the card; build_width_tables must not second-guess it by slot
                d['wrap'] = 1
                # mode=wrap MUST mean a two-line value. Twice now a value lost
                # its '\r' somewhere between the solve loop and this emit (a
                # 164pt single line then shipped and crossed the card edge).
                # Restore it here, loudly, instead of trusting the state.
                if '\r' not in st['val']:
                    _w = wrap2(str(st['val']).replace('\r', ' '))
                    if '\r' in _w:
                        d['val'] = _w
                        PENDING.append('%s: WRAP-VAL-RESTORED (mode=wrap, value had no line break)'
                                       % en.replace('\r', '|'))
            if en in ILLBOX:
                d['ill'] = ILLBOX[en]
                _m = ILLMETA.get(en) or {}
                d['room'] = _m.get('room', 0.0)
                d['illok'] = _m.get('illok', 0)
            if en in DUPPOS:
                # R3: emit one decision per occurrence, ordered by x so make_jsx
                # can hand frame #i its own value/centre. The base key stays as a
                # fallback (first occurrence) for older JSX that ignores @N.
                xs = DUPPOS[en]
                for _i, _x in enumerate(xs, 1):
                    _k = '%s@%d' % (en, _i)
                    _v = tr(_k)
                    _rec = dict(d)
                    _rec['cx'] = round(_x, 1)
                    if _v != _k:                 # explicit "short@2" in the table
                        _rec['val'] = _v
                    _rec['dupidx'] = _i
                    _rec['dupof'] = en
                    dec[_k] = _rec
                dec[en] = dict(d)                # fallback
            else:
                dec[en] = d
        for _en, (_row, _val, _sz) in abbr_rows.items():
            # szsrc lets make_jsx tell the two frames apart by their own size
            dec[_en + '#abbr'] = {'val': _val, 'cx': round(_row['cx'], 1),
                                  'dy': 0.0, 'mode': 'keep', 'szsrc': round(_sz, 2)}
        DEC[str(ab)] = dec
        REPORT.append('AB%-2d labels=%d' % (ab, len(state)))

    # R2 vector (outlined) text: labels that exist in the source artwork only as
    # vector paths (no text layer), so export_spans never sees them. Config lists
    # their bbox; we attach THIS language's translation for make_jsx to place.
    VECTEXT = []
    for _vt in (cfg.d.get('vector_text', []) or []):
        if _vt.get('color') != color:
            continue
        _en = _vt['en']
        _val = tr(_en)
        if not _val or _val == _en:
            PENDING.append('VECTEXT-MISS %s/%s %s (add "%s" to translations)' % (lang, color, _en, _en))
            continue
        VECTEXT.append({'page': int(_vt['page']), 'en': _en, 'val': _val,
                        'box': _vt['box'], 'size': float(_vt.get('size', 18.0)),
                        'bg': _vt.get('bg', [])})

    out = {'dec': DEC, 'title_map': title_map, 'titles': TITLES,
           'lead': lead, 'size': BASE_SIZE, 'short': SHORT_USED, 'pending': PENDING,
           'vectext': VECTEXT}
    path = cfg.decision_path(lang, color)
    json.dump(out, open(path, 'w', encoding='utf-8'), ensure_ascii=False)
    # read the file back and enforce the invariant on what will actually ship
    _chk = json.load(open(path, encoding='utf-8'))
    _bad = [en for ab, it in _chk['dec'].items() for en, r in it.items()
            if r.get('mode') == 'wrap' and '\r' not in str(r.get('val', ''))]
    if _bad:
        raise SystemExit('REFUSED %s/%s: mode=wrap without a line break in %s'
                         % (lang, color, _bad[:5]))
    ncx = sum(1 for a in DEC.values() for r in a.values() if r.get('cx') is not None)
    tot = sum(len(a) for a in DEC.values())
    print('\n'.join(REPORT))
    print('WROTE %s  entries=%d with_cx=%d' % (os.path.basename(path), tot, ncx))
    return tot, ncx


args = [a for a in sys.argv[1:] if not a.startswith('--')]
if not args:
    raise SystemExit(__doc__)
sel = []
for a in args:
    if a == 'all':
        for l in cfg.langs:
            for c in cfg.colors:
                sel.append((l['code'], c['code']))
    elif a in cfg.L:
        for c in cfg.colors:
            sel.append((a, c['code']))
    elif a in cfg.C:
        for l in cfg.langs:
            sel.append((l['code'], a))
    elif '_' in a:
        l, c = a.split('_', 1)
        if l in cfg.L and c in cfg.C:
            sel.append((l, c))
seen = set()
for lang, color in sel:
    if (lang, color) in seen:
        continue
    seen.add((lang, color))
    solve_book(lang, color)
