"""Draw every mapped SVG path through the bundled geometry and PPT writer."""
import argparse
from pathlib import Path
import subprocess
import sys

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input-svg',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--job-name',required=True)
    args=parser.parse_args()
    if not args.job_name.startswith('shibielujing') or not args.job_name[len('shibielujing'):].isdigit():
        parser.error('job-name must use shibielujingN')
    scripts=Path(__file__).resolve().parents[3]/'native/scripts'
    output=args.output_root/args.job_name
    cache=output/'.cell-ppt-cache'
    commands=[
        [str(scripts/'prepare_geometry_cache.py'),'--input',str(args.input_svg),'--output-dir',str(cache),'--job-id',args.job_name],
        [str(scripts/'run_cell_ppt_ooxml.py'),'--geometry-cache',str(cache/'geometry-cache.json'),'--output-pptx',str(output/(args.job_name+'.pptx'))],
    ]
    for command in commands:
        subprocess.run([sys.executable,'-X','utf8',*command],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

if __name__=='__main__':main()
