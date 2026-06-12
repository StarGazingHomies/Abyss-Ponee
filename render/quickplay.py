import pathlib
import random
import cairo
from PIL import Image
import numpy as np

try:
    from render.tetra import _draw_text_shadow
except ImportError:
    from tetra import _draw_text_shadow

# ── Colours ──────────────────────────────────────────────────────────────────
BG             = (0.32, 0.137, 0.078)
REV_BG         = (0.164, 0.027, 0.055)
BORDER_COL_TL  = (0.568, 0.188, 0.113)
REV_BORDER_COL_TL = (0.360, 0.050, 0.050)
BORDER_COL_BR  = (0.215, 0.080, 0.050)
REV_BORDER_COL_BR = (0.125, 0.024, 0.024)
TITLE_COL      = (0.700, 0.375, 0.250)
SHADOW_COL     = (1.000, 0.823, 0.741)
VALUE_COL      = (1.000, 0.600, 0.415)
PB_ORANGE      = (0.990, 0.439, 0.274)
LABEL_COL      = TITLE_COL # (0.592, 0.513, 0.438)
PERSONAL_RANK_COL = (0.64, 0.30, 0.157)
ALT_BG         = (0.28, 0.117, 0.066)   # darker inset behind the altitude number
REV_ALT_BG         = (0.141, 0.023, 0.047)
ROW_DIV_COL    = (0.280, 0.170, 0.108)
ICON_TINT      = (0.978, 0.748, 0.345)   # amber used to recolour all mod icons
WHITE          = (1.000, 1.000, 1.000)

# ── Layout ───────────────────────────────────────────────────────────────────
SCALE       = 3
RECT_WIDTH       = 400 * SCALE
FONT_FACE   = "HUN"

PAD         = 18 * SCALE
TITLE_SIZE  = 10 * SCALE
ALT_SIZE    = 60 * SCALE
ICON_SIZE   = 20 * SCALE   # side length of each mod icon
ICON_GAP    = 4  * SCALE   # gap between icons
BANNER_H    = 50 * SCALE
GAP         = 12  * SCALE
SMALL_GAP   = 5  * SCALE
STAT_ROW_H  = 14 * SCALE
STAT_FONT   = 8  * SCALE

ASSETS_DIR  = pathlib.Path(__file__).parent.parent / "assets"

FLOOR_ALTITUDES = [
    0, 50, 150, 300, 450, 650, 850, 1100, 1350, 1650 # Floor 10 stretches to infinity
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _set_rgb(ctx, col, alpha=1.0):
    ctx.set_source_rgba(*col, alpha)


def _draw_text(ctx, text, x, y, size, bold=False, colour=WHITE, align="left", font=None):
    ctx.select_font_face(
        font or FONT_FACE,
        cairo.FONT_SLANT_NORMAL,
        cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL,
    )
    ctx.set_font_size(size)
    ext = ctx.text_extents(text)
    if align == "right":
        x -= ext.x_advance
    elif align == "center":
        x -= ext.x_advance / 2
    _set_rgb(ctx, colour)
    ctx.move_to(x, y)
    ctx.show_text(text)
    return ext.x_advance


def resize_for_cairo(img: Image.Image, size: tuple[int, int], resample=Image.LANCZOS) -> cairo.ImageSurface:
    """Resize an RGBA image and return a Cairo surface with premultiplied alpha (FORMAT_ARGB32)."""
    img = img.convert("RGBA")
    arr = np.array(img, dtype=np.float32) / 255.0

    alpha = arr[:, :, 3:4]
    arr[:, :, :3] *= alpha

    premul = Image.fromarray((arr * 255).clip(0, 255).astype(np.uint8), "RGBA")
    resized = premul.resize(size, resample)

    # LANCZOS ringing can produce pixels where RGB > A (invalid premultiplied).
    # Cairo assumes RGB <= A, so clamp to enforce that invariant.
    out = np.array(resized, dtype=np.uint8)
    out[:, :, :3] = np.minimum(out[:, :, :3], out[:, :, 3:4])
    bgra = out[:, :, [2, 1, 0, 3]]

    w, h = size
    return cairo.ImageSurface.create_for_data(bytearray(bgra.tobytes()), cairo.FORMAT_ARGB32, w, h)


def _load_mod_icon(mod_name, size_px):
    rev = False
    if "reverse" in mod_name:
        # size_px *= 2
        rev = True
    path = ASSETS_DIR / "mod_icons" / f"{mod_name}.png"
    img = Image.open(path).convert("RGBA")

    return resize_for_cairo(img, (size_px, size_px), resample=Image.BICUBIC), rev

    # """Return a cairo ImageSurface for the named mod, tinted to ICON_TINT."""
    # path = ASSETS_DIR / f"Mod_{mod_name}.png"
    # img  = Image.open(path).convert("RGBA").resize((size_px, size_px), Image.LANCZOS)
    # tr, tg, tb = ICON_TINT
    # new_pixels = []
    # for r, g, b, a in img.getdata():
    #     lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    #     new_pixels.append((int(lum * tr * 255), int(lum * tg * 255), int(lum * tb * 255), a))
    # tinted = Image.new("RGBA", img.size)
    # tinted.putdata(new_pixels)
    # data = tinted.tobytes("raw", "BGRA")
    # return cairo.ImageSurface.create_for_data(bytearray(data), cairo.FORMAT_ARGB32, size_px, size_px)


def _active_mods(entry):
    """Return the list of non-reverse mod names for this entry."""
    # print(entry["extras"]["zenith"]["mods"])
    # return ['expert', 'allspin', 'volatile']
    return [m for m in entry["extras"]["zenith"]["mods"]]


def _has_reverse(entry):
    """Return True if this entry has the reverse mod active."""
    return any([(True if "reverse" in m else False) for m in entry["extras"]["zenith"]["mods"]])


def _format_altitude(alt_m):
    if alt_m >= 10000:
        return f"{alt_m / 1000:.2f} KM"
    if alt_m >= 1000:
        return f"{alt_m:.1f} M"
    return f"{alt_m:.2f} M"


def _draw_altitude_text(ctx, alt_m, cx, y):
    """Draw altitude split into integer, decimal (smaller), and unit suffix (amber)."""
    val_str = f"{alt_m:,.1f}"
    suffix = " M"

    dot = val_str.find('.')
    int_part = val_str[:dot] if dot != -1 else val_str
    dec_part = val_str[dot:] if dot != -1 else ''

    dec_size = int(ALT_SIZE * 0.60)
    sdx, sdy = 0, 2 * SCALE
    shadow_col = PB_ORANGE

    ctx.select_font_face(FONT_FACE, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(ALT_SIZE)
    int_w    = ctx.text_extents(int_part).x_advance
    suffix_w = ctx.text_extents(suffix).x_advance
    ctx.set_font_size(dec_size)
    dec_w = ctx.text_extents(dec_part).x_advance if dec_part else 0

    x = cx - (int_w + dec_w + suffix_w) / 2

    _draw_text_shadow(ctx, int_part, x, y, size=ALT_SIZE, colour=SHADOW_COL,
                      shadow_offset=(sdx, sdy), shadow_col=shadow_col,
                      glow_col=shadow_col, glow_radius = 3 * SCALE, glow_alpha=0.7)
    x += int_w
    if dec_part:
        _draw_text_shadow(ctx, dec_part, x, y, size=dec_size, colour=SHADOW_COL,
                          shadow_offset=(sdx, sdy), shadow_col=shadow_col,
                          glow_col=shadow_col, glow_radius = 3 * SCALE, glow_alpha=0.7)
        x += dec_w
    _draw_text_shadow(ctx, suffix, x, y, size=dec_size, colour=VALUE_COL)


def _format_time(ms):
    total_ms = round(ms)
    mins   = total_ms // 60000
    secs   = (total_ms % 60000) // 1000
    ms_rem = total_ms % 1000
    return f"{mins}:{secs:02d}.{ms_rem:03d}"


def _build_stat_rows(entry):
    stats    = entry["results"]["stats"]
    agg      = entry["results"]["aggregatestats"]
    zenith   = stats["zenith"]
    extras_z = entry["extras"]["zenith"]

    altitude  = zenith["altitude"]
    floor_num = zenith["floor"]
    kills     = stats["kills"]
    finaltime = stats["finaltime"]
    pps       = agg["pps"]
    vs        = agg["vsscore"]
    apm       = agg["apm"]

    attack    = stats["garbage"]["attack"]
    pieces    = stats["piecesplaced"]
    inputs_n  = stats["inputs"]
    topcombo  = stats["topcombo"]
    topbtb    = stats["topbtb"]

    final_pos   = extras_z["finalPos"]
    final_count = extras_z["finalCount"]
    peak_pos    = extras_z["peakPos"]
    peak_count  = extras_z["peakCount"]

    t_sec      = finaltime / 1000
    alt_per_s  = altitude / t_sec if t_sec > 0 else 0
    atk_per_pc = attack / pieces  if pieces  > 0 else 0
    kpp        = inputs_n / pieces if pieces  > 0 else 0

    return [
        ("TIME",                   _format_time(finaltime)),
        ("FLOOR",                  str(floor_num)),
        ("KO'S",                   str(kills)),
        ("PEAK POSITION",          f"{peak_pos} / {peak_count}"),
        ("FINAL POSITION",         f"{final_pos} / {final_count}"),
        ("ALTITUDE PER SECOND",    f"{alt_per_s:.2f}"),
        ("ATTACK",                 str(attack)),
        ("ATTACK PER PIECE",       f"{atk_per_pc:.3f}"),
        ("ATTACK PER MINUTE",      f"{apm:.2f}"),
        ("PIECES PER SECOND",      f"{pps:.2f}"),
        ("VERSUS SCORE",           f"{vs:.2f}"),
        ("MAXIMUM COMBO",          str(topcombo)),
        ("MAX BACK-TO-BACK CHAIN", str(topbtb)),
        ("KEYS PER PIECE",         f"{kpp:.3f}"),
    ]


# ── Main render ───────────────────────────────────────────────────────────────

def render_quickplay(entry, output_path="output.png"):
    """Render a single Quick Play (zenith) game entry to a PNG."""
    rank     = entry["personal_rank"]
    is_pb    = (rank == 1)
    mods     = _active_mods(entry)
    reversed = _has_reverse(entry)
    rows     = _build_stat_rows(entry)

    # ── Pre-compute altitude rect (icons live inside it when present) ─────
    alt_rect_top = PAD + TITLE_SIZE + GAP // 2
    alt_text_y = alt_rect_top + GAP // 2 + ALT_SIZE - ICON_SIZE // 4
    # print(mods)
    if len(mods) > 0:
        # print("modified")
        alt_rect_h = GAP // 2 + ALT_SIZE + GAP // 2 + ICON_SIZE // 2
    else:
        alt_rect_h = GAP // 2 + ALT_SIZE + GAP // 2
    icon_y     = alt_text_y + GAP // 2 + ICON_SIZE // 4   # top of icons, only used when mods present

    # ── Pre-compute canvas height ─────────────────────────────────────────
    y = alt_rect_top + alt_rect_h
    # if is_pb:
    y += GAP + BANNER_H  # PB banner will display rank if it's not a pb
    y += GAP
    table_top = y
    y += len(rows) * STAT_ROW_H
    y += PAD

    height = y

    # ── Determine width for bg img ─────────────────────────────────────────
    WIDTH = int(height / 9 * 16)
    rect_left = (WIDTH - RECT_WIDTH) // 2

    cx = WIDTH // 2

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, height)
    ctx     = cairo.Context(surface)

    # ── Background Image ───────────────────────────────────────────────────────
    floor_num = entry["results"]["stats"]["zenith"]["floor"]
    altitude  = entry["results"]["stats"]["zenith"]["altitude"]
    bg_candidates = sorted((ASSETS_DIR / "qp_bg").glob(f"{floor_num}f*.jpg"))
    if bg_candidates:
        floor_start = FLOOR_ALTITUDES[floor_num - 1]
        floor_end   = FLOOR_ALTITUDES[floor_num] if floor_num < len(FLOOR_ALTITUDES) else floor_start + 1
        fraction    = max(0.0, min(1.0, (altitude - floor_start) / (floor_end - floor_start)))
        idx         = min(int(fraction * len(bg_candidates)), len(bg_candidates) - 1)
        bg_surf = resize_for_cairo(Image.open(bg_candidates[idx]), (WIDTH, height))
        ctx.set_source_surface(bg_surf, 0, 0)
        ctx.paint_with_alpha(0.8)  # Adjust alpha as needed (0.0 = fully transparent, 1.0 = fully opaque)

    # ── Background ───────────────────────────────────────────────────────
    border_pad = 6 * SCALE
    if reversed:
        _set_rgb(ctx, REV_BG)
    else:
        _set_rgb(ctx, BG)
    ctx.rectangle(rect_left + border_pad, border_pad, RECT_WIDTH - 2 * border_pad, height - 2 * border_pad)
    ctx.fill()

    h = SCALE  # half of the 2*SCALE border width

    # Outer and inner corners of the border ring
    obx = rect_left + border_pad - h
    orx = rect_left + RECT_WIDTH - border_pad + h
    oty = border_pad - h
    oby = height - border_pad + h
    ibx = rect_left + border_pad + h
    irx = rect_left + RECT_WIDTH - border_pad - h
    ity = border_pad + h
    iby = height - border_pad - h

    # TL color: left + top sides. The outer→inner diagonal at TR and BL creates
    # a 45° triangular tip at each color-transition corner.
    if reversed:
        _set_rgb(ctx, REV_BORDER_COL_TL)
    else:
        _set_rgb(ctx, BORDER_COL_TL)
    ctx.new_path()
    ctx.move_to(obx, oty)
    ctx.line_to(orx, oty)
    ctx.line_to(irx, ity)
    ctx.line_to(ibx, ity)
    ctx.line_to(ibx, iby)
    ctx.line_to(obx, oby)
    ctx.close_path()
    ctx.fill()

    # BR color: right + bottom sides, sharing the same diagonal edges at TR and BL.
    if reversed:
        _set_rgb(ctx, REV_BORDER_COL_BR)
    else:
        _set_rgb(ctx, BORDER_COL_BR)
    ctx.new_path()
    ctx.move_to(obx, oby)
    ctx.line_to(orx, oby)
    ctx.line_to(orx, oty)
    ctx.line_to(irx, ity)
    ctx.line_to(irx, iby)
    ctx.line_to(ibx, iby)
    ctx.close_path()
    ctx.fill()



    # ── Title ─────────────────────────────────────────────────────────────
    _draw_text(ctx, "YOUR FINAL ALTITUDE", rect_left + PAD + 4 * SCALE, PAD + TITLE_SIZE,
               size=TITLE_SIZE, colour=TITLE_COL)

    # ── Altitude rect ─────────────────────────────────────────────────────
    if reversed:
        _set_rgb(ctx, REV_ALT_BG)
    else:
        _set_rgb(ctx, ALT_BG)
    ctx.rectangle(rect_left + PAD, alt_rect_top, RECT_WIDTH - 2 * PAD, alt_rect_h)
    ctx.fill()

    _draw_altitude_text(ctx, altitude, cx, alt_text_y)

    # ── PB Banner ─────────────────────────────────────────────────────────
    y = alt_rect_top + alt_rect_h
    y += GAP
    bx = PAD
    bw = RECT_WIDTH - 2 * PAD
    if is_pb:
        _set_rgb(ctx, PB_ORANGE)
    elif reversed:
        _set_rgb(ctx, REV_ALT_BG)
    else:
        _set_rgb(ctx, ALT_BG)
    ctx.rectangle(rect_left + bx, y, bw, BANNER_H)
    ctx.fill()

    if is_pb:
        # This week's personal rank text
        _draw_text(ctx, f"THIS WEEK'S PERSONAL RANK", cx, y + 10 * SCALE,
                   size=8 * SCALE, bold=False, colour=PERSONAL_RANK_COL, align="center")

        _draw_text_shadow(ctx, "PERSONAL BEST", cx, y + BANNER_H // 2 + 10 * SCALE,
                   size=20 * SCALE, bold=True, colour=WHITE, align="center",
                          shadow_offset=(0, 1 * SCALE), shadow_col=PB_ORANGE,
                            glow_col=WHITE, glow_radius=5 * SCALE, glow_alpha=0.5)
    else:
        # Draw the rank instead of the PB banner
        _draw_text(ctx, f"THIS WEEK'S PERSONAL RANK", cx, y + 10 * SCALE,
                   size=8 * SCALE, bold=False, colour=PERSONAL_RANK_COL, align="center")

        # Draw a small #
        # Get width of the # character to position it correctly
        rank_text = f"{rank}" if rank is not None else "100+"

        hash_width = _draw_text(ctx, "#", 0, 0, size=10 * SCALE, bold=True, colour=PERSONAL_RANK_COL)
        number_width = _draw_text(ctx, f"{rank_text}", 0, 0, size=20 * SCALE, bold=True, colour=PERSONAL_RANK_COL)

        hash_x = cx - number_width / 2 - hash_width

        _draw_text(ctx, "#", hash_x, y + BANNER_H // 2 + 10 * SCALE,
                   size=10 * SCALE, bold=True, colour=PERSONAL_RANK_COL)

        _draw_text_shadow(ctx, f"{rank_text}", cx, y + BANNER_H // 2 + 10 * SCALE,
                     size=20 * SCALE, bold=True, colour=SHADOW_COL, align="center",
                              shadow_offset=(0, 1 * SCALE), shadow_col=PB_ORANGE,
                             glow_col=WHITE, glow_radius=5 * SCALE, glow_alpha=0.1)
        pass

    # ── Mod icons (centered inside bottom of altitude rect) ───────────────
    if mods:
        total_w = len(mods) * ICON_SIZE + (len(mods) - 1) * ICON_GAP
        ix = cx - total_w // 2
        for mod in mods:
            try:
                surf, rev = _load_mod_icon(mod, ICON_SIZE)
                # if rev:
                #     ctx.set_source_surface(surf, cx - total_w, icon_y - ICON_SIZE // 2)
                # else:
                ctx.set_source_surface(surf, ix, icon_y)
                ctx.paint()
            except FileNotFoundError:
                pass
            ix += ICON_SIZE + ICON_GAP

    # ── Stat table ────────────────────────────────────────────────────────
    lx = rect_left + PAD + 4 * SCALE
    rx = rect_left + RECT_WIDTH - PAD - 4 * SCALE
    text_offset = STAT_ROW_H // 2 + STAT_FONT // 3

    for i, (label, value) in enumerate(rows):
        row_y = table_top + i * STAT_ROW_H
        _set_rgb(ctx, ROW_DIV_COL)
        ctx.set_line_width(1)
        ctx.move_to(lx, row_y)
        ctx.line_to(rx, row_y)
        ctx.stroke()
        ty = row_y + text_offset
        _draw_text(ctx, label, lx, ty, size=STAT_FONT, colour=LABEL_COL)
        _draw_text(ctx, value, rx, ty, size=STAT_FONT, colour=VALUE_COL, align="right")

    surface.write_to_png(output_path)


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Render a Quick Play game from JSON data")
    parser.add_argument("--input",  "-i", default="../quickplay_output.json", help="Path to input JSON file")
    parser.add_argument("--output", "-o", default="qp_output.png",            help="Path to output PNG file")
    parser.add_argument("--game",   "-g", type=int, default=1,                help="Game number to render (1-indexed)")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = data["data"]["entries"]
    if args.game < 1 or args.game > len(entries):
        parser.error(f"--game must be between 1 and {len(entries)}")

    # render_quickplay(entries[8], args.output)

    # Make mods visible for testing
    entries[9]["extras"]["zenith"]["mods"] = ["expert", "allspin", "volatile", "doublehole"]
    # entries[9]["extras"]["zenith"]["mods"] = ["expert_reversed"]
    entries[9]["personal_rank"] = 42
    render_quickplay(entries[9], args.output)
