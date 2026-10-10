import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from illustrator_svg import expand, NS


class MarkerCompatibilityTests(unittest.TestCase):
    def svg(self,body,extra=''):
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300">'
                '<defs><marker id="a" viewBox="0 0 10 10" refX="10" refY="5" '
                'markerWidth="10" markerHeight="10" orient="auto-start-reverse" markerUnits="userSpaceOnUse">'
                '<path d="M0 0L10 5L0 10Z" style="fill:context-stroke"/></marker></defs>'+extra+body+'</svg>').encode()

    def test_preserves_bezier_shaft_and_host_transform(self):
        d='M20 100 C50 20 150 20 200 100'
        src=self.svg(f'<path id="shaft" d="{d}" transform="translate(10 20)" opacity="0.5" fill="none" stroke="#123456" marker-end="url(#a)"/>')
        data,count=expand(src);root=ET.fromstring(data)
        self.assertEqual(count,1)
        shaft=next(n for n in root.iter(NS+'path') if n.get('id')=='shaft')
        self.assertEqual(shaft.get('d'),d)
        host=next(n for n in root.iter(NS+'g') if shaft in list(n))
        self.assertEqual(host.get('transform'),'translate(10 20)')
        self.assertEqual(host.get('opacity'),'0.5')
        self.assertIsNone(shaft.get('marker-end'))
        self.assertEqual(shaft.get('stroke'),'#123456')
        self.assertIn('fill:#123456',data.decode())

    def test_css_start_mid_end_are_all_expanded(self):
        src=self.svg('<polyline class="arrow" points="10,10 100,10 100,80"/>','<style>.arrow { fill:none; stroke:#456789; marker-start:url(#a);marker-mid:url(#a);marker-end:url(#a) }</style>')
        data,count=expand(src);root=ET.fromstring(data)
        self.assertEqual(count,3)
        transforms=[n.get('transform','') for n in root.iter(NS+'g')]
        self.assertTrue(any('translate(10.0 10.0) rotate(180.0)' in x for x in transforms))
        self.assertTrue(any('translate(100.0 10.0) rotate(45.0)' in x for x in transforms))
        self.assertTrue(any('translate(100.0 80.0) rotate(90.0)' in x for x in transforms))

    def test_preserves_nonmarker_bytes(self):
        src=self.svg('<circle cx="25" cy="30" r="10"/>')
        self.assertEqual(expand(src),(src,0))

    def test_unresolved_marker_is_not_silently_dropped(self):
        src=self.svg('<path d="M0 0L20 20" marker-end="url(#missing)"/>')
        with self.assertRaisesRegex(ValueError,'Unresolved'):
            expand(src)

    def test_marker_units_and_reference_point(self):
        src=self.svg('<line x1="10" y1="20" x2="110" y2="20" stroke-width="4" marker-end="url(#a)"/>')
        src=src.replace(b'userSpaceOnUse',b'strokeWidth')
        data,count=expand(src)
        self.assertEqual(count,1)
        self.assertIn(b'scale(4.0) translate(-10.0 -5.0)',data)


if __name__=='__main__':unittest.main()
