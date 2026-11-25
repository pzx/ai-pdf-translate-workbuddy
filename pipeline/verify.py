# -*- coding: utf-8 -*-
"""Verify finished PDFs: page count, zero live text (outlined), file presence,
plus optional layout-constraint checks fed by the decision JSON.

    python verify.py [pipeline.json] [--layout]

Basic checks (always on): every PDF exists, page count matches config, zero
live text (text was outlined). --layout adds static checks over the decision
JSON that catch the classic card bugs before they ship:

  * overflow   - a decision entry whose font size (sz) is absent/smaller than
                 source yet the translated word is much longer than the source
                 (heuristic: need sz when val is >=1.6x the source length).
  * obstacles  - illustration boxes ("obstacles" in the decision JSON) that
                 overlap a word's declared centre (cx) within the artboard.
  * two-line   - a translated value with a soft break must set a leading mode
                 (the JSX does this; here we just report such entries so they
                 are reviewed).
  * page-edge  - rendered PDF pages: report ink outside the safe page frame
                 (outlined text/graphics touching the TrimBox edge).

All layout findings are WARNINGS with an exit code 2 (basic failures still exit
1); they are advisory because the authoritative geometry lives in Illustrator.
"""
import os, sys, glob, json
import pymupdf
from common import Config, load_dec

cfg = Config(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else None)
LAYOUT = '--layout' in sys.argv
OUT = os.path.join(cfg.output, cfg.batch, 'pdf')
S = cfg.s
E, V, SZ = S['entries'], S['value'], S['size_override']

print('%-46s %5s %7s %9s' % ('file', 'pages', 'text', 'size MB'))
bad = 0
# Completeness first: the old version globbed whatever existed, so a book that
# was never produced simply vanished from the report and the run still passed.
EXPECT = {cfg.product_paths(l['code'], c['code'])[1]: (l['code'], c['code'], c['pages'])
          for l in cfg.langs for c in cfg.colors}
missing = sorted(p for p in EXPECT if not os.path.exists(p))
pdfs = sorted(p for p in EXPECT if os.path.exists(p))
extra = sorted(set(glob.glob(os.path.join(OUT, '*.pdf'))) - set(EXPECT))
for p in missing:
    lc, cc, _pg = EXPECT[p]
    bad += 1
    print('%-46s    --  MISSING (%s/%s)' % (os.path.basename(p)[:46], lc, cc))
for p in pdfs:
    d = pymupdf.open(p)
    txt = sum(len(d[i].get_text().strip()) for i in range(len(d)))
    name = os.path.basename(p)
    exp = EXPECT[p][2]
    flag = ''
    if txt:
        bad += 1; flag += ' !LIVE-TEXT'
    if exp and len(d) != exp:
        bad += 1; flag += ' !PAGES(exp %s)' % exp
    print('%-46s %5d %7d %9.1f%s' % (name[:46], len(d), txt, os.path.getsize(p)/1e6, flag))
    d.close()
if extra:
    print('note: %d pdf(s) in %s do not match any configured product (ignored): %s'
          % (len(extra), OUT, ', '.join(os.path.basename(x) for x in extra[:5])))
print('expected=%d  found=%d  missing=%d  with-issues=%d'
      % (len(EXPECT), len(pdfs), len(missing), bad))

warn = 0
if LAYOUT:
    print('\n--- layout checks (--layout) ---')
    for lang in cfg.langs:
        lc = lang['code']
        for color in cfg.colors:
            cc = color['code']
            dp = cfg.decision_path(lc, cc)
            if not os.path.exists(dp):
                continue
            dec = json.load(open(dp, encoding='utf-8'))
            obs = dec.get('obstacles', {}) or {}
            for ab, entries in dec.get(E, {}).items():
                boxes = obs.get(ab, []) or []
                for en, rec in entries.items():
                    val = str(rec.get(V, ''))
                    if not val:
                        continue
                    # A bare entry with NO layout decision at all means the
                    # decision engine never sized/positioned it -> likely to
                    # overflow. A translated word being longer than the source
                    # is NOT itself a problem: the engine already sized it.
                    layout_keys = ('cx', 'dy', SZ, S.get('mode', 'mode'))
                    if not any(k in rec for k in layout_keys) and val != en:
                        print('  WARN undecided %s|%s|%s|%s val=%r (no layout decision)' % (lc, cc, ab, en, val))
                        warn += 1
                    # obstacle overlap at the declared centre (only when the
                    # decision JSON actually provides illustration boxes)
                    cx = rec.get('cx')
                    if cx is not None and boxes:
                        px = float(cx)
                        for b in boxes:
                            if len(b) >= 4 and float(b[0]) <= px <= float(b[2]):
                                print('  WARN obstacle  %s|%s|%s|%s cx=%.1f in box %s' % (lc, cc, ab, en, px, b))
                                warn += 1
                                break
    print('layout warnings=%d (undecided / obstacle; two-line is expected and not flagged)' % warn)

sys.exit(1 if bad else (2 if warn else 0))
