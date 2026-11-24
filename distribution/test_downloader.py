"""Exercise the real Windows CMD/PowerShell downloader against a local HTTP server."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from build_downloader import render


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main(root):
    root.mkdir(parents=True, exist_ok=True)
    payloads = {f'app.zip.part{i:02}': os.urandom(128 * 1024) for i in range(1, 4)}
    complete = b''.join(payloads.values())
    manifest = {'file': 'app.zip', 'bytes': len(complete), 'sha256': sha(complete),
                'parts': [{'file': name, 'bytes': len(data), 'sha256': sha(data)}
                          for name, data in payloads.items()]}
    calls = []
    state = {'drop': False, 'ignore_range': False, 'corrupt': False}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            name = self.path.rsplit('/', 1)[-1]
            if name not in payloads:
                self.send_error(404)
                return
            data = payloads[name]
            start = int(self.headers.get('Range', 'bytes=0-')[6:].split('-')[0])
            calls.append({'name': name, 'start': start})
            if state['ignore_range']:
                start = 0
            self.send_response(206 if start else 200)
            self.send_header('Content-Length', str(len(data) - start))
            if start:
                self.send_header('Content-Range', f'bytes {start}-{len(data)-1}/{len(data)}')
            self.end_headers()
            chunk = data[start:]
            if state['corrupt']:
                chunk = bytes([chunk[0] ^ 1]) + chunk[1:]
            try:
                if state['drop'] and name.endswith('03'):
                    self.wfile.write(chunk[:max(1, len(chunk) // 2)])
                    self.wfile.flush()
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                else:
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    outcomes = []

    def scenario(name):
        path = root / name
        path.mkdir(exist_ok=False)
        (path / 'Download.cmd').write_text(render(manifest, url), 'ascii', newline='\r\n')
        calls.clear()
        return path

    def run(path, success=True):
        result = subprocess.run(['cmd.exe', '/d', '/c', str(path / 'Download.cmd'), '--no-pause'],
                                capture_output=True, timeout=90)
        (path / 'run.log').open('ab').write(result.stdout + result.stderr)
        assert (result.returncode == 0) == success, (path.name, result.returncode, result.stdout[-3000:], result.stderr[-3000:])
        if success:
            assert (path / 'app.zip').read_bytes() == complete
        else:
            assert not (path / 'app.zip').exists()
        return result

    try:
        p = scenario('01 fresh 中文 path')
        run(p)
        assert len(calls) == 3
        calls.clear()
        run(p)
        assert not calls
        outcomes.append('fresh download and idempotent verified rerun')

        p = scenario('02 manual parts')
        for name, data in payloads.items():
            (p / name).write_bytes(data)
        run(p)
        assert not calls
        assert all((p / name).read_bytes() == data for name, data in payloads.items())
        outcomes.append('manual fragments reused offline and preserved')

        p = scenario('03 interrupted transfer')
        state['drop'] = True
        run(p, success=False)
        assert (p / 'app.zip.downloading').read_bytes() == complete[:256*1024]
        saved = (p / 'app.zip.part03.downloading').stat().st_size
        assert 0 < saved < 128*1024
        state['drop'] = False
        calls.clear()
        run(p)
        assert calls == [{'name': 'app.zip.part03', 'start': saved}], calls
        outcomes.append('network failure preserves verified prefix and resumes current part by Range')

        p = scenario('04 corrupted saved data')
        (p / 'app.zip.downloading').write_bytes(complete[:128*1024] + b'wrong' * 30000)
        (p / 'app.zip.part02.downloading').write_bytes(b'x' * (128*1024))
        (p / 'app.zip.part03').write_bytes(b'bad manual data')
        run(p)
        assert {x['name'] for x in calls} == {'app.zip.part02', 'app.zip.part03'}
        assert (p / 'app.zip.part03').read_bytes() == b'bad manual data'
        outcomes.append('corrupt saved segment and current part repaired without deleting manual data')

        p = scenario('05 server ignores range')
        (p / 'app.zip.part01.downloading').write_bytes(complete[:1000])
        state['ignore_range'] = True
        run(p)
        state['ignore_range'] = False
        assert calls[0]['start'] == 1000 and calls[1]['start'] == 0
        outcomes.append('server without Range restarts only current fragment')

        p = scenario('06 damaged server data')
        state['corrupt'] = True
        run(p, success=False)
        state['corrupt'] = False
        assert not (p / 'app.zip').exists()
        outcomes.append('bad SHA256 never produces final ZIP')

        p = scenario('07 exclusive download lock')
        # .NET file handle simulates another downloader owning the same assembly.
        lock_script = "$f=[IO.File]::Open($env:SP_LOCK,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None); Write-Output 'LOCKED'; Start-Sleep 30"
        lock = subprocess.Popen(['powershell.exe', '-NoProfile', '-Command', lock_script],
                                env={**os.environ, 'SP_LOCK': str(p / 'app.zip.downloading')}, stdout=subprocess.PIPE)
        try:
            assert b'LOCKED' in lock.stdout.readline()
            run(p, success=False)
            assert not calls
        finally:
            lock.terminate(); lock.wait()
        outcomes.append('concurrent downloader refuses exclusive file lock')
    finally:
        server.shutdown()
        server.server_close()
    result = {'passed': True, 'cases': outcomes, 'runtime': 'Windows CMD + Windows PowerShell 5.1 + system curl'}
    (root / 'test-results.json').write_text(json.dumps(result, indent=2), 'utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', type=Path, required=True)
    main(parser.parse_args().work)
