import json
import math
from datetime import datetime
from typing import Dict, Iterable, List, Tuple

try:
    from tetra import _draw_text_shadow
except ImportError:
    from render.tetra import _draw_text_shadow

import cairo

# Styling (kept close to tetra.py conventions)
BG = (0.0, 0.0, 0.0)
AXIS = (0.85, 0.85, 0.90)
GRID = (0.25, 0.25, 0.30)
LINE = (0.12, 0.92, 0.48)
TEXT = (0.95, 0.95, 0.98)
MARKER_RADIUS = 5.0
SHADE_ALPHA = 0.15

# Layout constants
DEFAULT_WIDTH = 1200
DEFAULT_HEIGHT = 600
PADDING_LEFT = 80
PADDING_RIGHT = 30
PADDING_TOP = 30
PADDING_BOTTOM = 60
GRID_LINE_COUNT = 6
AXIS_LABEL_SIZE = 16
TICK_LABEL_SIZE = 12
TIME_LABEL_COUNT = 10
TIME_LABEL_FORMAT = "%y-%m-%d"
TIME_LABEL_Y_OFFSET = 22
AXIS_LABEL_TR = "TR"
AXIS_LABEL_TIME = "Time"
TR_LABEL_DX = 0.0
TR_TICK_LABEL_PAD = 8.0
SCALE = 2.0

RESULT_COLOURS = {
    1: (1.00, 0.65, 0.26),  # victory
    2: (0.55, 0.55, 1.00),  # defeat
    3: (1.00, 0.65, 0.26),  # victory by disqualification
    4: (0.55, 0.55, 1.00),  # defeat by disqualification
    5: (0.60, 0.60, 0.60),  # tie
    6: (0.62, 0.96, 0.40),  # no contest
    7: (0.20, 0.20, 0.20),  # match nullified
}

FONT_FACE = "HUN"


def _set_rgb(ctx: cairo.Context, col: Tuple[float, float, float], alpha: float = 1.0) -> None:
    ctx.set_source_rgba(col[0], col[1], col[2], alpha)


def _to_seconds(timestamp: int) -> float:
    # Heuristic: treat large epoch values as milliseconds.
    return timestamp / 1000.0 if timestamp >= 10**12 else float(timestamp)


def _nice_step(raw: float) -> float:
    if raw <= 0:
        return 1.0
    exp = math.floor(math.log10(raw))
    frac = raw / (10 ** exp)
    if frac <= 1.5:
        nice = 1.0
    elif frac <= 3.0:
        nice = 2.0
    elif frac <= 7.0:
        nice = 5.0
    else:
        nice = 10.0
    return nice * (10 ** exp)


def _parse_points(points: Iterable[List[int]], start_time: int) -> Tuple[List[float], List[int], List[int], List[int]]:
    times: List[float] = []
    tr_values: List[int] = []
    results: List[int] = []
    opponent_trs: List[int] = []

    for point in points:
        offset, result, tr_value, opponent_tr = point
        timestamp = start_time + offset
        times.append(_to_seconds(timestamp))
        tr_values.append(tr_value)
        results.append(result)
        opponent_trs.append(opponent_tr)

    return times, tr_values, results, opponent_trs


def render_leagueflow(
    data: Dict,
    output_path: str = "leagueflow.png",
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    tr_label_dx: float = TR_LABEL_DX,
    scale: float = SCALE,
    no_points: bool = False,
    no_shading: bool = False,
    no_graph: bool = False,
) -> None:
    start_time = data["startTime"]
    points = data["points"]

    times, tr_values, results, opponent_trs = _parse_points(points, start_time)
    if not times:
        raise ValueError("No leagueflow points provided")

    padding_left = PADDING_LEFT * scale
    padding_right = PADDING_RIGHT * scale
    padding_top = PADDING_TOP * scale
    padding_bottom = PADDING_BOTTOM * scale
    marker_radius = MARKER_RADIUS * scale
    axis_label_size = AXIS_LABEL_SIZE * scale
    tick_label_size = TICK_LABEL_SIZE * scale
    time_label_y_offset = TIME_LABEL_Y_OFFSET * scale
    base_font_size = 14 * scale

    min_time = min(times)
    max_time = max(times)
    min_tr = min(min(tr_values), min(opponent_trs))
    max_tr = max(max(tr_values), max(opponent_trs))

    # Test: Scale them to account for size of the marker radius
    # min_tr -= (max_tr - min_tr) * (marker_radius / (height * scale - padding_top - padding_bottom))
    # max_tr += (max_tr - min_tr) * (marker_radius / (height * scale - padding_top - padding_bottom))
    # min_time -= (max_time - min_time) * (marker_radius / (width * scale - padding_left - padding_right))
    # max_time += (max_time - min_time) * (marker_radius / (width * scale - padding_left - padding_right))

    if min_time == max_time:
        max_time += 1.0
    if min_tr == max_tr:
        max_tr += 1

    scaled_width = max(1, int(round(width * scale)))
    scaled_height = max(1, int(round(height * scale)))


    plot_w = scaled_width - padding_left - padding_right
    plot_h = scaled_height - padding_top - padding_bottom
    inner_left = padding_left # + marker_radius
    inner_right = padding_left + plot_w # - marker_radius
    inner_top = padding_top # + marker_radius
    inner_bottom = padding_top + plot_h # - marker_radius
    inner_w = max(1.0, inner_right - inner_left)
    inner_h = max(1.0, inner_bottom - inner_top)

    def x_from_time(t: float) -> float:
        return inner_left + (t - min_time) / (max_time - min_time) * inner_w

    def y_from_tr(tr: float) -> float:
        return inner_top + (max_tr - tr) / (max_tr - min_tr) * inner_h

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, scaled_width, scaled_height)
    ctx = cairo.Context(surface)
    ctx.select_font_face(FONT_FACE, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(base_font_size)

    # Background
    _set_rgb(ctx, BG)
    ctx.rectangle(0, 0, scaled_width, scaled_height)
    ctx.fill()

    # Grid and axes
    tr_range = max_tr - min_tr
    tr_step = _nice_step(tr_range / GRID_LINE_COUNT)
    tr_start = math.floor(min_tr / tr_step) * tr_step
    tr_end = math.ceil(max_tr / tr_step) * tr_step

    _set_rgb(ctx, GRID, 0.55)
    ctx.set_line_width(1 * scale)
    tr_value = tr_start
    while tr_value <= tr_end + 1e-6:
        y = y_from_tr(tr_value)
        if padding_top <= y <= scaled_height - padding_bottom:
            ctx.move_to(padding_left, y)
            ctx.line_to(scaled_width - padding_right, y)
            ctx.stroke()
            _set_rgb(ctx, TEXT, 0.9)
            label = f"{int(tr_value)}"
            ext = ctx.text_extents(label)
            label_right = padding_left - (TR_TICK_LABEL_PAD * scale)
            ctx.move_to(label_right - ext.x_advance, y + 5 * scale)
            ctx.show_text(label)
            _set_rgb(ctx, GRID, 0.55)
        tr_value += tr_step

    label_divisor = max(1, TIME_LABEL_COUNT - 1)
    for i in range(TIME_LABEL_COUNT):
        t = min_time + (max_time - min_time) * (i / label_divisor)
        x = x_from_time(t)
        if padding_left <= x <= scaled_width - padding_right:
            ctx.move_to(x, padding_top)
            ctx.line_to(x, scaled_height - padding_bottom)
            ctx.stroke()

    # Axis lines
    _set_rgb(ctx, AXIS)
    ctx.set_line_width(2 * scale)
    ctx.move_to(padding_left, padding_top)
    ctx.line_to(padding_left, scaled_height - padding_bottom)
    ctx.line_to(scaled_width - padding_right, scaled_height - padding_bottom)
    ctx.stroke()

    ctx.save()
    ctx.rectangle(padding_left + scale, padding_top - scale, plot_w, plot_h)
    ctx.clip()

    # Shade area under TR line
    if not no_shading:
        _set_rgb(ctx, LINE, SHADE_ALPHA)
        last_y = 0
        for i, (t, tr) in enumerate(zip(times, tr_values)):
            x = x_from_time(t)
            y = y_from_tr(tr)
            if i == 0:
                ctx.move_to(x, y)
            else:
                ctx.line_to(x, last_y)
                ctx.line_to(x, y)
            last_y = y
        last_x = x_from_time(times[-1])
        first_x = x_from_time(times[0])
        axis_y = scaled_height - padding_bottom
        ctx.line_to(last_x, axis_y)
        ctx.line_to(first_x, axis_y)
        ctx.close_path()
        ctx.fill()

    # TR line
    if not no_graph:
        _set_rgb(ctx, LINE)
        ctx.set_line_width(2.5 * scale)
        last_y = 0
        for i, (t, tr) in enumerate(zip(times, tr_values)):
            x = x_from_time(t)
            y = y_from_tr(tr)
            if i == 0:
                ctx.move_to(x, y)
            else:
                ctx.line_to(x, last_y)
                ctx.line_to(x, y)
            last_y = y
        ctx.stroke()

    # Opponent markers
    if not no_points:
        for t, result, opponent_tr in zip(times, results, opponent_trs):
            x = x_from_time(t)
            y = y_from_tr(opponent_tr)
            col = RESULT_COLOURS.get(result, (0.7, 0.7, 0.7))
            _set_rgb(ctx, col)
            ctx.move_to(x, y - marker_radius)
            ctx.line_to(x + marker_radius, y)
            ctx.line_to(x, y + marker_radius)
            ctx.line_to(x - marker_radius, y)
            ctx.close_path()
            ctx.fill()

    ctx.restore()

    # Labels
    _set_rgb(ctx, TEXT)
    ctx.set_font_size(axis_label_size)
    tr_ext = ctx.text_extents(AXIS_LABEL_TR)
    tr_right = padding_left + (tr_label_dx * scale)
    tr_x = tr_right - (tr_ext.x_bearing + tr_ext.width)
    ctx.move_to(tr_x, padding_top - 8 * scale)
    ctx.show_text(AXIS_LABEL_TR)
    ctx.move_to(scaled_width - padding_right - 60 * scale, scaled_height - 20 * scale)
    ctx.show_text(AXIS_LABEL_TIME)

    ctx.set_font_size(tick_label_size)
    label_y = scaled_height - padding_bottom + time_label_y_offset
    label_divisor = max(1, TIME_LABEL_COUNT - 1)
    for i in range(TIME_LABEL_COUNT):
        t = min_time + (max_time - min_time) * (i / label_divisor)
        label = datetime.fromtimestamp(t).strftime(TIME_LABEL_FORMAT)
        x = x_from_time(t)
        ext = ctx.text_extents(label)
        ctx.move_to(x - ext.x_advance / 2, label_y)
        ctx.show_text(label)

    surface.write_to_png(output_path)


def render_leagueflow_file(
    input_path: str,
    output_path: str = "leagueflow.png",
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    tr_label_dx: float = TR_LABEL_DX,
    scale: float = SCALE,
) -> None:
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    render_leagueflow(
        data["data"],
        output_path=output_path,
        width=width,
        height=height,
        tr_label_dx=tr_label_dx,
        scale=scale,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Render Tetra Leagueflow from JSON data")
    parser.add_argument("--input", "-i", default="../leagueflow.json", help="Path to input JSON file containing leagueflow data")
    parser.add_argument("--output", "-o", default="leagueflow.png", help="Path to output PNG file")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="Width of output image in pixels")
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help="Height of output image in pixels")
    parser.add_argument("--tr-label-dx", type=float, default=TR_LABEL_DX, help="Shift TR label right (positive) or left (negative)")
    parser.add_argument("--scale", type=float, default=SCALE, help="Scale factor for output size and layout")
    args = parser.parse_args()

    render_leagueflow_file(
        args.input,
        output_path=args.output,
        width=args.width,
        height=args.height,
        tr_label_dx=args.tr_label_dx,
        scale=args.scale,
    )
