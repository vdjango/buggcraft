"""Public launcher identity shared by catalogue, mirror and file requests."""

from pathlib import Path

from core.update_client import current_version


def _launcher_version():
    for parent in Path(__file__).resolve().parents:
        resources = parent / 'resources'
        if (resources / 'app-version.txt').is_file():
            return current_version(resources)
    return '0.0.0'


LAUNCHER_VERSION = _launcher_version()
USER_AGENT = f'BUGG | {LAUNCHER_VERSION}'
