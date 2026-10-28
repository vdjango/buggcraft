"""Persistent per-launch connection diagnostics and portable support archives."""
import atexit
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import re
import sys
import threading
import secrets
import gzip
import time
from zipfile import ZipFile, ZIP_DEFLATED

_session_file = None
_log_root = None
_export_lock = threading.Lock()
RETENTION_DAYS = 7
SESSION_BUDGET = 128 * 1024 * 1024


def prune_connection_logs(root, *, now=None, max_bytes=SESSION_BUDGET):
    """Bound previous launches and network snapshots; never remove other files."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        return
    now = time.time() if now is None else now
    files = sorted((path for path in root.iterdir() if not path.is_symlink() and path.is_file()
                    and (re.fullmatch(r'.+\.log(?:\.\d+)?', path.name)
                         or re.fullmatch(r'network-[A-Za-z0-9_-]+\.json', path.name))),
                   key=lambda path: path.stat().st_mtime)
    total = sum(path.stat().st_size for path in files)
    for path in files:
        if _session_file is not None and (path == _session_file or path.name.startswith(_session_file.name + '.')):
            continue
        stat = path.stat()
        if stat.st_mtime < now - RETENTION_DAYS * 86400 or total > max_bytes:
            path.unlink()
            total -= stat.st_size


def redact(text):
    text = str(text)
    text = re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer [REDACTED]', text)
    text = re.sub(r'(?i)(--(?:accessToken|clientToken|xuid)\s+)("[^"]*"|\x27[^\x27]*\x27|\S+)', r'\1[REDACTED]', text)
    # Never persist SDP credentials or request credentials, even in tracebacks.
    text = re.sub(r'(?im)^(a=ice-pwd:).*$', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)(\b(?:password|passwd|secret|access_token|refresh_token|token|api_key|x-api-key|authorization)\b[\s\"\x27]*[:=]\s*)(\"[^\"]*\"|\x27[^\x27]*\x27|[^\s,;}]+)',
                  r'\1[REDACTED]', text)
    return text


def redact_structure(value):
    if isinstance(value, dict):
        return {key: ('[REDACTED]' if re.fullmatch(r'(?i)(?:password|passwd|secret|access_token|refresh_token|token|api_key|x-api-key|authorization)', str(key))
                      else redact_structure(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_structure(item) for item in value]
    return redact(value) if isinstance(value, str) else value


class SafeFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


class ConnectionOnly(logging.Filter):
    def filter(self, record):
        return record.name.startswith('hookup.')


def configure_connection_logging(directory):
    global _session_file, _log_root
    _log_root = Path(directory).resolve()
    os.environ['BUGGCRAFT_BRIDGE_LOG_DIR'] = str(_log_root / 'players')
    sessions = _log_root / 'p2p-sessions'
    sessions.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    _session_file = sessions / f'{stamp}-{os.getpid()}.log'
    try:
        prune_connection_logs(sessions)
    except OSError as error:
        logging.getLogger('hookup.native_routes').warning('connection_journal_cleanup_failed error=%s', type(error).__name__)
    handler = RotatingFileHandler(_session_file, maxBytes=10 * 1024 * 1024,
                                 backupCount=8, encoding='utf-8')
    handler.setLevel(logging.DEBUG)
    handler.addFilter(ConnectionOnly())
    handler.setFormatter(SafeFormatter('%(asctime)s %(levelname)s [%(threadName)s] %(name)s %(message)s'))
    logging.getLogger().addHandler(handler)
    for name in ('hookup.social', 'hookup.native_routes', 'hookup.native_transport',
                 'hookup.rooms', 'hookup.network_diagnostics'):
        logging.getLogger(name).setLevel(logging.DEBUG)
    logging.getLogger('hookup.native_routes').info('session_start id=%s platform=%s python=%s pid=%s',
                                        _session_file.stem, platform.platform(), platform.python_version(), os.getpid())
    atexit.register(lambda: logging.getLogger('hookup.native_routes').info('session_end id=%s', _session_file.stem))
    return _session_file


def connection_session_directory():
    return _session_file.parent if _session_file else None


async def export_connection_diagnostics(destination):
    from hookup.native_routes import diagnostic_snapshot
    native = await diagnostic_snapshot()
    return await asyncio.to_thread(export_diagnostics, destination, native_diagnostics=native)


def export_diagnostics(destination, directory=None, game_directory=None, java_path=None, *, native_diagnostics=None):
    """Collect fresh routes and allowlisted game/launcher logs, without settings or worlds."""
    from utils.http_identity import LAUNCHER_VERSION
    root = Path(directory or _log_root or os.environ.get('BUGGCRAFT_LOG_DIR') or Path.cwd()).resolve()
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Flush while connections are still active, without stopping their session.
    for handler in logging.getLogger().handlers:
        handler.flush()
    collection_errors = []
    network = {'status': 'failed'}
    try:
        from utils.network_diagnostics import capture_network
        snapshot = capture_network(root / 'p2p-sessions', 'export-' + secrets.token_hex(8))
        network = {'status': 'collected', 'trace_id': snapshot['trace_id'],
                   'route_error': snapshot.get('route_error'),
                   'interfaces_error': snapshot.get('interfaces_error')}
    except Exception as error:
        network['error'] = type(error).__name__ + ': ' + redact(error)
    selected_game = {}
    missing_game_logs = []
    if game_directory is None and directory is None:
        try:
            import config.settings as settings
            manager = settings._settings_manager_instance
            if manager is not None:
                game_directory = manager.get_minecraft_isolation_directory()
                selected_game = {'version': manager.get_setting('minecraft.version.enable'),
                                 'java_path': manager.get_version_setting('java.path')}
                java_path = java_path or selected_game['java_path']
        except Exception as error:
            collection_errors.append({'component': 'game-selection', 'error': type(error).__name__})
    files = list(root.glob('buggcraft*.log*')) + list(root.glob('Buggcraft-install.log*'))
    sessions = root / 'p2p-sessions'
    if sessions.is_dir() and not sessions.is_symlink():
        files += list(sessions.glob('*.log*'))
        files += list(sessions.glob('network-*.json'))
    sources = [(path, path.relative_to(root).as_posix()) for path in files]
    player_logs = root / 'players'
    if player_logs.is_dir() and not player_logs.is_symlink():
        # Native bridge records only bounded metadata. Keep each player's directory
        # in the support archive so host-side streams can be correlated separately.
        for player in player_logs.iterdir():
            if player.is_symlink() or not player.is_dir() or not re.fullmatch(r'[A-Za-z0-9_-]{1,90}', player.name):
                continue
            sources.extend((path, path.relative_to(root).as_posix())
                           for path in player.glob('*.jsonl') if not path.is_symlink())
    inventory = None
    if game_directory:
        game_root = Path(game_directory).resolve()
        selected_game['directory'] = str(game_root)
        selected_game['directory_exists'] = game_root.is_dir()
        try:
            from utils.game_diagnostics import game_inventory
            inventory = game_inventory(game_root, java_path, selected_game.get('version'))
        except Exception as error:
            collection_errors.append({'component': 'game-inventory', 'error': type(error).__name__})
        for name in ('latest.log', 'debug.log'):
            path = game_root / 'logs' / name
            relative = 'game/logs/' + name
            sources.append((path, relative))
            if not path.is_file():
                missing_game_logs.append(relative)
        logs = game_root / 'logs'
        if logs.is_dir() and not logs.is_symlink():
            rotated = [path for path in logs.iterdir() if path.name not in ('latest.log', 'debug.log')
                       and path.is_file() and not path.is_symlink()
                       and (path.name.endswith(('.log', '.log.gz')) or re.fullmatch(r'(?:latest|debug)\.log\.\d+(?:\.gz)?', path.name))]
            sources.extend((path, 'game/logs/' + path.name) for path in sorted(rotated, key=lambda path: path.stat().st_mtime, reverse=True)[:20])
        crash_root = game_root / 'crash-reports'
        if crash_root.is_dir() and not crash_root.is_symlink():
            crashes = sorted(crash_root.glob('*.txt'), key=lambda path: path.stat().st_mtime, reverse=True)[:5]
            sources.extend((path, 'game/crash-reports/' + path.name) for path in crashes)
        for pattern in ('hs_err_pid*.log', 'replay_pid*.log'):
            crashes = sorted(game_root.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)[:5]
            sources.extend((path, 'game/jvm/' + path.name) for path in crashes)
    available = []
    for path, relative in sources:
        try:
            if path.is_file() and not path.is_symlink() and path.resolve() != destination:
                available.append((path.stat().st_mtime, path, relative))
        except OSError as error:
            collection_errors.append({'path': relative, 'error': type(error).__name__})
    skipped = []
    total = 0
    with _export_lock, ZipFile(destination, 'w', compression=ZIP_DEFLATED, compresslevel=6) as archive:
        records = []
        from utils.p2p_evidence import summarize_player_logs
        summary = summarize_player_logs(path for _, path, relative in
            sorted(available, key=lambda item: item[0], reverse=True) if relative.startswith('players/'))
        data = json.dumps(redact_structure(summary), ensure_ascii=False, indent=2).encode('utf-8')
        archive.writestr('p2p-evidence.json', data)
        records.append({'path': 'p2p-evidence.json', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        if inventory is not None:
            data = json.dumps(redact_structure(inventory), ensure_ascii=False, indent=2).encode('utf-8')
            archive.writestr('game/inventory.json', data)
            records.append({'path': 'game/inventory.json', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        # Incident files and the active Python session precede bulk samples/game logs.
        def priority(item):
            at, path, relative = item
            return ('.events.' in path.name, path == _session_file, relative.startswith('p2p-sessions/'), at)
        for _, path, relative in sorted(available, key=priority, reverse=True):
            try:
                size = path.stat().st_size
                if total + size > 200 * 1024 * 1024:
                    skipped.append(relative)
                    continue
                if relative.startswith('game/logs/') and path.name.endswith('.gz'):
                    with gzip.open(path, 'rb') as stream:
                        raw = stream.read(32 * 1024 * 1024 + 1)
                    if len(raw) > 32 * 1024 * 1024:
                        collection_errors.append({'path': relative, 'error': 'Compressed log exceeds 32 MiB expanded limit'})
                        continue
                    relative += '.decompressed.log'
                    data = redact(raw.decode('utf-8', errors='replace')).encode('utf-8')
                else:
                    data = redact(path.read_text(encoding='utf-8', errors='replace')).encode('utf-8')
                if total + len(data) > 200 * 1024 * 1024:
                    skipped.append(relative)
                    continue
            except (OSError, EOFError) as error:
                collection_errors.append({'path': relative, 'error': type(error).__name__})
                continue
            archive.writestr(relative, data)
            records.append({'path': relative, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            total += len(data)
        metadata = {'collected_utc': datetime.now(timezone.utc).isoformat(),
                    'launcher_version': LAUNCHER_VERSION, 'diagnostic_schema': 2,
                    'platform': platform.platform(), 'python': platform.python_version(),
                    'session': _session_file.stem if _session_file else None,
                    'native_journal': native_diagnostics or {'status': 'not_requested', 'flushed': False},
                    'retention': {'days': RETENTION_DAYS, 'python_session_max_bytes': SESSION_BUDGET,
                                  'native_max_bytes': 256 * 1024 * 1024,
                                  'critical_events_reserved_fraction': 0.25},
                    'files': records, 'skipped_over_200_mib': skipped,
                    'network_collection': network, 'selected_game': selected_game,
                    'missing_game_logs': missing_game_logs,
                    'collection_errors': collection_errors,
                    'notice': 'Network addresses and local paths are retained for troubleshooting; credentials are redacted.'}
        archive.writestr('diagnostics.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    return destination
