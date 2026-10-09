"""Compatibility entry point; all code is bundled within this Skill."""
import runpy
import sys
from pathlib import Path
scripts = Path(__file__).resolve().parents[3] / 'native' / 'scripts'
sys.path.insert(0, str(scripts))
if __name__ == '__main__':
    runpy.run_path(str(scripts / 'run_from_svg.py'), run_name='__main__')
