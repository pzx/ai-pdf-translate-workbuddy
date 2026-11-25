# -*- coding: utf-8 -*-
r"""Generate a decision-driven Illustrator JSX for one language x colour.

    python make_jsx.py <lang> <color> <out.jsx> <out.log> [pipeline.json]

Reads the decision JSON for (lang,color) and emits a self-contained JSX that:
  - opens the source .ai, replaces text frames by decision key (val/size/cx/dy)
  - resolves every word against ITS OWN artboard first (boardOf), so a key that
    appears on several pages never borrows another page's centre
  - guards word width with the self-generated width tables (MAXW / SCALE)
  - typesets titles with ONE size per title, derived from the source artwork and
    shrunk only until the ink box is inside the title oval; wrapped titles are
    centred line-by-line (see layout_rules() below)
  - applies the language's output font (CJK fallback already chosen in config)
  - saves editable .ai WITH PDF compatibility layer (unless disabled - NEVER in delivery)
  - outlines all text frames then saves the outlined .pdf
  - writes a log with a DONE marker + timing, and ERROR: on failure
  - keeps the source artwork/illustrations/letters untouched

Encoding rule (critical): JSX must be pure ASCII. Every non-ASCII string is
escaped to \uXXXX by js() below; template comments stay English. ExtendScript
parses the file as ANSI and a stray Chinese character breaks DoJavaScriptFile
with "JavaScript code was missing".
"""
import os, sys, json
from common import Config

lang, color, outjs, outlog = sys.argv[1:5]
cfg = Config(sys.argv[5] if len(sys.argv) > 5 else None)
d = __import__('common').load_dec(cfg, lang, color)
S = cfg.s
E, V, SZ = S['entries'], S['value'], S['size_override']
FONT = cfg.font_for(lang)
# Title band: everything whose text bottom sits above this many points from the
# page top is treated as a title. 62 fits the card deck; a taller/full-page
# layout must raise it (layout.title_band_pt).
TITLE_BAND = float((cfg.d.get('layout') or {}).get('title_band_pt', 62))

# R1 font resolution: Illustrator's app.textFonts[i].name is NOT always the
# Windows family+style string from config (a family/style name may silently
# fail while the font IS installed, because Illustrator exposes its PostScript
# name instead). Derive every name the font advertises from its own file (full
# name + PostScript name, all locales) and hand them ALL to the JSX as
# candidates. findFont matches any of them; a total miss is logged loudly
# instead of silently leaving the source artwork's font in place.
def _font_candidates():
    names = [FONT]
    # called at import time, before _font_file() below is defined -> use Config directly
    ff = cfg.resolve_font_file(lang, required=False)
    if ff and os.path.exists(ff):
        try:
            from fontTools.ttLib import TTFont
            f = TTFont(ff)
            for rec in f['name'].names:
                if rec.nameID not in (1, 4, 6):   # family / full / postscript
                    continue
                try:
                    v = rec.toUnicode()
                except Exception:
                    continue
                if v and v not in names:
                    names.append(v)
            f.close()
        except Exception:
            pass
    return names

FONTCANDS = _font_candidates()
src = cfg.source_path(color)
ai, pdf = cfg.product_paths(lang, color)
SPANS = os.path.join(cfg.work, cfg.f.get('spans', 'spans_all.json'))
if not os.path.exists(SPANS):
    # Title sizes are measured from the source spans. Without them every title
    # used to fall back to a hard-coded 22pt and quietly break the per-page
    # sizing (green 'Abbigliamento' 15.8 / orange 'Body Parts' 14.7 -> blown up).
    print('SPANS-MISSING %s' % SPANS)
    print('  title sizes come from the source spans; refusing to guess 22pt for every')
    print('  title. Generate the file first:  python export_spans.py')
    sys.exit(3)

# ---- geometry configuration (layout constraints) -------------------------
g = cfg.d.get('geometry', {})
GEO = {
    'capr': g.get('cap_ratio_by_lang', {}).get(lang, g.get('cap_ratio_default', 0.7280)),
    'lead': g.get('lead_at_18', 17.9),
    'title_fit': bool(g.get('title_fit', True)),
    'ikword': bool(g.get('ink_bounds_words', False)),
    'emargin': g.get('ellipse_margin', 0.94),
    'ewmin': g.get('ellipse_w_range', [80, 150])[0],
    'ewmax': g.get('ellipse_w_range', [80, 150])[1],
    'ehmin': g.get('ellipse_h_range', [18, 60])[0],
    'ehmax': g.get('ellipse_h_range', [18, 60])[1],
    'edxy': g.get('ellipse_center_tol', 8),
    'egap': g.get('ellipse_lead_gap', 1.5),
    'ogap': g.get('obstacle_gap', 0),
    'ocap': g.get('obstacle_nudge_cap', 0),
    # a wrapped label may be lifted at most this far, and must keep this much
    # clear of the card's bottom edge (see the wrapDy block)
    'bmargin': float(cfg.d.get('layout', {}).get('card_bottom_margin_pt', 6)),
    # a frame at/above this size that misses TITLE[] is reported as TITLE-MISS
    'tmissz': float(cfg.d.get('layout', {}).get('title_miss_size_pt', 19.5)),
    # body text may only be resized when a project explicitly opts in
    'bshr': bool(cfg.d.get('layout', {}).get('body_shrink', False)),
}
# GEO_JS is emitted AFTER the title sizes are derived from the source artwork
GEOMETRY_JS = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'geometry.jsx.inc'), encoding='utf-8').read()

# ---- width tables (self-generated by build_width_tables.py) -----------------
# MAXW: per-slot max allowed ink width; SCALE: per-entry font-size factor;
# FINAL: translated text possibly wrapped with \r. Falls back to empty tables
# if the width pass was not run, so the generator stays usable stand-alone.
_wt_path = os.path.join(cfg.work, 'width_tables.json')
WT = json.load(open(_wt_path, encoding='utf-8')) if os.path.exists(_wt_path) else {}
SLOT = WT.get('slot', {})
SAFE = WT.get('safe', {})
PERLANG = WT.get('per_lang', {}).get(lang, {})

# apply FINAL (wrapped) translations + record SCALE into decision entries in-memory
for _ab, _recs in d.get(E, {}).items():
    for _en, _rec in _recs.items():
        _key = _en
        if _key not in PERLANG and '\r' in _key:
            _key = _key.split('\r')[0]
        _pl = PERLANG.get(_key)
        if _pl:
            # NEVER undo a wrap that build_decisions already solved: the width
            # table is a second opinion, and its unwrapped text would silently
            # collapse a correct two-line label back onto one long line
            # ("camion dei pompieri" grew 177pt wide and ran into its neighbours).
            _dv = _rec.get(V)
            if not (isinstance(_dv, str) and '\r' in _dv and '\r' not in str(_pl['val'])):
                _rec[V] = _pl['val']      # wrapped text, e.g. "macchina\rdella polizia"
            _rec['scale'] = _pl['scale']  # font-size factor
        else:
            _rec.setdefault('scale', 1.0)

# MAXW for titles = TITLE_MAXW (105); for body = slot maxw
MAXW = {}
for _en, _info in SLOT.items():
    MAXW[_en] = _info['maxw']
# SCALE map from PERLANG (built after js() is defined, see below)

for p in (os.path.dirname(ai), os.path.dirname(pdf)):
    os.makedirs(p, exist_ok=True)

def js(s):
    """escape any string to a pure-ASCII JS double-quoted literal"""
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

# build JS table literals now that js() exists
MAXW_JS = ',\n'.join('%s:%s' % (js(en), MAXW[en]) for en in sorted(MAXW))
SCALE = {en: r.get('scale', 1.0) for en, r in PERLANG.items()}
SCALE_JS = ',\n'.join('%s:%s' % (js(en), round(SCALE[en], 4)) for en in sorted(SCALE))

# ---- decision completeness gate -------------------------------------------
# A decision entry MUST carry cx: the target horizontal centre measured from
# the source artwork. Without it this script emits cx=null and the JSX silently
# skips the centring translate(), so every word sits off its illustration.
# That is exactly what happens when a project builds decisions with only
# val/mode (no geometry pass). sz is deliberately optional: a missing sz means
# "keep the source font size", which is the normal case in the reference book.
gate = cfg.d.get('gate', {})
total_entries = sum(len(v) for v in d.get(E, {}).values() if isinstance(v, dict))
if total_entries == 0:
    sys.stderr.write('GATE FAIL %s %s: decision file has no entries under "%s".\n'
                     % (lang, color, E))
    sys.exit(3)
missing_cx, missing_sz = [], []
for ab in sorted(d.get(E, {}), key=lambda x: int(x)):
    for en, rec in d[E][ab].items():
        if rec.get('cx') is None:
            missing_cx.append('%s|%s' % (ab, en))
        if rec.get('sz') is None:
            missing_sz.append('%s|%s' % (ab, en))
if missing_cx:
    sys.stderr.write(
        'GATE FAIL %s %s: %d/%d entries have NO cx (target centre). '
        'The generated JSX would skip centring and misalign every word. '
        'Run the geometry-based decision engine first. Examples: %s\n'
        % (lang, color, len(missing_cx), total_entries, ', '.join(missing_cx[:10])))
    sys.exit(3)
if gate.get('require_sz') and missing_sz:
    sys.stderr.write(
        'GATE FAIL %s %s: %d/%d entries have NO sz and gate.require_sz is true. '
        'Examples: %s\n'
        % (lang, color, len(missing_sz), total_entries, ', '.join(missing_sz[:10])))
    sys.exit(3)

# ---- decision map: artboard -> { english-key : {val,sz,cx,dy} } --------------
map_lines, ill_lines = [], []
for ab in sorted(d.get(E, {}), key=lambda x: int(x)):
    entries, ientries = [], []
    for en, rec in d[E][ab].items():
        val = rec.get(V, '')
        sz = rec.get(SZ)
        cx = rec.get('cx')
        dy = rec.get('dy', 0)
        cx_s = 'null' if cx is None else str(round(float(cx), 3))
        sz_s = 'null' if sz is None else str(round(float(sz), 3))
        dy_s = str(round(float(dy or 0), 3))
        _ssrc = rec.get('szsrc')          # NB: not `src` - that is the .ai path
        src_s = 'null' if _ssrc is None else str(round(float(_ssrc), 3))
        _idy = rec.get('illdy')
        idy_s = 'null' if _idy is None else str(round(float(_idy), 3))
        _dupof = rec.get('dupof')
        dup_s = 'null' if _dupof is None else js(_dupof)
        _dupidx = rec.get('dupidx')
        didx_s = 'null' if _dupidx is None else str(int(_dupidx))
        entries.append('%s:[%s,%s,%s,%s,%s,%s,%s,%s]' % (
            js(en), js(val), cx_s, sz_s, dy_s, src_s, idy_s, dup_s, didx_s))
        _ib = rec.get('ill')
        if _ib:
            _rm = float(rec.get('room') or 0.0)
            _ok = int(rec.get('illok') or 0)
            ientries.append('%s:[%s,%.1f,%d]' % (
                js(en), ','.join('%.1f' % float(v) for v in _ib), _rm, _ok))
    if entries:
        map_lines.append('%s:{%s}' % (ab, ','.join(entries)))
    if ientries:
        ill_lines.append('%s:{%s}' % (ab, ','.join(ientries)))
MAP_JS = ',\n'.join(map_lines)
ILL_JS = ',\n'.join(ill_lines)

# ---- R2 vector (outlined) text: source labels with no text layer -----------
# vectext entries carry a 1-based page and a source bbox. Group by 0-based
# artboard; make_jsx deletes the outlined paths in that bbox and typesets the
# translated word there, so a word drawn as curves still gets translated.
# Matching tolerances and the body-label size range are configurable (defaults
# below suit an 18pt-label deck); see config.example.json vector_text_engine.
_VTE = cfg.d.get('vector_text_engine', {})
VTCFG = {
    'ctol': float(_VTE.get('center_tol_pt', 3.0)),
    'stol': float(_VTE.get('size_tol_pt', 4.0)),
    'tlo': float(_VTE.get('template_size_min_pt', 16.5)),
    'thi': float(_VTE.get('template_size_max_pt', 19.5)),
}
_vt_by_ab = {}
for _vt in (d.get('vectext', []) or []):
    _ab = int(_vt['page']) - 1
    _bx = ','.join('%.1f' % float(x) for x in _vt['box'])
    _bg = _vt.get('bg', [])
    _bg_js = '[' + ','.join('%.0f' % float(v) for v in _bg) + ']' if _bg else 'null'
    _item = '[%s,%s,%s,%.1f,%s]' % (
        js(_vt['en']), js(_vt['val']), '[' + _bx + ']',
        float(_vt.get('size', 18.0)), _bg_js)
    _vt_by_ab.setdefault(_ab, []).append(_item)
VECTEXT_JS = ',\n'.join('%d:[%s]' % (ab, ','.join(items))
                        for ab, items in sorted(_vt_by_ab.items()))

# ---- title map --------------------------------------------------------------
tm = d.get(S['titles'], {})

# Coverage guard: every artboard normally carries exactly one title. If the
# decision file has fewer titles than artboards, some page's title never made it
# into title_map and the JSX would leave it in ENGLISH without any error (that
# is what happened to the four "Behaviors" pages of the blue book).
_abs = [int(k) for k in d.get(E, {}) if str(k).isdigit()]
_n_titles = len(d.get('titles', {}))
if 'titles' in d and _abs and _n_titles < max(_abs) + 1:
    sys.stderr.write('WARN %s %s: %d artboards but only %d titles in the decisions -- '
                     'page(s) without a title will stay in English. Re-run export_geometry.py '
                     '(it now fails on this) and check the reported artboards.\n'
                     % (lang, color, max(_abs) + 1, _n_titles))

# ---- title sizes: DERIVED from the source artwork, never hard-coded --------
# The source uses one size for its single-line titles and a smaller one for its
# two-line titles (e.g. "Colors\r(Colours)").  We read both from the source,
# pick the largest single-line size at which every translated title still fits
# the pill, and use the source's own two-line size for titles that must wrap.
def _font_file():
    # None is legal: FONTCANDS then stays empty and findFont falls back to the
    # configured name alone (logged as FONT-MISS if nothing matches).
    return cfg.resolve_font_file(lang, required=False)

def _source_title_sizes():
    p = SPANS
    if not os.path.exists(p):
        return [], []
    pages = {}
    for s in json.load(open(p, encoding='utf-8')).get(color, []):
        t = (s.get('text') or '').strip()
        if not t or t.isdigit():
            continue
        x0, y0, x1, y1 = s['bbox']
        if y1 < TITLE_BAND and s["size"] >= 14:          # title band, above the artwork
            pages.setdefault(s['page'], []).append(round(float(s['size']), 2))
    one = sorted({v[0] for v in pages.values() if len(v) == 1}, reverse=True)
    many = sorted({v[0] for v in pages.values() if len(v) >= 2}, reverse=True)
    return one, many

def _pill_size():
    """Width/height of the title oval (the artwork's own pill, not a guess)."""
    try:
        import pymupdf
        doc = pymupdf.open(src)
        best = (0.0, 0.0)
        for dr in doc[0].get_drawings():
            r = dr['rect']
            if 100 < r.width < 145 and 26 < r.height < 44 and r.y1 < 70:
                if r.width * r.height > best[0] * best[1]:
                    best = (r.width, r.height)
        doc.close()
        return best if best[0] else (119.1, 34.0)
    except Exception:
        return (119.1, 34.0)

_FCACHE = {}
def _measure(text, size):
    ff = _font_file()
    if ff not in _FCACHE:
        f = __import__('fontTools.ttLib', fromlist=['TTFont']).TTFont(ff)
        _FCACHE[ff] = (f['head'].unitsPerEm, f.getBestCmap(), f['hmtx'])
    upm, cmap, hmtx = _FCACHE[ff]
    w = 0
    for ch in str(text).replace('\r', '').replace('\n', ''):
        g = cmap.get(ord(ch)) or cmap.get(ord('n'))
        w += hmtx[g][0]
    return w * size / upm

_one, _many = _source_title_sizes()
_PW, _PH = _pill_size()
_MA = (_PW / 2.0) * GEO['emargin']
_MB = (_PH / 2.0) * GEO['emargin']

def _fits(text, size):
    """Ellipse containment (the pill is a true ellipse: 4 beziers).  At cap
    height a 119x34 oval only offers ~105pt of width, so 108pt of text would
    hang over the ends — the 'Settimane' overflow."""
    half_w = _measure(text, size) / 2.0
    half_h = GEO['capr'] * size / 2.0
    return (half_w / _MA) ** 2 + (half_h / _MB) ** 2 <= 1.0

def _fit_size(text, size):
    """Largest size <= `size` at which the text stays inside the pill."""
    s = float(size)
    while s > 6 and not _fits(text, s):
        s = round(s - 0.1, 2)
    return s

# per-title size: the source's own size for THAT title, shrunk only as far as
# the oval demands (same key -> same size on every page)
_src_size = {}
_p = SPANS
if os.path.exists(_p):
    for s in json.load(open(_p, encoding='utf-8')).get(color, []):
        t = (s.get('text') or '').strip()
        if not t or t.isdigit():
            continue
        x0, y0, x1, y1 = s['bbox']
        if y1 < TITLE_BAND and s["size"] >= 14:
            _src_size.setdefault(t, []).append(round(float(s['size']), 2))
_median = lambda a: sorted(a)[len(a) // 2]
_book_single = _median([v[0] for v in _src_size.values()]) if _src_size else 22.0
twsz = float(g.get('title_wrap_size') or (_many[0] if _many else round(_book_single * 0.7, 1)))

TITLESZ = {}
for _k, _v in tm.items():
    _first = str(_k).split('\r')[0]
    _cand = _src_size.get(_first) or _src_size.get(str(_k)) or []
    _base = _median(_cand) if _cand else _book_single
    if '\r' in str(_k) or (len(_cand) == 1 and _cand[0] < _book_single * 0.8):
        # the source title was two lines (e.g. "Colors\r(Colours)"): we output
        # ONE line, so it must take the book's single-line size, not the 15pt
        # the artwork used to squeeze two lines in.
        _base = _book_single
    _single = _fit_size(_v, _base)
    if _single < _base * 0.85 and ' ' in str(_v):
        # shrinking to fit on one line would make it unreadably small:
        # wrap onto two lines at the source's two-line size instead.
        TITLESZ[_k] = round(float(twsz), 2)
    else:
        TITLESZ[_k] = _single
TITLESZ_JS = ',\n'.join('%s:%s' % (js(k), round(float(v), 2)) for k, v in TITLESZ.items())

GEO['tsz'] = _book_single
GEO['twsz'] = twsz
GEO_JS = 'var GEO={' + ','.join('%s:%s' % (k, ('true' if v else 'false') if isinstance(v, bool) else v) for k, v in GEO.items()) + '};'
print('title size: book=%s wrap=%s pill=%.1fx%.1f' % (_book_single, twsz, _PW, _PH))
print('  per-title:', {k.replace('\r', '/') if k else k: v for k, v in TITLESZ.items()})

TITLE_JS = ',\n'.join('%s:%s' % (js(k), js(v)) for k, v in tm.items())

# ---- illustration boxes per artboard (collision guard) ---------------------
# decision JSON may carry "obstacles": {"<ab>": [[x0,y0,x1,y1], ...]}.
# Coordinates must be in the same document space as visibleBounds (top>y>bottom).
obs_src = d.get('obstacles', {}) or {}
obs_lines = []
for ab, boxes in obs_src.items():
    bb = ','.join('[' + ','.join(str(round(float(v), 3)) for v in box) + ']' for box in boxes)
    obs_lines.append('%s:[%s]' % (ab, bb))
OBS_JS = ',\n'.join(obs_lines)

TPL = r'''#target illustrator
var SRC=__SRC__, DST_AI=__DST_AI__, DST_PDF=__DST_PDF__, LOG=__LOG__;
var FONT=__FONT__, FONTCANDS=__FONTCANDS__, PDFCOMPAT=__PDFCOMPAT__, WAIT_NOTE=__WAITNOTE__;
__GEO__
/* width guard tables (self-generated from source spans + font metrics) */
var MAXW={
__MAXW__
};
var SCALE={
__SCALE__
};
/* shared geometry helpers: inkBounds / scanEllipses / fitTitle / guardObstacles */
__GEOMETRY__
var TITLE={
__TITLE__
};
/* per-title size, already fitted to the oval (source size, shrunk if needed) */
var TITLESZ={
__TITLESZ__
};
/* DEC[ab][en] = [val, cx|null, sz|null, dy, szsrc|null] */
var DEC={
__MAP__
};
/* VECTEXT[ab] = [[en,val,[x0,y0,x1,y1],size],...] -- source text that was
   outlined in the artwork; replaced by a real translated text frame. */
var VECTEXT={
__VECTEXT__
};
/* VTCFG: configurable tolerances for locating the outlined group + the body
   label used as the replacement template (see vector_text_engine in config). */
var VTCFG=__VTCFG__;
/* ILL[ab][en] = [x0,ytop,x1,ybot,room,illok] for the label's OWN illustration.
   room = how far the text may rise before touching that art (text-only lift),
   illok= 1 only for the bottom row of a card, where the art may travel too. */
var ILL={
__ILL__
};
/* OBS[ab] = illustration boxes [[x0,y0,x1,y1],...] for collision guard */
var OBS={
__OBS__
};
/* Move a label's illustration by the same dy as its wrapped text.
   Only items whose visibleBounds match the recorded box are touched, and only
   the artwork -- never a card frame -- so the grid keeps its alignment. The
   matching OBS entry is shifted too, otherwise the collision guard would
   compare the moved text against the illustration's OLD box. */
/* Built once: walking doc.pageItems per wrapped label took minutes on a
   20k-object document. One pass, then plain array math per lookup. */
var ILLIDX=null;
function illIndex(){
  if(ILLIDX) return ILLIDX;
  ILLIDX=[];
  if(!doc) return ILLIDX;
  var n=doc.pageItems.length;
  for(var i=0;i<n;i++){
    var it=doc.pageItems[i];
    try{
      if(it.typename=="TextFrame") continue;
      var b=it.visibleBounds;
      ILLIDX.push([b[0],b[1],b[2],b[3],it]);
    }catch(e){}
  }
  return ILLIDX;
}
function liftIll(ab,en,dy){
  var bb=(ILL[ab]&&ILL[ab][en])?ILL[ab][en]:null;
  if(!bb||!doc) return 0;
  var idx=illIndex(), best=null, bd=1e9;
  for(var i=0;i<idx.length;i++){
    var r=idx[i];
    var d=Math.abs(r[0]-bb[0])+Math.abs(r[1]-bb[1])+Math.abs(r[2]-bb[2])+Math.abs(r[3]-bb[3]);
    if(d<bd){bd=d;best=r;}
  }
  best=best?best[4]:null;
  if(!best||bd>8){log("ILL-MISS "+en+" d="+(bd>1e8?"?":bd.toFixed(1)));return 0;}
  try{
    best.translate(0,dy);
    var ob=OBS[ab];
    if(ob) for(var j=0;j<ob.length;j++){
      var r=ob[j];
      if(Math.abs(r[0]-bb[0])<1.5&&Math.abs(r[2]-bb[2])<1.5&&
         Math.abs(r[1]-bb[1])<1.5&&Math.abs(r[3]-bb[3])<1.5){
        r[1]+=dy; r[3]+=dy;
      }
    }
    log("ILL-LIFT "+en+" by="+dy.toFixed(2));
    return 1;
  }catch(e2){log("ILL-FAIL "+en);return 0;}
}
var lines=[], doc=null;
function log(s){lines.push(s);}
function writeLog(){var f=new File(LOG);f.open("w");f.encoding="UTF-8";f.writeln(lines.join("\n"));f.close();}
/* R1: match ANY advertised name of the configured font (family+style,
   PostScript name, localized names) -- a font can be installed yet exposed by
   Illustrator only under its PostScript name. A total miss is logged so a
   silent fallback to the source artwork's font can never ship unnoticed. */
function findFont(nm){
    var cand=(FONTCANDS&&FONTCANDS.length)?FONTCANDS:[nm];
    for(var c=0;c<cand.length;c++)
        for(var i=0;i<app.textFonts.length;i++)
            if(app.textFonts[i].name===cand[c])return app.textFonts[i];
    log("FONT-MISS wanted="+cand.join("|"));
    return null;
}
function trimKey(s){return s.replace(/^\s+|\s+$/g,"");}
/* which artboard owns this text frame (all artboards share one coordinate space) */
/* balanced two-line split for a long title (char-count proxy: no measurer here) */
function wrapTitle(v){
    var words=String(v).split(/\s+/), n=words.length;
    if(n<2) return null;
    var best=null, bestMax=1e9;
    for(var i=1;i<n;i++){
        var l1=words.slice(0,i).join(" "), l2=words.slice(i).join(" ");
        var m=Math.max(l1.length,l2.length);
        if(m<bestMax){ bestMax=m; best=[l1,l2]; }
    }
    if(!best||!best[0]||!best[1]) return null;
    return best[0]+"\r"+best[1];
}
function boardOf(d,tf){
    var g=null; try{g=tf.geometricBounds;}catch(e){return null;}
    if(!g||g.length<4)return null;
    var px=(g[0]+g[2])/2, py=(g[1]+g[3])/2;
    for(var i=0;i<d.artboards.length;i++){
        var r=d.artboards[i].artboardRect;   /* [left, top, right, bottom] */
        if(px>=r[0]&&px<=r[2]&&py<=r[1]&&py>=r[3]) return String(i);
    }
    return null;
}
function unlockAll(d){
    /* only layers + text frames; never touch hidden/visible (that surfaces
       crop marks) and never walk all 20k page objects (minutes of COM calls) */
    for(var i=0;i<d.layers.length;i++){try{d.layers[i].locked=false;}catch(e){}}
    var tf=d.textFrames; for(var j=0;j<tf.length;j++){try{if(tf[j].locked)tf[j].locked=false;}catch(e){}}
}
/* R2: source labels outlined into vector paths have no text layer, so
   export_spans cannot see them and they ship untranslated in every language.
   The outlined word is compound paths wrapped in a group whose bbox matches
   the label box; we DELETE those groups by bbox match and typeset the
   translation in their place. Boxes come from config.vector_text; tolerances
   from config.vector_text_engine. NEVER walk doc.pageItems (tens of thousands
   of objects -> Illustrator hangs); groupItems is far smaller and a handful
   of single remove() calls are cheap. */
function replaceVectorText(d){
    if(!VECTEXT) return 0;
    var done=0;
    for(var ab in VECTEXT){
        var items=VECTEXT[ab];
        if(!items) continue;
        for(var q=0;q<items.length;q++){
            var en=items[q][0], val=items[q][1], box=items[q][2], sz=items[q][3];
            var x0=box[0],y0=box[1],x1=box[2],y1=box[3];
            try{
                /* delete the outlined word: groups whose bbox matches the label
                   box, within the configured centre/size tolerances. */
                var cxT=(x0+x1)/2, cyT=(y0+y1)/2;
                var wT=Math.abs(x1-x0), hT=Math.abs(y1-y0);
                var kill=[], groups=d.groupItems;
                for(var gi=0;gi<groups.length;gi++){
                    try{
                        var gp=groups[gi], gb=gp.visibleBounds;
                        var gcx=(gb[0]+gb[2])/2, gcy=(gb[1]+gb[3])/2;
                        var gw=Math.abs(gb[2]-gb[0]), gh=Math.abs(gb[3]-gb[1]);
                        if(Math.abs(gcx-cxT)<=VTCFG.ctol && Math.abs(gcy-cyT)<=VTCFG.ctol &&
                           Math.abs(gw-wT)<=VTCFG.stol && Math.abs(gh-hT)<=VTCFG.stol)
                            kill.push(gp);
                    }catch(eG){}
                }
                for(var k=0;k<kill.length;k++){ try{kill[k].remove();}catch(eR){} }
                log("VECTEXT-DEL "+en+" groups="+kill.length);
                /* translated text: DUPLICATE an existing label frame on the same
                   board as the template (inherits font/size/alignment/colour,
                   which a bare textFrames.add() fails to render reliably), then
                   re-type the value and move it onto the covered bbox. */
                var tpl=null;
                var tfs=d.textFrames;
                for(var ti=0;ti<tfs.length;ti++){
                    try{
                        var t=tfs[ti];
                        if(boardOf(d,t)!==String(ab)) continue;
                        var tc=t.contents;
                        if(!tc||/^\d+$/.test(tc)) continue;
                        if(String(tc).indexOf('\r')>=0) continue;
                        /* skip titles: they sit in the pill with their own
                           size/anchor; a body label is the right template */
                        var tsz=18;
                        try{tsz=t.textRange.characterAttributes.size;}catch(eSz){}
                        if(tsz<VTCFG.tlo||tsz>VTCFG.thi) continue;
                        tpl=t; break;
                    }catch(eTpl){}
                }
                if(!tpl){ log("VECTEXT-NOTPL "+en+" board="+ab); continue; }
                /* Setting geometricBounds / duplicate(matrix) both fail on a
                   duplicate in this doc; position (top-left anchor) is reliable. */
                var tf2=tpl.duplicate();
                tf2.contents=val;
                try{tf2.position=[x0, y0];}catch(eP){log("VECTEXT-POS "+eP.message);}
                var fnt=findFont(FONT);
                if(fnt)try{tf2.textRange.characterAttributes.textFont=fnt;}catch(e){}
                if(sz)try{tf2.textRange.characterAttributes.size=sz;}catch(e){}
                try{tf2.textRange.paragraphAttributes.justification=
                    ((typeof Justification!=="undefined")?Justification.CENTER:2);}catch(eJ){}
                try{tf2.textFramePreferences.verticalAnchor=
                    ((typeof TextAnchor!=="undefined")?TextAnchor.MIDDLE:2);}catch(eV){}
                try{tf2.bringToFront();}catch(eZ){}
                done++;
                log("VECTEXT "+en+" -> "+val+" board="+ab+" tpl="+tpl.contents+" cover=1");
            }catch(eT){ log("VECTEXT-FAIL "+en+" "+eT.message); }
        }
    }
    return done;
}
function processDoc(d){
    var replaced=0, titles=0, tmiss=0, notrans=0;
    var ELL = GEO.title_fit ? scanEllipses(d) : [];
    for(var i=0;i<d.textFrames.length;i++){
        var tf=d.textFrames[i], key=trimKey(tf.contents);
        if(!key||/^\d+$/.test(key))continue;           /* skip page numbers */
        if(TITLE[key]!==undefined){
            var tb=null; try{tb=tf.visibleBounds;}catch(e){}
            var fnt=findFont(FONT);
            /* A source title may itself be two lines ("Colors\r(Colours)"); one
               translated line replaces the pair, so re-typeset from scratch. */
            tf.contents=TITLE[key];
            if(fnt)try{tf.textRange.characterAttributes.textFont=fnt;}catch(e){}
            /* keep the frame's centred justification (the source pills are all
               centred): a wrapped title is then centred line-by-line, not
               left-aligned inside its own box */
            /* Paragraph alignment lives on the text RANGE, not on the frame:
               setting it on tf is silently ignored, which left wrapped titles
               left-aligned inside their own box. */
            try{tf.textRange.paragraphAttributes.justification=
                 ((typeof Justification!=="undefined")?Justification.CENTER:2);}catch(eJ){}
            var ell=(GEO.title_fit&&tb)?ellipseNear(ELL,tb):null;
            var avail=ell?(ell[2]-ell[0])*GEO.emargin:(MAXW[key]||105);
            /* One size for every title in the book. Only when a single line
               cannot fit the pill does that title step down to the 2-line size. */
            var wantSz=(TITLESZ[key]||GEO.tsz), two=false;
            try{tf.textRange.characterAttributes.size=wantSz;}catch(eS0){}
            var w1=0;
            try{var b0=(GEO.ikword?(inkBounds(tf)||tf.visibleBounds):tf.visibleBounds);
                w1=b0[2]-b0[0];}catch(eW0){}
            if(w1>avail+0.2){
                var wr=wrapTitle(TITLE[key]);
                if(wr){
                    tf.contents=wr; two=true; wantSz=GEO.twsz;
                    if(fnt)try{tf.textRange.characterAttributes.textFont=fnt;}catch(e2){}
                    try{tf.textRange.characterAttributes.size=wantSz;}catch(e3){}
                    log("TITLE wrap "+key+" -> "+wr.replace(/\r/g,"|")+" sz="+wantSz);
                }
            }
            var fin=wantSz;
            if(ell){ fin=centerTitleInPill(tf,ell,wantSz,two); }
            else{
                for(var wp=0;wp<5;wp++){
                    try{
                        var wb=(GEO.ikword?(inkBounds(tf)||tf.visibleBounds):tf.visibleBounds);
                        var ww=wb[2]-wb[0];
                        if(ww>avail){ fin=Math.max(7,fin*avail/ww);
                            tf.textRange.characterAttributes.size=fin; }
                        else break;
                    }catch(eW){break;}
                }
            }
            var fb=null; try{fb=(GEO.ikword?(inkBounds(tf)||tf.visibleBounds):tf.visibleBounds);}catch(eFB){}
            log("TITLE "+key+" sz="+fin.toFixed(2)+" lines="+(two?2:1)+
                " avail="+avail.toFixed(1)+" w="+(fb?(fb[2]-fb[0]).toFixed(1):"?")+
                " cx="+(fb?((fb[0]+fb[2])/2).toFixed(1):"?")+
                " cy="+(fb?((fb[1]+fb[3])/2).toFixed(1):"?"));
            titles++; continue;
        }
        /* A frame this large in the title band that is NOT in TITLE[] means the
           geometry pass never produced a title row for its artboard (the source
           artwork drew that title differently). It would otherwise be skipped
           in total silence and stay in English. */
        var _missSz=0; try{_missSz=tf.textRange.characterAttributes.size;}catch(eM){}
        if(_missSz>=GEO.tmissz){
            tmiss++;
            var _mb=null; try{_mb=tf.visibleBounds;}catch(eN){}
            log("TITLE-MISS "+key+" sz="+_missSz.toFixed(1)+
                (_mb?(" cy="+((_mb[1]+_mb[3])/2).toFixed(1)):""));
        }
        /* Resolve the frame's OWN artboard first. cx/val are page-specific:
           the old "first artboard that has this key" scan dragged words onto
           another page's column (tree: board 3 centre -> the beach artwork). */
        var ab=boardOf(doc,tf), spec=null, scoped=false;
        var _osz=0; try{_osz=tf.textRange.characterAttributes.size;}catch(eO){}
        /* Same English string, two roles: "<key>#abbr" carries the small-form
           translation and its source size (spec[4]); pick it only for the frame
           that actually has that size (the band cell), the full-length one keeps
           the normal entry. */
        if(ab!==null&&DEC[ab]){
            var _ab=DEC[ab][key+"#abbr"];
            if(_ab&&_ab[4]!==null&&_ab[4]!==undefined&&Math.abs(_osz-_ab[4])<0.7){
                spec=_ab; scoped=true;
            }
        }
        /* R3 homograph disambiguation: a word appearing twice on one board with
           different meanings ("short" = not-tall / not-long) is emitted by the
           decision layer as "key@1","key@2" each with its own cx/val (rec[6]
           names the base key). Pick the variant nearest THIS frame's x centre,
           so the two frames get two different words instead of one drawn twice. */
        if(!spec&&ab!==null&&DEC[ab]){
            var _fx=null;
            try{var _gb=tf.geometricBounds; _fx=(_gb[0]+_gb[2])/2;}catch(eFx){}
            var _variants=[];
            for(var _k in DEC[ab]){
                var _r=DEC[ab][_k];
                if(_r[6]===key) _variants.push(_r);
            }
            if(_variants.length&&_fx!==null){
                _variants.sort(function(a,b){return Math.abs(a[1]-_fx)-Math.abs(b[1]-_fx);});
                spec=_variants[0]; scoped=true;
                log("HOMOGRAPH "+key+" -> idx="+_variants[0][7]+" val="+_variants[0][0]);
            }
        }
        if(!spec&&ab!==null&&DEC[ab]&&DEC[ab][key]!==undefined){ spec=DEC[ab][key]; scoped=true; }
        if(!spec){
            for(var a in DEC){ if(DEC[a][key]!==undefined){ spec=DEC[a][key]; ab=a; break; } }
        }
        if(!spec){
            notrans++;
            log("KEY-NOTRANS board="+(ab===null?"?":ab)+" "+key+" (left as-is)");
            continue;
        }
        var val=spec[0], cx=spec[1], sz=spec[2], dy=spec[3];
        if(!scoped){ cx=null; log("KEY-MISS board="+ab+" "+key+" (text kept in place)"); }
        var osz=_osz,fnt0=null,clr=null,just=null;
        try{clr=tf.textRange.characterAttributes.fillColor;}catch(e){}
        try{just=tf.textRange.paragraphAttributes.justification;}catch(e){}
        var ob=GEO.ikword?(inkBounds(tf)||tf.visibleBounds):tf.visibleBounds;
        var top0=ob[1], oldH=Math.abs(ob[3]-ob[1]);
        tf.contents=val;
        var tr=tf.textRange, fnt=findFont(FONT);
        if(fnt)try{tr.characterAttributes.textFont=fnt;}catch(e){}
        var finalSz=sz!==null?sz:osz;
        /* BODY TEXT IS NEVER RESIZED (hard rule): only titles may change size.
           SCALE exists for the opt-in case where a project explicitly allows
           body shrinking; default OFF, the word keeps the artwork's size and
           any overflow is reported instead of being hidden. */
        var sc=SCALE[key]||1.0;
        if(GEO.bshr&&finalSz&&sc<1.0){ finalSz=finalSz*sc; }
        if(finalSz)try{tr.characterAttributes.size=finalSz;}catch(e){}
        if(clr)try{tr.characterAttributes.fillColor=clr;}catch(e){}
        if(just!==null)try{tr.paragraphAttributes.justification=just;}catch(e){}
        /* Width guard is REPORT-ONLY unless the project opted in: shrinking a
           body word breaks the size symmetry the cards rely on. */
        var mw=MAXW[key];
        if(mw&&finalSz){
            try{
                var wb0=(GEO.ikword?(inkBounds(tf)||tf.visibleBounds):tf.visibleBounds);
                var w0=wb0[2]-wb0[0];
                if(w0>mw+1.0){
                    if(GEO.bshr){
                        var cur=finalSz;
                        for(var wp=0;wp<4;wp++){
                            var wbq=(GEO.ikword?(inkBounds(tf)||tf.visibleBounds):tf.visibleBounds);
                            var wwq=wbq[2]-wbq[0];
                            if(wwq>mw){ cur=Math.max(6,cur*mw/wwq); tr.characterAttributes.size=cur; }
                            else break;
                        }
                        finalSz=cur;
                        log("BODY-SHRUNK "+key+" -> "+finalSz.toFixed(2));
                    }else{
                        log("BODY-OVERFLOW "+key+" w="+w0.toFixed(1)+" slot="+mw.toFixed(1)+
                            " (kept "+finalSz.toFixed(2)+"pt)");
                    }
                }
            }catch(eW){}
        }
        /* two-line frames are top-anchored; use configured leading (typo
           glyph height + ~1pt) so lines neither overlap nor hit the art above */
        if(val.indexOf("\r")>=0){try{tr.characterAttributes.autoLeading=false;
            tr.characterAttributes.leading=GEO.lead*((finalSz||osz||18)/18.0);}catch(e){}}
        /* Wrapped body labels: FIRST line stays where the source line was and
           the block grows downward (that is how the artwork's own two-line
           labels are built). Only if the block would then run into the card's
           bottom edge do we lift the whole block, and never by more than half
           the added height -- that upper bound is what keeps it clear of the
           illustration sitting right above the label. */
        var wrapDy=0, illDy=0;
        /* NO LOCAL GUESS WHEN THE DECISION LAYER SPOKE. It already solved the
           lift against the card frame and the whole row, and put the amount in
           `dy`/`illdy`. Running this block as well lifted the text twice. */
        if(!spec && val.indexOf("\r")>=0){
            try{
                var nhb=(GEO.ikword?(inkBounds(tf)||tf.visibleBounds):tf.visibleBounds);
                var newH=Math.abs(nhb[3]-nhb[1]);
                var extra=Math.max(0,newH-oldH);
                var abB=null;
                try{if(ab!==null&&ab!==undefined)abB=d.artboards[Number(ab)].artboardRect[3];}catch(eA){}
                if(abB!==null&&!isNaN(abB)){
                    var need=(abB+GEO.bmargin)-(top0+dy-newH);
                    if(need>0){
                        var want=Math.min(need,extra*0.5);
                        var m=(ab!==null&&ILL[ab])?ILL[ab][key]:null;
                        var room=m?m[4]:0, illok=m?m[5]:0;
                        /* 1) text only -- plenty of labels sit well clear of
                              their picture, so this is the normal case */
                        if(want<=room+0.01){
                            wrapDy=want;
                            log("WRAP-UP "+key+" by="+wrapDy.toFixed(2)+" (text)");
                        }
                        /* 2) art travels too -- BOTTOM ROW ONLY, and only
                              because the text alone has no room left */
                        else if(illok){
                            wrapDy=want; illDy=want-room;
                            log("WRAP-UP "+key+" by="+wrapDy.toFixed(2)+
                                " (text+art "+illDy.toFixed(2)+")");
                        }
                        /* 3) no room: lift what the text can, report the rest
                              (never push the word into the artwork) */
                        else{
                            wrapDy=Math.max(0,room);
                            log("WRAP-TIGHT "+key+" room="+room.toFixed(1)+
                                " need="+need.toFixed(1));
                        }
                    }
                }
            }catch(e){}
        }
        /* Some source frames are floor-to-ceiling area text with vertical
           justification: dropping a second paragraph into one puts line 1 at
           the TOP of the frame (over the artwork) and line 2 at the bottom.
           Detect it by the ink height and shrink the text path to the real
           block height, so the lines stack tightly like every other two-line
           label. Point text ignores the assignment (caught below). */
        if(val.indexOf("\r")>=0){
            try{
                var _n=val.split("\r").length;
                var _need=GEO.lead*((finalSz||osz||18)/18.0)*_n;
                var _hb=(GEO.ikword?(inkBounds(tf)||tf.visibleBounds):tf.visibleBounds);
                var _h=Math.abs(_hb[3]-_hb[1]);
                if(_h>_need*1.30){
                    var _tp=tf.textPath;
                    _tp.height=_need+1.5;
                    log("FRAME-TIGHT "+key+" h="+_h.toFixed(1)+"->"+(_need+1.5).toFixed(1));
                }
            }catch(eT){}
        }
        try{var vb=GEO.ikword?(inkBounds(tf)||tf.visibleBounds):tf.visibleBounds;
            tf.translate(0,(top0+dy+wrapDy)-vb[1]);}catch(e){}
        /* the decision layer may have lifted this label's art already (bottom
           row only); use its figure, never the local guess, to avoid moving
           the artwork twice */
        var _specIll=(spec&&spec[5]!==null&&spec[5]!==undefined)?spec[5]:0;
        if(_specIll>0.05){liftIll(ab,key,_specIll);}
        else if(illDy>0.05){liftIll(ab,key,illDy);}
        if(cx!==null){try{var nb=GEO.ikword?(inkBounds(tf)||tf.visibleBounds):tf.visibleBounds,
            ncx=(nb[0]+nb[2])/2,dx=cx-ncx;
            if(Math.abs(dx)>0.4)tf.translate(dx,0);}catch(e){}}
        if(OBS[ab]&&OBS[ab].length)guardObstacles(tf,OBS[ab],ab+"|"+key);
        replaced++;
    }
    log("REPLACED="+replaced+" TITLES="+titles+" TITLE-MISS="+tmiss+" KEY-NOTRANS="+notrans);
    if(tmiss||notrans) log("WARNING untranslated left in place: title_miss="+tmiss+" key_notrans="+notrans);
}
try{
    app.userInteractionLevel=UserInteractionLevel.DONTDISPLAYALERTS;
    var t0=new Date().getTime();
    doc=app.open(new File(SRC));
    log("OPEN ms="+(new Date().getTime()-t0));
    unlockAll(doc);
    processDoc(doc);
    var _vtn=replaceVectorText(doc);
    log("VECTEXT done="+_vtn);
    var t2=new Date().getTime();
    var aopt=new IllustratorSaveOptions(); aopt.pdfCompatible=PDFCOMPAT;
    doc.saveAs(new File(DST_AI),aopt);
    log("SAVE_AI ms="+(new Date().getTime()-t2));
    var t3=new Date().getTime();
    var total=doc.textFrames.length, skipped=0;
    for(var i=total-1;i>=0;i--){try{doc.textFrames[i].createOutline();}catch(e){skipped++;}}
    log("OUTLINE total="+total+" skipped="+skipped);
    var t4=new Date().getTime();
    var popt=new PDFSaveOptions(); try{popt.preserveEditability=false;}catch(e){}
    /* a PDF held open by a reader makes saveAs fail SILENTLY - remove first */
    try{var pf=new File(DST_PDF); if(pf.exists)pf.remove();}catch(eP){log("WARN pdf remove: "+eP.message);}
    doc.saveAs(new File(DST_PDF),popt);
    log("SAVE_PDF ms="+(new Date().getTime()-t4));
    try{doc.close(SaveOptions.DONOTSAVECHANGES);}catch(e){log("WARN close: "+e.message);}
    doc=null;
    /* close/purge can throw AFTER a successful save - never let that flip DONE to ERROR */
    log("DONE total_ms="+(new Date().getTime()-t0));
}catch(e){
    log("ERROR: "+e.message+" (line "+e.line+")");
    try{if(doc!==null)doc.close(SaveOptions.DONOTSAVECHANGES);}catch(e2){}
}
writeLog();
'''

tpl = (TPL.replace('__SRC__', js(src.replace('\\', '/')))
          .replace('__DST_AI__', js(ai.replace('\\', '/')))
          .replace('__DST_PDF__', js(pdf.replace('\\', '/')))
          .replace('__LOG__', js(outlog.replace('\\', '/')))
          .replace('__FONT__', js(FONT))
          .replace('__FONTCANDS__', '[' + ','.join(js(x) for x in FONTCANDS) + ']')
          .replace('__PDFCOMPAT__', 'true' if cfg.jsx.get('pdf_compatible', True) else 'false')
          .replace('__WAITNOTE__', js('runner waits %s ms after close' % cfg.jsx.get('wait_ms', 2000)))
          .replace('__GEO__', GEO_JS).replace('__GEOMETRY__', GEOMETRY_JS)
          .replace('__MAXW__', MAXW_JS).replace('__SCALE__', SCALE_JS)
          .replace('__TITLE__', TITLE_JS).replace('__TITLESZ__', TITLESZ_JS)
          .replace('__MAP__', MAP_JS).replace('__ILL__', ILL_JS)
          .replace('__VECTEXT__', VECTEXT_JS)
          .replace('__VTCFG__', '{"ctol":%.2f,"stol":%.2f,"tlo":%.2f,"thi":%.2f}' % (
              VTCFG['ctol'], VTCFG['stol'], VTCFG['tlo'], VTCFG['thi']))
          .replace('__OBS__', OBS_JS))
bad = [c for c in tpl if ord(c) > 127]
assert not bad, 'non-ASCII leaked into JSX: %r' % bad[:5]
open(os.path.join(cfg.work, outjs), 'w', encoding='utf-8', newline='\n').write(tpl)
print('gen', outjs, '| decisions', sum(len(v) for v in d.get(E, {}).values()),
      '| font', FONT, '| title_fit', GEO['title_fit'], '| obstacles', len(obs_lines))
