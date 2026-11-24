"""No model download: test the setup worker with small ZIP64-compatible fixtures."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import zipfile


def main(root):
    root.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).with_name('prepare_payload.ps1')
    (root / source.name).write_bytes(source.read_bytes())
    archive = root / 'fixture.zip'
    prefix = 'SomePhylloscopus-v0.1.0-Windows-NVIDIA/'
    entries = {'柳莺识别.exe': b'app', 'NVIDIA/runtime/pythonw.exe': b'python',
               'app/gui.py': b'# GUI', 'assets/plates/index.json': b'{}',
               'config/settings.json': b'{}', 'config/hero_gallery.json': b'{}',
               'models/test.bin': b'fixture' * 20000}
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(prefix + name, data)
    data = archive.read_bytes()
    sha = lambda b: hashlib.sha256(b).hexdigest()
    split = len(data) // 3
    parts = [data[:split], data[split:2*split], data[2*split:]]
    manifest = {'file': 'fixture.zip', 'bytes': len(data), 'sha256': sha(data),
                'parts': [{'file': f'fixture.zip.part{i+1:02}', 'bytes': len(b), 'sha256': sha(b)}
                          for i, b in enumerate(parts)]}
    (root / 'download-manifest.json').write_text(json.dumps(manifest), 'utf-8')
    results = []

    def run(name, source_zip='', source_parts='', cleanup=False, ok=True):
        work = root / (name + '.somephylloscopus-setup-v0.1.0')
        options = root / (name + '.txt')
        options.write_text(f'WorkDir={work}\nSourceZip={source_zip}\nSourceParts={source_parts}\n', 'utf-8-sig')
        cmd = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
               str(root / source.name), '-Options', str(options)]
        if cleanup:
            cmd.append('-Cleanup')
        p = subprocess.run(cmd, capture_output=True, timeout=60)
        (root / (name + ('.cleanup' if cleanup else '') + '.log')).write_bytes(p.stdout + p.stderr)
        assert (p.returncode == 0) == ok, (name, p.stdout, p.stderr)
        return work, p

    work, _ = run('offline 中文', archive)
    assert all((work / 'stage' / n).read_bytes() == b for n, b in entries.items())
    run('offline 中文', archive, cleanup=True)
    assert archive.read_bytes() == data and not work.exists()
    results.append('offline ZIP extraction, Unicode paths, cleanup preserves supplied ZIP')

    manual = root / 'manual-parts'; manual.mkdir()
    for item, b in zip(manifest['parts'], parts):
        (manual / item['file']).write_bytes(b)
    work, p = run('manual', source_parts=manual)
    assert b'Downloading' not in p.stdout
    assert (work / 'fixture.zip').read_bytes() == data
    assert all((manual / item['file']).read_bytes() == b for item, b in zip(manifest['parts'], parts))
    run('manual', source_parts=manual, cleanup=True)
    results.append('all existing fragments reused without network and preserved after cleanup')

    bad = root / 'bad.zip'; bad.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    work, _ = run('wrong-hash', bad, ok=False)
    assert not (work / 'stage').exists()
    results.append('wrong ZIP SHA256 rejected before extraction')

    work = root / 'unowned.somephylloscopus-setup-v0.1.0'; work.mkdir()
    sentinel = work / 'my-data'; sentinel.write_bytes(b'keep')
    run('unowned', archive, ok=False)
    assert sentinel.read_bytes() == b'keep'
    results.append('unowned cache directory refused without deleting files')

    evil = root / 'traversal.zip'
    with zipfile.ZipFile(evil, 'w') as z:
        z.writestr(prefix + '../escaped.txt', b'no')
    evil_data = evil.read_bytes()
    (root / 'download-manifest.json').write_text(json.dumps({'file':'traversal.zip','bytes':len(evil_data),'sha256':sha(evil_data),'parts':[]}), 'utf-8')
    work, _ = run('traversal', evil, ok=False)
    assert not (work / 'escaped.txt').exists()
    results.append('archive path traversal rejected')
    receipt = {'passed': True, 'cases': results, 'shell': 'Windows PowerShell 5.1'}
    (root / 'test-results.json').write_text(json.dumps(receipt, indent=2), 'utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--work', required=True, type=Path)
    main(p.parse_args().work)
