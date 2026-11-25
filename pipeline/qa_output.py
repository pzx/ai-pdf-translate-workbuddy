# -*- coding: utf-8 -*-
"""qa_output.py -- post-build QA on the shipped files themselves.

Everything up to here trusts a model of the layout. This step trusts nothing:
it opens the finished .ai/.pdf and reads the real glyph coordinates, so a
defect introduced anywhere in the chain (decision -> JSX -> Illustrator) still
gets caught. It is the only check that would have caught a word landing on the
corner page number, because that number is drawn by the template, not by us.

Checks per page
  PAGENO  a text run sits closer than --min pt to the page number  (overprint)
  BLEED   a text run reaches outside the page box                  (cut off)
  COUNT   page count differs from config.colors[].pages

Usage
  PIPELINE_CONFIG=... python qa_output.py                 # every product
  PIPELINE_CONFIG=... python qa_output.py --lang it       # one language
  PIPELINE_CONFIG=... python qa_output.py --files a.ai b.pdf --min 10
"""
import os
import sys
import glob
import statistics

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import pymupdf
except ImportError:                                   # pragma: no cover
    raise SystemExit('need pymupdf:  pip install pymupdf')

argv = sys.argv[1:]
MIN = 10.0
if '--min' in argv:
    MIN = float(argv[argv.index('--min') + 1])
lang_only = argv[argv.index('--lang') + 1] if '--lang' in argv else None
files = []
if '--files' in argv:
    i = argv.index('--files') + 1
    while i < len(argv) and not argv[i].startswith('--'):
        files.append(argv[i]); i += 1
explicit = bool(files)

EXPECT = {}
if not explicit:
    from common import Config
    cfg = Config(None)
    # Map by EXACT product name, not by a colour-name substring: two colours can
    # share a substring, and a product template that omits the colour name would
    # silently never be page-checked.
    for l in cfg.langs:
        for c in cfg.colors:
            ai_p, pdf_p = cfg.product_paths(l['code'], c['code'])
            EXPECT[os.path.basename(ai_p)] = c['pages']
            EXPECT[os.path.basename(pdf_p)] = c['pages']
    for f in sorted(glob.glob(os.path.join(cfg.output, '*', 'ai', '*.ai')) +
                    glob.glob(os.path.join(cfg.output, '*', 'pdf', '*.pdf'))):
        if lang_only and lang_only not in os.path.basename(f):
            continue
        files.append(f)


def pageno_spans(spans):
    """A page number is a short digit run set much smaller than the body text.
    Relying on a fixed 12pt would break every template whose numbering differs,
    and a calendar's big "01..12" would be mistaken for it."""
    digits = [s for s in spans if s[0].isdigit() and len(s[0]) <= 3]
    if not digits:
        return []
    body = statistics.median([s[2] for s in spans]) or 1.0
    small = [s for s in digits if s[2] <= 0.8 * body]
    return small or []


def title_rows(page):
    """Geometry of a pill title, read from VECTOR PATHS.

    Everything above this line assumes live text, and a finished .ai is fully
    outlined -- get_text() returns nothing, so every page was skipped and the
    post-build gate passed vacuously. The pill and its glyphs are still vector
    drawings, so this works on the shipped file.

    Returns (pill_rect, [row_bbox, ...]) or None when the page has no pill
    (other layouts are simply not checked here).
    """
    pill = None
    for dr in page.get_drawings():
        r = dr['rect']
        if 100 < r.width < 145 and 26 < r.height < 46 and r.y1 < 80:
            if pill is None or r.width * r.height > pill.width * pill.height:
                pill = r
    if pill is None:
        return None
    glyphs = []
    for dr in page.get_drawings():
        f = dr.get('fill')
        if not f or len(f) < 3:
            continue
        if min(f[0], f[1], f[2]) < 0.85:            # white glyphs on a dark pill
            continue
        r = dr['rect']
        if r.width <= 0.2 or r.height <= 0.2:
            continue
        if (r.x0 >= pill.x0 - 2 and r.x1 <= pill.x1 + 2
                and r.y0 >= pill.y0 - 3 and r.y1 <= pill.y1 + 3):
            glyphs.append(r)
    if not glyphs:
        return None
    glyphs.sort(key=lambda r: (r.y0 + r.y1) / 2)
    med_h = statistics.median([r.height for r in glyphs]) or 1.0
    rows, cur = [], [glyphs[0]]
    for r in glyphs[1:]:
        if (r.y0 + r.y1) / 2 - (cur[-1].y0 + cur[-1].y1) / 2 > 0.5 * med_h:
            rows.append(cur); cur = [r]
        else:
            cur.append(r)
    rows.append(cur)
    out_rows = []
    for row in rows:
        box = pymupdf.Rect(min(r.x0 for r in row), min(r.y0 for r in row),
                           max(r.x1 for r in row), max(r.y1 for r in row))
        # Baseline = the most common glyph bottom. A descender ("q" in
        # quotidiane, "g" in Stagioni) hangs below it and the generator is
        # allowed to let it hang, so it must not count as overflow.
        bottoms = sorted(r.y1 for r in row)
        base = bottoms[len(bottoms) // 2]
        out_rows.append((box, base))
    return pill, out_rows


def title_issues(page, pno):
    """A two-line title is a BLOCK: it must be centred on the pill, and each
    line has to stay inside the oval at ITS OWN height. Both were broken at
    once -- the block hung 13pt low because only the first line's cap band was
    centred, and growing it back to the artwork's size poked the ends out."""
    got = title_rows(page)
    if not got:
        return []
    pill, rows = got
    out = []
    cx, cy = (pill.x0 + pill.x1) / 2, (pill.y0 + pill.y1) / 2
    a, b = (pill.x1 - pill.x0) / 2, (pill.y1 - pill.y0) / 2
    if len(rows) >= 2:
        top, bot = rows[0][0].y0, rows[-1][0].y1
        off = (top + bot) / 2 - cy
        if abs(off) > 1.0:
            out.append(('TITLE-CENTER', pno, '%.1fpt off' % off))
    for i, (r, base) in enumerate(rows):
        worst = 0.0
        for px in (r.x0, r.x1):
            for py in (r.y0, base):             # cap band, descender excluded
                worst = max(worst, ((px - cx) / a) ** 2 + ((py - cy) / b) ** 2)
        if worst > 1.02:
            out.append(('TITLE-POUT', pno, 'row%d %.2f of the oval' % (i + 1, worst)))
        elif worst > 0.96 and len(rows) >= 2:
            # Inside the oval but with no margin: a two-line block that merely
            # touches the curve is what "looks like it is about to spill"
            # reads as. The generator aims at title_two_fill (0.90) for
            # multi-line blocks; anything this close means a hand-edited
            # decision or a differently shaped pill. Single-line titles are
            # deliberately allowed right up to the boundary, so they are not
            # reported here.
            out.append(('TITLE-TIGHT', pno, 'row%d %.2f of the oval' % (i + 1, worst)))
    return out


bad = 0
warns = []
checked = 0
for f in files:
    doc = pymupdf.open(f)
    hits = []
    for pno in range(len(doc)):
        page = doc[pno]
        spans = []
        for b in page.get_text('dict')['blocks']:
            for l in b.get('lines', []):
                for s in l['spans']:
                    t = s['text'].strip()
                    if t:
                        spans.append((t, s['bbox'], s['size']))
        # Vector-path checks first: an outlined page has no text at all, and
        # `continue`-ing on that is what made this step silently toothless.
        for _k, _p, _v in title_issues(page, pno + 1):
            if _k == 'TITLE-TIGHT':
                warns.append((os.path.basename(f), _p, _v)); continue
            hits.append((_k, _p, _v, '', ''))
        if not spans:
            continue                                # fully outlined page
        W, H = page.rect.width, page.rect.height
        for t, bb, sz in spans:
            if bb[0] < -0.5 or bb[2] > W + 0.5 or bb[1] < -0.5 or bb[3] > H + 0.5:
                hits.append(('BLEED', pno + 1, t[:22], round(bb[0], 1), round(W - bb[2], 1)))
        pn = pageno_spans(spans)
        for t, bb, sz in spans:
            if t.isdigit() and len(t) <= 3 and (t, bb, sz) in pn:
                continue
            for nt, nb, nsz in pn:
                if bb[3] < nb[1] - 2 or bb[1] > nb[3] + 2:
                    continue                        # different row
                if bb[0] > nb[2]:
                    continue                        # to the right of it
                gap = nb[0] - bb[2]
                if gap < MIN:
                    hits.append(('PAGENO', pno + 1, t[:22], round(gap, 1), nt))
    base = os.path.basename(f)
    exp = EXPECT.get(base)
    cnt_bad = exp is not None and len(doc) != exp
    checked += 1
    bad += len(hits) + (1 if cnt_bad else 0)
    print('%s %-56s pages=%d%s' % ('BAD' if (hits or cnt_bad) else 'OK ', base[:56],
                                   len(doc), '' if exp is None else ' (expected %d)' % exp))
    for h in hits[:12]:
        print('      %-7s p%-3d %-22s %s' % (h[0], h[1], h[2], h[3:]))
    if len(hits) > 12:
        print('      ... %d more' % (len(hits) - 12))

if warns:
    print('\n%d title(s) inside the pill but with no margin left '
          '(aim for title_two_fill):' % len(warns))
    for w in warns[:10]:
        print('      %-40s p%-3d %s' % (w[0][:40], w[1], w[2]))
print('\n%d file(s) checked, %d problem(s) (page-number clearance %.1fpt)'
      % (checked, bad, MIN))
sys.exit(1 if bad else 0)
