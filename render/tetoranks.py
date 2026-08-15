import math
import pathlib

import cairo
import numpy as np
from PIL import Image

BG           = (0.059, 0.086, 0.051)
PANEL        = (0.086, 0.129, 0.075)
USERNAME     = (0.976, 0.980, 0.961)
STAT         = (0.612, 0.792, 0.584)
LABEL        = (0.361, 0.518, 0.337)
TR_INT       = (0.886, 0.988, 0.871)

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

ASSETS_DIR = pathlib.Path(__file__).parent.parent / "assets"
RANKS_DIR = ASSETS_DIR / "ranks"

# ── Layout (base units == reference pixels; multiplied by SCALE) ─────────────
SCALE = 2
W_VERBOSE = 1495
W_COMPACT = 704
ROW_H = 35
ROW_GAP = 4
TOP = 9
BOTTOM = 6

PANEL_L = 4
PANEL_RAD = 4

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
STAT_SIZE = 17
STAT_DEC = 11
SUB_DY = 0                    # decimal part shares the integer baseline

FONT_FACE = "HUN"

options = cairo.FontOptions()
options.set_antialias(cairo.ANTIALIAS_GRAY)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _set_rgb(ctx, col, alpha=1.0):
    ctx.set_source_rgba(*col, alpha)


def _rounded_rect(ctx, x, y, w, h, r):
    ctx.new_sub_path()
    ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    ctx.arc(x + w - r, y + r, r, 1.5 * math.pi, 2 * math.pi)
    ctx.arc(x + w - r, y + h - r, r, 0, 0.5 * math.pi)
    ctx.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi)
    ctx.close_path()


def _font(ctx, size, bold=False, face=FONT_FACE):
    ctx.select_font_face(face,
                         cairo.FONT_SLANT_NORMAL,
                         cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(size)


def _draw_text(ctx, text, x, y, size, bold=False, colour=USERNAME, align="left"):
    _font(ctx, size, bold)
    ext = ctx.text_extents(text)
    if align == "right":
        x -= ext.x_advance
    elif align == "center":
        x -= ext.x_advance / 2
    _set_rgb(ctx, colour)
    ctx.move_to(x, y)
    ctx.show_text(text)
    return ext.x_advance


def _draw_parts(ctx, parts, x, y, colour, align="center"):
    """Draw a sequence of (text, size, bold, dy[, colour]) chunks laid out
    left-to-right on a shared baseline, matching tetra_recent.py."""
    total = 0.0
    for part in parts:
        _font(ctx, part[1], part[2])
        total += ctx.text_extents(part[0]).x_advance
    if align == "right":
        cx = x - total
    elif align == "center":
        cx = x - total / 2
    else:
        cx = x
    for part in parts:
        text, size, bold, dy = part[0], part[1], part[2], part[3]
        _font(ctx, size, bold)
        _set_rgb(ctx, part[4] if len(part) > 4 else colour)
        ctx.move_to(cx, y + dy)
        ctx.show_text(text)
        cx += ctx.text_extents(text).x_advance


def _split_decimal(value, group=False):
    """'98.03' -> ('98', '.03'); *group* adds thousands separators."""
    s = f"{value:,.2f}" if group else f"{value:.2f}"
    dot = s.find('.')
    return s[:dot], s[dot:]


def _rank_colour(rank):
    return RANK_COLOURS.get(rank, USERNAME)


def _load_surface(path, box):
    """Load a PNG and fit it into a *box* x *box* square, returning
    (cairo surface, draw_w, draw_h). Returns None if the file is missing."""
    p = pathlib.Path(path)
    if not p.exists():
        return None
    img = Image.open(p).convert("RGBA")
    ow, oh = img.size
    scale = box / max(ow, oh)
    dw, dh = max(1, round(ow * scale)), max(1, round(oh * scale))

    arr = np.array(img.resize((dw, dh), Image.LANCZOS), dtype=np.float32) / 255.0
    alpha = arr[:, :, 3:4]
    arr[:, :, :3] *= alpha                       # premultiply for Cairo
    out = (arr * 255).clip(0, 255).astype(np.uint8)
    out[:, :, :3] = np.minimum(out[:, :, :3], out[:, :, 3:4])  # clamp RGB <= A
    bgra = out[:, :, [2, 1, 0, 3]]
    surf = cairo.ImageSurface.create_for_data(bytearray(bgra.tobytes()),
                                              cairo.FORMAT_ARGB32, dw, dh)
    return surf, dw, dh


_badges = {}


def _rank_badge(rank):
    """Cached rank badge, rasterised at device resolution."""
    key = rank.lower()
    if key not in _badges:
        _badges[key] = _load_surface(RANKS_DIR / f"{key}.png", BADGE_BOX * SCALE)
    return _badges[key]


def _paint_badge(ctx, loaded, cx, cy):
    """Blit a badge centred on (cx, cy), bypassing the context scale so the
    image is drawn at its native device resolution."""
    surf, dw, dh = loaded
    ctx.save()
    ctx.scale(1 / SCALE, 1 / SCALE)
    ctx.set_source_surface(surf, round(cx * SCALE - dw / 2), round(cy * SCALE - dh / 2))
    ctx.paint()
    ctx.restore()


def _draw_value(ctx, value, cx, base_y, colour=STAT):
    """Draw a float as integer + small decimal, or '-' if missing."""
    if value is None:
        _draw_text(ctx, "-", cx, base_y, size=STAT_SIZE, colour=colour, align="center")
        return
    intp, decp = _split_decimal(value)
    _draw_parts(ctx, [(intp, STAT_SIZE, False, 0), (decp, STAT_DEC, False, SUB_DY)],
                cx, base_y, colour, align="center")


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
        base_y = cy + STAT_SIZE * 0.34

        _set_rgb(ctx, PANEL)
        _rounded_rect(ctx, PANEL_L, y, panel_r - PANEL_L, ROW_H, PANEL_RAD)
        ctx.fill()

        badge = _rank_badge(r['rank'])
        if badge is not None:
            _paint_badge(ctx, badge, BADGE_CX, cy)
        else:
            _draw_text(ctx, r['rank'], BADGE_CX, base_y, size=RANK_SIZE, bold=True,
                       colour=_rank_colour(r['rank']), align="center")

        _draw_tr(ctx, r['tr'], col['tr'], base_y)

        count = r['count']
        _draw_text(ctx, f"{count:,}" if count is not None else "-",
                   col['count'], base_y, size=STAT_SIZE, colour=STAT, align="center")

        _draw_value(ctx, r['apm'], col['apm'], base_y)
        _draw_value(ctx, r['pps'], col['pps'], base_y)
        _draw_value(ctx, r['vs'], col['vs'], base_y)

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
