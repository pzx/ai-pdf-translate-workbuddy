# -*- coding: utf-8 -*-
"""Rebuild only what changed: fingerprint skip + JSX generation + batch runner.

    python rebuild.py it_blue           ONE book (underscore/colon/comma joined)
    python rebuild.py it                all colours of one language
    python rebuild.py blue              one colour across all languages
    python rebuild.py it blue           TWO arguments = it(all colours) + blue(all
                                        languages) merged -- NOT one book!
    python rebuild.py all               every book (skips unchanged)
    python rebuild.py all --force       every book, ignore fingerprints

Fingerprint = decision file (size,mtime) + width_tables.json + source file
(size,mtime) + the layout-affecting CONFIG sections (geometry / layout / gate /
decision_engine / languages / default_font), stored in manifest. The config
sections are in on purpose: editing title_two_fill or a font must not report
SKIP(unchanged) on every book while the artwork keeps the old rule. Generator
SCRIPTS stay out: editing a script must not silently invalidate all books - use
--force for an intentional full rebuild. Success is judged by OUTPUT PDF mtime,
NOT the PowerShell stdout (non-UTF8), and the exit code reports failures
instead of only printing them.
"""
import os, sys, subprocess, json, time
from common import (Config, load_manifest, save_manifest, signature)

cfg = Config()
FORCE = '--force' in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith('--')]
if not args:
    raise SystemExit(__doc__)

sel = []
def add(l, c):
    if l in cfg.L and c in cfg.C and (l, c) not in sel:
        sel.append((l, c))

# Accepted selectors, all equivalent:
#   all | <lang> | <color> | <lang>:<color> | <lang>_<color> | a,b,c
# The old parser guessed "<lang><color>" by slicing the first two characters,
# so "it:orange" quietly resolved to ('it','') and rebuilt nothing while still
# exiting 0 -- a silent no-op is the worst failure mode for a build step.
for a in args:
    if a == 'all':
        for l in cfg.langs:
            for c in cfg.colors:
                add(l['code'], c['code'])
        continue
    if a in cfg.L:
        for c in cfg.colors:
            add(a, c['code'])
        continue
    if a in cfg.C:
        for l in cfg.langs:
            add(l['code'], a)
        continue
    got = False
    for part in [x for x in a.split(',') if x]:
        if ':' in part:
            l, c = part.split(':', 1)
        elif '_' in part:
            l, c = part.split('_', 1)
        else:
            continue          # bare token without a separator: not a target
        before = len(sel)
        add(l, c)
        got = got or len(sel) > before
    if not got:
        raise SystemExit('unknown target: %s  (use all | <lang> | <color> | '
                         '<lang>:<color>)' % a)
if not sel:
    raise SystemExit('nothing selected')

man = load_manifest(cfg)
jsxs, skipped, gen_failed = [], 0, []
env = dict(os.environ, BATCH_DATE=cfg.batch)
for lang, color in sel:
    ai, pdf = cfg.product_paths(lang, color)
    key = '%s|%s' % (lang, color)
    if (not FORCE and man.get(key) == signature(cfg, lang, color)
            and os.path.exists(ai) and os.path.exists(pdf)):
        print('--- %s %s  SKIP (unchanged)' % (lang, color), flush=True)
        skipped += 1; continue
    js = cfg.fmt('jsx', lang_code=lang, color_code=color)
    log = cfg.fmt('jsx_log', lang_code=lang, color_code=color)
    # absolute: the batch runner lives in <skill>/scripts and resolves relative
    # entries against ITS own folder, so a bare name is always MISSING there
    if not os.path.isabs(js):
        js = os.path.join(cfg.work, js)
    if not os.path.isabs(log):
        log = os.path.join(cfg.work, log)
    print('--- %s %s' % (lang, color), flush=True)
    gen = os.path.join(os.path.dirname(__file__), cfg.jsx.get('generator', 'make_jsx.py'))
    r = subprocess.run([sys.executable, gen, lang, color, js, log, cfg.path],
                       cwd=os.path.dirname(__file__), env=env,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        # a generator failure is normally the decision gate refusing an
        # incomplete decision file; show it loudly and abort the whole batch
        # instead of silently continuing with a wrong-looking delivery.
        print('    !! GENERATOR FAILED for %s %s (gate or error)' % (lang, color), flush=True)
        print('       ' + (r.stderr or r.stdout or '').strip()[-600:], flush=True)
        gen_failed.append('%s %s' % (lang, color))
        continue
    tail = [l for l in (r.stdout or '').splitlines() if 'decisions' in l]
    print('   ', tail[-1] if tail else (r.stdout or '')[-200:], flush=True)
    jsxs.append((js, lang, color))

if gen_failed:
    print('\n=== ABORT: %d book(s) blocked by the decision gate / generator error: %s'
          % (len(gen_failed), ', '.join(gen_failed)), flush=True)
    print('    Fix the decision JSON (missing cx) - NOTHING was sent to Illustrator.', flush=True)
    raise SystemExit(4)

if not jsxs:
    print('%d book(s) unchanged, nothing to build' % skipped, flush=True)
    raise SystemExit(0)

lst = 'joblist_%s.txt' % (time.strftime('%H%M%S'))
with open(os.path.join(cfg.work, lst), 'w', encoding='utf-8') as f:
    f.write('\n'.join(j for j, _, _ in jsxs) + '\n')
print('--- %d book(s) -> %s' % (len(jsxs), lst), flush=True)
started = time.time()
runner = os.path.normpath(os.path.join(os.path.dirname(__file__), cfg.jsx.get('runner', '../scripts/run_batch.ps1')))
cmd = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', runner,
       '-List', os.path.join(cfg.work, lst),
       '-WaitMs', str(cfg.jsx.get('wait_ms', 2000)),
       '-DoneMarker', cfg.jsx.get('done_marker', 'DONE total_ms')]
r = subprocess.run(cmd, cwd=cfg.work, text=True, encoding='utf-8', errors='replace')
print((r.stdout or '')[-2500:])
# trust file timestamps, not console text
built, failed = 0, []
for js, lang, color in jsxs:
    ai, pdf = cfg.product_paths(lang, color)
    if os.path.exists(ai) and os.path.exists(pdf) and os.path.getmtime(pdf) >= started - 2:
        man['%s|%s' % (lang, color)] = signature(cfg, lang, color)
        built += 1
    else:
        failed.append('%s %s' % (lang, color))
save_manifest(cfg, man)
print('built %d/%d, skipped %d%s' %
      (built, len(jsxs), skipped,
       '' if not failed else ', FAILED: ' + ', '.join(failed)), flush=True)
if failed:
    # the runner may still have exited 0 (older copies do); the products are the
    # only evidence that matters, so fail here as well
    raise SystemExit(2)
sys.exit(r.returncode)
