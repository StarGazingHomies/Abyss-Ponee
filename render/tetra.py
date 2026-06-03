import cairo
import math
from PIL import Image, ImageFilter

# Colours, sampled from reference image (hopefully ok)
BG           = (0.0, 0.0, 0.0)          # pure black background
BLUE_DARK    = (0.05, 0.11, 0.20)       # blue panel dark end
BLUE_MID     = (0.08, 0.18, 0.32)       # blue row normal
BLUE_BRIGHT  = (0.15, 0.42, 0.80)       # blue row winner highlight
LABEL_BLUE_W = (0.42, 0.65, 0.93)       # label colour for the blue (left) side during a win
LABEL_BLUE_L = BLUE_BRIGHT              # label colour for the blue (left) side during a loss
RED_DARK     = (0.20, 0.05, 0.05)       # red panel dark end
RED_MID      = (0.32, 0.08, 0.08)       # red row normal
RED_BRIGHT   = (0.73, 0.14, 0.14)       # red row winner highlight
LABEL_RED_W  = (0.96, 0.43, 0.43)       # label colour for the red (right) side during a win
LABEL_RED_L  = (0.80, 0.15, 0.15)       # label colour for the red (right) side during a loss
BLACK        = (0.0, 0.0, 0.0)
WHITE        = (1.0, 1.0, 1.0)
YELLOW       = (1.0, 0.80, 0.0)
GOLD         = (1.0, 0.53, 0.0)
GREY         = (0.55, 0.55, 0.60)
TIMER_WHITE  = (1.0, 1.0, 1.0)          # timer text colour

# Layout constants
SCALE           = 2                      # increase to scale the whole image up (e.g. 2 = 2×)
WIDTH           = 1000 * SCALE
ROW_H           = 40   * SCALE
HEADER_H        = 140  * SCALE
HEADER_BODY_PAD = 30   * SCALE           # gap between header and first round row
CENTRE_X        = WIDTH // 2
# FONT_FACE       = "HUN-din 1451"
# FONT_FACE_BOLD  = "HUN-din 1451"
FONT_FACE       = "HUN"
FONT_FACE_BOLD  = "HUN"
ROW_PAD         = 12   * SCALE
LINE_W          = 1.5  * SCALE           # accent line thickness
BORDER_RADIUS   = 2    * SCALE
TITLE_BORDER_WIDTH = 3 * SCALE

options = cairo.FontOptions()
# cairo.ANTIALIAS_GRAY, cairo.ANTIALIAS_SUBPIXEL, not going to use none
# APPARENTLY TETRIO DOES NOT SUBPIXEL ANTIALIAS LOL
options.set_antialias(cairo.ANTIALIAS_GRAY)


def _set_rgb(ctx, col, alpha=1.0):
    ctx.set_source_rgba(*col, alpha)


def _rounded_rect(ctx, x, y, w, h, r=6):
    """Draw a rounded rectangle path."""
    ctx.new_sub_path()
    ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    ctx.arc(x + w - r, y + r, r, 1.5 * math.pi, 2 * math.pi)
    ctx.arc(x + w - r, y + h - r, r, 0, 0.5 * math.pi)
    ctx.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi)
    ctx.close_path()


def _text_to_glyphs(ctx, text, x, y):
    """Convert *text* to a positioned glyph list using the current scaled font.
    Returns (glyphs, total_x_advance)."""
    glyphs = ctx.get_scaled_font().text_to_glyphs(x, y, text, False)
    if glyphs:
        last = glyphs[-1]
        sf = ctx.get_scaled_font()
        ext = sf.glyph_extents([last])
        advance = last.x + ext.x_advance
    else:
        advance = x
    return glyphs, advance - x


def _draw_text(ctx, text, x, y, size=16, bold=False, colour=WHITE, align="left"):
    """Draw text.  *align* can be 'left', 'right', or 'center'."""
    ctx.select_font_face(
        FONT_FACE_BOLD if bold else FONT_FACE,
        cairo.FONT_SLANT_NORMAL,
        cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL,
    )
    ctx.set_font_size(size)
    extents = ctx.text_extents(text)
    if align == "right":
        x -= extents.x_advance
    elif align == "center":
        x -= extents.x_advance / 2
    glyphs, advance = _text_to_glyphs(ctx, text, x, y)
    _set_rgb(ctx, colour)
    ctx.show_glyphs(glyphs)
    return extents.x_advance


def _draw_text_shadow(ctx, text, x, y, size=16, bold=False, colour=WHITE, align="left",
                      shadow_col=BLACK, shadow_offset=(0, 2), shadow_alpha=0.6,
                      glow_col=None, glow_radius=0, glow_alpha=0.9):
    """Draw text with an optional drop shadow and/or glow underneath it.

    Shadow: set shadow_alpha > 0 (default on).
    Glow:   set glow_radius > 0 to enable; glow_col defaults to colour.
    """
    ctx.select_font_face(
        FONT_FACE_BOLD if bold else FONT_FACE,
        cairo.FONT_SLANT_NORMAL,
        cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL,
    )
    ctx.set_font_size(size)
    extents = ctx.text_extents(text)
    ox = x
    if align == "right":
        ox -= extents.x_advance
    elif align == "center":
        ox -= extents.x_advance / 2

    glyphs, _ = _text_to_glyphs(ctx, text, ox, y)

    def _shifted_glyphs(dx, dy):
        return [cairo.Glyph(g.index, g.x + dx, g.y + dy) for g in glyphs]

    # Glow — render text to a temp surface, blur with Pillow, composite back
    if glow_radius > 0:
        gc = glow_col if glow_col is not None else colour

        margin = int(glow_radius * 3) + 4
        tw = int(extents.x_advance) + margin * 2
        th = int(size * 2) + margin * 2
        tmp_ox = margin
        tmp_oy = margin + int(size)

        tmp_surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, tw, th)
        tmp_ctx  = cairo.Context(tmp_surf)
        tmp_ctx.select_font_face(
            FONT_FACE_BOLD if bold else FONT_FACE,
            cairo.FONT_SLANT_NORMAL,
            cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL,
        )
        tmp_ctx.set_font_size(size)
        glow_glyphs, _ = _text_to_glyphs(tmp_ctx, text, tmp_ox, tmp_oy)
        tmp_ctx.set_source_rgba(*gc, glow_alpha)
        tmp_ctx.show_glyphs(glow_glyphs)

        buf = bytes(tmp_surf.get_data())
        pil = Image.frombuffer("RGBA", (tw, th), buf, "raw", "BGRA", 0, 1)
        pil = pil.filter(ImageFilter.GaussianBlur(radius=glow_radius))
        blurred = pil.tobytes("raw", "BGRA")

        blurred_surf = cairo.ImageSurface.create_for_data(
            bytearray(blurred), cairo.FORMAT_ARGB32, tw, th
        )
        ctx.set_source_surface(blurred_surf, ox - tmp_ox, y - tmp_oy)
        ctx.paint()

    # Shadow
    if shadow_alpha > 0:
        ctx.set_source_rgba(*shadow_col, shadow_alpha)
        ctx.show_glyphs(_shifted_glyphs(shadow_offset[0], shadow_offset[1]))

    # Crisp text on top
    _set_rgb(ctx, colour)
    ctx.show_glyphs(glyphs)
    return extents.x_advance


def _draw_stat_labels(ctx, apm, pps, vs, x, y, size=15, align="right", bold=True, label_col=None):
    """Draw stats for the BANNER with coloured labels."""
    lc_apm = label_col
    lc_pps = label_col
    lc_vs  = label_col
    parts = [
        (f"{apm:.2f} ", WHITE),
        ("APM ", lc_apm),
        ("▣ ", label_col),
        (f"{pps:.2f} ", WHITE),
        ("PPS ", lc_pps),
        ("▣ ", label_col),
        (f"{vs:.2f} ", WHITE),
        ("VS ", lc_vs),
    ]
    FALLBACK_FONT = "Segoe UI Symbol"

    def _select_main():
        ctx.select_font_face(FONT_FACE, cairo.FONT_SLANT_NORMAL,
                             cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(size)

    def _select_fallback():
        ctx.select_font_face(FALLBACK_FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(size)

    def _is_sep(text):
        return '▣' in text

    # measure total width for alignment
    total_w = 0.0
    for text, _ in parts:
        _select_fallback() if _is_sep(text) else _select_main()
        total_w += ctx.text_extents(text).x_advance

    _select_main()
    if align == "right":
        cx = x - total_w
    elif align == "center":
        cx = x - total_w / 2
    else:
        cx = x
    for text, col in parts:
        _select_fallback() if _is_sep(text) else _select_main()
        glyphs, advance = _text_to_glyphs(ctx, text, cx, y)
        _set_rgb(ctx, col)
        ctx.show_glyphs(glyphs)
        cx += ctx.text_extents(text).x_advance
    _select_main()


def _draw_row_stats(ctx, apm, pps, vs, x, y, size=15, align="right", label_col=None):
    """Draw stats per game instead of for the banner."""
    lc_apm = label_col
    lc_pps = label_col
    lc_vs  = label_col
    parts = [
        (f"{apm:.2f} ", WHITE),
        ("APM", lc_apm),
        (" - ", GREY),
        (f"{pps:.2f} ", WHITE),
        ("PPS", lc_pps),
        (" - ", GREY),
        (f"{vs:.2f} ", WHITE),
        ("VS", lc_vs),
    ]
    ctx.select_font_face(FONT_FACE, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(size)
    total_w = sum(ctx.text_extents(t).x_advance for t, _ in parts)
    if align == "right":
        cx = x - total_w
    elif align == "center":
        cx = x - total_w / 2
    else:
        cx = x
    for text, col in parts:
        glyphs, advance = _text_to_glyphs(ctx, text, cx, y)
        _set_rgb(ctx, col)
        ctx.show_glyphs(glyphs)
        cx += ctx.text_extents(text).x_advance


def render(data, output_path="output.png"):
    player0 = data['player0']
    player1 = data['player1']
    stats0 = data['stats'][0]   # (apm, pps, vs) overall
    stats1 = data['stats'][1]
    rounds = data['rounds']     # list of (winner, (apm,pps,vs), (apm,pps,vs))

    # Count wins
    wins0 = sum(1 for r in rounds if r[0] == 0)
    wins1 = sum(1 for r in rounds if r[0] == 1)

    num_rounds = len(rounds)
    body_h = num_rounds * (ROW_H + ROW_PAD)  # total height of all round rows (no pad after last row)
    HEIGHT = HEADER_H + HEADER_BODY_PAD + body_h  # 20 for footer / padding

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, WIDTH, HEIGHT)
    ctx = cairo.Context(surface)
    ctx.set_font_options(options)

    # Background
    _set_rgb(ctx, BG)
    ctx.rectangle(0, 0, WIDTH, HEIGHT)
    ctx.fill()

    # Header
    VS_GAP = 110 * SCALE
    panel_h = HEADER_H - 10*SCALE
    # Off screen -> Center
    lx = -50 * SCALE
    ly = 10  * SCALE
    panel_w = CENTRE_X - VS_GAP // 2 - lx

    # Left top
    _rounded_rect(ctx, lx, ly, panel_w, panel_h, r=BORDER_RADIUS)
    pat = cairo.LinearGradient(lx, 0, lx + panel_w, 0)
    pat.add_color_stop_rgba(0.0, *BLACK,    1.0)
    pat.add_color_stop_rgba(0.7, *BLUE_MID, 1.0)
    pat.add_color_stop_rgba(1.0, *BLUE_MID, 1.0)
    ctx.set_source(pat)
    ctx.fill()
    # Border
    _rounded_rect(ctx, lx, ly, panel_w, panel_h, r=BORDER_RADIUS)
    _set_rgb(ctx, BLUE_BRIGHT, 0.55)
    ctx.set_line_width(TITLE_BORDER_WIDTH)
    ctx.stroke()

    # Right top
    rx = CENTRE_X + VS_GAP // 2
    ry = ly
    rpanel_w = WIDTH - lx - rx
    _rounded_rect(ctx, rx, ry, rpanel_w, panel_h, r=BORDER_RADIUS)
    pat = cairo.LinearGradient(rx, 0, rx + rpanel_w, 0)
    pat.add_color_stop_rgba(0.0, *RED_MID, 1.0)
    pat.add_color_stop_rgba(0.3, *RED_MID, 1.0)
    pat.add_color_stop_rgba(1.0, *BLACK,   1.0)
    ctx.set_source(pat)
    ctx.fill()
    # Border
    _rounded_rect(ctx, rx, ry, rpanel_w, panel_h, r=BORDER_RADIUS)
    _set_rgb(ctx, RED_BRIGHT, 0.55)
    ctx.set_line_width(TITLE_BORDER_WIDTH)
    ctx.stroke()

    inner_left  = lx + panel_w - 10 * SCALE   # right inner edge of left panel
    inner_right = rx + 10 * SCALE              # left inner edge of right panel

    # Player names
    _draw_text(ctx, player0.upper(), inner_left, ly + 30*SCALE, size=22*SCALE, bold=True, colour=WHITE, align="right")
    _draw_text(ctx, player1.upper(), inner_right, ry + 30*SCALE, size=22*SCALE, bold=True, colour=WHITE, align="left")

    # Large win counts
    _draw_text_shadow(ctx, str(wins0), inner_left, ly + 90*SCALE, size=64*SCALE, bold=True, colour=WHITE, align="right",
                      shadow_col=GREY, shadow_offset=(0, 1.5*SCALE), shadow_alpha=1.0,
                      glow_col=WHITE, glow_radius=4 * SCALE, glow_alpha=0.5)
    _draw_text_shadow(ctx, str(wins1), inner_right, ry + 90*SCALE, size=64*SCALE, bold=True, colour=WHITE, align="left",
                      shadow_col=GREY, shadow_offset=(0, 1.5*SCALE), shadow_alpha=1.0,
                      glow_col=WHITE, glow_radius=4 * SCALE, glow_alpha=0.5)

    # Stats
    _draw_stat_labels(ctx, *stats0, inner_left, ly + panel_h - 12*SCALE, size=13*SCALE, align="right", label_col=BLUE_BRIGHT)
    _draw_stat_labels(ctx, *stats1, inner_right, ry + panel_h - 12*SCALE, size=13*SCALE, align="left", label_col=RED_BRIGHT)

    # "VS" in centre
    # _draw_text(ctx, "VS", CENTRE_X, ly + 72*SCALE, size=36*SCALE, bold=False, colour=YELLOW, align="center")
    _draw_text_shadow(ctx, "VS", CENTRE_X, ly + 85*SCALE, size=50*SCALE, bold=False, colour=YELLOW, align="center",
                      shadow_col=GOLD, shadow_offset=(0, 1.5*SCALE), shadow_alpha=1.0,
                      glow_col=GOLD, glow_radius=4*SCALE, glow_alpha=0.5)

    # -------------------- Rounds --------------------
    row_top  = HEADER_H + HEADER_BODY_PAD
    # Inner edge
    left_x2  = CENTRE_X - 30*SCALE
    right_x1 = CENTRE_X + 30*SCALE
    # Outer edges bleed off-screen so there's no visible empty gradient tail
    left_x1  = 100*SCALE
    right_x2 = WIDTH - 100*SCALE
    left_row_w  = left_x2 - left_x1
    right_row_w = right_x2 - right_x1

    for i, rnd in enumerate(rounds):
        winner = rnd[0]
        s0 = rnd[1]   # (apm, pps, vs) for player0
        s1 = rnd[2]   # (apm, pps, vs) for player1
        y = row_top + i * (ROW_H + ROW_PAD)

        # Determine highlight
        left_bg  = BLUE_BRIGHT if winner == 0 else BLUE_DARK
        right_bg = RED_BRIGHT  if winner == 1 else RED_DARK
        left_text = LABEL_BLUE_W if winner == 0 else LABEL_BLUE_L
        right_text = LABEL_RED_W if winner == 1 else LABEL_RED_L

        # Left row: Black left off screen -> solid right
        _rounded_rect(ctx, left_x1, y, left_row_w, ROW_H, r=4)
        pat = cairo.LinearGradient(left_x1, 0, left_x2, 0)
        pat.add_color_stop_rgba(0.0, *BLACK, 1.0)
        pat.add_color_stop_rgba(0.99, *left_bg, 1.0)
        pat.add_color_stop_rgba(1.0, *left_bg, 1.0)
        ctx.set_source(pat)
        ctx.fill()

        # Right row: Solid left -> Black right off screen
        _rounded_rect(ctx, right_x1, y, right_row_w, ROW_H, r=4)
        pat = cairo.LinearGradient(right_x1, 0, right_x2, 0)
        pat.add_color_stop_rgba(0.0, *right_bg, 1.0)
        pat.add_color_stop_rgba(0.01, *right_bg, 1.0)
        pat.add_color_stop_rgba(1.0, *BLACK, 1.0)
        ctx.set_source(pat)
        ctx.fill()

        # Accent lines on the inner (timer-facing) edges — drawn as thin
        # rounded rects so they conform to the bar's corner radius.
        left_line_col  = WHITE              if winner == 0 else BLUE_BRIGHT
        right_line_col = WHITE              if winner == 1 else RED_BRIGHT
        _set_rgb(ctx, left_line_col)
        _rounded_rect(ctx, left_x2 - LINE_W, y, LINE_W, ROW_H, r=2)
        ctx.fill()
        _set_rgb(ctx, right_line_col)
        _rounded_rect(ctx, right_x1, y, LINE_W, ROW_H, r=2)
        ctx.fill()

        # Row stats text
        text_y = y + ROW_H / 2 + 5*SCALE
        _draw_row_stats(ctx, *s0, left_x2 - 12*SCALE, text_y, size=15*SCALE, align="right", label_col=left_text)
        _draw_row_stats(ctx, *s1, right_x1 + 12*SCALE, text_y, size=15*SCALE, align="left",  label_col=right_text)

        # Center time
        duration = rnd[3] if len(rnd) > 3 else None
        mins = int(duration) // 60
        secs = int(duration) % 60
        time_str = f"{mins}:{secs:02d}"
        _draw_text(ctx, time_str, CENTRE_X, text_y, size=16*SCALE, bold=True, colour=TIMER_WHITE, align="center")

    # Save
    # Note that because of async not being real multithreading
    # there's no race condition / this will be ok
    surface.write_to_png(output_path)
