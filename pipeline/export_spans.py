# -*- coding: utf-8 -*-
r"""Export source text spans -> <work>/<files.spans> (+ unique_strings.json).

    python export_spans.py [pipeline.json] [--color purple]

Why this is a pipeline step, not a helper script
------------------------------------------------
Everything downstream reads the source artwork's OWN text metrics:
  * build_width_tables.py  -> every word's slot width / wrap decision
  * make_jsx.py            -> the per-title font size (measured, never assumed)
  * letters_export.py      -> which word illustrates each letter
  * ledger order           -> reading order on the page
Without this file a "clean rebuild" cannot start. It used to live in the
project as a one-off script, so a fresh project silently fell back to a
hard-coded 22pt title and English-looking output. Now it is part of the chain:

    export_spans.py -> build_decisions.py -> build_width_tables.py -> ...

Output format (consumed by common.py):
    { "<color>": [ {"page":1-based, "text":str, "bbox":[x0,y0,x1,y1],
                    "size":pt, "font":str, "color":int}, ... ] }
Soft line breaks are normalised to "\r" (the same escape the JSX uses).
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Config

args = [a for a in sys.argv[1:] if not a.startswith('--')]
cfg = Config(args[0] if args else None)
only = None
if '--color' in sys.argv:
    only = sys.argv[sys.argv.index('--color') + 1]

colors = [c for c in cfg.colors if only in (None, c['code'])]
if not colors:
    raise SystemExit('no such colour: %s' % only)

try:
    import pymupdf
except ImportError:
    raise SystemExit('pymupdf is required: pip install pymupdf')

out_path = os.path.join(cfg.work, cfg.f.get('spans', 'spans_all.json'))
uniq_path = os.path.join(cfg.work, 'unique_strings.json')
os.makedirs(cfg.work, exist_ok=True)

spans_all, uniq = {}, {}
for c in colors:
    color = c['code']
    path = cfg.source_path(color)
    if not path or not os.path.exists(path):
        raise SystemExit('source artwork not found for %s: %s' % (color, path))
    doc = pymupdf.open(path)
    items = []
    for pno in range(len(doc)):
        for b in doc[pno].get_text('dict')['blocks']:
            if b['type'] != 0:                 # 0 = text block
                continue
            for line in b['lines']:
                for s in line['spans']:
                    t = (s['text'] or '').replace('\n', '\r')
                    if not t.strip():
                        continue
                    items.append({'page': pno + 1,
                                  'text': t,
                                  'bbox': [round(v, 3) for v in s['bbox']],
                                  'size': round(float(s['size']), 3),
                                  'font': s['font'],
                                  'color': s['color']})
                    if not t.strip().isdigit():
                        uniq.setdefault(t, []).append((color, pno + 1))
    spans_all[color] = items
    print('%-7s pages=%d spans=%d' % (color, len(doc), len(items)))
    doc.close()

# merge with colours that were not re-exported (so --color does not wipe them)
if os.path.exists(out_path):
    try:
        old = json.load(open(out_path, encoding='utf-8'))
        for k, v in old.items():
            spans_all.setdefault(k, v)
    except Exception:
        pass

json.dump(spans_all, open(out_path, 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
json.dump({k: v for k, v in sorted(uniq.items())},
          open(uniq_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('WROTE %s | colours=%d | unique strings=%d'
      % (os.path.basename(out_path), len(spans_all), len(uniq)))
