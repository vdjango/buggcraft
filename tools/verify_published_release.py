"""Read-only verification of the actual GitHub and download-site release bytes."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', args.tag):
        raise ValueError('Invalid release tag')
    version = args.tag[1:]
    api = 'https://api.github.com/repos/vdjango/buggcraft/releases/tags/' + args.tag
    request = Request(api, headers={'User-Agent': 'Bugg-public-release-verification',
                                    'Authorization': 'Bearer ' + os.environ['GH_TOKEN']})
    with urlopen(request, timeout=45) as response:
        release = json.load(response)
    assert not release['draft'], 'GitHub release is still a draft'
    asset = next(a for a in release['assets'] if a['name'] == 'Bugg-native-windows-x64.zip')
    assert asset['browser_download_url'].startswith('https://github.com/vdjango/buggcraft/releases/download/')
    with urlopen(asset['browser_download_url'], timeout=120) as response:
        bundle = response.read(asset['size'] + 1)
    assert len(bundle) == asset['size']
    bundle_hash = hashlib.sha256(bundle).hexdigest()
    assert asset['digest'] == 'sha256:' + bundle_hash
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        assert json.loads(archive.read('bugg-update.json')) == {'format': 1, 'version': version, 'platform': 'windows-x64'}
        executable = archive.read('bugg.exe')
        assert executable.startswith(b'MZ') and archive.read('Buggcraft.exe') == executable
        if version == '2.0.1':
            assert archive.read('Bugg-v1.1.0.exe') == executable
    executable_hash = hashlib.sha256(executable).hexdigest()
    deadline = time.monotonic() + 20 * 60
    while True:
        with urlopen('https://download.bugg.icu/api/launcher/update?platform=windows-x64&runtime=cpp&current=1.1.0&channel=stable', timeout=45) as response:
            feed = json.load(response)
        if feed.get('version') == version and feed.get('update_available'):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('Download website did not publish the expected release')
        print('Waiting for download website publication', flush=True)
        time.sleep(15)
    feeds = {}
    for runtime, current, channel in [('legacy', '1.0.2-alpha.4', 'stable'), ('cpp', '1.1.0', 'stable'),
                                       ('cpp', '1.1.0', 'beta'), ('cpp', version, 'beta')]:
        url = f'https://download.bugg.icu/api/launcher/update?platform=windows-x64&runtime={runtime}&current={current}&channel={channel}'
        with urlopen(url, timeout=45) as response:
            feed = json.load(response)
        assert feed['update_available'] == (current != version)
        if current != version:
            assert feed['version'] == version
            assert feed['asset']['sha256'] == (executable_hash if runtime == 'legacy' else bundle_hash)
        feeds[f'{runtime}_{current}_{channel}'] = feed
    args.output.write_text(json.dumps({'version': version, 'release': release['html_url'],
                                       'bundle_sha256': bundle_hash, 'executable_sha256': executable_hash,
                                       'feeds': feeds}, indent=2) + '\n', encoding='utf-8')
    print('Verified published launcher, legacy migration and native update channels:', version)


if __name__ == '__main__':
    main()
