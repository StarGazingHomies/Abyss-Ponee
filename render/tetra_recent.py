import pathlib
import math
import re
from datetime import datetime, timezone, timedelta

import cairo
import numpy as np
from PIL import Image

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py < 3.9
    ZoneInfo = None

_OFFSET_RE = re.compile(r'(?:UTC|GMT)?\s*([+-])(\d{1,2})(?::?(\d{2}))?$', re.IGNORECASE)


def parse_timezone(tz_str):
    """Resolve a user-supplied timezone string to a tzinfo.

    Accepts IANA names ('America/New_York', 'Asia/Tokyo') and UTC offsets
    ('UTC-4', 'GMT+5:30', '+9', '-0530'). Empty/None -> UTC. Returns None if
    the string can't be interpreted."""
    if not tz_str:
        return timezone.utc
    s = tz_str.strip()
    if s.upper() in ('UTC', 'GMT', 'Z'):
        return timezone.utc
    if ZoneInfo is not None:
        try:
            return ZoneInfo(s)
        except Exception:
            pass
    m = _OFFSET_RE.fullmatch(s)
    if m:
        sign = 1 if m.group(1) == '+' else -1
        hours, mins = int(m.group(2)), int(m.group(3) or 0)
        if hours <= 14 and mins < 60:
            return timezone(sign * timedelta(hours=hours, minutes=mins))
    return None

# ── Colours (sampled from reference image) ─────────────────────────────────────
BG            = (0.051, 0.078, 0.047)   # outer background / gaps between rows (13,20,12)
PANEL         = (0.086, 0.129, 0.075)   # per-row panel (22,33,19)
BADGE_ORANGE  = (1.000, 0.655, 0.259)   # (255,167,66)  win
BADGE_BLUE    = (0.545, 0.545, 1.000)   # (139,139,255) loss
BADGE_NC      = (0.118, 0.176, 0.102)   # no-contest faint pennant (30,45,26)
BADGE_DQ_WIN  = (0.149, 0.149, 0.063)   # dark olive pennant for a DQ win
BADGE_DQ_LOSS = (0.235, 0.024, 0.086)   # dark maroon pennant for a DQ loss
BADGE_NULL    = (0.027, 0.043, 0.023)   # almost black for nullified
BADGE_TEXT    = (0.020, 0.027, 0.016)   # near-black text on coloured pennant
NC_TEXT       = (0.521, 0.741, 0.482)   # "NO CONTEST" green (133,189,123)
NULL_TEXT     = (0.300, 0.220, 0.106)   # dark "NULLIFIED"
DQ_WIN_TEXT   = (0.961, 0.553, 0.149)   # orange "VICTORY by DQ"
DQ_LOSS_TEXT  = (0.949, 0.110, 0.400)   # pink "DEFEAT by DQ"
USERNAME      = (0.976, 0.980, 0.961)   # (249,250,245)
VS_TEXT       = (0.486, 0.608, 0.443)   # (124,155,113)
STAT          = (0.518, 0.698, 0.486)   # (132,178,124)
DATE          = (0.612, 0.816, 0.576)   # (156,208,147)
TR_INT        = (0.973, 0.992, 0.957)   # bright integer part of the TR delta (248,253,244)
TR_FADE       = (0.624, 0.816, 0.580)   # muted decimal + "TR" suffix (160,208,148)

# ── Layout (base units == reference pixels; multiplied by SCALE) ───────────────
SCALE       = 2
W           = 1105            # trailing margin past the TR value (VIEW button removed)
ROW_H       = 35
ROW_GAP     = 4
TOP         = 9
BOTTOM      = 6

PANEL_L     = 4
PANEL_R     = 1101
PANEL_RAD   = 4

BADGE_L       = 5
BADGE_BODY_R  = 156
BADGE_TIP     = 168
BADGE_RAD     = 4
RESULT_X      = 148            # right edge of result text
RESULT_SIZE   = 15

VS_X        = 180
VS_SIZE     = 13
NAME_SIZE   = 17
NAME_GAP    = 7               # gap before the flag
FLAG_BOX    = 24             # square box the flag image is fit into
FLAG_GAP    = 6              # gap before the star
STAR_BOX    = 21

APM_CX      = 527
PPS_CX      = 617
VS_CX       = 702
STAT_SIZE   = 17
STAT_DEC    = 11
SUB_DY      = 0               # decimal part is smaller but shares the integer baseline

DATE_CX     = 853
DATE_SIZE   = 15

TR_RIGHT    = 1085
TR_SIZE     = 17
TR_DEC      = 11
TR_SUFFIX   = 14

FONT_FACE = "HUN"

ASSETS_DIR = pathlib.Path(__file__).parent.parent / "assets"

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


def _font(ctx, size, bold=False, face=FONT_FACE, italic=False):
    ctx.select_font_face(face,
                         cairo.FONT_SLANT_ITALIC if italic else cairo.FONT_SLANT_NORMAL,
                         cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(size)


def _draw_text(ctx, text, x, y, size, bold=False, colour=USERNAME, align="left", face=FONT_FACE, italic=False):
    _font(ctx, size, bold, face, italic)
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
    left-to-right.

    *x* is interpreted according to *align* ('left', 'right', 'center') and the
    chunks share a common baseline *y*, each offset vertically by its own dy
    (used for subscript decimals). A chunk may carry its own colour as an
    optional 5th element, otherwise the shared *colour* is used."""
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


def _draw_score(ctx, label, a, b, right_x, base_y, size, colour):
    """Draw 'LABEL a—b' right-aligned at right_x. The em-dash is drawn as a
    line because the HUN font lacks a proper en/em-dash glyph."""
    left = f"{label} {a}"
    right = f"{b}"
    dash_w = size * 0.42
    margin = size * 0.16
    _font(ctx, size, True)
    lw = ctx.text_extents(left).x_advance
    rw = ctx.text_extents(right).x_advance
    total = lw + margin + dash_w + margin + rw
    x = right_x - total

    _set_rgb(ctx, colour)
    ctx.move_to(x, base_y)
    ctx.show_text(left)

    dy = base_y - size * 0.28
    ctx.set_line_width(max(1.5, size * 0.11))
    ctx.move_to(x + lw + margin, dy)
    ctx.line_to(x + lw + margin + dash_w, dy)
    ctx.stroke()

    ctx.move_to(x + lw + margin + dash_w + margin, base_y)
    ctx.show_text(right)


def _split_decimal(value):
    """'98.03' -> ('98', '.03')."""
    s = f"{value:.2f}"
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


def _paint_surface(ctx, loaded, x, cy):
    """Blit a (surface, w, h) tuple left-aligned at x, vertically centred on cy.
    Returns the x advance (drawn width)."""
    surf, dw, dh = loaded
    ctx.save()
    ctx.set_source_surface(surf, x, cy - dh / 2)
    ctx.paint()
    ctx.restore()
    return dw


def _format_date(ts, tz=timezone.utc):
    """ISO timestamp -> 'M/D/YYYY, h:mm:ss AM/PM' in *tz*."""
    dt = datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone(tz)
    hour12 = dt.hour % 12 or 12
    ampm = 'AM' if dt.hour < 12 else 'PM'
    return f"{dt.month}/{dt.day}/{dt.year}, {hour12}:{dt.minute:02d}:{dt.second:02d} {ampm}"


# ── Main render ─────────────────────────────────────────────────────────────────

def render(games, output_path="output_recent.png", tz=timezone.utc):
    """Render a condensed list of recent Tetra League games.

    *tz* is a tzinfo used to display each game's timestamp.

    *games* is a list of dicts with keys:
        outcome   'victory' | 'defeat' | 'nocontest'
        my_wins   int
        opp_wins  int
        opponent  str            opponent username
        country   str | None     ISO 3166-1 alpha-2 code
        supporter bool
        apm, pps, vs   float     queried player's stats for the game
        ts        str            ISO timestamp
        tr_change float | None   TR delta for the queried player

    The result pennant is coloured by *outcome*: orange for a win, blue for a
    loss, dark green for a no contest.
    """
    s = SCALE
    n = len(games)
    height = TOP + n * ROW_H + (n - 1) * ROW_GAP + BOTTOM

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W * s, height * s)
    ctx = cairo.Context(surface)
    ctx.scale(s, s)
    ctx.set_font_options(options)

    _set_rgb(ctx, BG)
    ctx.rectangle(0, 0, W, height)
    ctx.fill()

    for i, g in enumerate(games):
        y = TOP + i * (ROW_H + ROW_GAP)
        cy = y + ROW_H / 2
        base_y = cy + STAT_SIZE * 0.34       # shared text baseline

        # Per-row panel
        _set_rgb(ctx, PANEL)
        _rounded_rect(ctx, PANEL_L, y, PANEL_R - PANEL_L, ROW_H, PANEL_RAD)
        ctx.fill()

        outcome = g['outcome']

        # ── Result pennant ───────────────────────────────────────────────
        # win = orange, loss = blue; DQ results use a dark pennant with
        # coloured text; no contest uses a dark green pennant.
        badge_col = {
            'victory':   BADGE_ORANGE,
            'defeat':    BADGE_BLUE,
            'dqvictory': BADGE_DQ_WIN,
            'dqdefeat':  BADGE_DQ_LOSS,
            'nullified': BADGE_NULL,
        }.get(outcome, BADGE_NC)

        ctx.new_sub_path()
        ctx.arc(BADGE_L + BADGE_RAD, y + BADGE_RAD, BADGE_RAD, math.pi, 1.5 * math.pi)
        ctx.line_to(BADGE_BODY_R, y)
        ctx.line_to(BADGE_TIP, cy)
        ctx.line_to(BADGE_BODY_R, y + ROW_H)
        ctx.arc(BADGE_L + BADGE_RAD, y + ROW_H - BADGE_RAD, BADGE_RAD, 0.5 * math.pi, math.pi)
        ctx.close_path()
        _set_rgb(ctx, badge_col)
        ctx.fill()

        if outcome in ('victory', 'defeat'):
            label = "VICTORY" if outcome == 'victory' else "DEFEAT"
            _draw_score(ctx, label, g['my_wins'], g['opp_wins'],
                        RESULT_X, base_y, size=RESULT_SIZE, colour=BADGE_TEXT)
        else:
            text, col = {
                'dqvictory': ("VICTORY by DQ", DQ_WIN_TEXT),
                'dqdefeat':  ("DEFEAT by DQ", DQ_LOSS_TEXT),
                'nullified':  ("NULLIFIED", NULL_TEXT),
            }.get(outcome, ("NO CONTEST", NC_TEXT))
            _draw_text(ctx, text, RESULT_X, base_y, size=RESULT_SIZE,
                       bold=True, colour=col, align="right")

        # ── vs OPPONENT  flag  star ─────────────────────────────────────
        cx = VS_X
        cx += _draw_text(ctx, "vs ", cx, base_y, size=VS_SIZE, bold=True, colour=VS_TEXT)
        cx += _draw_text(ctx, g['opponent'].upper(), cx, base_y, size=NAME_SIZE,
                         bold=True, colour=USERNAME)
        cx += NAME_GAP
        if g.get('country'):
            flag = _load_surface(ASSETS_DIR / "flags" / f"{g['country'].upper()}.png", FLAG_BOX)
            if flag:
                cx += _paint_surface(ctx, flag, cx, cy) + FLAG_GAP
        if g.get('supporter'):
            star = _load_surface(ASSETS_DIR / "star.png", STAR_BOX)
            if star:
                _paint_surface(ctx, star, cx, cy)

        # ── Stats (int large, decimal small/subscript) ──────────────────
        for value, col_cx in ((g['apm'], APM_CX), (g['pps'], PPS_CX), (g['vs'], VS_CX)):
            if value is None:
                _draw_text(ctx, "-", col_cx, base_y, size=STAT_SIZE, colour=STAT, align="center")
                continue
            intp, decp = _split_decimal(value)
            _draw_parts(ctx, [(intp, STAT_SIZE, False, 0), (decp, STAT_DEC, False, SUB_DY)],
                        col_cx, base_y, STAT, align="center")

        # ── Date ────────────────────────────────────────────────────────
        _draw_text(ctx, _format_date(g['ts'], tz), DATE_CX, base_y, size=DATE_SIZE,
                   colour=DATE, align="center")

        # ── TR change ───────────────────────────────────────────────────
        change = g.get('tr_change')
        if change is not None:
            if round(change, 2) == 0:
                head, dec = "±0", ".00"
            else:
                whole = f"{change:+.2f}"
                dot = whole.find('.')
                head, dec = whole[:dot], whole[dot:]
            _draw_parts(ctx, [(head, TR_SIZE, True, 0, TR_INT),
                              (dec, TR_DEC, True, SUB_DY, TR_FADE),
                              (" TR", TR_SUFFIX, True, 0, TR_FADE)],
                        TR_RIGHT, base_y, TR_INT, align="right")

    surface.write_to_png(output_path)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Render recent Tetra League games from JSON")
    parser.add_argument("--input", "-i", default="../tetra_recent_sample.json")
    parser.add_argument("--output", "-o", default="recent_output.png")
    parser.add_argument("--count", "-c", type=int, default=14)
    parser.add_argument("--tz", default=None, help="IANA name or UTC offset (e.g. America/New_York, UTC-4)")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    def build(entry):
        opp = entry['otherusers'][0]
        opp_id = opp['id']
        lb = entry['results']['leaderboard']
        me = next(p for p in lb if p['id'] != opp_id)
        opp_lb = next(p for p in lb if p['id'] == opp_id)
        result = entry['extras'].get('result', '')
        if result in ('dqvictory', 'dqdefeat'):
            outcome = result
        elif 'victory' in result:
            outcome = 'victory'
        elif 'defeat' in result:
            outcome = 'defeat'
        else:
            outcome = 'nocontest'
        league = entry['extras'].get('league', {}).get(me['id'])
        tr_change = None
        if league and league[0].get('tr') is not None and league[1].get('tr') is not None:
            tr_change = league[1]['tr'] - league[0]['tr']
        st = me['stats']
        return {
            'outcome': outcome,
            'my_wins': me['wins'],
            'opp_wins': opp_lb['wins'],
            'opponent': opp['username'],
            'country': opp.get('country'),
            'supporter': opp.get('supporter', False),
            'apm': st['apm'], 'pps': st['pps'], 'vs': st['vsscore'],
            'ts': entry['ts'],
            'tr_change': tr_change,
        }

    games = [build(e) for e in data['data']['entries'][:args.count]]
    render(games, args.output, tz=parse_timezone(args.tz) or timezone.utc)
