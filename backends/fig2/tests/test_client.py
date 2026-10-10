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
JID='fgp_'+'a'*24
SVG=b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 120"><rect x="10" y="10" width="50" height="50" fill="#3498db"/><path d="M80 10 L150 10 L150 70 L80 70Z M95 25 L95 55 L135 55 L135 25Z" fill="#dd7744" fill-rule="nonzero"/><text x="10" y="100" font-size="16" fill="#111111">Test</text></svg>'


class FakeAPI:
    def __init__(self):
        self.balance=90;self.account=17;self.submits=[];self.jobs={};self.lose=False
        self.body=SVG;self.digest=c.sha(SVG);self.downloads=0
    def me(self):
        return dict(id=self.account,role='customer',credits_available=self.balance,credits_per_task=45)
    def submit(self,payload):
        self.submits.append(payload)
        if payload['request_id'] not in self.jobs:
            self.balance-=45
            self.jobs[payload['request_id']]=dict(job_id=JID,charged_credits=45,status='queued')
        if self.lose:
            self.lose=False;raise TimeoutError('response lost')
        return self.jobs[payload['request_id']]
    def status(self,jid):
        return dict(job_id=jid,charged_credits=45,status='completed',sha256=self.digest)
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
        args=dict(image=self.img,text='',application='svg',thread_id=THREAD,credential_file=self.root/'never-read.key',
                  credits_approved=45,wake_authorized=True,api=self.api,registry=self.root/'registry')
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
    def test_fake_extension_rejected(self):
        self.img.write_text('not an image')
        with self.assertRaises(c.ClientError):self.prepare()
    def test_text_only_roundtrip_and_original_chat_handoff(self):
        self.prepare(image=None,text='客户科研文字',application='ai')
        c.submit_existing(self.job,self.api)
        self.assertIsNone(self.api.submits[0]['image'])
        self.assertEqual(self.api.submits[0]['text'],'客户科研文字')
        self.assertEqual(self.api.balance,45)
        result=c.poll_once(self.job,self.api)
        self.assertEqual(result['state'],'ready')
        self.assertEqual(result['application'],'ai')
        bridge=self.bridge()
        c.notify(self.job,bridge)
        self.assertEqual(bridge.sends[0][0],THREAD)
        self.assertIn('cell_cns_fig2',bridge.sends[0][1])
    def test_image_and_text_are_both_preserved(self):
        import base64
        self.prepare(text='图文一起提交')
        c.submit_existing(self.job,self.api)
        sent=self.api.submits[0]
        self.assertEqual(sent['text'],'图文一起提交')
        self.assertEqual(base64.b64decode(sent['image']['base64']),self.img.read_bytes())
        self.assertEqual(self.api.balance,45)
    def test_text_only_unknown_submit_does_not_rebill(self):
        self.prepare(image=None,text='纯文字任务')
        self.api.lose=True
        with self.assertRaises(TimeoutError):c.submit_existing(self.job,self.api)
        c.submit_existing(self.job,self.api)
        self.assertEqual(self.api.balance,45)
        self.assertEqual(len(self.api.jobs),1)
    def test_cli_empty_input_does_not_register_recovery(self):
        import contextlib,io
        args=['client.py','submit','--application','svg','--job-dir',str(self.job),
              '--credits-approved','45','--authorize-wake']
        with patch.object(sys,'argv',args),patch.object(c,'install_recovery') as install, \
             patch.object(c,'API') as api,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(c.main(),1)
        install.assert_not_called();api.assert_not_called()
        self.assertFalse(self.job.exists())
    def test_other_service_directory_rejected_before_network(self):
        self.prepare()
        state=c.read(self.job/'job.json');state['service']='/api/cell-figure-plus'
        c.write(self.job/'job.json',state)
        with patch.object(self.api,'me',side_effect=AssertionError('network')):
            with self.assertRaises(c.ClientError):c.submit_existing(self.job,self.api)
        with self.assertRaises(c.ClientError):pp.convert(self.job,file_only=True)
    def test_resume_after_attention_retains_order_and_can_receive(self):
        self.prepare();original=c.submit_existing(self.job,self.api)
        c.update(self.job,state='attention',last_error='HTTP:401')
        c.acknowledge(self.job,original['wake_nonce'])
        with patch.object(c,'start_waiter',return_value={'pid':123}) as start:
            self.assertEqual(c.resume_job(self.job)['state'],'waiting')
        start.assert_called_once()
        resumed=c.read_job(self.job)
        for field in ('request_id','job_id','account_id'):
            self.assertEqual(resumed[field],original[field])
        self.assertNotEqual(resumed['wake_nonce'],original['wake_nonce'])
        self.assertEqual(c.poll_once(self.job,self.api)['state'],'ready')
        bridge=self.bridge();c.notify(self.job,bridge)
        self.assertEqual(len(bridge.sends),1)
        self.assertEqual(len(self.api.submits),1)
    def test_resume_uncertain_wake_requires_reconciliation(self):
        self.ready();c.update(self.job,state='wake_uncertain',wake_state='uncertain')
        with patch.object(c,'start_waiter') as start:
            self.assertEqual(c.resume_job(self.job)['next_action'],'inspect_original_chat_and_acknowledge')
        start.assert_not_called()
    def test_resume_stopped_conversion_uses_saved_svg(self):
        self.ready();c.update(self.job,state='stopped',before_stop='received')
        with patch.object(c,'start_waiter') as start:
            self.assertEqual(c.resume_job(self.job)['next_action'],'export_existing_svg')
        start.assert_not_called()
        self.assertEqual(c.read_job(self.job)['state'],'received')
    def test_text_optional_and_insufficient_balance(self):
        self.api.balance=44
        with self.assertRaises(c.ClientError):self.prepare()
        self.assertFalse((self.job/'job.json').exists());self.assertFalse(self.api.submits)
    def test_origin_and_authorization_required(self):
        for values in ({'thread_id':None},{'credits_approved':18},{'wake_authorized':False}):
            with self.subTest(values=values),self.assertRaises(c.ClientError):self.prepare(**values)
    def test_idempotency_response_loss_deducts_once(self):
        self.api.balance=45;first=self.prepare();self.api.lose=True
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
    def test_new_ppt_submission_rejected_before_network(self):
        with patch.object(self.api, 'me', side_effect=AssertionError('network')):
            with self.assertRaises(c.ClientError):
                self.prepare(application='ppt')

    def test_legacy_ppt_returns_svg_without_desktop_or_resubmission(self):
        self.ready()
        c.update(self.job, application='ppt', conversion_mode='bundled-direct-v6')
        original = self.job/'editable/old.pptx'
        original.parent.mkdir(); original.write_bytes(b'old-output')
        with patch.object(pp.subprocess, 'run', side_effect=AssertionError('desktop must not start')):
            result = pp.convert(self.job, file_only=True)
            delivered = pp.complete(self.job, visual_checked=True)
        self.assertEqual(result['svg'], delivered['svg'])
        self.assertTrue(result['svg'].endswith('.svg'))
        self.assertEqual(original.read_bytes(), b'old-output')
        self.assertEqual((self.job/'result.svg').read_bytes(), SVG)
        self.assertEqual(len(self.api.submits), 1)

    def test_gradients_clipping_and_nested_coordinates_remain_unchanged(self):
        self.ready()
        source = self.job/'result.svg'
        data = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600"><defs><radialGradient id="g"><stop stop-color="#336699"/><stop offset="1" stop-color="#fff"/></radialGradient><clipPath id="c"><circle cx="5" cy="5" r="4"/></clipPath><marker id="a" markerWidth="5" markerHeight="5"><path d="M0 0L5 2L0 5Z"/></marker></defs><svg x="300" y="200" width="100" height="100" viewBox="0 0 10 10"><g transform="rotate(10 5 5)" clip-path="url(#c)"><rect width="10" height="10" fill="url(#g)"/><path d="M1 1L8 8" marker-end="url(#a)"/></g></svg></svg>'
        source.write_bytes(data); c.update(self.job, svg_sha256=c.sha(data))
        result = pp.export_svg(self.job)
        self.assertEqual(Path(result['svg']).read_bytes(), data)
        self.assertEqual(source.read_bytes(), data)

    def test_default_font_and_user_override_survive_resume(self):
        import xml.etree.ElementTree as ET
        self.ready()
        first = pp.export_svg(self.job)
        def text_node(path):
            return next(n for n in ET.parse(path).getroot().iter() if n.tag.endswith('}text'))
        self.assertEqual(text_node(first['svg']).get('font-family'), 'Times New Roman')
        custom = pp.export_svg(self.job, font_family='Calibri')
        self.assertNotEqual(first['svg'], custom['svg'])
        node = text_node(custom['svg'])
        self.assertEqual(node.get('font-family'), 'Calibri')
        self.assertEqual((node.get('x'),node.get('y'),node.get('font-size')), ('10','100','16'))
        self.assertEqual(pp.export_svg(self.job)['svg'], custom['svg'])
        self.assertEqual((self.job/'result.svg').read_bytes(), SVG)

    def test_changed_source_or_output_prevents_completion(self):
        self.ready()
        result = pp.export_svg(self.job)
        with self.assertRaises(c.ClientError):
            pp.complete(self.job, visual_checked=False)
        original = Path(result['svg']).read_bytes()
        Path(result['svg']).write_bytes(original+b' ')
        with self.assertRaises(c.ClientError):
            pp.complete(self.job, visual_checked=True)
        Path(result['svg']).write_bytes(original)
        (self.job/'result.svg').write_bytes(SVG+b' ')
        with self.assertRaises(c.ClientError):
            pp.complete(self.job, visual_checked=True)

    def test_adobe_import_requires_choice_and_matching_receipt(self):
        self.ready(); result = pp.export_svg(self.job)
        with self.assertRaises(c.ClientError):
            pp.import_illustrator(self.job)
        c.update(self.job, application='ai')
        with self.assertRaises(c.ClientError):
            pp.complete(self.job, visual_checked=True)
        receipt = subprocess.CompletedProcess([], 0, json.dumps({'opened':True, 'path':result['svg'], 'reused':False}), '')
        with patch.object(pp.subprocess, 'run', return_value=receipt) as run:
            if os.name == 'nt':
                imported = pp.import_illustrator(self.job)
                self.assertTrue(imported['opened'])
                self.assertIn('import_illustrator.ps1', ' '.join(run.call_args.args[0]))
                pp.complete(self.job, visual_checked=True)
                self.assertEqual(c.read(self.job/'job.json')['state'], 'delivered')

    def test_import_failure_keeps_svg_and_does_not_mark_delivered(self):
        self.ready(); c.update(self.job, application='ai')
        result = pp.export_svg(self.job)
        with patch.object(pp.subprocess, 'run', side_effect=OSError('unavailable')):
            with self.assertRaises(c.ClientError):
                pp.import_illustrator(self.job)
        self.assertTrue(Path(result['svg']).is_file())
        self.assertNotEqual(c.read(self.job/'job.json')['state'], 'delivered')



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
                data=json.dumps(dict(id=1,role='customer',credits_available=45,credits_per_task=45)).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            api=c.API('fake','http://127.0.0.1:'+str(server.server_port),test_http=True)
            with patch.object(c,'read_token',side_effect=['unit_test_token','wrong_account']) as read_token:
                self.assertEqual(api.me()['credits_available'],45);api.me()
                with self.assertRaises(c.ClientError):api.call(c.PREFIX+'/redirect')
                self.assertEqual(read_token.call_count,1)
            self.assertEqual(seen,['Bearer unit_test_token']*3)
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
