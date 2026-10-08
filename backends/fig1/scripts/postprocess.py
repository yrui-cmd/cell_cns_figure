"""Only the approved-SVG branch of cell_su7. Never invoke a paid image route."""
import json
import os
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from client import ACCEPTED_PRICES, ClientError, Lock, SKILL, read, sha, update, validate_svg, write


def dependency():
    root=SKILL.parents[2]/'cell_su7'/'scripts'
    required=('run_from_svg.py','run_illustrator.py','allocate_shibielujing_name.py','validate_vector_svg.py')
    if not all((root/f).is_file() for f in required):
        raise ClientError('缺少同级 cell_su7 的 SVG 后处理脚本，请先安装该 Skill')
    return root


def pptx_audit(path):
    with zipfile.ZipFile(path) as z:
        if z.testzip():raise ClientError('Damaged PPTX archive')
        slide=ET.fromstring(z.read('ppt/slides/slide1.xml'))
        ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
        if slide.findall('.//p:pic',ns) or slide.findall('.//a:blip',ns):
            raise ClientError('PPTX contains raster/SVG pictures instead of native objects')
        shapes=slide.findall('.//p:sp',ns)
        if not shapes:raise ClientError('PPTX has no editable native shapes')
        return {'native_shapes':len(shapes),'native_text_runs':len(slide.findall('.//a:t',ns))}


def run(command, log):
    with log.open('ab') as f:
        offset=f.tell()
        proc=subprocess.run(command,stdout=f,stderr=f)
    if proc.returncode:
        with log.open('rb') as f:
            f.seek(offset)
            detail=f.read(65536).decode('utf-8',errors='replace')
        reasons={
            'Only redundant full-canvas clipping can be removed automatically':'返回 SVG 含局部裁剪，当前转换器需要先展开裁剪，尚未生成可交付文件',
            'Even-odd compound fill requires winding normalization':'返回 SVG 的奇偶填充复合路径需要先规范化绕向，尚未生成可交付文件',
            'AI_NOT_RUNNING':'Illustrator 尚未打开，请打开 Illustrator 和测试用目标文档后继续原任务',
            'AI_DOCUMENT_REQUIRED':'Illustrator 缺少目标文档，请打开目标文档后继续原任务',
        }
        for marker,reason in reasons.items():
            if marker in detail:
                raise ClientError(reason+'；已保留 SVG，不重新付费提交')
        raise ClientError('本地转换未完成；保留已收到的 SVG 和日志，不重新付费提交')


def convert(directory, *, file_only=False):
    directory=Path(directory).resolve()
    with Lock(directory/'conversion.lock'):
        state=read(directory/'job.json')
        if state['state']=='stopped':
            raise ClientError('Task is stopped; resume explicitly before conversion')
        if not state.get('svg') or state.get('charged_credits') not in ACCEPTED_PRICES:
            raise ClientError('No verified returned SVG')
        current=os.environ.get('CODEX_THREAD_ID')
        if current and current!=state['thread_id']:
            raise ClientError('Continue conversion in the originating chat')
        svg=Path(state['svg'])
        if svg.resolve()!=directory/'result.svg' or sha(svg.read_bytes())!=state['svg_sha256']:
            raise ClientError('Returned SVG changed')
        validate_svg(svg.read_bytes())
        scripts=dependency()
        destination=directory/'editable'
        destination.mkdir(exist_ok=True)
        name=state.get('conversion_name') if state.get('conversion_mode')=='direct-path-v1' else None
        if not name:
            name=subprocess.check_output([sys.executable,str(scripts/'allocate_shibielujing_name.py'),'--root',str(destination)],text=True).strip().splitlines()[-1]
            update(directory,conversion_name=name,conversion_mode='direct-path-v1')
        output=destination/name
        from direct_svg import prepare
        mapping_svg=output/(name+'-direct.svg')
        mapping=prepare(svg,mapping_svg,application=state['application'])
        write(directory/'direct-mapping.json',mapping)
        mapping_sha=sha(mapping_svg.read_bytes())
        log=directory/'conversion.log'
        target=output/(name+('.pptx' if state['application']=='ppt' else '.ai'))
        update(directory,conversion='running')
        try:
            # Reuse a verified native output; do not redraw after a chat interruption.
            native_receipt=directory/'native-output.json'
            old=read(native_receipt) if native_receipt.exists() else {}
            reusable=old.get('mapping_sha256')==mapping_sha and old.get('conversion_mode')=='direct-path-v1' and old.get('svg_sha256')==state['svg_sha256'] and target.is_file() and old.get('native_sha256')==sha(target.read_bytes())
            if not reusable:
                route=SKILL/'scripts/run_direct_ppt.py' if state['application']=='ppt' else scripts/'run_illustrator.py'
                run([sys.executable,'-X','utf8',str(route),'--input-svg',str(mapping_svg),
                     '--output-root',str(destination),'--job-name',name],log)
            if not target.is_file() or target.stat().st_size==0:
                raise ClientError('Native output file missing')
            result={'svg':str(svg),'application':state['application'],'native':str(target)}
            if state['application']=='ppt':
                result.update(pptx_audit(target))
                preview=output/(name+'.png')
                if not file_only:
                    if os.name!='nt':raise ClientError('Live PowerPoint visualization currently requires Windows')
                    playback=output/(name+'-playback.pptx')
                    if old.get('playback_sha256') and playback.exists() and sha(playback.read_bytes())==old['playback_sha256']:
                        pass
                    else:
                        run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(scripts/'run_ppt_path_playback.ps1'),
                             '-InputPptx',str(target),'-OutputPptx',str(playback)],log)
                    result.update(pptx_audit(playback))
                    result['playback']=str(playback)
                    run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(SKILL/'scripts/preview_ppt.ps1'),
                         '-InputPptx',str(playback),'-OutputPng',str(preview)],log)
                    if not preview.is_file():raise ClientError('PowerPoint preview is missing')
                    result['preview']=str(preview)
            else:
                preview=output/(name+'.png')
                if not preview.is_file():raise ClientError('Illustrator PNG preview missing')
                result['preview']=str(preview)
            receipt={**result,'svg_sha256':state['svg_sha256'],'conversion_mode':'direct-path-v1','mapping_sha256':mapping_sha,'native_sha256':sha(target.read_bytes()),
                     'playback_sha256':sha(Path(result['playback']).read_bytes()) if result.get('playback') else None}
            write(native_receipt,receipt)
            update(directory,conversion='native_ready',deliverables=result,last_error=None)
            return result
        except Exception as e:
            update(directory,conversion='attention',last_error=type(e).__name__)
            raise


def complete(directory, *, visual_checked):
    directory=Path(directory)
    state=read(directory/'job.json')
    current=os.environ.get('CODEX_THREAD_ID')
    if state['state']=='stopped' or current and current!=state['thread_id']:
        raise ClientError('Only the active originating chat may complete this task')
    if not visual_checked or state['conversion']!='native_ready':
        raise ClientError('Native conversion and actual visual verification required')
    result=read(directory/'native-output.json')
    if sha(Path(state['svg']).read_bytes())!=state['svg_sha256'] or result['svg_sha256']!=state['svg_sha256']:
        raise ClientError('Returned SVG changed since conversion')
    if sha(Path(result['native']).read_bytes())!=result['native_sha256']:
        raise ClientError('Native file changed since validation')
    if state['application']=='ppt':pptx_audit(Path(result['native']))
    if result.get('playback') and sha(Path(result['playback']).read_bytes())!=result['playback_sha256']:
        raise ClientError('Playback file changed since validation')
    update(directory,state='delivered',conversion='complete',visual_checked=True)
    return {k:result[k] for k in ('svg','native','preview','playback') if result.get(k)}
