# -*- coding: utf-8 -*-
"""Generic geometry loader for decision-driven card translation.

Replaces the project-bound geomcolor.py. Reads the TSVs produced by
export_geometry.py and groups page objects per artboard into:
    labels / illus / frames / pageno / title
plus a `frame_inner` (precise inner border) and each label's `own_illus`.

Box format is [x0, ytop, x1, ybottom] in Illustrator coords (Y grows up).
All paths come from pipeline.json (files.geom / files.geom_inner), so this
module carries no project-specific path, colour, or page-count constants.
"""
import os


def _rows(path):
    if not os.path.exists(path):
        return
    for ln in open(path, encoding='utf-8'):
        p = ln.rstrip('\n').split('\t')
        if len(p) < 9 or p[0] == 'ERROR':
            continue
        try:
            ab = int(p[0])
        except ValueError:
            continue
        yield p, ab


class GeomLib:
    def __init__(self, cfg):
        self.cfg = cfg
        self.work = cfg.work
        g = cfg.d.get('geometry_export', {})
        # A label's "own" illustration is normally the one ABOVE it (Y-up,
        # larger cy). New layouts that put art below can flip this.
        self.illus_above = bool(g.get('illus_above', True))
        self.own_gap = float(g.get('own_illus_cy_gap', 20.0))

    def geom_path(self, color):
        p = self.cfg.f.get('geom')
        if p:
            return os.path.join(self.work, self.cfg.fmt('geom', color_code=color))
        return os.path.join(self.work, 'geom_%s.tsv' % color)

    def inner_path(self, color):
        p = self.cfg.f.get('geom_inner')
        if p:
            return os.path.join(self.work, self.cfg.fmt('geom_inner', color_code=color))
        return os.path.join(self.work, 'inner_%s.tsv' % color)

    def ink_path(self, color):
        p = self.cfg.f.get('ink')
        if p:
            return os.path.join(self.work, self.cfg.fmt('ink', color_code=color))
        return os.path.join(self.work, 'ink_%s.tsv' % color)

    def _inner(self, color):
        m = {}
        for p, ab in _rows(self.inner_path(color)):
            # inner row: ab cx cy x0 y0 x1 y1 w h  (9 fields, no kind/txt)
            if ab in m or len(p) < 8:
                continue
            try:
                m[ab] = [float(p[3]), float(p[4]), float(p[5]), float(p[6])]
            except ValueError:
                continue
        return m

    def parse(self, color):
        inner = self._inner(color)
        pages = {}
        for p, ab in _rows(self.geom_path(color)):
            kind = p[1]
            try:
                cx, cy = float(p[2]), float(p[3])
                box = [float(p[4]), float(p[5]), float(p[6]), float(p[7])]
            except ValueError:
                continue
            kids = int(p[8]) if p[8].lstrip('-').isdigit() else 0
            txt = p[9] if len(p) > 9 else ''
            pg = pages.setdefault(ab, {'labels': [], 'illus': [], 'frames': [],
                                       'pageno': None, 'title': None})
            if kind == 'L':
                # an empty label group (TextFrame with no characters) is not a
                # translatable word: keeping it creates a "" key that matches
                # nothing, shows as a blank row in the ledger and makes the
                # REPLACED count disagree with the decision count
                if not txt.strip():
                    continue
                pg['labels'].append({'cx': cx, 'cy': cy, 'box': box,
                                     'en': txt.replace('|', '\r')})
            elif kind == 'I':
                pg['illus'].append({'cx': cx, 'cy': cy, 'box': box,
                                    'w': box[2] - box[0], 'h': box[1] - box[3]})
            elif kind == 'F':
                pg['frames'].append({'cx': cx, 'cy': cy, 'box': box,
                                     'w': box[2] - box[0], 'h': box[1] - box[3],
                                     'kids': kids})
            elif kind == 'P':
                pg['pageno'] = {'cx': cx, 'cy': cy, 'box': box, 'txt': txt}
            elif kind == 'T':
                pg['title'] = {'cx': cx, 'cy': cy, 'box': box,
                               'en': txt.replace('|', '\r') if txt else ''}

        for ab, pg in pages.items():
            fs = sorted(pg['frames'], key=lambda f: f['w'] * f['h'])
            pg['frame_outer'] = fs[-1]['box'] if fs else None
            # NO fallback to the smallest frame: an inner TSV that is missing (or
            # classifies nothing on this page) means the card edges are unknown,
            # and every in-card shift / wrap decision would be solved against
            # the wrong rectangle without a single warning. Leaving it None makes
            # preflight.py and build_decisions.py REFUSE loudly instead.
            pg['frame_inner'] = inner.get(ab)
            for l in pg['labels']:
                # link the nearest illustration in the expected vertical
                # direction; score blends horizontal distance with vertical.
                cand = [i for i in pg['illus']
                        if (i['cy'] > l['cy'] + self.own_gap) if self.illus_above]
                if not self.illus_above:
                    cand = [i for i in pg['illus']
                            if i['cy'] < l['cy'] - self.own_gap]
                best, bs = None, None
                for i in cand:
                    dx = abs(i['cx'] - l['cx'])
                    dy = abs(i['cy'] - l['cy'])
                    score = dx + dy * 0.25
                    if bs is None or score < bs:
                        bs, best = score, i
                l['own_illus'] = best
            self._attach_facts(pg)
        return pages

    # ------------------------------------------------------------------
    # Facts: everything the decision layer is allowed to know about a page.
    # It used to re-derive these by walking objects with sign-sensitive math
    # in two different places (and got the Y direction wrong once), so they
    # are computed exactly once, here, and consumed verbatim downstream.
    # ------------------------------------------------------------------
    def _attach_facts(self, pg):
        lay = (self.cfg.d.get('layout') or {})
        ogap = float(lay.get('obstacle_gap_pt', 2.0))
        brow = float(lay.get('bottom_row_pt', 60.0))
        rowtol = float(lay.get('row_tol_pt', 16.0))
        labs = pg.get('labels') or []
        if not labs:
            return
        # group labels into rows by their centre y (the cards are grids, so
        # labels of one row share a baseline within a couple of points)
        order = sorted(labs, key=lambda l: -l['cy'])
        rid, prev = 0, None
        for l in order:
            if prev is not None and (prev - l['cy']) > rowtol:
                rid += 1
            l['row'] = rid
            prev = l['cy']
        pg['rows'] = {}
        for l in labs:
            pg['rows'].setdefault(l['row'], []).append(l)
        fyb = pg['frame_inner'][3] if pg.get('frame_inner') else None
        for l in labs:
            own = l.get('own_illus')
            f = {'row': l['row'], 'ill': None, 'room': 0.0, 'illok': 0, 'ceil': None}
            if own is not None:
                ob = own['box']
                f['ill'] = [round(v, 1) for v in ob]
                # Y grows up: clearance between the art's BOTTOM and the text's
                # TOP is (art_bottom - text_top), positive when there is a gap.
                f['room'] = round(max(0.0, ob[3] - l['box'][1] - ogap), 1)
                if fyb is not None:
                    f['illok'] = 1 if (l['box'][3] - fyb) < brow else 0
                # free space above the art, ignoring the whole own row (the row
                # travels together, so its other cells are not obstacles)
                mates = set(id(x) for x in pg['rows'][l['row']])
                ceil_y = None
                for ii in list(pg['illus']) + list(pg['labels']):
                    if id(ii) in mates:
                        continue
                    b = ii['box']
                    if b[3] <= ob[1] + 0.5:          # its bottom is not above us
                        continue
                    if not (b[2] > ob[0] - 8 and b[0] < ob[2] + 8):
                        continue
                    ceil_y = b[3] if ceil_y is None else min(ceil_y, b[3])
                if ceil_y is not None:
                    f['ceil'] = round(ceil_y - ob[1] - ogap, 1)
                else:
                    f['ceil'] = round(float(lay.get('row_lift_headroom_pt', 60.0)), 1)
            else:
                # No illustration of its own (a colour swatch, a bare shape, a
                # calendar cell). The label may still rise into the free space
                # above it, so measure that instead of pretending there is none.
                ceil_y = None
                for ii in pg['illus'] + pg['labels']:
                    if ii is l:
                        continue
                    b = ii['box']
                    if b[3] <= l['box'][1] + 0.5:
                        continue
                    if not (b[2] > l['box'][0] - 8 and b[0] < l['box'][2] + 8):
                        continue
                    ceil_y = b[3] if ceil_y is None else min(ceil_y, b[3])
                if ceil_y is not None:
                    f['room'] = round(max(0.0, ceil_y - l['box'][1] - ogap), 1)
                if fyb is not None:
                    f['illok'] = 1 if (l['box'][3] - fyb) < brow else 0
            l['facts'] = f

    def ink_boxes(self, color):
        """(ab, round(cx), round(cy)) -> [x0, ytop, x1, ybottom] real ink box."""
        out = {}
        for p, ab in _rows(self.ink_path(color)):
            if len(p) < 7:
                continue
            try:
                out[(ab, round(float(p[1])), round(float(p[2])))] = [float(x) for x in p[3:7]]
            except ValueError:
                continue
        return out
