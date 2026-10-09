import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import progress_panel as p


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = {'created_at':1000, 'updated_at':1000, 'state':'waiting',
                      'credential_file':'DO_NOT_EXPOSE', 'text':'PRIVATE_INPUT'}
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        (self.root/'job.json').write_text(json.dumps(self.state), encoding='utf-8')

    def complete(self):
        data = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0L1 1"/></svg>'
        (self.root/'result.svg').write_bytes(data)
        self.state.update(svg=str(self.root/'result.svg'), svg_sha256=hashlib.sha256(data).hexdigest(),
                          result_received_at=1100, state='ready')
        self.save()

    def test_estimate_caps_at_99_even_after_an_hour(self):
        self.assertEqual(p.snapshot(self.root,now=1000)['percent'],0)
        self.assertEqual(p.snapshot(self.root,now=2800)['percent'],50)
        self.assertEqual(p.snapshot(self.root,now=4600)['percent'],99)
        self.assertEqual(p.snapshot(self.root,now=90000)['percent'],99)

    def test_remote_completion_without_local_file_is_not_100(self):
        self.state.update(remote_status='completed',state='ready')
        self.save()
        self.assertFalse(p.snapshot(self.root,now=90000)['complete'])

    def test_only_verified_local_result_finishes_early(self):
        self.complete()
        snapshot=p.snapshot(self.root,now=1200)
        self.assertEqual(snapshot['percent'],100)
        self.assertEqual(snapshot['elapsed'],100)
        (self.root/'result.svg').write_bytes(b'corrupted')
        self.assertFalse(p.snapshot(self.root,now=1200)['complete'])

    def test_pause_and_attention_never_mean_complete(self):
        for state in ['stopped','attention','wake_uncertain']:
            self.state['state']=state;self.save()
            self.assertFalse(p.snapshot(self.root,now=90000)['complete'])

    def test_local_http_receives_state_changes_without_any_remote_calls(self):
        server=p.make_server(self.root,'test-capability')
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}/test-capability/'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(base+'status') as response:
                before=json.load(response)
                self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertFalse(before['complete'])
            self.assertNotIn('DO_NOT_EXPOSE',json.dumps(before))
            self.assertNotIn('PRIVATE_INPUT',json.dumps(before))
            self.complete()
            with opener.open(base+'status') as response:
                self.assertEqual(json.load(response)['percent'],100)
            with self.assertRaises(urllib.error.HTTPError) as caught:
                opener.open(base.replace('test-capability','wrong')+'status')
            self.assertEqual(caught.exception.code,404)
            request=urllib.request.Request(base+'status',headers={'Host':'example.org'})
            with self.assertRaises(urllib.error.HTTPError) as caught:opener.open(request)
            self.assertEqual(caught.exception.code,403)
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
