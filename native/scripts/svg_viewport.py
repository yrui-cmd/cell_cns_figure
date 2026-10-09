"""Nested SVG viewport placement shared by the bundled PPT and AI parsers."""
import math
import re
import copy
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


def numeric_geometry(element, viewport):
    """Resolve percentages in the current SVG user viewport, before transforms."""
    widths = {'x', 'x1', 'x2', 'cx', 'width', 'rx'}
    heights = {'y', 'y1', 'y2', 'cy', 'height', 'ry'}
    clone = None
    for key in widths | heights | {'r'}:
        value = element.get(key)
        if not value or '%' not in value:
            continue
        reference = viewport[0] if key in widths else viewport[1] if key in heights else math.hypot(*viewport)/math.sqrt(2)
        if clone is None:
            clone = copy.deepcopy(element)
        clone.set(key, str(length(value, reference)))
    return clone if clone is not None else element


def path_from_subpaths(subpaths, close_fill=False):
    import pathops
    path = pathops.Path()
    pen = path.getPen()
    for subpath in subpaths:
        points = subpath['points']
        if not points:
            continue
        pen.moveTo(tuple(points[0]['a']))
        for previous, current in zip(points, points[1:]):
            if previous['r'] == previous['a'] and current['l'] == current['a']:
                pen.lineTo(tuple(current['a']))
            else:
                pen.curveTo(tuple(previous['r']), tuple(current['l']), tuple(current['a']))
        if subpath['closed']:
            last, first = points[-1], points[0]
            if last['r'] != last['a'] or first['l'] != first['a']:
                pen.curveTo(tuple(last['r']), tuple(first['l']), tuple(first['a']))
            pen.closePath()
        elif close_fill:
            pen.closePath()
        else:
            pen.endPath()
    return path


def clip_atoms(atoms, transform, rectangle, to_subpaths):
    """Calculate visible native paths; never move/resize the original artwork.

    Boolean intersections retain Bézier curves. Strokes that cross a viewport
    edge are expanded before intersection so no false border is introduced.
    """
    import pathops
    from fontTools.pens.recordingPen import RecordingPen
    from fontTools.pens.qu2cuPen import Qu2CuPen
    inverse = transform.inverse()
    x, y, w, h = rectangle
    clip = pathops.Path()
    corners = [transform.transformPoint(p) for p in ((x,y),(x+w,y),(x+w,y+h),(x,y+h))]
    clip.moveTo(*corners[0])
    for corner in corners[1:]:
        clip.lineTo(*corner)
    clip.close()
    result = []
    inverse_scale = max(math.hypot(inverse.xx,inverse.xy),math.hypot(inverse.yx,inverse.yy))
    for atom in atoms:
        if atom['kind'] == 'text':
            # Keep editable text. Native font extents are checked in the preview.
            result.append(atom)
            continue
        coords = [inverse.transformPoint(p[key]) for s in atom['subpaths'] for p in s['points'] for key in ('a','l','r')]
        pad = max((p.get('strokeWidth',0)/2 for p in atom['paintParts'] if p.get('stroked')),default=0)*inverse_scale
        if all(x+pad <= px <= x+w-pad and y+pad <= py <= y+h-pad for px,py in coords):
            result.append(atom)
            continue
        for paint in atom['paintParts']:
            for kind in ('fill','stroke'):
                if not paint.get('filled' if kind=='fill' else 'stroked'):
                    continue
                path = path_from_subpaths(atom['subpaths'],close_fill=kind=='fill')
                if kind=='fill':
                    path.fillType = pathops.FillType.EVEN_ODD if paint.get('fillRule')=='evenodd' else pathops.FillType.WINDING
                else:
                    cap={'butt':pathops.LineCap.BUTT_CAP,'round':pathops.LineCap.ROUND_CAP,'square':pathops.LineCap.SQUARE_CAP}[paint.get('strokeCap','butt')]
                    join={'miter':pathops.LineJoin.MITER_JOIN,'round':pathops.LineJoin.ROUND_JOIN,'bevel':pathops.LineJoin.BEVEL_JOIN}[paint.get('strokeJoin','miter')]
                    path.stroke(paint['strokeWidth'],cap,join,paint.get('strokeMiterLimit',4))
                    path.convertConicsToQuads(.001)
                visible=pathops.op(path,clip,pathops.PathOp.INTERSECTION)
                if not visible:
                    continue
                pen=RecordingPen()
                visible.draw(Qu2CuPen(pen,max_err=.001,all_cubic=True))
                paths=to_subpaths(pen.value)
                if not paths:
                    continue
                part=dict(paint,filled=True,stroked=False,fillRule='nonzero',fillColor=paint['fillColor' if kind=='fill' else 'strokeColor'])
                new=dict(atom,subpaths=paths,paintParts=[part],complexity=sum(len(s['points']) for s in paths),viewport_clipped=True)
                result.append(new)
    return result
