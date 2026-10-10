"""Expand SVG markers in an Illustrator-only copy without changing body paths."""
import copy
import math
import re
import xml.etree.ElementTree as ET

import cssselect2
import tinycss2
from svgpathtools import parse_path

NS = '{http://www.w3.org/2000/svg}'
MARKERS = ('marker-start', 'marker-mid', 'marker-end')
INHERITED = set(MARKERS) | {'marker', 'stroke', 'stroke-width', 'fill', 'color', 'fill-opacity', 'stroke-opacity', 'visibility'}


def declarations(text):
    return [(d.lower_name, tinycss2.serialize(d.value).strip(), d.important)
            for d in tinycss2.parse_declaration_list(text, skip_comments=True, skip_whitespace=True)
            if d.type == 'declaration']


def styles(root):
    matcher = cssselect2.Matcher()
    for element in root.iter(NS+'style'):
        for rule in tinycss2.parse_stylesheet(element.text or '', skip_comments=True, skip_whitespace=True):
            if rule.type == 'qualified-rule':
                for selector in cssselect2.compile_selector_list(tinycss2.serialize(rule.prelude)):
                    matcher.add_selector(selector, declarations(tinycss2.serialize(rule.content)))
    result = {}
    for wrapped in cssselect2.ElementWrapper.from_xml_root(root).iter_subtree():
        node = wrapped.etree_element
        parent = result.get(wrapped.parent.etree_element, {}) if wrapped.parent else {'fill':'black','stroke':'none','stroke-width':'1','visibility':'visible'}
        values = {k:v for k,v in parent.items() if k in INHERITED}
        ranked = {}
        def put(key, value, rank):
            keys = MARKERS if key == 'marker' else (key,)
            for k in keys:
                if k not in ranked or rank >= ranked[k][0]:ranked[k] = (rank, value)
        for key,value in node.attrib.items():put(key,value,(0,0,0,0,0,0))
        for specificity,order,pseudo,items in matcher.match(wrapped):
            if pseudo:continue
            for key,value,important in items:put(key,value,(int(important),0,*specificity,order))
        for order,(key,value,important) in enumerate(declarations(node.get('style',''))):
            put(key,value,(int(important),1,0,0,0,order))
        for key,(_,value) in ranked.items():
            values[key] = parent.get(key, '') if value == 'inherit' else value
        result[node] = values
    return result


def number(value, default=0):
    value = str(value if value is not None else default).strip()
    match = re.fullmatch(r'([-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?)(px|pt|pc|mm|cm|in)?', value)
    if not match:raise ValueError('Unsupported marker length: '+value)
    return float(match[1])*{None:1,'px':1,'pt':96/72,'pc':16,'mm':96/25.4,'cm':96/2.54,'in':96}[match[2]]


def tangent(segment, t):
    try:return segment.unit_tangent(t)
    except (ValueError, ZeroDivisionError, AssertionError):
        delta = segment.end-segment.start
        return delta/abs(delta) if delta else 0j


def anchors(node):
    tag = node.tag.split('}')[-1]
    if tag == 'path':path = parse_path(node.get('d',''))
    elif tag == 'line':
        path = parse_path('M %s %s L %s %s' % tuple(node.get(k,'0') for k in ('x1','y1','x2','y2')))
    elif tag in ('polyline','polygon'):
        pts = re.findall(r'[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?',node.get('points',''))
        if len(pts)%2:raise ValueError('Invalid marker polyline')
        path = parse_path('M '+' '.join(pts)+(' Z' if tag=='polygon' else '')) if pts else []
    else:raise ValueError('Unsupported element with markers: '+tag)
    if not path:return []
    result=[]
    for sub in path.continuous_subpaths():
        units=[(tangent(seg,0),tangent(seg,1)) for seg in sub]
        first=next((u[0] or u[1] for u in units if u[0] or u[1]),1+0j)
        last=next((u[1] or u[0] for u in reversed(units) if u[0] or u[1]),first)
        result.append(('marker-start',sub[0].start,first))
        for i in range(1,len(sub)):
            before=next((units[j][1] or units[j][0] for j in range(i-1,-1,-1) if any(units[j])),first)
            after=next((units[j][0] or units[j][1] for j in range(i,len(sub)) if any(units[j])),last)
            a,b=math.atan2(before.imag,before.real),math.atan2(after.imag,after.real)
            if b-a>math.pi:b-=2*math.pi
            if a-b>math.pi:b+=2*math.pi
            angle=(a+b)/2
            result.append(('marker-mid',sub[i].start,complex(math.cos(angle),math.sin(angle))))
        result.append(('marker-end',sub[-1].end,last))
    return result


def expand(data):
    root=ET.fromstring(data)
    computed=styles(root)
    definitions={n.get('id'):n for n in root.iter() if n.get('id')}
    parents={child:parent for parent in root.iter() for child in parent}
    expanded=0
    for node,style in list(computed.items()):
        if node.tag.split('}')[-1] not in ('path','line','polyline','polygon'):continue
        refs={key:style.get(key,'none') for key in MARKERS}
        if all(v in ('none','') for v in refs.values()):continue
        ancestor=parents.get(node)
        in_marker=False
        while ancestor is not None:
            if ancestor.tag==NS+'marker':in_marker=True;break
            ancestor=parents.get(ancestor)
        if in_marker:continue
        parent=parents[node]
        wrapper=ET.Element(NS+'g')
        # Keep the host transform/opacity on the group, shared by shaft and heads.
        for key in ('transform','opacity','clip-path','mask','filter'):
            if key in style:
                wrapper.set(key,style[key])
                node.attrib.pop(key,None)
        body_style=[(k,v,imp) for k,v,imp in declarations(node.get('style',''))
                    if k not in ('transform','opacity','clip-path','mask','filter','marker',*MARKERS)]
        for key in ('transform','opacity','clip-path','mask','filter'):
            body_style.append((key,'none' if key!='opacity' else '1',True))
        body_style.extend((k,'none',True) for k in MARKERS)
        node.set('style',';'.join(k+':'+v+(' !important' if imp else '') for k,v,imp in body_style))
        for key in MARKERS:node.attrib.pop(key,None)
        node.attrib.pop('marker',None)
        index=list(parent).index(node)
        parent.remove(node);parent.insert(index,wrapper);wrapper.append(node)
        for key,point,direction in anchors(node):
            ref=refs[key]
            if ref in ('none',''):continue
            match=re.fullmatch(r'url\([\s\x22\x27]*#([^\s\x22\x27)]+)[\s\x22\x27]*\)',ref)
            marker=definitions.get(match[1]) if match else None
            if marker is None or marker.tag!=NS+'marker':raise ValueError('Unresolved SVG marker: '+ref)
            width,height=number(marker.get('markerWidth'),3),number(marker.get('markerHeight'),3)
            if width<=0 or height<=0:continue
            view=[float(n) for n in re.split(r'[\s,]+',marker.get('viewBox',f'0 0 {width} {height}').strip())]
            x,y,w,h=view
            if w<=0 or h<=0:raise ValueError('Invalid marker viewBox')
            sx,sy=width/w,height/h
            preserve=marker.get('preserveAspectRatio','xMidYMid meet').split()
            if preserve[0]=='defer':preserve=preserve[1:]
            dx=dy=0
            if preserve[0]!='none':
                sx=sy=max(sx,sy) if 'slice' in preserve else min(sx,sy)
                dx=(width-w*sx)*(0 if 'xMin' in preserve[0] else 1 if 'xMax' in preserve[0] else .5)
                dy=(height-h*sy)*(0 if 'YMin' in preserve[0] else 1 if 'YMax' in preserve[0] else .5)
            rx,ry=number(marker.get('refX')),number(marker.get('refY'))
            orient=marker.get('orient','0')
            angle=math.degrees(math.atan2(direction.imag,direction.real)) if orient.startswith('auto') else float(orient.removesuffix('deg'))
            if orient=='auto-start-reverse' and key=='marker-start':angle+=180
            units=number(style.get('stroke-width'),1) if marker.get('markerUnits','strokeWidth')=='strokeWidth' else 1
            if units<=0:continue
            g=ET.SubElement(wrapper,NS+'g',{'transform':f'translate({point.real} {point.imag}) rotate({angle}) scale({units}) translate({-(rx-x)*sx-dx} {-(ry-y)*sy-dy})'})
            viewport=ET.SubElement(g,NS+'svg',{'width':str(width),'height':str(height),'viewBox':f'{x} {y} {w} {h}','preserveAspectRatio':marker.get('preserveAspectRatio','xMidYMid meet'),'overflow':computed[marker].get('overflow','hidden')})
            for child in marker:
                clone=copy.deepcopy(child)
                for old,new in zip(child.iter(),clone.iter()):
                    values=computed[old]
                    flattened={k:v for k,v in values.items() if k not in (*MARKERS,'marker','id','class','style','transform') and ':' not in k and not k.startswith('{')}
                    for k,v in flattened.items():
                        if v=='context-stroke':v=style.get('stroke','none')
                        elif v=='context-fill':v=style.get('fill','black')
                        if k in ('fill','stroke','fill-opacity','stroke-opacity','stroke-width','color','visibility'):
                            new.set(k,v)
                    inline=[]
                    for k,v,imp in declarations(new.get('style','')):
                        if k in ('marker',*MARKERS):continue
                        if v=='context-stroke':v=style.get('stroke','none')
                        elif v=='context-fill':v=style.get('fill','black')
                        inline.append(k+':'+v+(' !important' if imp else ''))
                    new.set('style',';'.join(inline)+';marker:none !important')
                    new.attrib.pop('id',None)
                viewport.append(clone)
            expanded+=1
    if not expanded:return data,0
    root.set('version','1.1')
    ET.register_namespace('',NS[1:-1])
    ET.register_namespace('xlink','http://www.w3.org/1999/xlink')
    return ET.tostring(root,encoding='utf-8',xml_declaration=True),expanded
