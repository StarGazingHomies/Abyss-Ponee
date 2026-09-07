"""Render one page of a TETR.IO achievement leaderboard as a table.

Above the table sits the achievement's own summary -- medallion, name, objective,
flavour text, note chips -- followed by a strip of medal-cutoff cards and, for
COMPETITIVE achievements, a strip of leaderboard-placement cards. The layout and
every constant below follow TETRA CHANNEL's own achievement page; the authority
is ``https://ch.tetr.io/res/js/achievement.js`` and ``achievements.css``.

Rows are plain dicts produced by ``teto_commands._build_ach_row``."""
import math

import cairo

from .common import (ASSETS_DIR, BG, FLAGS_DIR, LABEL, PANEL, PANEL_L, PANEL_RAD, ROW_GAP,
                     ROW_H, STAT, STAT_DEC, STAT_SIZE, SCALE, TOP, BOTTOM, TR_INT,
                     USERNAME, _baseline, _draw_panel, _draw_parts, _draw_text, _fit_text,
                     _format_date, _format_time, _hex, _icon, _measure, _paint_icon,
                     _rounded_rect, _set_rgb, options)

ACH_DIR = ASSETS_DIR / "achievements"
FRAMES_DIR = ACH_DIR / "frames"
BADGES_DIR = ACH_DIR / "badges"
ICONS_DIR = ACH_DIR / "icons"

# ── API enums (achievements.js) ────────────────────────────────────────────────
RT_PERCENTILE, RT_ISSUE, RT_ZENITH = 1, 2, 3
RT_LAX, RT_VLAX, RT_MLAX, RT_INVARIANT = 4, 5, 6, 7
VT_NONE, VT_NUMBER, VT_TIME, VT_TIME_INV, VT_FLOOR, VT_ISSUE, VT_NUMBER_INV = range(7)
ART_UNRANKED, ART_RANKED, ART_COMPETITIVE = 0, 1, 2

MIN_SAFE_INTEGER = -9007199254740991   # the API's "no minimum" sentinel

RANK_AR = {'bronze': 1, 'silver': 2, 'gold': 3, 'platinum': 5, 'diamond': 8, 'issued': 1}
# (key, position, AR) for the placement cards, best placement first
COMPETITIVE_AR = (('t3', 3, 6), ('t5', 5, 5), ('t10', 10, 4),
                  ('t25', 25, 3), ('t50', 50, 2), ('t100', 100, 1))

# ── Colours (achievements.css) ────────────────────────────────────────────────
ACCENT = {
    'issued': _hex('#E684C4'), 'bronze': _hex('#b38070'), 'silver': _hex('#7e9ea7'),
    'gold': _hex('#e2a042'), 'platinum': _hex('#70d0a3'), 'diamond': _hex('#b590ff'),
    't100': _hex('#b38070'), 't50': _hex('#7e9ea7'), 't25': _hex('#e2a042'),
    't10': _hex('#70d0a3'), 't5': _hex('#b590ff'), 't3': _hex('#ff65a8'),
    'none': _hex('#999999'),
}
TIER_PRI = {
    'diamond': _hex('#deb3ff'), 'platinum': _hex('#a1ffe8'), 'gold': _hex('#ffe6aa'),
    'silver': _hex('#cddefd'), 'bronze': _hex('#fdccc7'), 'none': _hex('#999999'),
    'issued': _hex('#ffffff'),
}
NOTE_ACCENT = {
    'unranked': _hex('#8D7BE5'), 'competitive': _hex('#e56e32'), 'hidden': _hex('#e575a2'),
    'event': _hex('#6ab348'), 'event_past': _hex('#528d6b'), 'disabled': _hex('#964461'),
    'nolb': _hex('#528d6b'),
}
CARD_BODY = _hex('#162113')
NOTE_BG = _hex('#0F160D')
NOTE_TEXT = _hex('#cfd8cb')
WHITE = _hex('#ffffff')
ICON_INK = (0.0, 0.0, 0.0)     # the sprite sheets are white masks; TETR.IO inverts them
ICON_ALPHA = 0.8

# ── Layout ─────────────────────────────────────────────────────────────────────
HDR_PAD = 12
MEDAL_BOX = 104
MEDAL_INNER = 0.5714           # the inner sprite is 4/7 of the frame
NAME_DY, OBJECT_DY, DESC_DY, NOTES_DY = 34, 58, 78, 86
NAME_SIZE, OBJECT_SIZE, DESC_SIZE = 28, 17, 15
NOTE_H, NOTE_GAP, NOTE_SIZE, NOTE_LABEL_SIZE, NOTE_ICON = 22, 3, 12, 11, 15
NOTE_PAD = 9

STRIP_GAP = 6
CARD_GAP = 4
CARD_RAD = 3
BAR_H = 18
CUT_CARD_H = BAR_H + 44
COMP_CARD_H = BAR_H + 30
BAR_SIZE, BAR_SUFFIX_SIZE, CHIP_SIZE = 11, 10, 10
CARD_VALUE_SIZE, CARD_DEC_SIZE, CARD_SUB_SIZE = 24, 15, 11

HEADER_H = 22
HEADER_SIZE = 14
ROW_NAME_SIZE = 17
FLAG_BOX = 24
STAR_BOX = 21
ICON_GAP = 6
NAME_PAD = 6
RANK_PAD = 8

RANK_W = 72
DATE_W, VALUE_W = 200, 210
DATE_W_ISSUED = DATE_W + VALUE_W
PLAYER_W, PLAYER_W_ALLY = 400, 520

# Medal cutoff cards per rank type: (tier, suffix, cutoff key, count key).
# A None cutoff key means "the achievement's own minimum", which mapValue()
# renders as "Any" when there is no minimum. Ordered low tier -> high tier.
CUTOFF_CARDS = {
    RT_PERCENTILE: (('bronze', '(top 70%)', 'bronze', 'bronze_count'),
                    ('silver', '(top 50%)', 'silver', 'silver_count'),
                    ('gold', '(top 30%)', 'gold', 'gold_count'),
                    ('platinum', '(top 10%)', 'platinum', 'platinum_count'),
                    ('diamond', '(top 5%)', 'diamond', 'diamond_count')),
    RT_LAX: (('silver', '(any)', None, 'total'),
             ('gold', '(top 60%)', 'gold', 'gold_count'),
             ('platinum', '(top 20%)', 'platinum', 'platinum_count'),
             ('diamond', '(top 5%)', 'diamond', 'diamond_count')),
    RT_MLAX: (('silver', '(any)', None, 'total'),
              ('gold', '(top 50%)', 'gold', 'gold_count'),
              ('platinum', '(top 20%)', 'platinum', 'platinum_count'),
              ('diamond', '(top 10%)', 'diamond', 'diamond_count')),
    RT_VLAX: (('gold', '(any)', None, 'total'),
              ('platinum', '(top 50%)', 'platinum', 'platinum_count'),
              ('diamond', '(top 20%)', 'diamond', 'diamond_count')),
    RT_INVARIANT: (('bronze', '(any)', None, 'total'),
                   ('silver', '(top 70%)', 'silver', 'silver_count'),
                   ('gold', '(top 50%)', 'gold', 'gold_count'),
                   ('platinum', '(top 30%)', 'platinum', 'platinum_count'),
                   ('diamond', '(top 10%)', 'diamond', 'diamond_count')),
}
# QUICK PLAY boards use fixed floors instead of percentiles: (tier, floor, altitude)
ZENITH_CARDS = (('bronze', 3, 150), ('silver', 5, 450), ('gold', 7, 850),
                ('platinum', 9, 1350), ('diamond', 10, 1650))

NOTE_TEXTS = {
    'unranked': "This achievement does not contribute to your Achievement Rating.",
    'competitive': "This achievement grants extra Achievement Rating to those who place "
                   "in its Top 100 leaderboard.",
    'hidden': "This achievement is only visible to the worthy.",
    'disabled': "This achievement is no longer available.",
    'nolb': "TETRA CHANNEL hides this leaderboard, but the API still serves it.",
}


# ── Value formatting ───────────────────────────────────────────────────────────

def _value_parts(v, ach, big, small, colour, faded, floor=None):
    """_draw_parts chunks for an achievement value, porting mapValue() from
    ch.tetr.io/res/js/achievement.js.

    *v* of None falls back to the achievement's minimum, which is how the "any
    score qualifies" cards are drawn. *floor* is an entry's floor number (the
    ``a`` field), appended after the altitude on QUICK PLAY boards."""
    vt = ach.get('vt', VT_NUMBER)
    deci = ach.get('deci') or 0
    if v is None:
        v = ach.get('min')
    if v is None or v == MIN_SAFE_INTEGER:
        return [("Any", big, True, 0, colour)]

    if vt in (VT_NUMBER, VT_NUMBER_INV):
        n = -v if vt == VT_NUMBER_INV else v
        parts = [(f"{math.floor(n):,}", big, True, 0, colour)]
        if deci:
            parts.append((f".{math.floor((n % 1) * 10 ** deci)}", small, True, 0, faded))
        return parts

    if vt in (VT_TIME, VT_TIME_INV):
        text = _format_time(-v if vt == VT_TIME_INV else v)
        dot = text.find('.')
        return [(text[:dot], big, True, 0, colour), (text[dot:], small, True, 0, faded)]

    if vt == VT_FLOOR:
        parts = [(f"{math.floor(v):,}", big, True, 0, colour),
                 (f".{math.floor((v % 1) * 10)}", small, True, 0, faded),
                 (" m", small, False, 0, faded)]
        if floor is not None:
            parts.append((f"  F{floor:g}", small, False, 0, faded))
        return parts

    return [("-", big, False, 0, faded)]


def _notes(ach):
    """(key, label, text) for each note chip the achievement earns."""
    out = []
    art = ach.get('art', ART_RANKED)
    if art == ART_UNRANKED:
        out.append(('unranked', 'UNRANKED', NOTE_TEXTS['unranked']))
    elif art == ART_COMPETITIVE:
        out.append(('competitive', 'COMPETITIVE', NOTE_TEXTS['competitive']))
    event, past = ach.get('event'), ach.get('event_past')
    if ach.get('hidden') and not past:
        out.append(('hidden', 'HIDDEN', NOTE_TEXTS['hidden']))
    if event:
        out.append(('event_past' if past else 'event', 'EVENT',
                    f"This achievement was part of the {event} event. It is no longer available."
                    if past else f"This achievement is part of the {event} event."))
    if ach.get('disabled') and not past:
        out.append(('disabled', 'SUSPENDED', NOTE_TEXTS['disabled']))
    if ach.get('nolb'):
        out.append(('nolb', 'NO LEADERBOARD', NOTE_TEXTS['nolb']))
    return out


# ── Header ─────────────────────────────────────────────────────────────────────

def _badge_icon(key):
    name = 'event' if key == 'event_past' else ('hidden' if key == 'nolb' else key)
    return _icon(BADGES_DIR / f"{name}.png", NOTE_ICON)


def _draw_note(ctx, key, label, text, x, y, right):
    """One note bar: coloured label block, then the explanatory sentence."""
    _set_rgb(ctx, NOTE_BG)
    _rounded_rect(ctx, x, y, right - x, NOTE_H, CARD_RAD)
    ctx.fill()

    icon = _badge_icon(key)
    label_w = NOTE_PAD * 2 + _measure(ctx, label, NOTE_LABEL_SIZE, True)
    if icon is not None:
        label_w += icon[1] / SCALE + ICON_GAP
    _set_rgb(ctx, NOTE_ACCENT[key])
    _rounded_rect(ctx, x, y, label_w, NOTE_H, CARD_RAD)
    ctx.fill()

    base = y + NOTE_H / 2 + NOTE_LABEL_SIZE * 0.34
    lx = x + NOTE_PAD
    if icon is not None:
        lx += _paint_icon(ctx, icon, lx, y + NOTE_H / 2) + ICON_GAP
    _draw_text(ctx, label, lx, base, size=NOTE_LABEL_SIZE, bold=True, colour=WHITE)

    tx = x + label_w + NOTE_PAD * 1.5
    _draw_text(ctx, _fit_text(ctx, text, NOTE_SIZE, right - tx - NOTE_PAD), tx,
               y + NOTE_H / 2 + NOTE_SIZE * 0.34, size=NOTE_SIZE, colour=NOTE_TEXT)


def _draw_header(ctx, ach, cutoffs, rows, hy, hh, left, right):
    _set_rgb(ctx, PANEL)
    _rounded_rect(ctx, left, hy, right - left, hh, PANEL_RAD)
    ctx.fill()

    # Medallion: tier frame with the achievement's sprite inked into it. The site
    # picks a random tier here; pin it so identical input renders identically.
    tier = 'issued' if ach.get('rt') == RT_ISSUE else 'diamond'
    mcx, mcy = left + HDR_PAD + MEDAL_BOX / 2, hy + hh / 2
    frame = _icon(FRAMES_DIR / f"{tier}.png", MEDAL_BOX)
    if frame is not None:
        _paint_icon(ctx, frame, mcx, mcy, align="center")
    if ach.get('k') is not None:
        inner = _icon(ICONS_DIR / f"{ach['k']}.png", round(MEDAL_BOX * MEDAL_INNER),
                      recolour=ICON_INK, alpha=ICON_ALPHA)
        if inner is not None:
            _paint_icon(ctx, inner, mcx, mcy, align="center")

    tx = left + HDR_PAD + MEDAL_BOX + 16
    tr = right - HDR_PAD

    total = (cutoffs or {}).get('total')
    if total is not None:
        _draw_text(ctx, f"{total:,} HOLDERS", tr, hy + NAME_DY, size=HEADER_SIZE,
                   colour=LABEL, align="right")
    if rows:
        _draw_text(ctx, f"RANKS {rows[0]['pos']:,} - {rows[-1]['pos']:,}", tr, hy + OBJECT_DY,
                   size=HEADER_SIZE, colour=LABEL, align="right")
    text_r = tr - 150      # keep the name/objective clear of the right-hand labels

    _draw_text(ctx, _fit_text(ctx, str(ach.get('name', '')).upper(), NAME_SIZE, text_r - tx,
                              True), tx, hy + NAME_DY, size=NAME_SIZE, bold=True,
               colour=TIER_PRI[tier])
    if ach.get('object'):
        _draw_text(ctx, _fit_text(ctx, ach['object'], OBJECT_SIZE, text_r - tx), tx,
                   hy + OBJECT_DY, size=OBJECT_SIZE, colour=USERNAME)
    if ach.get('desc'):
        _draw_text(ctx, _fit_text(ctx, ach['desc'], DESC_SIZE, text_r - tx, italic=True), tx,
                   hy + DESC_DY, size=DESC_SIZE, colour=LABEL, italic=True)

    ny = hy + NOTES_DY
    for key, label, text in _notes(ach):
        _draw_note(ctx, key, label, text, tx, ny, tr)
        ny += NOTE_H + NOTE_GAP


# ── Cutoff / placement cards ───────────────────────────────────────────────────

def _draw_card_bar(ctx, key, label, suffix, ar, x, y, w):
    """The card's coloured caption: 'DIAMOND (top 5%)' plus a '+8 AR' chip."""
    accent = ACCENT[key]
    ctx.save()
    _rounded_rect(ctx, x, y, w, BAR_H * 2, CARD_RAD)   # square off the bottom edge
    ctx.clip()
    _set_rgb(ctx, accent)
    ctx.rectangle(x, y, w, BAR_H)
    ctx.fill()
    ctx.restore()

    chip = f"+{ar} AR" if ar else None
    tw = _measure(ctx, label, BAR_SIZE, True)
    if suffix:
        tw += _measure(ctx, f" {suffix}", BAR_SUFFIX_SIZE)
    chip_w = (_measure(ctx, chip, CHIP_SIZE, True) + 12) if chip else 0
    cx = x + (w - (tw + (chip_w + 5 if chip else 0))) / 2
    base = y + BAR_H / 2 + BAR_SIZE * 0.34

    cx += _draw_text(ctx, label, cx, base, size=BAR_SIZE, bold=True, colour=WHITE)
    if suffix:
        cx += _draw_text(ctx, f" {suffix}", cx, base, size=BAR_SUFFIX_SIZE, colour=WHITE)
    if chip:
        cx += 5
        _set_rgb(ctx, WHITE)
        _rounded_rect(ctx, cx, y + 2, chip_w, BAR_H - 4, 2)
        ctx.fill()
        _draw_text(ctx, chip, cx + chip_w / 2, y + BAR_H / 2 + CHIP_SIZE * 0.34,
                   size=CHIP_SIZE, bold=True, colour=accent, align="center")


def _draw_card(ctx, key, label, suffix, ar, value_parts, sub, x, y, w, h):
    _set_rgb(ctx, CARD_BODY)
    _rounded_rect(ctx, x, y, w, h, CARD_RAD)
    ctx.fill()
    _draw_card_bar(ctx, key, label, suffix, ar, x, y, w)
    _draw_parts(ctx, value_parts, x + w / 2, y + BAR_H + 26, TR_INT, align="center")
    if sub:
        _draw_text(ctx, sub, x + w / 2, y + BAR_H + 42, size=CARD_SUB_SIZE, colour=LABEL,
                   align="center")


def _cutoff_specs(ach, cutoffs):
    """(key, label, suffix, ar, value_parts, sub) per medal cutoff card."""
    rt, art = ach.get('rt'), ach.get('art', ART_RANKED)
    ranked = art != ART_UNRANKED
    big, small = CARD_VALUE_SIZE, CARD_DEC_SIZE
    out = []

    if rt == RT_ISSUE:
        total = cutoffs.get('total') or 0
        return [('issued', 'TOTAL ISSUED', '', RANK_AR['issued'] if ranked else 0,
                 [(f"{total:,}", big, True, 0, TR_INT)], None)]

    if rt == RT_ZENITH:
        for tier, floor, alt in ZENITH_CARDS:
            count = cutoffs.get(f'{tier}_count')
            out.append((tier, tier.upper(), '', RANK_AR[tier] if ranked else 0,
                        [(f"Floor {floor}", big, True, 0, TR_INT)],
                        f"{alt}m, {count:,} minted" if count is not None else f"{alt}m"))
        return out

    for tier, suffix, value_key, count_key in CUTOFF_CARDS.get(rt, ()):
        count = cutoffs.get(count_key)
        out.append((tier, tier.upper(), suffix, RANK_AR[tier] if ranked else 0,
                    _value_parts(cutoffs.get(value_key) if value_key else None, ach,
                                 big, small, TR_INT, STAT),
                    f"{count:,} minted" if count is not None else None))
    return out


def _competitive_specs(ach, top_values):
    return [(key, f"TOP {pos}", '', ar,
             _value_parts((top_values or {}).get(key), ach, CARD_VALUE_SIZE, CARD_DEC_SIZE,
                          TR_INT, STAT), None)
            for key, pos, ar in reversed(COMPETITIVE_AR)]


def _draw_strip(ctx, specs, y, h, left, right):
    n = len(specs)
    w = (right - left - CARD_GAP * (n - 1)) / n
    for i, (key, label, suffix, ar, parts, sub) in enumerate(specs):
        _draw_card(ctx, key, label, suffix, ar, parts, sub, left + i * (w + CARD_GAP), y, w, h)


# ── Table ──────────────────────────────────────────────────────────────────────

def _draw_name_run(ctx, user, nx, limit, cy, base_y, colour):
    """Username + flag + supporter star, returning the new cursor position."""
    nx += _draw_text(ctx, _fit_text(ctx, user.get('username') or '', ROW_NAME_SIZE,
                                    limit - nx, True),
                     nx, base_y, size=ROW_NAME_SIZE, bold=True, colour=colour) + ICON_GAP
    if user.get('country'):
        flag = _icon(FLAGS_DIR / f"{user['country'].upper()}.png", FLAG_BOX)
        if flag is not None:
            nx += _paint_icon(ctx, flag, nx, cy) + ICON_GAP
    if user.get('supporter'):
        star = _icon(ASSETS_DIR / "star.png", STAR_BOX)
        if star is not None:
            nx += _paint_icon(ctx, star, nx, cy) + ICON_GAP
    return nx


def _draw_player(ctx, row, ach, x, w, cy, base_y):
    limit = x + w - NAME_PAD
    nx = _draw_name_run(ctx, row, x + NAME_PAD, limit, cy, base_y, USERNAME)
    ally = row.get('ally')
    if not ally:
        return
    nx += _draw_text(ctx, " and " if ach.get('pair') else " with ", nx, base_y,
                     size=STAT_DEC, colour=LABEL)
    _draw_name_run(ctx, ally, nx, limit, cy, base_y, STAT)


def _columns(ach, rows):
    """(header, width, kind) per column. ISSUE boards have no score to show, so
    they drop VALUE and widen DATE -- matching LBS['achievements/issued']."""
    player_w = (PLAYER_W_ALLY if ach.get('pair') or any(r.get('ally') for r in rows)
                else PLAYER_W)
    cols = [('RANK', RANK_W, 'rank'), ('PLAYER', player_w, 'player')]
    if ach.get('rt') == RT_ISSUE:
        cols.append(('DATE', DATE_W_ISSUED, 'date'))
    else:
        cols.append(('DATE', DATE_W, 'date'))
        cols.append(('VALUE', VALUE_W, 'value'))
    return cols


# ── Main render ────────────────────────────────────────────────────────────────

def render(rows, output_path="achievements.png", achievement=None, cutoffs=None,
           top_values=None):
    """Render *rows* for *achievement*.

    *rows* are dicts from ``teto_commands._build_ach_row``::

        {pos, username, country, supporter, ally, v, a, ts}

    *achievement* and *cutoffs* are the ``data.achievement`` and ``data.cutoffs``
    objects from ``GET /api/achievements/{k}``. *top_values* maps the placement
    keys in :data:`COMPETITIVE_AR` to the value held at that leaderboard
    position, and is only used when the achievement is COMPETITIVE."""
    ach = achievement or {}
    cutoffs = cutoffs or {}
    s = SCALE
    n = len(rows)

    cols = _columns(ach, rows)
    width = PANEL_L + sum(c[1] for c in cols) + PANEL_L
    panel_r = width - PANEL_L

    n_notes = len(_notes(ach))
    hdr_h = max(MEDAL_BOX + 2 * HDR_PAD,
                NOTES_DY + n_notes * (NOTE_H + NOTE_GAP) + HDR_PAD)
    cut_specs = _cutoff_specs(ach, cutoffs)
    comp_specs = (_competitive_specs(ach, top_values)
                  if ach.get('art') == ART_COMPETITIVE else [])

    hdr_y = TOP
    cut_y = hdr_y + hdr_h + STRIP_GAP
    comp_y = cut_y + CUT_CARD_H + STRIP_GAP
    table_y = (comp_y + COMP_CARD_H if comp_specs else cut_y + CUT_CARD_H) + STRIP_GAP
    rows_top = table_y + HEADER_H
    height = rows_top + n * ROW_H + max(0, n - 1) * ROW_GAP + BOTTOM

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, round(width * s), round(height * s))
    ctx = cairo.Context(surface)
    ctx.scale(s, s)
    ctx.set_font_options(options)

    _set_rgb(ctx, BG)
    ctx.rectangle(0, 0, width, height)
    ctx.fill()

    _draw_header(ctx, ach, cutoffs, rows, hdr_y, hdr_h, PANEL_L, panel_r)
    if cut_specs:
        _draw_strip(ctx, cut_specs, cut_y, CUT_CARD_H, PANEL_L, panel_r)
    if comp_specs:
        _draw_strip(ctx, comp_specs, comp_y, COMP_CARD_H, PANEL_L, panel_r)

    # Column headers
    header_base = table_y + HEADER_H / 2 + HEADER_SIZE * 0.34
    x = PANEL_L
    for text, w, kind in cols:
        if text:
            if kind == 'player':
                _draw_text(ctx, text, x + NAME_PAD, header_base, size=HEADER_SIZE, colour=LABEL)
            elif kind == 'rank':
                _draw_text(ctx, text, x + w - RANK_PAD, header_base, size=HEADER_SIZE,
                           colour=LABEL, align="right")
            else:
                _draw_text(ctx, text, x + w / 2, header_base, size=HEADER_SIZE, colour=LABEL,
                           align="center")
        x += w

    for i, r in enumerate(rows):
        y = rows_top + i * (ROW_H + ROW_GAP)
        cy = y + ROW_H / 2
        base_y = _baseline(cy)
        _draw_panel(ctx, y, PANEL_L, panel_r)

        x = PANEL_L
        for _text, w, kind in cols:
            cx = x + w / 2
            if kind == 'rank':
                _draw_text(ctx, f"{r['pos']:,}", x + w - RANK_PAD, base_y, size=STAT_SIZE,
                           bold=True, colour=STAT, align="right")
            elif kind == 'player':
                _draw_player(ctx, r, ach, x, w, cy, base_y)
            elif kind == 'date':
                ts = r.get('ts')
                _draw_text(ctx, _format_date(ts) if ts else "-", cx, base_y, size=STAT_SIZE,
                           colour=STAT, align="center")
            elif kind == 'value':
                _draw_parts(ctx, _value_parts(r.get('v'), ach, STAT_SIZE, STAT_DEC, TR_INT,
                                              LABEL, floor=r.get('a')),
                            cx, base_y, TR_INT, align="center")
            x += w

    surface.write_to_png(output_path)


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json
    import sys

    sys.path.insert(0, str(ASSETS_DIR.parent))
    from teto_commands import _ach_rows          # noqa: E402  (the real row numbering)

    ap = argparse.ArgumentParser(description="Render an /api/achievements/{k} response.")
    ap.add_argument('--input', '-i', default='ach_sample_18.json')
    ap.add_argument('--output', '-o', default='ach_output.png')
    ap.add_argument('--count', '-c', type=int, default=12, help="rows to draw")
    args = ap.parse_args()

    with open(args.input, encoding='utf-8') as f:
        payload = json.load(f)
    data = payload.get('data', payload)
    ach, cuts, lb = data['achievement'], data['cutoffs'], data['leaderboard']

    rows, _state = _ach_rows(lb, ach)
    tops = {key: lb[pos - 1]['v'] for key, pos, _ar in COMPETITIVE_AR if len(lb) >= pos}
    render(rows[:args.count], args.output, achievement=ach, cutoffs=cuts, top_values=tops)
    print(f"wrote {args.output} ({len(rows[:args.count])} rows)")
