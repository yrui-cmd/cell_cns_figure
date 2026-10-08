import sys
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from direct_svg import prepare


class DirectMappingTests(unittest.TestCase):
    def test_original_geometry_order_and_compound_paths_retained(self):
        data=b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100"><defs><clipPath id="clip"><rect width="10" height="10"/></clipPath><linearGradient id="paint"><stop stop-color="#ff0000"/><stop offset="1" stop-color="#0000ff"/></linearGradient><path id="ref" d="M1 2L3 4"/></defs><g transform="translate(7 9)" clip-path="url(#clip)"><path id="a" d="M0 0L40 0L40 40Z M5 5L10 5L10 10Z" fill-rule="evenodd" fill="url(#paint)"/><path id="b" d="M0 0L40 0L40 40Z"/><use href="#ref" x="3" y="4"/></g></svg>'''
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'original.svg';target=Path(directory)/'mapped.svg'
            source.write_bytes(data)
            report=prepare(source,target,application='ppt')
            self.assertEqual(source.read_bytes(),data)
            original=ET.fromstring(data);root=ET.parse(target).getroot()
            mapped=[n for n in root.iter() if n.tag.endswith('path')]
            self.assertEqual([n.get('id') for n in mapped],['a','b','ref'])
            self.assertEqual(mapped[0].get('d'),next(n for n in original.iter() if n.get('id')=='a').get('d'))
            self.assertEqual(root[0].get('transform'),'translate(7 9)')
            self.assertEqual(mapped[0].get('fill'),'#ff0000')
            self.assertEqual(report['adjustments']['ignored_clip-path'],1)
            self.assertFalse(any(n.get('clip-path') for n in root.iter()))
            self.assertEqual(report['adjustments']['expanded_use'],1)
            prepare(source,target,application='ai')
            a=next(n for n in ET.parse(target).iter() if n.get('id')=='a')
            self.assertEqual(a.get('fill-rule'),'evenodd')


if __name__=='__main__':unittest.main()
