"""Deliver the returned vector SVG; optionally open it in Illustrator."""
import json
import os
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import client as c

MODE = 'svg-delivery-v1'


def verified_source(directory):
    directory = Path(directory).resolve()
    state = c.read_job(directory) if hasattr(c, 'read_job') else c.read(directory/'job.json')
    if state['state'] == 'stopped':
        raise c.ClientError('Task is stopped; resume explicitly before delivery')
    current = os.environ.get('CODEX_THREAD_ID')
    if current and current != state['thread_id']:
        raise c.ClientError('Continue delivery in the originating chat')
    prices = getattr(c, 'ACCEPTED_PRICES', (c.PRICE,))
    prefix = 'cfp_' if c.PRICE == 20 else 'fgp_'
    if state.get('service', c.PREFIX) != c.PREFIX or not str(state.get('job_id', '')).startswith(prefix):
        raise c.ClientError('Task belongs to another service')
    if not state.get('svg') or state.get('charged_credits') not in prices:
        raise c.ClientError('No verified returned SVG')
    svg = Path(state['svg'])
    if svg.resolve() != directory/'result.svg' or not svg.is_file():
        raise c.ClientError('Returned SVG missing or outside task directory')
    data = svg.read_bytes()
    if c.sha(data) != state['svg_sha256']:
        raise c.ClientError('Returned SVG changed')
    c.validate_svg(data)
    return state, svg, data


def export_svg(directory, *, font_family=None):
    directory = Path(directory).resolve()
    with c.Lock(directory/'conversion.lock'):
        state, source, data = verified_source(directory)
        font = (font_family or state.get('font_family') or 'Times New Roman').strip()
        if not font or any(ord(ch) < 32 for ch in font):
            raise c.ClientError('Invalid font family')
        root = ET.fromstring(data)
        text_nodes = [n for n in root.iter() if n.tag.split('}')[-1] in ('text', 'tspan', 'textPath')]
        if text_nodes:
            # Change only font selection; retain geometry, clips, gradients and order.
            css_font = font.replace('\\', '\\\\').replace('"', '\\"')
            for node in text_nodes:
                node.set('font-family', font)
                style = node.get('style', '').rstrip().rstrip(';')
                node.set('style', style + ';font-family:"' + css_font + '" !important;')
            ET.register_namespace('', 'http://www.w3.org/2000/svg')
            ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
            data = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        c.validate_svg(data)
        destination = directory/'deliverables'
        destination.mkdir(exist_ok=True)
        output = destination/('figure-' + c.sha(data)[:12] + '.svg')
        if not output.is_file() or output.read_bytes() != data:
            temp = output.with_name(output.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                with temp.open('xb') as f:
                    f.write(data); f.flush(); os.fsync(f.fileno())
                os.replace(temp, output)
            finally:
                temp.unlink(missing_ok=True)
        result = {'svg': str(output), 'original_svg': str(source), 'format': 'svg'}
        c.write(directory/'svg-output.json', {
            **result, 'mode': MODE, 'source_sha256': state['svg_sha256'],
            'sha256': c.sha(data), 'font_family': font})
        c.update(directory, conversion='svg_ready', conversion_mode=MODE,
                 font_family=font, deliverables=result, last_error=None)
        return result


def convert(directory, *, file_only=False, font_family=None):
    """New PPT selections use bundled native paths; old callbacks keep SVG delivery."""
    state, _, _ = verified_source(directory)
    if state.get('ppt_delivery') in ('native-paths-v1','native-paths-v2'):
        return export_ppt(directory, font_family=font_family)
    return export_svg(directory, font_family=font_family)


def export_ppt(directory, *, font_family=None, illustrator=False):
    directory = Path(directory).resolve()
    export_svg(directory, font_family=font_family)
    with c.Lock(directory/'conversion.lock'):
        state, receipt = verified_output(directory)
        # Record the selected output before conversion so failure cannot complete as SVG-only.
        c.update(directory, ppt_delivery='native-paths-v2', conversion='ppt_converting')
        destination = directory/'deliverables'/('ppt-'+uuid.uuid4().hex[:12])
        command = [sys.executable, '-X', 'utf8', str(Path(__file__).with_name('powerpoint_native.py')),
                   '--svg', receipt['svg'], '--output', str(destination)]
        if illustrator: command.append('--illustrator')
        try:
            process = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                     errors='replace', timeout=300,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            c.update(directory, conversion='ppt_failed', last_error='Native PPT conversion interrupted; SVG retained')
            raise c.ClientError('Native PPT conversion interrupted; SVG retained. Retry the same task') from exc
        if process.returncode:
            c.update(directory, conversion='ppt_failed', last_error='Native PPT or actual display check failed; SVG retained')
            try: message=json.loads(process.stdout.strip()).get('error','Conversion failed')
            except ValueError: message='Native PPT conversion failed'
            raise c.ClientError(str(message)[:800]+'; original SVG retained; no new order needed')
        record = destination/'native.json'
        if not record.is_file(): raise c.ClientError('Native PPT receipt missing')
        native = c.read(record)
        c.write(directory/'ppt-output.json', {**native, 'svg_sha256':receipt['sha256']})
        native = verified_ppt(directory, receipt)
        result = {key:native[key] for key in ('pptx','preview','comparison_page')}
        result.update(svg=receipt['svg'], original_svg=receipt['original_svg'], text_mode='editable_text')
        c.update(directory, conversion='ppt_review_required', deliverables=result, last_error=None)
        return result


def verified_ppt(directory, svg_receipt):
    directory = Path(directory).resolve()
    path = directory/'ppt-output.json'
    if not path.is_file(): raise c.ClientError('Export and review editable PPTX before completing')
    receipt = c.read(path)
    if receipt.get('mode') != 'native-paths-v2' or receipt.get('svg_sha256') != svg_receipt['sha256'] or receipt.get('source_sha256') != svg_receipt['sha256']:
        raise c.ClientError('PPTX receipt does not match the current SVG')
    for key in ('pptx','preview','report'):
        file = Path(receipt.get(key, '')).resolve()
        if directory/'deliverables' not in file.parents or not file.is_file() or c.sha(file.read_bytes()) != receipt.get(key+'_sha256'):
            raise c.ClientError('PPTX display evidence changed or is missing: '+key)
    from display_check import inspect_pptx
    audit=inspect_pptx(receipt['pptx'])
    if receipt.get('text_mode') != 'editable_text' or receipt.get('outlined_text') is not False or receipt.get('native_text_runs') != audit['counts_by_type']['17']:
        raise c.ClientError('PPTX must preserve text as editable text boxes; rebuild this older output')
    if not (audit['native_freeforms'] or audit['counts_by_type']['17']) or audit['svg_graphics'] or audit['raster_pictures']:
        raise c.ClientError('PPTX is not a native editable-path document')
    report=c.read(receipt['report'])
    if report.get('status') != 'review_required' or report.get('source_sha256') != svg_receipt['sha256']:
        raise c.ClientError('Actual display checks are incomplete or stale')
    if report.get('powerpoint',{}).get('source',{}).get('sha256') != receipt['pptx_sha256']:
        raise c.ClientError('PowerPoint preview belongs to a different PPTX')
    for key in ('svg','powerpoint','illustrator'):
        evidence=report.get(key,{})
        if evidence.get('status')=='rendered':
            file=Path(evidence.get('preview','')).resolve()
            if directory/'deliverables' not in file.parents or not file.is_file() or c.sha(file.read_bytes()) != evidence.get('preview_sha256'):
                raise c.ClientError('Display preview changed since validation: '+key)
    return receipt


def verified_output(directory):
    directory = Path(directory).resolve()
    state, _, _ = verified_source(directory)
    receipt_path = directory/'svg-output.json'
    if not receipt_path.is_file():
        raise c.ClientError('Export SVG before delivery')
    receipt = c.read(receipt_path)
    if receipt.get('mode') != MODE or receipt.get('source_sha256') != state['svg_sha256']:
        raise c.ClientError('Export the current SVG before delivery')
    path = Path(receipt['svg'])
    if path.resolve().parent != directory/'deliverables' or not path.is_file():
        raise c.ClientError('Delivery SVG missing or outside task directory')
    data = path.read_bytes()
    if c.sha(data) != receipt.get('sha256'):
        raise c.ClientError('Delivery SVG changed since validation')
    c.validate_svg(data)
    return state, receipt


def import_illustrator(directory):
    directory = Path(directory).resolve()
    with c.Lock(directory/'conversion.lock'):
        state, receipt = verified_output(directory)
        if state.get('application') != 'ai':
            raise c.ClientError('Illustrator import was not selected for this task')
        if os.name != 'nt':
            raise c.ClientError('Automatic Illustrator import requires Windows; the SVG is ready')
        output = directory/'deliverables'/('ai-' + uuid.uuid4().hex[:12])
        script = Path(__file__).with_name('illustrator_native.py')
        try:
            process = subprocess.run(
                [sys.executable, '-X', 'utf8', str(script), '--svg', receipt['svg'], '--output', str(output)],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise c.ClientError('Illustrator save could not be confirmed; SVG is preserved, retry the same task') from exc
        if process.returncode:
            raise c.ClientError('Illustrator conversion failed; SVG is preserved: ' + process.stderr[-1500:])
        try:
            result = json.loads(process.stdout.strip())
        except ValueError:
            raise c.ClientError('Illustrator save receipt missing; SVG is preserved') from None
        c.write(directory/'illustrator-import.json', result)
        return verified_illustrator(directory, receipt)


def verified_illustrator(directory, receipt):
    imported = directory/'illustrator-import.json'
    if not imported.is_file():
        raise c.ClientError('Import and save this SVG in Illustrator before delivery')
    result = c.read(imported)
    if (result.get('mode') != 'illustrator-native-v1' or not result.get('opened') or
            result.get('svg_sha256') != receipt['sha256'] or result.get('text_mode') != 'editable_text'):
        raise c.ClientError('Save the current SVG as native AI with editable text before delivery')
    for key in ('ai','preview','reference_preview','audit','report','comparison_page','path'):
        path = Path(result.get(key,''))
        if (not path.is_file() or not path.resolve().is_relative_to(directory/'deliverables') or
                c.sha(path.read_bytes()) != result.get('hashes',{}).get(key)):
            raise c.ClientError('Illustrator output or visual evidence changed: ' + key)
    audit = c.read(result['audit'])
    if not all(audit.get(k) for k in ('saved_and_reopened','text_content_matches','aspect_ratio_matches')):
        raise c.ClientError('Illustrator text/canvas verification incomplete')
    if audit.get('raster_items') or audit.get('placed_items'):
        raise c.ClientError('Illustrator delivery is not fully native artwork')
    return result


def complete(directory, *, visual_checked):
    directory = Path(directory).resolve()
    with c.Lock(directory/'conversion.lock'):
        state, receipt = verified_output(directory)
        if not visual_checked:
            raise c.ClientError('Actual SVG visual verification required')
        native = verified_ppt(directory, receipt) if state.get('ppt_delivery') in ('native-paths-v1','native-paths-v2') else None
        adobe = verified_illustrator(directory, receipt) if state.get('application') == 'ai' else None
        updated = c.update(directory, state='delivered', conversion='complete', visual_checked=True)
        if updated['state'] != 'delivered':
            raise c.ClientError('Task stopped before delivery')
        result = {key: receipt[key] for key in ('svg', 'original_svg')}
        if native: result.update({key:native[key] for key in ('pptx','preview','comparison_page')})
        if adobe: result.update({key:adobe[key] for key in ('ai','preview','comparison_page')})
        return result
