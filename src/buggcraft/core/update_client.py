"""Check and install signed-by-hash launcher packages from the Buggcraft service."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import uuid
import zipfile


UPDATE_API = 'https://download.bugg.icu/api/launcher/update'
DOWNLOAD_ORIGIN = 'https://download.bugg.icu'
MAX_PACKAGE_BYTES = 1_500_000_000
_VERSION = re.compile(r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$')


def parse_version(value):
    if not isinstance(value, str):
        return None
    match = _VERSION.fullmatch(value.removeprefix('v'))
    if not match:
        return None
    major, minor, patch, prerelease = match.groups()
    if prerelease:
        parts = prerelease.split('.')
        if any(not part or (part.isdigit() and len(part) > 1 and part.startswith('0')) for part in parts):
            return None
        prerelease = tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts)
    return int(major), int(minor), int(patch), prerelease


def version_key(value):
    parsed = parse_version(value)
    if parsed is None:
        raise ValueError('Invalid launcher version')
    major, minor, patch, prerelease = parsed
    return major, minor, patch, (1, ()) if prerelease is None else (0, prerelease)


def platform_id(system=None, machine=None):
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    if system == 'windows' and machine in ('amd64', 'x86_64', 'x64'):
        return 'windows-x64'
    if system == 'linux' and machine in ('amd64', 'x86_64', 'x64'):
        return 'linux-x86_64'
    if system == 'darwin' and machine in ('arm64', 'aarch64'):
        return 'macos-arm64'
    if system == 'darwin' and machine in ('x86_64', 'amd64', 'x64'):
        return 'macos-x86_64'
    return None


def _trusted_https_url(value):
    parsed = urllib.parse.urlparse(value)
    return parsed.scheme == 'https' and parsed.hostname == 'download.bugg.icu'


def check_for_update(current_version, channel='stable', target=None, timeout=8):
    """Return the published package for this installation, or None."""
    target = target or platform_id()
    if target is None:
        return None
    if channel not in ('stable', 'beta'):
        channel = 'stable'
    query = urllib.parse.urlencode({'current': current_version, 'platform': target, 'channel': channel})
    request = urllib.request.Request(
        UPDATE_API + '?' + query,
        headers={'Accept': 'application/json', 'User-Agent': 'Buggcraft-Launcher'},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if not _trusted_https_url(response.geturl()):
            raise ValueError('Update API redirected outside the trusted service')
        payload = json.loads(response.read(256 * 1024 + 1).decode('utf-8'))
    if len(json.dumps(payload)) > 256 * 1024 or payload.get('update_available') is not True:
        return None
    available = payload.get('version')
    if parse_version(available) is None or parse_version(current_version) is None:
        raise ValueError('Update service returned an invalid version')
    if version_key(available) <= version_key(current_version):
        return None
    asset = payload.get('asset')
    if (not isinstance(asset, dict) or not _trusted_https_url(asset.get('url', ''))
            or asset.get('platform') not in (None, target)
            or not isinstance(asset.get('size'), int) or not 0 < asset['size'] <= MAX_PACKAGE_BYTES
            or not re.fullmatch(r'[0-9a-f]{64}', asset.get('sha256', ''))):
        raise ValueError('Update service returned an unsafe package manifest')
    if target in ('macos-arm64', 'macos-x86_64'):
        if not asset.get('name', '').endswith('.zip'):
            raise ValueError('macOS update must be an application archive')
    elif target == 'windows-x64' and asset.get('name') != 'Buggcraft.exe':
        raise ValueError('Windows update must be the launcher executable')
    elif target == 'linux-x86_64' and asset.get('name') != 'Buggcraft':
        raise ValueError('Linux update must be the launcher executable')
    return payload


def current_version(resource_path):
    try:
        value = (Path(resource_path) / 'app-version.txt').read_text(encoding='ascii').strip()
    except OSError:
        return '0.0.0'
    return value if parse_version(value) else '0.0.0'


def download_update(update, directory, progress=None, timeout=30):
    asset = update['asset']
    if not _trusted_https_url(asset['url']):
        raise ValueError('Update URL is not trusted')
    target = Path(directory).resolve()
    target.mkdir(parents=True, exist_ok=True)
    suffix = '.zip' if asset['name'].endswith('.zip') else '.exe' if asset['name'].endswith('.exe') else ''
    destination = target / ('.buggcraft-update-' + uuid.uuid4().hex + suffix)
    request = urllib.request.Request(asset['url'], headers={'User-Agent': 'Buggcraft-Launcher'})
    digest, size = hashlib.sha256(), 0
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, destination.open('xb') as output:
            if not _trusted_https_url(response.geturl()):
                raise ValueError('Package download redirected outside the trusted service')
            length = response.headers.get('Content-Length')
            if length is not None and int(length) != asset['size']:
                raise ValueError('Package size does not match the release manifest')
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > asset['size'] or size > MAX_PACKAGE_BYTES:
                    raise ValueError('Package exceeded its published size')
                digest.update(chunk)
                output.write(chunk)
                if progress:
                    progress(size, asset['size'])
            output.flush()
            os.fsync(output.fileno())
        if size != asset['size'] or digest.hexdigest() != asset['sha256']:
            raise ValueError('Downloaded package failed size or SHA-256 verification')
        return destination
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def _spawn_windows_replacement(source, target, process_id):
    pids = [process_id]
    parent = os.environ.get('NUITKA_ONEFILE_PARENT', '')
    if parent.isdecimal() and int(parent) > 0 and int(parent) != process_id:
        import psutil
        if psutil.Process(process_id).ppid() == int(parent):
            pids.append(int(parent))
    payload = json.dumps({'source': str(source), 'target': str(target), 'pids': pids}, ensure_ascii=True)
    payload64 = __import__('base64').b64encode(payload.encode('utf-8')).decode('ascii')
    script = (
        "$ErrorActionPreference='Stop';"
        "$d=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + payload64 + "')) | ConvertFrom-Json;"
        "foreach($waitId in $d.pids){while(Get-Process -Id $waitId -ErrorAction SilentlyContinue){Start-Sleep -Milliseconds 300}};"
        "$backup=$d.target+'.backup-'+[Guid]::NewGuid().ToString('N');"
        "try{"
        "for($attempt=0;$attempt -lt 30;$attempt++){try{Move-Item -LiteralPath $d.target -Destination $backup;break}catch{if($attempt -eq 29){throw};Start-Sleep -Milliseconds 300}};"
        "Move-Item -LiteralPath $d.source -Destination $d.target;"
        "Start-Process -FilePath $d.target -WorkingDirectory (Split-Path -LiteralPath $d.target);"
        "Remove-Item -LiteralPath $backup -ErrorAction SilentlyContinue"
        "}catch{if(Test-Path -LiteralPath $backup){Move-Item -LiteralPath $backup -Destination $d.target -Force};"
        "$_ | Out-String | Set-Content -LiteralPath ($d.target+'.update-error.log') -Encoding UTF8}"
    )
    encoded = __import__('base64').b64encode(script.encode('utf-16le')).decode('ascii')
    flags = getattr(subprocess, 'DETACHED_PROCESS', 0x00000008) | getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    flags |= getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x00000200)
    subprocess.Popen(['powershell.exe', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
                      '-EncodedCommand', encoded], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags, env=_replacement_environment())


def _replacement_environment():
    # A detached replacement must start as a fresh onefile parent process.
    return {key: value for key, value in os.environ.items() if not key.startswith('NUITKA_')}


def _mac_bundle_path(executable):
    for parent in Path(executable).resolve().parents:
        if parent.suffix == '.app':
            return parent
    raise ValueError('Could not locate the running Buggcraft.app')


def _spawn_macos_replacement(archive, target, process_id):
    with zipfile.ZipFile(archive) as package:
        roots, app_roots = set(), set()
        for member in package.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or '..' in path.parts or not path.parts:
                raise ValueError('macOS update archive contains an unsafe path')
            roots.add(path.parts[0])
            if path.parts[0].endswith('.app'):
                app_roots.add(path.parts[0])
        if len(app_roots) != 1 or roots - app_roots - {'__MACOSX'}:
            raise ValueError('macOS update archive must contain one application bundle')
        bundle_name = next(iter(app_roots))
    stage = target.parent / ('.buggcraft-update-' + uuid.uuid4().hex)
    staged_bundle = stage / bundle_name
    backup = target.parent / ('.buggcraft-backup-' + uuid.uuid4().hex + '.app')
    script = '\n'.join((
        'set -eu',
        f'while kill -0 {int(process_id)} 2>/dev/null; do sleep 0.3; done',
        f'mkdir -m 700 {shlex.quote(str(stage))}',
        f'/usr/bin/ditto -x -k {shlex.quote(str(archive))} {shlex.quote(str(stage))}',
        f'test -d {shlex.quote(str(staged_bundle))}',
        f'mv {shlex.quote(str(target))} {shlex.quote(str(backup))}',
            f'if ! mv {shlex.quote(str(staged_bundle))} {shlex.quote(str(target))}; then mv {shlex.quote(str(backup))} {shlex.quote(str(target))}; exit 1; fi',
        f'/usr/bin/open {shlex.quote(str(target))}',
        f'/bin/rm -rf {shlex.quote(str(backup))} {shlex.quote(str(stage))} {shlex.quote(str(archive))}',
    ))
    subprocess.Popen(['/bin/sh', '-c', script], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True, env=_replacement_environment())


def apply_update(package, executable=None):
    """Schedule a verified update and let the OS restart the launcher."""
    target_platform = platform_id()
    executable = Path(executable or sys.argv[0]).resolve()
    if target_platform == 'windows-x64':
        if package.suffix != '.exe' or not executable.is_file():
            raise ValueError('Windows update executable is missing')
        _spawn_windows_replacement(package, executable, os.getpid())
        return 'scheduled'
    if target_platform == 'linux-x86_64':
        if package.suffix or not executable.is_file():
            raise ValueError('Linux update executable is missing')
        mode = executable.stat().st_mode
        os.chmod(package, mode | 0o755)
        os.replace(package, executable)
        os.execve(str(executable), [str(executable), *sys.argv[1:]], _replacement_environment())
    if target_platform in ('macos-arm64', 'macos-x86_64'):
        if package.suffix != '.zip':
            raise ValueError('macOS update archive is missing')
        _spawn_macos_replacement(package, _mac_bundle_path(executable), os.getpid())
        return 'scheduled'
    raise ValueError('This system does not have a supported Buggcraft update package')
