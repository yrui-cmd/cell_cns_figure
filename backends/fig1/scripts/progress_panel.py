"""Local, read-only task progress. Never contacts the task API or a model."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ESTIMATE = 3600


def snapshot(directory, now=None):
    from client import read
    directory = Path(directory)
    state = read(directory/'job.json')
    now = time.time() if now is None else now
    elapsed = max(0, now - state['created_at'])
    complete = False
    result = directory/'result.svg'
    expected = state.get('svg_sha256')
    # A remote "completed" status alone is insufficient: the local receiver
    # must have saved a verified receipt AND the matching file.
    if state.get('svg') and isinstance(expected, str) and len(expected) == 64 and result.is_file():
        complete = hashlib.sha256(result.read_bytes()).hexdigest() == expected
    if complete:
        elapsed = max(0, state.get('result_received_at', state.get('updated_at', now))-state['created_at'])
    stopped = state.get('state') == 'stopped'
    attention = state.get('state') == 'attention'
    label = ('结果已接收' if complete else '已暂停' if stopped else
             '需要处理' if attention else '等待结果返回' if elapsed >= ESTIMATE else '正在处理')
    return {'complete': complete, 'percent': 100 if complete else min(99, int(elapsed/ESTIMATE*100)),
            'elapsed': elapsed, 'estimate': ESTIMATE, 'label': label,
            'paused': stopped or attention, 'demo': bool(state.get('progress_demo'))}


def make_server(directory, token, port=0):
    directory = Path(directory)
    prefix = '/'+token
    page = Path(__file__).with_name('progress_panel.html').read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                self.send_error(403); return
            if self.path == prefix+'/':
                body, kind = page, 'text/html; charset=utf-8'
            elif self.path == prefix+'/status':
                try:
                    body = json.dumps(snapshot(directory), ensure_ascii=False).encode()
                except (OSError, ValueError, KeyError):
                    self.send_error(503); return
                kind = 'application/json; charset=utf-8'
            else:
                self.send_error(404); return
            self.server.last_access = time.monotonic()
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.last_access = time.monotonic()
    return server


def serve(directory):
    from client import Lock, read, write
    directory = Path(directory).resolve()
    with Lock(directory/'progress-server.lock'):
        meta = read(directory/'progress-panel.json')
        server = make_server(directory, meta['token'], meta.get('port', 0))
        meta.update(port=server.server_port, pid=os.getpid())
        meta['url'] = f'http://127.0.0.1:{server.server_port}/{meta["token"]}/'
        write(directory/'progress-panel.json', meta)
        server.timeout = 1
        try:
            # An open panel keeps its local server alive. Closed panels release
            # the process after a day and can be reopened with the progress command.
            while time.monotonic()-server.last_access < 86400:
                server.handle_request()
        finally:
            server.server_close()


def alive(meta):
    port = meta.get('port')
    token = meta.get('token')
    if not isinstance(port, int) or not 0 < port < 65536 or not isinstance(token, str):
        return False
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/{token}/status', timeout=.8) as response:
            return isinstance(json.load(response).get('complete'), bool)
    except Exception:
        return False


def start(directory):
    from client import Lock, read, write
    directory = Path(directory).resolve()
    if not (directory/'job.json').is_file():
        raise ValueError('No submitted task')
    path = directory/'progress-panel.json'
    with Lock(directory/'progress-start.lock', 10):
        meta = read(path) if path.exists() else {'token': secrets.token_hex(24)}
        if alive(meta):
            return meta['url']
        # Reuse the saved port and capability after process/app restarts so an
        # existing browser panel reconnects without a model turn.
        write(path, meta)
        exe = Path(sys.executable)
        if os.name == 'nt' and exe.with_name('pythonw.exe').exists():
            exe = exe.with_name('pythonw.exe')
        options = {'creationflags':subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session':True}
        with (directory/'progress-panel.log').open('ab') as log:
            process = subprocess.Popen([str(exe), '-X', 'utf8', str(Path(__file__).resolve()), '--serve', str(directory)],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True, **options)
        deadline = time.monotonic()+8
        while time.monotonic() < deadline:
            current = read(path)
            if alive(current):
                return current['url']
            if process.poll() is not None:
                break
            time.sleep(.15)
        raise RuntimeError('Local progress panel unavailable; task receiver remains independent')



def show(directory, *, force=False, bridge_factory=None):
    from client import Lock, read, write
    directory = Path(directory).resolve()
    url = start(directory)
    with Lock(directory/'progress-open.lock', 10):
        meta = read(directory/'progress-panel.json')
        if meta.get('opened') and not force:
            return {'progress_url':url,'progress_opened':True}
        state = read(directory/'job.json')
        if bridge_factory is None:
            from desktop_bridge import Bridge
            bridge_factory = Bridge
        bridge = bridge_factory(caller_thread_id=state['thread_id'], submit_thread_ids=[], panel_url=url)
        try:
            result = bridge._desktop_tool('open_in_codex',{'placement':'right','target':{'type':'browser','url':url}})
            if result.get('status') not in ('opened','queued','ok'):
                raise RuntimeError('Progress panel open was not acknowledged')
            if result.get('threadId',state['thread_id']) != state['thread_id']:
                raise RuntimeError('Progress panel belongs to another chat')
            meta.update(opened=True, opened_at=time.time())
            write(directory/'progress-panel.json',meta)
            return {'progress_url':url,'progress_opened':True}
        finally:
            bridge.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', type=Path, required=True)
    serve(parser.parse_args().serve)
