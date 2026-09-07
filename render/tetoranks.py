import cairo

from .common import (BG, LABEL, PANEL_L, RANKS_DIR, ROW_GAP, ROW_H, SCALE, STAT, STAT_DEC,
                     STAT_SIZE, SUB_DY, TOP, BOTTOM, TR_INT, USERNAME, _baseline, _draw_panel,
                     _draw_parts, _draw_text, _draw_value, _icon, _paint_icon, _set_rgb,
                     _split_decimal, options)

# TETR.IO rank tier colours (fallback letter colour when the badge is missing).
RANK_COLOURS = {
    'X+':   (0.655, 0.388, 0.917),
    'X':    (0.72 , 0.42 , 1.00 ),
    'U':    (1.00 , 0.35 , 0.62 ),
    'SS':   (0.86 , 0.55 , 0.12 ),
    'S+':   (1.00 , 0.80 , 0.20 ),
    'S':    (1.00 , 0.80 , 0.20 ),
    'S-':   (1.00 , 0.80 , 0.20 ),
    'A+':   (0.25 , 0.85 , 0.35 ),
    'A':    (0.25 , 0.85 , 0.35 ),
    'A-':   (0.25 , 0.85 , 0.35 ),
    'B+':   (0.20 , 0.75 , 0.85 ),
    'B':    (0.20 , 0.75 , 0.85 ),
    'B-':   (0.20 , 0.75 , 0.85 ),
    'C+':   (0.30 , 0.55 , 1.00 ),
    'C':    (0.30 , 0.55 , 1.00 ),
    'C-':   (0.30 , 0.55 , 1.00 ),
    'D+':   (1.00 , 0.55 , 0.25 ),
    'D':    (1.00 , 0.55 , 0.25 ),
}

# ── Layout specific to this board (see render.common for the shared metrics) ──
W_VERBOSE = 1495
W_COMPACT = 704

HEADER_H = 24
HEADER_GAP = 4
FOOTER_H = 24
FOOTER_GAP = 6

BADGE_L = 28
BADGE_BOX = 24
BADGE_CX = BADGE_L + BADGE_BOX / 2

# Column x positions: text centres, except the left-aligned Actual TR and the
# right-aligned Inflated column. The compact layout drops Position, Target TR
# and the deflation/inflation figures, closing up the gaps they leave.
COLUMNS_VERBOSE = {
    'tr': 78, 'count': 279, 'pos': 467, 'apm': 641, 'pps': 739, 'vs': 831,
    'targettr': 953, 'deflated': 1138, 'inflated': 1467,
}
COLUMNS_COMPACT = {
    'tr': 78, 'count': 279, 'apm': 460, 'pps': 558, 'vs': 650,
}

HEADERS = (
    ('tr',       "Actual TR", "left"),
    ('count',    "Players",   "center"),
    ('pos',      "Position",  "center"),
    ('apm',      "APM",       "center"),
    ('pps',      "PPS",       "center"),
    ('vs',       "VS",        "center"),
    ('targettr', "Target TR", "center"),
    ('deflated', "Deflated",  "center"),
    ('inflated', "Inflated",  "right"),
)

RANK_SIZE = 17
HEADER_SIZE = 15


# ── Helpers ─────────────────────────────────────────────────────────────

def _rank_colour(rank):
    return RANK_COLOURS.get(rank, USERNAME)


def _draw_tr(ctx, tr, x, base_y, align="left"):
    """Draw the actual TR boundary as integer + small decimal."""
    if tr is None:
        _draw_text(ctx, "-", x, base_y, size=STAT_SIZE, colour=TR_INT, align=align)
        return
    intp, decp = _split_decimal(tr, group=True)
    _draw_parts(ctx, [(intp, STAT_SIZE, True, 0), (decp, STAT_DEC, True, SUB_DY)],
                x, base_y, TR_INT, align=align)


def _draw_drift(ctx, drift, x, base_y, align="center"):
    """Draw a deflation/inflation figure as '284.85 TR (16.49%)', or 'N/A'."""
    if not drift:
        _draw_text(ctx, "N/A", x, base_y, size=STAT_SIZE, colour=LABEL, align=align)
        return
    tr, pct = drift
    intp, decp = _split_decimal(tr, group=True)
    parts = [(intp, STAT_SIZE, False, 0, STAT),
             (decp, STAT_DEC, False, SUB_DY, LABEL),
             (" TR", STAT_SIZE, False, 0, LABEL)]
    if pct is not None:
        pint, pdec = _split_decimal(pct)
        parts += [(" (", STAT_SIZE, False, 0, LABEL),
                  (pint, STAT_SIZE, False, 0, LABEL),
                  (pdec, STAT_DEC, False, SUB_DY, LABEL),
                  ("%)", STAT_SIZE, False, 0, LABEL)]
    _draw_parts(ctx, parts, x, base_y, STAT, align=align)


# ── Data parsing ────────────────────────────────────────────────────────────────

def _drift(high, low, span):
    """(TR gap, gap as a % of *span*) when *high* sits above *low*, else None."""
    if high is None or low is None:
        return None
    delta = high - low
    if delta <= 0:
        return None
    return delta, (delta / span * 100) if span else None


def _annotate(ranks):
    """Attach deflation/inflation figures to each rank.

    A rank's TR band runs from its own boundary up to the next rank's. The band
    is *deflated* when its floor sits below the TR that rank is meant to start
    at, and *inflated* when its ceiling — the next rank's boundary — sits above
    the TR that rank is meant to start at. Both are also given as a share of
    the band's actual width."""
    for i, r in enumerate(ranks):
        above = ranks[i - 1] if i else None
        span = None
        if above is not None and above['tr'] is not None and r['tr'] is not None:
            span = above['tr'] - r['tr']
        r['deflated'] = _drift(r['targettr'], r['tr'], span)
        r['inflated'] = _drift(above['tr'], above['targettr'], span) if above else None


def parse(data_obj):
    """Turn the Labs League Ranks data object into (total, rank list).

    *data_obj* is the inner ``data.data`` object: a ``total`` field plus one
    key per rank. Ranks are returned sorted by their leaderboard position
    (highest rank first)."""
    total = data_obj.get('total')
    ranks = []
    for key, meta in data_obj.items():
        if key == 'total' or not isinstance(meta, dict):
            continue
        ranks.append({
            'rank': key.upper(),
            'pos': meta.get('pos'),
            'percentile': meta.get('percentile'),
            'tr': meta.get('tr'),
            'targettr': meta.get('targettr'),
            'count': meta.get('count'),
            'apm': meta.get('apm'),
            'pps': meta.get('pps'),
            'vs': meta.get('vs'),
        })
    ranks.sort(key=lambda r: r['pos'] if r['pos'] is not None else float('inf'))
    _annotate(ranks)
    return total, ranks


# ── Main render ─────────────────────────────────────────────────────────────────

def render(ranks, output_path="tetoranks.png", total=None, verbose=False):
    """Render one row per rank.

    *ranks* is a list of dicts as produced by :func:`parse`. *verbose* adds the
    Position, Target TR, Deflated and Inflated columns."""
    s = SCALE
    n = len(ranks)
    col = COLUMNS_VERBOSE if verbose else COLUMNS_COMPACT
    width = W_VERBOSE if verbose else W_COMPACT
    panel_r = width - PANEL_L
    rows_top = TOP + HEADER_H + HEADER_GAP
    height = rows_top + n * ROW_H + (n - 1) * ROW_GAP
    if total is not None:
        height += FOOTER_GAP + FOOTER_H
    height += BOTTOM

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width * s, height * s)
    ctx = cairo.Context(surface)
    ctx.scale(s, s)
    ctx.set_font_options(options)

    _set_rgb(ctx, BG)
    ctx.rectangle(0, 0, width, height)
    ctx.fill()

    # Column headers
    header_base = TOP + HEADER_SIZE * 0.9
    for key, text, align in HEADERS:
        if key not in col:
            continue
        _draw_text(ctx, text, col[key], header_base, size=HEADER_SIZE, bold=key == 'tr',
                   colour=STAT if key == 'tr' else LABEL, align=align)

    for i, r in enumerate(ranks):
        y = rows_top + i * (ROW_H + ROW_GAP)
        cy = y + ROW_H / 2
        base_y = _baseline(cy)

        _draw_panel(ctx, y, PANEL_L, panel_r)

        badge = _icon(RANKS_DIR / f"{r['rank'].lower()}.png", BADGE_BOX)
        if badge is not None:
            _paint_icon(ctx, badge, BADGE_CX, cy, align="center")
        else:
            _draw_text(ctx, r['rank'], BADGE_CX, base_y, size=RANK_SIZE, bold=True,
                       colour=_rank_colour(r['rank']), align="center")

        _draw_tr(ctx, r['tr'], col['tr'], base_y)

        count = r['count']
        _draw_text(ctx, f"{count:,}" if count is not None else "-",
                   col['count'], base_y, size=STAT_SIZE, colour=STAT, align="center")

        _draw_value(ctx, r['apm'], col['apm'], base_y, STAT)
        _draw_value(ctx, r['pps'], col['pps'], base_y, STAT)
        _draw_value(ctx, r['vs'], col['vs'], base_y, STAT)

        if not verbose:
            continue

        pos, pct = r['pos'], r.get('percentile')
        parts = [(f"#{pos:,}" if pos is not None else "-", STAT_SIZE, False, 0, STAT)]
        if pct is not None:
            parts.append((f" (top {pct * 100:g}%)", STAT_SIZE, False, 0, LABEL))
        _draw_parts(ctx, parts, col['pos'], base_y, STAT, align="center")

        target = r.get('targettr')
        _draw_text(ctx, f"{target:,.0f}" if target is not None else "-",
                   col['targettr'], base_y, size=STAT_SIZE, colour=STAT, align="center")

        _draw_drift(ctx, r.get('deflated'), col['deflated'], base_y)
        _draw_drift(ctx, r.get('inflated'), col['inflated'], base_y, align="right")

    if total is not None:
        footer_y = rows_top + n * ROW_H + (n - 1) * ROW_GAP + FOOTER_GAP
        footer_cy = footer_y + FOOTER_H / 2
        _draw_text(ctx, f"TOTAL PLAYERS: {total:,}", width / 2, footer_cy + HEADER_SIZE * 0.34,
                   size=HEADER_SIZE, colour=LABEL, align="center")

    surface.write_to_png(output_path)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Render TETRA LEAGUE ranks from JSON")
    parser.add_argument("--input", "-i", default="../league_ranks_sample.json")
    parser.add_argument("--output", "-o", default="tetoranks.png")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        obj = json.load(f)

    # Accept either a full API response, {"data": {...}}, or the raw ranks object.
    data = obj.get("data", obj)
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict) \
            and "total" in data["data"]:
        data = data["data"]
    total, ranks = parse(data)
    render(ranks, args.output, total=total, verbose=args.verbose)
    print(f"Rendered {len(ranks)} ranks to {args.output}")
