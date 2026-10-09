"""Nested SVG viewport placement shared by the bundled PPT and AI parsers."""
import math
import re
from fontTools.misc.transform import Transform


def length(value, reference, default=0.0):
    if value is None:
        return default
    match = re.fullmatch(r'\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(%|px|pt|pc|in|cm|mm|q)?\s*', value)
    if not match:
        raise ValueError('Unsupported SVG viewport length: ' + value)
    number = float(match[1])
    factors = {'px': 1, 'pt': 96/72, 'pc': 16, 'in': 96, 'cm': 96/2.54, 'mm': 96/25.4, 'q': 96/101.6}
    result = number * (reference / 100 if match[2] == '%' else factors.get(match[2], 1))
    if not math.isfinite(result):
        raise ValueError('Nonfinite SVG viewport length')
    return result


def resolve(element, parent_size):
    """Return placement, child user-space size, and viewport clipping rectangle."""
    pw, ph = parent_size
    x = length(element.get('x'), pw)
    y = length(element.get('y'), ph)
    width = length(element.get('width'), pw, pw)
    height = length(element.get('height'), ph, ph)
    if width < 0 or height < 0:
        raise ValueError('Negative nested SVG viewport size')
    if width == 0 or height == 0:
        return None, None, None
    box = element.get('viewBox')
    if not box:
        return Transform().translate(x, y), (width, height), (x, y, width, height)
    values = [float(v) for v in re.split(r'[\s,]+', box.strip())]
    if len(values) != 4 or not all(math.isfinite(v) for v in values) or min(values[2:]) <= 0:
        raise ValueError('Invalid nested SVG viewBox')
    vx, vy, vw, vh = values
    parts = element.get('preserveAspectRatio', 'xMidYMid meet').split()
    if parts and parts[0] == 'defer':
        parts.pop(0)
    align = parts[0] if parts else 'xMidYMid'
    mode = parts[1] if len(parts) > 1 else 'meet'
    if len(parts) > 2 or mode not in ('meet', 'slice'):
        raise ValueError('Unsupported preserveAspectRatio')
    sx, sy = width / vw, height / vh
    if align != 'none':
        match = re.fullmatch(r'x(Min|Mid|Max)Y(Min|Mid|Max)', align)
        if not match:
            raise ValueError('Unsupported preserveAspectRatio alignment')
        sx = sy = min(sx, sy) if mode == 'meet' else max(sx, sy)
        factors = {'Min': 0, 'Mid': .5, 'Max': 1}
        dx = (width - vw * sx) * factors[match[1]]
        dy = (height - vh * sy) * factors[match[2]]
    else:
        dx = dy = 0
    matrix = Transform().translate(x + dx, y + dy).scale(sx, sy).translate(-vx, -vy)
    return matrix, (vw, vh), (x, y, width, height)


def check_clip(atoms, before_viewport, rectangle):
    """Reject real viewport clipping instead of silently painting outside it.

    Checking Bezier control hulls is conservative: uncertain clips are reported,
    never discarded. Text extents still require the final native visual review.
    """
    inverse = before_viewport.inverse()
    x, y, w, h = rectangle
    for atom in atoms:
        points = [atom['text']['position']] if atom.get('kind') == 'text' else [
            point[key] for path in atom.get('subpaths', []) for point in path['points'] for key in ('a', 'l', 'r')]
        for point in points:
            px, py = inverse.transformPoint(point)
            if not (x - .001 <= px <= x + w + .001 and y - .001 <= py <= y + h + .001):
                raise ValueError('Nested SVG viewport clipping requires preprocessing; original SVG retained')
