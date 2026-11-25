# -*- coding: utf-8 -*-
"""Preflight: can this project be laid out at all?

Run it before build_decisions.py. It answers, per colour and per language, the
questions whose "no" used to surface only as silently-wrong output:

  * does every page have an inner card frame?      (no -> card edges unknown)
  * do labels have a matching illustration?        (no -> lift budgets are 0)
  * is the title census complete?                  (no -> pages keep English)
  * is the translation table covered?              (no -> English text ships)
  * did the last decision run leave labels stuck?  (mode=manual)

Exit code 0 = go, 2 = at least one hard blocker.

    python preflight.py               # all colours, all languages
    python preflight.py --color green # one colour
"""
import collections
import glob
import json
import os
import sys

from common import Config
from geomlib import GeomLib

HARD = []
SOFT = []


def _say(tag, msg):
    print('%-6s %s' % (tag, msg))


def check_geometry(cfg, g, color):
    pages = g.parse(color)
    if not pages:
        HARD.append('%s: no geometry TSV (%s)' % (color, g.geom_path(color)))
        return pages
    with_lab = {ab: pg for ab, pg in pages.items() if pg['labels']}
    no_frame = sorted(ab + 1 for ab, pg in with_lab.items() if not pg.get('frame_inner'))
    no_title = sorted(ab + 1 for ab, pg in pages.items() if not pg.get('title'))
    labs = [l for pg in with_lab.values() for l in pg['labels']]
    no_art = [l['en'] for l in labs if not (l.get('facts') or {}).get('ill')]
    rows = collections.Counter(len(pg.get('rows') or {}) for pg in with_lab.values())
    bottom = sum(1 for l in labs if (l.get('facts') or {}).get('illok'))
    _say('geom', '%-7s pages=%-3d labels=%-4d bottom-row=%-4d rows/page=%s'
         % (color, len(with_lab), len(labs), bottom, dict(sorted(rows.items()))))
    if no_frame:
        HARD.append('%s: %d page(s) without an inner frame: %s'
                    % (color, len(no_frame), no_frame[:8]))
    if no_title:
        SOFT.append('%s: %d page(s) without a title row: %s'
                    % (color, len(no_title), no_title[:8]))
    if no_art:
        pct = 100.0 * len(no_art) / max(1, len(labs))
        (SOFT if pct < 35 else HARD).append(
            '%s: %d/%d labels (%.0f%%) have no matching illustration%s'
            % (color, len(no_art), len(labs), pct,
               '' if pct < 35 else ' -- check geometry_export.illus_above / own_illus_cy_gap'))
    return pages


def check_translations(cfg, pages_by_color):
    langs = [l['code'] for l in cfg.langs]
    all_en = set()
    for pages in pages_by_color.values():
        for pg in pages.values():
            all_en.update(l['en'] for l in pg['labels'])
    if not all_en:
        return
    _tp = os.path.join(cfg.work, cfg.f.get('translations', 'translations.json'))
    if not os.path.exists(_tp):
        HARD.append('translations table not found: %s' % _tp)
        return
    T = json.load(open(_tp, encoding='utf-8'))
    for lang in langs:
        miss = [e for e in all_en
                if not (isinstance(T.get(e), dict) and T[e].get(lang))]
        short = sum(1 for e in all_en
                    if isinstance(T.get(e), dict) and T[e].get(lang + '_short'))
        _say('tr', '%-5s cover=%-4d/%-4d (%3.0f%%)  short=%-3d'
             % (lang, len(all_en) - len(miss), len(all_en),
                100.0 * (len(all_en) - len(miss)) / len(all_en), short))
        if miss:
            (HARD if len(miss) > 0.10 * len(all_en) else SOFT).append(
                '%s: %d label(s) without a translation, e.g. %r'
                % (lang, len(miss), miss[:5]))


def check_decisions(cfg):
    files = sorted(glob.glob(os.path.join(cfg.work, 'v7_dec_*.json')))
    if not files:
        _say('dec', 'none yet (run build_decisions.py)')
        return
    tot = collections.Counter()
    stuck = []
    for f in files:
        d = json.load(open(f, encoding='utf-8'))
        base = os.path.basename(f)[len('v7_dec_'):-5]
        for ab, items in (d.get('dec') or {}).items():
            for en, rec in items.items():
                tot[rec.get('mode')] += 1
                if rec.get('mode') in ('manual', 'row'):
                    stuck.append('%s p%d %s' % (base, int(ab) + 1, en.replace('\r', '/')))
    _say('dec', '%-28s %s' % ('modes', dict(tot)))
    if stuck:
        _say('dec', '%d label(s) still unresolved (mode=manual/row), e.g. %s'
             % (len(stuck), '; '.join(stuck[:6])))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    cfg = Config(args[0] if args else None)
    g = GeomLib(cfg)
    want = [c['code'] for c in cfg.colors]
    if '--color' in sys.argv:
        i = sys.argv.index('--color')
        if i + 1 < len(sys.argv):
            want = [sys.argv[i + 1]]
    print('preflight  work=%s' % cfg.work)
    pages_by_color = {c: check_geometry(cfg, g, c) for c in want}
    check_translations(cfg, pages_by_color)
    check_decisions(cfg)

    print()
    for s in SOFT:
        _say('NOTE', s)
    for h in HARD:
        _say('BLOCK', h)
    if HARD:
        print('\npreflight: %d blocker(s) -- fix before build_decisions.py' % len(HARD))
        return 2
    print('preflight: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main())
