# -*- coding: utf-8 -*-
r"""Create / validate / fill the two human-language tables the pipeline needs.

    python init_translations.py --init                 # 骨架：键来自源稿（+几何，含复合键）
    python init_translations.py --keys                 # 打印待译键清单（分批翻译用）
    python init_translations.py --merge it_1.json      # 合并 {en: "译文"} 到全部语言？
    python init_translations.py --merge it_1.json --lang it
    python init_translations.py --merge-gloss zh.json  # 合并 {en: "中文"} 到 zh_gloss.json
    python init_translations.py --check [--strict]     # 对照源稿校验，--strict 有缺就退出码 3

Why this exists
---------------
translations.json / zh_gloss.json used to be hand-assembled: keys were copied out
of the artwork by eye, so a typo silently produced an English card (tr() falls
back to the English text) or a KEY-NOTRANS at build time. The skill itself has
no translation ability (no network, no LLM) - but it CAN own the STRUCTURE:

  * keys are derived from the source artwork, never typed by hand;
  * compound two-line words ("clothing\rstore") come from the geometry TSV, not
    from the text spans, so --init must run AFTER export_geometry to see them;
  * every merge is idempotent and refuses unknown keys, so a chunk written for
    another book cannot pollute this one;
  * --check is the gate: missing / empty / extra keys, plus the count of
    two-line keys, "<lang>_short" and "<lang>_abbr" entries.

Content still comes from a translator (human, or the agent in-session): this
script never invents wording.
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import Config

_VAL_FLAGS = ('--merge', '--merge-gloss', '--lang', '--color', '--config')
_vetos = set()
for _i, _a in enumerate(sys.argv):
    if _a in _VAL_FLAGS and _i + 1 < len(sys.argv):
        _vetos.add(sys.argv[_i + 1])
args = [a for a in sys.argv[1:]
        if not a.startswith('--') and a not in _vetos]
cfg = Config(args[0] if args else None)

TR_PATH = os.path.join(cfg.work, cfg.f.get('translations', 'translations.json'))
GL_PATH = os.path.join(cfg.work, cfg.f.get('gloss', 'zh_gloss.json'))
LANGS = [l["code"] for l in cfg.langs]


# ---------------------------------------------------------------- key sources
def norm(t):
    return str(t).replace('|', '\r').strip()


def keys_from_spans():
    out = set()
    for color, rows in (cfg.spans or {}).items():
        for s in rows:
            t = norm(s.get('text') or '')
            if t and not t.isdigit():
                out.add(t)
    return out


def keys_from_geom():
    """Compound labels ("clothing\\rstore") only exist as ONE object in the
    artwork, so they are absent from the text spans. The geometry TSV keeps them
    verbatim after the '|' -> '\\r' normalisation."""
    out = set()
    for c in cfg.colors:
        p = os.path.join(cfg.work, cfg.f['geom'].format(color_code=c['code']))
        if not os.path.exists(p):
            continue
        for ln in open(p, encoding='utf-8'):
            f = ln.rstrip('\n').split('\t')
            if len(f) < 10 or f[1] not in ('L', 'T'):
                continue
            t = norm(f[9])
            if t and not t.isdigit():
                out.add(t)
    return out


def all_keys():
    return sorted(keys_from_spans() | keys_from_geom())


# ------------------------------------------------------------------- load/save
def load(path, default):
    if not os.path.exists(path):
        return default
    return json.load(open(path, encoding='utf-8'))


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(obj, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


# ------------------------------------------------------------------- commands
def cmd_init():
    keys = all_keys()
    old = load(TR_PATH, {})
    table = {}
    kept = 0
    for k in keys:
        v = old.get(k)
        if isinstance(v, dict):
            table[k] = {L: v.get(L, '') for L in LANGS}
            # carry project-specific columns (it_short / it_abbr ...) untouched
            for extra, val in v.items():
                if extra not in LANGS:
                    table[k][extra] = val
            kept += 1 if any(v.get(L) for L in LANGS) else 0
        else:
            table[k] = {L: '' for L in LANGS}
    dropped = sorted(set(old) - set(keys))
    save(TR_PATH, table)
    print('WROTE %s  keys=%d  (carried over %d non-empty, dropped %d stale key(s))'
          % (os.path.basename(TR_PATH), len(table), kept, len(dropped)))
    if dropped:
        print('  dropped: %s' % ', '.join(map(repr, dropped[:10])))
    if not os.path.exists(GL_PATH):
        save(GL_PATH, {'words': {}, 'overrides': {}})
        print('WROTE %s (empty skeleton)' % os.path.basename(GL_PATH))


def cmd_keys():
    keys = all_keys()
    out = os.path.join(cfg.work, 'tr_keys.txt')
    with open(out, 'w', encoding='utf-8') as f:
        for k in keys:
            f.write(k.replace('\r', '|\\r|') + '\n')
    print('WROTE %s  keys=%d' % (os.path.basename(out), len(keys)))
    print('compound (two-line) keys: %d' % sum(1 for k in keys if '\r' in k))


def cmd_merge(path, lang=None, overwrite=False):
    chunk = json.load(open(path, encoding='utf-8'))
    table = load(TR_PATH, {})
    known = set(table) | set(all_keys())
    filled = skipped_unknown = skipped_set = 0
    for en, val in chunk.items():
        en = norm(en)
        if en not in known:
            skipped_unknown += 1
            continue
        rec = table.setdefault(en, {L: '' for L in LANGS})
        if isinstance(val, dict):
            pairs = [(L, v) for L, v in val.items()]
        else:
            if not lang:
                raise SystemExit('flat chunk needs --lang <code> (or use {"en":{"it":..}} form)')
            pairs = [(lang, val)]
        if isinstance(val, dict) and ('zh' in val or 'zhcn' in val):
            # one chunk can carry both: {"apple": {"it": "mela", "zh": "苹果"}}
            zh = val.get('zh') or val.get('zhcn')
            if isinstance(zh, str) and zh.strip():
                g = load(GL_PATH, {'words': {}, 'overrides': {}})
                g.setdefault('words', {})[en] = zh.strip()
                save(GL_PATH, g)
            pairs = [(L, v) for L, v in pairs if L not in ('zh', 'zhcn')]
        for L, v in pairs:
            if not isinstance(v, str) or not v.strip():
                continue
            if rec.get(L) and not overwrite:
                skipped_set += 1
                continue
            rec[L] = v.replace('\n', '\r')
            filled += 1
    save(TR_PATH, table)
    print('MERGED %s: filled=%d unknown=%d kept-existing=%d'
          % (os.path.basename(path), filled, skipped_unknown, skipped_set))
    if skipped_unknown:
        print('  !! %d key(s) not present in the artwork were ignored '
              '(check spelling / stray whitespace)' % skipped_unknown)


def cmd_merge_gloss(path):
    chunk = json.load(open(path, encoding='utf-8'))
    g = load(GL_PATH, {'words': {}, 'overrides': {}})
    g.setdefault('words', {})
    g.setdefault('overrides', {})
    n = 0
    for en, zh in chunk.items():
        en = norm(en)
        if zh and zh.strip():
            g['words'][en] = zh.strip()
            n += 1
    save(GL_PATH, g)
    print('MERGED %s: words=%d total, %d from this chunk'
          % (os.path.basename(path), len(g['words']), n))


def cmd_check(strict=False):
    keys = all_keys()
    table = load(TR_PATH, {})
    missing = [k for k in keys if k not in table]
    extra = sorted(k for k in table if k not in keys)
    print('keys in artwork=%d  keys in table=%d' % (len(keys), len(table)))
    if missing:
        print('  MISSING %d key(s) (in artwork, not in table):' % len(missing))
        for k in missing[:10]:
            print('    - %r' % k)
    if extra:
        print('  EXTRA %d key(s) (in table, not in artwork):' % len(extra))
        print('    %s' % ', '.join(map(repr, extra[:10])))
    bad = 0
    for L in LANGS:
        empt = [k for k in keys if k in table and not (table[k].get(L) or '').strip()]
        pct = 100.0 * len(empt) / max(1, len(keys))
        flag = 'OK ' if not empt else ('!! ' if pct > 10 else '~  ')
        print('  %s%-5s empty=%d/%d (%.0f%%)' % (flag, L, len(empt), len(keys), pct))
        if empt:
            bad += 1
            if L == LANGS[0]:
                print('       e.g. %s' % ', '.join(map(repr, empt[:8])))
    comp = [k for k in keys if '\r' in k]
    print('  two-line (compound) keys: %d %s'
          % (len(comp), [k.replace('\r', '|') for k in comp[:5]]))
    for L in LANGS:
        s = [k for k, v in table.items() if isinstance(v, dict) and (v.get(L + '_short') or '').strip()]
        a = [k for k, v in table.items() if isinstance(v, dict) and (v.get(L + '_abbr') or '').strip()]
        print('  %-5s _short=%d  _abbr=%d' % (L, len(s), len(a)))
    g = load(GL_PATH, {})
    words = g.get('words', {})
    zh_missing = [k for k in keys if k not in words]
    print('  zh_gloss words=%d  missing=%d  overrides=%d'
          % (len(words), len(zh_missing), len(g.get('overrides', {}))))
    if missing or (strict and bad):
        print('CHECK FAILED')
        sys.exit(3)
    print('CHECK OK')


if '--init' in sys.argv:
    cmd_init()
elif '--keys' in sys.argv:
    cmd_keys()
elif '--merge' in sys.argv:
    chunk = sys.argv[sys.argv.index('--merge') + 1]
    lang = sys.argv[sys.argv.index('--lang') + 1] if '--lang' in sys.argv else None
    cmd_merge(chunk, lang, '--overwrite' in sys.argv)
elif '--merge-gloss' in sys.argv:
    cmd_merge_gloss(sys.argv[sys.argv.index('--merge-gloss') + 1])
elif '--check' in sys.argv:
    cmd_check('--strict' in sys.argv)
else:
    raise SystemExit(__doc__)
