"""Local SVG / PowerPoint / Illustrator display evidence. No paid requests.

PowerPoint without --pptx creates a vector-SVG display deck, not native freeforms.
With --pptx, inspect and render a private copy of the actual editable deck.
"""
import argparse
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
import zipfile

from PIL import Image, ImageChops, ImageStat, ImageOps


class DisplayError(ValueError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canvas(data):
    root = ET.fromstring(data)
    if root.tag.split('}')[-1] != 'svg':
        raise DisplayError('Expected SVG')
    vb = [float(x) for x in re.split(r'[\s,]+', root.get('viewBox', '').strip()) if x]
    if vb and (len(vb) != 4 or not all(math.isfinite(x) for x in vb) or min(vb[2:]) <= 0):
        raise DisplayError('Invalid viewBox')
    def length(value, fallback):
        if value is None or value.endswith('%'):
            return fallback
        m = re.fullmatch(r'\s*([+\-\d.eE]+)\s*(px|pt|pc|mm|cm|in)?\s*', value)
        if not m:
            raise DisplayError('Unsupported canvas length: ' + value)
        return float(m[1])*{None:1,'px':1,'pt':96/72,'pc':16,'mm':96/25.4,'cm':96/2.54,'in':96}[m[2]]
    w = length(root.get('width'), vb[2] if vb else None)
    h = length(root.get('height'), vb[3] if vb else None)
    if not w or not h or not all(math.isfinite(v) and v > 0 for v in (w,h)):
        raise DisplayError('SVG needs a positive canvas')
    return {'width_px':w,'height_px':h,'viewBox':vb or [0,0,w,h],
            'preserveAspectRatio':root.get('preserveAspectRatio','xMidYMid meet')}


def inspect_ppt_shapes(shapes):
    rows = []
    def visit(items, parent=''):
        for i in range(1, items.Count+1):
            s = items.Item(i)
            kind = int(s.Type)
            row = {'name':str(s.Name),'type':kind,'parent':parent,
                   'bounds_pt':[float(s.Left),float(s.Top),float(s.Width),float(s.Height)]}
            if kind == 5:
                row['nodes'] = int(s.Nodes.Count)
            rows.append(row)
            if kind == 6:
                visit(s.GroupItems, row['name'])
    visit(shapes)
    counts = {str(k):sum(r['type'] == k for r in rows) for k in (5,6,13,17,28)}
    mode = ('mixed' if counts['5'] and (counts['28'] or counts['13']) else
            'native_paths' if counts['5'] else 'embedded_svg' if counts['28'] else 'other')
    return {'mode':mode,'counts_by_type':counts,'shapes':rows,
            'native_freeforms':counts['5'],'svg_graphics':counts['28'],'raster_pictures':counts['13']}


def inspect_pptx(path, slide_index=1):
    """Inspect saved native paths without thousands of slow cross-process COM calls."""
    ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main',
        'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
    with zipfile.ZipFile(path) as z:
        root=ET.fromstring(z.read(f'ppt/slides/slide{slide_index}.xml'))
    rows=[]
    for element in root.iter():
        tag=element.tag.split('}')[-1]
        if tag not in ('sp','grpSp','pic','graphicFrame'):continue
        kind=6 if tag=='grpSp' else 13 if tag=='pic' else 1
        if element.find('./p:spPr/a:custGeom',ns) is not None:kind=5
        elif tag=='sp' and element.find('./p:txBody',ns) is not None:kind=17
        if tag=='pic' and any(n.tag.endswith('}svgBlip') for n in element.iter()):kind=28
        name=element.find('.//p:cNvPr',ns)
        transform=element.find('./p:spPr/a:xfrm',ns)
        row={'name':name.get('name','') if name is not None else '', 'type':kind}
        if transform is not None:
            row['transform_emu']={n.tag.split('}')[-1]:n.attrib for n in transform}
        if kind==5:row['path_commands']=sum(len(n) for n in element.findall('./p:spPr/a:custGeom/a:pathLst/a:path',ns))
        rows.append(row)
    counts={str(k):sum(r['type']==k for r in rows) for k in (1,5,6,13,17,28)}
    mode='native_paths' if counts['5'] and not(counts['13'] or counts['28']) else 'mixed' if counts['5'] else 'embedded_svg' if counts['28'] else 'other'
    return {'mode':mode,'counts_by_type':counts,'shapes':rows,'native_freeforms':counts['5'],
            'svg_graphics':counts['28'],'raster_pictures':counts['13']}


def render_powerpoint(svg, output, width_px, height_px, *, pptx=None, slide_index=1):
    if os.name != 'nt':
        raise DisplayError('Actual PowerPoint preview requires Windows desktop PowerPoint')
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise DisplayError('Install the optional display requirements for PowerPoint checks') from exc
    pythoncom.CoInitialize()
    pres = None
    app = None
    try:
        app = win32com.client.Dispatch('PowerPoint.Application')
        if pptx:
            original = Path(pptx).resolve()
            if not original.is_file() or original.suffix.lower() != '.pptx':
                raise DisplayError('PPTX file missing')
            deck = output/'checked-copy.pptx'
            shutil.copy2(original, deck)
            pres = app.Presentations.Open(str(deck), -1, 0, 0)
            source = {'pptx':str(original),'sha256':sha(original)}
        else:
            deck = output/'svg-display.pptx'
            pres = app.Presentations.Add(0)
            # px -> points exactly once; one uniform scale for PowerPoint slide limits.
            k = min(.75, 4032/max(width_px,height_px))
            pres.PageSetup.SlideWidth = width_px*k
            pres.PageSetup.SlideHeight = height_px*k
            slide = pres.Slides.Add(1,12)
            pic = slide.Shapes.AddPicture(str(svg),0,-1,0,0,width_px*k,height_px*k)
            if int(pic.Type) != 28:
                raise DisplayError('PowerPoint did not preserve the SVG as a vector graphic')
            pic.Name = 'Cell SVG source — vector display, not converted paths'
            pres.SaveAs(str(deck),24)
            source = {'svg':str(svg),'sha256':sha(svg)}
        if not 1 <= slide_index <= pres.Slides.Count:
            raise DisplayError('Slide index outside presentation')
        slide = pres.Slides.Item(slide_index)
        audit = inspect_pptx(deck,slide_index)
        w,h = float(pres.PageSetup.SlideWidth),float(pres.PageSetup.SlideHeight)
        preview = output/'powerpoint.png'
        slide.Export(str(preview),'PNG',1200,max(1,round(1200*h/w)))
        if not preview.is_file():
            raise DisplayError('PowerPoint preview was not exported')
        return {**audit,'status':'rendered','preview':str(preview),'preview_sha256':sha(preview),
                'presentation':str(deck),'presentation_sha256':sha(deck),'source':source,
                'slide_index':slide_index,'slide_size_pt':[w,h],'version':str(app.Version)}
    finally:
        # Close only the private presentation opened/created here, never the user's documents/app.
        if pres is not None:
            try: pres.Close()
            except Exception: pass
        pres = None
        app = None
        pythoncom.CoUninitialize()


def compare_images(reference, candidate, destination):
    def opaque(path):
        with Image.open(path) as f:
            rgba = f.convert('RGBA')
        white = Image.new('RGBA',rgba.size,'white')
        return Image.alpha_composite(white,rgba).convert('RGB')
    a,b = opaque(reference),opaque(candidate)
    ratios = [a.width/a.height,b.width/b.height]
    # Resize proportionally; never stretch a mismatched canvas to conceal a coordinate error.
    b = ImageOps.contain(b,a.size,Image.Resampling.LANCZOS)
    fitted = Image.new('RGB',a.size,'white')
    fitted.paste(b,((a.width-b.width)//2,(a.height-b.height)//2))
    diff = ImageChops.difference(a,fitted)
    # White means identical; dark/color marks highlight actual pixel differences.
    ImageChops.invert(diff).save(destination)
    return {'mean_absolute_channel_error':sum(ImageStat.Stat(diff).mean)/3,
            'aspect_ratio_difference':abs(ratios[0]-ratios[1]),
            'difference_preview':str(destination),'automatic_visual_pass':False}


def write_report(output, report):
    panels=[]
    for key,title in [('svg','SVG reference'),('powerpoint','Actual PowerPoint'),('illustrator','Actual Illustrator')]:
        info=report.get(key,{})
        if info.get('preview'):
            filename=Path(info['preview']).name
            panels.append('<section><h2>'+title+'</h2><img src="'+html.escape(filename,quote=True)+'"><p>'+html.escape(info.get('mode',info.get('status','')) )+'</p></section>')
        else:
            panels.append('<section><h2>'+title+'</h2><p>'+html.escape(info.get('error','Not requested'))+'</p></section>')
    report_file=output/'report.json'
    report_file.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    page='''<!doctype html><meta charset="utf-8"><title>Cell display comparison</title>
<style>body{font:16px system-ui;margin:24px;background:#f5f6f8;color:#24303a}.panels{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}section{background:white;padding:16px;border-radius:12px}h2{font-size:18px}img{width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}a{color:#286190}</style>
<h1>SVG / PowerPoint / Illustrator</h1><p>实际软件渲染对照。embedded_svg 是嵌入矢量，native_paths 才表示存在原生路径。数值差异不代替人工审图，也不自动判定一致。</p><div class="panels">'''+''.join(panels)+'</div>'
    for name,cmp in report.get('comparisons',{}).items():
        page+='<p><a href="'+html.escape(Path(cmp['difference_preview']).name,quote=True)+'">'+html.escape(name)+' difference</a></p>'
    page+='<details><summary>路径类型、坐标及检查记录</summary><pre>'+html.escape(json.dumps(report,ensure_ascii=False,indent=2))+'</pre></details>'
    (output/'index.html').write_text(page,encoding='utf-8')


def run(svg, output, *, pptx=None, slide_index=1, illustrator=False):
    svg=Path(svg).resolve()
    if not svg.is_file():raise DisplayError('SVG missing')
    data=svg.read_bytes();dimensions=canvas(data)
    output=Path(output).resolve()
    # A fresh report directory prevents stale previews from being counted as current evidence.
    output.mkdir(parents=True,exist_ok=False)
    source=output/'source.svg';source.write_bytes(data)
    report={'source_svg':str(svg),'source_sha256':sha(source),'canvas':dimensions,
            'visual_review_required':True,'status':'review_required','comparisons':{}}
    try:
        import cairosvg
        preview=output/'svg.png'
        cairosvg.svg2png(bytestring=data,write_to=str(preview),output_width=1200,
                        output_height=max(1,round(1200*dimensions['height_px']/dimensions['width_px'])),
                        background_color='white')
        report['svg']={'status':'rendered','preview':str(preview),'preview_sha256':sha(preview),'renderer':'CairoSVG'}
    except Exception as exc:
        report['svg']={'status':'failed','error':str(exc)}
    try:
        report['powerpoint']=render_powerpoint(source,output,dimensions['width_px'],dimensions['height_px'],pptx=pptx,slide_index=slide_index)
    except Exception as exc:
        report['powerpoint']={'status':'failed','error':str(exc)}
    if illustrator:
        try:
            from illustrator_svg import expand
            expanded,count=expand(data)
            ai_svg=output/'illustrator-source.svg';ai_svg.write_bytes(expanded)
            preview=output/'illustrator.png'
            proc=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                '-File',str(Path(__file__).with_name('import_illustrator.ps1')),'-SvgPath',str(ai_svg),'-PreviewPath',str(preview)],
                capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if proc.returncode:raise DisplayError('Illustrator preview failed; original SVG retained')
            receipt=json.loads(proc.stdout.strip())
            if not receipt.get('opened') or not preview.is_file():raise DisplayError('Illustrator preview not confirmed')
            report['illustrator']={**receipt,'status':'rendered','preview_sha256':sha(preview),'expanded_markers':count}
        except Exception as exc:
            report['illustrator']={'status':'failed','error':str(exc)}
    if report['svg']['status']=='rendered':
        for key in ('powerpoint','illustrator'):
            if report.get(key,{}).get('status')=='rendered':
                report['comparisons'][key]=compare_images(report['svg']['preview'],report[key]['preview'],output/(key+'-difference.png'))
    if any(report.get(k,{}).get('status')=='failed' for k in ('svg','powerpoint','illustrator')):
        report['status']='incomplete'
    report['report']=str(output/'report.json');report['comparison_page']=str(output/'index.html')
    write_report(output,report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--svg',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--pptx',type=Path);p.add_argument('--slide',type=int,default=1)
    p.add_argument('--illustrator',action='store_true')
    a=p.parse_args()
    try:
        result=run(a.svg,a.output,pptx=a.pptx,slide_index=a.slide,illustrator=a.illustrator)
        print(json.dumps({k:result[k] for k in ('status','report','comparison_page')},ensure_ascii=False))
        return 1 if result['status']=='incomplete' else 0
    except Exception as exc:
        print(json.dumps({'status':'failed','error':str(exc)},ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
