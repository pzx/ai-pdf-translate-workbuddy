# -*- coding: utf-8 -*-
"""Rebuild only what changed: fingerprint skip + JSX generation + batch runner.

    python rebuild.py it_blue           ONE book (underscore/colon/comma joined)
    python rebuild.py it                all colours of one language
    python rebuild.py blue              one colour across all languages
    python rebuild.py it blue           TWO arguments = it(all colours) + blue(all
                                        languages) merged -- NOT one book!
    python rebuild.py all               every book (skips unchanged)
    python rebuild.py all --force       every book, ignore fingerprints

Fingerprint = decision file (size,mtime) + source file (size,mtime), stored in
manifest. Deliberately EXCLUDES generator scripts: editing a script must not
silently invalidate all books - use --force for an intentional full rebuild.
Success is judged by OUTPUT PDF mtime, NOT the PowerShell stdout (non-UTF8).
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
for a in args:
    if a == 'all':
        for l in cfg.langs:
            for c in cfg.colors:
                add(l['code'], c['code'])
    elif a in cfg.L:
        for c in cfg.colors:
            add(a, c['code'])
    elif ':' in a or ',' in a or '_' in a:
        for part in a.replace(':', ',').split(','):
            l, c = (part.split('_', 1) if '_' in part else (part[:2], part[2:]))
            add(l, c)
    elif a in cfg.C:
        for l in cfg.langs:
            add(l['code'], a)
    else:
        raise SystemExit('unknown target: ' + a)

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
for js, lang, color in jsxs:
    ai, pdf = cfg.product_paths(lang, color)
    if os.path.exists(ai) and os.path.exists(pdf) and os.path.getmtime(pdf) >= started - 2:
        man['%s|%s' % (lang, color)] = signature(cfg, lang, color)
save_manifest(cfg, man)
print('built %d, skipped %d' % (len(jsxs), skipped), flush=True)
sys.exit(r.returncode)
