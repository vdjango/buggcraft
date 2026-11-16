"""Read-only verification of the actual GitHub and download-site release bytes."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
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
    assert release['prerelease'], 'The desktop release must remain a test release'
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
        assert executable.startswith(b'MZ')
        if 'Buggcraft.exe' in archive.namelist():
            assert archive.read('Buggcraft.exe') == executable
        if version == '2.0.1':
            assert archive.read('Bugg-v1.1.0.exe') == executable
    executable_hash = hashlib.sha256(executable).hexdigest()
    platforms = {'windows-x64': bundle_hash}
    # Older releases can contain Windows alone; verify every native platform
    # actually published by the shared packager, including its executable mode.
    for desktop in release['assets']:
        match = re.fullmatch(r'Bugg-native-((?:macos|linux)-(?:arm64|x86_64))\.zip', desktop['name'])
        if not match:
            continue
        platform = match[1]
        with urlopen(desktop['browser_download_url'], timeout=180) as response:
            data = response.read(desktop['size'] + 1)
        digest = hashlib.sha256(data).hexdigest()
        assert len(data) == desktop['size'] and desktop['digest'] == 'sha256:' + digest
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            assert json.loads(archive.read('bugg-update.json')) == {'format': 1, 'version': version, 'platform': platform}
            entry = 'Bugg.app/Contents/MacOS/bugg' if platform.startswith('macos-') else 'bugg'
            if entry not in archive.namelist() and platform.startswith('macos-'):
                entry = 'Contents/MacOS/bugg'
            assert archive.getinfo(entry).external_attr >> 16 & 0o111
            bridge = str(PurePosixPath(entry).parent / 'native/bin/buggcraft-bridge')
            assert archive.getinfo(bridge).external_attr >> 16 & 0o111
        platforms[platform] = digest
    deadline = time.monotonic() + 20 * 60
    while True:
        with urlopen(f'https://download.bugg.icu/api/launcher/update?platform=windows-x64&runtime=cpp&current=1.1.0&channel=beta', timeout=45) as response:
            feed = json.load(response)
        if feed.get('version') == version and feed.get('update_available'):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('Download website did not publish the expected release')
        print('Waiting for download website publication', flush=True)
        time.sleep(15)
    feeds = {}
    for runtime, current, channel in [('legacy', '1.0.2-alpha.4', 'beta'),
                                       ('cpp', '1.1.0', 'stable'), ('cpp', '1.1.0', 'beta'),
                                       ('cpp', version, 'beta'), ('cpp', version, 'stable')]:
        url = f'https://download.bugg.icu/api/launcher/update?platform=windows-x64&runtime={runtime}&current={current}&channel={channel}'
        with urlopen(url, timeout=45) as response:
            feed = json.load(response)
        if channel == 'beta' and current != version:
            assert feed['update_available'] and feed['version'] == version
            assert feed['asset']['sha256'] == (executable_hash if runtime == 'legacy' else bundle_hash)
        elif channel == 'beta':
            assert not feed['update_available']
        elif current == version:
            assert not feed['update_available']
        elif feed['update_available']:
            assert feed['version'] != version and feed.get('channel') == 'stable'
        feeds[f'{runtime}_{current}_{channel}'] = feed
    for platform, digest in platforms.items():
        for current, channel in [('1.1.0', 'stable'), ('1.1.0', 'beta'),
                                 (version, 'beta'), (version, 'stable')]:
            url = f'https://download.bugg.icu/api/launcher/update?platform={platform}&runtime=cpp&current={current}&channel={channel}'
            with urlopen(url, timeout=45) as response:
                feed = json.load(response)
            if channel == 'beta' and current != version:
                assert feed['update_available']
                assert feed['version'] == version and feed['asset']['sha256'] == digest
                # The release owner trims surrounding whitespace on import.
                assert feed['notes'] == release['body'].strip()
                # Check the actual download route as well as feed metadata.
                with urlopen(Request(feed['asset']['url'], headers={'Range': 'bytes=0-3'}), timeout=60) as response:
                    assert response.status in (200, 206) and response.read(4) == b'PK\x03\x04'
            elif current == version or channel == 'beta':
                assert not feed['update_available']
            elif feed['update_available']:
                assert feed['version'] != version and feed.get('channel') == 'stable'
            feeds[f'{platform}_{current}_{channel}'] = feed
    releases_url = 'https://download.bugg.icu/api/launcher/releases'
    with urlopen(releases_url, timeout=45) as response:
        history = json.load(response)
    previous = next((row for row in history['releases'] if row['tag_name'] == 'v2.0.2'), None)
    assert previous, 'Previously downloaded release v2.0.2 disappeared from website history'
    old_mac = next(item for item in previous['assets'] if item['name'] == 'Buggcraft-macos-arm64.zip')
    with urlopen(Request(old_mac['browser_download_url'], headers={'Range': 'bytes=0-3'}), timeout=60) as response:
        assert response.status in (200, 206) and response.read(4) == b'PK\x03\x04'
    args.output.write_text(json.dumps({'version': version, 'release': release['html_url'],
                                       'bundle_sha256': bundle_hash, 'executable_sha256': executable_hash,
                                       'platforms': platforms, 'feeds': feeds}, indent=2) + '\n', encoding='utf-8')
    print('Verified published launcher, legacy migration and native update channels:', version)


if __name__ == '__main__':
    main()
