import sys
import os
from pathlib import Path



def get_launcher_directory():
    """Return the deployed launcher location, independent of its working directory."""
    configured = os.environ.get('BUGGCRAFT_LAUNCHER_DIR')
    if configured:
        return Path(configured).expanduser().resolve()
    if getattr(sys, 'frozen', False) or '__compiled__' in globals():
        # Nuitka onefile keeps the outer executable in argv[0].
        executable = Path(sys.argv[0] if '__compiled__' in globals() else sys.executable).resolve()
        for parent in executable.parents:
            if parent.suffix.lower() == '.app':
                return parent.parent
        return executable.parent
    # Source launches use the project directory, never src/buggcraft or the IDE cwd.
    return Path(__file__).resolve().parents[3]


def get_default_minecraft_dir():
    return get_launcher_directory() / '.minecraft'
