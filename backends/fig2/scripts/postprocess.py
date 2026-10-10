"""Deliver the returned vector SVG; optionally open it in Illustrator."""
import json
import os
import subprocess
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
    """Compatibility for old callbacks; now exports SVG without desktop conversion."""
    return export_svg(directory, font_family=font_family)


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
        from illustrator_svg import expand
        try:
            data, marker_count = expand(Path(receipt['svg']).read_bytes())
        except (ValueError, KeyError, TypeError) as exc:
            raise c.ClientError('Illustrator marker preparation failed; original SVG is preserved: ' + str(exc)) from exc
        c.validate_svg(data)
        imported_svg = Path(receipt['svg'])
        if marker_count:
            imported_svg = directory/'deliverables'/('illustrator-' + c.sha(data)[:12] + '.svg')
            if not imported_svg.is_file() or imported_svg.read_bytes() != data:
                temp = imported_svg.with_name(imported_svg.name+'.'+uuid.uuid4().hex+'.tmp')
                try:
                    with temp.open('xb') as f:
                        f.write(data); f.flush(); os.fsync(f.fileno())
                    os.replace(temp, imported_svg)
                finally:
                    temp.unlink(missing_ok=True)
        script = Path(__file__).with_name('import_illustrator.ps1')
        try:
            process = subprocess.run(
                ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                 '-File', str(script), '-SvgPath', str(imported_svg)],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise c.ClientError('Illustrator import could not be confirmed; SVG is preserved, retry the same task') from exc
        if process.returncode:
            raise c.ClientError('Illustrator import failed; open Illustrator and retry the same task. SVG is preserved')
        try:
            result = json.loads(process.stdout.strip())
        except ValueError:
            raise c.ClientError('Illustrator import could not be confirmed; SVG is preserved') from None
        if not result.get('opened') or Path(result.get('path', '')).resolve() != imported_svg.resolve():
            raise c.ClientError('Illustrator import receipt mismatch')
        result['expanded_markers'] = marker_count
        c.write(directory/'illustrator-import.json', {**result, 'svg_sha256': receipt['sha256'], 'import_sha256': c.sha(data)})
        return {**result, 'svg': receipt['svg']}


def complete(directory, *, visual_checked):
    directory = Path(directory).resolve()
    with c.Lock(directory/'conversion.lock'):
        state, receipt = verified_output(directory)
        if not visual_checked:
            raise c.ClientError('Actual SVG visual verification required')
        if state.get('application') == 'ai':
            imported = directory/'illustrator-import.json'
            if not imported.is_file() or c.read(imported).get('svg_sha256') != receipt['sha256']:
                raise c.ClientError('Import this SVG into Illustrator before completing the selected delivery')
        updated = c.update(directory, state='delivered', conversion='complete', visual_checked=True)
        if updated['state'] != 'delivered':
            raise c.ClientError('Task stopped before delivery')
        return {key: receipt[key] for key in ('svg', 'original_svg')}
