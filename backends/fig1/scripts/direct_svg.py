"""User-selected direct geometry mapping, without SVG effect compatibility gates.

Keep the downloaded original immutable. Only the private mapping copy drops
clipping/masks/filters. The report names presentation approximations explicitly.
"""
import copy
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

NS='http://www.w3.org/2000/svg'
HREF='{http://www.w3.org/1999/xlink}href'
RESOURCE={'defs','clipPath','mask','filter','linearGradient','radialGradient','pattern','marker','metadata','title','desc'}
EFFECTS={'clip-path','mask','filter','marker-start','marker-mid','marker-end','stroke-dasharray','stroke-dashoffset','vector-effect'}


def tag(node):return node.tag.rsplit('}',1)[-1]


def inline(node):
    for part in node.attrib.pop('style','').split(';'):
        if ':' in part:
            key,value=part.split(':',1)
            node.set(key.strip(),value.strip())


def prepare(source, destination, *, application):
    tree=ET.parse(source);root=tree.getroot()
    for node in root.iter():inline(node)
    definitions={node.get('id'):copy.deepcopy(node) for node in root.iter() if node.get('id')}
    counts=Counter()

    def paint(value,seen=()):
        match=re.fullmatch(r'url\(\s*[\x22\x27]?#([^\x22\x27)]+)[\x22\x27]?\s*\)(?:\s+(.*))?',value)
        if not match:return value
        ident=match.group(1)
        if ident in seen:return match.group(2) or '#000000'
        resource=definitions.get(ident)
        if resource is not None:
            stops=[n for n in resource.iter() if tag(n)=='stop']
            if stops:
                counts['gradient_to_first_stop']+=1
                return stops[0].get('stop-color','#000000')
            href=resource.get('href',resource.get(HREF,''))
            if href.startswith('#'):return paint('url('+href+')',seen+(ident,))
        counts['unresolved_paint_to_solid']+=1
        return match.group(2) or '#000000'

    def clean(node,chain=()):
        for key in list(node.attrib):
            if key in EFFECTS:
                counts['ignored_'+key]+=1;node.attrib.pop(key)
        for key in ('fill','stroke'):
            if key in node.attrib:node.set(key,paint(node.get(key)))
        if application=='ppt' and node.get('fill-rule')=='evenodd':
            node.set('fill-rule','nonzero');counts['ppt_native_compound_fill']+=1
        if tag(node)=='text':
            textpaths=[n for n in node if tag(n)=='textPath']
            if textpaths:
                # Keep live label content at the source curve anchor and tangent.
                tp=textpaths[0];href=tp.get('href',tp.get(HREF,''))
                ref=definitions.get(href.lstrip('#'))
                if ref is not None and ref.get('d'):
                    from svgpathtools import parse_path
                    path=parse_path(ref.get('d'));length=path.length()
                    offset=tp.get('startOffset','0')
                    distance=float(offset.rstrip('%'))*(length/100 if offset.endswith('%') else 1)
                    position=path.ilength(max(0,min(length,distance))) if length else 0
                    point=path.point(position);tangent=path.derivative(position)
                    angle=math.degrees(math.atan2(tangent.imag,tangent.real))
                    node.set('x',str(point.real));node.set('y',str(point.imag))
                    node.set('transform',node.get('transform','')+f' rotate({angle} {point.real} {point.imag})')
                counts['text_on_curve_to_live_label']+=len(textpaths)
            if len(node):
                contents=''.join(node.itertext())
                for child in list(node):node.remove(child)
                node.text=contents
        for child in list(node):
            if tag(child) in RESOURCE:
                node.remove(child);continue
            if tag(child)=='use':
                href=child.get('href',child.get(HREF,''))
                ident=href.lstrip('#')
                if not href.startswith('#') or ident not in definitions or ident in chain:
                    raise ValueError('Cannot directly map unresolved/cyclic SVG use: '+ident)
                replacement=ET.Element('{'+NS+'}g',dict(child.attrib))
                for key in ('href',HREF,'x','y'):replacement.attrib.pop(key,None)
                replacement.set('transform',child.get('transform','')+f" translate({child.get('x','0')} {child.get('y','0')})")
                original=copy.deepcopy(definitions[ident])
                replacement.append(original)
                index=list(node).index(child);node.remove(child);node.insert(index,replacement)
                clean(replacement,chain+(ident,));counts['expanded_use']+=1
            else:clean(child,chain)

    clean(root)
    # Viewport positioning remains in the patched bundled parser. The direct
    # mapping policy intentionally does not apply viewport clipping.
    used_ids=set()
    for index,node in enumerate(root.iter()):
        if node is not root and tag(node)=='svg':
            node.set('overflow','visible')
        ident=node.get('id')
        if ident in used_ids:
            replacement_id=f'{ident}__instance_{index}'
            while replacement_id in used_ids:replacement_id+='x'
            node.set('id',replacement_id)
        if node.get('id'):used_ids.add(node.get('id'))
    ET.register_namespace('',NS)
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    tree.write(destination,encoding='utf-8',xml_declaration=True)
    return {'mode':'bundled-direct-v4','application':application,'source':str(Path(source).resolve()),
            'mapping_svg':str(destination.resolve()),'adjustments':dict(counts),
            'geometry':'Source path coordinates, transforms, order and subpaths retained; no image recognition, tracing or culling.'}
