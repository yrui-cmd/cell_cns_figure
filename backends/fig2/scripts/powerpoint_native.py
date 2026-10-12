"""Build native editable PowerPoint paths and actual cross-application evidence."""
import argparse
import json
from pathlib import Path
from display_check import DisplayError, run, sha, inspect_pptx

MODE = 'native-paths-v2'


def convert(svg, output, *, illustrator=False):
    from svg_native_geometry import build
    svg, output = Path(svg).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source_hash = sha(svg)
    result = build(svg, output)
    from native_text import calibrate_baselines
    result['text_baseline_calibration']=calibrate_baselines(result['pptx'],output/'font-calibration')
    report = run(svg, output/'display', pptx=result['pptx'], illustrator=illustrator)
    audit = inspect_pptx(result['pptx'])
    if not (audit['native_freeforms'] or audit['counts_by_type']['17']) or audit['raster_pictures'] or audit['svg_graphics']:
        raise DisplayError('PPTX must contain native vector paths, without embedded pictures')
    if report['status'] == 'incomplete':
        raise DisplayError('Actual display check is incomplete; SVG and partial files retained at '+str(output))
    if sha(svg) != source_hash:
        raise DisplayError('Source changed during conversion; rebuild before delivery')
    result.update(mode=MODE, source_sha256=source_hash, pptx_sha256=sha(result['pptx']),
                  preview=report['powerpoint']['preview'], preview_sha256=report['powerpoint']['preview_sha256'],
                  report=report['report'], report_sha256=sha(report['report']),
                  comparison_page=report['comparison_page'], visual_review_required=True,
                  svg_graphics=0, raster_pictures=0)
    (output/'native.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--svg', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--illustrator', action='store_true')
    a = p.parse_args()
    try:
        result = convert(a.svg, a.output, illustrator=a.illustrator)
        print(json.dumps({k:result[k] for k in ('pptx','preview','comparison_page','native_freeforms')}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({'error':str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__': raise SystemExit(main())
