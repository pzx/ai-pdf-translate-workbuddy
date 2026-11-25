# -*- coding: utf-8 -*-
r"""Export geometry TSVs from the source .ai files (one JSX per colour).

    python export_geometry.py [all|<color> [<color> ...]] [--no-run]

For each colour it injects SRC / output paths / the GEO size gates into
geometry_export_template.jsx, emits a pure-ASCII JSX into work/, then runs the
same Illustrator batch runner used for builds. Success is judged by each
<geom>.log carrying the DONE marker AND a non-trivial geom TSV.

Size gates live in config.geometry_export - tune them for a NEW layout until
the per-artboard label/title/illustration counts look right (see --no-run and
the printed counts). This is the one step that is NOT layout-agnostic: object
classification is inherently driven by the artwork's own dimensions.
"""
import os, sys, json, subprocess, time
from common import Config

cfg = Config()
HERE = os.path.dirname(os.path.abspath(__file__))
TPL = open(os.path.join(HERE, 'geometry_export_template.jsx'), encoding='utf-8').read()

g = cfg.d.get('geometry_export', {})
GEO = {
    'lhmin': g.get('label_h_range', [14, 46])[0],
    'lhmax': g.get('label_h_range', [14, 46])[1],
    'fwmin': g.get('frame_w_min', 300),
    'fhmin': g.get('frame_h_min', 250),
    'twmin': g.get('title_w_range', [130, 165])[0],
    'twmax': g.get('title_w_range', [130, 165])[1],
    'thmin': g.get('title_h_range', [28, 40])[0],
    'thmax': g.get('title_h_range', [28, 40])[1],
    'iminKids': g.get('illus_min_kids', 2),
    'iminH': g.get('illus_h_min', 25),
    'iwmin': g.get('inner_w_range', [410, 470])[0],
    'iwmax': g.get('inner_w_range', [410, 470])[1],
    'innerHMin': g.get('inner_h_range', [260, 300])[0],
    'innerHMax': g.get('inner_h_range', [260, 300])[1],
    # recognise a title by its TEXT (font size), not only by its banner box
    'tmin': g.get('title_min_size_pt', 19),
    # a title must sit in the top band of the card (fraction of its height)
    'tband': g.get('title_band_ratio', 0.25),
    # banner-shaped vector art in the title band -> suspected OUTLINED title
    'xwmin': g.get('outline_w_range', [60, 220])[0],
    'xwmax': g.get('outline_w_range', [60, 220])[1],
    'xhmin': g.get('outline_h_range', [12, 60])[0],
    'xhmax': g.get('outline_h_range', [12, 60])[1],
}
GEO_JS = 'var GEO={' + ','.join('%s:%s' % (k, v) for k, v in GEO.items()) + '};'


def js(s):
    out = []
    for ch in str(s):
        o = ord(ch)
        if ch == '"': out.append('\\"')
        elif ch == '\\': out.append('\\\\')
        elif ch == '\r': out.append('\\r')
        elif ch == '\n': out.append('\\n')
        elif 32 <= o < 127: out.append(ch)
        else: out.append('\\u%04x' % o)
    return '"' + ''.join(out) + '"'


args = [a for a in sys.argv[1:] if not a.startswith('--')]
NO_RUN = '--no-run' in sys.argv
_ALL = [c['code'] for c in cfg.colors]
if not args or args[0] == 'all':
    # "all" means every colour; the old code took args[1:] and silently exported 0 books
    want = args[1:] or _ALL
else:
    want = args
jobs = []
for color in want:
    if color not in cfg.C:
        print('skip unknown color', color); continue
    src = cfg.source_path(color)
    geom = os.path.join(cfg.work, 'geom_%s.tsv' % color)
    inner = os.path.join(cfg.work, 'inner_%s.tsv' % color)
    jx = os.path.join(cfg.work, 'export_geom_%s.jsx' % color)
    tpl = (TPL.replace('__SRC__', js(src.replace('\\', '/')))
              .replace('__LOG_GEOM__', js(geom.replace('\\', '/')))
              .replace('__LOG_INNER__', js(inner.replace('\\', '/')))
              # runner convention: "<script>.log" (extension REPLACED, see run_batch.ps1)
              .replace('__LOG_JOB__', js((os.path.splitext(jx)[0] + '.log').replace('\\', '/')))
              .replace('__CFG__', GEO_JS))
    bad = [c for c in tpl if ord(c) > 127]
    if bad:
        raise SystemExit('non-ASCII leaked into geometry JSX: %r' % bad[:5])
    open(jx, 'w', encoding='utf-8', newline='\n').write(tpl)
    jobs.append((color, jx, geom))
    print('gen', os.path.basename(jx), 'src=', os.path.basename(src))

if NO_RUN:
    print('--no-run: JSX generated, not executed'); raise SystemExit(0)

lst = 'geom_jobs_%s.txt' % time.strftime('%H%M%S')
open(os.path.join(cfg.work, lst), 'w', encoding='utf-8').write(
    # absolute paths: the runner lives in <skill>/scripts, not in work/, so bare
    # basenames would be resolved against the wrong directory (MISSING every job)
    '\n'.join(j for _, j, _ in jobs) + '\n')
runner = os.path.normpath(os.path.join(HERE, cfg.jsx.get('runner', '../scripts/run_batch.ps1')))
r = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', runner,
                    '-List', os.path.join(cfg.work, lst),
                    '-WaitMs', str(cfg.jsx.get('wait_ms', 2000)),
                    '-DoneMarker', 'DONE total_ms'],
                   cwd=cfg.work, text=True, encoding='utf-8', errors='replace')
print((r.stdout or '')[-2000:])

# judge by outputs, not console text
REQUIRE_T = bool(g.get('require_title_per_board', True))
bad = []
for color, jx, geom in jobs:
    log = os.path.splitext(jx)[0] + '.log'
    ok = (os.path.exists(geom) and os.path.exists(log)
          and 'DONE total_ms' in open(log, encoding='utf-8', errors='replace').read())
    lines = sum(1 for _ in open(geom, encoding='utf-8')) if os.path.exists(geom) else 0
    print('%-8s geom=%s lines=%d' % (color, 'OK' if ok else 'FAIL', lines))
    if not ok or lines < 10:
        bad.append(color)
        continue
    # Every artboard must yield exactly one title row. When the artwork draws a
    # title differently (e.g. not as a group of the expected size) that page's
    # title silently vanishes from the decisions, and the JSX then leaves it in
    # English without any error -- exactly what happened to 4 "Behaviors" pages.
    t_boards, all_boards, x_boards, y_boards = set(), set(), set(), set()
    for ln in open(geom, encoding='utf-8'):
        f = ln.rstrip('\n').split('\t')
        if len(f) < 2:
            continue
        try:
            ab = int(f[0])
        except ValueError:
            continue
        all_boards.add(ab)
        if f[1] == 'T':
            t_boards.add(ab)
        elif f[1] == 'X':
            x_boards.add(ab)
        elif f[1] == 'Y':
            y_boards.add(ab)
    if y_boards:
        print('    !! artboard(s) %s have NO text object at all -- the page looks' % sorted(y_boards))
        print('       fully outlined. Nothing on it can be replaced as text.')
    if all_boards:
        n_ab = max(all_boards) + 1
        missing = sorted(set(range(n_ab)) - t_boards)
        outlined = sorted(set(missing) & x_boards)
        absent = sorted(set(missing) - x_boards)
        dups = sorted(b for b in t_boards if sum(
            1 for ln2 in open(geom, encoding='utf-8')
            if ln2.split('\t')[:2] == [str(b), 'T']) > 1)
        if dups:
            print('    !! artboard(s) %s carry MORE THAN ONE title row (T).' % dups)
            print('       Only one pill per card is normal: a same-shaped group lower on')
            print('       the card (calendar cell, badge) is being misfiled as a title.')
            print('       Tune geometry_export.title_band_ratio / title_w|h_range.')
        print('         artboards=%d titles=%d%s'
              % (n_ab, len(t_boards), '' if not missing else '  MISSING on %s' % missing))
        if outlined:
            print('    !! artboard(s) %s: the title is OUTLINED (vector art where the' % outlined)
            print('       banner belongs, no text object). It cannot be replaced as text;')
            print('       re-export those pages with live text, or redraw that title by hand.')
        if absent and REQUIRE_T:
            print('    !! artboard(s) %s have no title row (T) and no banner art either.' % absent)
            print('       The title there is not a group of the expected size, so it never')
            print('       reaches the decisions and would stay in ENGLISH, silently.')
            print('       Fix: add it to config "tune": {"titles": {"<lang>": {"<EN>": "<TR>"}}}')
            print('       or adjust geometry_export.title_w_range / title_h_range, then re-run')
            print('       export_geometry.py + build_decisions.py.')
            bad.append(color)
        elif absent:
            print('    !! (allowed by geometry_export.require_title_per_board=false)')
        if outlined:
            print('       -> outlined-title artboards are reported, not fatal (text needs manual work)')
if bad:
    raise SystemExit('geometry export FAILED for: ' + ', '.join(bad))
print('geometry exported for %d color(s)' % len(jobs))
