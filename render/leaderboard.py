"""Render one page of a TETR.IO leaderboard (user or record boards) as a table.

Rows are plain dicts produced by ``teto_commands._build_lb_row``; the set of
columns drawn depends on *board* (see :data:`COLUMNS`)."""
import cairo

from .common import (ASSETS_DIR, BG, FLAGS_DIR, LABEL, PANEL_L, RANKS_DIR, ROW_GAP, ROW_H,
                     SCALE, STAT, STAT_DEC, STAT_SIZE, SUB_DY, TOP, BOTTOM, TR_INT, USERNAME,
                     _baseline, _draw_panel, _draw_parts, _draw_text, _draw_value,
                     _format_date, _format_time, _icon, _paint_icon, _set_rgb, _split_decimal,
                     options)

MODS_DIR = ASSETS_DIR / "zenith_mods"

# ── Layout specific to this board (see render.common for the shared metrics) ──
TITLE_H = 26
TITLE_GAP = 2
HEADER_H = 22
HEADER_GAP = 4

TITLE_SIZE = 18
HEADER_SIZE = 14
NAME_SIZE = 17

BADGE_BOX = 24
FLAG_BOX = 24
STAR_BOX = 21
MOD_BOX = 22
ICON_GAP = 6
NAME_PAD = 6                  # left padding inside the name column
RANK_PAD = 8                  # right padding inside the rank column

BOARD_TITLES = {
    'league':   'TETRA LEAGUE',
    'xp':       'XP',
    'ar':       'ACHIEVEMENT RATING',
    '40l':      '40 LINES',
    'blitz':    'BLITZ',
    'zenith':   'QUICK PLAY',
    'zenithex': 'QUICK PLAY EXPERT',
}

# Column spec: (row key, header text, width, kind). Kinds:
#   rank      rank number, right-aligned
#   badge     TETRA LEAGUE rank badge
#   name      username + flag + supporter star, left-aligned
#   value     float as integer + small decimals
#   tr        like value but bright and thousands-grouped
#   int       integer with thousands separators ("-" if missing/negative)
#   time      milliseconds as [h:]m:ss.mmm
#   altitude  metres with 1 decimal and a small "m"
#   date      ISO timestamp as YYYY-MM-DD
#   mods      QUICK PLAY mod icons
#   finesse   (faults, accuracy %) as "0F (100%)" with the accuracy faded
#   glicko    (glicko, rd) as "4221±70"
#   games     (won, played) as "811/1,064 (76.22%)" with the percentage faded
_RANK = ('rank', 'RANK', 70, 'rank')
_BADGE = ('league_rank', '', 36, 'badge')
_NAME = ('username', 'PLAYER', 290, 'name')
_DATE = ('ts', 'DATE', 110, 'date')
_FINESSE = ('finesse', 'FINESSE', 130, 'finesse')

COLUMNS = {
    'league': [_RANK, _BADGE, _NAME,
               ('tr', 'TR', 120, 'tr'), ('glicko', 'GLICKO', 120, 'glicko'),
               ('apm', 'APM', 80, 'value'), ('pps', 'PPS', 70, 'value'), ('vs', 'VS', 80, 'value'),
               ('games', 'GAMES', 200, 'games')],
    'xp':     [_RANK, _NAME,
               ('xp', 'XP', 150, 'int'), ('level', 'LEVEL', 80, 'int'),
               ('games', 'GAMES', 90, 'int'), ('hours', 'HOURS', 90, 'int')],
    'ar':     [_RANK, _NAME,
               ('ar', 'AR', 80, 'int'),
               ('ar_1', 'BRONZE', 80, 'int'), ('ar_2', 'SILVER', 75, 'int'), ('ar_3', 'GOLD', 65, 'int'),
               ('ar_4', 'PLAT', 65, 'int'), ('ar_5', 'DIAMOND', 90, 'int'),
               ('ar_t100', 'TOP 100', 85, 'int'), ('ar_t50', 'TOP 50', 75, 'int'), ('ar_t25', 'TOP 25', 75, 'int'),
               ('ar_t10', 'TOP 10', 75, 'int'), ('ar_t5', 'TOP 5', 65, 'int'), ('ar_t3', 'TOP 3', 65, 'int')],
    '40l':    [_RANK, _NAME,
               ('time', 'TIME', 120, 'time'), _FINESSE, ('kpp', 'KPP', 70, 'value'), ('kps', 'KPS', 80, 'value'),
               ('pieces', 'PIECES', 80, 'int'), ('pps', 'PPS', 80, 'value'), _DATE],
    'blitz':  [_RANK, _NAME,
               _FINESSE, ('spp', 'SPP', 90, 'value'), ('level', 'LEVEL', 70, 'int'),
               ('pieces', 'PIECES', 80, 'int'), ('pps', 'PPS', 80, 'value'), ('score', 'SCORE', 130, 'int'), _DATE],
    'zenith': [_RANK, _NAME,
               ('altitude', 'ALTITUDE', 120, 'altitude'), ('floor', 'FLOOR', 70, 'int'), ('time', 'TIME', 120, 'time'),
               ('apm', 'APM', 80, 'value'), ('pps', 'PPS', 70, 'value'), ('vs', 'VS', 80, 'value'),
               ('mods', 'MODS', 130, 'mods'), _DATE],
}
COLUMNS['zenithex'] = COLUMNS['zenith']


# ── Cell drawing ────────────────────────────────────────────────────────────────

def _draw_missing(ctx, cx, base_y):
    _draw_text(ctx, "-", cx, base_y, size=STAT_SIZE, colour=LABEL, align="center")


def _draw_cell(ctx, kind, value, x, w, cy, base_y):
    cx = x + w / 2
    if kind == 'rank':
        _draw_text(ctx, f"{value:,}", x + w - RANK_PAD, base_y, size=STAT_SIZE, bold=True,
                   colour=STAT, align="right")
        return

    if kind == 'badge':
        if value:
            badge = _icon(RANKS_DIR / f"{str(value).lower()}.png", BADGE_BOX)
            if badge is not None:
                _paint_icon(ctx, badge, cx, cy, align="center")
        return

    if kind == 'name':
        nx = x + NAME_PAD
        nx += _draw_text(ctx, value.get('username', ''), nx, base_y, size=NAME_SIZE, bold=True,
                         colour=USERNAME) + ICON_GAP
        if value.get('country'):
            flag = _icon(FLAGS_DIR / f"{value['country'].upper()}.png", FLAG_BOX)
            if flag is not None:
                nx += _paint_icon(ctx, flag, nx, cy) + ICON_GAP
        if value.get('supporter'):
            star = _icon(ASSETS_DIR / "star.png", STAR_BOX)
            if star is not None:
                _paint_icon(ctx, star, nx, cy)
        return

    if kind == 'mods':
        icons = [ic for ic in (_icon(MODS_DIR / f"{m}.png", MOD_BOX) for m in (value or []))
                 if ic is not None]
        if not icons:
            return
        total = sum(ic[1] / SCALE for ic in icons) + ICON_GAP * (len(icons) - 1)
        mx = cx - total / 2
        for ic in icons:
            mx += _paint_icon(ctx, ic, mx, cy) + ICON_GAP
        return

    if kind == 'glicko':
        glicko, rd = value
        if glicko is None or glicko < 0:
            _draw_missing(ctx, cx, base_y)
            return
        parts = [(f"{round(glicko):,}", STAT_SIZE, False, 0)]
        if rd is not None and rd >= 0:
            parts.append((f"\u00b1{round(rd)}", STAT_DEC, False, SUB_DY, LABEL))
        _draw_parts(ctx, parts, cx, base_y, STAT)
        return

    if kind == 'games':
        won, played = value
        if played is None or played < 0:
            _draw_missing(ctx, cx, base_y)
            return
        won = won if won is not None and won >= 0 else 0
        parts = [(f"{won:,}/{played:,}", STAT_SIZE, False, 0)]
        if played:
            parts.append((f" ({won / played * 100:.2f}%)", STAT_DEC, False, SUB_DY, LABEL))
        _draw_parts(ctx, parts, cx, base_y, STAT)
        return

    if value is None:
        _draw_missing(ctx, cx, base_y)
        return

    if kind == 'finesse':
        faults, accuracy = value
        _draw_parts(ctx, [(f"{faults:,}F", STAT_SIZE, False, 0),
                          (f" ({accuracy:.2f}%)", STAT_DEC, False, SUB_DY, LABEL)],
                    cx, base_y, STAT)
    elif kind == 'value':
        _draw_value(ctx, value, cx, base_y, STAT)
    elif kind == 'tr':
        intp, decp = _split_decimal(value, group=True)
        _draw_parts(ctx, [(intp, STAT_SIZE, True, 0), (decp, STAT_DEC, True, SUB_DY)],
                    cx, base_y, TR_INT)
    elif kind == 'int':
        if value < 0:
            _draw_missing(ctx, cx, base_y)
        else:
            _draw_text(ctx, f"{round(value):,}", cx, base_y, size=STAT_SIZE, colour=STAT, align="center")
    elif kind == 'time':
        text = _format_time(value)
        dot = text.find('.')
        _draw_parts(ctx, [(text[:dot], STAT_SIZE, False, 0), (text[dot:], STAT_DEC, False, SUB_DY)],
                    cx, base_y, STAT)
    elif kind == 'altitude':
        intp, decp = _split_decimal(value, group=True, places=1)
        _draw_parts(ctx, [(intp, STAT_SIZE, True, 0), (decp, STAT_DEC, True, SUB_DY),
                          ("m", STAT_DEC, False, SUB_DY, LABEL)],
                    cx, base_y, TR_INT)
    elif kind == 'date':
        _draw_text(ctx, _format_date(value), cx, base_y, size=STAT_SIZE, colour=STAT, align="center")
    else:
        _draw_text(ctx, str(value), cx, base_y, size=STAT_SIZE, colour=STAT, align="center")


# ── Main render ─────────────────────────────────────────────────────────────────

def render(rows, output_path="leaderboard.png", board='league', country=None):
    """Render *rows* (see ``teto_commands._build_lb_row``) for *board*.
    *country* is an ISO 3166-1 alpha-2 code, or None for the global board."""
    s = SCALE
    n = len(rows)
    cols = COLUMNS[board]
    width = PANEL_L + sum(c[2] for c in cols) + PANEL_L
    panel_r = width - PANEL_L
    rows_top = TOP + TITLE_H + TITLE_GAP + HEADER_H + HEADER_GAP
    height = rows_top + n * ROW_H + max(0, n - 1) * ROW_GAP + BOTTOM

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width * s, height * s)
    ctx = cairo.Context(surface)
    ctx.scale(s, s)
    ctx.set_font_options(options)

    _set_rgb(ctx, BG)
    ctx.rectangle(0, 0, width, height)
    ctx.fill()

    # Title: board + scope on the left, rank range on the right
    title_base = TOP + TITLE_H / 2 + TITLE_SIZE * 0.34
    scope = country.upper() if country else "GLOBAL"
    _draw_text(ctx, f"{BOARD_TITLES.get(board, board.upper())}  ({scope})", PANEL_L + NAME_PAD,
               title_base, size=TITLE_SIZE, bold=True, colour=USERNAME)
    if rows:
        lo, hi = rows[0]['rank'], rows[-1]['rank']
        _draw_text(ctx, f"RANKS {lo:,} - {hi:,}", panel_r - RANK_PAD, title_base,
                   size=TITLE_SIZE, colour=LABEL, align="right")

    # Column headers
    header_base = TOP + TITLE_H + TITLE_GAP + HEADER_H / 2 + HEADER_SIZE * 0.34
    x = PANEL_L
    for key, text, w, kind in cols:
        if text:
            if kind == 'name':
                _draw_text(ctx, text, x + NAME_PAD, header_base, size=HEADER_SIZE, colour=LABEL)
            elif kind == 'rank':
                _draw_text(ctx, text, x + w - RANK_PAD, header_base, size=HEADER_SIZE,
                           colour=LABEL, align="right")
            else:
                _draw_text(ctx, text, x + w / 2, header_base, size=HEADER_SIZE,
                           bold=kind == 'tr', colour=STAT if kind == 'tr' else LABEL, align="center")
        x += w

    for i, r in enumerate(rows):
        y = rows_top + i * (ROW_H + ROW_GAP)
        cy = y + ROW_H / 2
        base_y = _baseline(cy)

        _draw_panel(ctx, y, PANEL_L, panel_r)

        x = PANEL_L
        for key, _text, w, kind in cols:
            if kind == 'name':
                value = r
            elif kind == 'glicko':
                value = (r.get('glicko'), r.get('rd'))
            elif kind == 'games':
                value = (r.get('wins'), r.get('games'))
            else:
                value = r.get(key)
            _draw_cell(ctx, kind, value, x, w, cy, base_y)
            x += w

    surface.write_to_png(output_path)
