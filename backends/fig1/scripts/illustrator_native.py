"""Save and reopen native Illustrator artwork; retain live text and visual evidence."""
import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess

from display_check import DisplayError, canvas, compare_images, sha, write_report
from illustrator_svg import expand

MODE = 'illustrator-native-v1'


def run(svg, output):
    svg = Path(svg).resolve()
    data = svg.read_bytes()
    dimensions = canvas(data)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output/'source.svg'
    source.write_bytes(data)
    expanded, count = expand(data)
    prepared = output/'illustrator-source.svg'
    prepared.write_bytes(expanded)
    ai, preview, audit_file = output/'editable.ai', output/'illustrator.png', output/'audit.json'
    process = subprocess.run([
        'powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', str(Path(__file__).with_name('import_illustrator.ps1')),
        '-SvgPath', str(prepared), '-AiPath', str(ai), '-PreviewPath', str(preview),
        '-AuditPath', str(audit_file)], capture_output=True, text=True, encoding='utf-8',
        errors='replace', timeout=180, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if process.returncode:
        raise DisplayError('Illustrator save/reopen failed; original SVG retained: '+process.stderr[-1500:])
    receipt = json.loads(process.stdout.strip())
    if not receipt.get('opened') or Path(receipt.get('path','')).resolve() != prepared:
        raise DisplayError('Illustrator import receipt mismatch')
    if not all(p.is_file() and p.stat().st_size for p in (ai, preview, audit_file)):
        raise DisplayError('Illustrator output or actual preview missing')
    if not ai.read_bytes().startswith((b'%PDF-', b'%!PS-Adobe')):
        raise DisplayError('Illustrator did not save a native AI document')
    audit = json.loads(audit_file.read_text(encoding='utf-8-sig'))
    if not audit.get('saved_and_reopened'):
        raise DisplayError('Saved Illustrator document was not reopened')
    # Capture rendered instances: a text node reused through <use> is visible more
    # than once, while definitions alone do not appear in the artwork.
    from native_text import capture
    _, text_records = capture(data)
    original_text = ''.join(row['char'] for row in text_records)
    actual_text = ''.join(row['text'] for row in audit['text'])
    if original_text.strip() and not audit['text_frames']:
        raise DisplayError('Source text did not survive as editable Illustrator text')
    if audit['raster_items'] or audit['placed_items']:
        raise DisplayError('Illustrator import contains raster or linked artwork; inspect before delivery')
    def letters(s): return Counter(c for c in s if not c.isspace())
    expected, actual = letters(original_text), letters(actual_text)
    audit['text_content_matches'] = expected == actual
    audit['missing_characters'] = dict(expected-actual)
    audit['extra_characters'] = dict(actual-expected)
    w,h = dimensions['width_px'],dimensions['height_px']
    board = audit['artboard']
    audit['aspect_ratio_matches'] = abs(abs((board[2]-board[0])/(board[1]-board[3]))/(w/h)-1)<.001
    audit_file.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    import cairosvg
    reference = output/'svg.png'
    cairosvg.svg2png(bytestring=data,write_to=str(reference),output_width=1200,
                    output_height=max(1,round(1200*h/w)),background_color='white')
    report = {'mode':MODE,'source_svg':str(svg),'source_sha256':sha(source),'canvas':dimensions,
              'status':'review_required','visual_review_required':True,
              'svg':{'status':'rendered','preview':str(reference),'renderer':'CairoSVG'},
              'illustrator':{**audit,'status':'rendered','preview':str(preview),'ai':str(ai)},
              'comparisons':{'illustrator':compare_images(reference,preview,output/'illustrator-difference.png')}}
    write_report(output,report)
    if not audit['text_content_matches'] or not audit['aspect_ratio_matches']:
        raise DisplayError('Illustrator text or canvas changed; inspect '+str(output/'index.html'))
    if sha(svg)!=sha(source): raise DisplayError('SVG changed during Illustrator conversion')
    result = {'mode':MODE,'opened':True,'path':str(prepared),'svg':str(svg),'svg_sha256':sha(source),
              'ai':str(ai),'preview':str(preview),'reference_preview':str(reference),
              'audit':str(audit_file),'report':str(output/'report.json'),'comparison_page':str(output/'index.html'),
              'paths':audit['paths'],'text_frames':audit['text_frames'],'expanded_markers':count,
              'text_mode':'editable_text','visual_review_required':True}
    result['hashes'] = {k:sha(result[k]) for k in ('ai','preview','reference_preview','audit','report','comparison_page','path')}
    (output/'native.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--svg',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.svg,args.output),ensure_ascii=False))
