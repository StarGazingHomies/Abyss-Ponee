"""Shared Cairo drawing helpers and layout constants for the board renderers.

``leaderboard``, ``tetra_recent`` and ``tetoranks`` all draw the same kind of
table: rounded per-row panels on a dark background, text laid out on a shared
baseline, and small PNG icons blitted at device resolution. The pieces they
have in common live here; anything a single board owns stays in its module.

Colours here are the leaderboard/tetoranks palette. ``tetra_recent`` uses
slightly different values for :data:`BG`, :data:`STAT` and :data:`TR_INT` and
overrides them locally, so helpers that need a stat colour take it as an
argument instead of reading the module global."""
import math
import pathlib
from datetime import datetime

import cairo
import numpy as np
from PIL import Image

# ── Colours ────────────────────────────────────────────────────────────────────
PANEL        = (0.086, 0.129, 0.075)
USERNAME     = (0.976, 0.980, 0.961)
STAT         = (0.612, 0.792, 0.584)
LABEL        = (0.361, 0.518, 0.337)
TR_INT       = (0.886, 0.988, 0.871)
BG           = (0.059, 0.086, 0.051)


def _hex(code):
    """'#b590ff' -> (0.710, 0.565, 1.0). TETR.IO's own CSS is the source for
    most of the accent colours, so keeping them in hex form makes them greppable
    against the site."""
    code = code.lstrip('#')
    return tuple(int(code[i:i + 2], 16) / 255 for i in (0, 2, 4))

# ── Asset locations ────────────────────────────────────────────────────────────
ASSETS_DIR = pathlib.Path(__file__).parent.parent / "assets"
RANKS_DIR = ASSETS_DIR / "ranks"
FLAGS_DIR = ASSETS_DIR / "flags"

# ── Layout (base units == reference pixels; multiplied by SCALE) ───────────────
SCALE = 2
ROW_H = 35
ROW_GAP = 4
TOP = 9
BOTTOM = 6

PANEL_L = 4
PANEL_RAD = 4

STAT_SIZE = 17
STAT_DEC = 11
SUB_DY = 0                    # decimal part shares the integer baseline

FONT_FACE = "HUN"

options = cairo.FontOptions()
options.set_antialias(cairo.ANTIALIAS_GRAY)


# ── Primitives ─────────────────────────────────────────────────────────────────

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


def _draw_text(ctx, text, x, y, size, bold=False, colour=USERNAME, align="left",
               face=FONT_FACE, italic=False):
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


def _measure(ctx, text, size, bold=False, face=FONT_FACE, italic=False):
    """Advance width of *text* in base units, without drawing it."""
    _font(ctx, size, bold, face, italic)
    return ctx.text_extents(text).x_advance


def _fit_text(ctx, text, size, max_w, bold=False, face=FONT_FACE, italic=False):
    """*text* truncated with an ellipsis until it fits in *max_w* base units."""
    if max_w <= 0 or _measure(ctx, text, size, bold, face, italic) <= max_w:
        return text
    for n in range(len(text) - 1, 0, -1):
        candidate = text[:n] + "…"
        if _measure(ctx, candidate, size, bold, face, italic) <= max_w:
            return candidate
    return "…"


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


def _split_decimal(value, group=False, places=2):
    """'98.03' -> ('98', '.03'); *group* adds thousands separators."""
    s = f"{value:,.{places}f}" if group else f"{value:.{places}f}"
    dot = s.find('.')
    return s[:dot], s[dot:]


def _format_time(ms):
    """Milliseconds as [h:]m:ss.mmm."""
    total = ms / 1000
    m, s = divmod(total, 60)
    h, m = divmod(int(m), 60)
    if h:
        return f"{h}:{m:02d}:{s:06.3f}"
    if m:
        return f"{m}:{s:06.3f}"
    return f"{s:.3f}"


def _format_date(ts):
    """ISO 8601 timestamp (Z-tolerant) as YYYY-MM-DD."""
    return datetime.fromisoformat(ts.replace('Z', '+00:00')).strftime('%Y-%m-%d')


# ── Rows ───────────────────────────────────────────────────────────────────────

def _baseline(cy):
    """Shared text baseline for a row centred on *cy*."""
    return cy + STAT_SIZE * 0.34


def _draw_panel(ctx, y, left, right, colour=PANEL):
    """Fill the rounded per-row panel spanning [*left*, *right*] at *y*."""
    _set_rgb(ctx, colour)
    _rounded_rect(ctx, left, y, right - left, ROW_H, PANEL_RAD)
    ctx.fill()


def _draw_value(ctx, value, cx, base_y, colour):
    """Draw a float as a large integer part plus a small decimal part, centred
    on *cx*, or '-' if *value* is None."""
    if value is None:
        _draw_text(ctx, "-", cx, base_y, size=STAT_SIZE, colour=colour, align="center")
        return
    intp, decp = _split_decimal(value)
    _draw_parts(ctx, [(intp, STAT_SIZE, False, 0), (decp, STAT_DEC, False, SUB_DY)],
                cx, base_y, colour, align="center")


# ── Icons ──────────────────────────────────────────────────────────────────────

def _load_surface(path, box, recolour=None, alpha=1.0):
    """Load a PNG and fit it into a *box* x *box* square, returning
    (cairo surface, draw_w, draw_h). Returns None if the file is missing.

    *recolour* replaces every pixel's RGB with a flat colour, keeping the
    original alpha -- the achievement icon sheets ship as white silhouettes that
    have to be drawn dark. *alpha* scales the whole image's opacity."""
    p = pathlib.Path(path)
    if not p.exists():
        return None
    img = Image.open(p).convert("RGBA")
    ow, oh = img.size
    scale = box / max(ow, oh)
    dw, dh = max(1, round(ow * scale)), max(1, round(oh * scale))

    arr = np.array(img.resize((dw, dh), Image.LANCZOS), dtype=np.float32) / 255.0
    if recolour is not None:
        arr[:, :, :3] = recolour
    if alpha != 1.0:
        arr[:, :, 3] *= alpha
    a = arr[:, :, 3:4]
    arr[:, :, :3] *= a                           # premultiply for Cairo
    out = (arr * 255).clip(0, 255).astype(np.uint8)
    out[:, :, :3] = np.minimum(out[:, :, :3], out[:, :, 3:4])  # clamp RGB <= A
    bgra = out[:, :, [2, 1, 0, 3]]
    surf = cairo.ImageSurface.create_for_data(bytearray(bgra.tobytes()),
                                              cairo.FORMAT_ARGB32, dw, dh)
    return surf, dw, dh


_icons = {}


def _icon(path, box, recolour=None, alpha=1.0):
    """Cached image rasterised at device resolution (*box* is in base units)."""
    key = (str(path), box, recolour, alpha)
    if key not in _icons:
        _icons[key] = _load_surface(path, box * SCALE, recolour, alpha)
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
