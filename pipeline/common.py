# -*- coding: utf-8 -*-
"""Shared config loader and helpers for the generic translation pipeline.

All project-specific facts live in a pipeline.json (see config.example.json).
Every script imports from here so naming/paths/schema are defined in ONE place.

Core contract (the decision JSON is the single source of truth):
    {
      "dec": { "<ab>": { "<english>": {"val", "sz"?, "cx"?, "dy"?, "mode"?} } },
      "title_map": { "<english title>": "<translation>" }
    }
The ledger (xlsx) is only a VIEW of these files. Edits flow back via ledger_import.
"""
import os, json, hashlib, collections, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)


def find_config(explicit=None):
    """Locate pipeline.json: explicit arg > env > this dir > cwd."""
    cands = []
    if explicit:
        cands.append(explicit)
    if os.environ.get('PIPELINE_CONFIG'):
        cands.append(os.environ['PIPELINE_CONFIG'])
    cands += [os.path.join(HERE, 'pipeline.json'), os.path.join(os.getcwd(), 'pipeline.json')]
    for p in cands:
        if p and os.path.exists(p):
            return os.path.abspath(p)
    raise SystemExit('pipeline.json not found. Copy config.example.json -> pipeline.json '
                     'and edit, or set PIPELINE_CONFIG.')


class Config:
    def __init__(self, path=None):
        self.path = find_config(path)
        self.d = json.load(open(self.path, encoding='utf-8'))
        self.base = os.path.abspath(self.d['base'])
        self.work = self._abs(self.d.get('work_dir', 'work'))
        self.input_dir = self._abs(self.d.get('input_dir', 'input'))
        self.output = self._abs(self.d.get('output_dir', 'output'))
        self.xlsx_dir = self._abs(self.d.get('xlsx_dir', 'output/xlsx'))
        self.batch = os.environ.get('BATCH_DATE') or str(self.d.get('batch_date', ''))
        self.langs = self.d['languages']           # [{code,name,font}]
        self.colors = self.d['colors']             # [{code,name,no,pages}]
        self.L = {l['code']: l for l in self.langs}
        self.C = {c['code']: c for c in self.colors}
        self.LNAME = {l['code']: l['name'] for l in self.langs}
        self.CNAME = {c['code']: c['name'] for c in self.colors}
        self.NAME2LANG = {l['name']: l['code'] for l in self.langs}
        self.NAME2COLOR = {c['name']: c['code'] for c in self.colors}
        self.f = self.d['files']
        self.s = self.d['schema']
        self.jsx = self.d.get('jsx', {})
        self.DEF_FONT = self.d.get('default_font', 'Arial Rounded MT Bold')
        self._spans = None
        self._gloss = None
        self._sizes = None

    def _abs(self, p):
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(self.base, p))

    def fmt(self, key, **kw):
        ctx = dict(base=self.base, work=self.work, batch=self.batch,
                   lang_code='', color_code='', lang_name='', color_name='', no='')
        ctx.update(kw)
        return self.f[key].format(**ctx)

    def decision_path(self, lang, color):
        return os.path.join(self.work, self.fmt('decision', lang_code=lang, color_code=color))

    def source_path(self, color):
        c = self.C[color]
        return os.path.join(self.input_dir, self.fmt('source_ai', color_code=color,
                            color_name=c['name'], no=c['no']))

    def product_stem(self, lang, color):
        c, l = self.C[color], self.L[lang]
        return self.fmt('product', color_code=color, color_name=c['name'], no=c['no'],
                        lang_code=lang, lang_name=l['name'])

    def product_paths(self, lang, color):
        stem = self.product_stem(lang, color)
        return (os.path.join(self.output, self.batch, 'ai', stem + '.ai'),
                os.path.join(self.output, self.batch, 'pdf', stem + '.pdf'))

    def ledger_path(self):
        return os.path.join(self.xlsx_dir, self.f['ledger'])

    def letters_path(self):
        return os.path.join(self.xlsx_dir, self.f['letters'])

    def font_for(self, lang):
        return self.L[lang].get('font') or self.DEF_FONT

    # ---- source metrics (font size per colour/page/word) --------------------
    @property
    def spans(self):
        if self._spans is None:
            p = os.path.join(self.work, self.f['spans'])
            self._spans = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
        return self._spans

    @property
    def sizes(self):
        """(color, page_1based, norm_word) -> size; duplicates take the larger."""
        if self._sizes is None:
            raw = collections.defaultdict(list)
            for color, lst in self.spans.items():
                for it in lst:
                    t = norm(it.get('text', ''))
                    if t:
                        raw[(color, it['page'], t)].append(it['size'])
            self._sizes = {k: max(v) for k, v in raw.items()}
        return self._sizes

    def src_size(self, color, en, ab=None):
        heads = [norm(en)] + [norm(p) for p in str(en).replace('\n', '\r').split('\r') if norm(p)]
        if ab is not None and ab not in (None, '', 'TITLE', '标题'):
            page = int(ab) + (1 if self.s.get('ab_is_zero_based', True) else 0)
            for h in heads:
                if (color, page, h) in self.sizes:
                    return self.sizes[(color, page, h)]
        vals = [v for h in heads for (c, _p, w), vv in self.sizes.items()
                if c == color and w == h for v in [vv]]
        if not vals:
            return 18.0
        return collections.Counter(vals).most_common(1)[0][0]

    # ---- Chinese gloss ------------------------------------------------------
    @property
    def gloss(self):
        if self._gloss is None:
            p = os.path.join(self.work, self.f['gloss'])
            self._gloss = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {}
        return self._gloss

    def zh(self, color, ab, en):
        g = self.gloss
        words, over = g.get('words', {}), g.get('overrides', {})
        k = '%s|%s|%s' % (color, ab, norm(en))
        return over.get(k, words.get(norm(en), ''))

    # ---- reading order (so ledger rows follow the page layout) --------------
    def order_index(self):
        idx = {}
        for color, lst in self.spans.items():
            for it in lst:
                t = str(it.get('text', '')).strip()
                if t and t not in idx:
                    idx[t] = (it['page'], round(it['bbox'][1], 1), it['bbox'][0])
        return idx

    def sort_key(self, order, en, ab):
        o = order.get(en) or order.get(str(en).split('\r')[0])
        a = 0 if ab in (None, '', 'TITLE', '标题') else int(ab)
        return (0, a, o[1], o[2]) if o else (999, a, 0, 0)


# ---- shared string helpers -------------------------------------------------
def norm(t):
    """Normalise a text-frame key: collapse whitespace/newlines, lower, tidy parens."""
    t = ' '.join(str(t).replace('\r', ' ').replace('\n', ' ').split()).strip().lower()
    return t.replace('( ', '(').replace(' )', ')')


def nk(t):
    return norm(t)


def crlf(s):
    """xlsx stores soft returns as \n; decisions use \r. Normalise both ways."""
    return str(s).replace('\r\n', '\n').replace('\n', '\r')


def load_dec(cfg, lang, color):
    return json.load(open(cfg.decision_path(lang, color), encoding='utf-8'))


def signature(cfg, lang, color):
    """Fingerprint = decision file + source file + the width tables.

    Deliberately EXCLUDES generator scripts: editing a script must not silently
    invalidate every book. Use --force for an intentional full rebuild.
    The width tables ARE included: they decide wrapping / short forms / max
    width per slot, so a change there must invalidate the book -- otherwise a
    rebuild reports SKIP(unchanged) and the new rule never reaches the files.
    """
    h = hashlib.md5()
    st = os.stat(cfg.decision_path(lang, color))
    h.update(('%s|%s|' % (st.st_size, int(st.st_mtime))).encode())
    wt = os.path.join(cfg.work, 'width_tables.json')
    if os.path.exists(wt):
        sw = os.stat(wt)
        h.update(('%s|%s|' % (sw.st_size, int(sw.st_mtime))).encode())
    st = os.stat(cfg.source_path(color))
    h.update(('%s|%s' % (st.st_size, int(st.st_mtime))).encode())   # no trailing '|' (matches project manifest format)
    return h.hexdigest()


def load_manifest(cfg):
    p = os.path.join(cfg.work, cfg.f['manifest'])
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return {}


def save_manifest(cfg, man):
    p = os.path.join(cfg.work, cfg.f['manifest'])
    json.dump(man, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def columns(ws):
    """header name -> column index, so columns can be added/reordered freely."""
    m = {}
    for i in range(1, ws.max_column + 1):
        v = ws.cell(row=1, column=i).value
        if v:
            m[str(v).strip()] = i
    return m
