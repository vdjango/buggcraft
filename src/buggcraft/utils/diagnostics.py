"""Persistent per-launch connection diagnostics and portable support archives."""
import atexit
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
from zipfile import ZipFile, ZIP_DEFLATED

_session_file = None
_log_root = None
_export_lock = threading.Lock()


def redact(text):
    text = str(text)
    text = re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer [REDACTED]', text)
    # Never persist SDP credentials or request credentials, even in tracebacks.
    text = re.sub(r'(?im)^(a=ice-pwd:).*$', r'\1[REDACTED]', text)
    text = re.sub(r'(?i)(\b(?:password|passwd|secret|access_token|refresh_token|token|api_key|x-api-key|authorization)\b[\s\"\x27]*[:=]\s*)(\"[^\"]*\"|\x27[^\x27]*\x27|[^\s,;}]+)',
                  r'\1[REDACTED]', text)
    return text


class SafeFormatter(logging.Formatter):
    def format(self, record):
        text = super().format(record)
        if record.name.endswith('rtcpeerconnection') and 'Description(' in record.getMessage():
            text = text.split('\n', 1)[0] + ' [SDP omitted]'
        return redact(text)


class ConnectionOnly(logging.Filter):
    def filter(self, record):
        return record.name.startswith(('hookup.', 'aioice', 'asyncssh'))


def configure_connection_logging(directory):
    global _session_file, _log_root
    _log_root = Path(directory).resolve()
    sessions = _log_root / 'p2p-sessions'
    sessions.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    _session_file = sessions / f'{stamp}-{os.getpid()}.log'
    handler = RotatingFileHandler(_session_file, maxBytes=10 * 1024 * 1024,
                                 backupCount=8, encoding='utf-8')
    handler.setLevel(logging.DEBUG)
    handler.addFilter(ConnectionOnly())
    handler.setFormatter(SafeFormatter('%(asctime)s %(levelname)s [%(threadName)s] %(name)s %(message)s'))
    logging.getLogger().addHandler(handler)
    for name in ('hookup.peer', 'hookup.relay', 'hookup._rtc.rtcpeerconnection',
                 'hookup._rtc.rtcicetransport', 'hookup._rtc.rtcdtlstransport', 'aioice'):
        logging.getLogger(name).setLevel(logging.DEBUG)
    # Packet-by-packet SCTP logging would add synchronous disk IO to game traffic.
    logging.getLogger('hookup._rtc.rtcsctptransport').setLevel(logging.INFO)
    logging.getLogger('hookup.peer').info('session_start id=%s platform=%s python=%s pid=%s',
                                        _session_file.stem, platform.platform(), platform.python_version(), os.getpid())
    atexit.register(lambda: logging.getLogger('hookup.peer').info('session_end id=%s', _session_file.stem))
    return _session_file


def connection_session_directory():
    return _session_file.parent if _session_file else None


def export_diagnostics(destination, directory=None):
    """Allowlist only logs; settings, tokens, profiles and game files stay out."""
    root = Path(directory or _log_root or os.environ.get('BUGGCRAFT_LOG_DIR') or Path.cwd()).resolve()
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Flush while connections are still active, without stopping their session.
    for handler in logging.getLogger().handlers:
        handler.flush()
    files = list(root.glob('buggcraft*.log*')) + list(root.glob('Buggcraft-install.log*'))
    sessions = root / 'p2p-sessions'
    if sessions.is_dir() and not sessions.is_symlink():
        files += list(sessions.glob('*.log*'))
        files += list(sessions.glob('network-*.json'))
    skipped = []
    total = 0
    with _export_lock, ZipFile(destination, 'w', compression=ZIP_DEFLATED, compresslevel=6) as archive:
        records = []
        for path in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
            if not path.is_file() or path.is_symlink() or path.resolve() == destination:
                continue
            size = path.stat().st_size
            if total + size > 200 * 1024 * 1024:
                skipped.append(path.relative_to(root).as_posix())
                continue
            data = redact(path.read_text(encoding='utf-8', errors='replace')).encode('utf-8')
            relative = path.relative_to(root).as_posix()
            archive.writestr(relative, data)
            records.append({'path': relative, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            total += size
        metadata = {'collected_utc': datetime.now(timezone.utc).isoformat(),
                    'platform': platform.platform(), 'python': platform.python_version(),
                    'session': _session_file.stem if _session_file else None,
                    'files': records, 'skipped_over_200_mib': skipped,
                    'notice': 'Network addresses and local paths are retained for troubleshooting; credentials are redacted.'}
        archive.writestr('diagnostics.json', json.dumps(metadata, ensure_ascii=False, indent=2))
    return destination
