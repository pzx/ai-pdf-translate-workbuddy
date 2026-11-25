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
FILL = 1.0        # geometry.title_two_fill, read from the config below
lang_only = argv[argv.index('--lang') + 1] if '--lang' in argv else None
files = []
if '--files' in argv:
    i = argv.index('--files') + 1
    while i < len(argv) and not argv[i].startswith('--'):
        files.append(argv[i]); i += 1
if '--files' in argv and not files:
    sys.exit('--files given without a path')
explicit = bool(files)

EXPECT = {}
# Pill-title probing. These describe the ARTWORK, not this book: a different
# deck has a different pill, and the gate must be told where to look instead of
# silently finding nothing (which is how it passed vacuously before). Overridden
# by layout.title_pill_w_range / _h_range / title_top_pt / title_glyph.
PILL_W = (100.0, 145.0)      # pill width range, pt
PILL_H = (26.0, 46.0)        # pill height range, pt
PILL_TOP = 80.0              # the pill sits in the top band of the page
POUT = 1.02                  # a corner this far outside the oval = real overflow
CTOL = 1.0                   # block centre vs pill centre, pt
GLYPH = 'light'              # 'light' = white glyphs on a dark pill
if not explicit:
    from common import Config
    cfg = Config(None)
    FILL = float(cfg.d.get('geometry', {}).get('title_two_fill', 1.0))
    _L = cfg.d.get('layout', {}) or {}
    PILL_W = tuple(_L.get('title_pill_w_range', PILL_W))
    PILL_H = tuple(_L.get('title_pill_h_range', PILL_H))
    PILL_TOP = float(_L.get('title_top_pt', PILL_TOP))
    POUT = float(_L.get('title_pout', POUT))
    CTOL = float(_L.get('title_center_tol_pt', CTOL))
    GLYPH = _L.get('title_glyph', GLYPH)
    # Map by EXACT product name, not by a colour-name substring: two colours can
    # share a substring, and a product template that omits the colour name would
    # silently never be page-checked.
    for l in cfg.langs:
        for c in cfg.colors:
            ai_p, pdf_p = cfg.product_paths(l['code'], c['code'])
            EXPECT[os.path.basename(ai_p)] = c['pages']
            EXPECT[os.path.basename(pdf_p)] = c['pages']
    # --lang accepts the config code (it) as well as the product label (意大利语).
    # Matching on the filename only meant `--lang it` silently checked ZERO files
    # and still printed "0 problem(s)".
    _match = [lang_only] if lang_only else []
    if lang_only in cfg.L:
        _match.append(cfg.L[lang_only]['name'])
    for f in sorted(glob.glob(os.path.join(cfg.output, '*', 'ai', '*.ai')) +
                    glob.glob(os.path.join(cfg.output, '*', 'pdf', '*.pdf'))):
        if _match and not any(m in os.path.basename(f) for m in _match):
            continue
        files.append(f)
    if not files:
        sys.exit('no product matched --lang %r / output %s' % (lang_only, cfg.output))


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


def _text_rows(page, pill):
    """Rows of a LIVE title (an .ai is editable artwork, so its title is a TEXT
    FRAME and there is not a single glyph path inside the pill -- the vector
    probe alone reported every .ai page as unreadable). Each span's baseline
    origin is the baseline, so descenders do not inflate the cap band."""
    got = []
    for b in page.get_text('dict')['blocks']:
        for l in b.get('lines', []):
            for s in l['spans']:
                if not s['text'].strip():
                    continue
                r = pymupdf.Rect(s['bbox'])
                if (r.x0 >= pill.x0 - 2 and r.x1 <= pill.x1 + 2
                        and r.y0 >= pill.y0 - 3 and r.y1 <= pill.y1 + 3):
                    got.append((r, s['origin'][1]))
    if not got:
        return []
    got.sort(key=lambda x: x[1])
    rows = [[got[0]]]
    for r, base in got[1:]:
        if abs(base - rows[-1][-1][1]) > 1.0:
            rows.append([(r, base)])
        else:
            rows[-1].append((r, base))
    out = []
    for row in rows:
        box = pymupdf.Rect(min(r.x0 for r, _ in row), min(r.y0 for r, _ in row),
                           max(r.x1 for r, _ in row), max(r.y1 for r, _ in row))
        out.append((box, statistics.median([b for _, b in row])))
    return out


def title_rows(page):
    """Geometry of a pill title, read from VECTOR PATHS.

    Everything above this line assumes live text, and a finished .ai is fully
    outlined -- get_text() returns nothing, so every page was skipped and the
    post-build gate passed vacuously. The pill and its glyphs are still vector
    drawings, so this works on the shipped file.

    Returns (pill_rect, [row_bbox, ...], kind) or None when the page has no pill
    at all (other layouts are simply not checked here). kind is 'path' for the
    shipped (outlined) artwork and 'text' when the title is still live -- an .ai
    is editable, so its title is a text frame and the row boxes are SPAN boxes,
    which include the font's side bearings and ascent/descent. Those are fine
    for the block centre but too fat to judge the oval corner by corner.
    A pill with no rows at all means the probe found nothing to read.
    """
    pill = None
    for dr in page.get_drawings():
        r = dr['rect']
        if (PILL_W[0] < r.width < PILL_W[1] and PILL_H[0] < r.height < PILL_H[1]
                and r.y1 < PILL_TOP):
            if pill is None or r.width * r.height > pill.width * pill.height:
                pill = r
    if pill is None:
        return None
    glyphs = []
    for dr in page.get_drawings():
        f = dr.get('fill')
        if not f or len(f) < 3:
            continue
        mn = min(f[0], f[1], f[2])
        if GLYPH == 'light' and mn < 0.85:          # white glyphs on a dark pill
            continue
        if GLYPH == 'dark' and mn > 0.45:           # dark glyphs on a light pill
            continue
        r = dr['rect']
        if r.width <= 0.2 or r.height <= 0.2:
            continue
        # The pill's own fill is a drawing inside the pill too; a path almost as
        # big as the pill is the background, not a glyph (in 'dark' mode it
        # would otherwise be read as one and report u=2.0 on every page).
        if r.width > pill.width * 0.9 and r.height > pill.height * 0.9:
            continue
        if (r.x0 >= pill.x0 - 2 and r.x1 <= pill.x1 + 2
                and r.y0 >= pill.y0 - 3 and r.y1 <= pill.y1 + 3):
            glyphs.append(r)
    if not glyphs:
        # No glyph paths: the title is still LIVE TEXT (editable .ai, or a PDF
        # that was never outlined). Read it there instead of calling the page
        # unchecked -- that is what the whole gate is supposed to prevent.
        return pill, _text_rows(page, pill), 'text'
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
    return pill, out_rows, 'path'


def title_issues(page, pno):
    """A two-line title is a BLOCK: it must be centred on the pill, and each
    line has to stay inside the oval at ITS OWN height. Both were broken at
    once -- the block hung 13pt low because only the first line's cap band was
    centred, and growing it back to the artwork's size poked the ends out."""
    got = title_rows(page)
    if not got:
        return []
    pill, rows, kind = got
    if not rows:
        # The pill is there but nothing inside it looked like a glyph path, so
        # this page was NOT checked. Reporting it as silence is what let the
        # whole gate pass vacuously when it was still reading live text.
        return [('TITLE-UNREAD', pno, 'no glyph paths')]
    out = []
    cx, cy = (pill.x0 + pill.x1) / 2, (pill.y0 + pill.y1) / 2
    a, b = (pill.x1 - pill.x0) / 2, (pill.y1 - pill.y0) / 2
    if len(rows) >= 2:
        top, bot = rows[0][0].y0, rows[-1][0].y1
        off = (top + bot) / 2 - cy
        # A live title's span box adds the font's ascent above the cap and its
        # descent below the last baseline, and the two are not symmetric
        # (measured 1.5pt on the pt-BR book even though the shipped PDF sits at
        # 0.0pt), so the tolerance is wider for text than for real glyph paths.
        tol = CTOL if kind == 'path' else CTOL * 2.5
        if abs(off) > tol:
            out.append(('TITLE-CENTER', pno, '%.1fpt off' % off))
    for i, (r, base) in enumerate(rows):
        if kind != 'path':
            # A span box carries the font's side bearings and its full ascent,
            # so its corners sit outside the ink by several points and would
            # report a false overflow on every live-title page. The shipped PDF
            # is judged on real glyph paths; here only the block centre counts.
            continue
        worst = 0.0
        for px in (r.x0, r.x1):
            for py in (r.y0, base):             # cap band, descender excluded
                worst = max(worst, ((px - cx) / a) ** 2 + ((py - cy) / b) ** 2)
        if worst > POUT:
            out.append(('TITLE-POUT', pno, 'row%d %.2f of the oval' % (i + 1, worst)))
        elif worst > FILL + 0.02 and len(rows) >= 2:
            # Inside the oval but past the margin the config asks for. With the
            # default title_two_fill = 1.0 this can never fire (1.0 + 0.02 is
            # already the TITLE-POUT ceiling) -- it only speaks when a project
            # has deliberately opted into a margin, in which case a block this
            # close means a hand-edited decision or a differently shaped pill.
            # Single-line titles are allowed right up to the boundary, so they
            # are never reported here.
            out.append(('TITLE-TIGHT', pno, 'row%d %.2f of the oval' % (i + 1, worst)))
    return out


if not files:
    sys.exit('no file to check (nothing matched the selector) -- refusing to '
             'report a clean pass on zero files')

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
    if any(h[0] == 'TITLE-UNREAD' for h in hits):
        print('      NOTE  a pill was found but no glyph path matched. The page was '
              'NOT checked:')
        print('            if the title is dark on a light pill set '
              'layout.title_glyph = "dark";'
              )
        print('            if the pill itself differs, tune layout.title_pill_w_range, '
              'title_pill_h_range, title_top_pt.')

if warns:
    print('\n%d title(s) inside the pill but past the configured margin '
          '(title_two_fill = %.2f):' % (len(warns), FILL))
    for w in warns[:10]:
        print('      %-40s p%-3d %s' % (w[0][:40], w[1], w[2]))
print('\n%d file(s) checked, %d problem(s) (page-number clearance %.1fpt)'
      % (checked, bad, MIN))
sys.exit(1 if bad else 0)
