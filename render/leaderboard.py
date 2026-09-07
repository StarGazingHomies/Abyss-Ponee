"""Render one page of a TETR.IO leaderboard (user or record boards) as a table.

Rows are plain dicts produced by ``teto_commands._build_lb_row``; the set of
columns drawn depends on *board* (see :data:`COLUMNS`)."""
import math
import pathlib
from datetime import datetime

import cairo
import numpy as np
from PIL import Image

BG           = (0.059, 0.086, 0.051)
PANEL        = (0.086, 0.129, 0.075)
USERNAME     = (0.976, 0.980, 0.961)
STAT         = (0.612, 0.792, 0.584)
LABEL        = (0.361, 0.518, 0.337)
TR_INT       = (0.886, 0.988, 0.871)

ASSETS_DIR = pathlib.Path(__file__).parent.parent / "assets"
RANKS_DIR = ASSETS_DIR / "ranks"
FLAGS_DIR = ASSETS_DIR / "flags"
MODS_DIR = ASSETS_DIR / "zenith_mods"

# ── Layout (base units == reference pixels; multiplied by SCALE) ─────────────
SCALE = 2
ROW_H = 35
ROW_GAP = 4
TOP = 9
BOTTOM = 6

PANEL_L = 4
PANEL_RAD = 4

TITLE_H = 26
TITLE_GAP = 2
HEADER_H = 22
HEADER_GAP = 4

TITLE_SIZE = 18
HEADER_SIZE = 14
NAME_SIZE = 17
STAT_SIZE = 17
STAT_DEC = 11
SUB_DY = 0                    # decimal part shares the integer baseline

BADGE_BOX = 24
FLAG_BOX = 24
STAR_BOX = 21
MOD_BOX = 22
ICON_GAP = 6
NAME_PAD = 6                  # left padding inside the name column
RANK_PAD = 8                  # right padding inside the rank column

FONT_FACE = "HUN"

options = cairo.FontOptions()
options.set_antialias(cairo.ANTIALIAS_GRAY)

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
    left-to-right on a shared baseline."""
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


def _split_decimal(value, group=False, places=2):
    s = f"{value:,.{places}f}" if group else f"{value:.{places}f}"
    dot = s.find('.')
    return s[:dot], s[dot:]


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


_icons = {}


def _icon(path, box):
    """Cached image rasterised at device resolution (*box* is in base units)."""
    key = (str(path), box)
    if key not in _icons:
        _icons[key] = _load_surface(path, box * SCALE)
    return _icons[key]


def _paint_icon(ctx, loaded, x, cy, align="left"):
    """Blit a device-resolution icon vertically centred on *cy*. With
    align="left" *x* is the left edge; with "center" it is the centre.
    Returns the width consumed in base units."""
    surf, dw, dh = loaded
    w = dw / SCALE
    if align == "center":
        x -= w / 2
    ctx.save()
    ctx.scale(1 / SCALE, 1 / SCALE)
    ctx.set_source_surface(surf, round(x * SCALE), round(cy * SCALE - dh / 2))
    ctx.paint()
    ctx.restore()
    return w


def _format_time(ms):
    total = ms / 1000
    m, s = divmod(total, 60)
    h, m = divmod(int(m), 60)
    if h:
        return f"{h}:{m:02d}:{s:06.3f}"
    if m:
        return f"{m}:{s:06.3f}"
    return f"{s:.3f}"


def _format_date(ts):
    return datetime.fromisoformat(ts.replace('Z', '+00:00')).strftime('%Y-%m-%d')


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
        intp, decp = _split_decimal(value)
        _draw_parts(ctx, [(intp, STAT_SIZE, False, 0), (decp, STAT_DEC, False, SUB_DY)],
                    cx, base_y, STAT)
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
        base_y = cy + STAT_SIZE * 0.34

        _set_rgb(ctx, PANEL)
        _rounded_rect(ctx, PANEL_L, y, panel_r - PANEL_L, ROW_H, PANEL_RAD)
        ctx.fill()

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
