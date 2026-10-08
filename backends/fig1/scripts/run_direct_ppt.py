"""Reuse su7 geometry and native PPT drawing, with no visibility culling stage."""
import argparse
from pathlib import Path
import subprocess
import sys


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input-svg',type=Path,required=True)
    p.add_argument('--output-root',type=Path,required=True)
    p.add_argument('--job-name',required=True)
    args=p.parse_args()
    scripts=Path(__file__).resolve().parents[4]/'cell_su7/scripts'
    output=args.output_root/args.job_name
    cache=output/'.cell-ppt-cache'
    subprocess.run([sys.executable,'-X','utf8',str(scripts/'prepare_geometry_cache.py'),
        '--input',str(args.input_svg),'--output-dir',str(cache),'--job-id',args.job_name],check=True)
    subprocess.run([sys.executable,'-X','utf8',str(scripts/'run_cell_ppt_ooxml.py'),
        '--geometry-cache',str(cache/'geometry-cache.json'),'--output-pptx',str(output/(args.job_name+'.pptx'))],check=True)


if __name__=='__main__':main()
