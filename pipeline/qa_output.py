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
    for f in sorted(glob.glob(os.path.join(cfg.output, '*', 'ai', '*.ai')) +
                    glob.glob(os.path.join(cfg.output, '*', 'pdf', '*.pdf'))):
        if lang_only and lang_only not in os.path.basename(f):
            continue
        files.append(f)
    for c in cfg.colors:
        EXPECT[c['name']] = c['pages']


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


bad = 0
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
    exp = None
    for name, pages in EXPECT.items():
        if name in base:
            exp = pages
    cnt_bad = exp is not None and len(doc) != exp
    checked += 1
    bad += len(hits) + (1 if cnt_bad else 0)
    print('%s %-56s pages=%d%s' % ('BAD' if (hits or cnt_bad) else 'OK ', base[:56],
                                   len(doc), '' if exp is None else ' (expected %d)' % exp))
    for h in hits[:12]:
        print('      %-7s p%-3d %-22s %s' % (h[0], h[1], h[2], h[3:]))
    if len(hits) > 12:
        print('      ... %d more' % (len(hits) - 12))

print('\n%d file(s) checked, %d problem(s) (page-number clearance %.1fpt)'
      % (checked, bad, MIN))
sys.exit(1 if bad else 0)
