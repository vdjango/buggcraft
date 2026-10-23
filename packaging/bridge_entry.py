"""Legacy command alias for the C++ executable; no protocol code lives here."""
import os
import sys
import subprocess
from hookup.native_routes import executable

def run():
    binary = executable()
    if binary is None:
        raise FileNotFoundError('The native multiplayer bridge is not installed')
    if os.name != 'nt':
        os.execv(binary, [binary, *sys.argv[1:]])
    raise SystemExit(subprocess.call([binary, *sys.argv[1:]]))

if __name__ == '__main__':
    run()
