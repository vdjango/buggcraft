"""Compatibility command that replaces itself with the native stdio bridge."""
import os
import asyncio
import subprocess
from .native_routes import executable

async def main():
    binary = executable()
    if binary is None:
        raise FileNotFoundError('The C++ multiplayer bridge is not installed')
    if os.name != 'nt':
        os.execv(binary, [binary])
    # Windows execv exits the wrapper before the native child has finished.
    # Keep ownership of its pipes and lifetime for CLI callers and test tools.
    process = await asyncio.create_subprocess_exec(
        binary, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        status = await process.wait()
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()
    if status:
        raise SystemExit(status)
