"""Executable entry for the launcher-independent stdio bridge."""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import sys


def run():
    parser = argparse.ArgumentParser(description='Buggcraft JSON-RPC 2.0 bridge over stdio')
    parser.add_argument('--version', action='store_true', help='Print build information and exit')
    args = parser.parse_args()
    if args.version:
        from hookup.bridge import build_info
        print(json.dumps(build_info(), ensure_ascii=True))
        return 0
    # Credentials travel only in stdin; stdout must contain JSON-RPC frames.
    logging.basicConfig(level=logging.ERROR, stream=sys.stderr,
                        format='%(levelname)s %(name)s: %(message)s')
    if sys.stdin is None or sys.stdout is None:
        print('Start the bridge with redirected stdin and stdout.', file=sys.stderr)
        return 2
    if sys.platform == 'win32':
        import msvcrt
        import os
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    from hookup.bridge import main
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError, BrokenPipeError):
        return 0
    except Exception:
        # Protocol-specific errors are handled inside serve(); no request
        # contents or credentials belong in an unhandled-exception traceback.
        print('Bridge stopped after an internal failure.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(run())
