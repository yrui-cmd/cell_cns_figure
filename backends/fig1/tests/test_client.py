"""Isolated regressions. No real keys, paid API requests, or chat sends."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import client as c
import postprocess as pp
from PIL import Image

THREAD='12345678-1234-4234-8234-123456789abc'
JID='cfp_'+'a'*24
SVG=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 120"><rect x="10" y="10" width="50" height="50" fill="#3498db"/><path d="M80 10 L150 10 L150 70 L80 70Z M95 25 L95 55 L135 55 L135 25Z" fill="#dd7744" fill-rule="nonzero"/><text x="10" y="100" font-size="16" fill="#111111">Test</text></svg>'


class FakeAPI:
    def __init__(self):
        self.balance=40;self.account=17;self.submits=[];self.jobs={};self.lose=False
        self.body=SVG;self.digest=c.sha(SVG);self.downloads=0
    def me(self):
        return dict(id=self.account,role='customer',credits_available=self.balance,credits_per_task=20)
    def submit(self,payload):
        self.submits.append(payload)
        if payload['request_id'] not in self.jobs:
            self.balance-=20
            self.jobs[payload['request_id']]=dict(job_id=JID,charged_credits=20,status='queued')
        if self.lose:
            self.lose=False;raise TimeoutError('response lost')
        return self.jobs[payload['request_id']]
    def status(self,jid):
        return dict(job_id=jid,charged_credits=20,status='completed',sha256=self.digest)
    def download(self,jid):
        self.downloads+=1;return self.body


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.job=self.root/'job';self.img=self.root/'image.png'
        Image.new('RGB',(20,10),'white').save(self.img)
        self.api=FakeAPI()
        self.env=patch.dict(os.environ,{'CODEX_THREAD_ID':THREAD});self.env.start()
    def tearDown(self):
        self.env.stop();self.temp.cleanup()
    def prepare(self,**kw):
        args=dict(image=self.img,text='',application='ppt',thread_id=THREAD,credential_file=self.root/'never-read.key',
                  credits_approved=20,wake_authorized=True,api=self.api,registry=self.root/'registry')
        args.update(kw);return c.prepare(self.job,**args)
    def ready(self):
        self.prepare();c.submit_existing(self.job,self.api);return c.poll_once(self.job,self.api)
    def bridge(self,*,busy=False,uncertain=False,ack=False):
        outer=self
        class Bridge:
            sends=[]
            def __init__(self,**kw):
                outer.assertEqual(kw['submit_thread_ids'],[THREAD])
            def _desktop_tool(self,name,args):
                outer.assertEqual(name,'read_thread')
                return {'thread':{'id':THREAD,'status':{'type':'active' if busy else 'idle'}},'turns':[]}
            def submit(self,thread,prompt):
                self.sends.append((thread,prompt))
                if ack:c.acknowledge(outer.job,c.read(outer.job/'job.json')['wake_nonce'])
                if uncertain:raise TimeoutError()
                return {'queued':True,'thread_id':thread}
            def close(self):pass
        return Bridge
    def test_empty_input_rejected_before_network(self):
        with patch.object(self.api,'me',side_effect=AssertionError('network')):
            with self.assertRaises(c.ClientError):self.prepare(image=None)
    def test_text_only_retry_deducts_once_and_downloads(self):
        first=self.prepare(image=None,text='  Research description  ')
        self.assertIsNone(first['image'])
        self.assertFalse(list(self.job.glob('input.*')))
        self.api.lose=True
        with self.assertRaises(TimeoutError):c.submit_existing(self.job,self.api)
        state=c.submit_existing(self.job,self.api)
        self.assertEqual(state['state'],'waiting')
        self.assertEqual(self.api.balance,20)
        self.assertEqual([p['request_id'] for p in self.api.submits],[first['request_id']]*2)
        self.assertNotIn('image',self.api.submits[0])
        self.assertEqual(self.api.submits[0]['text'],'Research description')
        self.assertEqual(c.poll_once(self.job,self.api)['state'],'ready')
    def test_text_only_saved_text_tamper_rejected(self):
        self.prepare(image=None,text='Research description')
        (self.job/'requirements.txt').write_text('Changed',encoding='utf-8')
        with self.assertRaises(c.ClientError):c.submit_existing(self.job,self.api)
        self.assertFalse(self.api.submits)
    def test_text_does_not_hide_invalid_image(self):
        with patch.object(self.api,'me',side_effect=AssertionError('network')):
            with self.assertRaises(c.ClientError):self.prepare(image=self.root/'missing.png',text='Valid text')
            with self.assertRaises(c.ClientError):self.prepare(image=None,text='  ')
    def test_fake_extension_rejected(self):
        self.img.write_text('not an image')
        with self.assertRaises(c.ClientError):self.prepare()
    def test_text_optional_and_insufficient_balance(self):
        self.api.balance=19
        with self.assertRaises(c.ClientError):self.prepare()
        self.assertFalse((self.job/'job.json').exists());self.assertFalse(self.api.submits)
    def test_origin_and_authorization_required(self):
        for values in ({'thread_id':None},{'credits_approved':19},{'wake_authorized':False}):
            with self.subTest(values=values),self.assertRaises(c.ClientError):self.prepare(**values)
    def test_idempotency_response_loss_deducts_once(self):
        self.api.balance=20;first=self.prepare();self.api.lose=True
        with self.assertRaises(TimeoutError):c.submit_existing(self.job,self.api)
        self.assertEqual(c.read(self.job/'job.json')['state'],'submit_unknown')
        s=c.submit_existing(self.job,self.api)
        self.assertEqual(s['state'],'waiting');self.assertEqual(self.api.balance,0)
        self.assertEqual([x['request_id'] for x in self.api.submits],[first['request_id']]*2)
        c.submit_existing(self.job,self.api);self.assertEqual(len(self.api.submits),2)
    def test_reuse_directory_does_not_rebill(self):
        first=self.prepare();self.assertEqual(self.prepare()['request_id'],first['request_id'])
        with self.assertRaises(c.ClientError):self.prepare(text='different')
        self.assertEqual(len(c.read(self.root/'registry/registry.json')),1)
    def test_account_switch_prevents_submission(self):
        self.prepare();self.api.account=18
        with self.assertRaises(c.ClientError):c.submit_existing(self.job,self.api)
        self.assertFalse(self.api.submits)
    def test_saved_input_tamper_prevents_submission(self):
        s=self.prepare();Path(s['image']).write_bytes(b'changed')
        with self.assertRaises(c.ClientError):c.submit_existing(self.job,self.api)
        self.assertFalse(self.api.submits)
    def test_old_approved_pending_order_is_not_resubmitted(self):
        self.prepare()
        c.update(self.job,credits_approved=19,state='submit_unknown')
        state=c.submit_existing(self.job,self.api)
        self.assertEqual(state['state'],'attention')
        self.assertFalse(self.api.submits)

    def test_existing_historical_receipt_still_downloads(self):
        self.prepare();c.submit_existing(self.job,self.api)
        c.update(self.job,credits_approved=19,charged_credits=19)
        status=self.api.status
        self.api.status=lambda jid:{**status(jid),'charged_credits':19}
        self.assertEqual(c.poll_once(self.job,self.api)['state'],'ready')

    def test_download_checksum_rejected(self):
        self.prepare();c.submit_existing(self.job,self.api);self.api.body=b'wrong'
        with self.assertRaises(c.ClientError):c.poll_once(self.job,self.api)
        self.assertFalse((self.job/'result.svg').exists())
    def test_download_durable_and_not_repeated(self):
        s=self.ready();self.assertEqual(s['state'],'ready')
        c.poll_once(self.job,self.api);self.assertEqual(self.api.downloads,1)
        self.assertEqual((self.job/'result.svg').read_bytes(),SVG)
    def test_svg_active_and_raster_rejected(self):
        for part in ('<script/>','<image href="data:image/png;base64,AA"/>','<use href="https://example.org/a"/>','<path onclick="x"/>'):
            with self.subTest(part=part),self.assertRaises(c.ClientError):
                c.validate_svg(('<svg xmlns="http://www.w3.org/2000/svg">'+part+'</svg>').encode())
    def test_busy_origin_waits_then_notifies_once(self):
        self.ready();busy=self.bridge(busy=True);self.assertEqual(c.notify(self.job,busy)['state'],'ready')
        self.assertFalse(busy.sends)
        free=self.bridge();self.assertEqual(c.notify(self.job,free)['state'],'wake_sent')
        c.notify(self.job,free);self.assertEqual(len(free.sends),1)
    def test_uncertain_wake_does_not_duplicate(self):
        self.ready();bridge=self.bridge(uncertain=True)
        self.assertEqual(c.notify(self.job,bridge)['state'],'wake_uncertain')
        c.notify(self.job,bridge);self.assertEqual(len(bridge.sends),1)
    def test_fast_ack_not_overwritten(self):
        self.ready();bridge=self.bridge(ack=True)
        self.assertEqual(c.notify(self.job,bridge)['state'],'received')
    def test_wrong_chat_cannot_ack(self):
        s=self.ready()
        with patch.dict(os.environ,{'CODEX_THREAD_ID':'different'}),self.assertRaises(c.ClientError):
            c.acknowledge(self.job,s['wake_nonce'])
    def test_stopped_never_notifies_or_converts(self):
        self.ready();c.update(self.job,state='stopped',before_stop='ready');bridge=self.bridge()
        self.assertEqual(c.notify(self.job,bridge)['state'],'stopped');self.assertFalse(bridge.sends)
        self.assertEqual(c.update(self.job,state='ready')['state'],'stopped')
        with self.assertRaises(c.ClientError):pp.convert(self.job,file_only=True)
    def test_stop_twice_preserves_resume_state(self):
        self.ready()
        for _ in range(2):
            result=subprocess.run([sys.executable,str(c.SKILL/'scripts/client.py'),'stop','--job-dir',str(self.job)],capture_output=True)
            self.assertEqual(result.returncode,0,result.stdout)
        self.assertEqual(c.read(self.job/'job.json')['before_stop'],'ready')
    def test_cli_preserves_postprocess_error_message(self):
        self.ready();c.update(self.job,state='stopped')
        result=subprocess.run([sys.executable,'-X','utf8',str(c.SKILL/'scripts/client.py'),'convert','--job-dir',str(self.job)],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,1)
        self.assertIn('Task is stopped',json.loads(result.stdout)['error'])
    def test_unsupported_clip_keeps_actionable_failure(self):
        code='print("ERROR|Only redundant full-canvas clipping can be removed automatically");raise SystemExit(1)'
        with self.assertRaisesRegex(c.ClientError,'局部裁剪'):
            pp.run([sys.executable,'-c',code],self.root/'clip-test.log')
    def test_waiter_single_instance_and_recovery(self):
        self.prepare()
        with c.Lock(self.job/'waiter.lock'):
            self.assertEqual(c.start_waiter(self.job),{'already_running':True})
        with patch.object(c,'start_waiter') as start:
            c.recover(self.root/'registry');start.assert_called_once_with(str(self.job.resolve()))
    def test_waiter_persists_heartbeat_and_handles_stop(self):
        self.prepare()
        with patch.object(c,'poll_once',side_effect=lambda directory:c.update(directory,state='stopped')),patch.object(c.time,'sleep'):
            c.wait(self.job)
        self.assertEqual(c.read(self.job/'waiter.json')['pid'],os.getpid())
    def test_old_conversion_gets_new_output_and_preserves_original(self):
        self.ready()
        old=self.job/'editable/shibielujing1'
        old.mkdir(parents=True)
        original=old/'shibielujing1.pptx'
        original.write_bytes(b'old-layout-output')
        c.update(self.job,conversion_mode='direct-path-v1',conversion_name='shibielujing1')
        result=pp.convert(self.job,file_only=True)
        self.assertNotEqual(Path(result['native']),original)
        self.assertEqual(original.read_bytes(),b'old-layout-output')
        self.assertEqual(c.read(self.job/'job.json')['conversion_mode'],'bundled-native-v2')
        self.assertEqual(pp.dependency(),c.SKILL.parents[1]/'native/scripts')

    def test_native_ppt_conversion_and_resume(self):
        self.ready()
        try:result=pp.convert(self.job,file_only=True)
        except c.ClientError:self.fail((self.job/'conversion.log').read_text(encoding='utf-8'))
        self.assertGreaterEqual(result['native_shapes'],3)
        self.assertGreaterEqual(result['native_text_runs'],1)
        self.assertEqual((self.job/'result.svg').read_bytes(),SVG)
        with patch.object(pp,'run',side_effect=AssertionError('conversion should reuse output')):
            self.assertEqual(pp.convert(self.job,file_only=True)['native'],result['native'])
        with self.assertRaises(c.ClientError):pp.complete(self.job,visual_checked=False)
        (self.job/'result.svg').write_bytes(SVG+b' ')
        with self.assertRaises(c.ClientError):pp.complete(self.job,visual_checked=True)


class TransportTests(unittest.TestCase):
    def test_hardcoded_origin(self):
        with self.assertRaises(c.ClientError):c.API('none','https://elsewhere.example')
    def test_real_http_with_pinned_token_and_denied_redirect(self):
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                seen.append(self.headers.get('Authorization'))
                if self.path.endswith('/redirect'):
                    self.send_response(302);self.send_header('Location','http://127.0.0.1:1/leak');self.end_headers();return
                data=json.dumps(dict(id=1,role='customer',credits_available=20,credits_per_task=20)).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            api=c.API('fake','http://127.0.0.1:'+str(server.server_port),test_http=True)
            with patch.object(c,'read_token',side_effect=['unit_test_token','wrong_account']) as read_token:
                self.assertEqual(api.me()['credits_available'],20);api.me()
                with self.assertRaises(c.ClientError):api.call(c.PREFIX+'/redirect')
                self.assertEqual(read_token.call_count,1)
            self.assertEqual(seen,['Bearer unit_test_token']*3)
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
