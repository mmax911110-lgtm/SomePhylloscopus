"""Render the self-contained Windows downloader; requires only Python to build."""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_URL = 'https://github.com/mmax911110-lgtm/SomePhylloscopus/releases/download/v0.1.0'


def render(manifest, base_url=BASE_URL):
    template = (HERE / 'downloader-template.cmd').read_text('ascii')
    return template.replace('__MANIFEST__', json.dumps(manifest, indent=2)).replace('__BASE_URL__', base_url)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=HERE / 'Download-Windows-NVIDIA.cmd')
    args = parser.parse_args()
    manifest = json.loads((HERE / 'download-manifest.json').read_text('utf-8'))
    args.output.write_text(render(manifest), encoding='ascii', newline='\r\n')
    print(args.output)
